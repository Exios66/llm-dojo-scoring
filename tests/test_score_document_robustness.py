"""0.27.1 review fixes: tier-1 guards, CMS derivation by ``doc_subclass``, block-status gating.

Network-free. Each section is one review finding (I1, I2, I3 of the 0.27.0 review).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import llm_dojo_scoring.scoring.doc_scorers.dispatch as dispatch_mod
from llm_dojo_scoring import score_document
from llm_dojo_scoring.pipeline.archive import score_archive_block
from llm_dojo_scoring.scoring.doc_scorers import get_doc_scorer
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

CASES = {
    c["case_id"]: c
    for c in json.loads((Path(__file__).parent / "fixtures" / "doc_scorers" / "inputs.json").read_text())["cases"]
}
CUAD = CASES["contract__license__cuad_labels_none_predicted"]
MAUD = CASES["merger_agreement__other__maud_labels_no_clause_keys"]
CUAD_LABELS = json.loads(CUAD["expected"]["cuad_clause_labels"]) if isinstance(
    CUAD["expected"]["cuad_clause_labels"], str
) else dict(CUAD["expected"]["cuad_clause_labels"])

#: Pre-0.27 keys of the block. Values below were produced by dojo 0.26.0.
OLD_KEYS = ("overall_score", "status", "reason", "n_fields_scored", "field_scores", "method", "extraction_f1")


def _labels(**override):
    """The CUAD fixture labels with some categories overridden."""
    out = dict(CUAD_LABELS)
    out.update(override)
    return out


# (id, doc_type, predicted, expected, 0.26.0 overall_score, 0.26.0 status)
I1_CASES = [
    ("cuad-clauses-true", "contract", {"cuad_clauses": True, "document_name": "MSA"}, CUAD["expected"], None, "unscorable"),
    ("cuad-clauses-int", "contract", {"cuad_clauses": 5, "document_name": "MSA"}, CUAD["expected"], None, "unscorable"),
    (
        "cuad-label-nan",
        "contract",
        {"document_name": "MSA"},
        {"cuad_clause_labels": _labels(**{"Governing Law": float("nan")}), "document_name": "MSA"},
        1.0,
        "scored",
    ),
    (
        "cuad-label-true",
        "contract",
        {"document_name": "MSA"},
        {"cuad_clause_labels": _labels(**{"Governing Law": True}), "document_name": "MSA"},
        1.0,
        "scored",
    ),
    (
        "topic-pred-list",
        "correspondence",
        {"sender": "a", "content_topic": ["legal", "hr"]},
        {"sender": "a", "content_topic": "legal"},
        1.0,
        "scored",
    ),
    (
        "topic-gold-list",
        "correspondence",
        {"sender": "a"},
        {"sender": "a", "content_topic": ["legal", "hr"]},
        1.0,
        "scored",
    ),
    (
        "topic-empty-dict",
        "correspondence",
        {"sender": "a", "content_topic": {}},
        {"sender": "a", "content_topic": "legal"},
        1.0,
        "scored",
    ),
    (
        "sentiment-list",
        "correspondence",
        {"sender": "a", "sentiment_label": ["x", "y"]},
        {"sender": "a", "sentiment_label": "neutral"},
        1.0,
        "scored",
    ),
]


@pytest.mark.parametrize("case", I1_CASES, ids=[c[0] for c in I1_CASES])
def test_score_document_survives_bad_field_values(case):
    """A bad field value inside a dict prediction never escapes ``score_document``."""
    _, doc_type, predicted, expected, _, _ = case
    payload = score_document(doc_type, predicted, expected)
    assert payload["scorer"]["doc_type"] == doc_type
    assert "overall_extraction_score" in payload


@pytest.mark.parametrize("case", I1_CASES, ids=[c[0] for c in I1_CASES])
def test_archive_block_survives_bad_field_values_and_keeps_026_scores(case):
    """The block does not raise, and its pre-0.27 field-map keys are what 0.26.0 produced."""
    _, doc_type, predicted, expected, overall_026, status_026 = case
    block = score_archive_block(doc_type, predicted, expected)
    assert block["overall_score"] == overall_026
    assert block["status"] == status_026
    assert block["scorer"] is not None


def test_failed_extras_are_marked_not_raised(monkeypatch):
    """A raising ``extras`` leaves tier 0 intact and marks ``scoring_method``."""
    scorer = get_doc_scorer("correspondence")

    def boom(*_a, **_k):
        """Always fails."""
        raise ValueError("extras exploded")

    monkeypatch.setattr(type(scorer), "extras", boom)
    broken = score_document("correspondence", {"sender": "a"}, {"sender": "a"})
    monkeypatch.undo()
    healthy = score_document("correspondence", {"sender": "a"}, {"sender": "a"})
    assert broken["scoring_method"] == f"{healthy['scoring_method']}+extras-failed"
    assert broken["overall_extraction_score"] == healthy["overall_extraction_score"] == 1.0


def test_failed_headline_is_marked_not_raised(monkeypatch):
    """A raising ``headline`` keeps the field-map score and marks ``scoring_method``."""
    scorer = get_doc_scorer("contract")

    def boom(*_a, **_k):
        """Always fails."""
        raise TypeError("headline exploded")

    monkeypatch.setattr(type(scorer), "headline", boom)
    payload = score_document("contract", {"document_name": "MSA"}, {"document_name": "MSA"})
    assert payload["scoring_method"].endswith("+extras-failed")
    assert payload["overall_extraction_score"] == 1.0
    assert "suite_overall_extraction_score" not in payload


def test_failure_warning_is_logged(monkeypatch):
    """The downgrade is logged like tier 0's, once per process and key."""
    seen = []
    monkeypatch.setattr(dispatch_mod, "_warn_once", lambda key, message, exc=None: seen.append(key))
    scorer = get_doc_scorer("correspondence")
    monkeypatch.setattr(type(scorer), "extras", lambda *a, **k: 1 / 0)
    score_document("correspondence", {"sender": "a"}, {"sender": "a"})
    assert seen == ["extras-failed-correspondence"]


