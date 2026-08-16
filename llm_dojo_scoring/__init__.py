"""llm-dojo-scoring — dedicated scoring, error analysis, visualization, and
interpretation suite for LLM document pipelines.

Import into llm-entity-extraction / llm-mailroom to replace the project-local
scoring code (``src/field_scoring.py``, ``src/metrics.py``, ``src/bootstrap.py``,
``src/cost_models.py``, ``src/scorers.py``, ``src/experiment_log.py``,
``src/taxonomy.py``, ``agents/sorter_agent.py`` equivalence constants,
``scripts/reporting/export_experiment_results.py``) with one shared library.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import (
    bootstrap,
    classification,
    config,
    cost,
    diagnostics,
    equivalences,
    error_analysis,
    experiment,
    export,
    failure_modes,
    field_scoring,
    io,
    interpret,
    report,
    visualize,
)

# Convenience re-exports (the most common entry points).
from .bootstrap import bootstrap_ci, delta_significance, wilson_ci
from .classification import (
    accuracy,
    binary_metrics,
    confusion_matrix,
    exact_match,
    macro_accuracy,
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
from .config import (
    Settings,
    clear_settings_cache,
    configure,
    get_settings,
    load_settings,
)

__all__ = [
    "__version__",
    "bootstrap", "classification", "config", "cost", "diagnostics",
    "equivalences", "error_analysis", "experiment", "export", "failure_modes",
    "field_scoring", "io", "interpret", "report", "visualize",
    "bootstrap_ci", "delta_significance", "wilson_ci",
    "accuracy", "binary_metrics", "confusion_matrix", "exact_match",
    "macro_accuracy", "normalize_label", "per_class_stats",
    "estimate_cost", "tokens_summary",
    "equivalent_doc_subclasses", "equivalent_subtypes",
    "normalize_doc_subclass", "normalize_subtype",
    "classify_docclass_failure", "classify_failure", "per_subtype_accuracy",
    "summarize_failures",
    "EntityListScore", "ExtractionScoreResult", "score_extraction",
    "score_field", "score_entity_list",
    "Settings", "clear_settings_cache", "configure", "get_settings",
    "load_settings",
]