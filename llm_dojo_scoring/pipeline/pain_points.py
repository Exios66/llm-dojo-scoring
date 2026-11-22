"""Pain-point composites: two penalty scores built around a client's stated operating costs.

A client's document-intelligence team said what hurts most in production: the volume of
documents a person has to review, errors, and misarchived documents. The composites turn a
pipeline run into two numbers on that scale, one for classification and one for entity
extraction. Each document earns **penalty points** from 0 (correct and complete) to 4 (sent
to a person when the pipeline could have finished it); **lower is better**. Profile
``amfam-v1`` (the American Family Insurance pain points) sets the default scale below.

This module is scorer-agnostic and record-based: it reads one :class:`PainPointDocument` per
document (the routing outcome plus the document's already-scored extraction row) and never
loads rows, runs a pipeline or calls a scorer. The consumer owns row loading and stage
naming; see ``docs/contracts/PAIN_POINT_SCORING.md``.

Classification (``pain_points_classification``), worst reason wins:

====  =====================  ==============================================================
 pts  reason                 when
====  =====================  ==============================================================
  4   unnecessary_review     routed to review although the expected stage is archived
  4   pipeline_failure       the document errored or ended in no final stage
  3   wrong_doc_type         archived under another class (a misarchive)
  2   missed_review          archived although the expected stage is review
  1   wrong_subtype          archived under the right class with the wrong subclass
  0   necessary_review       routed to review, and the expected stage is review
  0   correct                archived under the right class (and subclass, when labelled)
====  =====================  ==============================================================

Entity extraction (``pain_points_extraction``), over documents with field ground truth:

====  =====================  ==============================================================
 pts  reason                 when
====  =====================  ==============================================================
  4   unnecessary_review     as above: the extraction never had to reach a person
  4   pipeline_failure       as above
  3   fabricated             values were stated but none is supported by the truth (no
                             exact field, no near miss, at least one wrong or invented one)
  2   low_recall             under a third of the targeted entities reported correctly,
                             including an extraction that stated nothing
  1   partial                some targeted entities right, but not all, or extra values
                             were stated on fields the truth leaves empty
  0   necessary_review       as above: a person had to see it anyway
  0   complete               every targeted entity right and nothing invented
====  =====================  ==============================================================

Definitions, so a number can be traced back:

- *Targeted entities* are the expected fields with a value (the Dojo's ``tp + fn`` events);
  *reported correctly* is a field the Dojo scores 1.0 (``tp``). The share is ``tp / (tp + fn)``.
  The detailed suite path (corporate records, any row with a subclass) returns no ``tp`` /
  ``fn``; there the per-field ``n_value_correct`` / ``n_targeted`` (see
  :func:`field_value_outcomes`) are used, and without ``fp`` the documented-absence
  hallucinations (``n_hallucinated``) stand in for it.
- *Invented values* are the Dojo's false positives (``fp``) plus ``n_value_wrong`` (a value
  stated on a targeted field that scores under :data:`FABRICATION_MAX_FIELD_SCORE`). A value
  between that bar and 1.0 is a near miss (``n_value_partial``): wrong, but not invented.
- Clause-label rows (``scoring_method`` containing ``+maud`` or ``+cuad``) and rows with no
  counts at all use the row's ``overall_extraction_score`` as the share and are never called
  fabricated.
- *Unnecessary review* uses the document's ``expected_stage`` (default archived). Without
  expected stages every review counts as needless.

Documents without an expected class are left out of both composites, and documents without an
extraction row out of the extraction composite (``excluded``): a missing label is never scored
as correct.
"""

from __future__ import annotations

import math
import numbers
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from llm_dojo_scoring.analysis.bootstrap import bootstrap_ci
from llm_dojo_scoring.schemas.gt_metadata import is_empty_value

PROFILE = "amfam-v1"
CLASSIFICATION = "classification"
EXTRACTION = "extraction"

CLASSIFICATION_REASONS = (
    "unnecessary_review", "pipeline_failure", "wrong_doc_type", "missed_review", "wrong_subtype",
    "necessary_review", "correct",
)
EXTRACTION_REASONS = (
    "unnecessary_review", "pipeline_failure", "fabricated", "low_recall", "partial",
    "necessary_review", "complete",
)

