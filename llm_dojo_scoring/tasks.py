"""Task-aware scoring across the additional document hierarchy.

Issue #19 / KANBAN-047: the CUAD-focused scoring suite is generalized to
cover every task type the eval loop produces — **MAUD** (merger-agreement
doc-class + consideration-type subclass + per-question classification),
**LegalBench** (task-mode binary Yes/No), **chained sorter→extractor runs**
(composite sorter + extractor scoring), **multi classification** (macro/micro
per-class + confusion), and **court opinions** (court_opinion doc-class path).

All functions are deterministic pure functions over ``(predicted, expected)``
pairs so offline rescoring, manifest re-scoring, and live Langfuse/Braintrust
scoring never disagree. Failed rows (``ERROR_PREFIX`` predictions) count as
mismatches in the headline accuracy and are skipped by per-class/confusion
breakdowns — the same convention as :mod:`.classification`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .bootstrap import bootstrap_ci
from .classification import (
    ERROR_PREFIX,
    binary_metrics,
    confusion_matrix,
    macro_accuracy,
    normalize_label,
    top_confusions,
)
from .config import (
    LEGALBENCH_BINARY_LABELS,
    LEGALBENCH_YES_NO,
    MAUD_CONSIDERATION_ALIASES,
    MAUD_CONSIDERATION_EQUIVALENCES,
    MAUD_CONSIDERATION_TYPES,
    TASK_KINDS,
)
from .equivalences import equivalent_doc_subclasses, normalize_doc_subclass

_ALIAS_RE = re.compile(r"[^a-z0-9]+")


def _fold(value: Any) -> str:
    """Lowercase, non-alphanumerics -> single spaces (for fuzzy matching)."""
    return _ALIAS_RE.sub(" ", str(value).strip().lower()).strip()


def task_kind(task: str) -> str:
    """Resolve a task key to its scoring kind (unknown keys fall back to the
    task name itself → plain label classification)."""
    return TASK_KINDS.get(task, task)


def normalize_maud_consideration(value: Any) -> str:
    """Coerce a raw MAUD consideration answer into the canonical key.

    Handles the MAUD surface ("All Cash", "Mixed Cash & Stock", ...) and the
    docclass eval's canonical snake_case (``all_cash``, ...); unknown values
    degrade to ``other`` (the GT gap convention).
    """
    if value is None:
        return "other"
    folded = _fold(value)
    if folded in MAUD_CONSIDERATION_ALIASES:
        return MAUD_CONSIDERATION_ALIASES[folded]
    for key in MAUD_CONSIDERATION_TYPES:
        if _fold(key) == folded:
            return key
    return "other"


def normalize_legalbench(value: Any) -> str:
    """Coerce a raw LegalBench task answer to the canonical label set."""
    folded = _fold(value)
    for label in LEGALBENCH_BINARY_LABELS:
        if folded == label or folded in LEGALBENCH_YES_NO.get(label, set()):
            return label
    return folded


def normalize_task_answer(task: str, value: Any, valid=None) -> str:
    """Task-aware label normalization (subtype/doc_class go through the
    classification normalizer; MAUD and LegalBench use their own tables)."""
    if task in ("maud_docclass", "maud_question"):
        return normalize_maud_consideration(value)
    kind = task_kind(task)
    if kind == "docclass":
        if valid is not None:
            return normalize_doc_subclass(value, allowed=set(valid))
        return normalize_doc_subclass(value)
    if kind == "legalbench":
        return normalize_legalbench(value)
    return normalize_label(value, valid=valid)


def _per_class(expected: Iterable, predicted: Iterable) -> dict[str, dict]:
    """Per-expected-class exact-match stats over pre-normalized pairs.

    Failed rows (``ERROR_PREFIX`` predictions) are skipped, matching
    :func:`.classification.per_class_stats`.
    """
    by_class: dict[str, dict] = {}
    for e, p in zip(expected, predicted):
        if str(p).startswith(ERROR_PREFIX):
            continue
        bucket = by_class.setdefault(e, {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += int(p == e)
    for bucket in by_class.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 4) if bucket["n"] else 0.0
    return by_class


def _ci(per_row: list[float], *, seed: int, n_boot: int):
    return bootstrap_ci(per_row, seed=seed, n_boot=n_boot)


def _label_score(task: str, expected: list, predicted: list, *,
                 valid=None, seed: int, n_boot: int) -> dict:
    """Shared score dict for label-classification kinds (subtype, doc_class,
    multiclass, court_opinion, maud_question)."""
    norm = lambda v: normalize_task_answer(task, v, valid=valid)
    pairs = [(norm(e), norm(p)) for e, p in zip(expected, predicted)]
    exp = [e for e, _ in pairs]
    pred = [p for _, p in pairs]
    per_row = [1.0 if e == p else 0.0 for e, p in pairs]
    matrix, labels = confusion_matrix(exp, pred)
    return {
        "task": task,
        "kind": task_kind(task),
        "exact_match": round(sum(per_row) / len(per_row), 4) if per_row else 0.0,
        "exact_match_ci": _ci(per_row, seed=seed, n_boot=n_boot),
        "macro_accuracy": macro_accuracy(exp, pred),
        "per_class": _per_class(exp, pred),
        "confusion": {"matrix": matrix, "labels": labels},
        "top_confusions": top_confusions(matrix, labels),
        "n": len(per_row),
    }


def score_task(
    task: str,
    expected: list,
    predicted: list,
    *,
    valid=None,
    expected_subclass: list | None = None,
    predicted_subclass: list | None = None,
    seed: int = 42,
    n_boot: int = 2000,
) -> dict:
    """Score a task over paired per-document answers.

    Args:
        task: task key (subtype | doc_class | docclass | maud_docclass |
            maud_question | legalbench | multiclass | court_opinion).
        expected / predicted: parallel sequences of per-document answers.
        valid: optional valid-label table (regex patterns for
            classification kinds, or a key set for doc_subclass scoping).
        expected_subclass / predicted_subclass: the second-level doc_subclass
            dimension (consideration type) for ``docclass`` / ``maud_docclass``.
        seed / n_boot: bootstrap CI parameters.

    Returns a task-appropriate score dict (exact match, per-class, confusion,
    bootstrap CIs; doc_type + subclass for the hierarchical kinds). For
    ``chained`` runs use :func:`chained_composite` / :func:`chained_summary`.
    """
    kind = task_kind(task)

    if kind == "legalbench":
        norm = lambda v: normalize_task_answer(task, v)
        pairs = [(norm(e), norm(p)) for e, p in zip(expected, predicted)]
        exp = [e for e, _ in pairs]
        pred = [p for _, p in pairs]
        per_row = [1.0 if e == p else 0.0 for e, p in pairs]
        matrix, labels = confusion_matrix(exp, pred)
        positive = LEGALBENCH_BINARY_LABELS[0]
        return {
            "task": task,
            "kind": kind,
            "exact_match": round(sum(per_row) / len(per_row), 4) if per_row else 0.0,
            "exact_match_ci": _ci(per_row, seed=seed, n_boot=n_boot),
            "per_class": _per_class(exp, pred),
            "binary": binary_metrics(exp, pred, positive=positive),
            "confusion": {"matrix": matrix, "labels": labels},
            "top_confusions": top_confusions(matrix, labels),
            "n": len(per_row),
        }

    if kind == "docclass":
        norm_dt = lambda v: normalize_label(v)
        doc_exp = [norm_dt(e) for e in expected]
        doc_pred = [norm_dt(p) for p in predicted]
        doc_ok = [1.0 if e == p else 0.0 for e, p in zip(doc_exp, doc_pred)]
        result = {
            "task": task,
            "kind": kind,
            "doc_type_accuracy": round(sum(doc_ok) / len(doc_ok), 4) if doc_ok else 0.0,
            "doc_type_accuracy_ci": _ci(doc_ok, seed=seed, n_boot=n_boot),
            "per_class": _per_class(doc_exp, doc_pred),
            "n": len(doc_ok),
        }
        if expected_subclass is not None and predicted_subclass is not None:
            sub_ok = []
            sub_ok_equiv = []
            sub_exp_norm = []
            sub_pred_norm = []
            for e, p in zip(expected_subclass, predicted_subclass):
                en = normalize_maud_consideration(e)
                pn = normalize_maud_consideration(p)
                sub_exp_norm.append(en)
                sub_pred_norm.append(pn)
                sub_ok.append(1.0 if en == pn else 0.0)
                equiv = equivalent_doc_subclasses(en, pn, allowed=set(MAUD_CONSIDERATION_TYPES))
                sub_ok_equiv.append(1.0 if (en == pn or equiv) else 0.0)
            exact = [1.0 if (de == dp and se == sp)
                     else 0.0 for de, dp, se, sp in
                     zip(doc_exp, doc_pred, sub_exp_norm, sub_pred_norm)]
            result.update({
                "subclass_accuracy": round(sum(sub_ok) / len(sub_ok), 4) if sub_ok else 0.0,
                "subclass_accuracy_ci": _ci(sub_ok, seed=seed, n_boot=n_boot),
                "subclass_accuracy_equiv": round(sum(sub_ok_equiv) / len(sub_ok_equiv), 4) if sub_ok_equiv else 0.0,
                "exact_match": round(sum(exact) / len(exact), 4) if exact else 0.0,
                "exact_match_ci": _ci(exact, seed=seed, n_boot=n_boot),
                "per_subclass": _per_class(sub_exp_norm, sub_pred_norm),
                "n_subclass_scored": len(sub_ok),
            })
        return result

    if kind == "chained":
        raise ValueError(
            "chained runs are scored with chained_composite()/chained_summary() "
            "— score_task expects per-document (expected, predicted) pairs"
        )

    return _label_score(task, expected, predicted, valid=valid, seed=seed, n_boot=n_boot)


def multiclass_score(expected: list, predicted: list, *, valid=None,
                     seed: int = 42, n_boot: int = 2000) -> dict:
    """Multi-classification score (macro + micro per-class + confusion)."""
    result = _label_score("multiclass", expected, predicted, valid=valid,
                          seed=seed, n_boot=n_boot)
    result["micro_accuracy"] = result["exact_match"]
    return result


def court_opinion_score(expected: list, predicted: list, *, seed: int = 42,
                        n_boot: int = 2000) -> dict:
    """Court-opinion doc-class scoring (the court_opinion dimension)."""
    return _label_score("court_opinion", expected, predicted,
                        seed=seed, n_boot=n_boot)


def maud_docclass_score(expected_doc_type: list, predicted_doc_type: list,
                        expected_subclass: list, predicted_subclass: list,
                        *, seed: int = 42, n_boot: int = 2000) -> dict:
    """MAUD merger-agreement hierarchical score (doc_type + consideration)."""
    return score_task("maud_docclass", expected_doc_type, predicted_doc_type,
                      expected_subclass=expected_subclass,
                      predicted_subclass=predicted_subclass,
                      seed=seed, n_boot=n_boot)


def maud_question_score(expected: list, predicted: list, *,
                        seed: int = 42, n_boot: int = 2000) -> dict:
    """MAUD per-question classification score (exact match + per-class)."""
    return score_task("maud_question", expected, predicted,
                      seed=seed, n_boot=n_boot)


def legalbench_score(expected: list, predicted: list, *,
                     seed: int = 42, n_boot: int = 2000) -> dict:
    """LegalBench task-mode score (binary Yes/No + per-class + metrics)."""
    return score_task("legalbench", expected, predicted, seed=seed, n_boot=n_boot)


def chained_composite(sorter_score: float, extractor_score: float,
                      *, weights: tuple[float, float] = (0.25, 0.75)) -> float:
    """Combine the sorter classification score and the extractor composite
    into one chained run score.

    The extractor carries the document-level output the pipeline is ultimately
    judged on, so it dominates the default weighting (0.25 / 0.75)."""
    w_s, w_e = weights
    return round(w_s * float(sorter_score) + w_e * float(extractor_score), 4)


def chained_summary(
    sorter_exact: float, sorter_subtype: float,
    extractor_overall: float, extractor_presence: float,
    n: int,
    *,
    weights: tuple[float, float] = (0.25, 0.75),
) -> dict:
    """Record-shaped score dict for a chained sorter→extractor run.

    Mirrors the repo's chained-eval composite: the sorter's document-type
    exact match + subtype accuracy, the extractor's overall extraction score +
    field presence, and the weighted composite (default 0.25/0.75)."""
    return {
        "sorter": {
            "exact_match": round(float(sorter_exact), 4),
            "subtype_accuracy": round(float(sorter_subtype), 4),
        },
        "extractor": {
            "overall_extraction_score": round(float(extractor_overall), 4),
            "field_presence": round(float(extractor_presence), 4),
        },
        "composite": chained_composite(sorter_exact, extractor_overall, weights=weights),
        "weights": {"sorter": weights[0], "extractor": weights[1]},
        "n": n,
    }


__all__ = [
    "task_kind", "normalize_maud_consideration", "normalize_legalbench",
    "normalize_task_answer", "score_task", "multiclass_score",
    "court_opinion_score", "maud_docclass_score", "maud_question_score",
    "legalbench_score", "chained_composite", "chained_summary",
]