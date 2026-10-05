"""Live roster, field-map authority, and per-document specialist score surfaces.

Authority: ``Exios66/llm-mailroom@main`` ``src/config/taxonomy.yaml`` (git blob
``ca297bd8e55e62b79ee452b02b65926b5032bdf1``), pinned in
``tests/fixtures/taxonomy_field_types.json``. These tests fail loudly when the
dojo drifts from the live mailroom taxonomy or when a retired specialist
(compliance filing) creeps back into the live roster. Merger agreement is its
own class/specialist — never a contract alias.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_dojo_scoring.config import (
    DOC_CLASS_KEYS,
    LIVE_DOC_CLASS_KEYS,
    RETIRED_DOC_CLASS_KEYS,
)
from llm_dojo_scoring.corpus import CORPUS_EXTRACTION_FIELDS
from llm_dojo_scoring.field_scoring import ExtractionScoreResult
from llm_dojo_scoring.mailroom import (
    EXTRACT_CLASS_ALIASES,
    LIVE_DOC_TYPES,
    LIVE_SPECIALISTS,
    SORTER_LABEL_SET,
    is_live_extract_class,
    resolve_extract_class,
)
from llm_dojo_scoring.scorecard_honesty import (
    metric_id_allowed,
    metric_id_for,
    metric_ids_for_class,
)
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "taxonomy_field_types.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text())
_AUTHORITY_BLOB_SHA1 = "ca297bd8e55e62b79ee452b02b65926b5032bdf1"
_LIVE = tuple(_FIXTURE["live_doc_types"])
_SPECIALIST_FOR = {
    key: meta["specialist"] for key, meta in _FIXTURE["doc_classes"].items()
}

#: Minimal per-class (expected, predicted) pairs for the payload contract.
_SCORE_FIXTURES: dict[str, tuple[dict, dict]] = {
    "contract": ({"governing_law": "Delaware"}, {"governing_law": "Delaware"}),
    "merger_agreement": (
        {"effective_time": "9:00 a.m."},
        {"effective_time": "9:00 a.m."},
    ),
    "corporate_record": ({"entity_name": "Acme Corp"}, {"entity_name": "Acme Corp"}),
    "correspondence": ({"sender": "Alice"}, {"sender": "Alice"}),
    "insurance_claim": (
        {
            "claim_number": "CLM-1",
            "claimed_amount": 100.0,
            "coverage_determination": "approved",
            "denial_reasons": [],
        },
        {
            "claim_number": "CLM-1",
            "claimed_amount": 100.0,
            "coverage_determination": "approved",
            "denial_reasons": [],
        },
    ),
}


def test_authority_blob_pin_is_verified():
    assert _FIXTURE["authority_blob_sha1"] == _AUTHORITY_BLOB_SHA1
    assert _FIXTURE["authority"].endswith("src/config/taxonomy.yaml")


def test_live_doc_type_roster_matches_authority():
    assert tuple(LIVE_DOC_TYPES) == _LIVE
    assert _LIVE == (
        "contract",
        "merger_agreement",
        "corporate_record",
        "correspondence",
        "insurance_claim",
    )


@pytest.mark.parametrize("doc_type", _LIVE)
def test_live_field_map_matches_mailroom_taxonomy(doc_type):
    authority = _FIXTURE["doc_classes"][doc_type]
    assert DEFAULT_FIELD_TYPES[doc_type] == authority["field_types"]
    assert set(CORPUS_EXTRACTION_FIELDS[doc_type]) == set(authority["field_types"])


@pytest.mark.parametrize("doc_type", _LIVE)
def test_each_live_specialist_has_its_own_suite(doc_type):
    specialist = _SPECIALIST_FOR[doc_type]
    assert specialist in LIVE_SPECIALISTS
    suite = get_suite(specialist)
    assert suite.doc_type == doc_type
    assert suite.retired is False
    assert suite.field_types == _FIXTURE["doc_classes"][doc_type]["field_types"]
    # Doc-type alias resolves to the same specialist-bound suite.
    assert get_suite(doc_type).doc_type == doc_type


def test_merger_specialist_is_separate_from_contracts():
    assert EXTRACT_CLASS_ALIASES == {}
    assert resolve_extract_class("merger_agreement") == "merger_agreement"
    contract = DEFAULT_FIELD_TYPES["contract"]
    merger = DEFAULT_FIELD_TYPES["merger_agreement"]
    assert merger != contract
    assert {"cuad_family", "cuad_clauses"} <= set(contract)
    assert not ({"cuad_family", "cuad_clauses"} & set(merger))
    assert {"effective_time", "intent", "subject_matter"} <= set(merger)
    assert get_suite("contracts_specialist").doc_type == "contract"
    assert get_suite("merger_agreement_specialist").doc_type == "merger_agreement"


def test_compliance_filing_stays_retired():
    assert "compliance_filing" in RETIRED_DOC_CLASS_KEYS
    assert "compliance_filing" not in LIVE_DOC_CLASS_KEYS
    assert set(DOC_CLASS_KEYS) - set(RETIRED_DOC_CLASS_KEYS) == set(LIVE_DOC_CLASS_KEYS)
    assert "compliance_filing" not in LIVE_DOC_TYPES
    assert "compliance_filing" not in SORTER_LABEL_SET
    assert is_live_extract_class("compliance_filing") is False
    assert resolve_extract_class("compliance_filing") is None
    assert "compliance_specialist" not in LIVE_SPECIALISTS
    assert get_suite("compliance_specialist").retired is True
    # The live taxonomy has no compliance_filing class at all.
    assert "compliance_filing" not in _FIXTURE["doc_classes"]


@pytest.mark.parametrize("doc_type", _LIVE)
def test_metric_ids_cover_every_live_class(doc_type):
    ids = metric_ids_for_class(doc_type)
    assert "pipeline.extraction.overall" in ids
    assert "pipeline.extraction.field_micro_f2" in ids
    assert metric_id_allowed("pipeline.extraction.overall", doc_type)


def test_metric_id_mappings_cover_f2_and_content():
    assert (
        metric_id_for("extraction_f2", doc_class="insurance_claim")
        == "pipeline.extraction.field_micro_f2"
    )
    assert (
        metric_id_for("content_topic_accuracy", doc_class="correspondence")
        == "pipeline.enron.topic_accuracy"
    )
    assert (
        metric_id_for("sentiment_accuracy", doc_class="correspondence")
        == "pipeline.enron.sentiment_accuracy"
    )
    assert metric_id_allowed("pipeline.enron.topic_accuracy", "correspondence")
    assert metric_id_allowed("pipeline.extraction.field_micro_f2", "corporate_record")


@pytest.mark.parametrize("doc_type", _LIVE)
def test_score_document_emits_full_per_document_payload(doc_type):
    expected, predicted = _SCORE_FIXTURES[doc_type]
    suite = get_suite(_SPECIALIST_FOR[doc_type])
    out = suite.score_document(expected, predicted)
    assert isinstance(out, dict)
    for key in (
        "extraction",
        "overall_score",
        "schema_valid",
        "parse_ok",
        "schema_adherence",
        "extraction_precision",
        "extraction_recall",
        "extraction_f1",
        "extraction_f2",
        "metric_id",
        "provenance",
        "detail",
    ):
        assert key in out, f"{doc_type} payload missing {key}"
    assert out["overall_score"] == 1.0
    assert out["metric_id"] in metric_ids_for_class(doc_type)
    assert out["provenance"]["metric_id"] == out["metric_id"]
    assert out["provenance"]["scorer_version"]


def test_plain_batch_emits_schema_and_parse():
    expected, predicted = _SCORE_FIXTURES["contract"]
    out = get_suite("contracts_specialist").score([expected], [predicted])
    assert isinstance(out, dict)
    assert "schema_valid" in out
    assert "parse_ok" in out
    assert out["extraction_f1"] == 1.0


def test_plain_single_doc_keeps_dataclass_api():
    expected, predicted = _SCORE_FIXTURES["contract"]
    out = get_suite("contracts_specialist").score(expected, predicted)
    assert isinstance(out, ExtractionScoreResult)


def test_insurance_single_document_carries_class_extras():
    expected, predicted = _SCORE_FIXTURES["insurance_claim"]
    out = get_suite("insurance_claims_specialist").score_document(expected, predicted)
    assert out["determination_consistency"] == 1.0
    assert out["amount_exactness"] == 1.0
    assert "schema_promotion_gate" in out


def test_correspondence_content_only_gt_is_scored_not_unscorable():
    out = get_suite("correspondence_specialist").score(
        {"content_topic": "legal_contracts"}, {"content_topic": "legal_contracts"}
    )
    assert isinstance(out, dict)
    assert out.get("status") != "unscorable"
    assert out["content_topic_accuracy"] == 1.0
    # No extractable schema field → no field mean, not a zero.
    assert out["overall_score"] is None


def test_merger_maud_only_gt_is_scored_not_unscorable():
    labels = {"No-Shop": "Yes"}
    out = get_suite("merger_agreement_specialist").score(
        {"maud_clause_labels": labels}, {"maud_clause_labels": labels}
    )
    assert isinstance(out, dict)
    assert out.get("status") != "unscorable"
    assert out["maud_question_accuracy"] == 1.0


def test_triage_only_contract_gt_stays_unscorable():
    out = get_suite("contracts_specialist").score(
        {"contract_subtype": "nda"}, {"document_name": "Mutual NDA"}
    )
    assert out.get("status") == "unscorable"
    assert out.get("reason") == "gt_no_extractable_fields"


@pytest.mark.parametrize("suite_name", ["sorter", "archivist"])
def test_score_document_rejects_non_extraction_suites(suite_name):
    with pytest.raises(TypeError, match="extraction"):
        get_suite(suite_name).score_document({}, {})


@pytest.mark.parametrize("expected", [42, False, "[]", '"contract"', "null"])
def test_score_document_wrong_gt_shape_fails_closed_with_provenance(expected):
    result = get_suite("contracts_specialist").score_document(
        expected, {"governing_law": "Delaware"}, dataset_revision="fixture-revision",
    )
    assert result["status"] == "unscorable"
    assert result["reason"] == "gt_wrong_schema"
    assert result["overall_score"] is None
    assert result["provenance"]["dataset_revision"] == "fixture-revision"


def test_score_document_partial_prediction_reports_distinct_f1_and_f2():
    suite = get_suite("contracts_specialist")
    kwargs = {
        "field_types": {"first_id": "id", "second_id": "id"},
        "dataset_revision": "fixture-revision", "prompt_id": "fixture-prompt",
        "split": "test", "draw_seed": 42, "serving_kind": "local",
        "model_id": "fixture-model",
    }
    expected = {"first_id": "A", "second_id": "B"}
    predicted = {"first_id": "A"}
    result = suite.score_document(expected, predicted, **kwargs)
    assert result == suite.score(expected, predicted, detailed=True, **kwargs)
    assert result["extraction"].field_scores == {"first_id": 1.0, "second_id": 0.0}
    assert result["overall_score"] == 0.5
    assert result["extraction_precision"] == 1.0
    assert result["extraction_recall"] == 0.5
    assert result["extraction_f1"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["extraction_f2"] == pytest.approx(5 / 9, abs=1e-4)
    for key in ("dataset_revision", "prompt_id", "split", "serving_kind", "model_id"):
        assert result["provenance"][key] == kwargs[key]


@pytest.mark.parametrize("predicted_sentiment,accuracy", [("positive", 1.0), ("negative", 0.0)])
def test_sentiment_only_document_is_scored_without_fabricated_extraction_score(predicted_sentiment, accuracy):
    result = get_suite("correspondence_specialist").score_document(
        {"sentiment_label": "positive"}, {"sentiment_label": predicted_sentiment},
    )
    assert result.get("status") != "unscorable"
    assert result["sentiment_accuracy"] == accuracy
    assert result["overall_score"] is None
    assert result["extraction"].field_scores == {}


@pytest.mark.parametrize("doc_type", ["contract", "corporate_record", "insurance_claim", "merger_agreement"])
def test_content_metric_ids_are_rejected_outside_correspondence(doc_type):
    assert not metric_id_allowed("pipeline.enron.sentiment_accuracy", doc_type)
    assert not metric_id_allowed("pipeline.enron.topic_f1_macro", doc_type)
    assert not metric_id_allowed("not.a.metric", doc_type)
