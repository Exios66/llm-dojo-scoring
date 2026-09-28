"""Visualization for evaluation results (matplotlib).

All functions take a normalized results frame (see
:mod:`llm_dojo_scoring.io.normalize_results_frame`) — or, for the mailroom
views, plain label / score lists — and return a ``matplotlib.figure.Figure``;
the CLI saves them to PNG. Backend is left to the caller (CLI and tests force
Agg for headless use).

Design tokens (0.17.0 refresh): one validated categorical order (colour-blind
adjacent ΔE ≥ 9 on the light surface), a single-hue sequential ramp for
magnitude (heatmaps, confusion matrices — no red/green), recessive grids and
axes, text in ink tokens (never the series colour), and legends whenever two
or more series share a plot. Axes adapt to the metric's scale: 0–1 metrics
render as percentages, anything else as plain numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from . import error_analysis as ea
from .config import PER_SUBTYPE

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8984"
GRID = "#e6e5e1"

#: Categorical order — fixed, never cycled. A 9th series folds into "Other".
SERIES: tuple[str, ...] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
)
OTHER = "#b4b2ab"

#: Single-hue (blue) sequential ramp, light → dark.
SEQUENTIAL: tuple[str, ...] = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)
EMPHASIS = SERIES[0]          # the best run / the highlighted bar
SUPPORT = SEQUENTIAL[3]       # every other bar (same hue family, recessive)
_SEQ_CMAP = LinearSegmentedColormap.from_list("dojo_blue", ("#f4f8fd", *SEQUENTIAL))

# Kept for backwards compatibility with callers that imported the old names.
_BEST_COLOR = EMPHASIS
_OTHER_COLOR = SUPPORT
_FAIL_COLOR = SERIES[7]


def _series_colors(n: int) -> list[str]:
    """First ``n`` categorical slots in fixed order (``OTHER`` past eight)."""
    return [SERIES[i] if i < len(SERIES) else OTHER for i in range(n)]


def _style(ax, *, grid_axis: str = "x") -> None:
    """Recessive frame: no top/right spines, hairline grid behind the marks."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=8, length=0)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.title.set_color(INK)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _figure(figsize) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


def _is_unit_scale(values) -> bool:
    """True when every value sits in [0, 1] (render as a percentage)."""
    arr = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return bool(len(arr)) and float(arr.min()) >= 0.0 and float(arr.max()) <= 1.0


def _fmt(value: float, unit: bool) -> str:
    return f"{value * 100:.1f}%" if unit else f"{value:,.3g}"


def _limits(values, unit: bool, pad: float = 0.08) -> tuple[float, float]:
    if unit:
        return 0.0, 1.08
    arr = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if arr.empty:
        return 0.0, 1.0
    lo, hi = min(0.0, float(arr.min())), max(0.0, float(arr.max()))
    span = (hi - lo) or 1.0
    return lo - (pad * span if lo < 0 else 0.0), hi + pad * span


def _run_labels(df: pd.DataFrame, width: int = 44) -> list[str]:
    return [str(r.get("Experiment Name", f"run {i}"))[:width]
            for i, (_, r) in enumerate(df.iterrows())]


