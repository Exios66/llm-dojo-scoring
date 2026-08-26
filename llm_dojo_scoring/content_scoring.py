"""Enron topic/sentiment and MAUD per-question extraction scorers.

These are the type-specific content evaluators that sit *alongside* typed
extraction (sender/recipient/…, ContractExtraction fields). They consume
corpus differentiators, not specialist extraction-schema fields:

- correspondence: ``content_topic`` (11 Enron topics) and ``sentiment_label``
  (negative / neutral / positive)
- merger_agreement: ``maud_clause_labels`` (22 Hub question keys → answer +
  category), or the specialist ``maud_clauses`` ``'<Question>: <Answer>'`` list

All functions are deterministic pure functions over ``(predicted, expected)``
pairs so offline rescoring and live Langfuse scoring never disagree.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .classification import ERROR_PREFIX, confusion_matrix, top_confusions
from .config import MAUD_CONSIDERATION_ALIASES, MAUD_CONSIDERATION_TYPES
from .corpus import (
    CORRESPONDENCE_SENTIMENT_LABELS,
    CORRESPONDENCE_TOPICS,
    MAUD_CLAUSE_CATEGORIES,
    MAUD_QUESTION_KEYS,
)
from .tasks import normalize_maud_consideration

__all__ = [
    "CORRESPONDENCE_CONTENT_KEYS",
    "MAUD_LABEL_KEY",
    "normalize_content_topic",
    "normalize_sentiment_label",
    "normalize_maud_question_key",
    "normalize_maud_category",
    "normalize_maud_answer",
    "parse_maud_labels",
    "peel_non_extraction_fields",
    "score_content_topic",
    "score_sentiment",
    "score_correspondence_content",
    "score_maud_extraction",
]

#: GT differentiator keys that are not CorrespondenceExtraction fields.
CORRESPONDENCE_CONTENT_KEYS: frozenset[str] = frozenset(
    {
        "content_topic",
        "topic_evidence",
        "sentiment_label",
        "sentiment_score",
        "sentiment_evidence",
        "label_evidence",
    }
)

#: Corpus JSON of {question: {answer, category, ...}} — not an extraction field.
MAUD_LABEL_KEY = "maud_clause_labels"

#: Keys stripped from extraction dicts before :func:`score_extraction`.
NON_EXTRACTION_KEYS: frozenset[str] = CORRESPONDENCE_CONTENT_KEYS | {MAUD_LABEL_KEY}

_ALIAS_RE = re.compile(r"[^a-z0-9]+")

_SENTIMENT_ALIASES: dict[str, str] = {
    "pos": "positive",
    "positive": "positive",
    "plus": "positive",
    "neg": "negative",
    "negative": "negative",
    "minus": "negative",
    "neu": "neutral",
    "neutral": "neutral",
    "mixed": "neutral",
}

_YES_NO = {
    "yes": "yes", "y": "yes", "true": "yes", "1": "yes",
    "no": "no", "n": "no", "false": "no", "0": "no",
}


def _fold(value: Any) -> str:
    return _ALIAS_RE.sub(" ", str(value or "").strip().lower()).strip()


def _fold_key(value: Any) -> str:
    return _fold(value).replace(" ", "_")


def normalize_content_topic(value: Any) -> str:
    """Coerce a raw Enron topic into a canonical ``CORRESPONDENCE_TOPICS`` key."""
    if value is None or str(value).strip() == "":
        return ""
    folded = _fold_key(value)
    for topic in CORRESPONDENCE_TOPICS:
        if topic == folded or _fold(topic) == _fold(value):
            return topic
    return folded


def normalize_sentiment_label(value: Any) -> str:
    """Coerce a raw sentiment into ``negative`` / ``neutral`` / ``positive``."""
    if value is None or str(value).strip() == "":
        return ""
    folded = _fold(value)
    if folded in _SENTIMENT_ALIASES:
        return _SENTIMENT_ALIASES[folded]
    if folded in CORRESPONDENCE_SENTIMENT_LABELS:
        return folded
    return folded


def normalize_maud_question_key(value: Any) -> str:
    """Map a raw question string onto a Hub ``MAUD_QUESTION_KEYS`` entry."""
    folded = _fold(value)
    if not folded:
        return ""
    for key in MAUD_QUESTION_KEYS:
        if _fold(key) == folded:
            return key
    return str(value).strip()


def normalize_maud_category(value: Any) -> str:
    """Map a raw category onto ``MAUD_CLAUSE_CATEGORIES`` when recognised."""
    folded = _fold(value)
    if not folded:
        return ""
    for cat in MAUD_CLAUSE_CATEGORIES:
        if _fold(cat) == folded:
            return cat
    return folded.replace(" ", "_") if folded else ""


def normalize_maud_answer(question: str, value: Any) -> str:
    """Task-aware answer fold: consideration type, yes/no, otherwise folded text."""
    if value is None:
        return ""
    key = normalize_maud_question_key(question)
    if key == "Type of Consideration":
        return normalize_maud_consideration(value)
    folded = _fold(value)
    if folded in _YES_NO:
        return _YES_NO[folded]
    return folded


def is_valid_maud_answer(question: str, value: Any) -> bool:
    """True when the predicted answer is in the question's known class set."""
    if value is None or str(value).strip() == "":
        return False
    key = normalize_maud_question_key(question)
    folded = _fold(value)
    if key == "Type of Consideration":
        if folded in MAUD_CONSIDERATION_ALIASES:
            return True
        return any(_fold(t) == folded for t in MAUD_CONSIDERATION_TYPES)
    if folded in _YES_NO:
        return True
    return bool(folded)


