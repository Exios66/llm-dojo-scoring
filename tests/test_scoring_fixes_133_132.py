"""Regression tests for #133 (money with a currency word and a suffix) and #132 (CMS marker)."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.schemas import doc_classes
from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.scoring.field_scoring import parse_money
from llm_dojo_scoring.scoring.suites import get_suite


@pytest.mark.parametrize(
    "text, value",
    [
        ("1.2M USD", 1_200_000.0),
        ("USD 1.2M", 1_200_000.0),
        ("$1.2M", 1_200_000.0),
        ("5K dollars", 5_000.0),
        ("EUR 3B", 3_000_000_000.0),
        ("3 dollars", 3.0),
        ("1,200,000 USD", 1_200_000.0),
    ],
)
def test_parse_money_reads_currency_words_with_suffixes(text, value):
    """#133: a currency word before or after a K/M/B amount no longer defeats the parser."""
    assert parse_money(text) == value


def test_parse_money_still_rejects_non_amounts():
    """Text that is not an amount stays unparseable."""
    assert parse_money("USD") is None
    assert parse_money("about a million") is None


def _carrier_row() -> dict:
    """A synthetic CMS carrier insurance row with every pipeline field populated."""
    values = {"claim_type": "health", "coverage_determination": "approved", "intent": "claim_data_record"}
    row = {}
    for field, ftype in doc_classes.field_types("insurance_claim").items():
        if field == "claim_checklist":
            continue
        if field in values:
            row[field] = values[field]
        elif ftype.startswith("entity_list"):
            row[field] = ["Item One"]
        else:
            row[field] = {"date": "2020-01-02", "money": "100"}.get(ftype, "Value")
    return row


def test_perfect_carrier_extraction_scores_one():
    """#132: a perfect carrier extraction is not capped by the subclass-derived CMS marker."""
    row = _carrier_row()
    result = get_suite("insurance_claims_specialist").score(
        expected=dict(row), predicted=dict(row), doc_subclass="carrier"
    )
    assert "cms_source_table" not in result.field_scores
    assert result.overall_score == 1.0


def test_perfect_carrier_extraction_has_full_field_micro_recall():
    """#132: the derived marker is not an expected event the extractor can miss."""
    row = _carrier_row()
    expected = {**row, "cms_source_table": "carrier"}
    metrics = extraction_binary_metrics(
        expected,
        dict(row),
        doc_class="insurance_claim",
        field_types={**doc_classes.field_types("insurance_claim"), "cms_source_table": "label"},
    )
    assert metrics["extraction_recall"] == 1.0


def test_a_stated_wrong_cms_table_is_still_scored():
    """A prediction that names a CMS table is scored against the derived marker."""
    row = _carrier_row()
    result = get_suite("insurance_claims_specialist").score(
        expected=dict(row), predicted={**row, "cms_source_table": "inpatient"}, doc_subclass="carrier"
    )
    assert result.field_scores["cms_source_table"] == 0.0
