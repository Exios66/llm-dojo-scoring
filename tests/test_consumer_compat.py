"""Consumer-compat — APIs required by mailroom / entity-extraction / sandbox.

Network-free. Pins the import surface those repos call so a dojo release
cannot drop a name they already depend on. When a consumer adds an import,
extend this list in the same PR that documents the pin bump.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import llm_dojo_scoring as dojo
from llm_dojo_scoring import load_registry
from llm_dojo_scoring.registry import MetricTier


# Top-level names imported by local-mailroom-sandbox + llm-mailroom tests.
_TOP_LEVEL = (
    "Emitter",
    "LangfuseSink",
    "LocalManifestSink",
    "ScoreRecord",
    "DEFAULT_FIELD_TYPES",
    "LEGACY_FULL_EXTRACTION_FIELD_TYPES",
    "accuracy",
    "bootstrap_ci",
    "classify_serving_kind",
    "compare_serving",
    "configure",
    "clear_settings_cache",
    "emit_serving_scorecard",
    "exact_match",
    "get_suite",
    "headline_metrics",
    "list_suites",
    "load_registry",
    "load_settings",
    "score_extraction",
    "score_archive_block",
    "format_audit_entry",
    "archivist_sign_off",
    "prepare_archivist_handoff",
    "capture_trace_knobs",
    "score_serving_run",
    "score_task",
    "split_local_api",
    "suite_for_doc_type",
)

# Module paths used via `from llm_dojo_scoring.<mod> import ...`
_MODULE_ATTRS: dict[str, tuple[str, ...]] = {
    "bootstrap": ("bootstrap_ci", "delta_significance", "wilson_ci"),
    "classification": (
        "accuracy",
        "binary_metrics",
        "confusion_matrix",
        "exact_match",
        "fbeta",
        "macro_accuracy",
        "normalize_label",
        "per_class_stats",
    ),
    "config": (
        "CONTRACT_SUBTYPES",
        "DOC_SUBCLASS_EQUIVALENCES",
        "PER_SUBTYPE",
    ),
    "content_scoring": ("peel_non_extraction_fields",),
    "cost": ("estimate_cost", "estimate_for_record", "price_for", "tokens_summary"),
    "diagnostics": ("extraction_diagnostics", "parse_duration_days"),
    "emitter": ("Emitter", "LangfuseSink", "LocalManifestSink", "ScoreRecord"),
    "equivalences": ("equivalent_subtypes", "normalize_subtype"),
    "experiment": (
        "append_experiment",
        "dotted_get",
        "git_snapshot",
        "load_records",
        "mean",
        "record_date",
        "utc_now",
    ),
    "export": ("extraction_columns", "sorter_columns", "write_codebook", "write_workbook"),
    "extraction_metrics": ("extraction_binary_metrics",),
    "archive": (
        "score_archive_block",
        "upsert_archive_scoring",
        "archive_entry_hash",
        "format_audit_entry",
        "archivist_sign_off",
        "prepare_archivist_handoff",
        "validate_audit_entry",
        "empty_audit_log_entry",
    ),
    "trace_knobs": (
        "capture_trace_knobs",
        "parse_confidence",
        "parse_reasoning",
        "confidence_calibration_error",
    ),
    "failure_modes": ("classify_failure",),
    "field_scoring": (
        "ExtractionScoreResult",
        "get_field_types",
        "get_settings",
        "score_category_presence",
        "score_entity_list",
        "score_extraction",
        "score_field",
    ),
    "intake": ("deterministic_normalize",),
    "mailroom": (
        "observation_type_for",
        "score_aligned_classification",
    ),
    "prompts": ("get_prompt", "list_prompts"),
    "pruning": ("dashboard_metrics", "headline_metrics"),
    "serving": (
        "CANONICAL_SERVING_KEYS",
        "compare_serving",
        "emit_serving_scorecard",
        "pair_comparable_runs",
        "serving_scorecard",
    ),
    "suites": (
        "DEFAULT_FIELD_TYPES",
        "LEGACY_FULL_EXTRACTION_FIELD_TYPES",
        "get_suite",
    ),
    "tasks": ("contracteval_metrics", "contracteval_score", "get_jaccard"),
}

# Mailroom SCORE_CONFIGS / suite extras that must resolve in the registry.
_MAILROOM_SCORE_NAMES = (
    "content_topic_accuracy",
    "content_topic_f1_macro",
    "sentiment_accuracy",
    "sentiment_f1_macro",
    "maud_question_accuracy",
    "maud_question_macro_accuracy",
    "maud_clause_presence",
    "maud_valid_class_rate",
    "maud_category_accuracy",
    "extraction_precision",
    "extraction_recall",
    "extraction_f1",
    "extraction_f2",
    "entity_list_f1",
    "determination_consistency",
    "amount_exactness",
    "intake_prep_completeness",
    "intake_changed_rate",
    "intake_messy_rate",
    "intake_hyphen_unwraps",
    "intake_collapsed_blanks",
    "ttft_seconds",
    "tokens_per_second",
    # #106 BERT fast path (mailroom-only; source null / ground_truth none)
    "bert_pass",
    "bert_sorter_agreement",
    "bert_fail_soft",
    "bert_elapsed_ms",
    "fast_path_est_cost_usd",
)


def test_package_version_is_semver_patch_or_newer():
    # Keep the consumer pin docs honest: published package version matches.
    parts = dojo.__version__.split(".")
    assert len(parts) >= 2
    assert tuple(int(p) for p in parts[:2]) >= (0, 12)


def test_top_level_consumer_exports_present():
    missing = [name for name in _TOP_LEVEL if not hasattr(dojo, name)]
    assert not missing, f"missing top-level exports: {missing}"


def test_module_attrs_used_by_dependents():
    for mod_name, attrs in _MODULE_ATTRS.items():
        mod = importlib.import_module(f"llm_dojo_scoring.{mod_name}")
        missing = [a for a in attrs if not hasattr(mod, a)]
        assert not missing, f"llm_dojo_scoring.{mod_name} missing {missing}"


def test_mailroom_score_names_in_registry():
    reg = load_registry()
    missing = [n for n in _MAILROOM_SCORE_NAMES if n not in reg.metrics]
    assert not missing, f"registry missing mailroom score names: {missing}"


def test_mailroom_t0_t1_have_citation_and_ground_truth():
    reg = load_registry()
    for name in _MAILROOM_SCORE_NAMES:
        m = reg.get(name)
        if m.tier > MetricTier.CORE:
            continue
        assert m.citation.strip(), name
        assert m.ground_truth in {
            "required",
            "optional",
            "structural",
            "none",
        }, (name, m.ground_truth)


def test_local_vs_api_surface_for_sandbox_and_mailroom():
    suite = dojo.get_suite("local_vs_api")
    assert suite.kind == "serving"
    out = dojo.compare_serving(
        [{"ttft_seconds": 0.5, "tokens_per_second": 100.0, "provider": "ollama"}],
        [{"ttft_seconds": 0.2, "tokens_per_second": 200.0, "provider": "openrouter"}],
    )
    assert "table" in out and "scorecard" in out and "cost" in out
    assert out["scorecard"]["agent"] == "local_vs_api"


def test_jellyfish_is_importable_core_dependency():
    """Mailroom ships jellyfish as a core dep; name scoring must not degrade."""
    import jellyfish

    assert jellyfish.jaro_winkler_similarity("Acme Corp", "Acme Corporation") > 0.8


def test_release_version_is_0_22_0():
    assert dojo.__version__ == "0.22.0"


# Every name llm-mailroom imports (src/ + notebooks/), per the sync plan's
# "Mailroom import surface" appendix, plus the v0.20.0 intents module.
_MAILROOM_TOP_LEVEL = (
    "get_suite",
    "list_suites",
    "load_registry",
    "get_field_types",
    "score_extraction",
    "ExtractionScoreResult",
    "warm_embedding_model",
    "score_category_presence",
    "normalize_text",
    "is_entity_list",
    "parse_date",
    "parse_money",
    "configure",
    "configure_from_taxonomy",
    # src/scripts/calibrate_field_scoring.py
    "EntityListScore",
    "get_ambiguous_band",
    # public replacement for relations.py's private matcher calls
    "embed_texts",
)

_MAILROOM_MODULE_ATTRS: dict[str, tuple[str, ...]] = {
    "field_scoring": (
        "_get_embedding",
        "embed_texts",
        # mailroom tests
        "FIELD_SCORERS",
        "field_is_ambiguous",
        "get_type_bands",
        "score_date_field",
        "score_free_text_field",
        "score_id_field",
        "score_money_field",
        "score_name_field",
    ),
    "scorecard_honesty": ("SCORER_VERSION",),
    "mailroom": ("score_aligned_classification",),
    "intake": (
        "looks_messy",
        "INTAKE_SPAN_KEYS",
        "INTAKE_SPAN",
        "INTAKE_LIVE_METHOD",
        "INTAKE_PREP_STEPS",
        "intake_span_output",
    ),
    "serving": ("compare_serving",),
    "registry": ("MetricTier",),
    "pruning": ("headline_metrics",),
    "prompts": ("get_prompt", "list_prompts"),
    "corpus": ("normalize_corpus_subclass", "DOC_TYPE_SUBCLASSES"),
    "content_scoring": ("peel_non_extraction_fields",),
    "archive": ("archive_entry_hash",),
    "intents": ("INTENT_LABELS", "INTENT_ALIASES", "INTENT_DESCRIPTIONS", "normalize_intent"),
}


def test_mailroom_import_surface_resolves():
    # Mailroom does `from llm_dojo_scoring import <name>`; a name that only
    # survives in a submodule would still break that import.
    missing = [name for name in _MAILROOM_TOP_LEVEL if not hasattr(dojo, name)]
    assert not missing, f"missing mailroom top-level imports: {missing}"
    for mod_name, attrs in _MAILROOM_MODULE_ATTRS.items():
        mod = importlib.import_module(f"llm_dojo_scoring.{mod_name}")
        gone = [a for a in attrs if not hasattr(mod, a)]
        assert not gone, f"llm_dojo_scoring.{mod_name} missing {gone}"


def test_readme_release_pins_match_version():
    # Release commits bump the README badge and install pins with the version
    # (as v0.19.1 did); a stale pin sends new consumers to the old release.
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    pins = set(re.findall(r"(?:release-|releases/tag/|\.git@|\.\.\.@)v(\d+\.\d+\.\d+)", readme))
    assert pins == {dojo.__version__}, pins


def test_mailroom_relations_matcher_methods_exist():
    # relations.py still calls these until it moves to embed_texts.
    from llm_dojo_scoring.field_scoring import _EmbeddingMatcher

    assert callable(getattr(_EmbeddingMatcher, "_embed", None))
    assert callable(getattr(_EmbeddingMatcher, "_load_local", None))


_MAILROOM_SCORE_DOCUMENT_KWARGS = dict(
    dataset_revision="46a4d3c2",
    split="test",
    draw_seed=42,
    prompt_id="insurance_claims_specialist_v1",
    model_id="Qwen/Qwen3-8B-AWQ",
    serving_kind="modal-vllm",
)


def test_mailroom_score_document_contract():
    """The payload keys mailroom reads from score_document (scores.py,
    run_hf_pilot.py) — scorable and unscorable rows."""
    from llm_dojo_scoring import ExtractionScoreResult, get_suite

    suite = get_suite("insurance_claims_specialist")
    gt = {"insurer": "Acme Mutual", "claim_number": "CLM-1"}
    out = suite.score_document(gt, dict(gt), **_MAILROOM_SCORE_DOCUMENT_KWARGS)
    assert isinstance(out["extraction"], ExtractionScoreResult)
    for key in ("metric_id", "parse_ok", "schema_adherence", "schema_valid"):
        assert key in out, key
    assert out["provenance"]["scorer_version"] == dojo.__version__
    assert out["provenance"]["dataset_revision"] == "46a4d3c2"
    assert out["provenance"]["metric_id"] == out["metric_id"]

    unscorable = suite.score_document(
        {"doc_subtype": "triage"}, dict(gt), **_MAILROOM_SCORE_DOCUMENT_KWARGS
    )
    assert unscorable["status"] == "unscorable"
    assert unscorable["reason"]
    assert unscorable["overall_score"] is None
    assert unscorable["provenance"]["dataset_revision"] == "46a4d3c2"


def test_sandbox_local_vs_api_emit_call_shape(tmp_path):
    """local-mailroom-sandbox: emit_local_vs_api_scorecard calls
    emit_serving_scorecard(comparison, run_id=..., emitter=Emitter(...)) on
    fixture records. With dataset_revision on the records (or passed as
    provenance) it must emit; price-table USD needs no hand-written basis."""
    from llm_dojo_scoring import Emitter, LocalManifestSink, emit_serving_scorecard
    from llm_dojo_scoring.serving import compare_serving

    def rec(**kw):
        base = {
            "prompt_version": "mailroom-default",
            "task": "sorter",
            "dataset_fingerprint": "fixture-serving-v0",
            "dataset_revision": "46a4d3c2",
            "ttft_seconds": 0.2,
            "e2e_latency_seconds": 1.0,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        base.update(kw)
        return base

    cmp = compare_serving(
        rec(provider="ollama", model="qwen3:8b", serving_kind="local"),
        rec(provider="openrouter", model="qwen/qwen3.7-flash"),
    )
    em = Emitter(sinks=[LocalManifestSink(tmp_path / "scores.jsonl")])
    emit_serving_scorecard(cmp, run_id="sand32", emitter=em)
    usd = [r for r in em._records if r.metric == "estimated_cost_usd"]
    assert usd and all(
        r.metadata["provenance"]["cost_basis"] == "token_price_estimate" for r in usd
    )
    assert {r.metadata["provenance"]["draw_seed"] for r in em._records} == {
        "fixture-serving-v0"
    }
