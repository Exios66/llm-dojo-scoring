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
    assert reg.get("f1_macro").source == "classification.macro_prf"
    assert reg.get("extraction_f1").source == "extraction_metrics.extraction_binary_metrics"
    assert reg.get("extraction_f2").tier is MetricTier.HEADLINE
    assert reg.get("content_topic_f1_macro").tier is MetricTier.HEADLINE
    assert reg.get("determination_consistency").applies_to("insurance_claims_specialist")


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
    assert d.citation == ""
    assert d.inclusion == ""
    assert d.ground_truth == ""


_ALLOWED_GT = {"required", "optional", "structural", "none"}

# Mailroom aliases this package does not compute (source stays null).
_EMITTER_ONLY = {
    "schema_valid",
    "parse_error",
    "success_rate",
    "completeness",
    "class_correct",
    "stage_correct",
    "extraction_correctness",
    "extraction_needs_judge_review",
    "expected_field_presence",
    "extraction_overall_verified_precision",
    "extraction_verified_precision",
    "mailroom-pipeline-judge",
    "mailroom-pipeline-quality",
    "extraction_hallucination_rate",
}


def test_t0_t1_metrics_have_citation_inclusion_ground_truth():
    reg = load_registry()
    t0_t1 = [m for m in reg.metrics.values() if m.tier <= MetricTier.CORE]
    assert t0_t1
    for m in t0_t1:
        assert m.citation.strip(), m.name
        assert m.inclusion.strip(), m.name
        assert m.ground_truth in _ALLOWED_GT, (m.name, m.ground_truth)
        if m.name in _EMITTER_ONLY:
            assert m.source is None, m.name
            assert m.ground_truth == "none", m.name
        elif m.name != "field_presence":
            assert m.source, m.name


def test_field_presence_honesty_gap_is_documented():
    m = load_registry().get("field_presence")
    assert "does not emit" in m.citation.lower() or "does not emit" in m.notes.lower()
    assert "not computed" in m.inclusion.lower()


def test_structural_metrics_are_labeled_structural():
    reg = load_registry()
    assert reg.get("determination_consistency").ground_truth == "structural"
    assert reg.get("intake_prep_completeness").ground_truth == "structural"


def test_custom_yaml_loads_without_citation_keys(tmp_path):
    path = tmp_path / "reg.yaml"
    path.write_text(yaml.safe_dump({"metrics": {"only_mine": {"tier": "core"}}}))
    reg = Registry.from_yaml(path)
    m = reg.get("only_mine")
    assert m.citation == ""
    assert m.inclusion == ""
    assert m.ground_truth == ""
