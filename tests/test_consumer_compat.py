"""Consumer-compat — APIs required by mailroom / entity-extraction / sandbox.

Network-free. Pins the import surface those repos call so a dojo release
cannot drop a name they already depend on. When a consumer adds an import,
extend this list in the same PR that documents the pin bump.
"""

from __future__ import annotations

import importlib

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
