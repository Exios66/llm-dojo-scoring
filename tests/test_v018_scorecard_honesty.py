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
    score_empty_field_contract,
    score_format_layer,
    stamp_provenance,
    summarize_run_completion,
)
from llm_dojo_scoring.serving import classify_serving_kind, split_local_api
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
    """Multiple distinct GT answers for one Hub key collapse to ``gt_ambiguous`` / unscorable."""
    expected = {
        "No-Shop": {"answer": ["Yes", "Strict liability standard"]},
    }
    out = score_maud_extraction(expected, {"No-Shop": {"answer": "Yes"}})
    assert out["n_ambiguous"] == 1
    assert out["n_questions"] == 0
    assert out["maud_question_accuracy"] is None
    assert out["status"] == "unscorable"
    assert out["reason"] == "gt_ambiguous"
    assert out["gt_ambiguous"] is True
    assert out["per_question"]["No-Shop"]["gt_ambiguous"] is True
    assert out["per_question"]["No-Shop"]["status"] == "unscorable"

    collapsed_string = score_maud_extraction(
        {"No-Shop": {"answer": "Yes / Strict liability / Reasonable standard"}},
        {"No-Shop": {"answer": "Yes"}},
    )
    assert collapsed_string["n_ambiguous"] == 1
    assert collapsed_string["status"] == "unscorable"
    assert "No-Shop" in collapsed_string["ambiguous_keys"]

    collapsed_spans = score_maud_extraction(
        ["No-Shop: Yes", "No-Shop: Strict liability standard"],
        ["No-Shop: Yes"],
    )
    assert collapsed_spans["n_ambiguous"] == 1
    assert collapsed_spans["status"] == "unscorable"


def test_maud_distinct_subquestion_keys_score_normally():
    """Distinct Hub sub-question keys stay distinct and score normally, even alongside an ambiguous key."""
    expected = {
        "No-Shop": {"answer": "Yes"},
        "Fiduciary exception:  Board determination (no-shop)": {"answer": "Yes"},
        "Breach of No Shop": {"answer": "No"},
    }
    predicted = {
        "No-Shop": {"answer": "Yes"},
        "Fiduciary exception:  Board determination (no-shop)": {"answer": "Yes"},
        "Breach of No Shop": {"answer": "No"},
    }
    out = score_maud_extraction(expected, predicted)
    assert out["n_ambiguous"] == 0
    assert out["n_questions"] == 3
    assert out["maud_question_accuracy"] == 1.0
    assert out["status"] == "scored"
    assert out["gt_ambiguous"] is False
    assert out["per_question"]["No-Shop"]["accuracy"] == 1.0
    assert out["per_question"]["Fiduciary exception:  Board determination (no-shop)"]["accuracy"] == 1.0
    assert out["per_question"]["Breach of No Shop"]["accuracy"] == 1.0

    mixed = score_maud_extraction(
        {
            "No-Shop": {"answer": ["Yes", "Strict liability standard"]},
            "Type of Consideration": {"answer": "All Cash"},
        },
        {
            "No-Shop": {"answer": "Yes"},
            "Type of Consideration": {"answer": "All Cash"},
        },
    )
    assert mixed["n_ambiguous"] == 1
    assert mixed["n_questions"] == 1
    assert mixed["maud_question_accuracy"] == 1.0
    assert mixed["status"] == "scored"
    assert mixed["per_question"]["No-Shop"]["gt_ambiguous"] is True
    assert mixed["per_question"]["Type of Consideration"]["accuracy"] == 1.0


def test_format_vs_extraction_and_empty_fields():
    """Spurious fills count as FP with zero empty-field credit; bad JSON fails parse, not extraction."""
    assert classify_extraction_failure(parse_ok=0.0, overall_score=0.9) == "format_parse"
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    expected = {"claim_number": "CLM-1", "adjuster": None}
    predicted = {"claim_number": "CLM-1", "adjuster": "Bob"}
    out = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="insurance_claim"
    )
    assert out["fp"] == 1
    assert out["n_spurious_fill"] == 1
    assert out["empty_field_credit"] == 0.0
    fmt = score_format_layer(
        predicted_raw='prefix {"claim_number": "CLM-1"} suffix'
    )
    assert fmt["parse_ok"] == 0.0


def test_prose_wrapped_json_is_parse_fail_not_zero_extraction():
    """JSON wrapped in chatty prose fails format parsing without zeroing out extraction."""
    raw = 'Sure, here you go:\n{"claim_number": "CLM-1", "adjuster": null}\nThanks!'
    fmt = score_format_layer(predicted_raw=raw)
    assert fmt["parse_ok"] == 0.0
    assert fmt["schema_adherence"] == 0.0
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    parsed = {"claim_number": "CLM-1", "adjuster": None}
    expected = {"claim_number": "CLM-1"}
    prf = extraction_binary_metrics(
        expected, parsed, field_map=field_map, doc_class="insurance_claim"
    )
    assert prf["extraction_f1"] == 1.0
    assert prf["fn"] == 0
    assert classify_extraction_failure(
        parse_ok=fmt["parse_ok"], overall_score=1.0
    ) == "format_parse"