#: A value stated on a targeted field that scores under this bar is counted as wrong
#: (``n_value_wrong``: unsupported by the truth); between it and 1.0 it is a near miss
#: (``n_value_partial``).
FABRICATION_MAX_FIELD_SCORE = 0.5

#: Stages that end a document; anything else (or an error) is a pipeline failure.
FINAL_STAGES = ("archived", "review")

#: Bootstrap defaults of :func:`breakdown` and :func:`compare` (same as ``bootstrap_ci``).
N_BOOT = 2000
SEED = 42

#: Bounds on every point value of a custom scale, so a mean stays finite and its 6-decimal
#: rounding never hides a penalty.
MAX_POINTS_BOUND = 1000.0
MIN_POINTS_BOUND = 0.001

#: The ``breakdown`` key that reads the document's expected class instead of ``groups``.
DOC_CLASS_KEY = "doc_class"
UNKNOWN = "unknown"


def _is_bool(value: Any) -> bool:
    """A Python or numpy boolean (``numpy.bool_`` is not a ``bool`` subclass)."""
    kind = type(value)
    return isinstance(value, bool) or (kind.__module__ == "numpy" and kind.__name__ in ("bool", "bool_", "bool8"))


def _num(value: Any) -> float | None:
    """A finite real number as a float (numpy numbers too); booleans, NaN, infinity and
    non-numbers are None.

    A NaN count (a pandas round trip fills a missing count with NaN) would fail every
    comparison and fall through to ``complete``; None sends it to the next source instead.
    """
    if _is_bool(value) or not isinstance(value, numbers.Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class PenaltyScale:
    """Points per reason. The defaults are profile ``amfam-v1``; the order is enforced.

    A scale whose values differ from the defaults must carry its own ``profile`` id: a
    custom scale labelled ``amfam-v1`` would be read as the client's numbers.
    """

    profile: str = PROFILE
    unnecessary_review: float = 4.0
    pipeline_failure: float = 4.0
    wrong_doc_type: float = 3.0
    missed_review: float = 2.0
    wrong_subtype: float = 1.0
    fabricated: float = 3.0
    low_recall: float = 2.0
    partial: float = 1.0
    #: Under this share of targeted entities reported correctly, an extraction is ``low_recall``.
    low_recall_below: float = 1 / 3

    def __post_init__(self) -> None:
        """Refuse non-finite values, a broken ladder order, and a custom scale under the client's profile."""
        # NaN fails every comparison below, so it would pass them; infinity breaks the 0-1 score.
        numeric = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "profile"}
        bad = {k: v for k, v in numeric.items() if _num(v) is None}
        if bad:
            raise ValueError(f"penalty scale values must be finite numbers: {bad}")
        points = {k: v for k, v in numeric.items() if k != "low_recall_below"}
        out_of_range = {k: v for k, v in points.items()
                        if v != 0 and not MIN_POINTS_BOUND <= abs(v) <= MAX_POINTS_BOUND}
        if out_of_range:
            raise ValueError(f"penalty scale points must lie in [{MIN_POINTS_BOUND}, {MAX_POINTS_BOUND}]: "
                             f"{out_of_range}")

        def strictly_falling(*names: str) -> None:
            """Require the named points to fall strictly in the given order."""
            values = [getattr(self, n) for n in names]
            if any(a <= b for a, b in zip(values, values[1:])):
                raise ValueError(f"penalty scale must fall strictly along {' > '.join(names)}: {values}")

        # The client's ordering: a needless review is the worst outcome on both composites.
        strictly_falling("unnecessary_review", "wrong_doc_type", "wrong_subtype")
        strictly_falling("unnecessary_review", "fabricated", "low_recall", "partial")
        if not self.wrong_doc_type > self.missed_review > 0 or self.wrong_subtype <= 0:
            raise ValueError("penalty scale: wrong_doc_type > missed_review > 0 and wrong_subtype > 0")
        if self.partial <= 0:
            raise ValueError("penalty scale: partial > 0 (a partial extraction is never free)")
        if not 0 < self.pipeline_failure <= self.unnecessary_review:
            raise ValueError("penalty scale: 0 < pipeline_failure <= unnecessary_review")
        if not 0 < self.low_recall_below < 1:
            raise ValueError("penalty scale: low_recall_below must lie in (0, 1)")
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("penalty scale: profile must be a non-empty string")
        if self.profile.strip().casefold() == PROFILE:
            changed = sorted(f.name for f in fields(self)
                             if f.name != "profile" and getattr(self, f.name) != f.default)
            if changed:
                raise ValueError(
                    f"penalty scale: a custom scale needs its own profile id, not {PROFILE!r} "
                    f"(values differ from the defaults: {changed})")

    @property
    def max_points(self) -> float:
        """The worst per-document penalty, the divisor of the 0-1 score."""
        return max(self.unnecessary_review, self.pipeline_failure)