def test_document_keys_failure_never_breaks_the_old_keys(monkeypatch):
    """If the tiered keys cannot be computed the pre-0.27 block keys are still returned."""
    expected = {"claim_number": "C1", "claimed_amount": "100.00"}
    healthy = score_archive_block("insurance_claim", expected, expected)

    def boom(*_a, **_k):
        """Always fails."""
        raise RuntimeError("document keys exploded")

    monkeypatch.setattr(dispatch_mod, "score_document", boom)
    block = score_archive_block("insurance_claim", expected, expected)
    for key in OLD_KEYS:
        assert block[key] == healthy[key]
    assert block["headline_score"] is None
    assert block["headline_metric"] is None
    assert block["unlabeled_fields"] is None
    assert block["entity_list_f1"] is None
    assert block["scorer"]["doc_type"] == "insurance_claim"


FUZZ_VALUES = [None, "", 0, 1.5, math.nan, True, [], {}, [None], [{}], {"a": [1]}, [1, 2], "x", ["a", "b"]]
EXTRA_LIVE = {
    "contract": ["cuad_clause_labels", "cuad_clauses"],
    "merger_agreement": ["maud_clause_labels", "maud_clauses"],
    "correspondence": ["content_topic", "sentiment_label"],
}
BASE = {"document_name": "X", "sender": "a", "claim_number": "C1", "entity_name": "E", "parties": ["A"]}


