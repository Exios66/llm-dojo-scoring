"""Risk-coverage curves for selective archiving, and per-slot decision-model summaries.

A mailroom archives a document without a person when some score clears a cutoff (a
decision model's support probability, an extraction confidence) and parks the rest for
review. Every cutoff trades the two costs the experiments report:

* **review rate**: the share of documents a person must look at;
* **wrong-archive rate**: the share of archived documents the gold scores wrong (the
  selective risk, with its Wilson upper bound: the number a release gate holds to its
  budget, as the sandbox slice gate does), and ``wrong_per_1000``: wrong archives per
  1,000 scorable documents, the misarchives a deployment would see.

:func:`risk_coverage_curve` sweeps the cutoffs over scored rows, :func:`operating_point`
picks the lowest review rate inside a wrong-archive budget, and
:func:`slot_decision_summary` reads llm-mailroom's ``decision_slot_outcomes`` (taxonomy
``decision_slots:``) into per-slot park, release and cap rates next to the pipeline's
own review and wrong-archive rates. All functions are pure and network-free.

A curve's ``coverage`` and ``review_rate`` are over the rows it is given (a caller that
passes only archived documents gets the extra review a further cutoff would cost), not
over every document of a run; :func:`slot_decision_summary`'s ``review_rate`` is over every
document.

Row conventions (:func:`risk_coverage_curve`): ``score`` is how safe the row looks to
archive (higher archives first); ``wrong`` is the gold: ``True`` when archiving the row
would be wrong, ``False`` when right, ``None`` when it cannot be scored. Unscorable rows
are counted and left out of every rate, never scored as right or wrong. A scorable row
without a finite score in [0, 1] can never clear a cutoff, so it is reviewed at every
point (counted under ``n_no_score``).
"""

from __future__ import annotations

import bisect
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .bootstrap import wilson_ci

__all__ = [
    "operating_point",
    "risk_coverage_curve",
    "slot_decision_summary",
]