DEFAULT_SCALE = PenaltyScale()


@dataclass(frozen=True)
class Outcome:
    """One document's penalty: its points and every reason that applied, worst first."""

    points: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse negative or non-finite points and an outcome with no reason."""
        if _num(self.points) is None or self.points < 0:
            raise ValueError(f"outcome points must be a finite number >= 0, got {self.points!r}")
        if not self.reasons or not all(isinstance(r, str) and r for r in self.reasons):
            raise ValueError(f"an outcome needs at least one non-empty reason, got {self.reasons!r}")

    @property
    def reason(self) -> str:
        """The worst reason, the one that set the points."""
        return self.reasons[0]


@dataclass(frozen=True)
class PainPointDocument:
    """What the composites read about one document.

    ``expected_stage`` None means archived. ``extraction`` is the document's scored extraction
    row (None when the document has no field truth); ``groups`` carries the breakdown labels
    (experiment, model, prompt, arm ...).
    """

    doc_id: str | None = None
    expected_class: str | None = None
    predicted_class: str | None = None
    stage: str | None = None
    expected_stage: str | None = None
    failed: bool = False
    subclass_correct: bool | None = None
    extraction: Mapping[str, Any] | None = None
    groups: Mapping[str, str] = field(default_factory=dict)


def _count(value: Any) -> float | None:
    """A usable event count: a finite, non-negative whole number, else None."""
    number = _num(value)
    return number if number is not None and number >= 0 and number == int(number) else None


def _absent(value: Any) -> bool:
    """No value: None, or a NaN (how pandas marks a missing cell)."""
    if value is None:
        return True
    try:
        return isinstance(value, numbers.Real) and not _is_bool(value) and math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _flag(value: Any) -> bool | None:
    """A Python or numpy boolean as ``bool``; anything else is None (unknown)."""
    return bool(value) if _is_bool(value) else None


def _label(value: Any) -> str:
    """A class or stage label, stripped and lower-cased; blank for None."""
    return str(value or "").strip().lower()


def _empty_container(value: Any) -> bool:
    """None, a blank string, an empty dict, or a list / tuple whose items are all of these."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    if isinstance(value, dict):
        return not value
    if isinstance(value, (list, tuple)):
        return all(_empty_container(item) for item in value)
    return False


def _blank(value: Any) -> bool:
    """Absence: a Dojo-blank value (``None``, ``n/a``, ``nan``, ``"[]"`` ...: ``is_empty_value``), or a
    list / tuple whose items are all None, blank strings or empty containers.

    A list holding a placeholder string (``["n/a"]``) is a stated value, as the Dojo's own scorer
    reads it: ``is_empty_value`` treats any non-empty list as a value, and entity-list matching
    scores its items.
    """
    return _empty_container(value) or is_empty_value(value)


def field_value_outcomes(
    expected: Mapping[str, Any], predicted: Mapping[str, Any], field_scores: Any,
) -> dict[str, int]:
    """Per-field outcomes on the targeted fields: how many, how many right, how stated ones missed.

    A targeted field is one the truth gives a value and the scorer scored (``n_targeted``); it is
    right at a field score of 1.0 (``n_value_correct``, the Dojo's ``tp`` rule). A stated value
    that missed is wrong under :data:`FABRICATION_MAX_FIELD_SCORE` (``n_value_wrong``) or a near
    miss (``n_value_partial``); a missed field with a blank prediction is neither. The detailed
    suite path (corporate records, any row with a subclass) returns no ``tp`` / ``fn``, so these
    are the event counts there. Empty when ``field_scores`` is not a mapping. A value is blank
    when the Dojo reads it as absence (``None``, ``n/a``, ``nan``, ``"[]"`` ...) or it is a list
    of blanks, so a placeholder is a miss, not a value.
    """
    if not isinstance(field_scores, Mapping):
        return {}
    expected = expected if isinstance(expected, Mapping) else {}
    predicted = predicted if isinstance(predicted, Mapping) else {}
    targeted = correct = wrong = partial = 0
    for name, value in expected.items():
        score = _num(field_scores.get(name))
        if _blank(value) or score is None:
            continue  # blank truth, or no finite field score: not a targeted field
        targeted += 1
        if float(score) >= 1.0:
            correct += 1
            continue
        if _blank(predicted.get(name)):
            continue
        if float(score) < FABRICATION_MAX_FIELD_SCORE:
            wrong += 1
        else:
            partial += 1
    return {"n_targeted": targeted, "n_value_correct": correct, "n_value_wrong": wrong, "n_value_partial": partial}


