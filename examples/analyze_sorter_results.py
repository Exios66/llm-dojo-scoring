#!/usr/bin/env python3
"""End-to-end example: analyze a sorter results workbook with the dojo suite.

    python examples/analyze_sorter_results.py \
        /path/to/Sorter_Experiment_Results.xlsx --target 0.94

Reads the workbook, normalizes the frame, builds every supported plot, runs
the interpretation, and writes a Markdown report.
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")

from llm_dojo_scoring import error_analysis as ea
from llm_dojo_scoring import interpret as interp
from llm_dojo_scoring import report as dojo_report
from llm_dojo_scoring import visualize as viz
from llm_dojo_scoring.io import normalize_results_frame, read_workbook


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a sorter results workbook.")
    parser.add_argument("workbook", help="Path to a results .xlsx")
    parser.add_argument("--metric", default="Subtype Accuracy")
    parser.add_argument("--target", type=float, default=None)
    parser.add_argument("--min-n", type=int, default=0)
    parser.add_argument("--plots", default=None, help="Directory for PNG plots")
    parser.add_argument("--out", default=None, help="Markdown report path")
    args = parser.parse_args()

    result = read_workbook(args.workbook)
    print(f"loaded {result.n_runs} runs ({result.kind}) from {result.path}")

    frame = normalize_results_frame(result.frame)
    plots_dir = args.plots or (args.workbook + "_plots")
    cost_column = "Cost Estimated USD" if "Cost Estimated USD" in frame.columns else None

    figures = viz.build_all_plots(frame, metric=args.metric, cost_column=cost_column)
    plot_paths = {os.path.basename(p).removeprefix("dojo_").removesuffix(".png"): p
                  for p in viz.save_plots(figures, plots_dir)}
    print(f"saved {len(plot_paths)} plots to {plots_dir}")

    interpretation = interp.interpret(frame, metric=args.metric, target=args.target,
                                      min_n=args.min_n, cost_column=cost_column)
    print(interp.render_notes(interpretation))

    out = args.out or (args.workbook + ".report.md")
    dojo_report.build_report(
        frame, path=out, metric=args.metric, target=args.target, min_n=args.min_n,
        cost_column=cost_column, plot_paths=plot_paths,
        title=f"{result.kind.capitalize()} Evaluation Report — {os.path.basename(args.workbook)}",
    )
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())