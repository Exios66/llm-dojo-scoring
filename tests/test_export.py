"""Export round-trip tests: build a workbook from synthetic records, then read
it back with the io loader and verify the column contract survives."""

import json
import os

import pandas as pd
import pytest

from llm_dojo_scoring.export import (
    build_sweep_workbook,
    dotted_get,
    extraction_columns,
    load_records,
    sorter_columns,
    sorter_records,
    write_codebook,
    write_workbook,
)
from llm_dojo_scoring.io import normalize_results_frame, read_codebook, read_workbook

PER_SUB = ["license", "franchise", "reseller", "distributor"]


def _sorter_record(name: str, acc: float, n: int = 509, model: str = "qwen/qwen3.7-flash",
                   version: str = "sorter_v13", note: str | None = None) -> dict:
    record = {
        "type": "experiment",
        "task": "subtype_classification",
        "experiment_name": name,
        "model": model,
        "prompt_versions": {"sorter": version},
        "parameters": {"temperature": 0.1, "max_tokens": 2048,
                       "max_input_chars": 12000, "max_concurrency": 8},
        "n_rows": n,
        "n_ok": n,
        "data_source": {"project": "llm-mailroom/mailroom-cuad-contracts",
                        "n_samples": n, "sample_requested": 0, "seed": 42},
        "scores": {
            "sorter": {
                "exact_match": 0.9961,
                "subtype_accuracy": acc,
                "subtype_accuracy_equiv": round(acc + 0.005, 4),
                "confidence": 0.95,
                "subtype_accuracy_ci": {"lo": round(acc - 0.02, 4),
                                        "hi": round(acc + 0.02, 4),
                                        "half": 0.02, "n": n},
                "exact_match_ci": {"lo": 0.9902, "hi": 1.0, "half": 0.0049, "n": n},
                "failure_insights": {
                    "n_failed": 39,
                    "mode_counts": {"equivalent_family": 4, "family_confusion": 29,
                                    "function_over_form": 2, "other_fallback": 4},
                },
                "per_subtype": {
                    s: {"accuracy": acc, "accuracy_equiv": round(acc + 0.005, 4),
                        "correct": int(acc * n), "equiv": 0, "total": n // 2}
                    for s in PER_SUB
                },
            },
        },
        "tokens": {"sorter": {"prompt_tokens": 1000, "completion_tokens": 500,
                              "total_tokens": 1500, "cost_usd": 0.0,
                              "cost_total_usd": 0.0, "cost_estimated_usd": 0.27,
                              "rows_with_usage": n}},
    }
    if note:
        record["_note"] = note
    return record


@pytest.fixture
def records() -> list[dict]:
    return [
        _sorter_record("qwen3.7-flash_sorter_v12_subtype_langfuse", 0.92, version="sorter_v12"),
        _sorter_record("qwen3.7-flash_sorter_v13_subtype_langfuse", 0.9430, version="sorter_v13"),
        _sorter_record("deepseek-v4-flash_sorter_v13_subtype_langfuse", 0.9253,
                       model="deepseek/deepseek-v4-flash", version="sorter_v13"),
    ]


def test_sorter_columns_length_and_headers():
    cols = sorter_columns()
    assert len(cols) == 114
    assert cols[0]["header"] == "DATE"
    assert "Subtype Accuracy" in [c["header"] for c in cols]
    assert "Failures: family_confusion" in [c["header"] for c in cols]
    assert "Accuracy: license" in [c["header"] for c in cols]
    assert "n Total: license" in [c["header"] for c in cols]
    assert "Cost Estimated USD" in [c["header"] for c in cols]


def test_dotted_get():
    assert dotted_get(_sorter_record("x", 0.9), "scores.sorter.subtype_accuracy") == 0.9
    assert dotted_get(_sorter_record("x", 0.9), "nope") is None


def test_workbook_round_trip(tmp_path, records):
    wb = tmp_path / "Sorter_Experiment_Results.xlsx"
    write_workbook(str(wb), "Eval Results", sorter_columns(), records, codebook_sheet=True)
    result = read_workbook(wb)
    assert result.n_runs == 3
    assert result.kind == "sorter"
    df = normalize_results_frame(result.frame)
    assert "Subtype Accuracy" in df.columns
    assert "model" in df.columns
    # spot-check values survived
    v12 = df[df["prompt_version"] == "v12"].iloc[0]
    assert v12["Subtype Accuracy"] == pytest.approx(0.92)
    assert v12["MODEL"] == "Qwen 3.7-Flash"


def test_codebook_round_trip(tmp_path):
    cb = tmp_path / "Sorter_Experiment_Codebook.csv"
    write_codebook(str(cb), sorter_columns())
    df = read_codebook(cb)
    assert len(df) == 114
    assert "Variable" in df.columns


def test_sweep_workbook(tmp_path, records):
    path, n = build_sweep_workbook(
        records, outdir=str(tmp_path),
        notes={"qwen3.7-flash_sorter_v13_subtype_langfuse": "champion"},
    )
    assert n == 2  # only v13 runs
    result = read_workbook(path)
    assert result.n_runs == 2
    df = normalize_results_frame(result.frame)
    assert "Notes" in df.columns
    assert df["Notes"].iloc[0] == "champion"


def test_sweep_picks_champion_prompt(records):
    from llm_dojo_scoring.export import champion_prompt_version

    assert champion_prompt_version(records) == "v13"


def test_sorter_records_filter(records):
    from llm_dojo_scoring.export import extraction_records

    assert len(sorter_records(records)) == 3
    assert len(extraction_records(records)) == 0


def test_extraction_columns_smoke():
    cols = extraction_columns()
    assert len(cols) == 141
    assert "Overall Extraction" in [c["header"] for c in cols]
    assert "Hallucination Rate (avg)" in [c["header"] for c in cols]
    assert "Diag: Date MAE (days)" in [c["header"] for c in cols]


def test_load_records_jsonl(tmp_path, records):
    log = tmp_path / "log.jsonl"
    with open(log, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    assert len(load_records(log)) == 3