"""KANBAN-061 — network-free tests for the unified emitter."""

from __future__ import annotations

import json

import pytest

from llm_dojo_scoring.emitter import (
    Emitter,
    get_emitter,
    LangfuseSink,
    LocalManifestSink,
    reset_default_emitter,
    ScoreRecord,
)
from llm_dojo_scoring.registry import clear_registry_cache, MetricTier, Registry


@pytest.fixture(autouse=True)
def _clean():
    clear_registry_cache()
    reset_default_emitter()
    yield
    clear_registry_cache()
    reset_default_emitter()


def _tiny_registry() -> Registry:
    from llm_dojo_scoring.registry import MetricDef

    reg = Registry()
    reg.metrics["f1_macro"] = MetricDef(name="f1_macro", tier=MetricTier.HEADLINE)
    reg.metrics["raw_prediction"] = MetricDef(
        name="raw_prediction", tier=MetricTier.LOG, aggregation="none"
    )
    return reg


def test_emit_score_roundtrip(tmp_path):
    sink = LocalManifestSink(tmp_path / "scores.jsonl")
    em = Emitter(sinks=[sink], registry=_tiny_registry())
    rec = em.emit_score("sorter", doc_id="d1", metric_name="f1_macro", value=0.9, run_id="r1")
    assert rec.value == 0.9
    lines = (tmp_path / "scores.jsonl").read_text().strip().splitlines()
    loaded = json.loads(lines[0])
    assert loaded["agent"] == "sorter" and loaded["metric"] == "f1_macro"


def test_unknown_metric_fails_fast(tmp_path):
    em = Emitter(sinks=[], registry=_tiny_registry())
    with pytest.raises(KeyError):
        em.emit_score("sorter", "d1", "not_a_metric", 1.0)


def test_scorecard_tier_filtering_and_aggregation(tmp_path):
    em = Emitter(sinks=[], registry=_tiny_registry())
    for i, v in enumerate([0.8, 0.9, 1.0]):
        em.emit_score("sorter", f"d{i}", "f1_macro", v, run_id="r1")
    em.emit_score("sorter", "dX", "raw_prediction", "lorem", run_id="r1")

    full = em.get_scorecard("sorter", run_id="r1")
    assert full["f1_macro"] == pytest.approx(0.9)
    assert full["raw_prediction"] == "lorem"

    dashboard = em.get_scorecard("sorter", run_id="r1", min_tier=1)
    assert "f1_macro" in dashboard
    assert "raw_prediction" not in dashboard


def test_scorecard_run_isolation(tmp_path):
    em = Emitter(sinks=[], registry=_tiny_registry())
    em.emit_score("sorter", "d1", "f1_macro", 0.5, run_id="r1")
    em.emit_score("sorter", "d1", "f1_macro", 1.0, run_id="r2")
    assert em.get_scorecard("sorter", run_id="r1")["f1_macro"] == 0.5
    assert em.get_scorecard("sorter", run_id="r2")["f1_macro"] == 1.0


def test_compare_headlines_delta(tmp_path):
    em = Emitter(sinks=[], registry=_tiny_registry())
    em.emit_score("a_agent", "d", "f1_macro", 0.5)
    em.emit_score("b_agent", "d", "f1_macro", 0.7)
    cmp = em.compare_headlines("a_agent", "b_agent")
    assert cmp["f1_macro"]["delta_b_minus_a"] == pytest.approx(0.2)


def test_sum_aggregation_for_cost(tmp_path):
    from llm_dojo_scoring.registry import MetricDef

    reg = Registry()
    reg.metrics["estimated_cost_usd"] = MetricDef(
        name="estimated_cost_usd", tier=MetricTier.CORE, aggregation="sum"
    )
    em = Emitter(sinks=[], registry=reg)
    for v in (0.1, 0.2, 0.3):
        em.emit_score("sorter", "d", "estimated_cost_usd", v)
    assert em.get_scorecard("sorter")["estimated_cost_usd"] == pytest.approx(0.6)


def test_langfuse_sink_inert_without_keys(monkeypatch):
    """Without keys the sink marks itself unavailable and never raises."""
    import os

    for k in list(os.environ):
        if k.startswith("LANGFUSE"):
            monkeypatch.delenv(k)
    s = LangfuseSink()
    assert s.available is False
    assert s._client is None
    s.emit(ScoreRecord(agent="x", metric="f1_macro", value=1.0))  # no-op
    s.flush()  # no-op


def test_local_sink_read_all(tmp_path):
    sink = LocalManifestSink(tmp_path / "s.jsonl")
    em = Emitter(sinks=[sink], registry=_tiny_registry())
    em.emit_score("sorter", "d1", "f1_macro", 0.42)
    records = sink.read_all()
    assert len(records) == 1 and records[0].value == 0.42


def test_default_emitter_singleton():
    e1 = get_emitter()
    e2 = get_emitter()
    assert e1 is e2
    reset_default_emitter()
    assert get_emitter() is not e1


def test_register_metric_adhoc(tmp_path):
    from llm_dojo_scoring.registry import MetricDef

    em = Emitter(sinks=[], registry=Registry())
    em.register_metric("custom_kpi", 0, description="ad hoc")
    em.emit_score("boss", "d1", "custom_kpi", 3.0)
    card = em.get_scorecard("boss", min_tier=0)
    assert card["custom_kpi"] == 3.0
