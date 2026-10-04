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
