import pytest

from llm_dojo_scoring.diagnostics import (
    DURATION_FIELDS,
    extraction_diagnostics,
    parse_duration_days,
)


def test_parse_duration_days():
    assert parse_duration_days("two (2) years") == 730
    assert parse_duration_days("thirty (30) days") == 30
    assert parse_duration_days("24 months") == 720
    assert parse_duration_days("annual") == 365
    assert parse_duration_days("1 year") == 365
    assert parse_duration_days("no duration here") is None
    assert parse_duration_days(None) is None


FIELD_TYPES = {
    "document_name": "name",
    "effective_date": "date",
    "term_length": "free_text",
    "contract_value": "money",
    "key_obligations": "entity_list:free_text",
    "parties": "entity_list:name",
}


def _row(field_scores, predicted=None, expected=None, list_scores=None, filename="doc1.pdf"):
    return {
        "filename": filename,
        "predicted": predicted or {},
        "expected_fields": expected or {},
        "field_scores": field_scores,
        "entity_list_scores": list_scores or {},
        "entity_list_audit": {},
    }


def test_extraction_diagnostics_field_decomposition():
    rows = [
        _row({"document_name": 1.0, "effective_date": 0.5, "contract_value": 0.0}),
        _row({"document_name": 1.0, "effective_date": 1.0, "contract_value": 1.0}),
    ]
    metrics = extraction_diagnostics(rows, FIELD_TYPES)
    assert metrics["field_exact_rate"] == pytest.approx(4 / 6, abs=1e-4)
    assert metrics["field_partial_rate"] == pytest.approx(1 / 6, abs=1e-4)
    assert metrics["field_miss_rate"] == pytest.approx(1 / 6, abs=1e-4)
    assert metrics["n_fields_scored"] == 6
    assert metrics["error_decomposition"]["document_name"]["exact_rate"] == 1.0


def test_extraction_diagnostics_date_mae_and_r2():
    rows = [
        _row({"effective_date": 1.0},
             predicted={"effective_date": "2024-03-01"},
             expected={"effective_date": "2024-03-01"}),
        _row({"effective_date": 1.0},
             predicted={"effective_date": "2024-03-08"},
             expected={"effective_date": "2024-03-01"}),
    ]
    metrics = extraction_diagnostics(rows, FIELD_TYPES)
    assert metrics["date_n_pairs"] == 2
    assert metrics["date_mae_days"] == pytest.approx(3.5)
    assert metrics["date_median_ae_days"] == 3.5


def test_extraction_diagnostics_duration():
    rows = [
        _row({},
             predicted={"term_length": "two (2) years"},
             expected={"term_length": "two (2) years"}),
        _row({},
             predicted={"term_length": "1 year"},
             expected={"term_length": "two (2) years"}),
    ]
    metrics = extraction_diagnostics(rows, FIELD_TYPES)
    assert metrics["duration_n_pairs"] == 2
    assert metrics["duration_mae_days"] == pytest.approx(365 / 2)  # (0 + 365)/2


def test_extraction_diagnostics_list_and_span():
    rows = [
        _row({"parties": 1.0},
             list_scores={"parties": {
                 "precision": 1.0, "recall": 1.0, "f1": 1.0,
                 "matched": 1, "n_predicted": 1, "n_expected": 1}}),
        _row({"parties": 0.0},
             list_scores={"parties": {
                 "precision": 0.0, "recall": 0.0, "f1": 0.0,
                 "matched": 0, "n_predicted": 2, "n_expected": 1}}),
    ]
    metrics = extraction_diagnostics(rows, FIELD_TYPES)
    assert metrics["entity_list_precision"]["parties"] == 0.5
    assert metrics["span_count_mae"] == pytest.approx(0.5)
    assert metrics["span_count_signed_mean"] == pytest.approx(0.5)  # (0 + 1)/2


def test_extraction_diagnostics_expected_resolver():
    rows = [
        _row({"effective_date": 1.0},
             predicted={"effective_date": "2024-03-01"},
             expected={"effective_date": "label text"},
             filename="a.pdf"),
    ]
    metrics = extraction_diagnostics(
        rows, FIELD_TYPES,
        expected_resolver=lambda master, fn, field, fallback: "2024-03-01"
    )
    assert metrics["date_mae_days"] == 0.0