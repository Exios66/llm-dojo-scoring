"""#18 remainder: the schema promotion gate covers every live class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_dojo_scoring.mailroom import LIVE_DOC_TYPES
from llm_dojo_scoring.scorecard_honesty import (
    DEFAULT_INSURANCE_SCHEMA_GATE,
    DEFAULT_SCHEMA_GATE,
    SCHEMA_PROMOTION_GATES,
    check_schema_promotion_gate,
)
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite

_TAXONOMY = json.loads(
    (Path(__file__).parent / "fixtures" / "taxonomy_field_types.json").read_text()
)
_SPECIALIST_FOR = {
    key: meta["specialist"] for key, meta in _TAXONOMY["doc_classes"].items()
}


def _one_field_pair(doc_class: str) -> tuple[dict, dict, dict]:
    """(expected, prediction missing every other key, full prediction)."""
    ftypes = DEFAULT_FIELD_TYPES[doc_class]
    field = next(k for k, t in ftypes.items() if t in ("text", "string", "str", "date"))
    value = "2024-01-15" if ftypes[field] == "date" else "Delaware"
    expected = {field: value}
    partial = {field: value}
    full = {k: None for k in ftypes}
    full[field] = value
    return expected, partial, full


def test_every_live_class_has_a_gate():
    assert set(SCHEMA_PROMOTION_GATES) == set(LIVE_DOC_TYPES)
    assert DEFAULT_INSURANCE_SCHEMA_GATE == DEFAULT_SCHEMA_GATE


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_high_score_with_invalid_schema_fails_the_gate(doc_class):
    """The #18 failure on every class: field match high, schema invalid."""
    expected, partial, _ = _one_field_pair(doc_class)
    out = get_suite(_SPECIALIST_FOR[doc_class]).score_document(expected, partial)
    gate = out["schema_promotion_gate"]
    assert out["overall_score"] == 1.0
    assert out["schema_valid"] < DEFAULT_SCHEMA_GATE
    assert gate["passes"] is False
    assert gate["reason"] == "schema_valid_below_threshold"
    assert gate["doc_class"] == doc_class


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_schema_complete_prediction_passes_the_gate(doc_class):
    expected, _, full = _one_field_pair(doc_class)
    out = get_suite(_SPECIALIST_FOR[doc_class]).score_document(expected, full)
    assert out["schema_promotion_gate"]["passes"] is True


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_batch_payload_carries_the_gate(doc_class):
    """Classes without extras used to return early with no gate on batches."""
    expected, partial, _ = _one_field_pair(doc_class)
    out = get_suite(_SPECIALIST_FOR[doc_class]).score([expected], [partial])
    assert out["schema_promotion_gate"]["passes"] is False


def test_gate_threshold_resolution():
    assert check_schema_promotion_gate(0.95, doc_class="contract")["passes"] is True
    assert check_schema_promotion_gate(0.95, doc_class="contract", threshold=0.99)[
        "passes"
    ] is False
    assert check_schema_promotion_gate(0.95)["threshold"] == DEFAULT_SCHEMA_GATE
    missing = check_schema_promotion_gate(None, doc_class="correspondence")
    assert missing == {
        "threshold": DEFAULT_SCHEMA_GATE,
        "doc_class": "correspondence",
        "passes": False,
        "reason": "schema_valid_missing",
    }


def test_batch_format_layer_counts_missing_keys_per_item():
    """A list was treated as one parsed object, so a batch always read 1.0."""
    from llm_dojo_scoring.scorecard_honesty import score_format_layer

    out = score_format_layer(
        predicted=[{"a": 1, "b": 2}, {"a": 1}], required_keys=["a", "b"]
    )
    assert out == {"parse_ok": 1.0, "schema_valid": 0.75, "schema_adherence": 0.75}


def test_batch_format_layer_counts_unparseable_strings():
    from llm_dojo_scoring.scorecard_honesty import score_format_layer

    out = score_format_layer(
        predicted=['{"a": 1}', "not json at all"], required_keys=["a"]
    )
    assert out["parse_ok"] == 0.5
    assert out["schema_valid"] == 0.5


def test_empty_batch_fails_closed():
    from llm_dojo_scoring.scorecard_honesty import score_format_layer

    assert score_format_layer(predicted=[], required_keys=["a"])["schema_valid"] == 0.0


@pytest.mark.parametrize("raw", ["[]", '[{"a": 1}]'])
def test_parsed_non_object_fails_required_keys(raw):
    from llm_dojo_scoring.scorecard_honesty import score_format_layer

    out = score_format_layer(predicted_raw=raw, required_keys=["a"])
    assert out == {"parse_ok": 1.0, "schema_valid": 0.0, "schema_adherence": 0.0}
    assert score_format_layer(predicted_raw=raw)["schema_valid"] == 1.0


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
@pytest.mark.parametrize("surplus_is_valid", [False, True])
def test_batch_gate_ignores_surplus_predictions(doc_class, surplus_is_valid):
    expected, partial, full = _one_field_pair(doc_class)
    scored = partial if surplus_is_valid else full
    surplus = full if surplus_is_valid else partial
    suite = get_suite(_SPECIALIST_FOR[doc_class])
    baseline = suite.score([expected], [scored])
    out = suite.score([expected], [scored, surplus])
    assert len(out["extraction"]) == 1
    for key in ("parse_ok", "schema_valid", "schema_adherence", "schema_promotion_gate"):
        assert out[key] == baseline[key]


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_batch_gate_respects_doc_text_limit(doc_class):
    expected, partial, full = _one_field_pair(doc_class)
    suite = get_suite(_SPECIALIST_FOR[doc_class])
    baseline = suite.score([expected], [full])
    out = suite.score([expected, expected], [full, partial], doc_text=[None])
    assert len(out["extraction"]) == 1
    assert out["schema_valid"] == baseline["schema_valid"]
    assert out["schema_promotion_gate"] == baseline["schema_promotion_gate"]
    empty = suite.score([expected], [full], doc_text=[])
    assert empty["extraction"] == []
    assert empty["schema_promotion_gate"]["passes"] is False


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_unscorable_document_carries_failing_gate_and_provenance(doc_class):
    _, _, full = _one_field_pair(doc_class)
    out = get_suite(_SPECIALIST_FOR[doc_class]).score_document(
        None, full, dataset_revision="test-revision", prompt_id="test-prompt"
    )
    assert out["status"] == "unscorable"
    assert out["schema_promotion_gate"] == check_schema_promotion_gate(None, doc_class=doc_class)
    assert out["provenance"]["dataset_revision"] == "test-revision"
    assert out["provenance"]["prompt_id"] == "test-prompt"
    assert out["provenance"]["metric_id"] == out["metric_id"]


@pytest.mark.parametrize("metric", ["schema_valid", "parse_ok"])
def test_dashboards_never_hide_schema(metric):
    """Registry-driven T0+T1 views must show structural validity for every
    live specialist; demoting it below T1 or scoping it away fails here."""
    from llm_dojo_scoring.registry import LIVE_SPECIALIST_AGENTS, get_registry

    reg = get_registry()
    for agent in LIVE_SPECIALIST_AGENTS:
        assert metric in reg.names_for(max_tier=1, agent=agent), agent
