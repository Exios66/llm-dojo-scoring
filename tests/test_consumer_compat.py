"""Consumer-compat — APIs required by mailroom / entity-extraction / sandbox.

Network-free. Pins the import surface those repos call so a dojo release
cannot drop a name they already depend on. When a consumer adds an import,
extend this list in the same PR that documents the pin bump.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import llm_dojo_scoring as dojo
from llm_dojo_scoring import load_registry
from llm_dojo_scoring.config import TASK_KINDS
from llm_dojo_scoring.metrics.registry import MetricTier


_CONSUMER_SURFACE_PATH = Path(__file__).resolve().parent / "fixtures" / "consumer_surface.json"


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
    """Require a numeric package version at least as new as the consumer baseline."""
    parts = dojo.__version__.split(".")
    assert len(parts) >= 2
    assert tuple(int(p) for p in parts[:2]) >= (0, 12)


def test_top_level_consumer_exports_present():
    """Preserve every top-level symbol imported by downstream consumers."""
    missing = [name for name in _TOP_LEVEL if not hasattr(dojo, name)]
    assert not missing, f"missing top-level exports: {missing}"


def test_module_attrs_used_by_dependents():
    """Preserve module-level attributes referenced by dependent applications."""
    for mod_name, attrs in _MODULE_ATTRS.items():
        mod = importlib.import_module(f"llm_dojo_scoring.{mod_name}")
        missing = [a for a in attrs if not hasattr(mod, a)]
        assert not missing, f"llm_dojo_scoring.{mod_name} missing {missing}"


def test_mailroom_score_names_in_registry():
    """Require all mailroom score names to resolve in the metric registry."""
    reg = load_registry()
    missing = [n for n in _MAILROOM_SCORE_NAMES if n not in reg.metrics]
    assert not missing, f"registry missing mailroom score names: {missing}"


def test_mailroom_t0_t1_have_citation_and_ground_truth():
    """Require citations and declared ground-truth policies for core mailroom metrics."""
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
    """Preserve serving comparison tables, scorecards, and costs for consumers."""
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


def test_release_version_is_current():
    """Pin the package version to the expected compatibility release."""
    assert dojo.__version__ == "0.27.2"


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
    """Resolve all top-level and module-level imports used by mailroom."""
    missing = [name for name in _MAILROOM_TOP_LEVEL if not hasattr(dojo, name)]
    assert not missing, f"missing mailroom top-level imports: {missing}"
    for mod_name, attrs in _MAILROOM_MODULE_ATTRS.items():
        mod = importlib.import_module(f"llm_dojo_scoring.{mod_name}")
        gone = [a for a in attrs if not hasattr(mod, a)]
        assert not gone, f"llm_dojo_scoring.{mod_name} missing {gone}"


def test_readme_release_pins_match_version():
    # Release commits bump the README badge and install pins with the version
    # (as v0.19.1 did); a stale pin sends new consumers to the old release.
    """Keep README release references aligned with the package version."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    pins = set(re.findall(r"(?:release-|releases/tag/|\.git@|\.\.\.@)v(\d+\.\d+\.\d+)", readme))
    assert pins == {dojo.__version__}, pins


def test_mailroom_relations_matcher_methods_exist():
    # relations.py still calls these until it moves to embed_texts.
    """Preserve private embedding methods still called by mailroom relations."""
    from llm_dojo_scoring.scoring.field_scoring import _EmbeddingMatcher

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
    from llm_dojo_scoring.analysis.serving import compare_serving

    def rec(**kw):
        """Build a serving record with dataset provenance and caller-supplied overrides."""
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


# ---------------------------------------------------------------------------
# Pinned consumer-surface manifest (#84)
# ---------------------------------------------------------------------------


def _consumer_surface() -> dict:
    """Load the pinned downstream import/dispatch manifest.

    Regenerate with ``uv run python scripts/audit_consumer_surface.py --write``.
    The test only reads the fixture, so it never needs the consumer checkouts.
    """
    return json.loads(_CONSUMER_SURFACE_PATH.read_text(encoding="utf-8"))


def _iter_consumer_sites(surface: dict):
    """Yield every consumer site recorded in the manifest."""
    for entry in surface["top_level"].values():
        yield from entry["consumers"]
    for entry in surface["modules"].values():
        for spec in entry["attrs"].values():
            yield from spec["consumers"]
    for section in surface["dispatch"].values():
        for sites in section["literals"].values():
            yield from sites
        yield from section["dynamic"]
    for patch in surface["patches"]:
        yield {key: patch[key] for key in ("repo", "file", "line")}
    for sites in surface["scores"]["visualizer_reads"].values():
        yield from sites


