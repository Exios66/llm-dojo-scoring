"""Tests for the Langfuse sync module — mocked HTTP transport plus a live
integration test that runs only when explicitly enabled (env
LLM_DOJO_SCORING_LANGFUSE_TEST=1 with credentials present)."""

import json
import os
from unittest import mock

import pandas as pd
import pytest

from llm_dojo_scoring import langfuse_sync as ls


def _trace(session: str, *, subtype_ok: bool, subtype_ok_equiv: bool,
           doc_type_ok: bool = True, contract_subtype: str = "license",
           expected: str = "license", confidence: float = 0.95,
           filename: str = "doc.pdf", ts: str = "2026-08-16T00:00:00Z",
           model: str = "qwen/qwen3.7-flash", prompt_version: str = "sorter_v13"):
    return {
        "id": "t-" + session + filename,
        "name": "subtype_classification",
        "sessionId": session,
        "timestamp": ts,
        "input": {"filename": filename, "expected": expected,
                  "prompt_version": prompt_version, "model": model},
        "output": {"sorter": {
            "doc_type": "contract" if doc_type_ok else "corporate_record",
            "contract_subtype": contract_subtype,
            "expected_subtype": expected,
            "doc_type_ok": doc_type_ok,
            "subtype_ok": subtype_ok,
            "subtype_ok_equiv": subtype_ok_equiv,
            "confidence": confidence,
        }},
    }


def test_row_from_trace_sorter():
    row = ls.row_from_trace(_trace("run_a", subtype_ok=True, subtype_ok_equiv=True))
    assert row["expected_subtype"] == "license"
    assert row["subtype_ok"] is True
    assert row["doc_type_ok"] is True
    assert row["filename"] == "doc.pdf"


def test_row_from_trace_skips_non_sorter_output():
    trace = {"id": "x", "sessionId": "s", "input": {}, "output": {"other": 1}}
    assert ls.row_from_trace(trace) is None


def test_row_from_trace_docclass():
    trace = {
        "id": "d", "sessionId": "s", "timestamp": "2026-08-16T00:00:00Z",
        "input": {"filename": "f", "prompt_version": "sorter_v6", "model": "m"},
        "output": {"sorter": {
            "doc_type": "corporate_record",
            "doc_subclass": "bylaws", "expected_subclass": "bylaws",
            "subclass_ok": True, "subclass_ok_equiv": True,
            "doc_type_ok": True, "confidence": 0.9,
        }},
    }
    row = ls.row_from_trace(trace, task=ls.DOCCLASS_TRACE)
    assert row["expected_subclass"] == "bylaws"
    assert row["subclass_ok"] is True


def test_group_rows_by_session():
    rows = [
        ("run_a", {"x": 1}),
        ("run_a", {"x": 2}),
        ("run_b", {"x": 3}),
    ]
    grouped = ls.group_rows_by_session(rows)
    assert sorted(grouped) == ["run_a", "run_b"]
    assert len(grouped["run_a"]) == 2


