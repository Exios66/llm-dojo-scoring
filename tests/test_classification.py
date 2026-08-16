import pytest

from llm_dojo_scoring.classification import (
    accuracy,
    binary_metrics,
    class_distribution,
    confusion_accuracy,
    confusion_matrix,
    exact_match,
    failure,
    macro_accuracy,
    normalize_label,
    per_class_stats,
    top_confusions,
)


def test_normalize_label_json():
    assert normalize_label('{"doc_type": "Contract"}') == "contract"
    assert normalize_label('{"doc_type": "Corporate Record"}') == "corporate_record"


def test_normalize_label_regex_fallback():
    assert normalize_label("This is a contract agreement") == "contract"
    assert normalize_label("court opinion") == "court_opinion"
    assert normalize_label("nonsense") == "nonsense"


def test_exact_match():
    assert exact_match("Contract", "contract") == 1.0
    assert exact_match("License Agreement", "contract") == 0.0


def test_failure_sentinel():
    assert failure("ERROR: parse failed", "contract") == 1.0
    assert failure("contract", "contract") == 0.0


def test_accuracy_and_macro():
    exp = ["contract", "contract", "license", "license", "license"]
    pred = ["contract", "contract", "contract", "license", "license"]
    assert accuracy(exp, pred) == 0.8
    assert macro_accuracy(exp, pred) == pytest.approx(0.8334, abs=1e-4)


def test_per_class_stats_skips_failures():
    exp = ["contract", "contract", "license"]
    pred = ["contract", "ERROR: fail", "license"]
    stats = per_class_stats(exp, pred)
    assert stats["contract"]["n"] == 1
    assert stats["contract"]["correct"] == 1
    assert stats["license"]["n"] == 1


def test_confusion_matrix():
    exp = ["a", "a", "b", "b"]
    pred = ["a", "b", "b", "b"]
    matrix, labels = confusion_matrix(exp, pred, labels=["a", "b"])
    assert matrix == [[1, 1], [0, 2]]
    assert confusion_accuracy(matrix) == 0.75


def test_top_confusions():
    matrix, labels = confusion_matrix(
        ["a", "a", "b"], ["a", "b", "a"], labels=["a", "b"]
    )
    confusions = top_confusions(matrix, labels)
    assert any(c["expected"] == "a" and c["predicted"] == "b" for c in confusions)


def test_binary_metrics():
    out = binary_metrics(
        [True, True, False, False], [True, False, True, False], positive="true"
    )
    assert out["tp"] == 1 and out["fp"] == 1 and out["fn"] == 1 and out["tn"] == 1
    assert out["precision"] == 0.5 and out["recall"] == 0.5 and out["f1"] == 0.5


def test_class_distribution():
    counts = class_distribution(["contract", "Contract", "license"])
    assert counts == {"contract": 2, "license": 1}