def _defining_module(defined_in: str):
    """Import a recorded defining module; ``__init__`` is the package itself
    (importing ``llm_dojo_scoring.__init__`` would load a second copy)."""
    if defined_in == "__init__":
        return dojo
    return importlib.import_module(f"llm_dojo_scoring.{defined_in}")


def test_pinned_consumer_surface_imports_resolve():
    """Every recorded top-level name and module attr still imports from its path."""
    surface = _consumer_surface()
    assert surface["schema_version"] == 1
    assert surface["top_level"] and surface["modules"], "manifest pins no consumer surface"
    failures: list[str] = []

    for name, entry in surface["top_level"].items():
        if entry["kind"] == "module":
            try:
                importlib.import_module(f"llm_dojo_scoring.{name}")
            except Exception as exc:  # pragma: no cover - failure detail path
                failures.append(f"llm_dojo_scoring.{name}: {type(exc).__name__}: {exc}")
            continue
        if not hasattr(dojo, name):
            failures.append(f"from llm_dojo_scoring import {name}")
            continue
        defined_in = entry.get("defined_in")
        if defined_in:
            defining = _defining_module(defined_in)
            if not hasattr(defining, name):
                failures.append(f"llm_dojo_scoring.{defined_in}.{name}")
            elif getattr(defining, name) is not getattr(dojo, name):
                failures.append(f"llm_dojo_scoring.{name} is not {defined_in}.{name}")

    for module_path, entry in surface["modules"].items():
        try:
            module = importlib.import_module(f"llm_dojo_scoring.{module_path}")
        except Exception as exc:  # pragma: no cover - failure detail path
            failures.append(f"llm_dojo_scoring.{module_path}: {type(exc).__name__}: {exc}")
            continue
        for attr, spec in entry["attrs"].items():
            if not hasattr(module, attr):
                failures.append(f"llm_dojo_scoring.{module_path}.{attr}")
                continue
            defined_in = spec.get("defined_in")
            if defined_in:
                defining = _defining_module(defined_in)
                if not hasattr(defining, attr):
                    failures.append(f"llm_dojo_scoring.{defined_in}.{attr}")
                elif getattr(defining, attr) is not getattr(module, attr):
                    failures.append(
                        f"llm_dojo_scoring.{module_path}.{attr} is not {defined_in}.{attr}"
                    )

    assert not failures, "consumer surface missing:\n" + "\n".join(failures)


def _dispatch_covers(section: dict, value: str) -> bool:
    """True when a dispatch value is literal, supported, or documented dynamic."""
    if value in section["literals"] or value in section["supported"]:
        return True
    return any(item.get("value") == value for item in section["dynamic"])


def test_pinned_dispatch_surface_covers_task_and_suite_vocabulary():
    """Every task kind and live suite is represented in the pinned dispatch section."""
    dispatch = _consumer_surface()["dispatch"]

    missing_tasks = [key for key in TASK_KINDS if not _dispatch_covers(dispatch["score_task"], key)]
    assert not missing_tasks, f"score_task dispatch missing task kinds: {missing_tasks}"

    live_suites = dojo.list_suites(live_only=True)
    missing_suites = [
        name for name in live_suites if not _dispatch_covers(dispatch["get_suite"], name)
    ]
    assert not missing_suites, f"get_suite dispatch missing live suites: {missing_suites}"


def test_pinned_langfuse_score_names_resolve():
    """Aliases and visualizer score reads stay resolvable in the registry."""
    scores = _consumer_surface()["scores"]
    registry = load_registry()
    names = set(scores["registry_ids"]) | set(scores["visualizer_reads"])
    for canonical, wire in scores["aliases"].items():
        names.update((canonical, wire))
    missing = sorted(name for name in names if name not in registry.metrics)
    assert not missing, f"pinned Langfuse score names missing from registry: {missing}"


def test_pinned_langfuse_alias_mapping_matches_emitter():
    """The pinned canonical → wire alias map is exactly what the emitter uses."""
    from llm_dojo_scoring.pipeline.mailroom import LANGFUSE_SCORE_NAME_ALIASES

    assert dict(_consumer_surface()["scores"]["aliases"]) == dict(LANGFUSE_SCORE_NAME_ALIASES)


def test_consumer_surface_sites_are_repo_relative():
    """Manifest consumer sites never embed absolute checkout paths."""
    surface = _consumer_surface()
    absolute = [
        site for site in _iter_consumer_sites(surface) if Path(site["file"]).is_absolute()
    ]
    assert not absolute, f"absolute consumer paths in fixture: {absolute}"