def test_aggregate_run_schema_and_values():
    rows = [
        {"expected_subtype": "license", "contract_subtype": "license",
         "subtype_ok": True, "subtype_ok_equiv": True, "doc_type_ok": True,
         "confidence": 0.95},
        {"expected_subtype": "license", "contract_subtype": "franchise",
         "subtype_ok": False, "subtype_ok_equiv": False, "doc_type_ok": True,
         "confidence": 0.9},
        {"expected_subtype": "franchise", "contract_subtype": "franchise",
         "subtype_ok": True, "subtype_ok_equiv": True, "doc_type_ok": True,
         "confidence": 1.0},
    ]
    rec = ls.aggregate_run("run_a", rows, model="qwen/qwen3.7-flash",
                           prompt_version="sorter_v13")
    assert rec["experiment_name"] == "run_a"
    s = rec["scores"]["sorter"]
    assert s["subtype_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["subtype_accuracy_equiv"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["exact_match"] == 1.0
    assert s["confidence"] == pytest.approx(0.95)
    assert s["subtype_accuracy_ci"]["n"] == 3
    assert s["per_subtype"]["license"]["total"] == 2
    assert s["per_subtype"]["license"]["accuracy"] == 0.5
    assert s["failure_insights"]["n_failed"] == 1
    assert rec["n_rows"] == 3


def test_records_to_sorter_frame_columns():
    rows = [{"expected_subtype": "license", "contract_subtype": "license",
             "subtype_ok": True, "subtype_ok_equiv": True, "doc_type_ok": True,
             "confidence": 0.95}]
    rec = ls.aggregate_run("run_a", rows, model="qwen/qwen3.7-flash",
                           prompt_version="sorter_v13")
    frame = ls.records_to_sorter_frame([rec])
    assert "Subtype Accuracy" in frame.columns
    assert "Experiment Name" in frame.columns
    assert len(frame) == 1
    assert frame["Experiment Name"].iloc[0] == "run_a"


def test_fetch_run_records_uses_session_groups():
    client = mock.Mock(spec=ls.LangfuseClient)
    client.list_traces.return_value = [
        _trace("run_a", subtype_ok=True, subtype_ok_equiv=True, filename="1.pdf"),
        _trace("run_a", subtype_ok=False, subtype_ok_equiv=False, filename="2.pdf"),
        _trace("run_b", subtype_ok=True, subtype_ok_equiv=True, filename="3.pdf"),
    ]
    records = ls.fetch_run_records(client)
    client.list_traces.assert_called_once()
    assert len(records) == 2
    by_name = {r["experiment_name"]: r for r in records}
    assert by_name["run_a"]["scores"]["sorter"]["subtype_accuracy"] == 0.5
    assert by_name["run_b"]["scores"]["sorter"]["subtype_accuracy"] == 1.0


def test_load_langfuse_config_env(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-x")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.com")
    monkeypatch.setenv("LANGFUSE_PROJECT", "proj")
    cfg = ls.load_langfuse_config()
    assert cfg.public_key == "pk-x"
    assert cfg.secret_key == "sk-x"
    assert cfg.base_url == "https://example.com"
    assert cfg.project == "proj"


def test_load_langfuse_config_required(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    env = tmp_path / "langfuse.env"
    env.write_text(
        'LANGFUSE_PUBLIC_KEY="pk-env"\n'
        'LANGFUSE_SECRET_KEY="sk-env"\n'
        'LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"\n'
    )
    cfg = ls.load_langfuse_config(env)
    assert cfg.public_key == "pk-env"
    assert cfg.secret_key == "sk-env"


def test_client_requires_credentials():
    with mock.patch.object(ls, "load_langfuse_config",
                           return_value=ls.LangfuseConfig(
                               "https://x", "", "")):
        with pytest.raises(ValueError):
            ls.LangfuseClient()


def test_sync_sorter_results_roundtrip(tmp_path):
    client = mock.Mock(spec=ls.LangfuseClient)
    client.list_traces.return_value = [
        _trace("run_a", subtype_ok=True, subtype_ok_equiv=True, filename="1.pdf"),
        _trace("run_a", subtype_ok=False, subtype_ok_equiv=False, filename="2.pdf"),
    ]
    records = ls.fetch_run_records(client)
    with mock.patch.object(ls, "LangfuseClient", return_value=client):
        frame, path = ls.sync_sorter_results(outdir=str(tmp_path))
    assert path is not None
    assert (tmp_path / "Sorter_Experiment_Results.xlsx").exists()
    assert (tmp_path / "Sorter_Experiment_Codebook.csv").exists()
    assert len(frame) == 1


def test_sync_sorter_results_forwards_session(tmp_path):
    client = mock.Mock(spec=ls.LangfuseClient)
    client.list_traces.return_value = [
        _trace("run_a", subtype_ok=True, subtype_ok_equiv=True, filename="1.pdf"),
    ]
    with mock.patch.object(ls, "LangfuseClient", return_value=client):
        ls.sync_sorter_results(outdir=str(tmp_path), session="run_a", workbook=False)
    client.list_traces.assert_called_once_with(name="subtype_classification",
                                               session="run_a", max_items=None)


def test_row_from_trace_document_pipeline():
    trace = {
        "id": "abc",
        "name": "document-pipeline",
        "sessionId": "pilot-hf-1",
        "userId": "eval",
        "release": "mailroom@0.5.0",
        "environment": "pilot",
        "input": {
            "filename": "claim.txt",
            "ground_truth": {
                "expected_hf_class": "insurance_claim",
                "expected_subclass": "carrier",
            },
        },
        "output": {
            "doc_type": "insurance_claim",
            "stage": "archived",
            "classification_confidence": 0.97,
        },
        "metadata": {},
    }
    row = ls.row_from_trace(trace, task=ls.PIPELINE_TRACE)
    assert row["exact_ok"] is True
    assert row["aligned_ok"] is True
    assert row["user_id"] == "eval"
    assert row["release"] == "mailroom@0.5.0"
    assert row["expected"] == "insurance_claim"


def test_row_from_trace_pipeline_aligns_merger():
    trace = {
        "id": "m",
        "name": "document-pipeline",
        "input": {"filename": "ma.txt", "ground_truth": {"expected_hf_class": "merger_agreement"}},
        "output": {"doc_type": "contract"},
        "metadata": {},
    }
    row = ls.row_from_trace(trace, task=ls.PIPELINE_TRACE)
    assert row["exact_ok"] is False
    assert row["aligned_ok"] is True


def test_aggregate_run_pipeline():
    rows = [
        {"expected": "merger_agreement", "predicted": "contract",
         "exact_ok": False, "aligned_ok": True,
         "expected_subclass": "all_cash", "predicted_subclass": "all_cash",
         "user_id": "u", "release": "mailroom@0.5.0", "environment": "pilot"},
        {"expected": "contract", "predicted": "contract",
         "exact_ok": True, "aligned_ok": True,
         "expected_subclass": None, "predicted_subclass": None},
    ]
    rec = ls.aggregate_run("pilot-hf-1", rows, task=ls.PIPELINE_TRACE)
    assert rec["scores"]["pipeline"]["exact_accuracy"] == 0.5
    assert rec["scores"]["pipeline"]["aligned_accuracy"] == 1.0
    assert rec["scores"]["pipeline"]["subclass_accuracy"] == 1.0
    assert rec["release"] == "mailroom@0.5.0"


# ---------------------------------------------------------------------------
# Live integration (opt-in)
# ---------------------------------------------------------------------------

LIVE_ENABLED = os.environ.get("LLM_DOJO_SCORING_LANGFUSE_TEST") == "1" \
    and os.environ.get("LANGFUSE_PUBLIC_KEY")


@pytest.mark.skipif(not LIVE_ENABLED,
                    reason="set LLM_DOJO_SCORING_LANGFUSE_TEST=1 + keys for live test")
def test_live_sync_sorter():
    client = ls.LangfuseClient()
    records = ls.fetch_run_records(client, task=ls.SORTER_TRACE, max_items=2000)
    assert records
    frame = ls.records_to_sorter_frame(records)
    assert len(frame) >= 1
    assert "Subtype Accuracy" in frame.columns
    # spot-check one experiment against a fetched trace group
    print(json.dumps({r["experiment_name"]: r["scores"]["sorter"]["subtype_accuracy"]
                      for r in records}, indent=1)[:500])