def _sorted_metric(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    return ea.require_metric(frame, metric).sort_values(metric, ascending=False)


def _ci_columns(df: pd.DataFrame, metric: str) -> tuple[Optional[pd.Series], Optional[pd.Series]]:
    """The CI columns that belong to ``metric`` — never another metric's.

    (0.16 always read ``Subtype Accuracy CI`` whiskers, so any other metric
    was drawn with the wrong interval.)"""
    for lo_name, hi_name in (
        (f"{metric} CI (lo)", f"{metric} CI (hi)"),
        (f"{metric} CI lo", f"{metric} CI hi"),
    ):
        if lo_name in df.columns and hi_name in df.columns:
            return (pd.to_numeric(df[lo_name], errors="coerce"),
                    pd.to_numeric(df[hi_name], errors="coerce"))
    return None, None


# ---------------------------------------------------------------------------
# Run-level plots (results frame)
# ---------------------------------------------------------------------------

def plot_metric_ci(frame: pd.DataFrame, metric: str = ea.DEFAULT_METRIC,
                   figsize=(11, 6), title: str | None = None) -> plt.Figure:
    """Horizontal bar chart of the metric per run with CI error bars (the
    headline plot). The best run carries the emphasis colour."""
    df = _sorted_metric(frame, metric)
    values = pd.to_numeric(df[metric], errors="coerce")
    unit = _is_unit_scale(values)
    lo, hi = _ci_columns(df, metric)
    xerr = None
    if lo is not None and lo.notna().any() and hi.notna().any():
        lo = lo.fillna(values)
        hi = hi.fillna(values)
        xerr = np.vstack([(values - lo).clip(lower=0), (hi - values).clip(lower=0)])
    fig, ax = _figure(figsize)
    y = np.arange(len(df))
    colors = [EMPHASIS if i == 0 else SUPPORT for i in range(len(df))]
    ax.barh(y, values, height=0.62, color=colors, edgecolor=SURFACE, linewidth=1.0,
            xerr=xerr, error_kw={"elinewidth": 1.0, "capsize": 3, "ecolor": INK_SECONDARY})
    ends = values if xerr is None else np.maximum(values, hi)
    x_lo, x_hi = _limits(ends, unit)
    x_hi += 0.06 * (x_hi - x_lo)  # room for the value label past the whisker
    offset = 0.012 * (x_hi - x_lo)
    for i, (v, end) in enumerate(zip(values, ends)):
        if v == v:
            ax.text(float(end) + offset, i, _fmt(float(v), unit), va="center",
                    fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(y)
    ax.set_yticklabels(_run_labels(df), fontsize=8, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(x_lo, x_hi)
    ax.set_xlabel(metric)
    ax.set_title(title or f"{metric} by run" + (" (CI where reported)" if xerr is not None else ""),
                 loc="left", fontsize=11)
    _style(ax, grid_axis="x")
    fig.tight_layout()
    return fig


def _bar_summary(summary: pd.DataFrame, key: str, metric: str, figsize,
                 title: str, rotate: int = 0, ranges: bool = False) -> plt.Figure:
    names = [str(v) for v in summary[key]]
    means = pd.to_numeric(summary["mean"], errors="coerce")
    extent = list(means) + (list(summary["best"]) if ranges else [])
    unit = _is_unit_scale(extent)
    fig, ax = _figure(figsize)
    x = np.arange(len(names))
    best = int(np.nanargmax(means.values)) if means.notna().any() else -1
    ax.bar(x, means, width=0.6, color=[EMPHASIS if i == best else SUPPORT for i in range(len(names))],
           edgecolor=SURFACE, linewidth=1.0)
    if ranges:
        for i, (_, row) in enumerate(summary.iterrows()):
            ax.plot([i, i], [row["worst"], row["best"]], color=INK_SECONDARY, lw=1)
    y_lo, y_hi = _limits(extent, unit)
    for i, m in enumerate(means):
        if m == m:
            ax.text(i, float(m) + 0.012 * (y_hi - y_lo), _fmt(float(m), unit),
                    ha="center", va="bottom", fontsize=8, color=INK_SECONDARY)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=rotate, ha="right" if rotate else "center", color=INK)
    ax.set_ylim(y_lo, y_hi)
    ax.set_ylabel(metric)
    ax.set_title(title, loc="left", fontsize=11)
    _style(ax, grid_axis="y")
    fig.tight_layout()
    return fig


def plot_prompt_version(frame: pd.DataFrame, metric: str = ea.DEFAULT_METRIC,
                        figsize=(10, 5), title: str | None = None) -> plt.Figure:
    """Bar chart of mean metric per prompt version with best/worst whiskers."""
    summary = ea.prompt_version_summary(frame, metric)
    if summary.empty:
        raise ValueError("no prompt_version data to plot")
    return _bar_summary(summary, "prompt_version", metric, figsize,
                        title or f"{metric} by prompt version (mean + range)", ranges=True)


def plot_model_comparison(frame: pd.DataFrame, metric: str = ea.DEFAULT_METRIC,
                          figsize=(9, 5), title: str | None = None) -> plt.Figure:
    """Bar chart of mean metric per model."""
    summary = ea.model_summary(frame, metric)
    if summary.empty:
        raise ValueError("no model data to plot")
    return _bar_summary(summary, "model", metric, figsize,
                        title or f"{metric} by model", rotate=15)


def _heatmap(ax, matrix: np.ndarray, *, vmin: float, vmax: float,
             annotate: bool, fmt) -> object:
    im = ax.imshow(matrix, aspect="auto", cmap=_SEQ_CMAP, vmin=vmin, vmax=vmax)
    if annotate:
        span = (vmax - vmin) or 1.0
        for (r, c), value in np.ndenumerate(matrix):
            if value != value:
                continue
            dark = (value - vmin) / span > 0.55
            ax.text(c, r, fmt(value), ha="center", va="center", fontsize=7,
                    color="#ffffff" if dark else INK)
    return im


def plot_per_subtype_heatmap(frame: pd.DataFrame,
                             runs: Optional[int] = None,
                             figsize: Optional[tuple] = None,
                             title: str | None = None) -> plt.Figure:
    """Runs x subtype accuracy heatmap (the per-class hotspot view).

    Rows are the top ``runs`` runs (by Subtype Accuracy), columns the
    canonical PER_SUBTYPE order; cell values are the per-subtype accuracies,
    on a single-hue ramp (darker = more accurate).
    """
    df = frame.copy()
    if "Subtype Accuracy" in df.columns:
        df = df.sort_values("Subtype Accuracy", ascending=False)
    if runs:
        df = df.head(runs)
    cols = [f"Accuracy: {s}" for s in PER_SUBTYPE if f"Accuracy: {s}" in df.columns]
    if not cols:
        raise ValueError("no per-subtype Accuracy columns in frame")
    matrix = df[cols].apply(pd.to_numeric, errors="coerce").values.astype(float)
    if figsize is None:
        figsize = (13, max(4, 0.4 * len(df)))
    fig, ax = _figure(figsize)
    annotate = matrix.shape[0] <= 12 and matrix.shape[1] <= 30
    # Scale to the data's own decade band (shown on the colour bar) so a
    # 79-vs-95 hotspot is visible; a fixed 0–1 range flattened it.
    finite = matrix[np.isfinite(matrix)]
    vmin = max(0.0, np.floor(float(finite.min()) * 10) / 10 - 0.1) if finite.size else 0.0
    im = _heatmap(ax, matrix, vmin=vmin, vmax=1, annotate=annotate,
                  fmt=lambda v: f"{v * 100:.0f}")
    labels = _run_labels(df)
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=7, color=INK)
    ax.set_xticks(np.arange(len(cols)))
    ax.set_xticklabels([c.replace("Accuracy: ", "") for c in cols],
                       rotation=60, ha="right", fontsize=8, color=INK)
    ax.set_title(title or "Per-subtype accuracy by run (%)", loc="left", fontsize=11)
    _style(ax, grid_axis="")
    cbar = fig.colorbar(im, ax=ax, shrink=0.6)
    cbar.set_label("accuracy", color=INK_SECONDARY)
    cbar.outline.set_visible(False)
    fig.tight_layout()
    return fig


def plot_failure_modes(frame: pd.DataFrame,
                       figsize=(10, 5), title: str | None = None) -> plt.Figure:
    """Stacked horizontal bars of the failure modes per run.

    Colours follow the categorical order (never cycled); modes past the
    eighth fold into one "Other" segment. Every mode is in the legend.
    """
    modes = ea.failure_mode_summary(frame)
    if modes.empty:
        raise ValueError("no failure-mode columns in frame")
    cols = [f"Failures: {m}" for m in modes.index if f"Failures: {m}" in frame.columns]
    if not cols:
        raise ValueError("no failure-mode columns in frame")
    df = frame.copy()
    counts = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    if len(cols) > len(SERIES):
        keep = cols[: len(SERIES) - 1]
        counts["Failures: Other"] = counts[cols[len(keep):]].sum(axis=1)
        cols = keep + ["Failures: Other"]
        counts = counts[cols]
    order = counts.sum(axis=1).sort_values(ascending=False).index
    counts = counts.loc[order]
    df = df.loc[order]
    fig, ax = _figure(figsize)
    y = np.arange(len(counts))
    left = np.zeros(len(counts))
    colors = _series_colors(len(cols))
    if cols[-1] == "Failures: Other":
        colors[-1] = OTHER
    for col, color in zip(cols, colors):
        ax.barh(y, counts[col], left=left, height=0.62, color=color,
                edgecolor=SURFACE, linewidth=1.5, label=col.replace("Failures: ", ""))
        left += counts[col].values
    ax.set_yticks(y)
    ax.set_yticklabels(_run_labels(df), fontsize=8, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("failed documents")
    ax.set_title(title or "Failure modes by run", loc="left", fontsize=11, pad=26)
    legend = ax.legend(fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.02),
                       ncol=min(len(cols), 4), frameon=False, borderaxespad=0)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    _style(ax, grid_axis="x")
    fig.tight_layout()
    return fig


def _annotated_scatter(ax, xs, ys, labels) -> None:
    ax.scatter(xs, ys, s=64, color=EMPHASIS, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    for x, yv, label in zip(xs, ys, labels):
        if x == x and yv == yv:
            ax.annotate(label, (float(x), float(yv)), fontsize=7, color=INK_SECONDARY,
                        xytext=(5, 4), textcoords="offset points")


def plot_confidence_scatter(frame: pd.DataFrame,
                            metric: str = ea.DEFAULT_METRIC,
                            figsize=(8, 6), title: str | None = None) -> plt.Figure:
    """Confidence vs accuracy scatter — the calibration/overconfidence view.
    Points below the diagonal are overconfident."""
    df = ea.require_metric(frame, metric)
    if "Average Confidence" not in df.columns:
        raise ValueError("no Average Confidence column in frame")
    conf = pd.to_numeric(df["Average Confidence"], errors="coerce")
    values = pd.to_numeric(df[metric], errors="coerce")
    fig, ax = _figure(figsize)
    ax.plot([0, 1], [0, 1], ls="--", color=INK_MUTED, lw=1, label="perfect calibration")
    _annotated_scatter(ax, conf, values,
                       [str(r.get("Experiment Name", ""))[:32] for _, r in df.iterrows()])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Average Confidence")
    ax.set_ylabel(metric)
    ax.set_title(title or f"Confidence vs {metric}", loc="left", fontsize=11)
    ax.legend(fontsize=8, frameon=False, labelcolor=INK_SECONDARY)
    _style(ax, grid_axis="both")
    fig.tight_layout()
    return fig


def plot_cost_efficiency(frame: pd.DataFrame, metric: str = ea.DEFAULT_METRIC,
                         cost_column: str = "Cost Estimated USD",
                         figsize=(8, 6), title: str | None = None) -> plt.Figure:
    """Accuracy vs cost scatter — the value-for-money view (log x-axis)."""
    df = ea.require_metric(frame, metric)
    if cost_column not in df.columns:
        raise ValueError(f"cost column '{cost_column}' not in frame")
    cost = pd.to_numeric(df[cost_column], errors="coerce")
    valid = cost.notna() & (cost > 0)
    if not valid.any():
        raise ValueError("no positive cost values to plot")
    df, cost = df[valid], cost[valid]
    values = pd.to_numeric(df[metric], errors="coerce")
    fig, ax = _figure(figsize)
    _annotated_scatter(ax, cost, values,
                       [str(r.get("Experiment Name", ""))[:32] for _, r in df.iterrows()])
    ax.set_xscale("log")
    ax.set_xlabel(f"Cost USD ({cost_column}, log scale)")
    ax.set_ylabel(metric)
    ax.set_title(title or f"Cost efficiency ({metric} vs cost)", loc="left", fontsize=11)
    _style(ax, grid_axis="both")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Mailroom views (label / score lists)
# ---------------------------------------------------------------------------

def plot_confusion_matrix(expected: Sequence, predicted: Sequence,
                          labels: Sequence[str] | None = None, *,
                          normalize: bool = True, figsize=(7, 6),
                          title: str | None = None) -> plt.Figure:
    """Doc-type confusion matrix (rows = expected, columns = predicted).

    ``normalize=True`` shades by row share (recall per class) and prints the
    percentage; raw counts otherwise. Without ``labels`` the axes use the
    five live mailroom classes + ``unknown`` (only those present), followed
    by any other label found in the data.
    """
    from .classification import confusion_matrix as _confusion
    from .mailroom import LIVE_DOC_TYPES, UNKNOWN_DOC_TYPE

    expected, predicted = list(expected), list(predicted)
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have the same length")
    if not expected:
        raise ValueError("no rows to plot")
    if labels is None:
        seen = {str(v) for v in expected + predicted}
        default = [*LIVE_DOC_TYPES, UNKNOWN_DOC_TYPE]
        labels = [lbl for lbl in default if lbl in seen] + sorted(seen - set(default))
    matrix, labels = _confusion(expected, predicted, labels=list(labels))
    counts = np.asarray(matrix, dtype=float)
    if normalize:
        totals = counts.sum(axis=1, keepdims=True)
        shade = np.divide(counts, totals, out=np.full_like(counts, np.nan), where=totals > 0)
        fmt = lambda v: f"{v * 100:.0f}%"  # noqa: E731
        vmax = 1.0
    else:
        shade = counts
        fmt = lambda v: f"{int(v)}"  # noqa: E731
        vmax = float(np.nanmax(counts)) or 1.0
    fig, ax = _figure(figsize)
    im = _heatmap(ax, shade, vmin=0, vmax=vmax, annotate=len(labels) <= 15, fmt=fmt)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8, color=INK)
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=8, color=INK)
    ax.set_xlabel("predicted")
    ax.set_ylabel("expected")
    ax.set_title(title or ("Doc-type confusion (row %)" if normalize else "Doc-type confusion (counts)"),
                 loc="left", fontsize=11)
    _style(ax, grid_axis="")
    cbar = fig.colorbar(im, ax=ax, shrink=0.7)
    cbar.outline.set_visible(False)
    fig.tight_layout()
    return fig


