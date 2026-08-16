"""Task-aware scoring across the additional document hierarchy (issue #19 /
KANBAN-047): MAUD, LegalBench, chained runs, multiclass, court opinions."""

from llm_dojo_scoring.tasks import (
    chained_composite,
    chained_summary,
    court_opinion_score,
    legalbench_score,
    maud_docclass_score,
    maud_question_score,
    multiclass_score,
    normalize_legalbench,
    normalize_maud_consideration,
    normalize_task_answer,
    score_task,
    task_kind,
)


def test_task_kind_routing():
    assert task_kind("subtype") == "subtype"
    assert task_kind("maud_docclass") == "docclass"
    assert task_kind("maud_question") == "maud_question"
    assert task_kind("legalbench") == "legalbench"
    assert task_kind("chained") == "chained"
    assert task_kind("unknown_task") == "unknown_task"


# --- MAUD ---------------------------------------------------------------

def test_normalize_maud_consideration():
    assert normalize_maud_consideration("All Cash") == "all_cash"
    assert normalize_maud_consideration("all-cash") == "all_cash"
    assert normalize_maud_consideration("Mixed Cash & Stock") == "mixed_cash_stock"
    assert normalize_maud_consideration("Mixed Cash & Stock (Election)") == "mixed_cash_stock_election"
    assert normalize_maud_consideration("all_stock") == "all_stock"
    assert normalize_maud_consideration("unspecified") == "other"
    assert normalize_maud_consideration(None) == "other"


def test_maud_docclass_doc_type_and_subclass():
    expected_dt = ["merger_agreement"] * 4
    predicted_dt = ["merger_agreement", "merger_agreement", "merger_agreement", "contract"]
    expected_sub = ["all_cash", "all_stock", "mixed_cash_stock", "all_cash"]
    predicted_sub = ["all_cash", "all_stock", "mixed_cash_stock_election", "all_cash"]
    s = maud_docclass_score(expected_dt, predicted_dt, expected_sub, predicted_sub)
    assert s["doc_type_accuracy"] == 0.75
    assert s["subclass_accuracy"] == 0.75          # election != mixed, strict
    assert s["subclass_accuracy_equiv"] == 1.0     # election family-equivalent
    assert s["exact_match"] == 0.5                  # rows 2 (subclass strict) + 3 (doc_type)
    assert s["n_subclass_scored"] == 4
    assert s["per_class"]["merger_agreement"]["accuracy"] == 0.75


def test_maud_question_score():
    expected = ["All Cash", "All Stock", "Other", "All Cash"]
    predicted = ["all cash", "all_stock", "mixed cash and stock", "all_cash"]
    s = maud_question_score(expected, predicted)
    assert s["exact_match"] == 0.75                 # row 2 mismatched -> other vs mixed
    assert s["n"] == 4
    assert s["exact_match_ci"] is not None
    assert s["per_class"]["all_cash"]["n"] == 2


# --- LegalBench ----------------------------------------------------------

def test_normalize_legalbench():
    assert normalize_legalbench("Yes") == "yes"
    assert normalize_legalbench("No.") == "no"
    assert normalize_legalbench("TRUE") == "yes"
    assert normalize_legalbench("0") == "no"


def test_legalbench_score():
    expected = ["yes", "no", "yes", "no", "yes"]
    predicted = ["yes", "yes", "yes", "no", "no"]
    s = legalbench_score(expected, predicted)
    assert s["exact_match"] == 0.6
    assert s["per_class"]["yes"]["n"] == 3
    assert s["per_class"]["no"]["accuracy"] == 0.5
    assert s["binary"]["precision"] == round(2 / 3, 4)   # 2 of 3 "yes" predictions correct
    assert s["binary"]["recall"] == round(2 / 3, 4)
    assert s["n"] == 5


# --- Multiclass / court opinions -----------------------------------------

def test_multiclass_score():
    expected = ["a", "b", "c", "a", "b"]
    predicted = ["a", "b", "c", "b", "b"]
    s = multiclass_score(expected, predicted)
    assert s["exact_match"] == 0.8
    assert s["micro_accuracy"] == 0.8
    assert s["macro_accuracy"] == round((0.5 + 1.0 + 1.0) / 3, 4)  # class a 1/2
    assert s["confusion"]["labels"] == ["a", "b", "c"]


def test_court_opinion_score():
    expected = ["court_opinion"] * 3
    predicted = ["court_opinion", "court_opinion", "contract"]
    s = court_opinion_score(expected, predicted)
    assert s["exact_match"] == 0.6667
    assert s["per_class"]["court_opinion"]["accuracy"] == 0.6667
    assert s["kind"] == "court_opinion"


# --- Chained -------------------------------------------------------------

def test_chained_composite_and_summary():
    assert chained_composite(1.0, 0.9) == round(0.25 * 1.0 + 0.75 * 0.9, 4)
    assert chained_composite(1.0, 0.9, weights=(0.5, 0.5)) == 0.95
    s = chained_summary(sorter_exact=1.0, sorter_subtype=0.6,
                        extractor_overall=0.8894, extractor_presence=0.9667, n=5)
    assert s["sorter"]["exact_match"] == 1.0
    assert s["sorter"]["subtype_accuracy"] == 0.6
    assert s["extractor"]["overall_extraction_score"] == 0.8894
    assert s["composite"] == round(0.25 * 1.0 + 0.75 * 0.8894, 4)
    assert s["n"] == 5


def test_score_task_dispatcher_and_chained_guard():
    assert score_task("doc_class", ["contract", "contract"], ["contract", "contract"])["exact_match"] == 1.0
    assert score_task("multiclass", ["a", "b"], ["a", "a"])["exact_match"] == 0.5
    assert normalize_task_answer("legalbench", "Yes") == "yes"
    assert normalize_task_answer("maud_docclass", "All Cash") == "all_cash"
    import pytest
    with pytest.raises(ValueError, match="chained_composite"):
        score_task("chained", ["a"], ["a"])