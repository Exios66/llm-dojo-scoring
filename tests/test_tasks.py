"""Task-aware scoring across the additional document hierarchy (issue #19 /
KANBAN-047): MAUD, LegalBench, chained runs, multiclass, court opinions."""

from llm_dojo_scoring.tasks import (
    chained_composite,
    chained_summary,
    contracteval_classified,
    contracteval_metrics,
    court_opinion_score,
    get_jaccard,
    legalbench_score,
    maud_docclass_score,
    maud_question_score,
    multiclass_score,
    normalize_legalbench,
    normalize_maud_consideration,
    normalize_task_answer,
    said_no_related,
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


# ---------------------------------------------------------------------------
# ContractEval (arXiv 2508.03080) — clause-level legal risk identification
# ---------------------------------------------------------------------------

ANTI = "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER PARTY, ASSIGN THIS AGREEMENT"


def test_get_jaccard_mirrors_contracteval():
    assert get_jaccard(ANTI, ANTI.lower()) == 1.0
    assert get_jaccard("a b c", "a b") == 2 / 3
    assert get_jaccard("", "") == 0.0  # empty-union guard
    # punctuation stripped + "/" -> space, exactly as Evaluation.py
    assert get_jaccard("a/b; c.", "a b c") == 1.0


def test_said_no_related_and_classified():
    assert said_no_related("No related clause.") is True
    assert said_no_related("No related clause") is True
    assert said_no_related("no related clause found here") is True
    assert said_no_related("There is a clause about X") is False
    assert contracteval_classified([ANTI], ANTI) is True
    assert contracteval_classified([ANTI], ANTI + " extra trailing") is True
    assert contracteval_classified([ANTI], "no related clause") is False
    assert contracteval_classified([ANTI, "SECOND LABEL"], ANTI) is False


def test_contracteval_metrics_confusion():
    m = contracteval_metrics(
        [[ANTI], [ANTI], [], [], [ANTI, "SECOND"]],
        [ANTI, "no related clause", "no related clause", "a fabricated clause", ANTI],
        categories=["Anti-Assignment"] * 5,
    )
    assert m["tp"] == 1
    assert m["fn"] == 2
    assert m["tn"] == 1
    assert m["fp"] == 1
    assert m["n_pairs"] == 5
    assert m["n_positive"] == 3
    assert m["precision"] == pytest.approx(1 / 2)
    assert m["recall"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["f1"] == pytest.approx(2 * 0.5 * (1 / 3) / (0.5 + 1 / 3))
    # Jaccard only over positive pairs (3 of them, two "no related clause").
    assert m["jaccard_mean"] > 0.0
    # false-no-related: 1 of the 3 positives said "no related clause".
    assert m["false_no_related_rate"] == pytest.approx(1 / 3, abs=1e-4)
    # The paper's hardcoded 1,244 denominator is reported separately.
    assert m["false_no_related_rate_paper"] == pytest.approx(1 / 1244, abs=1e-4)
    assert m["false_no_related_denominator"] == 1244
    # per_category breakdown present when categories are supplied.
    assert "per_category" in m
    assert m["per_category"]["Anti-Assignment"]["tp"] == 1


def test_contracteval_metrics_own_denominator():
    m = contracteval_metrics([[ANTI], []], ["no related clause", "no related clause"],
                             positive_denominator=None)
    assert m["n_positive"] == 1
    assert m["false_no_related_rate"] == 1.0  # own n_pos denominator
    assert m["false_no_related_denominator"] == 1


def test_contracteval_metrics_scale_free():
    """The scorer is pure and deterministic over the paper's own TP definition:
    a fully-correct positive output scores TP regardless of surrounding verbosity."""
    label = ["CLAUSE ONE"]
    assert contracteval_metrics([label, label], ["CLAUSE ONE", "CLAUSE ONE."])["tp"] == 2
    assert contracteval_metrics([label], ["CLAUSE TWO"])["fn"] == 1


def test_score_task_contracteval_dispatch():
    m = score_task("contracteval", [[ANTI], []], [ANTI, "no related clause"],
                   categories=["Anti-Assignment", "Anti-Assignment"])
    assert m["kind"] == "contracteval"
    assert m["tp"] == 1 and m["tn"] == 1
    assert task_kind("contracteval") == "contracteval"
