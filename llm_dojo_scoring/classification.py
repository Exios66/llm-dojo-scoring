"""Classification scorers: normalization, exact match, per-class stats,
confusion matrices, and binary metrics.

Ported from ``src/scorers.py`` (llm-entity-extraction) and generalized so the
valid-class table is configurable. All functions are deterministic pure
functions over ``(predicted, expected)`` pairs so Braintrust-scorer lookups,
local manifest scoring, and post-hoc analysis never disagree.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

ERROR_PREFIX = "ERROR: "  # task output sentinel for failed rows

# Default doc-class keys + regexes for label normalization (the
# llm-entity-extraction / llm-mailroom taxonomy).
_DEFAULT_CLASSES_RE: dict[str, re.Pattern[str]] = {
    "contract": re.compile(r"\bcontract\b"),
    "corporate_record": re.compile(r"\bcorporate[_ ]?record\b"),
    "due_diligence": re.compile(r"\bdue[_ ]?diligence\b"),
    "correspondence": re.compile(r"\bcorrespondence\b"),
    "compliance_filing": re.compile(r"\bcompliance[_ ]?filing\b"),
    "court_opinion": re.compile(r"\bcourt[_ ]?opinion\b"),
    "insurance_claim": re.compile(r"\binsurance[_ ]?claim\b"),
    "merger_agreement": re.compile(r"\bmerger[_ ]?agreement\b"),
}


def normalize_label(value, valid: dict[str, re.Pattern[str]] | None = None) -> str:
    """Coerce an LLM output into a class key (best effort)."""
    valid = valid or _DEFAULT_CLASSES_RE
    if value is None:
        return ""
    text = str(value).strip().lower()
    # Prefer a JSON object's doc_type field.
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            text = str(obj.get("doc_type") or text).lower()
        except json.JSONDecodeError:
            pass
    # Exact match.
    if text in valid:
        return text
    for cls, pattern in valid.items():
        if pattern.search(text):
            return cls
    return text.strip('"`*_ ')


def exact_match(output, expected) -> float:
    """Score 1.0 if the prediction matches the expected class, else 0.0."""
    return 1.0 if normalize_label(output) == normalize_label(expected) else 0.0


def failure(output, expected) -> float:
    """Score 1.0 for rows the model failed to classify (error sentinel)."""
    return 1.0 if str(output).startswith(ERROR_PREFIX) else 0.0


def accuracy(expected: list, predicted: list) -> float:
    """Overall exact-match accuracy over paired predictions."""
    if not expected:
        return 0.0
    hits = sum(1 for e, p in zip(expected, predicted)
               if normalize_label(p) == normalize_label(e))
    return round(hits / len(expected), 4)


def per_class_stats(expected: list, predicted: list) -> dict[str, dict]:
    """Aggregate exact-match accuracy per expected class.

    Returns ``{class: {"n": int, "correct": int, "accuracy": float}}``.
    Failed rows (``ERROR_PREFIX`` predictions) are skipped entirely.
    """
    by_class: dict[str, dict] = {}
    for e, p in zip(expected, predicted):
        cls = normalize_label(e)
        out = str(p)
        if out.startswith(ERROR_PREFIX):
            continue
        bucket = by_class.setdefault(cls, {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += int(normalize_label(out) == cls)
    for bucket in by_class.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 4) if bucket["n"] else 0.0
    return by_class


def macro_accuracy(expected: list, predicted: list) -> float:
    """Unweighted mean of per-class accuracies (ignores empty classes)."""
    stats = per_class_stats(expected, predicted)
    if not stats:
        return 0.0
    return round(sum(s["accuracy"] for s in stats.values()) / len(stats), 4)


def confusion_matrix(expected: list, predicted: list,
                     labels: list[str] | None = None) -> tuple[list[list[int]], list[str]]:
    """Expected x predicted counts.

    Rows are expected (ground-truth) classes, columns predicted classes, in
    ``labels`` order (default: sorted union of observed classes). Failed
    predictions (ERROR_PREFIX) are dropped.
    """
    pairs = [
        (normalize_label(e), normalize_label(p))
        for e, p in zip(expected, predicted)
        if not str(p).startswith(ERROR_PREFIX)
    ]
    if labels is None:
        labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for e, p in pairs:
        matrix[index[e]][index[p]] += 1
    return matrix, labels


def binary_metrics(expected: list, predicted: list, positive: str,
                   normalize: bool = True) -> dict:
    """Precision / recall / F1 for a one-vs-rest binary view.

    ``normalize=True`` runs labels through :func:`normalize_label` (exact
    class keys); ``normalize=False`` treats inputs as raw binary flags
    (True/False, 1/0, "yes"/"no").
    """
    def _flag(value):
        if not normalize:
            if isinstance(value, str):
                return value.strip().lower() in ("yes", "y", "true", "1", "1.0")
            return bool(value)
        return normalize_label(value) == positive

    tp = tn = fp = fn = 0
    for e, p in zip(expected, predicted):
        is_pos = _flag(e)
        pred_pos = _flag(p)
        if is_pos and pred_pos:
            tp += 1
        elif is_pos and not pred_pos:
            fn += 1
        elif not is_pos and pred_pos:
            fp += 1
        else:
            tn += 1
    precision = round(tp / (tp + fp), 4) if tp + fp else 0.0
    recall = round(tp / (tp + fn), 4) if tp + fn else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": round((tp + tn) / (tp + tn + fp + fn), 4) if tp + tn + fp + fn else 0.0,
    }


def confusion_accuracy(matrix: list[list[int]]) -> float:
    """Trace-over-total accuracy from a square confusion matrix."""
    total = sum(sum(row) for row in matrix)
    if not total:
        return 0.0
    trace = sum(matrix[i][i] for i in range(len(matrix)))
    return round(trace / total, 4)


def top_confusions(matrix: list[list[int]], labels: list[str],
                   k: int = 5) -> list[dict]:
    """The k most frequent off-diagonal (expected, predicted) pairs."""
    off = []
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            if i != j and count > 0:
                off.append({"expected": labels[i], "predicted": labels[j], "count": count})
    off.sort(key=lambda d: d["count"], reverse=True)
    return off[:k]


def class_distribution(labels: list) -> dict[str, int]:
    """Counts per normalized label (useful for support tables)."""
    return dict(Counter(normalize_label(x) for x in labels))


__all__ = [
    "ERROR_PREFIX", "normalize_label", "exact_match", "failure", "accuracy",
    "per_class_stats", "macro_accuracy", "confusion_matrix",
    "binary_metrics", "confusion_accuracy", "top_confusions",
    "class_distribution",
]
