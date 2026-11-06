"""``score_document`` and the wider ``score_archive_block`` (plan D7, spec §3, §3.1).

``score_document`` must return the sandbox's ``score_extraction_row`` payload byte for
byte (plus ``scorer``). ``score_archive_block`` keeps every key it had before 0.27.0 and
gains ``headline_score``, ``headline_metric``, ``unlabeled_fields``, ``entity_list_f1``
and ``scorer``.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest
from conftest import load_script
from test_sandbox_schema_adherence import GoldenSchemaLookup

import llm_dojo_scoring as dojo
from llm_dojo_scoring import score_document
from llm_dojo_scoring.scoring.doc_scorers.correspondence import CONTENT_KEYS
from llm_dojo_scoring.scoring.extraction_scope import scope_extraction_pair
from llm_dojo_scoring.scoring.suites import suite_for_doc_type
from llm_dojo_scoring.pipeline.archive import (
    ARCHIVE_SCORING_KEYS,
    ARCHIVE_SCORING_POST_V021_KEYS,
    ARCHIVE_SCORING_V027_KEYS,
    empty_archive_scoring_block,
    score_archive_block,
)

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"
CASES = {c["case_id"]: c for c in json.loads((FIXTURES / "inputs.json").read_text())["cases"]}
GOLDENS = json.loads((FIXTURES / "goldens.json").read_text())["cases"]
BEFORE = json.loads((FIXTURES / "archive_block_before.json").read_text())["cases"]
SIGNATURES = json.loads((FIXTURES / "corpus_eda_signatures.json").read_text())
to_jsonable = load_script("capture_sandbox_goldens").to_jsonable

SCORABLE = sorted(k for k, g in GOLDENS.items() if "error" not in g["payload"])
BAD_PAYLOAD = sorted(k for k, g in GOLDENS.items() if "error" in g["payload"])
BLOCKS = sorted(k for k, b in BEFORE.items() if "error" not in b)
BENCHMARK = sorted(k for k in SCORABLE if "suite_overall_extraction_score" in GOLDENS[k]["payload"])


def _document(case_id: str) -> dict:
    """``score_document`` on one case with the recorded mailroom model facts."""
    case = CASES[case_id]
    return score_document(
        case["doc_type"],
        case["predicted"],
        case["expected"],
        doc_text=case.get("doc_text"),
        doc_subclass=case.get("doc_subclass"),
        expected_subclass=case.get("expected_subclass"),
        schema_lookup=GoldenSchemaLookup(GOLDENS[case_id]),
    )


def _block(case_id: str, **extra) -> dict:
    """``score_archive_block`` on one case, as the snapshot was taken."""
    case = CASES[case_id]
    return score_archive_block(
        case["doc_type"],
        case["predicted"],
        case["expected"],
        doc_text=case.get("doc_text"),
        expected_subclass=case.get("expected_subclass"),
        **extra,
    )


#: Deliberate departure from the sandbox (0.27.0): a null prediction is a parse error,
#: not an adherent empty payload. Field scoring still treats it as empty.
NULL_PREDICTION_ADHERENCE = {
    "parse_error": True,
    "parse_failure_reason": "null_payload",
    "schema_valid": False,
    "schema_adherence": 0.0,
}


#: Extras the suites compute for ``suite.score`` callers, which the sandbox dropped and
#: 0.27.0 reports on the payload (never folded into ``overall_extraction_score``).
_SUITE_EXTRA_KEYS = {
    "correspondence": CONTENT_KEYS,
    "insurance_claim": ("determination_consistency", "amount_exactness"),
}


def _suite_extras(case_id: str) -> dict:
    """The type extras as the class suite itself computes them (an independent oracle)."""
    case = CASES[case_id]
    keys = _SUITE_EXTRA_KEYS.get(case["doc_type"])
    predicted = case["predicted"] if isinstance(case["predicted"], dict) else {}
    if not keys or not case["expected"]:
        return {}
    pred, exp = scope_extraction_pair(case["doc_type"], predicted, case["expected"])
    sub = case.get("doc_subclass") or case.get("expected_subclass") or "other"
    result = suite_for_doc_type(case["doc_type"]).score(
        exp, pred, doc_text=case.get("doc_text"), detailed=True, doc_subclass=sub
    )
    return {k: result[k] for k in keys if k in result}


def _expected_payload(case_id: str) -> dict:
    """The sandbox golden with the documented 0.27.0 departures applied.

    Adherence comes from the D2 goldens, which the sandbox recorded on the prediction as
    given (so foreign keys count and a null prediction is a parse error); the type extras
    come from the class suite.
    """
    golden = GOLDENS[case_id]
    payload = dict(golden["payload"])
    payload.update(golden["adherence"])
    payload.update(to_jsonable(_suite_extras(case_id)))
    return payload


@pytest.mark.parametrize("case_id", SCORABLE)
def test_score_document_matches_goldens(case_id):
    """Every scorable case reproduces the sandbox payload (plus the documented departures)."""
    got = to_jsonable(_document(case_id))
    scorer = got.pop("scorer")
    assert got == _expected_payload(case_id)
    assert scorer["doc_type"] == CASES[case_id]["doc_type"]
    assert scorer["tiers_run"][0] == "common"


@pytest.mark.parametrize("case_id", SCORABLE)
def test_field_scores_identical_to_sandbox(case_id):
    """The departures touch adherence and add extras; every sandbox score is unchanged."""
    got = to_jsonable(_document(case_id))
    golden = GOLDENS[case_id]
    adherence = set(golden["adherence"]) | {"extra_schema_key_count", "recovered_from_raw"}
    for key, value in golden["payload"].items():
        if key not in adherence:
            assert got[key] == value, key


def test_type_extras_are_reported():
    """Topic/sentiment and claims consistency reach the payload (the sandbox dropped them)."""
    topic = _document("correspondence__email__topic_sentiment_gt_match")
    assert topic["content_topic_accuracy"] == 1.0 and topic["sentiment_accuracy"] == 1.0
    claim = _document("insurance_claim__auto__partial")
    assert "determination_consistency" in claim and "amount_exactness" in claim


def test_extras_never_change_headline():
    """Extras sit beside the score; ``overall_extraction_score`` is the sandbox's."""
    case_id = "correspondence__memo__topic_sentiment_gt_mismatch"
    got = _document(case_id)
    assert got["overall_extraction_score"] == GOLDENS[case_id]["payload"]["overall_extraction_score"]