def _routing(doc: PainPointDocument, scale: PenaltyScale) -> Outcome | None:
    """The outcome shared by both composites for a document that did not archive, else None."""
    stage = _label(doc.stage)
    if _flag(doc.failed) is True or stage not in FINAL_STAGES:
        return Outcome(scale.pipeline_failure, ("pipeline_failure",))
    if stage == "review":
        if (_label(doc.expected_stage) or "archived") == "review":
            return Outcome(0.0, ("necessary_review",))
        return Outcome(scale.unnecessary_review, ("unnecessary_review",))
    return None


def _worst(found: list[tuple[float, str]], clean: str) -> Outcome:
    """The outcome whose points are the highest found, every reason kept, or ``clean`` at 0."""
    if not found:
        return Outcome(0.0, (clean,))
    found.sort(key=lambda item: -item[0])
    return Outcome(found[0][0], tuple(reason for _, reason in found))


def classification_outcome(doc: PainPointDocument, scale: PenaltyScale = DEFAULT_SCALE) -> Outcome | None:
    """One document's classification penalty; None when it has no expected class.

    An archive without a class name is a wrong class here: the document is filed nowhere a
    person would look for it.
    """
    expected = _label(doc.expected_class)
    if not expected:
        return None
    routed = _routing(doc, scale)
    if routed is not None:
        return routed
    found: list[tuple[float, str]] = []
    if _label(doc.predicted_class) != expected:
        found.append((scale.wrong_doc_type, "wrong_doc_type"))
    if (_label(doc.expected_stage) or "archived") == "review":
        found.append((scale.missed_review, "missed_review"))
    if _flag(doc.subclass_correct) is False and not any(r == "wrong_doc_type" for _, r in found):
        found.append((scale.wrong_subtype, "wrong_subtype"))
    return _worst(found, "correct")


def _field_counts(scored: Mapping[str, Any]) -> tuple[float | None, float | None, float]:
    """``(correct, targeted, invented)`` of one scored row; ``(None, None, 0)`` without usable counts.

    The Dojo event counts (``tp``, ``tp + fn``, ``fp``) when the row has them; otherwise the
    per-field counts (``n_value_correct``, ``n_targeted``), which the detailed suite path needs
    because it returns no ``tp`` / ``fn``. Without ``fp`` the documented-absence hallucinations
    (``n_hallucinated``) stand in for the values stated on empty truth. ``n_value_wrong`` is
    always added. An absent invention count is 0 (``None`` and NaN, the pandas marker for a
    missing value, are absent); one that is present but corrupt (negative, infinite, fractional,
    text) makes the invented values unknown, so the row has no usable counts and the share decides.
    """
    def present_but_unusable(key: str) -> bool:
        """The key holds a value that is not absent and not a usable count."""
        return not _absent(scored.get(key)) and _count(scored.get(key)) is None

    tp, fn, fp = (_count(scored.get(k)) for k in ("tp", "fn", "fp"))
    if tp is not None and fn is not None:
        correct, targeted = tp, tp + fn
    else:
        correct, targeted = _count(scored.get("n_value_correct")), _count(scored.get("n_targeted"))
        if correct is not None and targeted is not None and correct > targeted:
            correct = targeted = None  # inconsistent counts are no usable figure
    invention_keys = ("n_hallucinated" if _absent(scored.get("fp")) else "fp", "n_value_wrong")
    if any(present_but_unusable(k) for k in invention_keys):
        return None, None, 0.0
    empty_truth = fp if fp is not None else (_count(scored.get("n_hallucinated")) or 0.0)
    return correct, targeted, empty_truth + (_count(scored.get("n_value_wrong")) or 0.0)


