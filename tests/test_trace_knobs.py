"""Confidence / reasoning captured as experimental knobs, never scored."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.config import (
    TraceKnobSettings,
    clear_settings_cache,
    configure,
    configure_from_taxonomy,
    get_settings,
)
from llm_dojo_scoring.field_scoring import score_category_presence, score_extraction
from llm_dojo_scoring.trace_knobs import (
    capture_trace_knobs,
    confidence_calibration_error,
    parse_confidence,
    parse_reasoning,
)


@pytest.fixture(autouse=True)
def _restore_settings():
    """Clear the cached settings after each test so knob overrides don't leak."""
    yield
    clear_settings_cache()


def test_parse_confidence_and_reasoning():
    """Confidence and reasoning parsing coerce model output to the stable shapes."""
    assert parse_confidence(0.91) == 0.91
    assert parse_confidence("91") == 0.91
    assert parse_confidence({"confidence": 0.4}) == 0.4
    assert parse_confidence("nope") is None
    assert parse_reasoning("cited clause 7.1")["summary"] == "cited clause 7.1"
    parsed = parse_reasoning(
        {"summary": "found in 7.1", "entries": [{"field": "Anti-Assignment", "evidence": "shall not assign"}]}
    )
    assert parsed["entries"][0]["field"] == "Anti-Assignment"
    assert len(parsed["entries"]) == 1


def test_capture_does_not_enter_overall_score():
    """``confidence`` / ``reasoning`` never score as fields, only land in ``trace``."""
    result = score_extraction(
        "contract",
        {"document_name": "name"},
        {"document_name": "MSA", "confidence": 0.99, "reasoning": {"summary": "title page"}},
        {"document_name": "MSA", "confidence": 0.1, "reasoning": {"summary": "gt"}},
    )
    assert "confidence" not in result.field_scores
    assert "reasoning" not in result.field_scores
    assert result.overall_score == 1.0
    assert result.trace["confidence"] == 0.99
    assert result.trace["reasoning"]["summary"] == "title page"
    assert result.trace["calibration_error"] == pytest.approx(0.01)
    assert result.trace["confidence_gate"] == "pass"


def test_confidence_min_and_band_are_adjustable():
    """``confidence_min`` and ``confidence_band`` knobs change the confidence gate."""
    configure(trace_knobs__confidence_min=0.8)
    low = capture_trace_knobs({"confidence": 0.4})
    assert low["confidence_gate"] == "below_min"
    configure(trace_knobs__confidence_min=None, trace_knobs__confidence_band=(0.5, 0.85))
    band = capture_trace_knobs({"confidence": 0.6})
    assert band["confidence_gate"] == "in_band"
    high = capture_trace_knobs({"confidence": 0.9})
    assert high["confidence_gate"] == "pass"


def test_capture_can_be_turned_off():
    """Turning off capture knobs nulls out confidence / reasoning / entry count."""
    configure(trace_knobs__capture_confidence=False, trace_knobs__capture_reasoning=False)
    out = capture_trace_knobs(
        {"confidence": 0.99, "reasoning": "lots of prose"},
        correctness=1.0,
    )
    assert out["confidence"] is None
    assert out["reasoning"] is None
    assert out["n_reasoning_entries"] is None


def test_missing_confidence_assume_modes():
    """``assume_1`` / ``assume_0`` fill a missing confidence for gating only."""
    configure(trace_knobs__missing_confidence="assume_1")
    out = capture_trace_knobs({}, correctness=0.0)
    assert out["confidence"] is None
    assert out["confidence_gate"] == "pass"
    configure(trace_knobs__missing_confidence="assume_0", trace_knobs__confidence_min=0.5)
    gated = capture_trace_knobs({})
    assert gated["confidence_gate"] == "below_min"


def test_yaml_taxonomy_wires_trace_knobs():
    """``trace_knobs:`` in a taxonomy YAML dict wires through to settings and capture."""
    configure_from_taxonomy(
        {
            "trace_knobs": {
                "confidence_min": 0.7,
                "reasoning_routes_presence": False,
                "compute_calibration_error": False,
            }
        }
    )
    knobs = get_settings().trace_knobs
    assert knobs.confidence_min == 0.7
    assert knobs.reasoning_routes_presence is False
    assert knobs.compute_calibration_error is False
    captured = capture_trace_knobs({"confidence": 0.9}, correctness=1.0)
    assert captured["calibration_error"] is None


def test_reasoning_routes_presence_knob():
    """Disabling ``reasoning_routes_presence`` stops reasoning entries from routing CUAD matches."""
    anti = "NEITHER PARTY SHALL ASSIGN THIS AGREEMENT"
    predicted = {
        "cuad_clauses": ["an unrelated exclusivity provision"],
        "reasoning": {
            "entries": [{"field": "Anti-Assignment", "evidence": anti, "section_ref": "7.1"}],
        },
    }
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": anti, "field": "cuad_clauses"},
    }
    field_types = {"cuad_clauses": "entity_list:free_text"}
    score, _ = score_category_presence(predicted, expectations, field_types)
    assert score == 1.0
    configure(trace_knobs__reasoning_routes_presence=False)
    score_off, detail = score_category_presence(predicted, expectations, field_types)
    assert score_off == 0.0
    assert detail["Anti-Assignment"]["matched"] is False


def test_calibration_error_helper():
    """``confidence_calibration_error`` is the absolute gap, or ``None`` when confidence is missing."""
    assert confidence_calibration_error(0.9, 1.0) == pytest.approx(0.1)
    assert confidence_calibration_error(None, 1.0) is None


def test_configure_nested_trace_knob_settings_object():
    """``configure`` accepts a full ``TraceKnobSettings`` object for ``trace_knobs``."""
    knobs = TraceKnobSettings(confidence_min=0.55, capture_reasoning=False)
    configure(trace_knobs=knobs)
    assert get_settings().trace_knobs.confidence_min == 0.55
    assert get_settings().trace_knobs.capture_reasoning is False
