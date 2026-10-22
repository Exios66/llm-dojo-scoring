"""#22 remainder: Emitter.emit_score and the archive block carry provenance."""

from __future__ import annotations

import json

import pytest

from llm_dojo_scoring.archive import (
    ARCHIVE_SCORING_KEYS,
    empty_archive_scoring_block,
    score_archive_block,
)
from llm_dojo_scoring.emitter import (
    EMIT_REQUIRED_PROVENANCE,
    Emitter,
    LocalManifestSink,
)
from llm_dojo_scoring.registry import MetricDef, MetricTier, Registry
from llm_dojo_scoring.scorecard_honesty import (
    SCORER_VERSION,
    ProvenanceExportError,
    stamp_provenance,
    validate_comparison_provenance,
)

PROV = {
    "dataset_revision": "46a4d3c2",
    "prompt_id": "insurance_claims_specialist_v1",
    "serving_kind": "modal-vllm",
    "model_id": "Qwen/Qwen3-8B-AWQ",
}


def _registry() -> Registry:
    """Build a minimal registry covering extraction, latency, and cost provenance."""
    reg = Registry()
    reg.metrics["extraction_overall_score"] = MetricDef(
        name="extraction_overall_score", tier=MetricTier.HEADLINE
    )
    reg.metrics["ttft_seconds"] = MetricDef(
        name="ttft_seconds", tier=MetricTier.CORE, units="seconds"
    )
    reg.metrics["estimated_cost_usd"] = MetricDef(
        name="estimated_cost_usd", tier=MetricTier.CORE, units="USD", aggregation="sum"
    )
    return reg


@pytest.mark.parametrize("dropped", EMIT_REQUIRED_PROVENANCE)
def test_emit_refuses_each_missing_required_key(dropped):
    """Reject incomplete provenance before adding records to the emitter."""
    em = Emitter(sinks=[], registry=_registry())
    prov = {k: v for k, v in PROV.items() if k != dropped}
    with pytest.raises(ProvenanceExportError, match=dropped):
        em.emit_score("insurance_claims_specialist", "d1",
                      "extraction_overall_score", 0.7, provenance=prov)
    assert em._records == []  # refused before any sink or the scorecard


def test_emit_without_stamp_never_reaches_a_sink(tmp_path):
    """Reject unstamped scores without creating a sink manifest."""
    sink = LocalManifestSink(tmp_path / "s.jsonl")
    em = Emitter(sinks=[sink], registry=_registry())
    with pytest.raises(ProvenanceExportError):
        em.emit_score("a", "d1", "extraction_overall_score", 0.7)
    assert not (tmp_path / "s.jsonl").exists()


def test_emit_stamps_scorer_version_and_canonical_metric_id(tmp_path):
    """Stamp emitted scores with canonical identity, scorer version, and normalized serving kind."""
    sink = LocalManifestSink(tmp_path / "s.jsonl")
    em = Emitter(sinks=[sink], registry=_registry())
    em.emit_score("a", "d1", "extraction_overall_score", 0.7, provenance=PROV)
    row = json.loads((tmp_path / "s.jsonl").read_text())
    prov = row["metadata"]["provenance"]
    assert prov["metric_id"] == "pipeline.extraction.overall"
    assert prov["scorer_version"] == SCORER_VERSION
    assert prov["serving_kind"] == "modal"  # normalized token
    assert prov["model_id"] == "Qwen/Qwen3-8B-AWQ"


def test_emit_accepts_a_stamped_scorecard():
    """Accept a pre-stamped scorecard as the source of emission provenance."""
    em = Emitter(sinks=[], registry=_registry())
    card = stamp_provenance({"overall": 0.7}, **PROV)
    rec = em.emit_score("a", "d1", "extraction_overall_score", 0.7, provenance=card)
    assert rec.metadata["provenance"]["dataset_revision"] == "46a4d3c2"


def test_emit_reads_provenance_from_metadata():
    """Read embedded provenance without discarding unrelated record metadata."""
    em = Emitter(sinks=[], registry=_registry())
    rec = em.emit_score("a", "d1", "extraction_overall_score", 0.7,
                        metadata={"provenance": PROV, "side": "api"})
    assert rec.metadata["side"] == "api"
    assert rec.metadata["provenance"]["prompt_id"] == PROV["prompt_id"]


def test_unmapped_metric_gets_registry_identity_not_a_comparison_id():
    """Assign registry identity to metrics without a canonical comparison mapping."""
    em = Emitter(sinks=[], registry=_registry())
    rec = em.emit_score("a", "d1", "ttft_seconds", 0.4, provenance=PROV)
    assert rec.metadata["provenance"]["metric_id"] == "registry:ttft_seconds"


