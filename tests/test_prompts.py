"""Prompt catalog — coverage, families, anti-priming. Network-free."""

from __future__ import annotations

import re

import pytest

from llm_dojo_scoring.profiles import DEFAULT_PROFILES
from llm_dojo_scoring.prompts import (
    FAMILIES,
    PromptRecord,
    get_prompt,
    list_prompts,
)
from llm_dojo_scoring.registry import MetricTier, load_registry

_SCORED_PHRASES = (
    "you will be scored",
    "you will be evaluated on",
    "maximize f1",
    "maximize f2",
    "leaderboard",
)


def test_list_prompts_covers_every_default_profile():
    catalog_agents = {rec.agent for rec in list_prompts()}
    missing = set(DEFAULT_PROFILES) - catalog_agents
    assert not missing, f"profiles missing from prompt catalog: {sorted(missing)}"


def test_get_prompt_production_and_docclass():
    sorter = get_prompt("sorter")
    assert sorter.family == "production"
    assert sorter.kind == "llm"
    assert sorter.text.strip()
    assert "extraction_f1" not in sorter.text
    docclass = get_prompt("sorter", family="docclass")
    assert docclass.family == "docclass"
    assert docclass.version == "sorter_docclass_v7"
    assert docclass.text != sorter.text


def test_intake_is_deterministic_empty_text():
    rec = get_prompt("intake")
    assert rec.kind == "deterministic"
    assert rec.text == ""
    assert "NFC" in rec.notes or "nfc" in rec.notes.lower()


def test_archivist_is_procedural_empty_text():
    rec = get_prompt("archivist")
    assert rec.kind == "procedural"
    assert rec.text == ""


def test_proposed_auditors_have_no_llm_body():
    for agent in (
        "corporate_records_auditor",
        "due_diligence_auditor",
        "correspondence_auditor",
        "compliance_auditor",
        "court_opinions_auditor",
        "insurance_claims_auditor",
    ):
        rec = get_prompt(agent)
        assert rec.kind == "proposed"
        assert rec.text == ""
        assert rec.metrics_bundle == "audit"


def test_contract_auditor_and_audit_agent_share_contracts_audit_v0():
    audit = get_prompt("audit_agent")
    contract = get_prompt("contract_auditor")
    assert audit.kind == "llm" and contract.kind == "llm"
    assert audit.source_key == "contracts_audit_v0"
    assert contract.source_key == "contracts_audit_v0"
    assert audit.text.strip() and contract.text.strip()


def test_unknown_prompt_raises():
    with pytest.raises(KeyError):
        get_prompt("not_an_agent")
    with pytest.raises(KeyError):
        get_prompt("intake", family="docclass")


def test_judge_completeness_alias():
    judge = get_prompt("judge")
    completeness = get_prompt("judge-completeness")
    assert completeness.text == judge.text
    assert get_prompt("judge-classification").kind == "llm"
    assert get_prompt("judge-correctness").kind == "llm"


def test_colloquial_priming_flagged_not_rewritten():
    rec = get_prompt("contracts_specialist")
    assert "colloquial_precision" in rec.priming
    assert "precision" in rec.text.lower()
    doc = get_prompt("contracts_specialist", family="docclass")
    assert "colloquial_precision" in doc.priming


def test_llm_templates_omit_t0_t1_registry_ids():
    """Snake_case T0/T1 metric ids must not appear in model-visible text.

    Live JSON schema keys that collide with registry names
    (``schema_valid``, ``classification_correct``, ``extraction_correctness``)
    are flagged on ``priming`` rather than rewritten.
    Bare English words (accuracy, precision, completeness) are allowed.
    """
    reg = load_registry()
    denylist = [
        m.name
        for m in reg.metrics.values()
        if m.tier <= MetricTier.CORE and "_" in m.name
    ]
    for rec in list_prompts(kind="llm"):
        assert rec.kind == "llm"
        text = rec.text
        assert text.strip(), rec.agent
        lower = text.lower()
        for phrase in _SCORED_PHRASES:
            assert phrase not in lower, f"{rec.agent}/{rec.family}: {phrase!r}"
        for name in denylist:
            if name in rec.priming:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text):
                raise AssertionError(
                    f"{rec.agent}/{rec.family} template contains registry "
                    f"metric id {name!r}"
                )


def test_metrics_bundle_is_metadata_not_required_in_text():
    rec = get_prompt("insurance_claims_specialist")
    assert rec.metrics_bundle == "extraction"
    assert rec.doc_bundle == "insurance_claim"
    assert "extraction_f1" not in rec.text
    assert "determination_consistency" not in rec.text


def test_families_and_record_shape():
    rec = get_prompt("sorter")
    assert rec.family in FAMILIES
    assert isinstance(rec, PromptRecord)
    assert rec.key == ("sorter", "production")
    assert list_prompts(agent="sorter", family="docclass")[0].family == "docclass"
