"""DMR-111: distinguish complete run estimates from missing request usage."""

import pytest

from llm_dojo_scoring.cost import estimate_cost
from llm_dojo_scoring.serving import compare_serving, normalize_serving_record


_MODEL = "qwen/qwen3.7-flash"
_USAGE = {"prompt_tokens": 1000, "completion_tokens": 100}


@pytest.mark.parametrize("unknown_first", [False, True])
@pytest.mark.parametrize("explicit_unknown", [False, True])
def test_missing_request_usage_keeps_run_and_comparison_cost_unknown(unknown_first, explicit_unknown):
    """One unobserved request cannot be priced by another request's known tokens."""
    requests = [_USAGE, {}]
    if unknown_first:
        requests.reverse()
    record = {"provider": "openrouter", "model": _MODEL, "n": 2, "requests": requests}
    if explicit_unknown:
        record["estimated_cost_usd"] = None
    normalized = normalize_serving_record(record)
    assert normalized.estimated_cost_usd is None
    assert normalized.cost_basis is None
    comparison = compare_serving([], [record])
    assert comparison["api"]["n_requests"] == 2
    for block in (comparison["api"], comparison["cost"]["api"]):
        assert block["estimated_cost_usd"] is None
        assert block["cost_per_document"] is None
        assert block.get("cost_basis") is None


@pytest.mark.parametrize("recorded_cost", [0.0, 1.25])
def test_recorded_run_cost_does_not_require_per_request_usage(recorded_cost):
    """A recorded whole-run cost remains authoritative when request usage is absent."""
    record = {"provider": "openrouter", "model": _MODEL, "n": 2,
              "requests": [_USAGE, {}], "estimated_cost_usd": recorded_cost,
              "cost_basis": "busy_window"}
    comparison = compare_serving([], [record])
    for block in (comparison["api"], comparison["cost"]["api"]):
        assert block["estimated_cost_usd"] == recorded_cost
        assert block["cost_per_document"] == recorded_cost / 2
        assert block["cost_basis"] == "busy_window"


@pytest.mark.parametrize("requests", [
    [{"prompt_tokens": 1000}],
    [{"completion_tokens": 100}],
    [{"prompt_tokens": 1000}, {"completion_tokens": 100}],
])
def test_one_component_usage_retains_historical_estimation(requests):
    """A recorded input or output component still supports the existing price proxy."""
    record = {"provider": "openrouter", "model": _MODEL, "n": 99,
              "requests": requests, "estimated_cost_usd": None}
    expected = estimate_cost(sum(row.get("prompt_tokens", 0) for row in requests),
                             sum(row.get("completion_tokens", 0) for row in requests), _MODEL)
    comparison = compare_serving([], [record])
    assert comparison["api"]["n_docs"] == 99
    assert comparison["api"]["n_requests"] == len(requests)
    for block in (comparison["api"], comparison["cost"]["api"]):
        assert block["estimated_cost_usd"] == expected
        assert block["cost_per_document"] == round(expected / 99, 8)
        assert block["cost_basis"] == "token_price_estimate"


@pytest.mark.parametrize("zero_usage", [
    {"prompt_tokens": 0}, {"completion_tokens": 0},
    {"prompt_tokens": 0, "completion_tokens": 0},
])
def test_explicit_zero_usage_is_observed_usage(zero_usage):
    """Recorded zero tokens must remain distinct from wholly missing request usage."""
    record = {"provider": "openrouter", "model": _MODEL, "n": 2,
              "requests": [_USAGE, zero_usage], "estimated_cost_usd": None}
    normalized = normalize_serving_record(record)
    assert normalized.estimated_cost_usd == estimate_cost(1000, 100, _MODEL)
    assert normalized.cost_basis == "token_price_estimate"


@pytest.mark.parametrize("explicit_unknown", [False, True])
def test_complete_raw_usage_remains_estimable_with_multiple_documents(explicit_unknown):
    """Missing scalar cost permits complete run pricing even when documents exceed requests."""
    record = {"provider": "openrouter", "model": _MODEL, "n": 10, **_USAGE}
    if explicit_unknown:
        record["estimated_cost_usd"] = None
    comparison = compare_serving([], [record])
    expected = estimate_cost(1000, 100, _MODEL)
    assert comparison["api"]["n_requests"] == 1
    assert comparison["api"]["n_docs"] == 10
    assert comparison["api"]["estimated_cost_usd"] == expected
    assert comparison["cost"]["api"]["cost_per_document"] == round(expected / 10, 8)
    assert comparison["api"]["cost_basis"] == "token_price_estimate"
