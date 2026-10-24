"""Skeleton guarantees for llm-dojo-pipeline (#83)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import dojo_pipeline as dp
from llm_dojo_scoring import score_task
from llm_dojo_scoring.mailroom import LANGFUSE_SCORE_NAME_ALIASES
from dojo_pipeline.sinks import (
    FanoutSink, LangfuseTraceSink, LocalManifestTraceSink, OTelTraceSink,
    PhoenixTraceSink, SinkTargetMissing, TraceSink,
)

LABELS_E = ["nda", "lease", "nda", "lease"]
LABELS_P = ["nda", "lease", "lease", "lease"]
CASES = {
    "subtype": (LABELS_E, LABELS_P, {}),
    "doc_class": (["contract", "correspondence"], ["contract", "contract"], {}),
    "multiclass": (LABELS_E, LABELS_P, {}),
    "docclass": (["contract", "merger_agreement"], ["contract", "contract"], {}),
    "maud_question": (["all_cash", "all_stock"], ["all_cash", "all_cash"], {}),
    "enron_topic": (["legal", "finance"], ["legal", "legal"], {}),
    "enron_sentiment": (["positive", "negative"], ["positive", "positive"], {}),
    "wer": (["hello world"], ["hello word"], {}),
    "transcription": (["the quick fox"], ["the quick fox"], {}),
}


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == dp.__version__


def test_every_primary_task_key_has_a_family():
    expected = {"subtype", "doc_class", "multiclass", "docclass", "maud_docclass",
                "maud_question", "maud_extraction", "enron_topic", "enron_sentiment",
                "transcription", "wer", "cer"}
    assert expected <= set(dp.TASK_FAMILY)


@pytest.mark.parametrize("task", ["legalbench", "contracteval", "court_opinion", "chained"])
def test_mixed_source_tasks_are_not_primary(task):
    with pytest.raises(KeyError, match="mixed_source"):
        dp.family_for_task(task)


@pytest.mark.parametrize("task", sorted(CASES))
def test_family_numbers_equal_core(task):
    expected, predicted, kw = CASES[task]
    result = dp.score_family(task, expected, predicted, n_boot=50, **kw)
    core = score_task(task, expected, predicted, n_boot=50, **kw)
    assert result.metrics == core
    assert result.family == dp.TASK_FAMILY[task]


@pytest.mark.parametrize("task", sorted(CASES))
def test_contract_keys_present(task):
    expected, predicted, _ = CASES[task]
    result = dp.score_family(task, expected, predicted)
    assert result.ok, result.contract_gaps


def test_hierarchical_subclass_contract():
    result = dp.score_family(
        "maud_docclass", ["merger_agreement"] * 2, ["merger_agreement"] * 2,
        expected_subclass=["all_cash", "all_stock"],
        predicted_subclass=["all_cash", "all_cash"],
    )
    assert result.ok, result.contract_gaps
    assert "subclass_accuracy" in result.metrics


def test_strict_raises_on_gap(monkeypatch):
    import dojo_pipeline.families as fam
    monkeypatch.setattr(fam, "score_task", lambda *a, **k: {"n": 1})
    with pytest.raises(dp.ContractViolation):
        fam.score_family("subtype", ["a"], ["a"], strict=True)


def test_events_skip_nested_and_infer_types():
    result = dp.score_family("enron_topic", ["legal", "finance"], ["legal", "legal"])
    events = dp.events_from_result(result, agent="correspondence_specialist",
                                   run_id="r1", trace_id="t1")
    names = {e.metric for e in events}
    assert "accuracy" in names and "per_class" not in names and "task" not in names
    assert all(e.trace_id == "t1" and e.metadata["family"] == "correspondence" for e in events)
    assert dp.infer_data_type(True) == "BOOLEAN"
    assert dp.infer_data_type("CORRECT") == "CATEGORICAL"


def test_event_down_converts_to_core_record():
    ev = dp.ScoreEvent(metric="wer", value=0.1, agent="pdf_transcriber",
                       trace_id="t", comment="c")
    rec = ev.to_score_record()
    assert rec.metadata["trace_id"] == "t" and rec.metadata["data_type"] == "NUMERIC"


def test_local_manifest_roundtrip(tmp_path):
    sink = LocalManifestTraceSink(tmp_path / "m.jsonl")
    assert isinstance(sink, TraceSink)
    ev = dp.ScoreEvent(metric="cer", value=0.05, agent="image_extractor")
    sink.emit_many([ev, ev])
    assert sink.read_all() == [ev, ev]


class _FakeLangfuse:
    def __init__(self):
        self.sent = []

    def create_score(self, **kw):
        self.sent.append(kw)


def test_langfuse_wire_name_parity_with_dojo_alias_table():
    sink = LangfuseTraceSink(_FakeLangfuse())
    for canonical, alias in LANGFUSE_SCORE_NAME_ALIASES.items():
        assert sink.wire_name(canonical) == alias
    assert sink.wire_name("f1_macro") == "f1_macro"


def test_langfuse_refuses_unattached_score():
    client = _FakeLangfuse()
    sink = LangfuseTraceSink(client)
    with pytest.raises(SinkTargetMissing):
        sink.emit(dp.ScoreEvent(metric="wer", value=0.1, agent="pdf_transcriber"))
    assert client.sent == [] and sink.failure_counts() == {"missing_trace_id": 1}


@pytest.mark.parametrize("cls", [PhoenixTraceSink, OTelTraceSink])
def test_planned_sinks_raise(cls):
    with pytest.raises(NotImplementedError, match="#83"):
        cls().emit(dp.ScoreEvent(metric="wer", value=0.0, agent="x"))


def test_pipeline_scorer_transcriber_node_to_two_sinks(tmp_path):
    client = _FakeLangfuse()
    local = LocalManifestTraceSink(tmp_path / "m.jsonl")
    scorer = dp.PipelineScorer([local, LangfuseTraceSink(client)], strict=True)
    result = scorer.score_node("image_extractor", ["invoice total 42"], ["invoice total 41"])
    assert result.family == "transcription"
    events = scorer.emit(result, agent="image_extractor", metrics=("wer", "cer"),
                         trace_id="trace-1")
    assert [e.metric for e in local.read_all()] == ["wer", "cer"] == [s["name"] for s in client.sent]
    assert len(events) == 2


def test_pipeline_scorer_unscored_node_is_explicit():
    scorer = dp.PipelineScorer()
    with pytest.raises(NotImplementedError, match="#83"):
        scorer.score_node("judge_verify", [], [])
    with pytest.raises(KeyError):
        scorer.score_node("nope", [], [])


def test_fanout_tries_every_sink_before_raising(tmp_path):
    local = LocalManifestTraceSink(tmp_path / "m.jsonl")
    fan = FanoutSink([PhoenixTraceSink(), local])
    with pytest.raises(NotImplementedError):
        fan.emit(dp.ScoreEvent(metric="wer", value=0.0, agent="x"))
    assert len(local.read_all()) == 1
    assert fan.failure_counts() == {"phoenix.emit": 1}
