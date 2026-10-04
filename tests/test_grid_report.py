"""Specialist grid report — L4-style quality/cost tables for local → Modal runs.

Fixture numbers are synthetic (not a measured run) and chosen so every
aggregation is checkable by hand. The report must never fabricate a missing
metered/cold figure.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.grid import (
    GridDocument,
    GridExperiment,
    _is_error,
    build_grid_report,
    grid_scorecard,
    serving_efficiency_rows,
    session_cost_rows,
    specialist_grid_rows,
)

_EXPERIMENTS = [
    GridExperiment(
        name="Experiment 3",
        posture="2×L4 C32 n=50",
        gpus=2,
        gpu_type="L4",
        gpu_hourly_usd=0.80,
        client_concurrency=32,
        wall_seconds=300.0,
        metered_usd=1.09,
        documents_per_class=50,
        status="5 of 5 cells",
        serving_kind="modal",
    ),
    GridExperiment(
        name="Experiment 4",
        posture="2×L4 C32 n=100",
        gpus=2,
        gpu_type="L4",
        gpu_hourly_usd=0.80,
        client_concurrency=32,
        wall_seconds=600.0,
        metered_usd=None,  # billing report pending — must render n/a
        documents_per_class=100,
        status="5 of 5 cells",
        serving_kind="modal-vllm",  # normalizes to modal, never local
    ),
]

_DOCUMENTS = [
    # E3 contracts: scores 0.60/0.64 → 0.62; p50 95.0; 360 GPU s → $0.08; /2 ok.
    GridDocument(
        experiment="Experiment 3", specialist="Contracts",
        metric_id="cuad.clause_presence.micro_f1",
        score=0.60, ok=True, latency_seconds=100.0, gpu_seconds=180.0,
        completion_tokens=1000,
    ),
    GridDocument(
        experiment="Experiment 3", specialist="Contracts",
        metric_id="cuad.clause_presence.micro_f1",
        score=0.64, ok=True, latency_seconds=90.0, gpu_seconds=180.0,
        completion_tokens=1100,
    ),
    # E3 merger: scores 0.03/0.04 → 0.035; coverage 0.24/0.26 → 0.25;
    # p50 92.5; 400 GPU s → $0.088888…; /2 ok.
    GridDocument(
        experiment="Experiment 3", specialist="Merger Agreements",
        metric_id="maud.question.micro_accuracy",
        score=0.03, coverage=0.24, ok=True, latency_seconds=90.0,
        gpu_seconds=200.0, completion_tokens=2000,
    ),
    GridDocument(
        experiment="Experiment 3", specialist="Merger Agreements",
        metric_id="maud.question.micro_accuracy",
        score=0.04, coverage=0.26, ok=True, latency_seconds=95.0,
        gpu_seconds=200.0, completion_tokens=2000,
    ),
    # E4 contracts: one errored doc must not count as ok.
    GridDocument(
        experiment="Experiment 4", specialist="Contracts",
        metric_id="cuad.clause_presence.micro_f1",
        score=0.61, ok=True, latency_seconds=96.0, gpu_seconds=180.0,
        completion_tokens=1000,
    ),
    GridDocument(
        experiment="Experiment 4", specialist="Contracts",
        metric_id="cuad.clause_presence.micro_f1",
        score=None, ok=False, latency_seconds=120.0, gpu_seconds=200.0,
        error="LengthFinishReasonError", completion_tokens=400,
    ),
]


def _row(rows, experiment, specialist):
    return next(
        r for r in rows
        if r["experiment"] == experiment and r["specialist"] == specialist
    )


def test_specialist_grid_quality_latency_and_cost_per_ok():
    rows = specialist_grid_rows(_DOCUMENTS, _EXPERIMENTS)
    contracts = _row(rows, "Experiment 3", "Contracts")
    assert contracts["score"] == 0.62
    assert contracts["ok"] == 2 and contracts["n"] == 2
    assert contracts["p50_latency_seconds"] == 95.0
    assert contracts["gpu_cost_usd"] == 0.08
    assert contracts["cost_per_ok_document"] == 0.04
    assert contracts["cost_basis"] == "busy_window"
    assert contracts["serving_kind"] == "modal"
    assert contracts["metric_id"] == "cuad.clause_presence.micro_f1"

    merger = _row(rows, "Experiment 3", "Merger Agreements")
    assert merger["score"] == pytest.approx(0.035)
    assert merger["coverage"] == pytest.approx(0.25)
    assert merger["p50_latency_seconds"] == 92.5
    assert merger["cost_per_ok_document"] == pytest.approx(0.044444, abs=1e-6)


def test_error_rate_and_ok_count_from_explicit_errors():
    rows = specialist_grid_rows(_DOCUMENTS, _EXPERIMENTS)
    e4 = _row(rows, "Experiment 4", "Contracts")
    assert e4["n"] == 2
    assert e4["ok"] == 1
    assert e4["errored"] == 1
    assert e4["error_rate"] == 0.5
    assert e4["cost_per_ok_document"] == pytest.approx(0.084444, abs=1e-6)


def test_error_class_failure_is_not_masked_by_success_error_token():
    masked = GridDocument(
        experiment="Experiment 4",
        specialist="Contracts",
        error="stop",
        error_class="LengthFinishReasonError",
    )
    assert _is_error(masked) is True
    completed = GridDocument(
        experiment="Experiment 4",
        specialist="Contracts",
        error="stop_sequence",
        error_class="tool_calls",
    )
    assert _is_error(completed) is False


def test_serving_efficiency_pooled_per_experiment():
    rows = serving_efficiency_rows(_DOCUMENTS, _EXPERIMENTS)
    e3 = next(r for r in rows if r["experiment"] == "Experiment 3")
    assert e3["n_documents"] == 4
    assert e3["error_rate"] == 0.0
    assert e3["documents_per_minute"] == pytest.approx(0.8)
    # (1000+1100+2000+2000) / 300s / 2 GPUs
    assert e3["tokens_per_second_per_gpu"] == pytest.approx(10.166667, abs=1e-5)
    assert e3["gpu_cost_per_document"] == pytest.approx(0.0422, abs=1e-4)
    assert e3["serving_kind"] == "modal"

    e4 = next(r for r in rows if r["experiment"] == "Experiment 4")
    assert e4["error_rate"] == 0.5
    assert e4["documents_per_minute"] == pytest.approx(0.2)


def test_session_cost_busy_vs_metered():
    rows = session_cost_rows(_EXPERIMENTS, _DOCUMENTS)
    e3 = next(r for r in rows if r["session"] == "Experiment 3")
    assert e3["documents"] == 4
    assert e3["busy_gpu_usd"] == pytest.approx(0.168889, abs=1e-6)
    assert e3["metered_usd"] == 1.09
    assert e3["busy_share"] == pytest.approx(0.154944, abs=1e-5)
    assert e3["metered_per_document"] == pytest.approx(0.2725)
    assert e3["cost_basis"] == "billed_incl_cold"

    e4 = next(r for r in rows if r["session"] == "Experiment 4")
    assert e4["metered_usd"] is None
    assert e4["busy_share"] is None
    assert e4["metered_per_document"] is None  # never fabricated


def test_grid_report_markdown_matches_l4_shape():
    report = build_grid_report(
        documents=_DOCUMENTS,
        experiments=_EXPERIMENTS,
        title="L4 Specialist Grid (Experiments 3–4): Results and Cost Summary",
        setup="Qwen/Qwen3-8B-AWQ on vLLM v0.29.0, NVIDIA L4 at $0.80/GPU-hr; "
              "mailroom-dataset @ ed7576b6, seed 42.",
        findings=["Larger runs cost less per document."],
        provenance={
            "dataset_revision": "ed7576b6",
            "draw_seed": "42",
            "serving_kind": "modal",
            "cost_basis": "busy_window",
        },
        figures={"Throughput": "figures/1x-vs-2xL4-throughput.png"},
    )
    assert report.startswith("# L4 Specialist Grid")
    assert "## Key findings" in report
    assert "**Setup:** Qwen/Qwen3-8B-AWQ" in report
    # Posture table
    assert "| Experiment 3 | 2×L4 C32 n=50 | 2×L4 | 32 | 50 | 5 of 5 cells |" in report
    # Pooled efficiency: metrics as rows, experiments as columns.
    assert "| Error rate | 0.0% | 50.0% |" in report
    assert "| Documents per minute | 0.80 | 0.20 |" in report
    assert "| Tokens per second per GPU | 10 | 1 |" in report
    # Compact specialist rows joined with · across experiments.
    assert "| Contracts | 0.620 · 0.610 | 2/2 · 1/2 | 95.0 · 108.0 | $0.04000 · $0.08444 |" in report
    assert "| Merger Agreements | 0.035 (25%) | 2/2 | 92.5 | $0.04444 |" in report
    # Cost table: metered pending → n/a, totals withheld.
    assert "| Experiment 3 | 4 | $0.16889 | $1.09 | 15% | $0.27250 | n/a |" in report
    assert "| Experiment 4 | 2 | $0.08444 | n/a | n/a | n/a | n/a |" in report
    assert "| **Total** | 6 | $0.25333 | n/a | n/a | n/a | n/a |" in report
    assert "| serving_kind | modal |" in report
    assert "![Throughput](figures/1x-vs-2xL4-throughput.png)" in report
    assert "no number is fabricated" in report


def test_grid_scorecard_structure_and_provenance():
    card = grid_scorecard(
        documents=_DOCUMENTS,
        experiments=_EXPERIMENTS,
        provenance={"serving_kind": "modal", "cost_basis": "busy_window"},
    )
    assert card["provenance"]["serving_kind"] == "modal"
    assert len(card["specialists"]) == 3
    assert len(card["serving_efficiency"]) == 2
    assert len(card["cost"]) == 2
    assert all(row["cost_basis"] == "busy_window" for row in card["specialists"])
    assert all(row["cost_basis"] == "billed_incl_cold" for row in card["cost"])


def test_mixed_metric_ids_in_one_row_raise():
    docs = [
        {"experiment": "E", "specialist": "Contracts", "metric_id": "pipeline.extraction.overall", "score": 0.5},
        {"experiment": "E", "specialist": "Contracts", "metric_id": "cuad.clause_presence.micro_f1", "score": 0.5},
    ]
    with pytest.raises(ValueError, match="metric_id mixed"):
        specialist_grid_rows(docs, [GridExperiment(name="E", gpus=1, gpu_hourly_usd=1.0)])


def test_serving_kind_modal_is_never_remapped_to_local():
    row = specialist_grid_rows(
        _DOCUMENTS[:1], [GridExperiment(name="Experiment 3", serving_kind="modal-vllm")]
    )[0]
    assert row["serving_kind"] == "modal"
    with pytest.raises(ValueError, match="serving_kind"):
        specialist_grid_rows(
            _DOCUMENTS[:1], [GridExperiment(name="Experiment 3", serving_kind="cloud-remote")]
        )


def test_local_serving_kind_is_preserved():
    row = specialist_grid_rows(
        _DOCUMENTS[:1], [GridExperiment(name="Experiment 3", serving_kind="local")]
    )[0]
    assert row["serving_kind"] == "local"


def test_mapping_inputs_coerce_numbers_and_support_document_class_alias():
    documents = [{
        "experiment": "E", "doc_class": "Contracts", "score": "0.75",
        "coverage": "0.5", "ok": True, "latency_seconds": "12",
        "gpu_seconds": "1800", "completion_tokens": "120",
    }]
    experiments = [{
        "experiment": "E", "gpus": "2", "wall_seconds": "60",
        "gpu_hourly_usd": "2", "metered_usd": "3", "serving_kind": "modal-vllm",
    }]
    card = grid_scorecard(documents=documents, experiments=experiments)
    row = card["specialists"][0]
    assert row["specialist"] == "Contracts"
    assert row["score"] == 0.75
    assert row["coverage"] == 0.5
    assert row["p50_latency_seconds"] == 12.0
    assert row["cost_per_ok_document"] == 1.0
    assert row["serving_kind"] == "modal"
    assert card["serving_efficiency"][0]["tokens_per_second_per_gpu"] == 1.0
    assert card["cost"][0]["metered_per_document"] == 3.0


@pytest.mark.parametrize("value", [True, False, "unknown", None])
def test_invalid_numeric_mapping_values_do_not_fabricate_measurements(value):
    row = specialist_grid_rows([{
        "experiment": "E", "specialist": "Contracts", "score": value,
        "coverage": value, "latency_seconds": value, "gpu_seconds": value,
    }], [{"name": "E", "gpus": value, "gpu_hourly_usd": 1}])[0]
    for key in ("score", "coverage", "p50_latency_seconds", "gpu_cost_usd", "gpus"):
        assert row[key] is None
    assert row["n_scored"] == 0


def test_zero_scores_and_latency_are_measurements_not_missing_values():
    rows = specialist_grid_rows([
        GridDocument("E", "Contracts", score=0, coverage=0, latency_seconds=0),
        GridDocument("E", "Contracts", score=1, coverage=1, latency_seconds=10),
        GridDocument("E", "Contracts"),
    ])
    row = rows[0]
    assert row["n"] == 3
    assert row["n_scored"] == 2
    assert row["score"] == 0.5
    assert row["coverage"] == 0.5
    assert row["p50_latency_seconds"] == 5.0
    assert row["cost_per_ok_document"] is None
    assert row["serving_kind"] is None


def test_all_errored_documents_have_no_cost_per_ok_document():
    row = specialist_grid_rows(
        [GridDocument("E", "Contracts", ok=False, error="timeout", gpu_seconds=3600)],
        [GridExperiment("E", gpu_hourly_usd=2)],
    )[0]
    assert row["ok"] == 0
    assert row["errored"] == 1
    assert row["error_rate"] == 1.0
    assert row["gpu_cost_usd"] == 2.0
    assert row["cost_per_ok_document"] is None


@pytest.mark.parametrize("token", ["stop", "completed", "success", "none", "end_turn", "eos"])
@pytest.mark.parametrize("error_key", ["error", "error_class"])
def test_success_tokens_are_not_counted_as_errors(token, error_key):
    docs = [{"experiment": "E", "specialist": "Contracts", "ok": True, error_key: token}]
    card = grid_scorecard(documents=docs, experiments=[GridExperiment("E")])
    assert card["specialists"][0]["errored"] == 0
    assert card["specialists"][0]["ok"] == 1
    assert card["serving_efficiency"][0]["error_rate"] == 0.0


@pytest.mark.parametrize("wall_seconds", [None, 0, -1])
def test_missing_or_nonpositive_wall_time_withholds_throughput(wall_seconds):
    row = serving_efficiency_rows(
        [GridDocument("E", "Contracts", completion_tokens=120)],
        [GridExperiment("E", gpus=2, wall_seconds=wall_seconds)],
    )[0]
    assert row["documents_per_minute"] is None
    assert row["tokens_per_second_per_gpu"] is None


@pytest.mark.parametrize("gpus", [None, 0, -1])
def test_missing_or_nonpositive_gpu_count_withholds_only_gpu_throughput(gpus):
    row = serving_efficiency_rows(
        [GridDocument("E", "Contracts", completion_tokens=120)],
        [GridExperiment("E", gpus=gpus, wall_seconds=60)],
    )[0]
    assert row["documents_per_minute"] == 1.0
    assert row["tokens_per_second_per_gpu"] is None


def test_completion_tokens_take_precedence_over_total_including_zero():
    docs = [
        GridDocument("E", "Contracts", completion_tokens=60, total_tokens=600),
        GridDocument("E", "Contracts", total_tokens=180),
        GridDocument("E", "Contracts", completion_tokens=0, total_tokens=1000),
    ]
    row = serving_efficiency_rows(docs, [GridExperiment("E", gpus=2, wall_seconds=60)])[0]
    assert row["tokens_per_second_per_gpu"] == 2.0


def test_empty_experiment_preserves_billing_without_per_document_estimates():
    card = grid_scorecard(
        documents=[], experiments=[GridExperiment("E", wall_seconds=60, gpus=1, metered_usd=2)],
    )
    assert card["specialists"] == []
    row = card["serving_efficiency"][0]
    assert row["n_documents"] == 0
    for key in ("error_rate", "documents_per_minute", "tokens_per_second_per_gpu", "gpu_cost_per_document"):
        assert row[key] is None
    cost = card["cost"][0]
    assert cost["metered_usd"] == 2
    assert cost["metered_per_document"] is None
    assert cost["busy_share"] is None


def test_zero_metered_cost_is_preserved_without_dividing_by_zero():
    row = session_cost_rows(
        [GridExperiment("E", gpu_hourly_usd=1, metered_usd=0, billed_usd=0)],
        [GridDocument("E", "Contracts", gpu_seconds=0)],
    )[0]
    assert row["busy_gpu_usd"] == 0.0
    assert row["metered_per_document"] == 0.0
    assert row["billed_usd"] == 0
    assert row["busy_share"] is None


def test_scorecard_consumes_generators_once_and_keeps_experiment_order():
    docs = [GridDocument("B", "Contracts"), GridDocument("A", "Contracts")]
    experiments = [GridExperiment("A"), GridExperiment("B")]
    card = grid_scorecard(documents=(d for d in docs), experiments=(e for e in experiments))
    assert card == grid_scorecard(documents=docs, experiments=experiments)
    assert [row["experiment"] for row in card["specialists"]] == ["A", "B"]


@pytest.mark.parametrize("which", ["documents", "experiments"])
def test_scorecard_rejects_non_mapping_records(which):
    kwargs = {"documents": [], "experiments": [], which: [42]}
    with pytest.raises(TypeError, match="must be Grid"):
        grid_scorecard(**kwargs)


def test_scorecard_rejects_invalid_provenance_serving_kind():
    with pytest.raises(ValueError, match="provenance serving_kind invalid"):
        grid_scorecard(documents=[], experiments=[], provenance={"serving_kind": "unknown-provider"})


def test_expanded_report_totals_use_pooled_costs_and_document_counts():
    report = build_grid_report(
        documents=[
            GridDocument("A", "Contracts", ok=True, score=1, gpu_seconds=3600),
            GridDocument("B", "Contracts", ok=True, score=0.5, gpu_seconds=1800),
            GridDocument("B", "Contracts", ok=True, score=0.5, gpu_seconds=1800),
        ],
        experiments=[
            GridExperiment("A", gpu_hourly_usd=1, metered_usd=2, billed_usd=1),
            GridExperiment("B", gpu_hourly_usd=1, metered_usd=6, billed_usd=5),
        ],
        compact=False, appendix_url="https://example.com/method",
    )
    assert "| Contracts (A) | 1.000 | 1/1 | n/a | $1.00 |" in report
    assert "| Contracts (B) | 0.500 | 2/2 | n/a | $0.50000 |" in report
    assert "| **Total** | 3 | $2.00 | $8.00 | 25% | $2.67 | $6.00 |" in report
    assert "[appendix](https://example.com/method)" in report