def _macro_f1(expected: list[str], predicted: list[str]) -> float:
    """Unweighted mean F1 over labels that appear in *expected* (empty → 0)."""
    labels = sorted({e for e in expected if e})
    if not labels:
        return 0.0
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for e, p in zip(expected, predicted) if e == label and p == label)
        fp = sum(1 for e, p in zip(expected, predicted) if e != label and p == label)
        fn = sum(1 for e, p in zip(expected, predicted) if e == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1s.append(
            2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        )
    return round(sum(f1s) / len(f1s), 4)


def _label_content_score(
    task: str,
    expected: Iterable,
    predicted: Iterable,
    *,
    normalize,
) -> dict:
    pairs = []
    for e, p in zip(expected, predicted):
        if str(p).startswith(ERROR_PREFIX):
            pairs.append((normalize(e), ERROR_PREFIX.strip().lower()))
            continue
        pairs.append((normalize(e), normalize(p)))
    exp = [e for e, _ in pairs]
    pred = [p for _, p in pairs]
    n = len(pairs)
    exact = round(sum(1.0 if e == p else 0.0 for e, p in pairs) / n, 4) if n else 0.0
    per_class: dict[str, dict] = {}
    for e, p in pairs:
        bucket = per_class.setdefault(e, {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += int(e == p)
    for bucket in per_class.values():
        bucket["accuracy"] = (
            round(bucket["correct"] / bucket["n"], 4) if bucket["n"] else 0.0
        )
    matrix, labels = confusion_matrix(exp, pred)
    return {
        "task": task,
        "kind": task,
        "exact_match": exact,
        "accuracy": exact,
        "f1_macro": _macro_f1(exp, pred),
        "per_class": per_class,
        "confusion": {"matrix": matrix, "labels": labels},
        "top_confusions": top_confusions(matrix, labels),
        "n": n,
    }


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def score_content_topic(expected: Iterable, predicted: Iterable) -> dict:
    """Enron ``content_topic`` accuracy / macro-F1 over the 11 canonical topics."""
    result = _label_content_score(
        "enron_topic", expected, predicted, normalize=normalize_content_topic
    )
    result["content_topic_accuracy"] = result["accuracy"]
    result["content_topic_f1_macro"] = result["f1_macro"]
    return result


def score_sentiment(expected: Iterable, predicted: Iterable) -> dict:
    """Enron ``sentiment_label`` accuracy / macro-F1 over negative/neutral/positive."""
    result = _label_content_score(
        "enron_sentiment", expected, predicted, normalize=normalize_sentiment_label
    )
    result["sentiment_accuracy"] = result["accuracy"]
    result["sentiment_f1_macro"] = result["f1_macro"]
    return result


def score_correspondence_content(
    *,
    expected_topic: Any = None,
    predicted_topic: Any = None,
    expected_sentiment: Any = None,
    predicted_sentiment: Any = None,
) -> dict:
    """Combined Enron topic + sentiment score dict (omits sides that are absent)."""
    out: dict[str, Any] = {"task": "enron_content", "kind": "enron_content"}
    if expected_topic is not None and predicted_topic is not None:
        topic = score_content_topic(_as_list(expected_topic), _as_list(predicted_topic))
        out["topic"] = topic
        out["content_topic_accuracy"] = topic["content_topic_accuracy"]
        out["content_topic_f1_macro"] = topic["content_topic_f1_macro"]
        out["n_topic"] = topic["n"]
    if expected_sentiment is not None and predicted_sentiment is not None:
        sent = score_sentiment(
            _as_list(expected_sentiment), _as_list(predicted_sentiment)
        )
        out["sentiment"] = sent
        out["sentiment_accuracy"] = sent["sentiment_accuracy"]
        out["sentiment_f1_macro"] = sent["sentiment_f1_macro"]
        out["n_sentiment"] = sent["n"]
    return out


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _record_from_value(value: Any) -> dict[str, str]:
    """Normalize one question's payload to ``{answer, category}``."""
    if isinstance(value, dict):
        answer = value.get("answer")
        if answer is None:
            answer = value.get("value") or value.get("label") or ""
        category = value.get("category") or ""
        return {"answer": str(answer), "category": str(category)}
    return {"answer": "" if value is None else str(value), "category": ""}


def _parse_span(span: str) -> tuple[str, str] | None:
    """Split ``'<Question>: <Answer>'`` preferring the longest Hub key prefix."""
    text = str(span).strip()
    if not text:
        return None
    for key in sorted(MAUD_QUESTION_KEYS, key=len, reverse=True):
        prefix = key + ":"
        if text.lower().startswith(prefix.lower()):
            return key, text[len(prefix):].strip()
    if ":" in text:
        question, answer = text.split(":", 1)
        return question.strip(), answer.strip()
    return None


def parse_maud_labels(value: Any) -> dict[str, dict[str, str]]:
    """Coerce corpus JSON, specialist spans, or a question→answer map.

    Returns ``{canonical_question: {"answer": str, "category": str}}``.
    """
    value = _maybe_json(value)
    if value is None:
        return {}
    if isinstance(value, dict):
        out: dict[str, dict[str, str]] = {}
        for raw_key, raw_val in value.items():
            key = normalize_maud_question_key(raw_key)
            if not key:
                continue
            rec = _record_from_value(raw_val)
            rec["category"] = normalize_maud_category(rec["category"]) if rec["category"] else ""
            out[key] = rec
        return out
    if isinstance(value, (list, tuple)):
        out = {}
        for item in value:
            if isinstance(item, dict) and ("question" in item or "key" in item):
                key = normalize_maud_question_key(item.get("question") or item.get("key"))
                rec = _record_from_value(item)
                rec["category"] = (
                    normalize_maud_category(rec["category"]) if rec["category"] else ""
                )
                if key:
                    out[key] = rec
                continue
            parsed = _parse_span(item)
            if parsed is None:
                continue
            question, answer = parsed
            key = normalize_maud_question_key(question)
            if key:
                out[key] = {"answer": answer, "category": ""}
        return out
    parsed = _parse_span(str(value))
    if parsed is None:
        return {}
    question, answer = parsed
    key = normalize_maud_question_key(question)
    return {key: {"answer": answer, "category": ""}} if key else {}


def _documents(expected: Any, predicted: Any) -> list[tuple[Any, Any]]:
    """Yield (expected, predicted) per-document pairs.

    A list of dicts is a batch. A list of strings is one document's spans.
    """
    exp = _maybe_json(expected)
    pred = _maybe_json(predicted)
    exp_batch = isinstance(exp, list) and exp and isinstance(exp[0], dict)
    pred_batch = isinstance(pred, list) and pred and isinstance(pred[0], dict)
    if exp_batch or pred_batch:
        exp_list = exp if isinstance(exp, list) else [exp]
        pred_list = pred if isinstance(pred, list) else [pred] * len(exp_list)
        return list(zip(exp_list, pred_list))
    return [(exp, pred)]


def score_maud_extraction(expected: Any, predicted: Any) -> dict:
    """Per-question MAUD extraction over the 22 Hub keys.

    Headlines:

    - ``maud_question_accuracy`` — micro exact-answer match over expected questions
    - ``maud_question_macro_accuracy`` — unweighted mean of per-question accuracy
    - ``maud_clause_presence`` — share of expected questions present in the prediction
    - ``maud_valid_class_rate`` — share of predicted answers in the question's class set
    - ``maud_category_accuracy`` — category match when both sides have a category
    """
    docs = _documents(expected, predicted)
    question_stats: dict[str, dict[str, int]] = {
        key: {"n": 0, "exact": 0, "present": 0, "valid": 0, "category_n": 0, "category_ok": 0}
        for key in MAUD_QUESTION_KEYS
    }
    extra_questions: dict[str, dict[str, int]] = {}
    n_expected = 0
    n_exact = 0
    n_present = 0
    n_valid = 0
    n_category = 0
    n_category_ok = 0
    per_doc: list[dict] = []

    for exp_raw, pred_raw in docs:
        exp_labels = parse_maud_labels(exp_raw)
        pred_labels = parse_maud_labels(pred_raw)
        doc_n = 0
        doc_exact = 0
        doc_present = 0
        for question, rec in exp_labels.items():
            stats = question_stats.get(question)
            if stats is None:
                stats = extra_questions.setdefault(
                    question,
                    {"n": 0, "exact": 0, "present": 0, "valid": 0, "category_n": 0, "category_ok": 0},
                )
            stats["n"] += 1
            n_expected += 1
            doc_n += 1
            pred_rec = pred_labels.get(question)
            present = pred_rec is not None
            if present:
                stats["present"] += 1
                n_present += 1
                doc_present += 1
                pred_answer = pred_rec["answer"]
                if is_valid_maud_answer(question, pred_answer):
                    stats["valid"] += 1
                    n_valid += 1
            else:
                pred_answer = ""
            exp_answer = normalize_maud_answer(question, rec["answer"])
            got_answer = normalize_maud_answer(question, pred_answer) if present else ""
            if present and exp_answer == got_answer:
                stats["exact"] += 1
                n_exact += 1
                doc_exact += 1
            exp_cat = rec.get("category") or ""
            pred_cat = (pred_rec or {}).get("category") or ""
            if exp_cat:
                stats["category_n"] += 1
                n_category += 1
                if pred_cat and normalize_maud_category(pred_cat) == exp_cat:
                    stats["category_ok"] += 1
                    n_category_ok += 1
        per_doc.append({
            "n_questions": doc_n,
            "exact": doc_exact,
            "present": doc_present,
            "accuracy": round(doc_exact / doc_n, 4) if doc_n else 0.0,
            "presence": round(doc_present / doc_n, 4) if doc_n else 0.0,
        })

    per_question: dict[str, dict] = {}
    question_accuracies: list[float] = []
    for question, stats in {**question_stats, **extra_questions}.items():
        if stats["n"] == 0:
            continue
        acc = round(stats["exact"] / stats["n"], 4)
        question_accuracies.append(acc)
        per_question[question] = {
            "n": stats["n"],
            "accuracy": acc,
            "presence": round(stats["present"] / stats["n"], 4),
            "valid_class_rate": (
                round(stats["valid"] / stats["present"], 4) if stats["present"] else 0.0
            ),
            "category_accuracy": (
                round(stats["category_ok"] / stats["category_n"], 4)
                if stats["category_n"] else None
            ),
        }

    return {
        "task": "maud_extraction",
        "kind": "maud_extraction",
        "maud_question_accuracy": round(n_exact / n_expected, 4) if n_expected else 0.0,
        "maud_question_macro_accuracy": (
            round(sum(question_accuracies) / len(question_accuracies), 4)
            if question_accuracies else 0.0
        ),
        "maud_clause_presence": round(n_present / n_expected, 4) if n_expected else 0.0,
        "maud_valid_class_rate": round(n_valid / n_present, 4) if n_present else 0.0,
        "maud_category_accuracy": (
            round(n_category_ok / n_category, 4) if n_category else 0.0
        ),
        "n_questions": n_expected,
        "n_documents": len(docs),
        "n_present": n_present,
        "per_question": per_question,
        "per_document": per_doc,
    }


def peel_non_extraction_fields(
    expected: dict, predicted: dict
) -> tuple[dict, dict, dict[str, Any]]:
    """Split correspondence/MAUD differentiators off an extraction pair.

    Returns ``(expected_fields, predicted_fields, payload)`` where *payload*
    holds optional ``content_topic``, ``sentiment_label``, and ``maud`` pairs
    used by the content scorers. Evidence columns are dropped, not scored.
    """
    exp_fields = {k: v for k, v in expected.items() if k not in NON_EXTRACTION_KEYS}
    pred_fields = {k: v for k, v in predicted.items() if k not in NON_EXTRACTION_KEYS}
    payload: dict[str, Any] = {}
    if "content_topic" in expected or "content_topic" in predicted:
        payload["content_topic"] = (
            expected.get("content_topic"),
            predicted.get("content_topic"),
        )
    if "sentiment_label" in expected or "sentiment_label" in predicted:
        payload["sentiment_label"] = (
            expected.get("sentiment_label"),
            predicted.get("sentiment_label"),
        )
    exp_maud = expected.get(MAUD_LABEL_KEY)
    pred_maud = predicted.get(MAUD_LABEL_KEY)
    # ``maud_clauses`` is an extraction field; only use it as the prediction
    # (or expected) side when the corpus differentiator is present.
    if exp_maud is not None or pred_maud is not None:
        if exp_maud is None:
            exp_maud = expected.get("maud_clauses")
        if pred_maud is None:
            pred_maud = predicted.get("maud_clauses")
        payload["maud"] = (exp_maud, pred_maud)
    return exp_fields, pred_fields, payload