def test_adherence_reports_foreign_keys():
    """A merger prediction carrying CUAD keys reports them as extra schema keys."""
    got = _document("merger_agreement__other__mixed")
    assert {"cuad_clauses", "cuad_family"} <= set(got["extra_schema_keys"])


NULL_CASES = sorted(k for k in SCORABLE if CASES[k]["predicted"] is None)


@pytest.mark.parametrize("case_id", NULL_CASES)
def test_null_prediction_is_parse_error(case_id):
    """A ``None`` prediction is not adherent; its field scores match an empty extraction."""
    got = _document(case_id)
    for key, value in NULL_PREDICTION_ADHERENCE.items():
        assert got[key] == value
    golden = GOLDENS[case_id]["payload"]
    assert got["overall_extraction_score"] == golden["overall_extraction_score"]


def test_null_cases_exist():
    """The goldens cover null predictions, so the departure is exercised."""
    assert len(NULL_CASES) >= 3


@pytest.mark.parametrize("case_id", BAD_PAYLOAD)
def test_score_document_never_raises_on_bad_payload(case_id):
    """Where the sandbox raised on a str/list prediction, the dojo reports adherence instead."""
    got = _document(case_id)
    case = CASES[case_id]
    assert got["doc_type"] == case["doc_type"]
    assert set(GOLDENS[case_id]["adherence"]) <= set(got)
    assert got["schema_adherence"] in (0.0, 1.0)


@pytest.mark.parametrize("predicted", [None, 42, b"\xff", "no json here", ["a"], {"_parse_error": True}])
def test_score_document_odd_inputs(predicted):
    """Arbitrary junk is data, not an exception."""
    got = score_document("contract", predicted, {"parties": ["A"]})
    assert got["parse_error"] is True or got["schema_adherence"] in (0.0, 1.0)
    assert "overall_extraction_score" in got


