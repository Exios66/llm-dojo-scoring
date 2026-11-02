"""Calibration and risk math used by the reviewer and extraction-gate scorecards."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.analysis.calibration import (
    auroc,
    brier_score,
    clopper_pearson_upper,
    cross_fit_cutoffs,
    cutoff_at_target,
    cutoff_for_precision,
    expected_calibration_error,
    reliability_bins,
    required_samples,
    spearman,
)


def test_clopper_pearson_upper_matches_the_reviewer_risk_bar():
    """0/299 clears 1%; 0/149 and 1/405 do not."""
    assert clopper_pearson_upper(0, 299) == pytest.approx(0.00997, abs=1e-5)
    assert clopper_pearson_upper(0, 149) == pytest.approx(0.0199, abs=1e-4)
    assert clopper_pearson_upper(1, 405) == pytest.approx(0.0117, abs=1e-4)
    assert clopper_pearson_upper(0, 0) is None


def test_required_samples_matches_the_bound():
    """Zero errors need 299 accepts; one error needs 473."""
    assert required_samples(0, risk=0.01) == 299
    assert required_samples(1, risk=0.01) == 473
    assert required_samples(0, risk=0.02) == 149


def test_required_samples_rejects_bad_inputs():
    """Risk and confidence must be probabilities; errors cannot be negative."""
    with pytest.raises(ValueError):
        required_samples(0, risk=0)
    with pytest.raises(ValueError):
        required_samples(-1)
    with pytest.raises(ValueError):
        clopper_pearson_upper(2, 1)


def test_cutoff_at_target_is_the_lowest_passing_confidence():
    """The lowest cutoff whose accepted set reaches the target wins."""
    rows = [(0.5, False), (0.7, False), (0.8, True), (0.9, True)]
    assert cutoff_at_target(rows, 0.95) == 0.8
    assert cutoff_at_target([(0.9, False), (0.5, False)], 1.0) is None


def test_cross_fit_reports_held_out_accuracy_and_interval():
    """Five-fold cross-fit scores every held-out row once."""
    rows = [(0.9, True)] * 100 + [(0.5, False)] * 20
    out = cross_fit_cutoffs(rows, target=0.95)
    assert out["cutoff"] == 0.9
    assert out["holdout_accepted"] > 0
    assert out["holdout_accuracy"] == 1.0
    assert out["meets_target"] is True
    assert out["holdout_accuracy_ci"]["lo"] >= 0.95


def test_ece_and_brier_are_zero_for_a_perfect_calibration():
    """A perfectly confident correct set has no calibration error."""
    pairs = [(1.0, True), (1.0, True), (0.0, False), (0.0, False)]
    assert expected_calibration_error(pairs) == 0.0
    assert brier_score(pairs) == 0.0


def test_ece_and_brier_penalize_confident_errors():
    """A wrong answer at full confidence carries the maximum gap."""
    pairs = [(1.0, False), (0.0, True)]
    assert expected_calibration_error(pairs) == 1.0
    assert brier_score(pairs) == 1.0


def test_reliability_bins_report_counts_and_gaps():
    """Every bin is present, including empty ones."""
    bins = reliability_bins([(1.0, True), (0.49, False)], bins=2)
    assert len(bins) == 2
    assert bins[0]["n"] == 1 and bins[0]["accuracy"] == 0.0
    assert bins[1]["n"] == 1 and bins[1]["accuracy"] == 1.0


def test_auroc_and_spearman_rank_discrimination():
    """AUROC handles ties; Spearman handles monotone and constant axes."""
    assert auroc([0.9, 0.8, 0.2], [True, True, False]) == 1.0
    assert auroc([0.5, 0.5], [True, False]) == 0.5
    assert auroc([0.5], [True]) is None
    assert spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_cutoff_for_precision_keeps_the_most_coverage():
    """The lowest cutoff meeting target precision is returned."""
    cut = cutoff_for_precision([0.9, 0.8, 0.7, 0.1], [True, True, False, False], 0.9)
    assert cut == {"cutoff": 0.8, "precision": 1.0, "accept_rate": 0.5, "recall": 1.0}
    assert cutoff_for_precision([0.1], [True], 1.0)["cutoff"] == 0.1


# --- PR #103 review regressions -------------------------------------------


def test_clopper_pearson_upper_does_not_overflow_on_large_error_counts():
    """``math.comb(10**6, 67)`` exceeds float range; the Beta form must not."""
    big = clopper_pearson_upper(250, 3000)
    assert 250 / 3000 < big < 0.1
    huge = clopper_pearson_upper(200, 1_000_000)
    assert 200 / 1_000_000 < huge < 0.001


def test_clopper_pearson_upper_boundaries():
    """All errors gives 1.0; a higher confidence gives a looser bound."""
    assert clopper_pearson_upper(5, 5) == 1.0
    assert clopper_pearson_upper(1, 473) == pytest.approx(0.00999, abs=1e-5)
    assert clopper_pearson_upper(0, 135) == pytest.approx(0.0219, abs=1e-4)
    assert clopper_pearson_upper(3, 100, confidence=0.99) > clopper_pearson_upper(3, 100)
    with pytest.raises(ValueError):
        clopper_pearson_upper(1, 10, confidence=1.0)


def test_required_samples_handles_many_errors_without_raising():
    """80 wrong accepts used to overflow inside the 1e6 probe."""
    needed = required_samples(80)
    assert isinstance(needed, int)
    assert clopper_pearson_upper(80, needed) <= 0.01
    assert clopper_pearson_upper(80, needed - 1) > 0.01


def test_required_samples_returns_none_past_the_search_cap():
    """More errors than the one-million cap can never clear the bar: ``None``."""
    assert required_samples(2_000_000) is None


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.5])
def test_required_samples_validates_confidence_with_zero_errors(confidence):
    """The zero-error closed form used to skip confidence validation."""
    with pytest.raises(ValueError):
        required_samples(0, confidence=confidence)


def test_cross_fit_cutoffs_applies_its_confidence_level():
    """A 99% interval is wider than a 95% one and can fail the target."""
    rows = [(0.9, True)] * 100 + [(0.5, False)] * 20
    at_95 = cross_fit_cutoffs(rows, target=0.95)
    at_99 = cross_fit_cutoffs(rows, target=0.95, confidence=0.99)
    assert at_95["holdout_accuracy_ci"]["z"] == pytest.approx(1.959964, abs=1e-6)
    assert at_99["holdout_accuracy_ci"]["z"] == pytest.approx(2.575829, abs=1e-6)
    assert at_99["holdout_accuracy_ci"]["lo"] < at_95["holdout_accuracy_ci"]["lo"]
    assert at_95["meets_target"] is True
    assert at_99["meets_target"] is False


def test_cross_fit_cutoffs_rejects_an_invalid_confidence():
    """A confidence outside (0, 1) is rejected."""
    with pytest.raises(ValueError):
        cross_fit_cutoffs([(0.9, True)] * 10, confidence=1.5)
