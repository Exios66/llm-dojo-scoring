"""llm-dojo-scoring — dedicated scoring, error analysis, visualization, and
interpretation suite for LLM document pipelines.

Import into llm-entity-extraction / llm-mailroom to replace the project-local
scoring code (``src/field_scoring.py``, ``src/metrics.py``, ``src/bootstrap.py``,
``src/cost_models.py``, ``src/scorers.py``, ``src/experiment_log.py``,
``src/taxonomy.py``, ``agents/sorter_agent.py`` equivalence constants,
``scripts/reporting/export_experiment_results.py``) with one shared library.
"""

from __future__ import annotations

__version__ = "0.11.0"

from . import (
    bundles,
    doc_bundles,
    emitter,
    profiles,
    pruning,
    registry,
    corpus,
    mailroom,
    suites,
    asr,
    bootstrap,
    classification,
    claims_consistency,
    config,
    content_scoring,
    cost,
    diagnostics,
    equivalences,
    error_analysis,
    experiment,
    export,
    extraction_metrics,
    failure_modes,
    field_scoring,
    intake,
    io,
    interpret,
    langfuse_sync,
    phoenix_sync,
    prompts,
    report,
    tasks,
    visualize,
)

# Convenience re-exports (the most common entry points).
from .bootstrap import bootstrap_ci, delta_significance, wilson_ci
from .classification import (
    accuracy,
    binary_metrics,
    confusion_matrix,
    exact_match,
    fbeta,
    macro_accuracy,
    macro_prf,
    normalize_label,
    per_class_stats,
)
from .cost import estimate_cost, tokens_summary
from .equivalences import (
    equivalent_doc_subclasses,
    equivalent_subtypes,
    normalize_doc_subclass,
    normalize_subtype,
)
from .failure_modes import (
    classify_docclass_failure,
    classify_failure,
    per_subtype_accuracy,
    summarize_failures,
)
from .field_scoring import (
    EntityListScore,
    ExtractionScoreResult,
    score_extraction,
    score_field,
    score_entity_list,
)
from .extraction_metrics import (
    extraction_binary_metrics,
    mean_entity_list_f1,
    merge_extraction_counts,
)
from .claims_consistency import (
    amount_exactness,
    determination_consistency,
    score_claims_extras,
)
from .config import (
    Settings,
    clear_settings_cache,
    configure,
    get_settings,
    load_settings,
)
from .tasks import (
    chained_composite,
    chained_summary,
    court_opinion_score,
    legalbench_score,
    maud_docclass_score,
    maud_extraction_score,
    maud_question_score,
    multiclass_score,
    normalize_task_answer,
    score_task,
    task_kind,
)
from .asr import (
    character_error_rate,
    score_transcription,
    word_error_rate,
)
from .content_scoring import (
    score_content_topic,
    score_correspondence_content,
    score_maud_extraction,
    score_sentiment,
)
from .intake import (
    apply_intake,
    deterministic_normalize,
    looks_messy,
    score_intake,
)
from .bundles import BUILTIN_BUNDLES, Bundle, bundle_metric_names, get_bundle, validate_bundle
from .doc_bundles import (
    DOC_TYPES,
    DOC_TYPE_BUNDLES,
    get_doc_bundle,
    list_doc_types,
    validate_doc_bundle,
)
from .emitter import (
    Emitter,
    get_emitter,
    LangfuseSink,
    LocalManifestSink,
    reset_default_emitter,
    ScoreRecord,
)
from .profiles import AgentProfile, get_profile, list_profiles, load_profiles
from .pruning import (
    DEFAULT_DASHBOARD_TIER,
    dashboard_metrics,
    headline_metrics,
    prune_metrics,
    prune_records,
)
from .corpus import (
    CORPUS_DOC_TYPES,
    DOC_TYPE_SUBCLASSES,
    normalize_corpus_subclass,
    suite_schema,
)
from .mailroom import (
    EXTRACT_CLASS_ALIASES,
    LIVE_DOC_TYPES,
    LIVE_SPECIALISTS,
    NODE_OBSERVATION_TYPES,
    PIPELINE_TRACE,
    align_doc_type,
    langfuse_score_name,
    observation_type_for,
    resolve_extract_class,
    score_aligned_classification,
)
from .suites import (
    DEFAULT_FIELD_TYPES,
    DEFAULT_SUITES,
    DOC_TYPE_ALIASES,
    SPECIALIST_DOC_TYPES,
    ScoringSuite,
    get_suite,
    list_suites,
    score_suite,
    suite_for_doc_type,
)
from .registry import (
    ALLOWED_GROUND_TRUTH,
    clear_registry_cache,
    get_registry,
    load_registry,
    MetricDef,
    MetricTier,
    Registry,
)
from .prompts import PromptRecord, get_prompt, list_prompts

