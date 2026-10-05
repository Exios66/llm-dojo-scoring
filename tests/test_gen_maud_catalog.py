"""Offline unit tests for MAUD catalog regeneration and stale-artifact checks."""

import json
import sys
from collections import Counter, defaultdict

import pandas as pd
import pytest

from llm_dojo_scoring.corpus import MAUD_QUESTION_KEYS
from scripts import gen_maud_catalog as generator


def test_scan_unions_classes_and_counts_only_merger_rows():
    frame = pd.DataFrame([
        {"expected": "contract", "gt_fields": "not JSON: must be ignored"},
        {"expected": "merger_agreement", "gt_fields": json.dumps({
            "maud_clause_labels": {"No-Shop": {"valid_classes": ["Yes", "No"]}},
        })},
        {"expected": "merger_agreement", "gt_fields": json.dumps({
            "maud_clause_labels": json.dumps({"No-Shop": {"valid_classes": ["No", "Yes", "Yes"]}}),
        })},
        {"expected": "merger_agreement", "gt_fields": json.dumps({
            "maud_clause_labels": {
                "No-Shop": {"valid_classes": ["Strict liability"]},
                "MAE Definition": {"valid_classes": []},
                "Knowledge Definition": "not a record",
            },
        })},
        {"expected": "merger_agreement", "gt_fields": "{}"},
    ])
    union, distinct = defaultdict(set), defaultdict(set)
    counts, rows = Counter(), Counter()
    generator._scan(frame, "test", union, counts, distinct, rows)
    assert rows == {"test": 4}
    assert counts == {"No-Shop": 3}
    assert union == {"No-Shop": {"Yes", "No", "Strict liability"}}
    assert distinct == {"No-Shop": {frozenset(["Yes", "No"]), frozenset(["Strict liability"])}}


@pytest.fixture
def catalog_splits(monkeypatch):
    labels = {q: {"valid_classes": ["Zulu", "alpha"]} for q in MAUD_QUESTION_KEYS}
    frames = {
        "test": pd.DataFrame([{"expected": "merger_agreement", "gt_fields": json.dumps({
            "maud_clause_labels": labels,
        })}]),
        "train": pd.DataFrame([{"expected": "merger_agreement", "gt_fields": json.dumps({
            "maud_clause_labels": {"No-Shop": {"valid_classes": ["Beta", "alpha"]}},
        })}]),
    }
    # build_artifacts prepends to sys.path; keep that side effect local to the test.
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(generator, "_load_split", lambda split, *_: frames[split])
    return frames


def test_build_artifacts_contains_sorted_union_counts_and_provenance(catalog_splits):
    module, fixture_text = generator.build_artifacts(None, "synthetic-revision", "2026-01-02")
    fixture = json.loads(fixture_text)
    assert fixture["rows"] == {"total": 2, "test": 1, "train": 1}
    assert fixture["generated"] == "2026-01-02"
    assert fixture["source"].endswith("@ synthetic-revision")
    assert list(fixture["questions"]) == list(MAUD_QUESTION_KEYS)
    assert fixture["questions"]["No-Shop"] == {
        "classes": ["alpha", "Beta", "Zulu"], "answered_rows": 2, "distinct_class_sets": 2,
    }
    assert fixture["questions"]["MAE Definition"] == {
        "classes": ["alpha", "Zulu"], "answered_rows": 1, "distinct_class_sets": 1,
    }
    # Verify the generated Python is usable and agrees with its JSON artifact.
    namespace = {"__name__": "llm_dojo_scoring._generated_test_catalog"}
    exec(compile(module, "<generated-maud-catalog>", "exec"), namespace)
    assert namespace["MAUD_CATALOG_ROWS"] == 2
    assert namespace["MAUD_VARIABLE_CLASS_QUESTIONS"] == ("No-Shop",)
    assert namespace["MAUD_ANSWER_CLASSES"] == {
        q: tuple(entry["classes"]) for q, entry in fixture["questions"].items()
    }
    assert generator.build_artifacts(None, "synthetic-revision", "2026-01-02") == (module, fixture_text)


def test_build_artifacts_rejects_incomplete_catalog(catalog_splits):
    catalog_splits["test"].loc[0, "gt_fields"] = "{}"
    with pytest.raises(SystemExit, match="catalog incomplete, missing questions:.*Type of Consideration"):
        generator.build_artifacts(None, "revision", "date")


@pytest.mark.parametrize("stale", [None, "module", "fixture"])
def test_check_mode_detects_drift_without_writing(monkeypatch, tmp_path, capsys, stale):
    module_path, fixture_path = tmp_path / "maud.py", tmp_path / "classes.json"
    module_path.write_text("stale" if stale == "module" else "module\n")
    fixture_path.write_text("stale" if stale == "fixture" else "fixture\n")
    before = (module_path.read_bytes(), fixture_path.read_bytes())
    monkeypatch.setattr(generator, "MODULE_PATH", module_path)
    monkeypatch.setattr(generator, "FIXTURE_PATH", fixture_path)
    monkeypatch.setattr(generator, "build_artifacts", lambda *_: ("module\n", "fixture\n"))
    monkeypatch.setattr(sys, "argv", ["gen_maud_catalog.py", "--check"])
    assert generator.main() == (1 if stale else 0)
    assert (module_path.read_bytes(), fixture_path.read_bytes()) == before
    assert ("FAILED" if stale else "OK") in capsys.readouterr().out


def test_write_mode_forwards_options_and_writes_both_artifacts(monkeypatch, tmp_path, mocker):
    module_path, fixture_path = tmp_path / "maud.py", tmp_path / "classes.json"
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "MODULE_PATH", module_path)
    monkeypatch.setattr(generator, "FIXTURE_PATH", fixture_path)
    build = mocker.patch.object(generator, "build_artifacts", return_value=("module\n", "fixture\n"))
    monkeypatch.setattr(sys, "argv", [
        "gen_maud_catalog.py", "--write", "--parquet-dir", str(tmp_path),
        "--revision", "custom-revision", "--generated", "2026-01-02",
    ])
    assert generator.main() == 0
    build.assert_called_once_with(tmp_path, "custom-revision", "2026-01-02")
    assert module_path.read_text() == "module\n"
    assert fixture_path.read_text() == "fixture\n"
