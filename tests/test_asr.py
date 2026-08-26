"""WER / CER transcription scorers."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.asr import (
    character_error_rate,
    score_transcription,
    word_accuracy,
    word_error_rate,
)
from llm_dojo_scoring.suites import get_suite
from llm_dojo_scoring.tasks import score_task


def test_identical_strings_are_zero_error():
    ref = "The parties agree to terminate."
    assert word_error_rate(ref, ref) == 0.0
    assert character_error_rate(ref, ref) == 0.0
    assert word_accuracy(ref, ref) == 1.0


def test_one_substitution_wer_is_one_over_n():
    # 4 words; one substitution → 0.25
    assert word_error_rate("the parties agree today", "the parties agree tomorrow") == 0.25


def test_case_and_punctuation_are_normalized():
    assert word_error_rate("Hello, WORLD!", "hello world") == 0.0
    assert character_error_rate("ABC", "abc") == 0.0


def test_empty_reference_conventions():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("hello", "") == 1.0
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("x", "") == 1.0


def test_insertions_can_push_wer_above_one():
    # ref has 1 word; hyp has 3 → 2 insertions / 1 = 2.0
    assert word_error_rate("one two three", "one") == 2.0
    assert word_accuracy("one two three", "one") == 0.0


def test_cer_single_character_substitution():
    assert character_error_rate("bat", "cat") == pytest.approx(1 / 3)


def test_score_transcription_batch_means():
    out = score_transcription(
        ["alpha beta", "one two"],
        ["alpha beta", "one two three"],
    )
    assert out["wer"] > 0.0
    assert out["n"] == 2
    assert out["word_accuracy"] < 1.0


def test_score_task_transcription_alias():
    out = score_task("wer", ["hello world"], ["hello world"])
    assert out["wer"] == 0.0
    assert out["cer"] == 0.0


def test_transcriber_suites_return_wer_cer_and_have_no_honest_gap():
    for agent in ("pdf_transcriber", "image_extractor"):
        suite = get_suite(agent)
        assert suite.honest_gap is None
        names = set(suite.metric_names())
        assert {"wer", "cer", "word_accuracy"} <= names
        out = suite.score(
            "the parties agree to terminate",
            "the parties agree to terminate",
        )
        assert out["accuracy"] == 1.0
        assert out["f1_macro"] == 1.0
        assert out["wer"] == 0.0
        assert out["cer"] == 0.0
        assert out["word_accuracy"] == 1.0

    mismatch = get_suite("pdf_transcriber").score(
        "the parties agree to terminate",
        "the parties refuse to terminate",
    )
    assert mismatch["wer"] > 0.0
    assert mismatch["word_accuracy"] < 1.0
    assert mismatch["cer"] > 0.0
