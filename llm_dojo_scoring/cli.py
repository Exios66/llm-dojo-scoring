"""Command-line interface.

- ``dojo-analyze`` — analyze a results workbook / JSONL log into a Markdown
  report + PNG plots.
- ``dojo-export`` — regenerate the canonical experiment-log workbooks +
  codebooks from a JSONL log.
"""

from __future__ import annotations

import argparse
import os
import sys


def _cli_analyze(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dojo-analyze",
        description="Analyze an evaluation results workbook (or JSONL log): "
                    "scoring summary, error analysis, interpretation, plots.",
    )
    parser.add_argument("input", help="Path to a results workbook (.xlsx) or experiment-log JSONL")
    parser.add_argument("-o", "--out", default=None,
                        help="Markdown report path (default: <input>.report.md)")
    parser.add_argument("--plots", default=None,
                        help="Directory for PNG plots (default: <input>_plots/)")
    parser.add_argument("--no-plots", action="store_true", help="Skip plot generation")
    parser.add_argument("--metric", default="Subtype Accuracy",
                        help="Primary metric column (default: Subtype Accuracy)")
    parser.add_argument("--target", type=float, default=None,
                        help="Accuracy target (0-1) for the target-gate verdict")
    parser.add_argument("--min-n", type=int, default=0,
                        help="Minimum sample size for the champion run")
    parser.add_argument("--cost-column", default=None,
                        help="Cost column for the efficiency plot/note (default: Cost Estimated USD)")
    parser.add_argument("--task", default=None,
                        help="Task filter when the input is a JSONL log "
                             "(e.g. subtype_classification)")
    args = parser.parse_args(argv)

    from . import error_analysis as ea
    from .io import load_log, normalize_results_frame, read_workbook
    from .report import build_report

    path = args.input
    if path.endswith(".jsonl"):
        result = load_log(path, task=args.task)
    else:
        result = read_workbook(path)
    frame = normalize_results_frame(result.frame)
    if frame.empty:
        print(f"[dojo-analyze] no rows in {path}", file=sys.stderr)
        return 1

    cost_column = args.cost_column or ("Cost Estimated USD" if "Cost Estimated USD" in frame.columns else None)
    metric = args.metric if args.metric in frame.columns else ea.DEFAULT_METRIC
    if metric != args.metric:
        print(f"[dojo-analyze] metric '{args.metric}' not found — using '{metric}'", file=sys.stderr)

    out = args.out or (path + ".report.md")
    plots_dir = args.plots or (path + "_plots")

    plot_paths: dict[str, str] | None = None
    if not args.no_plots:
        try:
            import matplotlib

            matplotlib.use("Agg")
            from .visualize import build_all_plots, save_plots

            figures = build_all_plots(frame, metric=metric, cost_column=cost_column)
            saved = save_plots(figures, plots_dir, prefix="dojo")
            plot_paths = {os.path.basename(p).removeprefix("dojo_").removesuffix(".png"): p
                          for p in saved}
        except Exception as exc:  # pragma: no cover
            print(f"[dojo-analyze] plot generation failed: {exc}", file=sys.stderr)

    report = build_report(
        frame, path=out, metric=metric, target=args.target, min_n=args.min_n,
        cost_column=cost_column, plot_paths=plot_paths,
        title=f"{result.kind.capitalize()} Evaluation Report — {os.path.basename(path)}",
    )
    print(f"[dojo-analyze] {result.n_runs} runs -> {out}")
    if plot_paths:
        for p in plot_paths.values():
            print(f"[dojo-analyze]   plot: {p}")
    return 0


def _cli_export(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dojo-export",
        description="Regenerate per-task experiment performance workbooks + "
                    "codebooks (Google-Sheets-friendly, reference formats).",
    )
    parser.add_argument("--task", choices=["sorter", "extraction", "all"], default="all",
                        help="Which task workbook(s) to regenerate (default: all)")
    parser.add_argument("--outdir", default=".",
                        help="Output directory for the workbooks + codebooks")
    parser.add_argument("--log", default="reports/experiment_log.jsonl",
                        help="Path to the experiment log")
    parser.add_argument("--sweep", action="store_true",
                        help="Also write the model-sweep workbook (champion prompt)")
    args = parser.parse_args(argv)

    from .export import (
        extraction_columns, extraction_records, load_records, sorter_columns,
        sorter_records, build_sweep_workbook, write_codebook, write_workbook,
    )

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    records = load_records(args.log)
    tasks = ["sorter", "extraction"] if args.task == "all" else [args.task]
    for task in tasks:
        if task == "sorter":
            cols, recs = sorter_columns(), sorter_records(records)
            wb_path = os.path.join(outdir, "Sorter_Experiment_Results.xlsx")
            cb_path = os.path.join(outdir, "Sorter_Experiment_Codebook.csv")
            with_codebook = True
        else:
            cols, recs = extraction_columns(), extraction_records(records)
            wb_path = os.path.join(outdir, "Entity_Extraction_Results.xlsx")
            cb_path = os.path.join(outdir, "Entity_Extraction_Codebook.csv")
            with_codebook = False
        write_workbook(wb_path, "Eval Results", cols, recs, codebook_sheet=with_codebook)
        write_codebook(cb_path, cols)
        print(f"[dojo-export] {task}: {len(recs)} runs -> {wb_path} ({len(cols)} cols) + {cb_path}")
    if args.sweep and "sorter" in tasks:
        sweep_path, n = build_sweep_workbook(records, outdir=outdir)
        print(f"[dojo-export] sweep: {n} runs -> {sweep_path}")
    return 0


def analyze_main() -> None:
    raise SystemExit(_cli_analyze(sys.argv[1:]))


def export_main() -> None:
    raise SystemExit(_cli_export(sys.argv[1:]))


__all__ = ["_cli_analyze", "_cli_export", "analyze_main", "export_main"]
