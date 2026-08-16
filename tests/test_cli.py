import pytest

from llm_dojo_scoring.cli import _cli_analyze, _cli_export
from llm_dojo_scoring.report import build_report
from llm_dojo_scoring.io import normalize_results_frame


@pytest.fixture
def df(sorter_frame):
    return normalize_results_frame(sorter_frame)


def test_build_report_markdown(df):
    text = build_report(df)
    assert "# Evaluation Report" in text
    assert "## Verdicts" in text
    assert "Best run: qwen3.7-flash_sorter_v13_subtype_langfuse" in text
    assert "## Champion" in text
    assert "## Per-subtype accuracy" in text
    assert "## Failure modes" in text
    assert "## Reliability" in text


def test_build_report_writes_file(df, tmp_path):
    out = tmp_path / "report.md"
    build_report(df, path=str(out), target=0.94)
    assert out.exists()
    content = out.read_text()
    assert "Target met" in content


def test_build_report_with_plots(df, tmp_path):
    plot_paths = {"metric_ci": str(tmp_path / "dojo_metric_ci.png")}
    text = build_report(df, plot_paths=plot_paths)
    assert "![metric_ci]" in text


def test_cli_analyze_xlsx(tmp_path):
    import os

    from llm_dojo_scoring.export import sorter_columns, write_workbook

    xlsx = tmp_path / "results.xlsx"
    record = {
        "experiment_name": "qwen3.7-flash_sorter_v13_subtype_langfuse",
        "model": "qwen/qwen3.7-flash",
        "prompt_versions": {"sorter": "sorter_v13"},
        "n_rows": 509, "n_ok": 509,
        "scores": {"sorter": {"exact_match": 0.9961, "subtype_accuracy": 0.9430,
                              "subtype_accuracy_equiv": 0.9470, "confidence": 0.9583,
                              "subtype_accuracy_ci": {"lo": 0.921, "hi": 0.965, "half": 0.022, "n": 509},
                              "exact_match_ci": {"lo": 0.9902, "hi": 1.0, "half": 0.0049, "n": 509},
                              "failure_insights": {"n_failed": 29,
                                                   "mode_counts": {"family_confusion": 20, "equivalent_family": 5,
                                                                   "function_over_form": 2, "other_fallback": 2}},
                              "per_subtype": {}},
                   },
        "tokens": {"sorter": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                              "cost_estimated_usd": 0.27, "rows_with_usage": 509}},
    }
    write_workbook(str(xlsx), "Eval Results", sorter_columns(), [record], codebook_sheet=True)
    out = tmp_path / "out.md"
    rc = _cli_analyze([
        str(xlsx), "-o", str(out), "--plots", str(tmp_path / "plots"),
        "--target", "0.94", "--cost-column", "Cost Estimated USD",
    ])
    assert rc == 0
    assert out.exists()
    assert "Best run: qwen3.7-flash_sorter_v13_subtype_langfuse" in out.read_text()
    plots = os.listdir(tmp_path / "plots")
    assert len(plots) >= 3


def test_cli_analyze_langfuse_sync(tmp_path):
    """dojo-analyze langfuse:<name> pulls live traces and analyzes them."""
    from unittest import mock

    from llm_dojo_scoring import langfuse_sync as ls

    trace = {
        "id": "t1", "name": "subtype_classification",
        "sessionId": "qwen3.7-flash_sorter_v13_subtype_langfuse",
        "timestamp": "2026-08-16T00:00:00Z",
        "input": {"filename": "a.pdf", "expected": "license",
                  "prompt_version": "sorter_v13", "model": "qwen/qwen3.7-flash"},
        "output": {"sorter": {
            "doc_type": "contract", "contract_subtype": "license",
            "expected_subtype": "license", "doc_type_ok": True,
            "subtype_ok": True, "subtype_ok_equiv": True, "confidence": 0.95,
        }},
    }
    client = mock.Mock(spec=ls.LangfuseClient)
    client.list_traces.return_value = [trace]
    out = tmp_path / "lf.md"
    with mock.patch.object(ls, "LangfuseClient", return_value=client):
        rc = _cli_analyze(["langfuse:subtype_classification", "--max-items", "5",
                           "--no-plots", "-o", str(out)])
    assert rc == 0
    assert out.exists()
    assert "Best run: qwen3.7-flash_sorter_v13_subtype_langfuse" in out.read_text()


def test_cli_export(tmp_path):
    from llm_dojo_scoring.experiment import append_experiment

    log = tmp_path / "log.jsonl"
    append_experiment({
        "task": "subtype_classification",
        "experiment_name": "qwen3.7-flash_sorter_v13_subtype_langfuse",
        "model": "qwen/qwen3.7-flash",
        "n_rows": 509, "n_ok": 509,
        "scores": {"sorter": {"subtype_accuracy": 0.9, "per_subtype": {}}},
        "tokens": {"sorter": {}},
    }, log)
    outdir = tmp_path / "out"
    rc = _cli_export(["--task", "sorter", "--outdir", str(outdir), "--log", str(log)])
    assert rc == 0
    assert (outdir / "Sorter_Experiment_Results.xlsx").exists()
    assert (outdir / "Sorter_Experiment_Codebook.csv").exists()