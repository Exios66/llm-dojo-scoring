import pandas as pd
import pytest

from llm_dojo_scoring import error_analysis as ea
from llm_dojo_scoring.io import normalize_results_frame


@pytest.fixture
def df(sorter_frame) -> pd.DataFrame:
    return normalize_results_frame(sorter_frame)


def test_best_run(df):
    best = ea.best_run(df)
    assert best["Experiment Name"] == "qwen3.7-flash_sorter_v13_subtype_langfuse"
    assert best["Subtype Accuracy"] == pytest.approx(0.9430)
    assert ea.best_run(df, min_n=1000) is None


def test_runner_up(df):
    runner = ea.runner_up(df)
    assert runner["Prompt Version"] == "v14"


def test_prompt_version_summary(df):
    summary = ea.prompt_version_summary(df)
    assert list(summary.columns) == [
        "prompt_version", "n_runs", "mean", "best", "worst", "spread", "best_run", "best_n",
    ]
    v13 = summary[summary["prompt_version"] == "v13"].iloc[0]
    # v13 runs: qwen .9430, gpt-5-nano .8978, deepseek .9253, rerun .9350
    assert v13["n_runs"] == 4
    assert v13["mean"] == pytest.approx((0.9430 + 0.8978 + 0.9253 + 0.9350) / 4,
                                        abs=5e-5)


def test_model_summary(df):
    summary = ea.model_summary(df)
    qwen = summary[summary["model"] == "Qwen 3.7-Flash"].iloc[0]
    assert qwen["n_runs"] == 6


def test_metric_trend(df):
    trend = ea.metric_trend(df)
    assert "lo" in trend.columns and "hi" in trend.columns
    assert len(trend) == len(df)
    # lo <= metric <= hi for every row
    for _, row in trend.iterrows():
        assert row["lo"] <= row["Subtype Accuracy"] <= row["hi"]


def test_failure_mode_summary(df):
    modes = ea.failure_mode_summary(df)
    assert list(modes.index) == ["equivalent_family", "family_confusion",
                                 "function_over_form", "other_fallback"]
    assert modes.loc["family_confusion", "n_total"] == 29 * len(df)
    assert modes["pct_of_failures"].sum() == pytest.approx(1.0)


def test_per_subtype_summary(df):
    summary = ea.per_subtype_summary(df)
    assert "franchise" in summary.index
    assert summary.loc["franchise", "mean"] < summary.loc["license", "mean"]


def test_subtype_hotspots(df):
    hotspots = ea.subtype_hotspots(df, k=3)
    assert len(hotspots) == 3
    assert hotspots.iloc[0].name in ("franchise", "hosting")


def test_regression_alerts(df):
    alerts = ea.regression_alerts(df, threshold=0.005)
    # v13 0.9430 -> rerun 0.9350 = -0.008 (flagged); v12 0.9234 -> bug 0.88 = -0.0434
    assert len(alerts) == 2


def test_reliability_assessment(df):
    rel = ea.reliability_assessment(df)
    assert rel["n_runs"] == 8
    # halves: v9 .0289, v12 .0236, v13 .022, gpt .0278, deepseek .025,
    #         rerun .023, v14 .023, bug .03 -> median (.0236+.025)/2
    assert rel["median_ci_half"] == pytest.approx((0.0236 + 0.025) / 2)
    assert rel["runs_with_ci_pct"] == 1.0


def test_require_metric_raises(df):
    with pytest.raises(ValueError):
        ea.require_metric(df, "No Such Metric")


def test_real_workbook_analysis(real_artifacts):
    from llm_dojo_scoring.io import read_workbook

    result = read_workbook(real_artifacts["results"])
    df = normalize_results_frame(result.frame)
    best = ea.best_run(df)
    assert best is not None
    # Global best is a 1.0 pilot run; among full-sample runs (n>=100) the max
    # is the reference workbook's champion.
    best_full = ea.best_run(df, min_n=100)
    expected = df.loc[df["n"] >= 100, "Subtype Accuracy"].max()
    assert best_full["Subtype Accuracy"] == pytest.approx(expected)
    assert ea.failure_mode_summary(df).loc["family_confusion", "n_total"] > 0
    assert len(ea.per_subtype_summary(df)) >= 20