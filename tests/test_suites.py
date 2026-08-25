"""Dedicated per-agent scoring suites (v0.8.0).

Network-free: every pipeline agent has an importable suite; score()
routes to existing package functions; honest gaps are documented.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.profiles import DEFAULT_PROFILES, list_profiles
from llm_dojo_scoring.registry import (
    SPECIALIST_AGENTS,
    expand_agent_families,
    load_registry,
)
from llm_dojo_scoring.suites import (
    DEFAULT_FIELD_TYPES,
    DEFAULT_SUITES,
    DOC_TYPE_ALIASES,
    SPECIALIST_DOC_TYPES,
    get_suite,
    list_suites,
    score_suite,
    suite_for_doc_type,
)


def test_every_profile_has_a_dedicated_suite():
    assert set(DEFAULT_SUITES) == set(DEFAULT_PROFILES)
    assert set(list_suites()) == set(list_profiles())


def test_seven_specialist_suites_and_seven_auditors():
    specialists = list_suites(kind="extraction")
    assert set(specialists) == set(SPECIALIST_AGENTS)
    assert len(specialists) == 7
    auditors = [n for n in list_suites(kind="audit") if n.endswith("_auditor")]
    assert len(auditors) == 7
    assert "insurance_claims_auditor" in auditors


def test_get_suite_accepts_agent_and_doc_type_aliases():
    assert get_suite("sorter").name == "sorter"
    assert get_suite("agent:sorter").name == "sorter"
    assert get_suite("insurance_claim").name == "insurance_claims_specialist"
    assert get_suite("doc:contract").name == "contracts_specialist"
    assert get_suite("merger_agreement").name == "contracts_specialist"
    assert suite_for_doc_type("court_opinion").name == "court_opinions_specialist"


def test_unknown_suite_lists_known_names():
    with pytest.raises(KeyError, match="known agents"):
        get_suite("podcast_transcriber")


def test_every_suite_bundle_validates_against_registry():
    for name, suite in DEFAULT_SUITES.items():
        bundle = suite.materialize_bundle()
        assert bundle.name == f"agent:{name}"
        names = suite.metric_names()
        assert names
        reg = load_registry()
        for metric in names:
            reg.get(metric)  # KeyError on typo


def test_specialist_suites_embed_mailroom_field_types():
    for agent, doc_type in SPECIALIST_DOC_TYPES.items():
        suite = get_suite(agent)
        assert suite.kind == "extraction"
        assert suite.doc_type == doc_type
        assert suite.field_types == DEFAULT_FIELD_TYPES[doc_type]
        assert suite.computable is True
        assert suite.profile.doc_bundle == doc_type


def test_sorter_suite_is_classification_and_computable():
    suite = get_suite("sorter")
    assert suite.kind == "classification"
    assert suite.task_key == "docclass"
    assert "confusion_matrix" in suite.metric_names()
    assert "accuracy" in suite.headline_names()


def test_sorter_score_doc_class_labels():
    result = score_suite(
        "sorter",
        expected=["contract", "insurance_claim", "court_opinion"],
        predicted=["contract", "insurance_claim", "correspondence"],
        task="doc_class",
    )
    assert result["task"] == "doc_class"
    assert result["exact_match"] == pytest.approx(2 / 3, abs=1e-3)
    assert result["n"] == 3


def test_sorter_score_hierarchical_corpus_subclasses():
    result = score_suite(
        "sorter",
        expected=["contract", "merger_agreement", "insurance_claim", "correspondence"],
        predicted=["contract", "merger_agreement", "insurance_claim", "correspondence"],
        expected_subclass=["License_Agreements", "all_cash", "carrier", "attorney_demand"],
        predicted_subclass=["license", "all_cash", "carrier", "email"],
    )
    assert result["kind"] == "docclass"
    assert result["doc_type_accuracy"] == 1.0
    assert result["subclass_accuracy"] == 0.75  # correspondence form miss
    assert result["exact_match"] == 0.75


def test_contracts_specialist_score_uses_field_types():
    expected = {
        "parties": ["Acme Corp", "Beta LLC"],
        "effective_date": "2024-03-03",
        "contract_value": "$1,000.00",
    }
    predicted = {
        "parties": ["Beta LLC", "Acme Corp"],
        "effective_date": "March 3, 2024",
        "contract_value": "1000",
    }
    result = get_suite("contracts_specialist").score(expected, predicted)
    assert result.doc_class == "contract"
    assert result.overall_score == 1.0
    assert "parties" in result.entity_list_scores


def test_insurance_claims_specialist_score_money_and_id():
    expected = {
        "claim_number": "CLM-99",
        "claimed_amount": 1500.0,
        "insurer": "Acme Insurance",
    }
    predicted = {
        "claim_number": "clm-99",
        "claimed_amount": "$1,500.00",
        "insurer": "Acme Insurance",
    }
    result = get_suite("insurance_claim").score(expected, predicted)
    assert result.doc_class == "insurance_claim"
    assert result.overall_score == 1.0


def test_every_specialist_score_empty_expected_is_safe():
    for agent in SPECIALIST_AGENTS:
        result = get_suite(agent).score({}, {"confidence": 0.9})
        assert result.overall_score is None
        assert result.field_scores == {}


def test_audit_suite_disagreement_from_extraction_score():
    reference = {"entity_name": "Acme Holdings", "filing_number": "A-1"}
    auditor = {"entity_name": "Acme Holdings", "filing_number": "A-1"}
    out = get_suite("corporate_records_auditor").score(reference, auditor)
    assert out["audit_disagreement_rate"] == 0.0
    assert out["overall_score"] == 1.0

    wrong = {"entity_name": "Other Co", "filing_number": "ZZZ"}
    disagreed = get_suite("corporate_records_auditor").score(reference, wrong)
    assert disagreed["audit_disagreement_rate"] > 0.5


def test_transcription_suite_uses_existing_token_f1():
    out = get_suite("pdf_transcriber").score(
        "the parties agree to terminate",
        "the parties agree to terminate",
    )
    assert out["accuracy"] == 1.0
    assert out["f1_macro"] == 1.0


def test_emit_only_suites_raise_without_metrics():
    with pytest.raises(TypeError, match="emit-only"):
        get_suite("reporter").score(None, None)
    with pytest.raises(TypeError, match="emit-only"):
        get_suite("archivist").score(None, None)
    validated = get_suite("boss").score(
        None, None, metrics={"accuracy": 0.9, "not_a_metric": 1}
    )
    assert "accuracy" in validated["emitted"]
    assert "not_a_metric" in validated["skipped"]


def test_honest_gaps_documented_not_invented():
    for agent in (
        "correspondence_specialist",
        "insurance_claims_specialist",
        "due_diligence_specialist",
        "corporate_records_specialist",
        "compliance_specialist",
        "pdf_transcriber",
        "image_extractor",
    ):
        gap = get_suite(agent).honest_gap
        assert gap and "HONEST GAP" in gap


def test_contracts_and_court_have_real_benchmark_extras():
    contracts = set(get_suite("contracts_specialist").metric_names())
    court = set(get_suite("court_opinions_specialist").metric_names())
    assert {"jaccard_similarity", "laziness_rate"} <= contracts
    assert {"legalbench_accuracy", "legalbench_macro_f1"} <= court
    assert get_suite("contracts_specialist").honest_gap is None
    assert "LegalBench" in (get_suite("court_opinions_specialist").honest_gap or "")


def test_insurance_specialist_is_on_extraction_metrics():
    reg = load_registry()
    assert reg.get("extraction_overall_score").applies_to("insurance_claims_specialist")
    assert reg.get("field_presence").applies_to("insurance_claims_specialist")
    assert reg.get("date_mae_days").applies_to("insurance_claims_specialist")
    assert reg.get("money_mae_usd").applies_to("insurance_claims_specialist")


def test_expand_agent_families_covers_insurance():
    assert "insurance_claims_specialist" in expand_agent_families(["SPECIALISTS"])
    assert "insurance_claims_auditor" in expand_agent_families(["AUDITORS"])
    assert "sorter_reviewer" in expand_agent_families(["CLASSIFIERS"])
    assert expand_agent_families(["ALL"]) == ("ALL",)


def test_doc_type_aliases_cover_all_eight_classes():
    expected = {
        "contract",
        "corporate_record",
        "due_diligence",
        "correspondence",
        "compliance_filing",
        "court_opinion",
        "insurance_claim",
        "merger_agreement",
    }
    assert set(DOC_TYPE_ALIASES) == expected


def test_suite_to_dict_is_json_safe():
    d = get_suite("sorter").to_dict()
    assert d["name"] == "sorter"
    assert d["computable"] is True
    assert isinstance(d["metric_names"], list)
    assert d["honest_gap"] is None
