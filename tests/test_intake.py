"""Intake clerk — deterministic prep steps + scoring against clerk gold."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.intake import (
    INTAKE_LIVE_METHOD,
    INTAKE_METHODS,
    INTAKE_PREP_STEPS,
    INTAKE_SPAN,
    INTAKE_SPAN_KEYS,
    apply_intake,
    deterministic_normalize,
    intake_prep_completeness,
    looks_messy,
    score_intake,
)
from llm_dojo_scoring.mailroom import INTAKE_HANDOFF_NODE, observation_type_for
from llm_dojo_scoring.profiles import get_profile
from llm_dojo_scoring.suites import get_suite
from llm_dojo_scoring.tasks import score_task


def test_normalize_collapses_nbsp_and_unwraps_hyphens():
    cleaned, stats = deterministic_normalize("A\u00a0B\n\n\n\nagree-\nment")
    assert "A B" in cleaned
    assert "agreement" in cleaned
    assert stats["changed"] is True
    assert stats["hyphen_unwraps"] >= 1
    assert looks_messy("x\n" * 30) is True
    clean, st = deterministic_normalize("Hello world.\n\n1. Clause.")
    assert looks_messy(clean, st) is False


def test_empty_text_is_not_messy():
    cleaned, stats = deterministic_normalize("")
    assert cleaned == ""
    assert stats["changed"] is False
    assert looks_messy(cleaned, stats) is False


def test_normalize_is_idempotent():
    raw = "Hello   world.\r\n\r\n\r\nagree-\nment\n"
    once, _ = deterministic_normalize(raw)
    twice, stats = deterministic_normalize(once)
    assert once == twice
    assert stats["changed"] is False


def test_markdown_table_rows_keep_internal_spaces():
    raw = "| col  a | col  b |\n\n\nNext."
    cleaned, _ = deterministic_normalize(raw)
    assert "| col  a | col  b |" in cleaned


def test_apply_intake_payload_has_eval_keys():
    cleaned, stats = apply_intake("A\n\n\n\nB", filename="x.txt")
    for key in INTAKE_SPAN_KEYS:
        assert key in stats
    assert stats["method"] == INTAKE_LIVE_METHOD
    assert cleaned == "A\n\nB"


def test_prep_completeness_fails_when_wraps_remain():
    dirty = "agree-\nment\n\n\n\nNext"
    assert intake_prep_completeness(dirty) < 1.0
    cleaned, _ = deterministic_normalize(dirty)
    assert intake_prep_completeness(cleaned) == 1.0


def test_score_intake_clerk_against_itself():
    raw = "A\u00a0B\n\n\n\nagree-\nment"
    cleaned, stats = apply_intake(raw)
    out = score_intake(raw, cleaned)
    assert out["accuracy"] == 1.0
    assert out["f1_macro"] == 1.0
    assert out["intake_prep_completeness"] == 1.0
    assert out["intake_changed"] is True
    assert out["intake_hyphen_unwraps"] == stats["hyphen_unwraps"]


def test_score_intake_detects_skipped_prep():
    raw = "Hello   world.\n\n\n\nNext"
    out = score_intake(raw, raw)
    assert out["accuracy"] == 0.0
    assert out["intake_prep_completeness"] < 1.0


def test_llm_intake_scored_against_clerk_gold():
    raw = "The par-\nties agree."
    gold, _ = apply_intake(raw)
    llm_cleaned = "The parties agree."  # LLM also unwrapped
    out = score_intake(raw, {"text": llm_cleaned, "method": "llm", "changed": True})
    assert out["intake_method"] == "llm"
    assert out["intake_method_valid"] == 1.0
    assert out["accuracy"] == 1.0
    assert gold == llm_cleaned


def test_span_payload_without_text_scores_flags():
    raw = "A\n\n\n\nB"
    _, gold_stats = apply_intake(raw)
    payload = {k: gold_stats[k] for k in INTAKE_SPAN_KEYS}
    out = score_intake(raw, payload)
    assert out["intake_changed_match"] == 1.0
    assert out["intake_messy_match"] == 1.0
    assert out["intake_hyphen_unwraps_match"] == 1.0


def test_suite_and_profile_are_computable_prep_not_cost():
    profile = get_profile("intake")
    assert profile.tasks == ("prepare", "normalize")
    assert profile.metrics_bundle == "intake"
    assert profile.ground_truth is True
    assert profile.extras["span"] == INTAKE_SPAN
    assert profile.extras["handoff_node"] == INTAKE_HANDOFF_NODE
    assert profile.extras["handoff_agent"] == "sorter"
    assert set(profile.extras["methods"]) == set(INTAKE_METHODS)
    assert tuple(profile.extras["prep_steps"]) == INTAKE_PREP_STEPS
    assert observation_type_for(INTAKE_SPAN) == "span"

    suite = get_suite("intake")
    assert suite.kind == "intake"
    assert suite.computable is True
    assert suite.task_key == "intake"
    names = set(suite.metric_names())
    assert {
        "intake_prep_completeness",
        "intake_changed_rate",
        "intake_messy_rate",
        "intake_hyphen_unwraps",
        "intake_collapsed_blanks",
    } <= names

    raw = "Hello   world."
    cleaned, _ = apply_intake(raw)
    scored = suite.score(raw, cleaned)
    assert scored["accuracy"] == 1.0
    assert scored["intake_changed_rate"] == 1.0


def test_score_task_intake_and_missing_inputs():
    raw = "x  y"
    cleaned, _ = apply_intake(raw)
    out = score_task("intake", [raw], [cleaned])
    assert out["n"] == 1
    assert out["accuracy"] == 1.0
    with pytest.raises(TypeError, match="raw text"):
        get_suite("intake").score(None, None)