def test_pinned_legacy_module_paths_still_import():
    """A module pinned as reached through a legacy flat path still imports there.

    The manifest canonicalizes ``llm_dojo_scoring.pilot_labels`` to
    ``pipeline.pilot_labels`` and keeps only a ``legacy`` flag, so the flat
    path is recovered from ``LEGACY_MODULES`` and imported directly.
    """
    from llm_dojo_scoring._layout import LEGACY_MODULES

    surface = _consumer_surface()
    flat_by_canonical: dict[str, list[str]] = {}
    for flat, canonical in LEGACY_MODULES.items():
        flat_by_canonical.setdefault(canonical, []).append(flat)
    legacy_entries = {path: entry for path, entry in surface["modules"].items() if entry["legacy"]}
    assert legacy_entries, "manifest pins no legacy module path"
    failures: list[str] = []
    for canonical, entry in legacy_entries.items():
        flats = flat_by_canonical.get(canonical)
        if not flats:
            failures.append(f"{canonical}: pinned as legacy but has no flat alias")
            continue
        target = importlib.import_module(f"llm_dojo_scoring.{canonical}")
        for flat in flats:
            try:
                module = importlib.import_module(f"llm_dojo_scoring.{flat}")
            except Exception as exc:  # pragma: no cover - failure detail path
                failures.append(f"llm_dojo_scoring.{flat}: {type(exc).__name__}: {exc}")
                continue
            if module is not target:
                failures.append(f"llm_dojo_scoring.{flat} is not llm_dojo_scoring.{canonical}")
            failures.extend(
                f"llm_dojo_scoring.{flat}.{attr}"
                for attr in entry["attrs"]
                if not hasattr(module, attr)
            )
    assert not failures, "legacy consumer paths broken:\n" + "\n".join(failures)


def test_pinned_dispatch_literals_still_resolve():
    """Every literal a consumer passes to a dispatcher is still accepted by it."""
    dispatch = _consumer_surface()["dispatch"]
    failures: list[str] = []
    for value in dispatch["get_suite"]["literals"]:
        try:
            dojo.get_suite(value)
        except Exception as exc:  # pragma: no cover - failure detail path
            failures.append(f"get_suite({value!r}): {type(exc).__name__}: {exc}")
    for value in dispatch["suite_for_doc_type"]["literals"]:
        try:
            suite = dojo.suite_for_doc_type(value)
        except Exception as exc:  # pragma: no cover - failure detail path
            failures.append(f"suite_for_doc_type({value!r}): {type(exc).__name__}: {exc}")
            continue
        if suite.doc_type != value:
            failures.append(f"suite_for_doc_type({value!r}) returned doc_type {suite.doc_type!r}")
    for value in dispatch["score_task"]["literals"]:
        if value not in TASK_KINDS:
            failures.append(f"score_task({value!r}): not a task kind")
    assert not failures, "pinned dispatch inputs no longer resolve:\n" + "\n".join(failures)


def test_pinned_contract_suite_alias_resolves_to_the_contract_suite():
    """``get_suite("contract")`` (pinned from llm-mailroom) stays the contract suite."""
    assert "contract" in _consumer_surface()["dispatch"]["get_suite"]["literals"]
    suite = dojo.get_suite("contract")
    assert suite.doc_type == "contract"
    assert suite is dojo.suite_for_doc_type("contract") or suite.name == dojo.suite_for_doc_type(
        "contract"
    ).name


_CONTRACT_SURFACE_PATH = Path(__file__).resolve().parent / "fixtures" / "contract_surface.json"


def test_unified_audit_row_contract_surface():
    """The 0.27.0 names llm-mailroom (M6/M14/M15) and the sandbox (S1) build against keep their shape.

    ``consumer_surface.json`` is a scan of what consumers import today, so it cannot pin
    these until they adopt them (then regenerate it with
    ``scripts/audit_consumer_surface.py --write``). Until then this fixture pins them.
    """
    import inspect

    import llm_dojo_scoring
    from llm_dojo_scoring.pipeline.archive import ARCHIVE_SCORING_V027_KEYS
    from llm_dojo_scoring.scoring.doc_scorers import DOC_SCORERS

    contract = json.loads(_CONTRACT_SURFACE_PATH.read_text())
    for qualname, signature in contract["names"].items():
        name = qualname.split(":")[1]
        assert name in llm_dojo_scoring.__all__, name
        assert str(inspect.signature(getattr(llm_dojo_scoring, name))) == signature, name
    assert sorted(ARCHIVE_SCORING_V027_KEYS) == contract["archive_scoring_v027_keys"]
    assert sorted(DOC_SCORERS) == contract["doc_scorers"]
