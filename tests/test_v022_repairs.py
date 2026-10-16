"""Repairs after PR #42: fail-closed batches, archive identity, serving
comparisons, the comparison gate, and consumer-reported gaps (#16-#18, #22)."""

from __future__ import annotations

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.archive import (
    ARCHIVE_SCORING_POST_V021_KEYS,
    empty_archive_scoring_block,
    format_audit_entry,
    score_archive_block,
    validate_audit_entry,
)
from llm_dojo_scoring.emitter import Emitter
from llm_dojo_scoring.field_scoring import embed_texts, score_extraction
from llm_dojo_scoring.grid import build_grid_report, specialist_grid_rows
from llm_dojo_scoring.registry import get_registry
from llm_dojo_scoring.scorecard_honesty import (
    _CLASS_METRIC_IDS,
    _METRIC_ID_BY_NAME,
    COST_BASIS_VALUES,
    IncomparableMetricsError,
    ProvenanceExportError,
    UnknownMetricNameError,
    aggregate_quality_itt,
    assert_comparable_metric_ids,
    validate_comparison_provenance,
)
from llm_dojo_scoring.serving import compare_serving, pair_comparable_runs
from llm_dojo_scoring.suites import list_suites

LIVE = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")
INSURANCE = "insurance_claims_specialist"
GT = {"insurer": "Acme Mutual", "claim_number": "CLM-1"}


# ---- batch scoring (#16, #18) --------------------------------------------


def test_short_prediction_list_cannot_pass_the_batch_gate():
    suite = get_suite(INSURANCE)
    ftypes = {"insurer": "name", "claim_number": "id"}
    out = suite.score([dict(GT)] * 4, [dict(GT)], detailed=True, field_types=ftypes)
    assert out["schema_valid"] == pytest.approx(0.25)
    assert out["schema_promotion_gate"]["passes"] is False


def test_batch_rows_without_gt_are_unscorable_not_zero():
    suite = get_suite(INSURANCE)
    out = suite.score(
        [{"doc_subtype": "triage"}, dict(GT)], [dict(GT), dict(GT)], detailed=True
    )
    assert out["n_unscorable"] == 1
    assert out["n_scored"] == 1
    assert out["quality_mean"] == pytest.approx(1.0)


def test_all_unscorable_batch_is_unproven():
    suite = get_suite(INSURANCE)
    out = suite.score(
        [{"doc_subtype": "triage"}, {"doc_subtype": "triage"}],
        [dict(GT), dict(GT)],
        detailed=True,
    )
    assert out["n_scored"] == 0
    assert out["export_verdict"] == "unproven"
    assert out["quality_mean"] is None


def test_raw_string_prediction_is_parsed_and_gated():
    suite = get_suite(INSURANCE)
    bad = suite.score_document(dict(GT), "not json at all")
    assert bad["parse_ok"] == 0.0
    assert bad["schema_promotion_gate"]["passes"] is False
    good = suite.score_document(dict(GT), '{"insurer": "Acme Mutual", "claim_number": "CLM-1"}')
    assert good["overall_score"] == pytest.approx(1.0)


# ---- score_document provenance (#17, #22) --------------------------------


def test_score_document_refuses_contradicting_metric_id():
    with pytest.raises(ProvenanceExportError, match="contradicts"):
        get_suite(INSURANCE).score_document(dict(GT), dict(GT), metric_id="wrong.id")


def test_score_document_refuses_unknown_cost_basis():
    with pytest.raises(ProvenanceExportError, match="cost_basis"):
        get_suite(INSURANCE).score_document(dict(GT), dict(GT), cost_basis="bogus")


def test_score_document_stamps_a_valid_cost_basis():
    out = get_suite(INSURANCE).score_document(dict(GT), dict(GT), cost_basis="busy_window")
    assert out["provenance"]["cost_basis"] == "busy_window"


# ---- archive block -------------------------------------------------------


@pytest.mark.parametrize("claimed", ["", 0, False, "made.up"])
def test_archive_refuses_any_contradicting_claimed_metric_id(claimed):
    with pytest.raises(ProvenanceExportError):
        score_archive_block(
            "insurance_claim", dict(GT), dict(GT), provenance={"metric_id": claimed}
        )


def test_archive_method_resolves_to_canonical_id():
    block = score_archive_block("insurance_claim", dict(GT), dict(GT), method="extraction_f1")
    assert block["provenance"]["metric_id"] == "pipeline.extraction.field_micro_f1"


