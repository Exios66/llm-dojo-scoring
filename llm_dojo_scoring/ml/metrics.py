"""Score the trained intake classifier against dataset gold.

A record is one document::

    {"doc_type": gold class, "subclass": gold subclass (raw surface is fine),
     "pred_doc_type": ..., "pred_subclass": ...,
     "doc_type_confidence": 0..1, "subclass_confidence": 0..1,
     "fast_path": True when the model's answer was used without the LLM sorter}

A record without a gold ``doc_type`` is counted under ``n_unscored_by_reason`` and
never scored. Subclasses are compared after :func:`normalize_corpus_subclass` for the
gold class, so ``License_Agreements`` and ``license`` are the same answer. A subclass
is right only when the class is right too.

Fast-path risk is the error rate over the documents the model answered alone (class
or subclass wrong). ``selective_risk_upper`` is the Wilson upper bound of that rate:
the number a release gate should hold under its error budget, since a handful of
accepted documents says little about the true rate.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from ..analysis.bootstrap import wilson_ci
from ..analysis.calibration import expected_calibration_error
from ..schemas.corpus import normalize_corpus_subclass
from ..scoring.classification import macro_prf

__all__ = ["METRIC_IDS", "score_intake_model"]

#: Short metric name -> registered ``metric_id``.
METRIC_IDS: dict[str, str] = {
    "doc_type_accuracy": "ml.intake.doc_type_accuracy",
    "doc_type_macro_f1": "ml.intake.doc_type_macro_f1",
    "doc_type_ece": "ml.intake.doc_type_ece",
    "subclass_accuracy": "ml.intake.subclass_accuracy",
    "subclass_macro_f1": "ml.intake.subclass_macro_f1",
    "subclass_ece": "ml.intake.subclass_ece",
    "fast_path_coverage": "ml.intake.fast_path_coverage",
    "selective_risk": "ml.intake.selective_risk",
    "selective_risk_upper": "ml.intake.selective_risk_upper",
}


def _token(value: Any) -> str | None:
    """A stripped, lower-cased label, or None for blank / NaN-like values."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().lower()
    return None if text in {"", "nan", "none", "null"} else text


def _confidence(value: Any) -> float | None:
    """A finite confidence in [0, 1], else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _rate(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator`` rounded to six places, or None when empty."""
    return round(numerator / denominator, 6) if denominator else None


def score_intake_model(records: Iterable[Mapping[str, Any]], *, z: float = 1.96) -> dict[str, Any]:
    """Accuracy, macro F1 and ECE per head, plus fast-path coverage and risk.

    ``z`` sets the Wilson interval used for ``selective_risk_upper`` (1.96: 95%).
    """
    n = 0
    unscored: Counter[str] = Counter()
    class_gold: list[str] = []
    class_pred: list[str] = []
    class_pairs: list[tuple[float, bool]] = []
    sub_gold: list[str] = []
    sub_pred: list[str] = []
    sub_pairs: list[tuple[float, bool]] = []
    accepted = errors = 0
    for raw in records:
        n += 1
        gold = _token(raw.get("doc_type"))
        if gold is None:
            unscored["no_gold_doc_type"] += 1
            continue
        pred = _token(raw.get("pred_doc_type")) or ""
        class_ok = pred == gold
        class_gold.append(gold)
        class_pred.append(pred)
        confidence = _confidence(raw.get("doc_type_confidence"))
        if confidence is not None:
            class_pairs.append((confidence, class_ok))
        wrong = not class_ok
        gold_sub_raw = _token(raw.get("subclass"))
        if gold_sub_raw is not None:
            gold_sub = normalize_corpus_subclass(gold, gold_sub_raw)
            pred_sub_raw = _token(raw.get("pred_subclass"))
            pred_sub = normalize_corpus_subclass(gold, pred_sub_raw) if pred_sub_raw else ""
            sub_ok = class_ok and pred_sub == gold_sub
            sub_gold.append(f"{gold}/{gold_sub}")
            sub_pred.append(f"{pred}/{pred_sub}")
            sub_confidence = _confidence(raw.get("subclass_confidence"))
            if sub_confidence is not None:
                sub_pairs.append((sub_confidence, sub_ok))
            wrong = wrong or not sub_ok
        if raw.get("fast_path") is True:
            accepted += 1
            errors += int(wrong)
    scored = len(class_gold)
    risk = _rate(errors, accepted)
    interval = wilson_ci(errors / accepted, accepted, z) if accepted else None
    metrics = {
        "doc_type_accuracy": _rate(sum(g == p for g, p in zip(class_gold, class_pred)), scored),
        "doc_type_macro_f1": _macro_f1(class_gold, class_pred),
        "doc_type_ece": expected_calibration_error(class_pairs),
        "subclass_accuracy": _rate(sum(g == p for g, p in zip(sub_gold, sub_pred)), len(sub_gold)),
        "subclass_macro_f1": _macro_f1(sub_gold, sub_pred),
        "subclass_ece": expected_calibration_error(sub_pairs),
        "fast_path_coverage": _rate(accepted, scored),
        "selective_risk": risk,
        "selective_risk_upper": interval["hi"] if interval else None,
    }
    return {
        "n": n,
        "n_scored": scored,
        "n_unscored_by_reason": dict(unscored),
        "n_subclass_scored": len(sub_gold),
        "n_fast_path": accepted,
        "metrics": metrics,
        "provenance": {"metric_ids": dict(METRIC_IDS), "wilson_z": z},
    }


def _macro_f1(gold: list[str], pred: list[str]) -> float | None:
    """Macro F1 over the gold labels, or None with no rows."""
    if not gold:
        return None
    return round(float(macro_prf(gold, pred, normalize=False)["f1_macro"]), 6)