def extraction_outcome(doc: PainPointDocument, scale: PenaltyScale = DEFAULT_SCALE) -> Outcome | None:
    """One document's extraction penalty; None without an expected class or field truth.

    A row the scorer gave no usable figure is left out too, never scored as complete.
    """
    scored = doc.extraction
    if not isinstance(scored, Mapping) or not _label(doc.expected_class):
        return None
    routed = _routing(doc, scale)
    if routed is not None:
        return routed
    method = str(scored.get("scoring_method") or "")
    clause_labels = "+maud" in method or "+cuad" in method
    correct, targeted, invented = _field_counts(scored)
    if clause_labels or correct is None or targeted is None:
        share = _num(scored.get("overall_extraction_score"))
        if share is None or not 0.0 <= share <= 1.0:
            return None  # no usable figure: never scored as complete
        if share >= 1.0:
            return Outcome(0.0, ("complete",))
        if share < scale.low_recall_below:
            return Outcome(scale.low_recall, ("low_recall",))
        return Outcome(scale.partial, ("partial",))
    near_miss = _count(scored.get("n_value_partial")) or 0.0
    if targeted <= 0:
        # The truth holds only empty fields: anything stated was invented.
        return Outcome(scale.fabricated, ("fabricated",)) if invented > 0 else Outcome(0.0, ("complete",))
    share = correct / targeted
    if correct == 0 and near_miss == 0 and invented > 0:
        return Outcome(scale.fabricated, ("fabricated",))
    if share < scale.low_recall_below:
        return Outcome(scale.low_recall, ("low_recall",))
    if share < 1.0 or invented > 0:
        return Outcome(scale.partial, ("partial",))
    return Outcome(0.0, ("complete",))


def _outcome_dict(outcome: Outcome | None) -> dict[str, Any] | None:
    """An outcome as plain JSON-ready data, or None when the document is not scored."""
    if outcome is None:
        return None
    return {"points": outcome.points, "reason": outcome.reason, "reasons": list(outcome.reasons)}


def score_document(doc: PainPointDocument, scale: PenaltyScale = DEFAULT_SCALE) -> dict[str, Any]:
    """Both composites for one document; a composite is None when the document is not scored on it."""
    return {
        "doc_id": doc.doc_id,
        "expected_class": doc.expected_class,
        "groups": ({str(k): str(v) for k, v in doc.groups.items()} if isinstance(doc.groups, Mapping) else {}),
        CLASSIFICATION: _outcome_dict(classification_outcome(doc, scale)),
        EXTRACTION: _outcome_dict(extraction_outcome(doc, scale)),
    }


def summarize(
    outcomes: Iterable[tuple[Outcome | None, str | None]],
    reasons: Sequence[str],
    scale: PenaltyScale = DEFAULT_SCALE,
) -> dict[str, Any]:
    """``(outcome, class)`` pairs -> n, excluded, points, mean, 0-1 score, reasons and classes.

    ``reasons`` counts each document under its worst reason, listed in the given order.
    """
    points: Counter[str] = Counter()
    count: Counter[str] = Counter()
    tiers: Counter[str] = Counter({name: 0 for name in reasons})
    excluded = 0
    for outcome, cls in outcomes:
        if outcome is None:
            excluded += 1
            continue
        name = _label(cls) or UNKNOWN
        count[name] += 1
        points[name] += outcome.points
        tiers[outcome.reason] += 1
    n = sum(count.values())
    total = sum(points.values())
    mean = total / n if n else None
    return {
        "n": n,
        "excluded": excluded,
        "points": round(total, 6),
        "mean": round(mean, 6) if mean is not None else None,
        "score": round(1 - mean / scale.max_points, 6) if mean is not None else None,
        "reasons": dict(tiers),
        "by_class": {
            name: {"n": count[name], "points": round(points[name], 6),
                   "mean": round(points[name] / count[name], 6)}
            for name in sorted(count)
        },
    }