def test_archive_unknown_method_raises():
    with pytest.raises(UnknownMetricNameError):
        score_archive_block("insurance_claim", dict(GT), dict(GT), method="made_up_metric")


def test_archive_block_marks_unscorable_gt():
    block = score_archive_block("insurance_claim", dict(GT), {"doc_subtype": "triage"})
    assert block["status"] == "unscorable"
    assert block["reason"]
    scored = score_archive_block("insurance_claim", dict(GT), dict(GT))
    assert scored["status"] == "scored"


def test_legacy_archive_rows_without_new_keys_still_validate():
    legacy = {
        k: v for k, v in empty_archive_scoring_block().items()
        if k not in ARCHIVE_SCORING_POST_V021_KEYS
    }
    entry = format_audit_entry(
        doc_id="doc_legacy",
        matter_id="EXAMPLE",
        entry_id="e-legacy",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=legacy,
    )
    codes = {item["code"] for item in validate_audit_entry(entry)}
    assert "scoring_keys_incomplete" not in codes


# ---- serving comparisons (#17, #22) --------------------------------------


def _leg(provider: str, **kw):
    base = {"provider": provider, "ttft_seconds": 0.2,
            "scores": {"extraction_overall_score": 0.8}}
    base.update(kw)
    return base


def test_one_sided_metric_id_is_incomparable():
    out = compare_serving(
        _leg("vllm", metric_id="pipeline.extraction.overall"), _leg("openrouter")
    )
    assert out["incomparable"] is True
    assert out["incomparable_reason"] == "metric_id_missing"
    assert out["quality"]["delta_local_minus_api"] is None
    assert "INCOMPARABLE" in out["markdown"]


def test_mismatched_metric_id_suppresses_quality_delta():
    out = compare_serving(
        _leg("vllm", metric_id="pipeline.extraction.overall"),
        _leg("openrouter", metric_id="cuad.clause_presence.micro_f1"),
    )
    assert out["incomparable_reason"] == "metric_id_mismatch"
    assert out["quality"]["delta_local_minus_api"] is None
    assert out["scorecard"]["incomparable"] is True


def test_leg_mixing_metric_ids_is_incomparable():
    out = compare_serving(
        [
            _leg("vllm", metric_id="pipeline.extraction.overall"),
            _leg("vllm", metric_id="cuad.clause_presence.micro_f1"),
        ],
        _leg("openrouter", metric_id="pipeline.extraction.overall"),
    )
    assert out["incomparable_reason"] == "metric_id_mixed"


def test_same_metric_id_keeps_the_delta():
    out = compare_serving(
        _leg("vllm", metric_id="pipeline.extraction.overall"),
        _leg("openrouter", metric_id="pipeline.extraction.overall",
             scores={"extraction_overall_score": 0.6}),
    )
    assert not out.get("incomparable")
    assert out["quality"]["delta_local_minus_api"] == pytest.approx(0.2)


def test_compare_serving_require_provenance_refuses_gaps():
    with pytest.raises(ProvenanceExportError, match="dataset_revision"):
        compare_serving(
            _leg("vllm", model="qwen3:8b", prompt_version="p1"),
            _leg("openrouter", model="qwen/qwen3.7-flash", prompt_version="p1"),
            require_provenance={"local": {"split": "test"}, "api": {"split": "test"}},
        )
    mid = "pipeline.extraction.overall"
    compare_serving(
        _leg("vllm", model="qwen3:8b", prompt_version="p1", dataset_revision="r1",
             metric_id=mid),
        _leg("openrouter", model="qwen/qwen3.7-flash", prompt_version="p1",
             dataset_revision="r1", metric_id=mid),
        require_provenance={"local": {"split": "test"}, "api": {"split": "test"}},
    )


def test_pairing_keeps_different_dataset_revisions_apart():
    common = {"task": "sorter", "prompt_version": "p1", "dataset_fingerprint": "fp"}
    records = [
        {**common, "provider": "vllm", "dataset_revision": "r1"},
        {**common, "provider": "openrouter", "dataset_revision": "r2"},
    ]
    assert pair_comparable_runs(records) == []
    records[1]["dataset_revision"] = "r1"
    assert len(pair_comparable_runs(records)) == 1


# ---- comparison gate -----------------------------------------------------

_FULL = {
    "dataset_revision": "r1",
    "split": "test",
    "draw_seed": "42",
    "prompt_id": "p1",
    "metric_id": "pipeline.extraction.overall",
    "scorer_version": "0.21.0",
    "serving_kind": "local",
    "model_id": "qwen3:8b",
}