def test_score_document_scorer_names_module():
    """``scorer`` says which module ran and which tiers."""
    got = _document(BENCHMARK[0])
    assert got["scorer"]["module"].startswith("llm_dojo_scoring.scoring.doc_scorers.")
    assert got["scorer"]["tiers_run"] == ["common", "type", "subclass"] or got["scorer"]["tiers_run"][:2] == [
        "common",
        "type",
    ]
    generic = score_document("memo_pad", {"a": 1}, {"a": 1})
    assert generic["scorer"]["module"].endswith(".generic")


@pytest.mark.parametrize("case_id", BLOCKS)
@pytest.mark.parametrize("with_subclass", [False, True])
def test_archive_block_existing_keys_unchanged(case_id, with_subclass):
    """Every pre-0.27 key keeps its value, with or without ``doc_subclass``."""
    extra = {"doc_subclass": CASES[case_id].get("doc_subclass")} if with_subclass else {}
    got = to_jsonable(_block(case_id, **extra))
    before = json.loads(json.dumps(BEFORE[case_id]))
    # ``scorer_version`` stamps the package version, which a release cut moves on purpose.
    assert got["provenance"].pop("scorer_version") == dojo.__version__
    before["provenance"].pop("scorer_version")
    assert {k: got[k] for k in before} == before


@pytest.mark.parametrize("case_id", BLOCKS)
def test_archive_block_new_keys(case_id):
    """The block carries the 0.27.0 keys, with ``provenance`` still last."""
    got = _block(case_id, doc_subclass=CASES[case_id].get("doc_subclass"))
    assert tuple(got) == ARCHIVE_SCORING_KEYS
    assert got["scorer"]["doc_type"] == CASES[case_id]["doc_type"]
    golden = GOLDENS[case_id]["payload"]
    if "error" not in golden:
        # 0.27.1: the keys follow the block's own verdict (no entity F1 when nothing is
        # countable, no unlabeled-field list when there is no ground truth at all).
        assert got["entity_list_f1"] == (golden.get("entity_list_f1") if got["extraction_f1"] is not None else None)
        assert got["unlabeled_fields"] == (None if got["reason"] == "gt_missing" else golden.get("unlabeled_fields"))


@pytest.mark.parametrize("case_id", sorted(k for k, b in BEFORE.items() if "error" in b))
def test_archive_block_never_raises_on_bad_payload(case_id):
    """Text, prose and list predictions get a block (coerced, else empty) instead of an exception."""
    got = _block(case_id, doc_subclass=CASES[case_id].get("doc_subclass"))
    assert tuple(got) == ARCHIVE_SCORING_KEYS
    assert got["status"] in ("scored", "unscorable")


@pytest.mark.parametrize("predicted", [None, 42, b"\xff", "no json here", ["a"], '{"parties": ["A"]}'])
def test_archive_block_odd_inputs(predicted):
    """Arbitrary junk is data, not an exception."""
    got = score_archive_block("contract", predicted, {"parties": ["A"]})
    assert tuple(got) == ARCHIVE_SCORING_KEYS


def test_archive_block_json_text_is_coerced():
    """A JSON object in text scores the same as the dict it holds."""
    expected = {"parties": ["A"]}
    as_text = score_archive_block("contract", '{"parties": ["A"]}', expected)
    as_dict = score_archive_block("contract", {"parties": ["A"]}, expected)
    assert as_text["overall_score"] == as_dict["overall_score"]
    assert as_text["field_scores"] == as_dict["field_scores"]


@pytest.mark.parametrize("case_id", BENCHMARK)
def test_archive_block_headline(case_id):
    """MAUD/CUAD rows: ``headline_score`` is the benchmark number; ``overall_score`` is untouched."""
    got = _block(case_id, doc_subclass=CASES[case_id].get("doc_subclass"))
    golden = GOLDENS[case_id]["payload"]
    assert got["headline_score"] == golden["overall_extraction_score"]
    assert got["headline_metric"] in ("maud_accuracy", "cuad_presence_f1")
    assert got["overall_score"] == BEFORE[case_id]["overall_score"]