__all__ = [
    "__version__",
    "bootstrap", "classification", "claims_consistency", "config", "content_scoring", "cost", "diagnostics",
    "equivalences", "error_analysis", "experiment", "export", "extraction_metrics", "failure_modes",
    "field_scoring", "io", "interpret", "langfuse_sync", "phoenix_sync",
    "report", "asr", "corpus", "intake", "mailroom", "prompts", "suites", "tasks", "visualize",
    "bootstrap_ci", "delta_significance", "wilson_ci",
    "accuracy", "binary_metrics", "confusion_matrix", "exact_match",
    "fbeta", "macro_accuracy", "macro_prf", "normalize_label", "per_class_stats",
    "estimate_cost", "tokens_summary",
    "equivalent_doc_subclasses", "equivalent_subtypes",
    "normalize_doc_subclass", "normalize_subtype",
    "classify_docclass_failure", "classify_failure", "per_subtype_accuracy",
    "summarize_failures",
    "EntityListScore", "ExtractionScoreResult", "score_extraction",
    "score_field", "score_entity_list",
    "extraction_binary_metrics", "mean_entity_list_f1", "merge_extraction_counts",
    "amount_exactness", "determination_consistency", "score_claims_extras",
    "Settings", "clear_settings_cache", "configure", "get_settings",
    "load_settings",
    "chained_composite", "chained_summary", "court_opinion_score",
    "legalbench_score", "maud_docclass_score", "maud_extraction_score",
    "maud_question_score",
    "multiclass_score", "normalize_task_answer", "score_task", "task_kind",
    "BUILTIN_BUNDLES", "Bundle", "bundle_metric_names", "get_bundle",
    "validate_bundle",
    "Emitter", "get_emitter", "LangfuseSink", "LocalManifestSink",
    "reset_default_emitter", "ScoreRecord",
    "AgentProfile", "get_profile", "list_profiles", "load_profiles",
    "DEFAULT_DASHBOARD_TIER", "dashboard_metrics", "headline_metrics",
    "prune_metrics", "prune_records",
    "clear_registry_cache", "get_registry", "load_registry", "MetricDef",
    "MetricTier", "Registry", "ALLOWED_GROUND_TRUTH",
    "PromptRecord", "get_prompt", "list_prompts",
    "ScoringSuite", "DEFAULT_SUITES", "DEFAULT_FIELD_TYPES",
    "DOC_TYPE_ALIASES", "SPECIALIST_DOC_TYPES",
    "get_suite", "list_suites", "score_suite", "suite_for_doc_type",
    "CORPUS_DOC_TYPES", "DOC_TYPE_SUBCLASSES",
    "normalize_corpus_subclass", "suite_schema",
    "LIVE_DOC_TYPES", "LIVE_SPECIALISTS", "PIPELINE_TRACE",
    "EXTRACT_CLASS_ALIASES", "NODE_OBSERVATION_TYPES",
    "align_doc_type", "langfuse_score_name", "observation_type_for",
    "resolve_extract_class", "score_aligned_classification",
    "word_error_rate", "character_error_rate", "score_transcription",
    "score_content_topic", "score_sentiment",
    "score_correspondence_content", "score_maud_extraction",
    "apply_intake", "deterministic_normalize", "looks_messy", "score_intake",
]