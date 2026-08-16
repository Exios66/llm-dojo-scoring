import pytest

from llm_dojo_scoring.failure_modes import (
    classify_docclass_failure,
    classify_failure,
    confusion_from_rows,
    per_subtype_accuracy,
    summarize_failures,
)


def _row(doc_type_ok=True, subtype_ok=False, subtype_ok_equiv=False,
         contract_subtype="license", expected_subtype="license"):
    return {
        "doc_type_ok": doc_type_ok,
        "subtype_ok": subtype_ok,
        "subtype_ok_equiv": subtype_ok_equiv,
        "contract_subtype": contract_subtype,
        "expected_subtype": expected_subtype,
    }


def test_classify_failure_modes():
    assert classify_failure(_row(subtype_ok=True)) == "ok"
    assert classify_failure(_row(doc_type_ok=False)) == "function_over_form"
    assert classify_failure(_row(contract_subtype="other")) == "other_fallback"
    assert classify_failure(_row(subtype_ok_equiv=True)) == "equivalent_family"
    assert classify_failure(_row()) == "family_confusion"


def test_classify_docclass_failure():
    assert classify_docclass_failure({"doc_type_ok": False}) == "doc_type_miss"
    assert classify_docclass_failure({"doc_type_ok": True}) == "subclass_miss"


def test_summarize_failures():
    rows = [
        _row(subtype_ok=True),
        _row(doc_type_ok=False),
        _row(contract_subtype="other"),
        _row(subtype_ok_equiv=True),
        _row(),
    ]
    out = summarize_failures(rows)
    assert out["n_total"] == 5
    assert out["n_ok"] == 1
    assert out["n_failed"] == 4
    assert out["mode_counts"] == {
        "function_over_form": 1, "other_fallback": 1,
        "equivalent_family": 1, "family_confusion": 1,
    }


def test_per_subtype_accuracy():
    rows = [
        _row(subtype_ok=True, expected_subtype="license"),
        _row(subtype_ok=False, subtype_ok_equiv=True, expected_subtype="license"),
        _row(subtype_ok=False, expected_subtype="franchise"),
    ]
    acc = per_subtype_accuracy(rows)
    assert acc["license"]["n"] == 2
    assert acc["license"]["accuracy"] == 0.5
    assert acc["license"]["accuracy_equiv"] == 1.0
    assert acc["franchise"]["n"] == 1


def test_confusion_from_rows():
    rows = [
        {"expected_subtype": "license", "contract_subtype": "license"},
        {"expected_subtype": "license", "contract_subtype": "franchise"},
        {"expected_subtype": "franchise", "contract_subtype": "franchise"},
    ]
    matrix, keys = confusion_from_rows(rows)
    assert keys == ["franchise", "license"]
    assert matrix[1][1] == 1  # license->license
    assert matrix[1][0] == 1  # license->franchise