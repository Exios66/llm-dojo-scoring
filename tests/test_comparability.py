"""Cross-scorer-version comparability (issue #97).

A card built from two scorer releases can look comparable when only the
``metric_id`` agrees. These tests pin the release guard: mismatch is
incomparable, a one-sided stamp is missing, and jointly missing stamps are
comparable but explicitly unverified.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.analysis.serving import (
    aggregate_serving,
    compare_serving,
    pair_comparable_runs,
)
from llm_dojo_scoring.metrics.score_changelog import (
    score_changes_between,
    score_changes_for_metric,
)
from llm_dojo_scoring.metrics.scorecard_honesty import ProvenanceExportError, SCORER_VERSION


def _leg(provider: str, version: str | None = None, **kw):
    """Build one serving leg with a fixed quality score and optional release stamp."""
    record = {
        "provider": provider,
        "ttft_seconds": 0.2,
        "scores": {"extraction_overall_score": 0.8},
        "metric_id": "pipeline.extraction.overall",
        "dataset_revision": "r1",
        "split": "test",
        "draw_seed": "42",
        "prompt_id": "p1",
        "prompt_version": "p1",
        "model": "qwen3:8b",
    }
    if version is not None:
        record["provenance"] = {"scorer_version": version}
    record.update(kw)
    return record


def test_scorer_version_mismatch_is_incomparable():
    """Different scorer releases suppress the quality delta and name the reason."""
    out = compare_serving(_leg("vllm", "0.25.0"), _leg("openrouter", "0.26.0"))
    assert out["incomparable"] is True
    assert out["incomparable_reason"] == "scorer_version_mismatch"
    assert out["quality"]["delta_local_minus_api"] is None
    assert out["left_scorer_version"] == "0.25.0"
    assert out["right_scorer_version"] == "0.26.0"
    assert "scorer_version_mismatch" in out["markdown"]


def test_one_sided_scorer_version_is_missing():
    """A leg that names its release cannot compare against an unstamped leg."""
    out = compare_serving(_leg("vllm", "0.25.0"), _leg("openrouter"))
    assert out["incomparable"] is True
    assert out["incomparable_reason"] == "scorer_version_missing"
    assert out["quality"]["delta_local_minus_api"] is None


def test_jointly_missing_scorer_versions_are_unverified():
    """Legacy records without a release are comparable only with a flag."""
    out = compare_serving(_leg("vllm"), _leg("openrouter"))
    assert not out.get("incomparable")
    assert out["scorer_version_unverified"] is True
    assert out["quality"]["delta_local_minus_api"] == pytest.approx(0.0)


def test_partially_stamped_leg_is_unverified():
    """A leg pooling stamped and unstamped runs is comparable but unproven."""
    out = compare_serving(
        [_leg("vllm", "0.25.0"), _leg("vllm")],
        _leg("openrouter", "0.25.0"),
    )
    assert not out.get("incomparable")
    assert out["scorer_version_unverified"] is True
    assert out["local"]["scorer_version_partial"] is True


def test_mixed_scorer_versions_in_one_leg_are_incomparable():
    """A leg cannot pool two scorer generations under one quality identity."""
    out = compare_serving(
        [_leg("vllm", "0.25.0"), _leg("vllm", "0.26.0")],
        _leg("openrouter", "0.26.0"),
    )
    assert out["incomparable"] is True
    assert out["incomparable_reason"] == "scorer_version_mixed"
    assert out["local"]["scorer_version_conflict"] == ["0.25.0", "0.26.0"]


def test_aggregate_reports_the_uniform_version():
    """One release across a leg is carried onto the aggregate."""
    agg = aggregate_serving([_leg("vllm", "0.26.0")])
    assert agg["scorer_version"] == "0.26.0"
    assert "scorer_version_conflict" not in agg


def test_pair_comparable_runs_separates_scorer_versions():
    """Pairing never crosses a scorer release, even with matching metrics."""
    common = {
        "task": "sorter",
        "prompt_version": "p1",
        "dataset_fingerprint": "fp",
        "dataset_revision": "r1",
        "metric_id": "pipeline.extraction.overall",
    }
    records = [
        {**common, "provider": "vllm", "scorer_version": "0.25.0"},
        {**common, "provider": "openrouter", "scorer_version": "0.26.0"},
    ]
    assert pair_comparable_runs(records) == []
    records[1]["scorer_version"] = "0.25.0"
    assert len(pair_comparable_runs(records)) == 1


def test_score_changelog_lists_releases_between_two_versions():
    """The ledger names every release in the interval, oldest first."""
    changes = score_changes_between("0.24.0", "0.26.0")
    assert [entry["version"] for entry in changes] == ["0.25.0", "0.26.0"]
    assert all(entry["rescore_required"] for entry in changes)


def test_score_changelog_can_filter_one_metric():
    """A metric query returns only the releases that moved that metric."""
    changes = score_changes_for_metric(
        "cuad.clause_presence.micro_f1", "0.25.0", "0.26.0"
    )
    assert len(changes) == 1
    assert changes[0]["version"] == "0.26.0"


def test_score_changelog_handles_reversed_and_invalid_versions():
    """Reversing the pair is harmless; missing or junk releases yield nothing."""
    assert score_changes_between("0.26.0", "0.24.0") == score_changes_between(
        "0.24.0", "0.26.0"
    )
    assert score_changes_between(None, "0.26.0") == []
    assert score_changes_between("not-a-version", "0.26.0") == []


def test_compare_payload_carries_the_score_changes():
    """A mismatch names the scorer fixes behind the incomparable delta."""
    out = compare_serving(_leg("vllm", "0.24.0"), _leg("openrouter", "0.26.0"))
    assert [entry["version"] for entry in out["score_changes"]] == ["0.25.0", "0.26.0"]


def test_strict_provenance_uses_each_legs_recorded_release():
    """Strict export catches a release mismatch instead of restamping today."""
    with pytest.raises(ProvenanceExportError, match="scorer_version"):
        compare_serving(
            _leg("vllm", "0.25.0"),
            _leg("openrouter", "0.26.0"),
            require_provenance={"local": {}, "api": {}},
        )


def test_strict_provenance_accepts_matching_releases():
    """Matching recorded releases pass strict export."""
    out = compare_serving(
        _leg("vllm", SCORER_VERSION),
        _leg("openrouter", SCORER_VERSION),
        require_provenance={"local": {}, "api": {}},
    )
    assert not out.get("incomparable")


def test_strict_provenance_refuses_a_partially_stamped_leg():
    """A leg mixing stamped and unstamped runs cannot be certified strict."""
    with pytest.raises(ProvenanceExportError, match="unstamped"):
        compare_serving(
            [_leg("vllm", "0.25.0"), _leg("vllm")],
            _leg("openrouter", SCORER_VERSION),
            require_provenance={"local": {}, "api": {}},
        )


# --- PR #103 review regressions -------------------------------------------


@pytest.mark.parametrize("stamp", ["legacy", "unknown", "v-next"])
def test_unparseable_matching_scorer_versions_are_unverified(stamp):
    """A stamp the release ledger cannot parse proves nothing about the scorer."""
    out = compare_serving(_leg("vllm", stamp), _leg("openrouter", stamp))
    assert not out.get("incomparable")
    assert out["scorer_version_unverified"] is True


def test_one_unparseable_scorer_version_is_unverified_or_incomparable():
    """An invalid stamp on one leg never yields a clean, verified comparison."""
    out = compare_serving(_leg("vllm", "legacy"), _leg("openrouter", "0.26.0"))
    assert out.get("incomparable") or out.get("scorer_version_unverified")
    assert out["quality"]["delta_local_minus_api"] is None or out.get(
        "scorer_version_unverified"
    )


def test_valid_matching_scorer_versions_stay_verified():
    """Parseable, equal releases are not flagged."""
    out = compare_serving(_leg("vllm", "0.26.0"), _leg("openrouter", "0.26.0"))
    assert not out.get("incomparable")
    assert "scorer_version_unverified" not in out


def test_emit_serving_scorecard_keeps_historical_leg_release():
    """Uniformly stamped historical legs keep their release on every emitted record."""
    from llm_dojo_scoring import Emitter, emit_serving_scorecard

    cmp = compare_serving(_leg("vllm", "0.20.0"), _leg("openrouter", "0.20.0"))
    em = Emitter(sinks=[])
    emit_serving_scorecard(cmp, run_id="hist", emitter=em)
    assert em._records
    assert {r.metadata["provenance"]["scorer_version"] for r in em._records} == {"0.20.0"}
    assert SCORER_VERSION != "0.20.0"


def test_emit_serving_scorecard_explicit_scorer_version_wins():
    """A caller-supplied provenance scorer_version overrides the leg's recorded one."""
    from llm_dojo_scoring import Emitter, emit_serving_scorecard

    cmp = compare_serving(_leg("vllm", "0.20.0"), _leg("openrouter", "0.20.0"))
    em = Emitter(sinks=[])
    emit_serving_scorecard(
        cmp, run_id="hist", emitter=em,
        provenance={"local": {"scorer_version": "0.21.0"}},
    )
    got = {
        (r.metadata["side"], r.metadata["provenance"]["scorer_version"])
        for r in em._records
    }
    assert got == {("local", "0.21.0"), ("api", "0.20.0")}
