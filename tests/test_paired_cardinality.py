"""Independent regressions for cardinality and preserved scoring semantics."""

import pytest

from llm_dojo_scoring import classification as c
from llm_dojo_scoring.asr import score_transcription
from llm_dojo_scoring.content_scoring import (
    score_content_topic, score_sentiment, score_maud_extraction,
)
from llm_dojo_scoring.mailroom import score_aligned_classification
from llm_dojo_scoring.tasks import score_task, multiclass_score, contracteval_metrics


@pytest.mark.parametrize("metric", [
    c.accuracy, c.per_class_stats, c.macro_accuracy, c.confusion_matrix,
    c.macro_prf, score_aligned_classification, score_content_topic,
    score_sentiment, multiclass_score,
])
@pytest.mark.parametrize("sizes", [(2, 1), (1, 2), (0, 1), (1, 0)])
def test_paired_metrics_reject_missing_or_extra_rows(metric, sizes):
    """Both lengths must be reported before empty/error rows can hide a mismatch."""
    ne, np = sizes
    with pytest.raises(ValueError, match=rf"expected.*{ne}.*predicted.*{np}"):
        metric(["contract"] * ne, ["ERROR: unavailable"] * np)


@pytest.mark.parametrize("sizes", [(2, 1), (1, 2), (0, 1), (1, 0)])
def test_binary_rejects_mismatched_rows(sizes):
    """Binary counts cannot silently discard positive or negative documents."""
    ne, np = sizes
    with pytest.raises(ValueError, match=rf"expected.*{ne}.*predicted.*{np}"):
        c.binary_metrics([True] * ne, [False] * np, positive="yes", normalize=False)


@pytest.mark.parametrize("task", [
    "multiclass", "legalbench", "docclass", "pipeline", "maud_question",
    "enron_topic", "enron_sentiment", "transcription", "contracteval",
])
def test_dispatch_rejects_mismatched_documents(task):
    """Dispatch preserves the document-pair contract for every paired task kind."""
    with pytest.raises(ValueError, match=r"expected.*2.*predicted.*1"):
        score_task(task, ["yes", "no"], ["yes"])


@pytest.mark.parametrize("task", ["docclass", "pipeline"])
@pytest.mark.parametrize("exp_sub,pred_sub", [(["a"], ["a", "b"]), (["a"], ["a"])])
def test_subclasses_match_each_other_and_document_count(task, exp_sub, pred_sub):
    """Subclass arrays must cover the same documents as the parent labels."""
    with pytest.raises(ValueError, match=r"expected.*\d.*predicted.*\d"):
        score_task(task, ["contract"] * 2, ["contract"] * 2,
                   expected_subclass=exp_sub, predicted_subclass=pred_sub)


@pytest.mark.parametrize("sizes", [(2, 1), (1, 2), (0, 1), (1, 0)])
def test_transcription_batch_rejects_unequal_lists(sizes):
    """An absent OCR result must fail rather than improve the mean error rate."""
    ne, np = sizes
    with pytest.raises(ValueError, match=rf"expected.*{ne}.*predicted.*{np}"):
        score_transcription(["a"] * ne, ["a"] * np)


@pytest.mark.parametrize("sizes", [(2, 1), (1, 2), (0, 1), (1, 0)])
def test_maud_document_batches_reject_unequal_lists(sizes):
    """Only real batches of document dictionaries require equal cardinality."""
    ne, np = sizes
    with pytest.raises(ValueError, match=rf"expected.*{ne}.*predicted.*{np}"):
        score_maud_extraction([{"Type of Consideration": "All Cash"}] * ne,
                              [{"Type of Consideration": "All Cash"}] * np)


