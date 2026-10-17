"""Corporate label tools use local fixtures and a mocked parquet boundary."""

from __future__ import annotations

import ast
import json
import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from conftest import load_script
from llm_dojo_scoring.corporate_record_schema import ENTITY_CORE_FIELDS


@pytest.fixture
def parquet_reader(monkeypatch):
    parquet = ModuleType("pyarrow.parquet")
    parquet.read_table = Mock()
    arrow = ModuleType("pyarrow")
    arrow.parquet = parquet
    monkeypatch.setitem(sys.modules, "pyarrow", arrow)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", parquet)
    return parquet.read_table


@pytest.fixture
def relabel_script(parquet_reader):
    # load_script caches modules; remove this one so its mocked optional
    # dependency cannot leak into another test's script import.
    name = "dojo_scripts_relabel_corporate_record_gt"
    previous = sys.modules.pop(name, None)
    try:
        yield load_script("relabel_corporate_record_gt")
    finally:
        sys.modules.pop(name, None)
        if previous is not None:
            sys.modules[name] = previous


def _clean_row():
    return {
        "expected": "corporate_record", "expected_subclass": "other",
        "gt_fields": {
            "intent": "other", "subject_matter": "Governance of Café Holdings.",
            "gt_presence": {key: "schema_documented_absence" for key in ENTITY_CORE_FIELDS},
        },
    }


def _jsonl(path, rows):
    path.write_text("\n" + "\n\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return path


def test_audit_jsonl_reports_all_input_files_and_skips_other_classes(tmp_path, capsys):
    script = load_script("audit_corporate_record_labels")
    first = _jsonl(tmp_path / "first.jsonl", [_clean_row(), {"expected": "contract", "gt_fields": "{bad"}])
    second = _jsonl(tmp_path / "second.jsonl", [dict(_clean_row(), gt_fields="{bad")])
    assert list(script._rows(first))[0] == _clean_row()

    assert script.main([str(first), str(second), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "n_rows": 2, "totals": {"rows": 2, "gt_unparseable": 1},
        "by_subclass": {"other": {"rows": 2, "gt_unparseable": 1}},
    }


@pytest.mark.parametrize("rows", [[], [_clean_row()], [{"expected": "contract"}]])
def test_audit_clean_or_empty_input_returns_success(tmp_path, capsys, rows):
    script = load_script("audit_corporate_record_labels")
    path = _jsonl(tmp_path / "clean.jsonl", rows)
    assert script.main([str(path)]) == 0
    output = capsys.readouterr().out
    expected_count = sum(row.get("expected") == "corporate_record" for row in rows)
    assert f"corporate_record rows audited: {expected_count}" in output
    assert "totals: clean" in output


def test_audit_text_summarizes_conflicts_and_unlabeled_entities(tmp_path, capsys):
    script = load_script("audit_corporate_record_labels")
    row = {
        "expected": "corporate_record", "expected_subclass": "articles_of_incorporation",
        "gt_fields": {"subject_matter": "Bylaws of Acme.", "intent_source": "heuristic"},
    }
    path = _jsonl(tmp_path / "defects.jsonl", [row])
    assert script.main([str(path)]) == 1
    output = capsys.readouterr().out
    assert "articles_of_incorporation (1 rows):" in output
    assert "intent_heuristic=1" in output
    assert "subclass_content_conflict=1" in output
    assert "unlabeled entity fields=9" in output
    assert "registered_agent" in output


@pytest.mark.parametrize("suffix", [".parquet", ".bin"])
def test_audit_parquet_and_cache_files_read_only_required_columns(tmp_path, parquet_reader, suffix):
    script = load_script("audit_corporate_record_labels")
    path = tmp_path / f"ground_truth{suffix}"
    parquet_reader.return_value = SimpleNamespace(to_pylist=lambda: [_clean_row()])
    assert list(script._rows(path)) == [_clean_row()]
    parquet_reader.assert_called_once_with(path, columns=["expected", "expected_subclass", "gt_fields"])


@pytest.mark.parametrize("argv", [["relabel"], ["relabel", "out.jsonl"]])
def test_relabel_usage_does_not_read_or_write_files(relabel_script, parquet_reader, capsys, argv):
    assert relabel_script.main(argv) == 2
    parquet_reader.assert_not_called()
    assert "Usage::" in capsys.readouterr().out


def test_relabel_cli_repairs_all_files_and_survives_malformed_rows(
    tmp_path, capsys, parquet_reader, relabel_script,
):
    bad = {"expected": "corporate_record", "expected_subclass": "bylaws", "gt_fields": "{bad"}
    template = {
        "expected": "corporate_record", "expected_subclass": "bylaws", "document_id": "synthetic-1",
        "gt_fields": json.dumps({
            "subject_matter": "bylaws of Café Holdings (CIK 123) (SEC EDGAR exhibit).",
            "intent": "other", "intent_source": "heuristic", "keywords": '["bylaws", "EX-3.2"]',
        }),
    }
    inputs = [[bad, {"expected": "contract", "gt_fields": "{bad"}], [template]]
    before = deepcopy(inputs)
    parquet_reader.side_effect = [SimpleNamespace(to_pylist=lambda rows=rows: rows) for rows in inputs]
    paths = [tmp_path / "train.parquet", tmp_path / "test.bin"]
    destination = tmp_path / "repaired.jsonl"

    assert relabel_script.main(["relabel", str(destination), *(str(path) for path in paths)]) == 0

    parquet_reader.assert_has_calls([call(path) for path in paths])
    assert parquet_reader.call_count == 2
    assert inputs == before
    written = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert len(written) == 2
    assert written[0] == bad
    assert written[1]["document_id"] == "synthetic-1"
    gt = json.loads(written[1]["gt_fields"])
    assert gt["entity_name"] == "Café Holdings"
    assert gt["record_type"] == "bylaws" and gt["intent"] == "governance_rules"
    assert json.loads(gt["keywords"]) == ["Bylaws", "Café Holdings"]
    output = capsys.readouterr().out.splitlines()
    assert output[0] == f"2 rows -> {destination}"
    counts = ast.literal_eval(output[1].removeprefix("changes: "))
    assert counts == {
        "entity_name": 1, "subject_matter": 1, "keywords": 1,
        "record_type": 1, "intent": 1, "gt_unparseable": 1,
    }
    audit = ast.literal_eval(output[2].removeprefix("post-repair audit totals: "))
    assert audit["rows"] == 2 and audit["gt_unparseable"] == 1
    assert "subject_matter_template" not in audit and "keywords_provenance_ids" not in audit