def _finite(value: Any) -> float | None:
    """``value`` as a finite float, else None (booleans and ints too large for a float are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _score(value: Any) -> float | None:
    """A finite score in [0, 1], else None (booleans are not scores)."""
    value = _finite(value)
    return value if value is not None and 0.0 <= value <= 1.0 else None


def _upper(hits: int, total: int, z: float) -> float | None:
    """The Wilson upper bound of ``hits / total``, None for an empty denominator."""
    interval = wilson_ci(hits / total, total, z=z) if total else None
    return interval["hi"] if interval else None


def _rate(hits: int, total: int) -> float | None:
    """``hits / total`` to 6 places, None for an empty denominator."""
    return round(hits / total, 6) if total else None


def risk_coverage_curve(
    rows: Iterable[Mapping[str, Any]],
    thresholds: Sequence[float] | None = None,
    *,
    z: float = 1.96,
) -> dict[str, Any]:
    """Review rate and wrong-archive rate at each cutoff ``t`` (archive when ``score >= t``).

    ``thresholds`` defaults to every distinct score plus one cutoff above 1 (archive
    nothing). Each point reports ``threshold``, ``archived``, ``coverage`` (archived share
    of scorable rows), ``review_rate`` (``1 - coverage``), ``wrong_archives``,
    ``wrong_archive_rate`` (wrong among archived, ``None`` when nothing is archived) with
    its Wilson ``wrong_archive_upper95``, and ``wrong_per_1000`` (wrong archives per 1,000
    scorable rows). ``aurc`` is the area under the wrong-archive rate against coverage
    (trapezoids over the points with something archived; lower is better; ``None`` with
    fewer than two such points).
    """
    n = n_unscorable = n_no_score = 0
    scored: list[tuple[float, bool]] = []
    for row in rows:
        n += 1
        wrong = row.get("wrong") if isinstance(row, Mapping) else None
        if not isinstance(wrong, bool):
            n_unscorable += 1
            continue
        score = _score(row.get("score"))
        if score is None:
            n_no_score += 1
            continue
        scored.append((score, wrong))
    n_scorable = len(scored) + n_no_score
    if thresholds is None:
        cutoffs = sorted({s for s, _ in scored} | {1.01})
    else:
        cutoffs = sorted({c for c in map(_finite, thresholds) if c is not None})
    # Sorted once: the rows archived at cutoff t are the suffix from bisect_left(scores, t).
    scored.sort(key=lambda sw: sw[0])
    scores = [s for s, _ in scored]
    wrong_before = [0]
    for _, w in scored:
        wrong_before.append(wrong_before[-1] + w)
    points: list[dict[str, Any]] = []
    for t in cutoffs:
        first = bisect.bisect_left(scores, t)
        archived = len(scored) - first
        wrong = wrong_before[-1] - wrong_before[first]
        points.append({
            "threshold": t,
            "archived": archived,
            "coverage": _rate(archived, n_scorable),
            "review_rate": _rate(n_scorable - archived, n_scorable),
            "wrong_archives": wrong,
            "wrong_archive_rate": _rate(wrong, archived),
            "wrong_archive_upper95": _upper(wrong, archived, z),
            "wrong_per_1000": round(1000 * wrong / n_scorable, 3) if n_scorable else None,
        })
    covered = sorted((p["coverage"], p["wrong_archive_rate"]) for p in points if p["archived"])
    aurc = None
    if len(covered) >= 2:
        aurc = round(sum((c2 - c1) * (r1 + r2) / 2 for (c1, r1), (c2, r2) in zip(covered, covered[1:])), 6)
    return {
        "n": n,
        "n_scorable": n_scorable,
        "n_unscorable": n_unscorable,
        "n_no_score": n_no_score,
        "points": points,
        "aurc": aurc,
        "z": z,
    }


def operating_point(
    curve: Mapping[str, Any],
    *,
    max_wrong_archive_rate: float,
    use_upper: bool = True,
) -> dict[str, Any] | None:
    """The point with the lowest review rate whose wrong-archive rate is within budget.

    ``use_upper`` (default) holds the Wilson upper bound to the budget; ``use_upper=False``
    holds the point estimate, which is what a gate comparing its observed rate to a bar does.
    On a small sample the upper bound is wide, so no point may fit although the observed
    rate is within budget. Ties keep the higher threshold. ``None`` when no point fits.
    A point that archives nothing has no wrong-archive rate and is never chosen, so ``None``
    also covers a curve where only "review everything" stays within budget.
    """
    def rate(p: Mapping[str, Any]) -> float | None:
        """The rate held to the budget for point ``p``."""
        if use_upper:
            return p.get("wrong_archive_upper95")
        # The observed rate unrounded: a rounded 1/3 (0.333333) must not fit a 0.333333 budget.
        archived, wrong = p.get("archived"), p.get("wrong_archives")
        if isinstance(archived, int) and isinstance(wrong, int) and archived > 0:
            return wrong / archived
        return p.get("wrong_archive_rate")

    fits = [p for p in curve.get("points") or []
            if (r := rate(p)) is not None and r <= max_wrong_archive_rate and p.get("review_rate") is not None]
    if not fits:
        return None
    return dict(min(fits, key=lambda p: (p["review_rate"], -p["threshold"])))


_ACTIONS = ("park", "release", "capped", "agree", "hold", "unavailable", "unverified", "replaced")


def slot_decision_summary(records: Iterable[Mapping[str, Any]], *, z: float = 1.96) -> dict[str, Any]:
    """Per-slot decision rates and the pipeline's review and wrong-archive rates.

    Each record is one document: ``decision_slot_outcomes`` and ``decision_slot_marks``
    as llm-mailroom writes them, ``final_stage`` (top level, or under ``actual`` as in a
    dumped llm-mailroom ``RunRecord``; ``archived``, ``review``; anything else,
    such as ``crashed``, is neither) and ``wrong_archive`` (``True`` / ``False`` for an
    archived document the gold scores wrong / right, ``None`` when unscorable or not
    archived). A slot has seen a document when its ``seen:<slot>`` mark or an outcome is
    present. The marks are the durable record (llm-mailroom keeps only each slot's latest
    outcome and clears them when a person resolves a park), so a ``park:<slot>`` or
    ``release:<slot>`` mark counts the document as parked or released by that slot whatever
    its outcome says now; otherwise the outcome's ``action`` counts. Per slot: ``n_seen``,
    ``actions`` (count per action, the marks applied), ``park_rate``, ``release_rate``,
    ``capped_rate`` and ``unavailable_rate`` over ``n_seen``. Pipeline: ``n``, ``archived``,
    ``reviewed``, ``other`` (neither, e.g. crashed), ``review_rate`` (reviewed over ``n``,
    as the sandbox slice gate counts it), ``wrong_archive_rate`` and its Wilson
    ``wrong_archive_upper95`` over the scorable archives (archived with a boolean
    ``wrong_archive``), and ``wrong_per_1000`` over the scorable archives plus the reviewed
    documents. That denominator differs from ``risk_coverage_curve``'s ``wrong_per_1000``
    (over every scorable row given to the curve), so compare it only with other summaries.
    """
    n = archived = wrong = scorable_archives = reviewed = 0
    seen: Counter[str] = Counter()
    actions: dict[str, Counter[str]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        n += 1
        stage = record.get("final_stage")
        actual = record.get("actual")
        if stage is None and isinstance(actual, Mapping):
            stage = actual.get("final_stage")  # a dumped llm-mailroom RunRecord nests it
        is_archived = stage == "archived"
        archived += is_archived
        reviewed += stage == "review"
        verdict = record.get("wrong_archive")
        if is_archived and isinstance(verdict, bool):
            scorable_archives += 1
            wrong += verdict
        outcomes = record.get("decision_slot_outcomes")
        outcomes = outcomes if isinstance(outcomes, Mapping) else {}
        marks = record.get("decision_slot_marks")
        marks = [str(m) for m in marks] if isinstance(marks, (list, tuple)) else []
        marked = {m[5:] for m in marks if m.startswith("seen:")}
        for slot in marked | {str(s) for s in outcomes}:
            seen[slot] += 1
            outcome = outcomes.get(slot)
            action = outcome.get("action") if isinstance(outcome, Mapping) else None
            if f"park:{slot}" in marks:
                action = "park"
            elif f"release:{slot}" in marks:
                action = "release"
            actions.setdefault(slot, Counter())[action if action in _ACTIONS else "none"] += 1
    slots = {}
    for slot in sorted(seen):
        counts = actions.get(slot, Counter())
        total = seen[slot]
        slots[slot] = {
            "n_seen": total,
            "actions": dict(sorted(counts.items())),
            "park_rate": _rate(counts["park"], total),
            "release_rate": _rate(counts["release"], total),
            "capped_rate": _rate(counts["capped"], total),
            "unavailable_rate": _rate(counts["unavailable"], total),
        }
    return {
        "pipeline": {
            "n": n,
            "archived": archived,
            "reviewed": reviewed,
            "other": n - archived - reviewed,
            "review_rate": _rate(reviewed, n),
            "n_scorable_archives": scorable_archives,
            "wrong_archives": wrong,
            "wrong_archive_rate": _rate(wrong, scorable_archives),
            "wrong_archive_upper95": _upper(wrong, scorable_archives, z),
            "wrong_per_1000": (round(1000 * wrong / (scorable_archives + reviewed), 3)
                               if scorable_archives + reviewed else None),
        },
        "slots": slots,
    }