def plot_field_accuracy(field_scores: Mapping[str, Sequence[float] | float], *,
                        figsize: tuple | None = None,
                        title: str | None = None) -> plt.Figure:
    """Per-field mean extraction score (horizontal bars, weakest field first
    and highlighted). ``field_scores`` maps field → per-document scores (or
    an already-aggregated mean); each bar is labelled with its ``n``."""
    rows = []
    for field_name, value in field_scores.items():
        if isinstance(value, (int, float)):
            vals = [float(value)]
        else:
            vals = [float(v) for v in value if v is not None and v == v]
        if vals:
            rows.append((str(field_name), sum(vals) / len(vals), len(vals)))
    if not rows:
        raise ValueError("no field scores to plot")
    rows.sort(key=lambda r: r[1])
    if figsize is None:
        figsize = (8, max(3, 0.38 * len(rows) + 1))
    fig, ax = _figure(figsize)
    y = np.arange(len(rows))
    means = [r[1] for r in rows]
    unit = _is_unit_scale(means)
    colors = [EMPHASIS if i == 0 else SUPPORT for i in range(len(rows))]
    ax.barh(y, means, height=0.62, color=colors, edgecolor=SURFACE, linewidth=1.0)
    x_lo, x_hi = _limits(means, unit)
    for i, (_, mean, n) in enumerate(rows):
        ax.text(mean + 0.01 * (x_hi - x_lo), i, f"{_fmt(mean, unit)}  n={n}",
                va="center", fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8, color=INK)
    ax.set_xlim(x_lo, x_hi + 0.12 * (x_hi - x_lo))
    ax.set_xlabel("mean field score")
    ax.set_title(title or "Extraction score by field (weakest highlighted)", loc="left", fontsize=11)
    _style(ax, grid_axis="x")
    fig.tight_layout()
    return fig


