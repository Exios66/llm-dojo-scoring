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


@pytest.mark.parametrize("case_id", SCORABLE)
def test_score_document_matches_goldens(case_id):
    """Every scorable case reproduces the sandbox payload exactly once ``scorer`` is removed."""
    got = to_jsonable(_document(case_id))
    scorer = got.pop("scorer")
    assert got == GOLDENS[case_id]["payload"]
    assert scorer["doc_type"] == CASES[case_id]["doc_type"]
    assert scorer["tiers_run"][0] == "common"


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
    before = BEFORE[case_id]
    assert {k: got[k] for k in before} == before


@pytest.mark.parametrize("case_id", BLOCKS)
def test_archive_block_new_keys(case_id):
    """The block carries the 0.27.0 keys, with ``provenance`` still last."""
    got = _block(case_id, doc_subclass=CASES[case_id].get("doc_subclass"))
    assert tuple(got) == ARCHIVE_SCORING_KEYS
    assert got["scorer"]["doc_type"] == CASES[case_id]["doc_type"]
    golden = GOLDENS[case_id]["payload"]
    if "error" not in golden:
        assert got["entity_list_f1"] == golden.get("entity_list_f1")
        assert got["unlabeled_fields"] == golden.get("unlabeled_fields")


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
