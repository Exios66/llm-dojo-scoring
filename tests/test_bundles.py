"""KANBAN-061 — network-free tests for bundles, profiles, pruning."""

from __future__ import annotations

import pytest
import yaml

from llm_dojo_scoring.bundles import (
    BUILTIN_BUNDLES,
    bundle_metric_names,
    get_bundle,
    list_bundles,
    validate_bundle,
)
from llm_dojo_scoring.pruning import (
    dashboard_metrics,
    headline_metrics,
    prune_metrics,
)
from llm_dojo_scoring.profiles import (
    clear_profile_cache,
    get_profile,
    list_profiles,
    load_profiles,
)


@pytest.fixture(autouse=True)
def _clean_caches():
    from llm_dojo_scoring.registry import clear_registry_cache

    clear_registry_cache()
    clear_profile_cache()
    yield
    clear_registry_cache()
    clear_profile_cache()


# ----------------------------- bundles -------------------------------------


def test_all_ten_bundles_exist():
    assert set(list_bundles()) == {
        "classification", "extraction", "extraction_open", "cost",
        "factuality", "laziness_detection", "audit", "reporter",
        "transcription", "intake",
    }


def test_every_bundle_validates_against_default_registry():
    for name in list_bundles():
        assert validate_bundle(get_bundle(name))  # raises KeyError on typo


def test_audit_bundle_contents():
    names = set(bundle_metric_names("audit"))
    assert {"audit_disagreement_rate", "audit_resolution_rate"} <= names


def test_agent_overrides_add_specialist_extras():
    base = set(bundle_metric_names("extraction"))
    contracts = set(bundle_metric_names("extraction", agent="contracts_specialist"))
    court = set(bundle_metric_names("extraction", agent="court_opinions_specialist"))
    assert {"jaccard_similarity", "laziness_rate"} <= (contracts - base) | contracts
    assert "legalbench_macro_f1" in court


def test_max_tier_prunes_bundle_names():
    all_names = bundle_metric_names("classification")
    headlines = bundle_metric_names("classification", max_tier=0)
    assert headlines
    assert set(headlines) <= set(all_names)
    assert "f1_macro" in headlines
    assert "confusion_matrix" not in headlines


def test_unknown_bundle_raises():
    with pytest.raises(KeyError):
        get_bundle("nope")


# ----------------------------- profiles ------------------------------------


def test_default_profiles():
    # v0.6.0 (KANBAN-062/063): the original 14 plus the review/audit lanes.
    # v0.7.0 (KANBAN-067): + insurance_claims_specialist (23rd mailroom agent;
    # deliberate re-pin — see tests/test_doc_bundles.py for the full surface).
    expected = {
        "sorter", "contracts_specialist", "corporate_records_specialist",
        "due_diligence_specialist", "correspondence_specialist",
        "compliance_specialist", "court_opinions_specialist", "reporter",
        "judge", "boss", "pdf_transcriber", "image_extractor", "archivist",
        "audit_agent",
        # v0.6.0 additions
        "sorter_reviewer",
        "contract_auditor", "corporate_records_auditor",
        "due_diligence_auditor", "correspondence_auditor",
        "compliance_auditor", "court_opinions_auditor",
        "arbiter",
        # v0.7.0 addition (KANBAN-067)
        "insurance_claims_specialist",
        # v0.8.0: dedicated auditor matching the 7th specialist
        "insurance_claims_auditor",
        # v0.9.0: intake clerk (pre-sorter text prep)
        "intake",
    }
    assert set(list_profiles()) == expected


def test_task_derived_bundle_resolution():
    p = get_profile("sorter")
    assert p.resolve_bundle().name == "classification"
    a = get_profile("audit_agent")
    assert a.resolve_bundle().name == "audit"
    assert a.resolve_bundle(fallback=True).name == "extraction"


def test_yaml_overlay_overrides_and_extends(tmp_path, monkeypatch):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "agents": {
                    "audit_agent": {"metrics_bundle": "factuality"},
                    "brand_new_agent": {
                        "title": "New",
                        "tasks": ["extract"],
                        "metrics_bundle": "extraction",
                    },
                }
            }
        )
    )
    monkeypatch.setenv("LLM_DOJO_SCORING_PROFILES", str(path))
    profiles = load_profiles()
    assert profiles["audit_agent"].metrics_bundle == "factuality"
    assert "brand_new_agent" in profiles
    # defaults still present
    assert "sorter" in profiles


def test_yaml_overlay_bad_bundle_fails_fast(tmp_path, monkeypatch):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        yaml.safe_dump({"agents": {"x": {"tasks": ["extract"], "metrics_bundle": "bogus"}}})
    )
    monkeypatch.setenv("LLM_DOJO_SCORING_PROFILES", str(path))
    with pytest.raises(KeyError):
        load_profiles()


# ----------------------------- pruning -------------------------------------


def test_prune_metrics_caps_tier():
    out = prune_metrics(max_tier=1)
    assert all(m.tier <= 1 for m in out)
    deep = prune_metrics(max_tier=3)
    assert len(deep) > len(out)


def test_dashboard_metrics_sorter_headline_only():
    assert headline_metrics("sorter") == ["accuracy", "f1_macro"]
    core = dashboard_metrics("sorter")
    assert "f1_macro" in core and "confusion_matrix" not in core


def test_dashboard_metrics_contracts_specialist():
    head = headline_metrics("contracts_specialist")
    assert "extraction_overall_score" in head
    assert "extraction_f1" in head
    assert "extraction_f2" in head


def test_dashboard_metrics_audit_agent():
    core = dashboard_metrics("audit_agent")
    assert "audit_disagreement_rate" in core
    assert "audit_resolution_rate" in core


def test_unknown_agent_falls_back_to_applicable_metrics():
    names = dashboard_metrics("mystery_agent")
    assert "f1_macro" in names  # ALL-applicable metrics survive
    assert "audit_disagreement_rate" not in names
