"""Shared fixtures: a synthetic sorter results frame mirroring the
Sorter_Experiment_Results.xlsx schema, plus export round-trip helpers."""

import pandas as pd
import pytest

from llm_dojo_scoring.config import PER_SUBTYPE

METRIC = "Subtype Accuracy"


def make_sorter_frame(n_runs: int = 8) -> pd.DataFrame:
    """Deterministic synthetic sorter frame with CI + failure + per-subtype
    columns, mimicking the reference workbook."""
    rows = []
    specs = [
        # experiment, date, model, version, n, acc, ci_lo, ci_hi, conf
        ("qwen3.7-flash_sorter_v9_subtype_langfuse", "2026-08-13", "Qwen 3.7-Flash", "v9", 509, 0.9116, 0.8827, 0.9405, 0.9537),
        ("qwen3.7-flash_sorter_v12_subtype_langfuse", "2026-08-15", "Qwen 3.7-Flash", "v12", 509, 0.9234, 0.8978, 0.9450, 0.9556),
        ("qwen3.7-flash_sorter_v13_subtype_langfuse", "2026-08-16", "Qwen 3.7-Flash", "v13", 509, 0.9430, 0.9210, 0.9650, 0.9583),
        ("gpt-5-nano_sorter_v13_subtype_langfuse", "2026-08-16", "gpt-5-nano", "v13", 509, 0.8978, 0.8700, 0.9256, 0.8957),
        ("deepseek-v4-flash_sorter_v13_subtype_langfuse", "2026-08-16", "DeepSeek V4 Flash", "v13", 509, 0.9253, 0.9000, 0.9500, 0.9409),
        ("qwen3.7-flash_sorter_v13_subtype_langfuse_rerun", "2026-08-16", "Qwen 3.7-Flash", "v13", 509, 0.9350, 0.9120, 0.9580, 0.9570),
        ("qwen3.7-flash_sorter_v14_subtype_langfuse", "2026-08-16", "Qwen 3.7-Flash", "v14", 509, 0.9371, 0.9140, 0.9600, 0.9572),
        ("qwen3.7-flash_sorter_v12_subtype_langfuse_bug", "2026-08-16", "Qwen 3.7-Flash", "v12", 509, 0.8800, 0.8500, 0.9100, 0.9400),
    ]
    for exp, date, model, version, n, acc, lo, hi, conf in specs:
        row = {
            "DATE": pd.Timestamp(date),
            "Experiment Name": exp,
            "SAMPLE (n)": n,
            "MODEL": model,
            "Prompt Version": version,
            "Temperature": 0.1,
            "Doc Type Accuracy": 0.9961,
            METRIC: acc,
            "Subtype Accuracy (equiv)": round(acc + 0.005, 4),
            "Average Confidence": conf,
            "Rows Completed": n,
            "Rows Failed": 0,
            "Subtype Accuracy CI (lo)": lo,
            "Subtype Accuracy CI (hi)": hi,
            "Subtype Accuracy CI (half)": round((hi - lo) / 2, 4),
            "Doc Type Accuracy CI (lo)": 0.9902,
            "Doc Type Accuracy CI (hi)": 1.0,
            "Failures: n Failed": 39,
            "Failures: equivalent_family": 4,
            "Failures: family_confusion": 29,
            "Failures: function_over_form": 2,
            "Failures: other_fallback": 4,
            "Cost Estimated USD": 0.27,
        }
        for i, sub in enumerate(PER_SUBTYPE):
            # deterministic per-subtype accuracies with a couple of weak classes
            base = min(1.0, acc + 0.01)
            if sub in ("franchise", "hosting"):
                base = max(0.4, acc - 0.15)
            row[f"Accuracy: {sub}"] = round(base, 4)
        rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def sorter_frame() -> pd.DataFrame:
    return make_sorter_frame()


@pytest.fixture
def real_artifacts() -> dict:
    """Paths to the downloaded reference artifacts (skipped when absent)."""
    import os

    base = "/Users/luciusjmorningstar/Downloads"
    paths = {
        "results": os.path.join(base, "Sorter_Experiment_Results.xlsx"),
        "sweep": os.path.join(base, "Sorter_Model_Sweep_Results.xlsx"),
        "codebook": os.path.join(base, "Sorter_Experiment_Codebook.csv"),
    }
    for name, p in paths.items():
        if not os.path.exists(p):
            pytest.skip(f"{name} artifact not present: {p}")
    return paths