@pytest.mark.parametrize("metric_id", ["cuad.clause_presence.micro_f1", "", 0, False])
def test_contradicting_metric_id_is_refused(metric_id):
    """Reject supplied identities that contradict the emitted canonical metric."""
    em = Emitter(sinks=[], registry=_registry())
    with pytest.raises(ProvenanceExportError, match="contradicts"):
        em.emit_score("a", "d1", "extraction_overall_score", 0.7,
                      provenance={**PROV, "metric_id": metric_id})


@pytest.mark.parametrize("require_provenance", [True, False])
@pytest.mark.parametrize("stamped", [True, False])
@pytest.mark.parametrize("metric_id", ["registry:e2e_latency_seconds", "", 0, False])
def test_unmapped_metric_refuses_conflicting_identity(tmp_path, require_provenance, stamped, metric_id):
    """Reject conflicting registry identities before recording or writing a score."""
    sink = LocalManifestSink(tmp_path / "scores.jsonl")
    em = Emitter(sinks=[sink], registry=_registry(), require_provenance=require_provenance)
    prov = {**PROV, "metric_id": metric_id}
    if stamped:
        prov = stamp_provenance(prov)
    with pytest.raises(ProvenanceExportError, match="contradicts"):
        em.emit_score("a", "d1", "ttft_seconds", 0.4, provenance=prov)
    assert em._records == []
    assert sink.read_all() == []


def test_unmapped_metric_accepts_matching_identity():
    """Accept an explicitly supplied matching registry metric identity."""
    em = Emitter(sinks=[], registry=_registry())
    rec = em.emit_score("a", "d1", "ttft_seconds", 0.4,
                        provenance={**PROV, "metric_id": "registry:ttft_seconds"})
    assert rec.metadata["provenance"]["metric_id"] == "registry:ttft_seconds"


def test_cost_metric_requires_a_cost_basis():
    """Require and preserve a declared cost basis when emitting USD metrics."""
    em = Emitter(sinks=[], registry=_registry())
    with pytest.raises(ProvenanceExportError, match="cost_basis"):
        em.emit_score("a", "d1", "estimated_cost_usd", 0.01, provenance=PROV)
    with pytest.raises(ProvenanceExportError, match="cost_basis"):
        em.emit_score("a", "d1", "estimated_cost_usd", 0.01,
                      provenance={**PROV, "cost_basis": "per_token_guess"})
    rec = em.emit_score("a", "d1", "estimated_cost_usd", 0.01,
                        provenance={**PROV, "cost_basis": "busy_window"})
    assert rec.metadata["provenance"]["cost_basis"] == "busy_window"


def test_opt_out_still_records_what_was_given():
    """Retain supplied provenance and scorer identity when strict requirements are disabled."""
    em = Emitter(sinks=[], registry=_registry(), require_provenance=False)
    rec = em.emit_score("a", "d1", "extraction_overall_score", 0.7)
    prov = rec.metadata["provenance"]
    assert prov["scorer_version"] == SCORER_VERSION
    assert prov["dataset_revision"] is None


def test_two_emitted_records_pass_the_comparison_gate():
    """Accept comparison provenance from two compatibly stamped emitted records."""
    em = Emitter(sinks=[], registry=_registry())
    a = em.emit_score("a", "d1", "extraction_overall_score", 0.7,
                      provenance={**PROV, "split": "test", "draw_seed": "42"})
    b = em.emit_score("b", "d1", "extraction_overall_score", 0.6,
                      provenance={**PROV, "split": "test", "draw_seed": "42"})
    validate_comparison_provenance(a.metadata, b.metadata)


# ---- archive block -------------------------------------------------------


def test_empty_archive_block_has_a_null_stamp():
    """Include a scorer stamp with null caller identity in empty archive blocks."""
    block = empty_archive_scoring_block()
    assert ARCHIVE_SCORING_KEYS[-1] == "provenance"
    assert block["provenance"]["scorer_version"] == SCORER_VERSION
    assert block["provenance"]["model_id"] is None


def test_archive_block_stamps_caller_provenance():
    """Carry canonical metric identity and normalized caller provenance into archive scores."""
    block = score_archive_block(
        "insurance_claim", {"insurer": "Acme"}, {"insurer": "Acme"}, provenance=PROV
    )
    prov = block["provenance"]
    assert prov["metric_id"] == "pipeline.extraction.overall"
    assert prov["prompt_id"] == PROV["prompt_id"]
    assert prov["serving_kind"] == "modal"


def test_archive_block_metric_id_follows_headline_method():
    """Choose archive provenance identity from the headline scoring method."""
    block = score_archive_block(
        "contract", {}, {}, method="extraction_category_presence", provenance=PROV
    )
    assert block["provenance"]["metric_id"] == "cuad.clause_presence.micro_f1"


def test_archive_block_refuses_contradicting_metric_id():
    """Reject archive provenance that contradicts the selected headline metric."""
    with pytest.raises(ProvenanceExportError):
        score_archive_block(
            "insurance_claim", {}, {},
            provenance={**PROV, "metric_id": "maud.question.micro_accuracy"},
        )
