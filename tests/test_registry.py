"""KANBAN-061 — network-free tests for the registry module."""

from __future__ import annotations

import pytest
import yaml

from llm_dojo_scoring.registry import (
    clear_registry_cache,
    load_registry,
    MetricDef,
    MetricTier,
    Registry,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_registry_cache()
    yield
    clear_registry_cache()


def test_default_registry_loads_and_is_cached():
    r1 = load_registry()
    r2 = load_registry()
    assert r1 is r2
    assert len(r1.metrics) >= 40


def test_every_metric_has_valid_tier_and_units():
    reg = load_registry()
    for m in reg.metrics.values():
        assert isinstance(m.tier, MetricTier)
        assert 0 <= int(m.tier) <= 3
        assert m.units
        assert m.aggregation in {"mean", "sum", "none"}


def test_tier_distribution_matches_pruning_plan():
    reg = load_registry()
    assert reg.get("f1_macro").tier is MetricTier.HEADLINE
    assert reg.get("accuracy").tier is MetricTier.HEADLINE
    for name in ("precision", "recall", "f2", "cost_per_document", "audit_disagreement_rate"):
        assert reg.get(name).tier is MetricTier.CORE, name
    for name in ("confusion_matrix", "bootstrap_ci", "failure_mode_breakdown"):
        assert reg.get(name).tier is MetricTier.DEEP, name
    for name in ("judge_notes", "raw_prediction", "trace_id", "llm_call_count"):
        assert reg.get(name).tier is MetricTier.LOG, name


def test_filter_by_max_tier_and_agent():
    reg = load_registry()
    headline_core = reg.filter(max_tier=1)
    assert all(m.tier <= MetricTier.CORE for m in headline_core)
    audit = reg.filter(agent="audit_agent", max_tier=3)
    names = {m.name for m in audit}
    assert {"audit_disagreement_rate", "audit_resolution_rate"} <= names
    # sorter must not see audit-only metrics
    sorter = {m.name for m in reg.filter(agent="sorter")}
    assert "audit_disagreement_rate" not in sorter
    assert "f1_macro" in sorter  # ALL agents


def test_applies_to():
    reg = load_registry()
    assert reg.get("f1_macro").applies_to("anything")
    assert not reg.get("audit_disagreement_rate").applies_to("sorter")
    assert reg.get("audit_disagreement_rate").applies_to("audit_agent")


def test_unknown_metric_raises_keyerror():
    reg = load_registry()
    with pytest.raises(KeyError):
        reg.get("definitely_not_a_metric")


def test_yaml_roundtrip_custom_registry(tmp_path):
    custom = {
        "metrics": {
            "custom_metric": {
                "tier": "headline",
                "units": "USD",
                "description": "test metric",
                "applicable_agents": ["sorter"],
                "aggregation": "sum",
            },
            "named_tier": {"tier": 2},
        }
    }
    path = tmp_path / "reg.yaml"
    path.write_text(yaml.safe_dump(custom))
    reg = Registry.from_yaml(path)
    assert reg.get("custom_metric").tier is MetricTier.HEADLINE
    assert reg.get("custom_metric").units == "USD"
    assert reg.get("named_tier").tier is MetricTier.DEEP


def test_env_var_override(monkeypatch, tmp_path):
    path = tmp_path / "reg.yaml"
    path.write_text(
        yaml.safe_dump({"metrics": {"only_mine": {"tier": "core"}}})
    )
    monkeypatch.setenv("LLM_DOJO_SCORING_REGISTRY", str(path))
    reg = load_registry()
    assert reg.names() == ["only_mine"]


def test_explicit_path_beats_env(monkeypatch, tmp_path):
    env_path = tmp_path / "env.yaml"
    env_path.write_text(yaml.safe_dump({"metrics": {"env_metric": {"tier": 0}}}))
    file_path = tmp_path / "file.yaml"
    file_path.write_text(yaml.safe_dump({"metrics": {"file_metric": {"tier": 1}}}))
    monkeypatch.setenv("LLM_DOJO_SCORING_REGISTRY", str(env_path))
    assert load_registry(file_path).names() == ["file_metric"]


def test_mailroom_score_configs_preserved_as_aliases():
    """The 37 flat mailroom SCORE_CONFIGS names survive consolidation."""
    reg = load_registry()
    preserved = [
        "schema_valid", "parse_error", "stage_completed", "run_aborted",
        "guardrail_triggered", "classification_confidence",
        "extraction_confidence", "judge_notes", "llm_call_count",
        "completeness", "success_rate", "classification_correct",
    ]
    for name in preserved:
        assert name in reg.metrics, name
    # consolidation notes recorded
    assert "consolidat" in reg.get("success_rate").notes
    assert "confidence_calibration_error" in load_registry().metrics


def test_audit_metrics_are_new_and_core():
    reg = load_registry()
    assert "audit_agent" in reg.get("audit_disagreement_rate").applicable_agents
    assert "insurance_claims_auditor" in reg.get("audit_disagreement_rate").applicable_agents
    assert "arbiter" in reg.get("audit_resolution_rate").applicable_agents
    assert not reg.get("audit_disagreement_rate").applies_to("sorter")


def test_metricdef_defaults():
    d = MetricDef(name="x", tier=MetricTier.CORE)
    assert d.applies_to("whoever")
    assert d.units == "float[0,1]"
    assert d.aggregation == "mean"
