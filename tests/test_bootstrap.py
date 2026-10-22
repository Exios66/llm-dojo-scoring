"""Check confidence interval bounds, reproducibility, and insufficient-sample handling."""
import pytest

from llm_dojo_scoring.bootstrap import bootstrap_ci, delta_significance, wilson_ci


def test_bootstrap_ci_single_value_returns_none():
    """Decline bootstrap intervals for empty or singleton samples."""
    assert bootstrap_ci([1.0]) is None
    assert bootstrap_ci([]) is None


def test_bootstrap_ci_range_and_keys():
    """Return bounded bootstrap intervals with sample and method metadata."""
    ci = bootstrap_ci([1.0, 0.0, 1.0, 1.0], n_boot=500)
    assert ci is not None
    assert 0.0 <= ci["lo"] <= ci["hi"] <= 1.0
    assert set(ci) >= {"lo", "hi", "half", "n", "seed", "n_boot", "method"}
    assert ci["n"] == 4


def test_bootstrap_ci_deterministic():
    """Reproduce bootstrap intervals when the random seed is fixed."""
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert bootstrap_ci(values, seed=42) == bootstrap_ci(values, seed=42)


def test_delta_significance():
    """Detect a positive significant difference between separated constant samples."""
    a = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    b = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = delta_significance(a, b, n_boot=500)
    assert out is not None
    assert out["delta"] > 0
    assert out["significant"] is True
    assert out["n_a"] == len(a) and out["n_b"] == len(b)


def test_delta_significance_too_small():
    """Decline significance estimates when either sample is too small."""
    assert delta_significance([1.0], [1.0, 0.0]) is None


def test_wilson_ci():
    """Bracket the observed rate with a Wilson interval and reject zero observations."""
    ci = wilson_ci(0.9, 100)
    assert ci is not None
    assert ci["lo"] < 0.9 < ci["hi"]
    assert ci["half"] == pytest.approx((ci["hi"] - ci["lo"]) / 2)
    assert wilson_ci(0.9, 0) is None