def test_vary_axis_may_differ_but_must_be_present():
    api = {**_FULL, "serving_kind": "api", "model_id": "qwen/qwen3.7-flash"}
    with pytest.raises(ProvenanceExportError, match="mismatched"):
        validate_comparison_provenance(_FULL, api)
    validate_comparison_provenance(_FULL, api, vary=("serving_kind", "model_id"))
    with pytest.raises(ProvenanceExportError, match="missing"):
        validate_comparison_provenance(
            _FULL, {**api, "model_id": None}, vary=("serving_kind", "model_id")
        )


def test_draw_seed_may_be_absent_on_both_legs_only():
    no_seed = {**_FULL, "draw_seed": None}
    validate_comparison_provenance(no_seed, dict(no_seed))
    with pytest.raises(ProvenanceExportError, match="draw_seed"):
        validate_comparison_provenance(_FULL, no_seed)


def test_draw_seed_zero_is_a_real_seed():
    zero = {**_FULL, "draw_seed": 0}
    validate_comparison_provenance(zero, dict(zero))


def test_comparison_gate_validates_cost_basis_values():
    with pytest.raises(ProvenanceExportError, match="not one of"):
        validate_comparison_provenance(
            {**_FULL, "cost_basis": "guess"}, {**_FULL, "cost_basis": "guess"}
        )
    assert "token_price_estimate" in COST_BASIS_VALUES


def test_unknown_vary_key_is_a_caller_error():
    with pytest.raises(ValueError):
        validate_comparison_provenance(_FULL, _FULL, vary=("model",))


def test_one_sided_metric_id_refused_by_assert_helper():
    with pytest.raises(IncomparableMetricsError, match="metric_id_missing"):
        assert_comparable_metric_ids("pipeline.extraction.overall", None)
    soft = assert_comparable_metric_ids(None, "pipeline.extraction.overall", hard=False)
    assert soft["incomparable_reason"] == "metric_id_missing"
    assert assert_comparable_metric_ids(None, None)["metric_id_unverified"] is True


def test_emitter_names_an_invalid_cost_basis_as_invalid():
    em = Emitter(sinks=[])
    with pytest.raises(ProvenanceExportError, match="not one of"):
        em.emit_score(
            "a", "d1", "estimated_cost_usd", 0.01,
            provenance={
                "dataset_revision": "r1", "prompt_id": "p", "serving_kind": "api",
                "model_id": "m", "cost_basis": "guess",
            },
        )


# ---- ITT and grid (#16) --------------------------------------------------


def test_itt_denominator_excludes_unscorable_docs():
    rows = [{"overall_score": 1.0}, {"overall_score": 1.0}, {"status": "unscorable"}]
    itt = aggregate_quality_itt(rows, {"n_attempted": 4, "n_errored": 1})
    assert itt["n_attempted_scorable"] == 3
    assert itt["quality_mean_itt"] == pytest.approx(2 / 3, abs=1e-3)


def test_grid_rows_leave_unscorable_documents_out_of_quality():
    docs = [
        {"experiment": "e1", "specialist": "insurance_claim", "score": 0.9, "ok": True},
        {"experiment": "e1", "specialist": "insurance_claim", "score": 0.0,
         "status": "unscorable", "ok": True},
        {"experiment": "e1", "specialist": "contract", "score": 0.0,
         "scores": {"status": "unscorable"}},
    ]
    rows = {r["specialist"]: r for r in specialist_grid_rows(docs)}
    assert rows["insurance_claim"]["score"] == pytest.approx(0.9)
    assert rows["insurance_claim"]["n_unscorable"] == 1
    assert rows["contract"]["score"] is None
    assert rows["contract"]["quality_status"] == "unproven"


# ---- field scoring -------------------------------------------------------


@pytest.fixture
def type_bands():
    from llm_dojo_scoring.config import configure, get_settings

    saved = dict(get_settings().field_scoring.type_bands)
    yield lambda bands: configure(field_scoring__type_bands=bands)
    configure(field_scoring__type_bands=saved)


def test_score_extraction_uses_per_type_bands(type_bands):
    type_bands({"date": ("never",), "name": ("always",)})
    result = score_extraction(
        "contract",
        {"effective_date": "date", "party": "name"},
        {"effective_date": "2020-01-05", "party": "Acme"},
        {"effective_date": "2020-01-01", "party": "Acme"},
    )
    assert "effective_date" not in result.ambiguous_fields
    assert "party" in result.ambiguous_fields


