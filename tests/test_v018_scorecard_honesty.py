"""v0.18 live-run calibration — issues #16–#22."""

from __future__ import annotations

import pytest

from llm_dojo_scoring import compare_serving, get_suite
from llm_dojo_scoring.content_scoring import score_maud_extraction
from llm_dojo_scoring.cost import estimate_for_record, tokens_summary
from llm_dojo_scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.export import validate_comparison_export
from llm_dojo_scoring.failure_modes import classify_extraction_failure
from llm_dojo_scoring.scorecard_honesty import (
    IncomparableMetricsError,
    ProvenanceExportError,
    aggregate_quality_honest,
    aggregate_quality_itt,
    assert_comparable_metric_ids,
    assess_extraction_gt,
    check_schema_promotion_gate,
    score_format_layer,
    stamp_provenance,
    summarize_run_completion,
)
from llm_dojo_scoring.serving import classify_serving_kind
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES


def test_unscorable_triage_only_contracts_gt_not_zero():
    gt = {"contract_subtype": "license", "doc_type": "contract"}
    pred = {
        "parties": ["Acme Corp"],
        "effective_date": "2024-01-01",
        "governing_law": "Delaware",
    }
    assessment = assess_extraction_gt(
        gt, DEFAULT_FIELD_TYPES["contract"], doc_class="contract"
    )
    assert assessment.status == "unscorable"
    assert assessment.reason == "gt_no_extractable_fields"
    out = get_suite("contracts_specialist").score(gt, pred)
    assert out["status"] == "unscorable"
    assert out["overall_score"] is None
    assert out["export_verdict"] == "unproven"
    agg = aggregate_quality_honest(
        [{"status": "unscorable"}, {"overall_score": 0.8}]
    )
    assert agg["n_unscorable"] == 1
    assert agg["n_scored"] == 1
    assert agg["quality_mean"] == pytest.approx(0.8)
    assert agg["export_verdict"] == "scored"


def test_metric_id_mismatch_incomparable():
    with pytest.raises(IncomparableMetricsError):
        assert_comparable_metric_ids(
            "cuad.clause_presence.micro_f1",
            "pipeline.extraction.overall",
        )
    local = {"quality": {"metric_id": "cuad.clause_presence.micro_f1", "f1": 0.5}}
    api = {"quality": {"metric_id": "pipeline.extraction.overall", "f1": 0.5}}
    out = compare_serving(local, api)
    assert out.get("incomparable") is True


def test_schema_valid_gate_insurance():
    fmt = score_format_layer(
        predicted_raw='{"claim_number": "CLM-1"}',
        required_keys=["claim_number", "claimed_amount", "insurer"],
    )
    assert fmt["parse_ok"] == 1.0
    assert fmt["schema_valid"] < 1.0
    gate = check_schema_promotion_gate(fmt["schema_valid"])
    assert gate["passes"] is False


def test_maud_collapsed_gt_ambiguous():
    expected = {
        "No-Shop": {"answer": ["Yes", "Strict liability standard"]},
    }
    out = score_maud_extraction(expected, {"No-Shop": {"answer": "Yes"}})
    assert out["n_ambiguous"] == 1
    assert out["n_questions"] == 0
    assert out["maud_question_accuracy"] is None
    assert out["status"] == "unscorable"


def test_format_vs_extraction_and_empty_fields():
    assert classify_extraction_failure(parse_ok=0.0, overall_score=0.9) == "format_parse"
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    expected = {"claim_number": "CLM-1", "adjuster": None}
    predicted = {"claim_number": "CLM-1", "adjuster": "Bob"}
    out = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="insurance_claim"
    )
    assert out["fp"] == 1
    fmt = score_format_layer(
        predicted_raw='prefix {"claim_number": "CLM-1"} suffix'
    )
    assert fmt["parse_ok"] == 0.0


def test_completion_and_cost_basis():
    records = [
        {"status": "ok"},
        {"status": "ok"},
        {"error_class": "LengthFinishReasonError", "errored": True},
    ]
    completion = summarize_run_completion(records)
    assert completion["n_attempted"] == 3
    assert completion["n_errored"] == 1
    assert completion["completion_rate"] == pytest.approx(2 / 3, abs=1e-3)
    itt = aggregate_quality_itt(
        [{"overall_score": 1.0}, {"overall_score": 1.0}],
        completion,
    )
    assert itt["quality_mean_completed"] == 1.0
    assert itt["quality_mean_itt"] == pytest.approx(2 / 3, abs=1e-3)
    cost = estimate_for_record({"model": "gpt-4o-mini", "tokens": {"prompt_tokens": 1}})
    assert cost["cost_basis"] == "busy_window"
    summary = tokens_summary([{"cost_basis": "billed_incl_cold", "prompt_tokens": 1}], model="gpt-4o-mini")
    assert summary["cost_basis"] == "billed_incl_cold"


def test_modal_serving_kind_not_local():
    assert classify_serving_kind({"profile": "modal-vllm"}) == "modal"
    assert classify_serving_kind({"serving_kind": "modal"}) == "modal"


def test_provenance_export_refusal():
    left = stamp_provenance(
        {},
        dataset_revision="ed7576b",
        split="eval",
        draw_seed="seed-a",
        prompt_id="contracts_specialist_v30",
        metric_id="pipeline.extraction.overall",
        serving_kind="modal",
        model_id="qwen/qwen3.7-flash",
    )
    right = stamp_provenance(
        left,
        draw_seed="seed-b",
    )
    with pytest.raises(ProvenanceExportError):
        validate_comparison_export(left, right)
