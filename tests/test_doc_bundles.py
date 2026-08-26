"""KANBAN-067 — doc-type-aware bundles, honesty-flag resolver, 23rd profile.

Network-free. Companion to test_bundles.py (which keeps the TASK-bundle
surface pinned); this file pins the DOC-TYPE surface and the deliberate
22→23 profile re-pin (insurance_claims_specialist joined in Phase 1).
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.doc_bundles import (
    DOC_TYPES,
    DOC_TYPE_BUNDLES,
    get_doc_bundle,
    list_doc_types,
    validate_doc_bundle,
)
from llm_dojo_scoring.bundles import BUILTIN_BUNDLES, get_bundle
from llm_dojo_scoring.profiles import AgentProfile, get_profile, list_profiles


@pytest.fixture(autouse=True)
def _clean_caches():
    from llm_dojo_scoring.registry import clear_registry_cache

    clear_registry_cache()
    yield
    clear_registry_cache()


# ----------------------------- DOC_TYPE_BUNDLES ------------------------------

def test_all_eight_doc_types_present():
    expected = {
        "contract", "corporate_record", "due_diligence", "correspondence",
        "compliance_filing", "court_opinion", "insurance_claim",
        "merger_agreement",
    }
    assert set(list_doc_types()) == expected
    assert len(DOC_TYPES) == 8
    assert set(DOC_TYPES) == expected


def test_doc_bundle_names_are_prefixed_and_disjoint_from_task_bundles():
    for dt, b in DOC_TYPE_BUNDLES.items():
        assert b.name == f"doc:{dt}", b.name
    # separate namespace: no doc bundle name collides with a task bundle
    task_names = {b.name for b in BUILTIN_BUNDLES.values()}
    doc_names = {b.name for b in DOC_TYPE_BUNDLES.values()}
    assert task_names.isdisjoint(doc_names)


def test_every_doc_bundle_validates_against_default_registry():
    for dt in DOC_TYPE_BUNDLES:
        bundle = get_doc_bundle(dt)  # validate=True default
        assert bundle.metric_names


def test_unknown_doc_type_raises_with_known_list():
    with pytest.raises(KeyError, match="known:"):
        get_doc_bundle("podcast_transcript")


def test_contract_doc_bundle_has_laziness_overrides():
    b = get_doc_bundle("contract")
    extras = b.metrics_for("contracts_specialist")
    assert "laziness_rate" in extras and "hallucination_rate" in extras


def test_merger_agreement_bundle_has_maud_extraction_extras():
    b = get_doc_bundle("merger_agreement")
    assert "HONEST GAP" not in b.description
    assert "22 Hub" in b.description or "per-question" in b.description.lower()
    extras = b.metrics_for("contracts_specialist")
    assert "maud_question_accuracy" in extras
    assert "maud_clause_presence" in extras


def test_correspondence_bundle_has_enron_content_extras():
    b = get_doc_bundle("correspondence")
    assert "HONEST GAP" not in b.description
    assert "Enron" in b.description
    extras = b.metrics_for("correspondence_specialist")
    assert "content_topic_accuracy" in extras
    assert "sentiment_f1_macro" in extras


def test_insurance_claim_bundle_declares_honest_gap():
    b = get_doc_bundle("insurance_claim")
    assert "HONEST GAP" in b.description
    assert "DE-SynPUF" in b.description


def test_court_opinion_bundle_ships_legalbench():
    b = get_doc_bundle("court_opinion")
    extras = b.metrics_for("court_opinions_specialist")
    assert "legalbench_accuracy" in extras
    assert "HONEST GAP" not in b.description


# ----------------------------- resolver ------------------------------

def test_resolve_doc_bundle_by_doc_type_beats_everything():
    p = get_profile("contracts_specialist")
    bundle, used_fallback = p.resolve_doc_bundle("insurance_claim")
    assert bundle.name == "doc:insurance_claim"
    assert used_fallback is False


def test_resolve_doc_bundle_profile_field_when_no_doc_type():
    p = AgentProfile(
        name="test_doc_agent",
        tasks=("extract",),
        metrics_bundle="extraction",
        doc_bundle="court_opinion",
    )
    bundle, used_fallback = p.resolve_doc_bundle()
    assert bundle.name == "doc:court_opinion"
    assert used_fallback is False


def test_resolve_doc_bundle_explicit_fallback_flag():
    # v0.8.0: specialists bind a native doc_bundle, so the no-arg
    # resolver hits that field (used_fallback=False) rather than the
    # task bundle. Agents without a doc_bundle still fall back honestly.
    p = get_profile("contracts_specialist")
    bundle, used_fallback = p.resolve_doc_bundle()
    assert used_fallback is False
    assert bundle.name == "doc:contract"

    sorter = get_profile("sorter")
    fallback_bundle, sorter_fallback = sorter.resolve_doc_bundle()
    assert sorter_fallback is True
    assert fallback_bundle.name == "classification"


def test_resolve_doc_bundle_no_fallback_raises():
    p = get_profile("sorter")  # no native doc_bundle
    with pytest.raises(ValueError, match="no doc_bundle"):
        p.resolve_doc_bundle(fallback=False)


# ----------------------------- 22→23 re-pin + regression ------------------------------

def test_profile_set_re_pinned_to_25():
    expected = {
        "sorter", "contracts_specialist", "corporate_records_specialist",
        "due_diligence_specialist", "correspondence_specialist",
        "compliance_specialist", "court_opinions_specialist",
        "insurance_claims_specialist",  # KANBAN-067 Phase 1 addition
        "reporter", "judge", "boss", "pdf_transcriber", "image_extractor",
        "archivist", "audit_agent",
        "sorter_reviewer",
        "contract_auditor", "corporate_records_auditor",
        "due_diligence_auditor", "correspondence_auditor",
        "compliance_auditor",         "court_opinions_auditor",
        "insurance_claims_auditor",  # v0.8.0 — 7th specialist companion
        "arbiter",
        "intake",  # v0.9.0 — pre-sorter intake clerk (deterministic / LLM)
    }
    assert set(list_profiles()) == expected
    assert len(expected) == 25


def test_preexisting_22_profiles_unchanged_by_v070():
    """KANBAN-062 precedent: the v0.6.0 surface must be untouched.

    Every profile that shipped in 0.6.0 keeps its exact tasks / bundle /
    fallback / ground_truth; the only delta is the new 23rd entry.
    """
    v060 = {
        "sorter": (("classify", "route"), "classification", None, True),
        "contracts_specialist": (("extract",), "extraction", None, True),
        "corporate_records_specialist": (("extract",), "extraction", None, True),
        "due_diligence_specialist": (("extract",), "extraction", None, True),
        "correspondence_specialist": (("extract",), "extraction", None, True),
        "compliance_specialist": (("extract",), "extraction", None, True),
        "court_opinions_specialist": (("extract",), "extraction", None, True),
        "reporter": (("summarize",), "reporter", None, True),
        "judge": (("classify", "review"), "classification", None, True),
        "boss": (("orchestrate",), "reporter", None, True),
        "pdf_transcriber": (("transcribe",), "transcription", None, True),
        "image_extractor": (("transcribe",), "transcription", None, True),
        "archivist": (("store",), "cost", None, False),
        "audit_agent": (("verify", "review"), "audit", "extraction", False),
        "sorter_reviewer": (("classify", "review"), "classification", None, True),
        "contract_auditor": (("verify", "review"), "audit", "extraction", False),
        "corporate_records_auditor": (("verify", "review"), "audit", "extraction", False),
        "due_diligence_auditor": (("verify", "review"), "audit", "extraction", False),
        "correspondence_auditor": (("verify", "review"), "audit", "extraction", False),
        "compliance_auditor": (("verify", "review"), "audit", "extraction", False),
        "court_opinions_auditor": (("verify", "review"), "audit", "extraction", False),
        "arbiter": (("verify", "review"), "audit", None, False),
    }
    for name, (tasks, bundle, fb, gt) in v060.items():
        p = get_profile(name)
        assert p.tasks == tasks, name
        assert p.metrics_bundle == bundle, name
        assert p.fallback_bundle == fb, name
        assert p.ground_truth is gt, name
        # v0.8.0: specialists now bind their native doc-type bundle;
        # every other v0.6.0 profile stays unbound.
        if name.endswith("_specialist") and name != "audit_agent":
            assert p.doc_bundle is not None, name
        else:
            assert p.doc_bundle is None, name


def test_new_specialist_resolves_extraction_task_bundle():
    p = get_profile("insurance_claims_specialist")
    assert p.tasks == ("extract",)
    assert p.resolve_bundle().name == "extraction"
    # and its doc-type resolution works end to end
    b, fb = p.resolve_doc_bundle("insurance_claim")
    assert b.name == "doc:insurance_claim" and fb is False
