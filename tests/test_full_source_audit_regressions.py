"""Hand-counted regressions from the independent DMR-091 source audit."""

import pytest

from llm_dojo_scoring import get_suite, score_task
from llm_dojo_scoring.scorecard_honesty import summarize_run_completion
from llm_dojo_scoring.serving import aggregate_serving


@pytest.mark.parametrize("missing", [None, "not json"])
def test_missing_predictions_remain_in_content_population(missing):
    """One failed and one correct row means two attempts and half accuracy."""
    gt = {"sender": "Alice", "content_topic": "general_business", "sentiment_label": "neutral"}
    result = get_suite("correspondence").score([gt, gt], [missing, gt])
    assert result["n_topic"] == 2
    assert result["content_topic_accuracy"] == 0.5
    assert result["sentiment_accuracy"] == 0.5
    # Only the sender is an extraction event: TP=1, FN=1, FP=0.
    assert result["extraction_f1"] == pytest.approx(2 / 3, abs=1e-4)


def test_single_missing_prediction_retains_content_miss():
    """The scalar path follows the same missing-answer population contract."""
    gt = {"sender": "Alice", "content_topic": "general_business", "sentiment_label": "neutral"}
    result = get_suite("correspondence").score(gt, None)
    assert result["n_topic"] == 1
    assert result["content_topic_accuracy"] == result["sentiment_accuracy"] == 0.0


def test_missing_prediction_retains_maud_question():
    """One correct and one missing answer produce half MAUD accuracy."""
    gt = {"maud_clause_labels": {"No-Shop": {"answer": "Yes"}}}
    result = get_suite("merger_agreement").score([gt, gt], [None, {"maud_clauses": ["No-Shop: Yes"]}])
    assert result["n_questions"] == 2
    assert result["maud_question_macro_accuracy"] == 0.5


@pytest.mark.parametrize("predictions", [[None, {"cuad_clauses": ["Alpha may not compete"]}],
                                        [{"cuad_clauses": ["Alpha may not compete"]}]])
def test_missing_or_padded_presence_rows_are_misses(predictions):
    """Missing first or last predictions retain the two-document denominator."""
    gt = {"cuad_clause_labels": {"Non-Compete": [{"text": "Alpha may not compete"}]}}
    result = get_suite("contract").score([gt, gt], predictions)
    assert result["extraction_category_presence"] == 0.5


@pytest.mark.parametrize("task", ["multiclass", "doc_class", "docclass"])
@pytest.mark.parametrize("error", ["ERROR: contract provider unavailable", "ERROR: unavailable"])
def test_dispatch_errors_cannot_become_correct_labels(task, error):
    """Raw error rows are headline misses and excluded from class breakdowns."""
    result = score_task(task, ["contract", "correspondence"], [error, "correspondence"], n_boot=10)
    assert result["accuracy"] == 0.5
    assert set(result["per_class"]) == {"correspondence"}
    if "confusion" in result:
        assert result["confusion"] == {"matrix": [[1]], "labels": ["correspondence"]}


def test_parent_error_cannot_create_perfect_hierarchical_scores():
    """A failed parent prediction cannot contribute a successful subclass row."""
    result = score_task("docclass", ["contract"], ["ERROR: contract unavailable"],
                        expected_subclass=["license"], predicted_subclass=["license"], n_boot=10)
    assert result["accuracy"] == result["subclass_accuracy"] == result["exact_match"] == 0.0
    assert result["per_class"] == result["per_subclass"] == {}


@pytest.mark.parametrize("success", ["none", "stop", " completed "])
@pytest.mark.parametrize("failure", [{"error_class": "TimeoutError"}, {"finish_reason": "length"}])
def test_success_tokens_do_not_mask_independent_failures(success, failure):
    """Inspect each error-bearing field before deciding a record completed."""
    result = summarize_run_completion([{"error": success, **failure}])
    assert (result["n_completed"], result["n_errored"], result["completion_rate"]) == (0, 1, 0.0)
    expected = "TimeoutError" if "error_class" in failure else "LengthFinish"
    assert result["error_class_histogram"] == {expected: 1}


@pytest.mark.parametrize("costs,total,per_doc", [
    ([1.0, 3.0], 4.0, 2.0), ([1.0, 3.0, 2.0], 6.0, 2.0),
    ([None, None], None, None), ([1.0, None], None, None), ([0.0, 0.0], 0.0, 0.0),
])
def test_pooled_cost_requires_complete_run_totals(costs, total, per_doc):
    """Any unknown run cost keeps the pooled total and per-document rate unknown."""
    result = aggregate_serving([{"estimated_cost_usd": c, "cost_basis": "busy_window", "n": 1}
                                for c in costs])
    assert result["estimated_cost_usd"] == total
    assert result["cost_per_document"] == per_doc