def _summaries(docs: Sequence[PainPointDocument], scale: PenaltyScale) -> dict[str, dict[str, Any]]:
    """Both composites' run summaries over the documents."""
    classification = [(classification_outcome(d, scale), d.expected_class) for d in docs]
    extraction = [(extraction_outcome(d, scale), d.expected_class) for d in docs]
    return {CLASSIFICATION: summarize(classification, CLASSIFICATION_REASONS, scale),
            EXTRACTION: summarize(extraction, EXTRACTION_REASONS, scale)}


def score_run(docs: Iterable[PainPointDocument], scale: PenaltyScale = DEFAULT_SCALE) -> dict[str, Any]:
    """Both composites over a run's documents: profile, scale and one summary per composite."""
    return {"profile": scale.profile, "scale": asdict(scale), **_summaries(list(docs), scale)}


def _key_value(doc: PainPointDocument, name: str) -> str:
    """The group label a document has under a key name (``doc_class`` or a ``groups`` entry)."""
    if name == DOC_CLASS_KEY:
        return _label(doc.expected_class) or UNKNOWN
    value = doc.groups.get(name) if isinstance(doc.groups, Mapping) else None
    text = str(value).strip() if value is not None else ""
    return text or UNKNOWN


def _names(by: str | Sequence[str]) -> tuple[str, ...]:
    """Breakdown key names as a tuple; a bare string is one key, an empty or blank one is refused."""
    if by is None:
        raise ValueError("breakdown keys must be non-empty strings, got None")
    names = (by,) if isinstance(by, str) else tuple(by)
    if not names or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError(f"breakdown keys must be non-empty strings, got {by!r}")
    names = tuple(n.strip() for n in names)
    if len(set(names)) != len(names):
        raise ValueError(f"breakdown keys repeat: {list(names)}")
    return names


def _check_n_boot(n_boot: int, seed: int) -> None:
    """Refuse a resample count the bootstrap cannot use, and a seed that would not be one."""
    if isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 1:
        raise ValueError(f"n_boot must be a positive integer, got {n_boot!r}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an integer (a None seed is not deterministic), got {seed!r}")


def _doc_key(doc: PainPointDocument) -> str:
    """The id ``compare`` pairs and de-duplicates on: ``str(doc_id)``, stripped."""
    return str(doc.doc_id).strip()


def breakdown(
    docs: Iterable[PainPointDocument],
    by: str | Sequence[str] = ("experiment",),
    scale: PenaltyScale = DEFAULT_SCALE,
    *,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, Any]:
    """Both composites per group of documents, each with a bootstrap CI on the mean penalty.

    One entry per distinct key tuple, sorted. The key ``"doc_class"`` reads the expected class
    (lower-cased); any other key name reads ``doc.groups`` and a missing label is ``"unknown"``.
    ``ci`` is ``bootstrap_ci`` over the group's per-document points (None under two scored
    documents); it is on the penalty-points scale, like ``mean``.
    """
    names = _names(by)
    _check_n_boot(n_boot, seed)
    groups: dict[tuple[str, ...], list[PainPointDocument]] = {}
    for doc in docs:
        groups.setdefault(tuple(_key_value(doc, n) for n in names), []).append(doc)
    entries = []
    for key in sorted(groups):
        members = groups[key]
        entry: dict[str, Any] = {"key": dict(zip(names, key))}
        for composite, outcome_of in ((CLASSIFICATION, classification_outcome),
                                      (EXTRACTION, extraction_outcome)):
            outcomes = [(outcome_of(d, scale), d.expected_class) for d in members]
            reasons = CLASSIFICATION_REASONS if composite == CLASSIFICATION else EXTRACTION_REASONS
            summary = summarize(outcomes, reasons, scale)
            # Sorted, so the interval does not depend on the order the documents came in.
            points = sorted(o.points for o, _ in outcomes if o is not None)
            summary["ci"] = bootstrap_ci(points, n_boot=n_boot, seed=seed)
            entry[composite] = summary
        entries.append(entry)
    return {"profile": scale.profile, "scale": asdict(scale), "by": list(names), "groups": entries}


def _points_by_doc_id(members: Sequence[PainPointDocument], outcome_of: Any, scale: PenaltyScale,
                      ) -> dict[str, float]:
    """Per-document points of one composite, keyed by doc_id; unscored documents are left out."""
    out: dict[str, float] = {}
    for doc in members:
        outcome = outcome_of(doc, scale)
        if outcome is not None:
            out[_doc_key(doc)] = outcome.points
    return out


