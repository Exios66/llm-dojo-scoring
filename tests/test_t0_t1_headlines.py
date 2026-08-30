"""v0.10.0 — specialist field-micro P/R/F1/F2, insurance consistency, sorter PRF.

Network-free. Every new registry name maps to a function that computes.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.bundles import bundle_metric_names
from llm_dojo_scoring.claims_consistency import (
    amount_exactness,
    determination_consistency,
)
from llm_dojo_scoring.classification import fbeta, macro_prf
from llm_dojo_scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.pruning import dashboard_metrics, headline_metrics
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite
from llm_dojo_scoring.tasks import score_task


# ---------------------------------------------------------------------------
# Field-micro TP / FP / FN
# ---------------------------------------------------------------------------


def test_extraction_binary_metrics_perfect_insurance_schema():
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    expected = {
        "claim_number": "CLM-99",
        "claimed_amount": 1500.0,
        "insurer": "Acme Insurance",
        "adjuster": None,  # empty GT is skipped, not FN
    }
    predicted = {
        "claim_number": "clm-99",
        "claimed_amount": "$1,500.00",
        "insurer": "Acme Insurance",
    }
    out = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="insurance_claim"
    )
    assert out["tp"] == 3
    assert out["fn"] == 0
    assert out["fp"] == 0
    assert out["extraction_f1"] == 1.0
    assert out["extraction_f2"] == 1.0
    assert out["extraction_precision"] == 1.0
    assert out["extraction_recall"] == 1.0


def test_extraction_binary_metrics_miss_is_fn_not_soft_mean():
    field_map = DEFAULT_FIELD_TYPES["corporate_record"]
    expected = {
        "entity_name": "Acme Holdings",
        "record_type": "articles_of_incorporation",
        "filing_number": "A-1",
    }
    predicted = {
        "entity_name": "Acme Holdings",
        "record_type": "articles_of_incorporation",
        # filing_number missing → FN
        "extra_key": "hallucinated",  # FP
    }
    out = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="corporate_record"
    )
    assert out["tp"] == 2
    assert out["fn"] == 1
    assert out["fp"] == 1
    # P = 2/3, R = 2/3 — rounded to 4 decimals before F-beta
    assert out["extraction_precision"] == 0.6667
    assert out["extraction_recall"] == 0.6667
    assert out["extraction_f1"] == fbeta(0.6667, 0.6667, beta=1.0)


def test_extraction_binary_metrics_partial_list_is_fn_plus_unmatched_fp():
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    expected = {
        "insurer": "Acme",
        "denial_reasons": ["pre-existing condition", "missing paperwork"],
    }
    predicted = {
        "insurer": "Acme",
        "denial_reasons": ["pre-existing condition", "unrelated extra bullet"],
    }
    out = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="insurance_claim"
    )
    # insurer TP; denial_reasons not exact → FN; unmatched predicted item → FP
    assert out["tp"] == 1
    assert out["fn"] == 1
    assert out["fp"] >= 1
    assert out["extraction_f1"] < 1.0
    assert out["entity_list_f1"] is not None
    assert out["entity_list_f1"] < 1.0


def test_extraction_f2_is_van_rijsbergen_beta_2():
    # P=1, R=0.5 → F2 = 5PR/(4P+R) = 2.5/4.5
    assert fbeta(1.0, 0.5, beta=2.0) == round(5 * 1.0 * 0.5 / (4 * 1.0 + 0.5), 4)


# ---------------------------------------------------------------------------
# Insurance consistency
# ---------------------------------------------------------------------------


def test_determination_consistency_approved_empty_reasons():
    assert determination_consistency(
        {},
        {"coverage_determination": "approved", "denial_reasons": []},
    ) == 1.0


def test_determination_consistency_denied_empty_reasons_fails():
    assert determination_consistency(
        {},
        {"coverage_determination": "denied", "denial_reasons": []},
    ) == 0.0


def test_determination_consistency_denied_with_reasons():
    assert determination_consistency(
        {},
        {
            "coverage_determination": "denied",
            "denial_reasons": ["pre-existing condition"],
        },
    ) == 1.0


def test_amount_exactness_after_money_normalize():
    assert amount_exactness(
        {"claimed_amount": 1500.0},
        {"claimed_amount": "$1,500.00"},
    ) == 1.0
    assert amount_exactness(
        {"claimed_amount": 1500.0},
        {"claimed_amount": "$1,501.00"},
    ) == 0.0
    assert amount_exactness({"claimed_amount": None}, {"claimed_amount": 1}) is None


def test_insurance_batch_score_attaches_consistency_and_prf():
    expected = [
        {
            "claim_number": "CLM-1",
            "claimed_amount": 100.0,
            "coverage_determination": "approved",
            "denial_reasons": [],
        },
        {
            "claim_number": "CLM-2",
            "claimed_amount": 200.0,
            "coverage_determination": "denied",
            "denial_reasons": ["not covered"],
        },
    ]
    predicted = [
        {
            "claim_number": "clm-1",
            "claimed_amount": "$100.00",
            "coverage_determination": "approved",
            "denial_reasons": [],
        },
        {
            "claim_number": "clm-2",
            "claimed_amount": "$200.00",
            "coverage_determination": "denied",
            "denial_reasons": ["not covered"],
        },
    ]
    out = get_suite("insurance_claims_specialist").score(expected, predicted)
    assert isinstance(out, dict)
    assert out["extraction_f1"] == 1.0
    assert out["extraction_f2"] == 1.0
    assert out["determination_consistency"] == 1.0
    assert out["amount_exactness"] == 1.0
    assert len(out["extraction"]) == 2


def test_single_doc_extraction_still_returns_dataclass():
    result = get_suite("contracts_specialist").score(
        {"governing_law": "Delaware"},
        {"governing_law": "Delaware"},
    )
    assert result.overall_score == 1.0
    assert result.field_scores["governing_law"] == 1.0


# ---------------------------------------------------------------------------
# Sorter / docclass PRF
# ---------------------------------------------------------------------------


def test_score_task_docclass_f1_macro_matches_macro_prf():
    expected = ["contract", "insurance_claim", "court_opinion", "correspondence"]
    predicted = ["contract", "insurance_claim", "correspondence", "correspondence"]
    out = score_task("docclass", expected, predicted)
    prf = macro_prf(expected, predicted)
    assert out["f1_macro"] == prf["f1_macro"]
    assert out["precision"] == prf["precision"]
    assert out["recall"] == prf["recall"]
    assert out["f2"] == prf["f2"]
    assert out["accuracy"] == out["doc_type_accuracy"]
    assert "precision" in out["per_class"]["contract"]
    assert "f1" in out["per_class"]["contract"]


def test_score_task_docclass_subclass_macros():
    out = score_task(
        "docclass",
        ["contract", "merger_agreement", "insurance_claim", "correspondence"],
        ["contract", "merger_agreement", "insurance_claim", "correspondence"],
        expected_subclass=["License_Agreements", "all_cash", "carrier", "attorney_demand"],
        predicted_subclass=["license", "all_cash", "carrier", "email"],
    )
    assert out["subclass_accuracy"] == 0.75
    assert "subclass_f1_macro" in out
    assert "subclass_precision_macro" in out
    assert "subclass_recall_macro" in out
    assert 0.0 <= out["subclass_f1_macro"] <= 1.0


def test_score_task_pipeline_fills_f1_macro():
    out = score_task("pipeline", ["contract", "insurance_claim"], ["contract", "correspondence"])
    prf = macro_prf(["contract", "insurance_claim"], ["contract", "correspondence"])
    assert out["f1_macro"] == prf["f1_macro"]
    assert out["exact_accuracy"] == 0.5


# ---------------------------------------------------------------------------
# Headlines (bundle ∩ T0)
# ---------------------------------------------------------------------------


def test_headline_metrics_specialists_include_extraction_f1():
    for agent in (
        "contracts_specialist",
        "corporate_records_specialist",
        "correspondence_specialist",
        "compliance_specialist",
        "insurance_claims_specialist",
        "court_opinions_specialist",
        "due_diligence_specialist",
    ):
        head = headline_metrics(agent)
        assert "extraction_overall_score" in head, agent
        assert "extraction_f1" in head, agent


def test_headline_metrics_insurance_includes_extraction_f2():
    head = headline_metrics("insurance_claims_specialist")
    assert "extraction_f2" in head
    assert "extraction_overall_score" in head
    assert "extraction_f1" in head


def test_headline_metrics_correspondence_includes_topic_macro_f1():
    head = headline_metrics("correspondence_specialist")
    assert "content_topic_f1_macro" in head
    assert "extraction_overall_score" in head
    assert "extraction_f1" in head


def test_headline_metrics_sorter_unchanged():
    assert headline_metrics("sorter") == ["accuracy", "f1_macro"]


def test_headline_metrics_local_vs_api_ttft_and_throughput():
    head = headline_metrics("local_vs_api")
    assert "ttft_seconds" in head
    assert "tokens_per_second" in head
    assert "accuracy" not in head
    core = dashboard_metrics("local_vs_api")
    assert "gpu_utilization" in core
    assert "e2e_latency_seconds" in core


def test_dashboard_includes_extraction_precision_recall():
    core = dashboard_metrics("contracts_specialist")
    assert "extraction_precision" in core
    assert "extraction_recall" in core
    assert "extraction_f2" in core
    assert "entity_list_f1" in core


def test_extraction_bundle_lists_new_names():
    names = bundle_metric_names("extraction", agent="insurance_claims_specialist")
    assert "determination_consistency" in names
    assert "amount_exactness" in names
    names_c = bundle_metric_names("extraction", agent="correspondence_specialist")
    assert "content_topic_f1_macro" in names_c