def test_archive_block_no_headline_is_null():
    """Types without a headline rule leave both headline keys null."""
    case_id = next(k for k in BLOCKS if CASES[k]["doc_type"] == "insurance_claim")
    got = _block(case_id)
    assert got["headline_score"] is None and got["headline_metric"] is None


def test_no_gt_is_unscorable():
    """No ground truth: the block says why, and the new keys stay null."""
    case_id = "insurance_claim__property__no_ground_truth"
    got = _block(case_id, doc_subclass="property")
    assert got["status"] == BEFORE[case_id]["status"] == "unscorable"
    assert got["reason"] == "gt_missing"
    assert got["headline_score"] is None


def test_empty_block_and_legacy_rows():
    """The empty block has the new keys; legacy rows are not required to."""
    block = empty_archive_scoring_block()
    for key in ARCHIVE_SCORING_V027_KEYS:
        assert key in block
    assert not (ARCHIVE_SCORING_V027_KEYS & ARCHIVE_SCORING_POST_V021_KEYS)
    assert ARCHIVE_SCORING_KEYS[-1] == "provenance"


@pytest.mark.parametrize("qualname", sorted(SIGNATURES))
def test_corpus_eda_names_unchanged(qualname):
    """``gt_metadata`` and the ``corporate_record_*`` exports keep their signatures (spec §8)."""
    module, name = qualname.split(":")
    obj = getattr(importlib.import_module(module), name)
    if callable(obj) and not isinstance(obj, type):
        assert str(inspect.signature(obj)) == SIGNATURES[qualname]
    else:
        assert type(obj).__name__ == SIGNATURES[qualname]


def test_score_document_exported():
    """The dispatcher is public."""
    assert "score_document" in dojo.__all__


def test_json_after_braced_prose_is_recovered():
    """Prose with its own braces before the JSON object still yields the object (CodeAnt A)."""
    from llm_dojo_scoring.pipeline.sandbox_schema_adherence import coerce_predicted_payload

    payload, meta = coerce_predicted_payload('Note {see below}. Result: {"parties": ["A"]} done')
    assert payload == {"parties": ["A"]}
    assert meta["parse_error"] is False


@pytest.mark.parametrize("doc_type", ["contract", " Contract ", "CONTRACT", "contracts_specialist"])
def test_doc_type_spellings_score_alike(doc_type):
    """Case, padding and specialist aliases resolve to the canonical type before scoring (CodeAnt B)."""
    expected = {"parties": ["A"], "governing_law": "NY"}
    predicted = {"parties": ["A"], "governing_law": "NY", "claim_number": "X"}
    got = score_document(doc_type, predicted, expected)
    assert got["doc_type"] == "contract"
    assert got["scoring_method"] == "suite"
    assert got["scorer"]["module"].endswith(".contract")


@pytest.mark.parametrize(
    "doc_type, labels",
    [("merger_agreement", {"maud_clause_labels": "{}"}), ("contract", {"cuad_clause_labels": "{}"})],
)
def test_empty_benchmark_labels_keep_field_score(doc_type, labels):
    """An empty serialized label map gives no benchmark, so the field-map score stands (CodeAnt C)."""
    expected = {"parties": ["A"], **labels}
    got = score_document(doc_type, {"parties": ["A"]}, expected)
    assert got["overall_extraction_score"] is not None
    assert "+" not in got["scoring_method"]
    assert "suite_overall_extraction_score" not in got


def test_archive_block_custom_field_map_entity_f1():
    """With a caller's field map, ``entity_list_f1`` describes that map, not the default (CodeAnt D)."""
    ftypes = {"governing_law": "text"}  # no entity-list field in the caller's map
    exp = {"parties": ["A", "C"], "governing_law": "NY"}
    pred = {"parties": ["A", "B"], "governing_law": "NY"}
    block = score_archive_block("contract", pred, exp, field_types=ftypes)
    assert block["entity_list_f1"] is None
    default = score_archive_block("contract", pred, exp)
    assert default["entity_list_f1"] is not None
