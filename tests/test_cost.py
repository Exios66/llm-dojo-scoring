import pytest

from llm_dojo_scoring.cost import (
    estimate_cost,
    estimate_for_record,
    price_for,
    resolve_cost_basis,
    tokens_summary,
)


def test_price_for_known_and_prefix():
    assert price_for("qwen/qwen3.7-flash") == (0.03, 0.13)
    assert price_for("qwen/qwen3.7-flash-20260727") == (0.03, 0.13)
    assert price_for("unknown/model") is None
    assert price_for(None) is None


def test_estimate_cost():
    # 1M prompt tokens in + 1M completion out for qwen -> 0.03 + 0.13
    assert estimate_cost(1_000_000, 1_000_000, "qwen/qwen3.7-flash") == pytest.approx(0.16)
    assert estimate_cost(100, 50, "unknown/model") is None
    assert estimate_cost(0, 0, "qwen/qwen3.7-flash") is None


def test_tokens_summary():
    """Aggregates usage rows and derives both billed and estimated cost."""
    usage = [
        {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01},
        {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.03},
    ]
    summary = tokens_summary(usage, model="qwen/qwen3.7-flash")
    assert summary["prompt_tokens"] == 200
    assert summary["completion_tokens"] == 100
    assert summary["total_tokens"] == 300
    assert summary["cost_total_usd"] == pytest.approx(0.04)
    assert summary["cost_usd"] == pytest.approx(0.02)
    assert summary["rows_with_usage"] == 2
    assert summary["cost_estimated_usd"] == pytest.approx(
        (200 * 0.03 + 100 * 0.13) / 1_000_000
    )
    assert summary["cost_basis"] == "busy_window"


def test_estimate_for_record():
    """Estimates total and per-doc cost for a usage record."""
    record = {
        "model": "qwen/qwen3.7-flash",
        "n_rows": 509,
        "tokens": {"total": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}},
    }
    out = estimate_for_record(record)
    assert out["cost_estimated_usd"] == pytest.approx(0.16)
    assert out["per_doc_usd"] == pytest.approx(0.16 / 509, abs=1e-6)
    assert out["cost_basis"] == "busy_window"


def test_tokens_summary_requires_single_cost_basis():
    """Mixed labeled / unlabeled cost_basis rows raise instead of silently picking one."""
    summary = tokens_summary(
        [{"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}]
    )
    assert summary["cost_basis"] == "busy_window"
    with pytest.raises(ValueError, match="cost_basis mixed"):
        tokens_summary(
            [
                {"cost_basis": "busy_window", "prompt_tokens": 1},
                {"usd_basis": "billed_incl_cold", "prompt_tokens": 1},
            ]
        )


def test_resolve_cost_basis_rejects_mixed_labeled_and_unlabeled():
    """All-unlabeled rows default to busy_window; mixed labeled/unlabeled rows raise."""
    assert resolve_cost_basis([{"prompt_tokens": 1}, {"prompt_tokens": 2}]) == "busy_window"
    assert resolve_cost_basis(
        [{"cost_basis": "billed_incl_cold", "prompt_tokens": 1}]
    ) == "billed_incl_cold"
    with pytest.raises(ValueError, match="labeled and unlabeled"):
        resolve_cost_basis(
            [
                {"cost_basis": "busy_window", "prompt_tokens": 1},
                {"prompt_tokens": 1},
            ]
        )