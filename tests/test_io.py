"""Check experiment metadata parsing and workbook, codebook, and log ingestion."""
import pandas as pd
import pytest

from llm_dojo_scoring.io import (
    display_model,
    load_log,
    normalize_results_frame,
    parse_experiment_name,
    read_codebook,
    read_workbook,
)


def test_parse_experiment_name():
    """Extract model, prompt version, dimension, and suffix from varied run names."""
    parts = parse_experiment_name("qwen3.7-flash_sorter_v12_subtype_langfuse")
    assert parts["model_slug"] == "qwen3.7-flash"
    assert parts["prompt_version"] == "v12"
    assert parts["dimension"] == "subtype"
    assert parts["suffix"] == "langfuse"

    parts2 = parse_experiment_name("deepseek-v4-flash_sorter_v13_subtype_langfuse")
    assert parts2["model_slug"] == "deepseek-v4-flash"

    # fallback fragment extraction for pilot / nonstandard names
    parts3 = parse_experiment_name("pilot_langfuse_sorter_v5")
    assert parts3["prompt_version"] == "v5"
    assert parts3["model_slug"] == "pilot"

    parts4 = parse_experiment_name("weird name without pattern")
    assert parts4["prompt_version"] is None


def test_display_model():
    """Format known model identifiers while preserving unknown names and nulls."""
    assert display_model("qwen/qwen3.7-flash") == "Qwen 3.7-Flash"
    assert display_model("custom/model") == "custom/model"
    assert display_model(None) is None


def test_normalize_results_frame(sorter_frame):
    """Add canonical metadata columns and numeric metrics to sorter workbook rows."""
    df = normalize_results_frame(sorter_frame)
    assert "date" in df.columns
    assert "model" in df.columns
    assert "prompt_version" in df.columns
    assert "n" in df.columns
    assert df["n"].iloc[0] == 509
    assert df["key"].iloc[0] == "Qwen 3.7-Flash_v9"
    assert pd.api.types.is_numeric_dtype(df["Subtype Accuracy"])


def test_read_workbook_real_artifact(real_artifacts):
    """Read reference sorter runs with their codebook and diagnostic columns."""
    result = read_workbook(real_artifacts["results"])
    assert result.kind == "sorter"
    assert result.n_runs == 31
    assert result.codebook is not None
    assert len(result.codebook) >= 100
    # schema sanity: key columns present
    assert "Subtype Accuracy" in result.frame.columns
    assert "Failures: family_confusion" in result.frame.columns


def test_read_codebook_real_artifact(real_artifacts):
    """Preserve the reference codebook column schema during ingestion."""
    codebook = read_codebook(real_artifacts["codebook"])
    assert list(codebook.columns) == ["Variable", "Description", "Type", "Source", "Example / Values"]


def test_load_log(tmp_path):
    """Load experiment logs and apply task filters without losing run identity."""
    log = tmp_path / "log.jsonl"
    log.write_text(
        '{"experiment_name": "a", "task": "subtype_classification", "n_rows": 5}\n'
        '{"experiment_name": "b", "task": "contract_entity_extraction", "n_rows": 5}\n'
    )
    result = load_log(log)
    assert result.n_runs == 2
    filtered = load_log(log, task="subtype_classification")
    assert filtered.n_runs == 1
    assert filtered.frame.iloc[0]["experiment_name"] == "a"


def test_normalize_results_frame_sweep_real(real_artifacts):
    """Recognize reference sweep workbooks and preserve model and notes columns."""
    result = read_workbook(real_artifacts["sweep"])
    assert result.kind == "sweep"
    df = normalize_results_frame(result.frame)
    assert "model" in df.columns
    # The sweep workbook is a live pipeline artifact and can grow as new
    # model runs land; assert a sane minimum rather than a fixed count.
    assert len(df) >= 6
    assert "Notes" in df.columns