def test_equal_classification_manual_counts_and_error_policy():
    """A three-row confusion matrix yields two hits; error rows remain excluded."""
    exp, pred = ["a", "a", "b"], ["a", "b", "b"]
    assert c.accuracy(exp, pred) == 0.6667
    assert c.macro_accuracy(exp, pred) == 0.75
    assert c.confusion_matrix(exp, pred) == ([[1, 1], [0, 1]], ["a", "b"])
    assert c.per_class_stats(exp, pred)["a"]["recall"] == 0.5
    assert c.macro_prf(exp, pred)["f1_macro"] == 0.6667
    assert c.binary_metrics(exp, pred, positive="b")["tp"] == 1
    assert c.binary_metrics(exp, pred, positive="b")["fp"] == 1
    assert c.accuracy(["a", "b"], ["a", "ERROR: unavailable"]) == 1.0
    assert score_task("multiclass", exp, pred, n_boot=10)["accuracy"] == 0.6667
    assert score_aligned_classification(exp, pred)["n_exact"] == 2
    assert c.accuracy([], []) == 0.0


def test_content_generators_preserve_all_pairs():
    """Two sentiment rows yield one hit and a hand-computed macro F1 of one third."""
    result = score_sentiment(iter(["positive", "negative"]), iter(["pos", "positive"]))
    assert result["n"] == 2
    assert result["accuracy"] == 0.5
    assert result["f1_macro"] == 0.3333


def test_transcription_manual_values_and_scalar_forms():
    """One substitution across two equal-weight documents gives mean WER 0.25."""
    result = score_transcription(["a b", "c"], ["a x", "c"])
    assert result["wer"] == 0.25
    assert result["cer"] == 0.1667
    assert result["word_accuracy"] == 0.75
    assert result["n"] == 2
    assert score_transcription("a b", "a x")["wer"] == 0.5
    assert score_transcription(["a"], "a")["n"] == 1
    assert score_transcription([], [])["n"] == 0


def test_maud_unequal_spans_are_one_document():
    """Missing one answer lowers question accuracy instead of rejecting span lists."""
    exp = ["Type of Consideration: All Cash", "Custom question: Yes"]
    result = score_maud_extraction(exp, exp[:1])
    assert result["n_documents"] == 1
    assert result["n_questions"] == 2
    assert result["maud_question_accuracy"] == 0.5
    assert score_task("maud_extraction", exp, exp[:1])["maud_question_accuracy"] == 0.5


def test_maud_mixed_batch_and_scalar_broadcast_remains_supported():
    """Existing scalar predictions broadcast across expected document dictionaries."""
    result = score_maud_extraction(
        [{"Type of Consideration": "All Cash"}] * 2,
        {"Type of Consideration": "All Cash"},
    )
    assert result["n_documents"] == 2
    assert result["maud_question_accuracy"] == 1.0


def test_direct_contracteval_rejects_incomplete_outputs():
    """The direct benchmark surface shares the same document cardinality contract."""
    with pytest.raises(ValueError, match=r"expected.*2.*predicted.*1"):
        contracteval_metrics([["a"], ["b"]], ["a"])


@pytest.mark.parametrize("metric", [score_sentiment, score_content_topic, score_aligned_classification])
def test_iterable_pairs_reject_truncation(metric):
    """One-shot iterators must be fully counted before paired scoring starts."""
    with pytest.raises(ValueError, match=r"expected.*2.*predicted.*1"):
        metric(iter(["a", "b"]), iter(["a"]))


def test_maud_json_batches_obey_cardinality():
    """JSON decoding must retain the same document-batch guard as native lists."""
    with pytest.raises(ValueError, match=r"expected.*2.*predicted.*1"):
        score_task("maud_extraction", '[{"Q": "a"}, {"Q": "b"}]', '[{"Q": "a"}]')


def test_maud_mixed_list_forms_keep_existing_interpretation():
    """A batch on one side and span strings on the other keeps prior dispatch."""
    result = score_maud_extraction(
        [{"Type of Consideration": "All Cash"}] * 2,
        ["Type of Consideration: All Cash"],
    )
    assert result["n_documents"] == 1
    assert result["n_questions"] == 1
    assert result["maud_question_accuracy"] == 1.0