def test_correctly_empty_fields_score_one():
    """A field correctly left empty on both sides scores 1.0 and is never an FP/FN."""
    field_map = DEFAULT_FIELD_TYPES["insurance_claim"]
    expected = {"claim_number": "CLM-1", "adjuster": None}
    predicted = {"claim_number": "CLM-1", "adjuster": None}
    empty = score_empty_field_contract(
        expected, predicted, field_types=field_map
    )
    assert empty["field_scores"]["adjuster"] == 1.0
    assert empty["empty_field_credit"] == 1.0
    assert empty["n_correctly_empty"] == 1
    assert empty["n_spurious_fill"] == 0
    prf = extraction_binary_metrics(
        expected, predicted, field_map=field_map, doc_class="insurance_claim"
    )
    assert prf["fn"] == 0
    assert prf["fp"] == 0
    assert prf["n_correctly_empty"] == 1
    assert prf["empty_field_credit"] == 1.0
    from llm_dojo_scoring.field_scoring import score_extraction

    result = score_extraction("insurance_claim", field_map, predicted, expected)
    assert "adjuster" not in result.field_scores
    assert result.field_scores["claim_number"] == 1.0


@pytest.mark.parametrize(
    "finish_reason",
    [
        None, "", "stop", "completed", "success", "none",
        "end_turn", "eos", "STOP_SEQUENCE", "tool_calls",
    ],
)
def test_normal_finish_reasons_count_as_completed(finish_reason):
    """Normal finish reasons (stop, tool_calls, etc.) count as completed, not errored."""
    completion = summarize_run_completion([{"finish_reason": finish_reason}])
    assert completion["n_attempted"] == 1
    assert completion["n_completed"] == 1
    assert completion["n_errored"] == 0
    assert completion["completion_rate"] == 1.0
    assert completion["error_class_histogram"] == {}


@pytest.mark.parametrize("finish_reason", ["end_turn", "eos", "STOP_SEQUENCE", "tool_calls"])
@pytest.mark.parametrize(
    "error_signal",
    [
        {"errored": True},
        {"status": "error"},
        {"status": "ERROR_TIMEOUT"},
        {"error": "ContextWindowOverflowError"},
        {"error_class": "LengthFinishReasonError"},
    ],
)
def test_normal_finish_reasons_preserve_error_signals(finish_reason, error_signal):
    """An explicit error signal still counts as errored even alongside a normal finish reason."""
    completion = summarize_run_completion(
        [{"finish_reason": finish_reason, **error_signal}]
    )
    assert completion["n_completed"] == 0
    assert completion["n_errored"] == 1
    assert completion["completion_rate"] == 0.0
    assert sum(completion["error_class_histogram"].values()) == 1


@pytest.mark.parametrize(
    ("finish_reason", "error_class"),
    [
        ("length", "LengthFinish"),
        ("max_tokens", "LengthFinish"),
        ("content_filter", "content_filter"),
    ],
)
def test_error_finish_reasons_count_as_errors(finish_reason, error_class):
    """Length / content-filter finish reasons count as errored with the right error class."""
    completion = summarize_run_completion([{"finish_reason": finish_reason}])
    assert completion["n_completed"] == 0
    assert completion["n_errored"] == 1
    assert completion["error_class_histogram"] == {error_class: 1}


def test_completion_and_cost_basis():
    """End-to-end completion/error aggregation, quality-ITT, and cost-basis handling."""
    records = [
        {"status": "ok", "overall_score": 1.0},
        {"status": "ok", "overall_score": 1.0},
        {"error_class": "LengthFinishReasonError", "errored": True},
        {"error": "LengthFinishReasonError", "status": "ERROR"},
        {"finish_reason": "length", "errored": True},
        {"error_class": "ContextWindowOverflowError", "errored": True},
    ]
    completion = summarize_run_completion(records)
    assert completion["n_attempted"] == 6
    assert completion["n_errored"] == 4
    assert completion["n_completed"] == 2
    assert completion["completion_rate"] < 1
    assert completion["completion_rate"] == pytest.approx(2 / 6, abs=1e-3)
    assert completion["error_class_histogram"]["LengthFinish"] == 3
    assert completion["error_class_histogram"]["context_overflow"] == 1
    itt = aggregate_quality_itt(
        [{"overall_score": 1.0}, {"overall_score": 1.0}],
        completion,
    )
    assert itt["quality_mean_completed"] == 1.0
    assert itt["quality_mean_itt"] == pytest.approx(2 / 6, abs=1e-3)
    assert itt["quality_mean_itt"] != itt["quality_mean_completed"]
    cost = estimate_for_record({"model": "gpt-4o-mini", "tokens": {"prompt_tokens": 1}})
    assert "cost_basis" in cost
    assert cost["cost_basis"] == "busy_window"
    summary = tokens_summary([{"cost_basis": "billed_incl_cold", "prompt_tokens": 1}], model="gpt-4o-mini")
    assert summary["cost_basis"] == "billed_incl_cold"
    with pytest.raises(ValueError, match="cost_basis mixed"):
        tokens_summary(
            [
                {"cost_basis": "busy_window", "prompt_tokens": 1},
                {"cost_basis": "billed_incl_cold", "prompt_tokens": 1},
            ]
        )


def test_modal_serving_kind_not_local():
    """Modal-hosted vLLM serving is classified ``modal``, never ``local``."""
    assert classify_serving_kind({"profile": "modal-vllm"}) == "modal"
    assert classify_serving_kind({"serving_kind": "modal"}) == "modal"
    assert classify_serving_kind({"provider": "modal-vllm"}) == "modal"
    assert classify_serving_kind({"provider": "modal-vllm"}) != "local"
    local, api, unknown = split_local_api([{"provider": "modal-vllm"}])
    assert local == []
    assert api == []
    assert len(unknown) == 1


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
