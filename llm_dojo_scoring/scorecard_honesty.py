"""v0.18 scorecard honesty — fail-closed GT, metric identity, provenance, completion.

Live-run calibration for issues Exios66/llm-dojo-scoring #16–#22 (hub #233).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from statistics import fmean
from typing import Any, Mapping, Sequence

from . import __version__
from .gt_metadata import is_empty_value

__all__ = [
    "SCORER_VERSION",
    "PROVENANCE_KEYS",
    "COST_BASIS_VALUES",
    "IncomparableMetricsError",
    "ProvenanceExportError",
    "metric_id_for",
    "metric_ids_for_class",
    "metric_id_allowed",
    "assert_comparable_metric_ids",
    "assess_extraction_gt",
    "unscorable_extraction_result",
    "aggregate_quality_honest",
    "export_quality_verdict",
    "score_format_layer",
    "check_schema_promotion_gate",
    "DEFAULT_INSURANCE_SCHEMA_GATE",
    "classify_extraction_failure",
    "detect_maud_gt_ambiguity",
    "score_empty_field_contract",
    "canonical_error_class",
    "summarize_run_completion",
    "aggregate_quality_itt",
    "stamp_provenance",
    "validate_comparison_provenance",
    "normalize_serving_kind_token",
]

SCORER_VERSION = __version__

PROVENANCE_KEYS: frozenset[str] = frozenset(
    {
        "dataset_revision",
        "split",
        "draw_seed",
        "prompt_id",
        "metric_id",
        "scorer_version",
        "serving_kind",
        "model_id",
    }
)

COST_BASIS_VALUES: frozenset[str] = frozenset({"busy_window", "billed_incl_cold"})

#: Canonical completion-error histogram keys (#21).
ERROR_CLASS_LENGTH_FINISH = "LengthFinish"
ERROR_CLASS_CONTEXT_OVERFLOW = "context_overflow"

_COLLAPSED_ANSWER_SPLIT = re.compile(r"\s+[\/|;]\s+")
_CAMEL_BOUNDARY = re.compile(r"([a-z])([A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")

# Registry metric name → canonical metric_id (issue #17).
_METRIC_ID_BY_NAME: dict[str, str] = {
    "extraction_overall_score": "pipeline.extraction.overall",
    "overall_score": "pipeline.extraction.overall",
    "extraction_f1": "pipeline.extraction.field_micro_f1",
    "extraction_f2": "pipeline.extraction.field_micro_f2",
    "extraction_precision": "pipeline.extraction.field_micro_precision",
    "extraction_recall": "pipeline.extraction.field_micro_recall",
    "extraction_category_presence": "cuad.clause_presence.micro_f1",
    "maud_question_accuracy": "maud.question.micro_accuracy",
    "maud_clause_presence": "maud.clause_presence.rate",
    "f1_macro": "pipeline.classification.f1_macro",
    "accuracy": "pipeline.classification.accuracy",
    "content_topic_accuracy": "pipeline.enron.topic_accuracy",
    "content_topic_f1_macro": "pipeline.enron.topic_f1_macro",
    "sentiment_accuracy": "pipeline.enron.sentiment_accuracy",
    "sentiment_f1_macro": "pipeline.enron.sentiment_f1_macro",
}

# Doc class / suite → allowed metric_ids for comparisons (documented in docs/METRIC_IDS.md).
# Covers all five live extract classes (#17): contract, merger_agreement,
# corporate_record, correspondence, insurance_claim.
_CLASS_METRIC_IDS: dict[str, tuple[str, ...]] = {
    "contract": (
        "pipeline.extraction.overall",
        "cuad.clause_presence.micro_f1",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
        "maud.question.micro_accuracy",
    ),
    "merger_agreement": (
        "pipeline.extraction.overall",
        "maud.question.micro_accuracy",
        "maud.clause_presence.rate",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
    ),
    "corporate_record": (
        "pipeline.extraction.overall",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
    ),
    "insurance_claim": (
        "pipeline.extraction.overall",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
    ),
    "correspondence": (
        "pipeline.extraction.overall",
        "pipeline.extraction.field_micro_f1",
        "pipeline.extraction.field_micro_f2",
        "pipeline.enron.topic_accuracy",
        "pipeline.enron.topic_f1_macro",
        "pipeline.enron.sentiment_accuracy",
        "pipeline.enron.sentiment_f1_macro",
    ),
}

DEFAULT_INSURANCE_SCHEMA_GATE = 0.90

_TRIAGE_GT_KEYS: frozenset[str] = frozenset(
    {
        "contract_subtype",
        "doc_type",
        "doc_subclass",
        "document_type",
        "confidence",
        "content_topic",
        "sentiment_label",
        "maud_clause_labels",
    }
)

_JSON_PROSE = re.compile(r"^\s*[\{\[]", re.MULTILINE)


class IncomparableMetricsError(ValueError):
    """Raised when two score legs use different metric_id values."""


class ProvenanceExportError(ValueError):
    """Raised when a comparison export lacks matching provenance stamps."""


@dataclass(frozen=True)
class GtAssessment:
    status: str  # "scored" | "unscorable"
    reason: str | None = None

    @property
    def scorable(self) -> bool:
        return self.status == "scored"


def metric_id_for(
    metric_name: str,
    *,
    doc_class: str | None = None,
    presence_mode: bool = False,
) -> str:
    if presence_mode or metric_name == "extraction_category_presence":
        return "cuad.clause_presence.micro_f1"
    if metric_name.startswith("maud_"):
        return _METRIC_ID_BY_NAME.get(metric_name, f"maud.{metric_name.removeprefix('maud_')}")
    mid = _METRIC_ID_BY_NAME.get(metric_name)
    if mid:
        return mid
    if doc_class:
        return f"pipeline.{doc_class}.{metric_name}"
    return f"pipeline.{metric_name}"


def metric_ids_for_class(doc_class: str) -> tuple[str, ...]:
    return _CLASS_METRIC_IDS.get(doc_class, ("pipeline.extraction.overall",))


def metric_id_allowed(metric_id: str, doc_class: str) -> bool:
    """True when ``metric_id`` is on the class's allowed comparison list (#17).

    Unknown classes allow only ``pipeline.extraction.overall``.
    """
    return metric_id in metric_ids_for_class(doc_class)


def assert_comparable_metric_ids(
    left: str | None,
    right: str | None,
    *,
    hard: bool = True,
) -> dict[str, Any]:
    """Refuse silent cross-metric comparisons (#17)."""
    if not left or not right:
        return {"comparable": True, "metric_id": left or right}
    if left == right:
        return {"comparable": True, "metric_id": left}
    detail = {
        "comparable": False,
        "incomparable": True,
        "incomparable_reason": "metric_id_mismatch",
        "left_metric_id": left,
        "right_metric_id": right,
    }
    if hard:
        raise IncomparableMetricsError(
            f"Cannot compare {left!r} with {right!r} — use the same metric_id on both legs."
        )
    return detail


def _is_empty_value(value: Any) -> bool:
    """Empty / null / stringified-empty (``"[]"``, ``"{}"``) Hub GT value."""
    return is_empty_value(value)


def _has_extractable_gt(
    expected: Mapping[str, Any],
    field_types: Mapping[str, str],
    scorable_gt_keys: Sequence[str] = (),
) -> bool:
    """Return whether GT has a nonempty extraction or suite-declared content value.

    Triage keys are ignored in ``field_types`` but may qualify when explicitly
    included in ``scorable_gt_keys``.
    """
    for key in field_types:
        if key in _TRIAGE_GT_KEYS:
            continue
        if not _is_empty_value(expected.get(key)):
            return True
    # Content/MAUD differentiators are scorable when the calling suite carries
    # the matching scorer (correspondence topic/sentiment, MAUD question
    # accuracy). They stay triage-only for suites without those scorers.
    for key in scorable_gt_keys:
        if not _is_empty_value(expected.get(key)):
            return True
    return False


def assess_extraction_gt(
    expected: Any,
    field_types: Mapping[str, str] | None,
    *,
    doc_class: str = "extraction",
    presence_expectations: Any = None,
    scorable_gt_keys: Sequence[str] | None = None,
) -> GtAssessment:
    """Fail-closed GT check (#16). Triage-only contracts GT is unscorable.

    ``scorable_gt_keys`` lets a suite declare content-only differentiators it
    can genuinely score (e.g. ``content_topic`` for correspondence,
    ``maud_clause_labels`` for the merger specialist). A GT row holding only
    those keys is scored on the content metric instead of being suppressed
    as ``gt_no_extractable_fields``. Contracts triage-only rows (subtype /
    doc_type labels with no scorer) remain unscorable.

    Return a ``GtAssessment`` with status and reason: missing or non-dict
    input is unscorable; an empty dict is scored with reason ``gt_empty``.
    For a nonempty dict, truthy ``presence_expectations`` permits scoring
    without extractable fields. This check does not compute any scores.
    """
    if expected is None:
        return GtAssessment("unscorable", "gt_missing")
    if not isinstance(expected, dict):
        return GtAssessment("unscorable", "gt_wrong_schema")
    if not expected:
        return GtAssessment("scored", "gt_empty")
    ftypes = dict(field_types or {})
    if presence_expectations:
        return GtAssessment("scored", None)
    if _has_extractable_gt(expected, ftypes, tuple(scorable_gt_keys or ())):
        return GtAssessment("scored", None)
    # Triage-only contract rows (subtype labels without schema fields).
    if doc_class in {"contract", "merger_agreement"} or any(
        k in expected for k in ("contract_subtype", "doc_type", "cuad_family")
    ):
        return GtAssessment("unscorable", "gt_no_extractable_fields")
    if not ftypes:
        return GtAssessment("unscorable", "gt_no_field_map")
    return GtAssessment("unscorable", "gt_no_extractable_fields")


def unscorable_extraction_result(
    assessment: GtAssessment,
    *,
    doc_class: str = "extraction",
    metric_id: str | None = None,
) -> dict[str, Any]:
    mid = metric_id or metric_id_for("extraction_overall_score", doc_class=doc_class)
    return {
        "status": "unscorable",
        "reason": assessment.reason,
        "metric_id": mid,
        "overall_score": None,
        "extraction_overall_score": None,
        "quality_mean": None,
        "n_scored": 0,
        "n_unscorable": 1,
        "export_verdict": export_quality_verdict(assessment),
    }


def aggregate_quality_honest(
    doc_results: Sequence[Mapping[str, Any]],
    *,
    score_key: str = "overall_score",
) -> dict[str, Any]:
    """Quality mean excludes unscorable rows — never folds them in as 0.0 (#16)."""
    scored_vals: list[float] = []
    n_unscorable = 0
    for row in doc_results:
        if row.get("status") == "unscorable":
            n_unscorable += 1
            continue
        val = row.get(score_key)
        if val is None and isinstance(row.get("extraction"), dict):
            val = row["extraction"].get("overall_score")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            scored_vals.append(float(val))
    n_scored = len(scored_vals)
    return {
        "n_scored": n_scored,
        "n_unscorable": n_unscorable,
        "quality_mean": round(fmean(scored_vals), 4) if scored_vals else None,
        "quality_population": "scored_only",
        "export_verdict": (
            "unproven" if n_scored == 0 and n_unscorable else "scored"
        ),
    }


def export_quality_verdict(assessment: GtAssessment | None) -> str:
    if assessment is None or assessment.scorable:
        return "scored"
    return "unproven"


def _try_parse_json(text: str) -> tuple[Any | None, bool]:
    stripped = text.strip()
    if not stripped:
        return None, False
    if not (_JSON_PROSE.match(stripped) or stripped.startswith("{")):
        return None, False
    try:
        return json.loads(stripped), True
    except json.JSONDecodeError:
        return None, False


def score_format_layer(
    *,
    predicted: Any = None,
    predicted_raw: str | None = None,
    required_keys: Sequence[str] | None = None,
) -> dict[str, float]:
    """Separate parse/schema from field extraction (#18, #20)."""
    parsed = predicted
    parse_ok = 1.0
    if predicted_raw is not None:
        parsed, ok = _try_parse_json(predicted_raw)
        parse_ok = 1.0 if ok else 0.0
    elif isinstance(predicted, str):
        parsed, ok = _try_parse_json(predicted)
        parse_ok = 1.0 if ok else 0.0
    elif predicted is None:
        parse_ok = 0.0
    schema_valid = parse_ok
    if parse_ok >= 1.0 and isinstance(parsed, dict) and required_keys:
        missing = [k for k in required_keys if k not in parsed]
        if missing:
            schema_valid = round(1.0 - len(missing) / max(len(required_keys), 1), 4)
    return {
        "parse_ok": float(parse_ok),
        "schema_valid": float(schema_valid),
        "schema_adherence": float(schema_valid),
    }


def check_schema_promotion_gate(
    schema_valid: float | None,
    *,
    threshold: float = DEFAULT_INSURANCE_SCHEMA_GATE,
) -> dict[str, Any]:
    if schema_valid is None:
        return {"passes": False, "reason": "schema_valid_missing", "threshold": threshold}
    ok = float(schema_valid) >= threshold
    return {
        "passes": ok,
        "threshold": threshold,
        "schema_valid": float(schema_valid),
        "reason": None if ok else "schema_valid_below_threshold",
    }


def classify_extraction_failure(
    *,
    parse_ok: float | None = None,
    schema_valid: float | None = None,
    overall_score: float | None = None,
) -> str:
    """Format vs capability tagging (#20)."""
    if parse_ok is not None and parse_ok < 1.0:
        return "format_parse"
    if schema_valid is not None and schema_valid < 1.0:
        return "format_schema"
    if overall_score is not None and overall_score < 1.0:
        return "capability_miss"
    return "ok"


def score_empty_field_contract(
    expected: Mapping[str, Any] | None,
    predicted: Mapping[str, Any] | None,
    *,
    field_types: Mapping[str, str] | None = None,
    penalize_spurious_empty: bool = True,
) -> dict[str, Any]:
    """Correctly-empty → credit 1.0; spurious fill on empty GT → penalty (#20).

    Empty expected fields never enter :func:`score_extraction` ``overall_score``
    (archive mean of nonempty expected fields). This helper scores them
    separately so incorrectly-empty vs spurious-fill is explicit.
    """
    from .field_scoring import NEVER_SCORED_FIELDS, RETIRED_PROMPT_KEYS

    expected = dict(expected or {})
    predicted = dict(predicted or {})
    types = dict(field_types or {})
    field_scores: dict[str, float] = {}
    n_correctly_empty = 0
    n_spurious_fill = 0
    for name, exp_val in expected.items():
        if name in NEVER_SCORED_FIELDS or (
            name in RETIRED_PROMPT_KEYS and name not in types
        ):
            continue
        if types and name not in types:
            continue
        if not _is_empty_value(exp_val):
            continue
        if _is_empty_value(predicted.get(name)):
            field_scores[name] = 1.0
            n_correctly_empty += 1
            continue
        score = 0.0 if penalize_spurious_empty else 1.0
        field_scores[name] = score
        if penalize_spurious_empty:
            n_spurious_fill += 1
    n_empty = len(field_scores)
    credit = round(fmean(field_scores.values()), 4) if field_scores else None
    return {
        "field_scores": field_scores,
        "n_empty_expected": n_empty,
        "n_correctly_empty": n_correctly_empty,
        "n_spurious_fill": n_spurious_fill,
        "empty_field_credit": credit,
        "penalize_spurious_empty": penalize_spurious_empty,
    }


def _split_collapsed_answers(value: Any) -> list[str]:
    """Expand list answers and ``Yes / Strict liability`` collapsed strings (#19)."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_split_collapsed_answers(item))
        return out
    text = str(value).strip()
    if not text:
        return []
    parts = [p.strip() for p in _COLLAPSED_ANSWER_SPLIT.split(text) if p.strip()]
    if len(parts) >= 2:
        return parts
    return [text]


def detect_maud_gt_ambiguity(exp_labels: Mapping[str, Any]) -> set[str]:
    """Collapsed / multi-answer MAUD GT → ambiguous keys (#19).

    Distinct sub-question keys are left alone. A Hub key that holds several
    answers (list, slash-collapsed string, or an explicit ``gt_ambiguous``
    flag) is marked unscorable instead of matching one arbitrary value.
    """
    ambiguous: set[str] = set()
    for question, raw in exp_labels.items():
        answers: list[str] = []
        if isinstance(raw, dict):
            if raw.get("ambiguous") or raw.get("gt_ambiguous"):
                ambiguous.add(question)
                continue
            answers = _split_collapsed_answers(raw.get("answer"))
        elif raw is not None:
            answers = _split_collapsed_answers(raw)
        normalized = {_fold(a) for a in answers if _fold(a)}
        if len(normalized) > 1:
            ambiguous.add(question)
    return ambiguous


def _fold(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def canonical_error_class(token: str | None) -> str:
    """Histogram bucket for completion errors (#21)."""
    if token is None or str(token).strip() == "":
        return "unknown_error"
    raw = str(token).strip()
    spaced = _CAMEL_BOUNDARY.sub(r"\1 \2", raw)
    spaced = _ACRONYM_BOUNDARY.sub(r"\1 \2", spaced)
    folded = re.sub(r"[^a-z0-9]+", " ", spaced.lower()).strip()
    compact = folded.replace(" ", "")
    if (
        folded in {"length", "max tokens"}
        or "length finish" in folded
        or "lengthfinish" in compact
    ):
        return ERROR_CLASS_LENGTH_FINISH
    if any(
        needle in folded
        for needle in ("context overflow", "context window", "context length")
    ) or "contextoverflow" in compact:
        return ERROR_CLASS_CONTEXT_OVERFLOW
    return raw


def summarize_run_completion(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """LengthFinish / error honesty (#21)."""
    n_attempted = len(records)
    error_hist: dict[str, int] = {}
    n_errored = 0
    for rec in records:
        err = rec.get("error") or rec.get("error_class") or rec.get("finish_reason")
        status = str(rec.get("status") or "")
        is_error = bool(rec.get("errored") or status.upper().startswith("ERROR"))
        if not is_error and err:
            token = str(err)
            is_error = token.lower() not in {
                "stop", "completed", "success", "none", "",
                "end_turn", "eos", "stop_sequence", "tool_calls",
            }
        if not is_error:
            continue
        n_errored += 1
        key = canonical_error_class(err or status or "unknown_error")
        error_hist[key] = error_hist.get(key, 0) + 1
    n_completed = max(n_attempted - n_errored, 0)
    rate = round(n_completed / n_attempted, 4) if n_attempted else None
    return {
        "n_attempted": n_attempted,
        "n_completed": n_completed,
        "n_errored": n_errored,
        "completion_rate": rate,
        "error_class_histogram": error_hist,
    }


def aggregate_quality_itt(
    doc_results: Sequence[Mapping[str, Any]],
    completion: Mapping[str, Any],
    *,
    score_key: str = "overall_score",
) -> dict[str, Any]:
    """ITT population: attempted docs, errors count as zero quality (#21)."""
    base = aggregate_quality_honest(doc_results, score_key=score_key)
    n_attempted = int(completion.get("n_attempted") or len(doc_results))
    mean = base.get("quality_mean")
    n_errored = int(completion.get("n_errored") or 0)
    itt_mean = None
    if n_attempted and mean is not None:
        scored_total = float(mean) * base["n_scored"]
        itt_mean = round((scored_total + 0.0 * n_errored) / n_attempted, 4)
    out = dict(base)
    out.update(
        {
            "quality_population_itt": "attempted_including_errors_as_zero",
            "quality_mean_itt": itt_mean,
            "quality_population_completed": "scored_only",
            "quality_mean_completed": mean,
        }
    )
    return out


def stamp_provenance(
    scorecard: Mapping[str, Any] | None = None,
    *,
    dataset_revision: str | None = None,
    split: str | None = None,
    draw_seed: str | None = None,
    prompt_id: str | None = None,
    metric_id: str | None = None,
    serving_kind: str | None = None,
    model_id: str | None = None,
    cost_basis: str | None = None,
) -> dict[str, Any]:
    """Mandatory provenance block (#22)."""
    base = dict(scorecard or {})
    prov = {
        "dataset_revision": dataset_revision or base.get("dataset_revision"),
        "split": split or base.get("split"),
        "draw_seed": draw_seed or base.get("draw_seed") or base.get("dataset_fingerprint"),
        "prompt_id": prompt_id or base.get("prompt_id") or base.get("prompt_version"),
        "metric_id": metric_id or base.get("metric_id"),
        "scorer_version": base.get("scorer_version") or SCORER_VERSION,
        "serving_kind": normalize_serving_kind_token(
            serving_kind or base.get("serving_kind")
        ),
        "model_id": model_id or base.get("model_id") or base.get("model"),
    }
    if cost_basis or base.get("cost_basis"):
        prov["cost_basis"] = cost_basis or base.get("cost_basis")
    base["provenance"] = prov
    return base


def validate_comparison_provenance(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    require_cost_basis_if_cost: bool = True,
) -> None:
    """Refuse exports when provenance keys differ (#22)."""
    lp = left.get("provenance") or left
    rp = right.get("provenance") or right
    missing: list[str] = []
    mismatched: list[str] = []
    for key in PROVENANCE_KEYS:
        lv, rv = lp.get(key), rp.get(key)
        if not lv or not rv:
            missing.append(key)
        elif lv != rv:
            mismatched.append(key)
    if missing or mismatched:
        raise ProvenanceExportError(
            f"Comparison export refused: missing={missing} mismatched={mismatched}"
        )
    if require_cost_basis_if_cost:
        if left.get("cost") or right.get("cost"):
            lb, rb = lp.get("cost_basis"), rp.get("cost_basis")
            if not lb or not rb:
                raise ProvenanceExportError(
                    "Comparison export refused: cost present but cost_basis missing"
                )
            if lb != rb:
                raise ProvenanceExportError(
                    f"Comparison export refused: cost_basis mismatch ({lb!r} vs {rb!r})"
                )


def normalize_serving_kind_token(kind: str | None) -> str | None:
    if not kind:
        return kind
    token = str(kind).strip().lower()
    if token in {"modal", "modal-vllm", "modal_vllm"}:
        return "modal"
    if token in {"local", "offline", "self-hosted", "on-prem"}:
        return "local"
    if token in {"api", "cloud", "hosted", "openrouter"}:
        return "api"
    return token
