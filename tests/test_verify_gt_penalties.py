"""Synthetic, offline checks for the perfect-prediction replay tool."""

import json
import sys
from copy import deepcopy
from types import ModuleType

import pandas as pd
import pytest

from scripts import gen_maud_catalog as generator
from scripts import verify_gt_penalties as verifier


@pytest.mark.parametrize("script", [generator, verifier], ids=["catalog", "replay"])
def test_local_split_requires_existing_file(script, tmp_path):
    with pytest.raises(SystemExit, match="missing parquet for split 'test'"):
        script._load_split("test", tmp_path, "unused-revision")


@pytest.mark.parametrize("script", [generator, verifier], ids=["catalog", "replay"])
def test_local_split_reads_documented_path(script, tmp_path, mocker):
    path = tmp_path / "test" / "test-00000-of-00001.parquet"
    path.parent.mkdir()
    path.touch()
    frame = pd.DataFrame({"expected": ["merger_agreement"]})
    read = mocker.patch.object(pd, "read_parquet", return_value=frame)
    assert script._load_split("test", tmp_path, "unused-revision") is frame
    read.assert_called_once_with(path)


@pytest.mark.parametrize("script", [generator, verifier], ids=["catalog", "replay"])
def test_hub_split_forwards_pinned_revision(script, monkeypatch, mocker):
    hub = ModuleType("huggingface_hub")
    hub.hf_hub_download = mocker.Mock(return_value="cached.parquet")
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    frame = pd.DataFrame()
    read = mocker.patch.object(pd, "read_parquet", return_value=frame)
    assert script._load_split("train", None, script.DATASET_REVISION) is frame
    hub.hf_hub_download.assert_called_once_with(
        "Lucius-Morningstar/mailroom-dataset",
        "parquet/ground_truth/train/train-00000-of-00001.parquet",
        repo_type="dataset", revision="bc9eab280044befb51e19dda3071d290a8677f42",
    )
    read.assert_called_once_with("cached.parquet")


def test_perfect_prediction_omits_empty_values_and_presence_annotations():
    fields = {
        "cuad_clause_labels": {"Governing Law": [{"text": "Delaware"}]},
        "missing": None, "blank": " ", "placeholder": "n/a", "empty_json": "[]",
        "empty_list": [], "empty_map": {}, "zero": 0, "false": False,
        "parties": ["Acme"], "maud_clause_labels": {"No-Shop": {"answer": "Yes"}},
    }
    original = deepcopy(fields)
    assert verifier.perfect_prediction(fields) == {
        "zero": 0, "false": False, "parties": ["Acme"],
        "maud_clause_labels": {"No-Shop": {"answer": "Yes"}},
    }
    assert fields == original


@pytest.mark.parametrize("labels", [None, "", "not JSON", "[]", [], 42])
def test_invalid_label_containers_are_ignored(labels):
    assert verifier._maud_labels({"maud_clause_labels": labels}) == {}


@pytest.mark.parametrize("encoded", [False, True])
def test_maud_labels_accepts_mapping_or_json(encoded):
    labels = {"No-Shop": {"answer": "Yes"}}
    value = json.dumps(labels) if encoded else labels
    assert verifier._maud_labels({"maud_clause_labels": value}) == labels


@pytest.mark.parametrize("encoded", [False, True])
def test_class_check_reports_row_catalog_violation(encoded):
    classes = ["Yes", "No"]
    labels = {
        "No-Shop": {"answer": "Strict liability",
                    "valid_classes": json.dumps(classes) if encoded else classes},
        "Knowledge Definition": {"answer": "true", "valid_classes": ["Yes"]},
        "Missing answer": {"valid_classes": ["Yes"]},
        "Missing classes": {"answer": "Yes"},
        "Malformed classes": {"answer": "Yes", "valid_classes": "not JSON"},
        "Not a record": "Yes",
    }
    failures = [(0, "earlier-failure")]
    assert verifier._check_maud_labels(labels, failures, 7) == 1
    assert failures == [
        (0, "earlier-failure"), (7, "maud-class-mismatch", "No-Shop", "Strict liability"),
    ]


