"""Tests for the KANBAN-062/063 review/audit profile registry additions.

Network-free: pure registry inspection, no LLM or HTTP.
"""

from llm_dojo_scoring.profiles import DEFAULT_PROFILES, get_profile
from llm_dojo_scoring.bundles import get_bundle

NEW_PROFILES = [
    "sorter_reviewer",
    "contract_auditor",
    "corporate_records_auditor",
    "due_diligence_auditor",
    "correspondence_auditor",
    "compliance_auditor",
    "court_opinions_auditor",
    "arbiter",
]


def test_new_review_audit_profiles_registered():
    for name in NEW_PROFILES:
        assert name in DEFAULT_PROFILES, f"missing profile: {name}"


def test_sorter_reviewer_profile_shape():
    p = get_profile("sorter_reviewer")
    assert p.tasks == ("classify", "review")
    assert p.metrics_bundle == "classification"


def test_specialist_auditor_profiles_share_shape():
    auditors = [n for n in NEW_PROFILES if n.endswith("_auditor")]
    assert len(auditors) == 6  # one per specialist
    for name in auditors:
        p = get_profile(name)
        assert p.tasks == ("verify", "review")
        assert p.metrics_bundle == "audit"
        assert p.fallback_bundle == "extraction"
        assert p.ground_truth is False


def test_arbiter_profile_shape():
    p = get_profile("arbiter")
    assert p.tasks == ("verify", "review")
    assert p.metrics_bundle == "audit"
    assert p.ground_truth is False


def test_all_profile_bundles_resolve():
    for name, p in DEFAULT_PROFILES.items():
        get_bundle(p.metrics_bundle)  # raises on unknown bundle
        if p.fallback_bundle:
            get_bundle(p.fallback_bundle)


def test_preexisting_profiles_untouched():
    # The v0.5.x registry must survive the additions unchanged.
    aa = get_profile("audit_agent")
    assert aa.tasks == ("verify", "review")
    assert aa.metrics_bundle == "audit"
    assert aa.fallback_bundle == "extraction"
    assert aa.ground_truth is False
    assert get_profile("judge").metrics_bundle == "classification"
    assert get_profile("archivist").ground_truth is False
