"""Live llm-mailroom / The-Mailroom contract (v0.9.0)."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.mailroom import (
    EXTRACT_CLASS_ALIASES,
    INTAKE_AGENT,
    LIVE_DOC_TYPES,
    LIVE_SPECIALISTS,
    NODE_OBSERVATION_TYPES,
    PIPELINE_TRACE,
    RETIRED_DOC_TYPES,
    RETIRED_SPECIALISTS,
    SORTER_LABEL_SET,
    UNKNOWN_DOC_TYPE,
    align_doc_type,
    canonical_score_name,
    is_live_extract_class,
    langfuse_score_name,
    observation_type_for,
    resolve_extract_class,
    score_aligned_classification,
    trace_identity,
)
from llm_dojo_scoring.profiles import get_profile, list_profiles
from llm_dojo_scoring.registry import LIVE_SPECIALIST_AGENTS, load_registry
from llm_dojo_scoring.suites import get_suite, list_suites
from llm_dojo_scoring.tasks import score_task


def test_live_roster_is_five_specialists():
    assert LIVE_DOC_TYPES == (
        "contract",
        "corporate_record",
        "correspondence",
        "compliance_filing",
        "insurance_claim",
    )
    assert set(LIVE_SPECIALISTS) == set(LIVE_SPECIALIST_AGENTS)
    assert len(LIVE_SPECIALISTS) == 5
    assert set(RETIRED_DOC_TYPES) == {"court_opinion", "due_diligence"}
    assert UNKNOWN_DOC_TYPE in SORTER_LABEL_SET
    assert "merger_agreement" in SORTER_LABEL_SET
    assert "merger_agreement" not in LIVE_DOC_TYPES


def test_extract_alias_and_retired_never_extract():
    assert EXTRACT_CLASS_ALIASES["merger_agreement"] == "contract"
    assert resolve_extract_class("merger_agreement") == "contract"
    assert resolve_extract_class("contract") == "contract"
    assert resolve_extract_class("unknown") is None
    assert resolve_extract_class("court_opinion") is None
    assert resolve_extract_class("due_diligence") is None
    assert is_live_extract_class("insurance_claim")
    assert not is_live_extract_class("court_opinion")


def test_aligned_accuracy_merger_equals_contract():
    expected = ["contract", "merger_agreement", "insurance_claim"]
    predicted = ["contract", "contract", "correspondence"]
    out = score_aligned_classification(expected, predicted)
    assert out["n"] == 3
    assert out["exact_accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    assert out["aligned_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert align_doc_type("merger_agreement") == "contract"

    task = score_task("pipeline", expected, predicted)
    assert task["kind"] == "pipeline"
    assert task["aligned_accuracy"] == pytest.approx(2 / 3, abs=1e-3)


def test_observation_types_match_mailroom_map():
    assert observation_type_for("document-pipeline") == "chain"
    assert observation_type_for("classify-document") == "agent"
    assert observation_type_for("judge-verify") == "evaluator"
    assert observation_type_for("transcribe-pdf") == "retriever"
    assert observation_type_for("normalize-intake") == "span"
    assert observation_type_for("pipeline-result") == "generation"
    assert observation_type_for("answer-question") == "generation"
    assert set(NODE_OBSERVATION_TYPES) >= {
        "document-pipeline",
        "normalize-intake",
        "classify-document",
        "extract-fields",
        "judge-verify",
    }


def test_langfuse_score_transport_alias():
    assert langfuse_score_name("extraction_overall_verified_precision") == (
        "extraction_verified_precision"
    )
    assert canonical_score_name("extraction_verified_precision") == (
        "extraction_overall_verified_precision"
    )
    assert langfuse_score_name("accuracy") == "accuracy"
    reg = load_registry()
    assert "extraction_verified_precision" in reg.metrics
    assert "mailroom-pipeline-judge" in reg.metrics
    assert "mailroom-pipeline-quality" in reg.metrics
    assert "exact_accuracy" in reg.metrics
    assert "aligned_accuracy" in reg.metrics


def test_retired_suites_flagged_live_filter():
    assert get_suite("court_opinions_specialist").retired is True
    assert get_suite("due_diligence_specialist").retired is True
    assert get_suite("contracts_specialist").retired is False
    live_extract = list_suites(kind="extraction", live_only=True)
    assert set(live_extract) == set(LIVE_SPECIALISTS)
    assert "court_opinions_specialist" not in live_extract
    assert "court_opinions_specialist" in list_suites(kind="extraction")


def test_intake_clerk_profile_and_suite():
    assert INTAKE_AGENT in list_profiles()
    profile = get_profile("intake")
    assert profile.ground_truth is True
    assert profile.tasks == ("prepare", "normalize")
    suite = get_suite("intake")
    assert suite.kind == "intake"
    assert suite.computable is True
    assert suite.task_key == "intake"


def test_contract_suite_scores_hub_inventory_fields():
    suite = get_suite("contracts_specialist")
    for field in ("cuad_family", "merger_consideration", "cuad_clauses", "maud_clauses"):
        assert field in suite.field_types
    expected = {
        "document_name": "MSA",
        "parties": ["Acme"],
        "cuad_family": "license",
        "cuad_clauses": ["License Grant: Acme grants a license"],
        "maud_clauses": [],
    }
    predicted = {
        "document_name": "MSA",
        "parties": ["Acme"],
        "cuad_family": "license",
        "cuad_clauses": ["License Grant: Acme grants a license"],
        "maud_clauses": [],
    }
    result = suite.score(expected, predicted)
    assert result.overall_score == 1.0


def test_adjuster_null_is_not_a_requirement():
    """CMS rows have no named adjuster — null GT is skipped, not failed."""
    suite = get_suite("insurance_claim")
    expected = {"adjuster": None, "claim_number": "1", "insurer": "CMS"}
    predicted = {"adjuster": None, "claim_number": "1", "insurer": "CMS"}
    result = suite.score(expected, predicted)
    assert "adjuster" not in result.field_scores
    assert result.overall_score == 1.0


def test_trace_identity_reads_v4_camelcase():
    ident = trace_identity(
        {
            "id": "t1",
            "userId": "pilot",
            "sessionId": "pilot-hf-1",
            "release": "mailroom@0.5.0",
            "environment": "pilot",
            "name": PIPELINE_TRACE,
            "metadata": {},
        }
    )
    assert ident["user_id"] == "pilot"
    assert ident["session_id"] == "pilot-hf-1"
    assert ident["release"] == "mailroom@0.5.0"
    assert ident["name"] == PIPELINE_TRACE
