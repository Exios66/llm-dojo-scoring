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


def test_score_changelog_0_30_0_moves_field_micro_precision():
    """The #133 money fix can turn a FP+FN into a TP, so precision moves too.

    The fix ships in 0.30.0 (v0.29.0 was tagged from main before it landed),
    so the ledger names 0.30.0: a run stamped 0.28.1 and one stamped 0.30.0
    must find it.
    """
    changes = score_changes_for_metric(
        "pipeline.extraction.field_micro_precision", "0.28.1", "0.30.0"
    )
    money = [entry for entry in changes if "#133" in entry["change"]]
    assert [entry["version"] for entry in money] == ["0.30.0"]
    in_tag = score_changes_for_metric(
        "pipeline.extraction.field_micro_precision", "0.28.1", "0.29.0"
    )
    assert not any("#133" in entry["change"] for entry in in_tag)


def test_score_changelog_money_entry_names_every_metric_the_parser_moves():
    """#133's money fix also moves metrics that have no canonical ``metric_id``.

    ``parse_money`` feeds ``amount_exactness`` and the money diagnostics. A
    consumer comparing those across 0.29.0 to 0.30.0 must find them in the
    ledger entry, and the numbers must really move the way the entry says.
    """
    from llm_dojo_scoring.analysis.diagnostics import extraction_diagnostics
    from llm_dojo_scoring.scoring.claims_consistency import amount_exactness

    entry = next(
        e for e in score_changes_between("0.29.0", "0.30.0") if "#133" in e["change"]
    )
    for name in (
        "amount_exactness",
        "money_mae_usd",
        "money_median_ae_usd",
        "money_mae_per_field",
        "money_n_pairs",
    ):
        assert name in entry["change"], name
    # What the entry claims: pairs a bare K/M/B-with-currency-word string used to skip.
    assert amount_exactness({"claimed_amount": "$2,000,000"}, {"claimed_amount": "2M USD"}) == 1.0
    assert amount_exactness({"claimed_amount": "$1,200,000"}, {"claimed_amount": "USD 1.3M"}) == 0.0
    row = {
        "filename": "a",
        "predicted": {"claimed_amount": "5K dollars"},
        "expected_fields": {"claimed_amount": "$5,000"},
        "field_scores": {"claimed_amount": 1.0},
        "entity_list_scores": {},
        "entity_list_audit": {},
    }
    diagnostics = extraction_diagnostics([row], {"claimed_amount": "money"})
    assert diagnostics["money_n_pairs"] == 1
    assert diagnostics["money_mae_usd"] == 0.0


def test_new_metric_entries_are_the_only_ones_that_need_no_rescore():
    """``rescore_required: False`` is for new metric ids; the entry must say no value moves."""
    from llm_dojo_scoring.metrics.score_changelog import SCORE_CHANGELOG

    for entry in SCORE_CHANGELOG:
        if not entry["rescore_required"]:
            assert entry["change"].startswith("New metrics"), entry["version"]
            assert "No existing metric value changes" in entry["change"], entry["version"]
    # The 0.29.0 -> 0.30.0 interval mixes both kinds; a reader filters on the flag.
    interval = score_changes_between("0.29.0", "0.30.0")
    assert {entry["rescore_required"] for entry in interval} == {True, False}


def test_score_changelog_0_29_0_names_the_date_reader():
    """#134 (dates no longer read the clock) shipped in the v0.29.0 tag.

    A run stamped 0.28.1 compared with one stamped 0.29.0 must be told that
    date-field scores, and the field-micro metrics they feed, moved.
    """
    for metric_id in (
        "pipeline.extraction.overall",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
        "pipeline.extraction.field_micro_precision",
        "pipeline.extraction.field_micro_recall",
        # sandbox_scoring._same_date decides cuad_effective_from_agreement.
        "cuad.sandbox_category_detection.micro_f1",
        "cuad.sandbox_category_detection.micro_precision",
        "cuad.sandbox_category_detection.micro_recall",
    ):
        changes = score_changes_for_metric(metric_id, "0.28.1", "0.29.0")
        assert [entry["version"] for entry in changes] == ["0.29.0"], metric_id
        assert "#134" in changes[0]["change"]
        assert changes[0]["rescore_required"] is True


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