def compare(
    docs: Iterable[PainPointDocument],
    *,
    by: str = "experiment",
    baseline: str,
    scale: PenaltyScale = DEFAULT_SCALE,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, Any]:
    """Paired comparison of every other group value of ``by`` against ``baseline``.

    Per composite, documents are matched on ``doc_id`` among those scored on that composite in
    both groups. ``delta`` is candidate minus baseline mean penalty (positive = more penalty =
    worse); ``ci`` is ``bootstrap_ci`` over the per-document differences (None under two pairs).
    ``only_baseline`` / ``only_candidate`` count documents scored on the composite in one group
    only. Documents without a label under ``by`` form the ``"unknown"`` group, which is compared
    like any other. Raises ``ValueError`` for an unknown baseline, a missing ``doc_id`` or a
    duplicate ``doc_id`` inside one group.
    """
    if not isinstance(by, str) or not by.strip():
        raise ValueError(f"compare needs one non-empty group key name, got {by!r}")
    by = by.strip()
    _check_n_boot(n_boot, seed)
    groups: dict[str, list[PainPointDocument]] = {}
    for doc in docs:
        if doc.doc_id is None or not str(doc.doc_id).strip():
            raise ValueError(f"compare needs a doc_id on every document; missing on {doc!r}")
        groups.setdefault(_key_value(doc, by), []).append(doc)
    baseline = str(baseline).strip()
    if baseline not in groups:
        raise ValueError(f"unknown baseline {baseline!r} for {by!r}; groups: {sorted(groups)}")
    for value, members in groups.items():
        seen = Counter(_doc_key(d) for d in members)
        duplicated = sorted(i for i, c in seen.items() if c > 1)
        if duplicated:
            raise ValueError(f"duplicate doc_id inside {by}={value!r}: {duplicated}")
    out: dict[str, Any] = {
        "profile": scale.profile, "scale": asdict(scale), "by": by, "baseline": baseline,
        CLASSIFICATION: [], EXTRACTION: [],
    }
    for composite, outcome_of in ((CLASSIFICATION, classification_outcome),
                                  (EXTRACTION, extraction_outcome)):
        base = _points_by_doc_id(groups[baseline], outcome_of, scale)
        for candidate in sorted(v for v in groups if v != baseline):
            cand = _points_by_doc_id(groups[candidate], outcome_of, scale)
            paired = sorted(set(base) & set(cand))
            diffs = [cand[i] - base[i] for i in paired]
            n = len(paired)
            base_mean = sum(base[i] for i in paired) / n if n else None
            cand_mean = sum(cand[i] for i in paired) / n if n else None
            out[composite].append({
                "candidate": candidate,
                "n_paired": n,
                "baseline_mean": round(base_mean, 6) if base_mean is not None else None,
                "candidate_mean": round(cand_mean, 6) if cand_mean is not None else None,
                "delta": round(sum(diffs) / n, 6) if n else None,
                "ci": bootstrap_ci(diffs, n_boot=n_boot, seed=seed),
                "only_baseline": len(set(base) - set(cand)),
                "only_candidate": len(set(cand) - set(base)),
            })
    return out


def headline_scores(run: Mapping[str, Any]) -> dict[str, float | None]:
    """The registry-named run headlines of a :func:`score_run` result.

    ``pain_points_{classification,extraction}_mean`` (mean penalty points, lower is better) and
    ``pain_points_{classification,extraction}_score`` (``1 - mean / max_points``, higher is better);
    None when the composite scored no document.
    """
    out: dict[str, float | None] = {}
    for composite in (CLASSIFICATION, EXTRACTION):
        summary = run.get(composite) or {}
        out[f"pain_points_{composite}_mean"] = summary.get("mean")
        out[f"pain_points_{composite}_score"] = summary.get("score")
    return out


__all__ = [
    "CLASSIFICATION", "CLASSIFICATION_REASONS", "DEFAULT_SCALE", "DOC_CLASS_KEY", "EXTRACTION",
    "EXTRACTION_REASONS", "FABRICATION_MAX_FIELD_SCORE", "FINAL_STAGES", "Outcome",
    "PROFILE", "PainPointDocument", "PenaltyScale", "breakdown", "classification_outcome",
    "compare", "extraction_outcome", "field_value_outcomes", "headline_scores", "score_document", "score_run",
    "summarize",
]