def test_expected_subclass_is_not_scored_as_a_field():
    suite = get_suite(INSURANCE)
    out = suite.score_document({**GT, "expected_subclass": "pde"}, dict(GT))
    assert out["overall_score"] == pytest.approx(1.0)


def test_embed_texts_is_fail_soft_when_disabled():
    assert embed_texts(["Acme"]) is None


# ---- metric identity / registry ------------------------------------------


def test_every_canonical_id_is_allowed_somewhere():
    allowed = {mid for ids in _CLASS_METRIC_IDS.values() for mid in ids}
    classification_or_content = {
        "pipeline.classification.f1_macro",
        "pipeline.classification.accuracy",
    }
    assert set(_METRIC_ID_BY_NAME.values()) - allowed <= classification_or_content


@pytest.mark.parametrize("doc_class", LIVE)
def test_precision_recall_ids_allowed_for_live_classes(doc_class):
    assert "pipeline.extraction.field_micro_precision" in _CLASS_METRIC_IDS[doc_class]
    assert "pipeline.extraction.field_micro_recall" in _CLASS_METRIC_IDS[doc_class]


def test_registry_applies_every_suite_metric_to_its_agent():
    reg = get_registry()
    gaps = []
    for name in list_suites():
        suite = get_suite(name)
        for metric in suite.metric_names():
            if not reg.get(metric).applies_to(suite.profile.name):
                gaps.append((suite.profile.name, metric))
    assert gaps == []


def test_specialist_grid_markdown_shows_unproven():
    md = build_grid_report(
        documents=[{"experiment": "e1", "specialist": "contract", "status": "unscorable"}],
        experiments=[{"name": "e1"}],
    )
    assert "unproven" in md


def test_scoring_doc_field_tables_match_default_field_types():
    import re
    from pathlib import Path

    from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES

    text = (Path(__file__).resolve().parents[1] / "docs" / "SCORING.md").read_text(
        encoding="utf-8"
    )
    documented = {}
    for m in re.finditer(
        r"### `([a-z_]+)` \((\d+) fields\)\n\n\| Field \| Type \|\n\| --- \| --- \|\n"
        r"((?:\|[^\n]*\|\n)+)",
        text,
    ):
        rows = dict(re.findall(r"\| `([^`]+)` \| `([^`]+)` \|", m.group(3)))
        assert int(m.group(2)) == len(rows), m.group(1)
        documented[m.group(1)] = rows
    assert documented == {k: dict(v) for k, v in DEFAULT_FIELD_TYPES.items()}


# ---- adversarial-review follow-ups ----------------------------------------


def _insurance_full():
    from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES

    full = {k: None for k in DEFAULT_FIELD_TYPES["insurance_claim"]}
    full.update(GT)
    return full


@pytest.mark.parametrize("pred", [[None], ["garbage"], []])
def test_missing_batch_predictions_count_as_misses(pred):
    full = _insurance_full()
    out = get_suite(INSURANCE).score([GT, GT], [full, *pred])
    assert len(out["extraction"]) == 2
    assert out["extraction_recall"] == 0.5
    assert out["quality_mean"] == 0.5
    assert out["n_missing_predictions"] == (1 if not pred else 0)


def test_empty_prediction_list_scores_every_row_as_unfilled():
    out = get_suite(INSURANCE).score([GT, GT], [])
    assert out["n_scored"] == 2
    assert out["n_missing_predictions"] == 2
    assert out["extraction_recall"] == 0.0
    assert out["schema_promotion_gate"]["passes"] is False


def test_whole_batch_json_string_is_parsed():
    import json

    full = _insurance_full()
    out = get_suite(INSURANCE).score([GT, GT], json.dumps([full, full]))
    assert out["extraction_recall"] == 1.0
    assert out["parse_ok"] == 1.0


def test_gt_less_batch_rows_feed_no_content_extras():
    from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES

    keys = list(DEFAULT_FIELD_TYPES["correspondence"])[:2]
    gold = {**{k: "AB123" for k in keys}, "content_topic": "billing",
            "sentiment_label": "neutral"}
    other = {**gold, "content_topic": "legal", "sentiment_label": "negative"}
    out = get_suite("correspondence_specialist").score(
        [gold, {"foo": "bar"}], [gold, other]
    )
    assert out["n_unscorable"] == 1
    assert out["n_topic"] == 1 and out["content_topic_accuracy"] == 1.0
    assert out["n_sentiment"] == 1 and out["sentiment_accuracy"] == 1.0