PLOT_FACTORY = {
    "metric_ci": plot_metric_ci,
    "prompt_version": plot_prompt_version,
    "model": plot_model_comparison,
    "per_subtype": plot_per_subtype_heatmap,
    "failure_modes": plot_failure_modes,
    "confidence": plot_confidence_scatter,
    "cost": plot_cost_efficiency,
}


def build_all_plots(frame: pd.DataFrame, metric: str = ea.DEFAULT_METRIC,
                    cost_column: Optional[str] = None) -> dict[str, plt.Figure]:
    """Build every plot that the frame's columns support.

    Returns ``{plot_key: Figure}``. Skips (with a warning) plots whose
    required columns are missing.
    """
    import warnings

    plots: dict[str, plt.Figure] = {}
    for key, factory in PLOT_FACTORY.items():
        try:
            if key == "cost":
                if not cost_column:
                    continue
                plots[key] = factory(frame, metric, cost_column=cost_column)
            elif key in ("per_subtype", "failure_modes"):
                # these factories do not take the metric positionally
                plots[key] = factory(frame)
            else:
                plots[key] = factory(frame, metric)
        except (ValueError, KeyError, TypeError) as exc:
            warnings.warn(f"skipping {key} plot: {exc}", stacklevel=2)
    return plots


def save_plots(plots: dict[str, plt.Figure], outdir: str,
               prefix: str = "dojo") -> list[str]:
    """Save figures to ``outdir`` as ``{prefix}_{key}.png``; returns paths."""
    import os

    os.makedirs(outdir, exist_ok=True)
    paths = []
    for key, fig in plots.items():
        path = os.path.join(outdir, f"{prefix}_{key}.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        paths.append(path)
    return paths


__all__ = [
    "SERIES", "SEQUENTIAL", "SURFACE",
    "plot_metric_ci", "plot_prompt_version", "plot_model_comparison",
    "plot_per_subtype_heatmap", "plot_failure_modes",
    "plot_confidence_scatter", "plot_cost_efficiency",
    "plot_confusion_matrix", "plot_field_accuracy",
    "build_all_plots", "save_plots",
]
