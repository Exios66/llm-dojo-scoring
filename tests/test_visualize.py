"""Check headless result plots, optional data handling, and PNG export."""

import matplotlib

matplotlib.use("Agg")

import pytest
from matplotlib.figure import Figure

from llm_dojo_scoring import visualize as viz
from llm_dojo_scoring.io import normalize_results_frame


@pytest.fixture
def df(sorter_frame):
    """Normalize the sorter result fixture for visualization tests."""
    return normalize_results_frame(sorter_frame)


def test_plot_metric_ci(df):
    """Build a Matplotlib figure for metric confidence intervals."""
    fig = viz.plot_metric_ci(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_prompt_version(df):
    """Build a Matplotlib figure comparing prompt versions."""
    fig = viz.plot_prompt_version(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_model(df):
    """Build a Matplotlib figure comparing model results."""
    fig = viz.plot_model_comparison(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_per_subtype_heatmap(df):
    """Build a subtype heatmap figure limited to the top four runs."""
    fig = viz.plot_per_subtype_heatmap(df, runs=4)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_failure_modes(df):
    """Build a Matplotlib figure summarizing failure modes."""
    fig = viz.plot_failure_modes(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_confidence_scatter(df):
    """Build a Matplotlib figure relating confidence to results."""
    fig = viz.plot_confidence_scatter(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_plot_cost(df):
    """Build a Matplotlib figure for cost efficiency."""
    fig = viz.plot_cost_efficiency(df)
    assert isinstance(fig, Figure)
    matplotlib.pyplot.close(fig)


def test_build_all_plots_and_save(df, tmp_path):
    """Build the six default plot types and export each as a PNG."""
    plots = viz.build_all_plots(df)
    assert set(plots) == {"metric_ci", "prompt_version", "model",
                          "per_subtype", "failure_modes", "confidence"}
    paths = viz.save_plots(plots, str(tmp_path))
    assert len(paths) == len(plots)
    for p in paths:
        assert p.endswith(".png")


def test_build_all_plots_with_cost(df, tmp_path):
    """Include the optional cost plot when a cost column is supplied."""
    plots = viz.build_all_plots(df, cost_column="Cost Estimated USD")
    assert "cost" in plots


def test_missing_column_skips():
    """Keep supported metric plots while skipping subtype plots without required columns."""
    import pandas as pd

    minimal = pd.DataFrame({"Subtype Accuracy": [0.9], "Experiment Name": ["x"]})
    plots = viz.build_all_plots(minimal)
    assert "metric_ci" in plots  # requires only the metric + name
    assert "per_subtype" not in plots