def test_stamp_provenance_keeps_draw_seed_zero():
    from llm_dojo_scoring.scorecard_honesty import stamp_provenance

    assert stamp_provenance(draw_seed=0)["provenance"]["draw_seed"] == 0
    out = get_suite(INSURANCE).score_document(GT, _insurance_full(), draw_seed=0)
    assert out["provenance"]["draw_seed"] == 0


def test_mixed_cost_basis_refused_without_cost_block():
    with pytest.raises(ProvenanceExportError, match="cost_basis mismatch"):
        validate_comparison_provenance(
            {**_FULL, "cost_basis": "token_price_estimate"},
            {**_FULL, "cost_basis": "busy_window"},
        )


def test_vary_accepts_a_bare_key_name():
    api = {**_FULL, "serving_kind": "api"}
    validate_comparison_provenance(_FULL, api, vary="serving_kind")


def test_empty_batch_quality_is_unproven():
    from llm_dojo_scoring.scorecard_honesty import aggregate_quality_honest

    assert aggregate_quality_honest([])["export_verdict"] == "unproven"


def test_serving_run_inputs_keep_their_metric_id():
    from llm_dojo_scoring.serving import normalize_serving_record

    left = normalize_serving_record(_leg("vllm", metric_id="pipeline.extraction.overall"))
    right = normalize_serving_record(
        _leg("openrouter", metric_id="cuad.clause_presence.micro_f1")
    )
    assert left.metric_id == "pipeline.extraction.overall"
    out = compare_serving(left, right)
    assert out["incomparable_reason"] == "metric_id_mismatch"
    mixed = compare_serving(
        [left, _leg("vllm")], _leg("openrouter", metric_id="pipeline.extraction.overall")
    )
    assert mixed["incomparable_reason"] == "metric_id_mixed"
    assert "mixes metric_ids" in mixed["markdown"]


def test_no_metric_ids_on_either_leg_is_flagged_unverified():
    out = compare_serving(_leg("vllm"), _leg("openrouter"))
    assert not out.get("incomparable")
    assert out["metric_id_unverified"] is True


def test_leg_pooling_different_datasets_is_identity_mixed():
    from llm_dojo_scoring.serving import emit_serving_scorecard

    mid = "pipeline.extraction.overall"
    local = [
        _leg("vllm", dataset_revision="rA", metric_id=mid),
        _leg("vllm", dataset_revision="rB", metric_id=mid),
    ]
    api = _leg("openrouter", dataset_revision="rA", metric_id=mid)
    out = compare_serving(local, api)
    assert out["incomparable_reason"] == "identity_mixed"
    assert out["local"]["identity_conflict"] == ["dataset_revision"]
    assert out["quality"]["delta_local_minus_api"] is None
    with pytest.raises(ProvenanceExportError, match="dataset_revision"):
        emit_serving_scorecard(out, emitter=Emitter(sinks=[]))
    with pytest.raises(ProvenanceExportError, match="pools runs"):
        compare_serving(local, api, require_provenance={"local": {}, "api": {}})


def test_emit_drops_a_quality_metric_id_stamp_and_none_values():
    from llm_dojo_scoring.serving import emit_serving_scorecard

    cmp = compare_serving(
        _leg("vllm", model="qwen3:8b", prompt_version="p1", dataset_revision="r1"),
        _leg("openrouter", model="qwen/qwen3.7-flash", prompt_version="p1",
             dataset_revision="r1"),
    )
    stamp = {"metric_id": "pipeline.extraction.overall", "dataset_revision": None}
    card = emit_serving_scorecard(
        cmp, emitter=Emitter(sinks=[]), provenance={"local": stamp, "api": stamp}
    )
    assert card["dashboard"]["ttft_seconds"]["local"] == pytest.approx(0.2)


def test_grid_score_level_unscorable_wins_over_run_status():
    rows = specialist_grid_rows(
        documents=[
            {"experiment": "e1", "specialist": "contract", "status": "completed",
             "scores": {"status": "unscorable"}, "score": 0.0},
            {"experiment": "e1", "specialist": "contract", "status": "Unscorable"},
        ],
        experiments=[{"name": "e1"}],
    )
    assert rows[0]["n_unscorable"] == 2


def test_archive_accepts_a_canonical_id_as_method():
    block = score_archive_block(
        "insurance_claim", dict(GT), dict(GT), method="pipeline.extraction.overall"
    )
    assert block["provenance"]["metric_id"] == "pipeline.extraction.overall"