@pytest.mark.parametrize("doc_type", sorted(DEFAULT_FIELD_TYPES))
def test_odd_field_values_never_raise_either_entry_point(doc_type):
    """Every live field of every type, odd value on either side: neither entry point raises."""
    fields = list(DEFAULT_FIELD_TYPES[doc_type]) + EXTRA_LIVE.get(doc_type, [])
    for field in fields:
        for value in FUZZ_VALUES:
            for side in ("predicted", "expected"):
                pred, exp = dict(BASE), dict(BASE)
                (pred if side == "predicted" else exp)[field] = value
                where = f"{doc_type}.{field}={value!r} on {side}"
                try:
                    score_document(doc_type, pred, exp)
                    score_archive_block(doc_type, pred, exp)
                except Exception as exc:  # pragma: no cover - failure path
                    pytest.fail(f"{where}: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- I2: CMS by doc_subclass

CMS_EXPECTED = {
    "claim_number": "C1",
    "claimed_amount": "100.00",
    "coverage_determination": "approved",
    "insurer": "Medicare",
}
CMS_PREDICTED = {**CMS_EXPECTED, "cms_source_table": "outpatient"}


def test_doc_subclass_alone_derives_cms_table_in_block():
    """``doc_subclass`` stands in for ``expected_subclass`` when that is None (sandbox rule)."""
    via_doc = score_archive_block("insurance_claim", CMS_PREDICTED, CMS_EXPECTED, doc_subclass="inpatient")
    via_expected = score_archive_block("insurance_claim", CMS_PREDICTED, CMS_EXPECTED, expected_subclass="inpatient")
    document = score_document("insurance_claim", CMS_PREDICTED, CMS_EXPECTED, doc_subclass="inpatient")
    assert via_doc["method"] == via_expected["method"]
    assert "cms" in via_doc["method"]
    assert via_doc["field_scores"]["cms_source_table"] == 0.0
    assert via_doc["overall_score"] == pytest.approx(0.8)
    assert via_doc["overall_score"] == via_expected["overall_score"] == document["overall_extraction_score"]
    assert via_doc["field_scores"] == via_expected["field_scores"]
    assert via_doc["provenance"]["metric_id"] == via_expected["provenance"]["metric_id"]


def test_expected_subclass_still_wins_when_both_are_given():
    """Existing behaviour: ``expected_subclass`` decides the field-map CMS table."""
    both = score_archive_block(
        "insurance_claim", CMS_PREDICTED, CMS_EXPECTED, expected_subclass="outpatient", doc_subclass="inpatient"
    )
    expected_only = score_archive_block("insurance_claim", CMS_PREDICTED, CMS_EXPECTED, expected_subclass="outpatient")
    assert both["field_scores"] == expected_only["field_scores"]
    assert both["overall_score"] == expected_only["overall_score"] == 1.0


def test_non_cms_doc_subclass_leaves_the_field_map_alone():
    """A subclass that is not a CMS table changes nothing in the field map."""
    plain = score_archive_block("insurance_claim", CMS_PREDICTED, CMS_EXPECTED)
    other = score_archive_block("insurance_claim", CMS_PREDICTED, CMS_EXPECTED, doc_subclass="health")
    assert other["field_scores"] == plain["field_scores"]
    assert other["method"] == plain["method"]


def test_doc_subclass_on_non_insurance_leaves_the_field_map_alone():
    """Only insurance rows derive a table, whatever ``doc_subclass`` says."""
    expected = {"parties": ["A"], "document_name": "MSA"}
    plain = score_archive_block("contract", expected, expected)
    sub = score_archive_block("contract", expected, expected, doc_subclass="inpatient")
    for key in OLD_KEYS:
        assert sub[key] == plain[key]


# ---------------------------------------------------------------- I3: gating by block status


def test_corporate_extension_only_gt_has_no_entity_list_f1():
    """An unscorable block carries no entity-list F1 (the keys agree with ``status``)."""
    body = {"resolutions": ["Approve merger"]}
    block = score_archive_block("corporate_record", body, body, doc_subclass="board_resolution")
    assert block["status"] == "unscorable"
    assert block["reason"] == "gt_no_extractable_fields"
    assert block["extraction_f1"] is None
    assert block["entity_list_f1"] is None


def test_missing_gt_has_no_unlabeled_fields_or_entity_f1():
    """``expected=None`` is ``gt_missing``: no unlabeled-field list and no entity F1."""
    block = score_archive_block("corporate_record", {"entity_name": "Acme"}, None)
    assert block["status"] == "unscorable"
    assert block["reason"] == "gt_missing"
    assert block["unlabeled_fields"] is None
    assert block["entity_list_f1"] is None


def test_countable_corporate_block_keeps_its_keys():
    """A countable block still carries both keys."""
    block = score_archive_block(
        "corporate_record",
        {"entity_name": "Acme", "signatories": ["Bob"]},
        {"entity_name": "Acme", "signatories": ["Bob"]},
    )
    assert block["status"] == "scored"
    assert block["entity_list_f1"] is not None
    assert block["unlabeled_fields"] is not None


def test_maud_headline_row_keeps_status_but_headline_is_present():
    """Spec: ``status`` is unchanged for benchmark rows; the headline is what judges them."""
    block = score_archive_block("merger_agreement", MAUD["predicted"], MAUD["expected"])
    assert block["status"] == "unscorable"
    assert block["reason"] == "gt_no_extractable_fields"
    assert block["overall_score"] is None
    assert block["headline_score"] == 0.0
    assert block["headline_metric"] == "maud_accuracy"
    assert block["entity_list_f1"] is None
    assert block["extraction_f1"] is None


def test_cuad_headline_row_keeps_status_but_headline_is_present():
    """CUAD rows are judged by ``headline_score``; ``status`` stays the field-map verdict."""
    block = score_archive_block("contract", {"parties": ["A"]}, CUAD["expected"])
    assert block["headline_score"] is not None
    assert block["headline_metric"] == "cuad_presence_f1"
    if block["status"] != "scored":
        assert block["entity_list_f1"] is None
