"""Per-type verdicts for one value checked against the source document."""

from __future__ import annotations

import pytest

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
def test_value_verdict_by_field_type(doc_text, ftype, value, expected):
    assert value_verdict(ftype, value, doc_text)[0] == expected


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_document_text_is_unverifiable(missing):
    assert value_verdict("name", "Acme", missing) == ("unverifiable", None)


def test_name_coverage_is_reported(doc_text):
    assert value_verdict("name", "Acme Globex", doc_text) == ("not_found", pytest.approx(0.5))


def test_unknown_field_type_uses_the_name_rule(doc_text):
    assert value_verdict("mystery", "Acme Holdings", doc_text) == ("grounded", pytest.approx(1.0))


def test_verdicts_constant_lists_every_outcome():
    assert VERDICTS == ("grounded", "not_found", "unverifiable")
