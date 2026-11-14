"""Per-type verdicts for one value checked against the source document."""

from __future__ import annotations

import pytest

from grounding_inputs import DOC_TEXT

from llm_dojo_scoring.grounding.verdicts import VERDICTS, value_verdict


@pytest.mark.parametrize(("ftype", "value", "expected"), [
    ("name", "Acme Holdings", "grounded"),
    ("name", "Globex Corporation", "not_found"),
    ("free_text", "invoice from Acme", "grounded"),
    ("date", "2024-03-03", "grounded"),
    ("date", "2024-03-04", "not_found"),
    ("money", "$1,250.00", "grounded"),
    ("money", "$9,999", "not_found"),
    ("money", "about a thousand", "unverifiable"),
    ("id", "ab 12 34", "grounded"),
    ("id", "AB-99", "not_found"),
    ("cms_doc_ref", "AB1234", "grounded"),
    ("label", "invoice", "unverifiable"),
    ("name", "!!!", "unverifiable"),
])
def test_value_verdict_by_field_type(ftype, value, expected):
    """Value verdict by field type."""
    assert value_verdict(ftype, value, DOC_TEXT)[0] == expected


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_document_text_is_unverifiable(missing):
    """Missing document text is unverifiable."""
    assert value_verdict("name", "Acme", missing) == ("unverifiable", None)


def test_name_coverage_is_reported():
    """Name coverage is reported."""
    assert value_verdict("name", "Acme Globex", DOC_TEXT) == ("not_found", pytest.approx(0.5))


def test_unknown_field_type_uses_the_name_rule():
    """Unknown field type uses the name rule."""
    assert value_verdict("mystery", "Acme Holdings", DOC_TEXT) == ("grounded", pytest.approx(1.0))


def test_verdicts_constant_lists_every_outcome():
    """Verdicts constant lists every outcome."""
    assert VERDICTS == ("grounded", "not_found", "unverifiable")


@pytest.mark.parametrize(("value", "text", "expected"), [
    ("15", "Signed on Jan 15, 2023.", "not_found"),
    (2023, "dated 2023-01-15", "not_found"),
    ("555", "call 555-1234", "not_found"),
    ("$1.2M", "a total of $1.2 million", "grounded"),
    ("1.2 million dollars", "USD 1.2M was paid", "grounded"),
    ("-500", "owes $500", "grounded"),
    ("500", "owes 500 dollars", "grounded"),
    ("12,000", "the sum of 12,000 is due", "grounded"),
    ("99.50", "fee of 99.50", "grounded"),
    (True, "owes $1", "unverifiable"),
    ("500", "Total: $ 500", "grounded"),
    ("500", "Total: \u20ac 500", "grounded"),
    ("500", "Total: USD  500", "grounded"),
    ("500", "Total: 500  dollars", "grounded"),
    ("500", "Total: $\n500", "not_found"),
])
def test_money_counts_only_document_numbers_that_read_as_money(value, text, expected):
    """A day, a year or a phone digit group never grounds an amount; spelled scales do."""
    assert value_verdict("money", value, text)[0] == expected


@pytest.mark.parametrize(("value", "text", "expected"), [
    ("12", "Invoice dated 2012 and page 3", "unverifiable"),
    ("ab12", "ab 1 23", "not_found"),
    ("ab12", "ab 1 2", "grounded"),
    ("201", "Invoice dated 2012", "not_found"),
    ("CLM-0001", "Claim No. CLM-0001.", "grounded"),
    ("CLM 0001", "Claim No. CLM-0001.", "grounded"),
    ("CLM-0001", "Claim No. CLM 0001.", "grounded"),
])
def test_id_matches_whole_runs_only(value, text, expected):
    """An identifier never matches inside a longer run, and very short ids are unverifiable."""
    assert value_verdict("id", value, text)[0] == expected


@pytest.mark.parametrize(("ftype", "value", "text", "expected"), [
    ("id", "12345", "Invoice INV-12345 due", "grounded"),
    ("id", "12345", "Invoice No.12345 due", "grounded"),
    ("id", "INV-2024-0001", "ref inv 2024 0001", "grounded"),
    ("money", "5000000", "see Exhibit 5 M today", "not_found"),
    ("money", "5000000", "a budget of 5M", "grounded"),
])
def test_pre_pr_review_boundary_cases(ftype, value, text, expected):
    """An id part inside a prefixed run grounds; a spaced lone letter is not a money scale."""
    assert value_verdict(ftype, value, text)[0] == expected


@pytest.mark.parametrize(("value", "text", "expected"), [
    ("2024-03-03", "Effective 2024-03-03.", "grounded"),
    ("2024-03-03", "Effective 2024/03/03.", "grounded"),
    ("2024-03-03", "Effective 2024.03.03.", "grounded"),
    ("2024-03-03", "Signed March 3rd, 2024.", "grounded"),
    ("2024-03-03", "Signed Mar. 3rd, 2024.", "grounded"),
    ("2024-03-03", "Signed 3 March 2024.", "grounded"),
    ("2024-03-03", "Signed 3rd of March, 2024.", "grounded"),
    ("2024-03-03", "Made this 3rd day of March, 2024.", "grounded"),
    ("2024-03-03", "Signed Sunday, 3 March 2024.", "grounded"),
    ("2024-03", "dated March 2024", "grounded"),
    ("2024-03", "dated 03/2024", "grounded"),
    ("March 3", "Signed on March 3.", "grounded"),
    ("March 3", "Signed on the 3rd of March.", "grounded"),
    ("March 3", "Signed on March 3, 2024.", "grounded"),
    ("March the 3rd, 2024", "Effective 2024-03-03.", "grounded"),
    ("2024-03-03", "Signed on March 3.", "not_found"),
    ("2024-03-03", "dated March 2024", "not_found"),
    ("2024-03-04", "Effective 2024-03-03.", "not_found"),
    ("May 5", "you may 5 times", "not_found"),
    ("2024-03-01", "INV-2024-0301", "not_found"),
    ("2024-03", "Ref 2024-03-0001", "not_found"),
    ("2003-01-02", "see v1.2.3 for details", "not_found"),
    ("2034-01-02", "version 1.2.34 was released", "not_found"),
    ("March 3", "March 3,000 units shipped", "not_found"),
    ("March 3", "In March we met 3 times", "not_found"),
])
def test_date_verdict_reads_every_written_date_form(value, text, expected):
    """A date is grounded by the document's date in any common written form, never by an id."""
    assert value_verdict("date", value, text)[0] == expected, (value, text)
