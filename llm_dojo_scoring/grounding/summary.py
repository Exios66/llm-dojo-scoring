"""Unlabelled-value rates per run, class and field, and their ``ScoreRecord`` form.

The headline rate is ``grounding_not_found_rate``: of the unlabelled values that
could be checked, the share the source document does not state. ``unverifiable``
values are left out of its denominator and reported on their own
(``grounding_unverifiable_rate``) so a reader can see how much the rate cannot
see. A rate with a zero denominator is ``None``, never ``0.0``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from ..metrics.emitter import ScoreRecord
from .audit import SCHEMA_VERSION, UnlabelledValueAudit
from .verdicts import GROUNDED, NOT_FOUND, UNVERIFIABLE, VERDICTS

NOT_FOUND_RATE = "grounding_not_found_rate"
UNVERIFIABLE_RATE = "grounding_unverifiable_rate"
N_AUDITED = "grounding_n_audited"

#: The metric ids this module emits, in emission order.
METRIC_IDS: tuple[str, ...] = (NOT_FOUND_RATE, UNVERIFIABLE_RATE, N_AUDITED)


def _ratio(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator``, or ``None`` when there is nothing to divide by."""
    return numerator / denominator if denominator else None


@dataclass(frozen=True)
class GroundingCounts:
    """Verdict counts for one slice of audited values."""

    grounded: int = 0
    not_found: int = 0
    unverifiable: int = 0

    @property
    def n_audited(self) -> int:
        """Every audited value in the slice."""
        return self.grounded + self.not_found + self.unverifiable

    @property
    def n_checkable(self) -> int:
        """Values the document could confirm or refute (the rate's denominator)."""
        return self.grounded + self.not_found

    @property
    def not_found_rate(self) -> float | None:
        """Share of checkable values the document does not state."""
        return _ratio(self.not_found, self.n_checkable)

    @property
    def unverifiable_rate(self) -> float | None:
        """Share of audited values that could not be checked."""
        return _ratio(self.unverifiable, self.n_audited)

    def as_dict(self) -> dict[str, Any]:
        """Counts and rates as plain data."""
        return {
            GROUNDED: self.grounded,
            NOT_FOUND: self.not_found,
            UNVERIFIABLE: self.unverifiable,
            "n_audited": self.n_audited,
            "not_found_rate": self.not_found_rate,
            "unverifiable_rate": self.unverifiable_rate,
        }


def _counts(verdicts: Counter) -> GroundingCounts:
    """Freeze a verdict counter."""
    return GroundingCounts(verdicts[GROUNDED], verdicts[NOT_FOUND], verdicts[UNVERIFIABLE])


@dataclass(frozen=True)
class GroundingSummary:
    """Run-level counts with breakdowns by document class and by ``(class, field)``."""

    overall: GroundingCounts
    by_class: dict[str, GroundingCounts]
    by_field: dict[tuple[str, str], GroundingCounts]

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable summary; field keys are written ``"doc_class.field"``."""
        return {
            "schema_version": SCHEMA_VERSION,
            "overall": self.overall.as_dict(),
            "by_class": {key: value.as_dict() for key, value in self.by_class.items()},
            "by_field": {f"{c}.{f}": value.as_dict() for (c, f), value in self.by_field.items()},
        }


def summarize_grounding(audits: Iterable[UnlabelledValueAudit]) -> GroundingSummary:
    """Count verdicts overall, per class and per field (keys sorted for stable output).

    A record whose verdict is not one of :data:`~.verdicts.VERDICTS` raises
    ``ValueError`` rather than silently leaving the counts short.
    """
    overall: Counter = Counter()
    by_class: dict[str, Counter] = defaultdict(Counter)
    by_field: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for audit in audits:
        if audit.verdict not in VERDICTS:
            raise ValueError(f"unknown grounding verdict {audit.verdict!r}; expected one of {VERDICTS}")
        overall[audit.verdict] += 1
        by_class[audit.doc_class][audit.verdict] += 1
        by_field[(audit.doc_class, audit.field)][audit.verdict] += 1
    return GroundingSummary(
        overall=_counts(overall),
        by_class={key: _counts(by_class[key]) for key in sorted(by_class)},
        by_field={key: _counts(by_field[key]) for key in sorted(by_field)},
    )


def _slice_records(
    counts: GroundingCounts, scope: dict[str, Any], *, agent: str, run_id: str | None
) -> list[ScoreRecord]:
    """The three metrics for one slice, each tagged with its scope and denominator."""
    values = (
        (NOT_FOUND_RATE, counts.not_found_rate, counts.n_checkable),
        (UNVERIFIABLE_RATE, counts.unverifiable_rate, counts.n_audited),
        (N_AUDITED, counts.n_audited, counts.n_audited),
    )
    return [
        ScoreRecord(agent=agent, metric=metric, value=value, run_id=run_id,
                    metadata={**scope, "denominator": denominator})
        for metric, value, denominator in values
    ]


def grounding_score_records(
    summary: GroundingSummary, *, agent: str, run_id: str | None = None
) -> list[ScoreRecord]:
    """``ScoreRecord`` s for the run, then each class, then each field."""
    records = _slice_records(summary.overall, {"scope": "run"}, agent=agent, run_id=run_id)
    for doc_class, counts in summary.by_class.items():
        records += _slice_records(counts, {"scope": "class", "doc_class": doc_class},
                                  agent=agent, run_id=run_id)
    for (doc_class, field), counts in summary.by_field.items():
        records += _slice_records(counts, {"scope": "field", "doc_class": doc_class, "field": field},
                                  agent=agent, run_id=run_id)
    return records