@pytest.fixture
def replay_frame(monkeypatch):
    frame = pd.DataFrame([
        {"expected_specialist": "contracts_specialist", "gt_fields": json.dumps({
            "parties": ["Acme"],
            "maud_clause_labels": {"No-Shop": {
                "answer": "Yes", "valid_classes": ["Yes", "No"],
                "category": "Deal Protection and Related Provisions",
            }},
        })},
        {"expected_specialist": "contracts_specialist", "gt_fields": json.dumps({
            "doc_type": "contract", "contract_subtype": "license",
        })},
    ])
    monkeypatch.setattr(verifier, "_load_split", lambda *_: frame)
    return frame


def test_replay_perfect_row_and_unscorable_row(replay_frame):
    report = verifier.verify_split("test", None, "synthetic-revision")
    assert report["split"] == "test"
    assert report["failures"] == []
    assert report["totals"] == {
        "rows": 2, "scored": 1, "unscorable": 1, "events": 1,
        "fn": 0, "fp": 0, "spurious": 0, "f1_fail": 0, "presence_fail": 0,
        "maud_rows": 1, "maud_parity_fail": 0, "maud_class_mismatch": 0,
    }
    assert report["per_specialist"]["contracts_specialist"] == {
        "rows": 2, "scored": 1, "unscorable": 1, "events": 1,
        "fn": 0, "fp": 0, "spurious": 0, "presence_fail": 0,
    }


def test_replay_detects_invalid_gt_even_when_prediction_is_identical(replay_frame):
    fields = json.loads(replay_frame.loc[0, "gt_fields"])
    fields["maud_clause_labels"]["No-Shop"]["answer"] = "Strict liability"
    replay_frame.loc[0, "gt_fields"] = json.dumps(fields)
    report = verifier.verify_split("test", None, "synthetic-revision")
    assert report["totals"]["maud_class_mismatch"] == 1
    assert report["totals"]["maud_parity_fail"] == 1
    assert report["failures"] == [
        (0, "maud-class-mismatch", "No-Shop", "Strict liability"),
        (0, "contracts_specialist", "maud:maud_valid_class_rate", 0.0, None, None),
    ]


@pytest.mark.parametrize("metric", verifier.MAUD_PARITY_METRICS)
def test_replay_reports_missing_parity_metrics(replay_frame, mocker, metric):
    suite = mocker.Mock(field_types={})
    scores = {name: 1.0 for name in verifier.MAUD_PARITY_METRICS if name != metric}
    suite.score_document.return_value = scores
    mocker.patch.object(verifier, "get_suite", return_value=suite)
    report = verifier.verify_split("test", None, "synthetic-revision")
    assert report["totals"]["maud_parity_fail"] == 1
    assert report["failures"] == [
        (0, "contracts_specialist", f"maud-missing:{metric}", None, None, None),
    ]


@pytest.mark.parametrize("failure", [
    None, "fn", "fp", "spurious", "f1_fail", "presence_fail",
    "maud_parity_fail", "maud_class_mismatch", "detail-only",
])
def test_cli_fails_for_penalty_counts_or_failure_details(monkeypatch, mocker, failure):
    totals = dict.fromkeys([
        "fn", "fp", "spurious", "f1_fail", "presence_fail",
        "maud_parity_fail", "maud_class_mismatch",
    ], 0)
    details = [(0, "failure")] if failure == "detail-only" else []
    if failure in totals:
        totals[failure] = 1
    replay = mocker.patch.object(verifier, "verify_split", side_effect=[
        {"totals": totals, "failures": details, "per_specialist": {}},
        {"totals": dict.fromkeys(totals, 0), "failures": [], "per_specialist": {}},
    ])
    monkeypatch.setattr(sys, "argv", ["verify_gt_penalties.py"])
    assert verifier.main() == (1 if failure else 0)
    assert replay.call_args_list == [
        mocker.call("test", None, verifier.DATASET_REVISION),
        mocker.call("train", None, verifier.DATASET_REVISION),
    ]
