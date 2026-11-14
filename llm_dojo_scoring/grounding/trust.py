"""The trust gate: when an agent's ``valid`` verdicts may stand in for a person's.

An agent (``reviewer_id``: one boss prompt version, one JEV release) is **trusted** at
time ``t`` when, over its latest ``window`` paired checks known at ``t``
(:func:`~llm_dojo_scoring.grounding.agreement.reviewer_agreement` with ``as_of=t``):

* it called at least ``min_n`` values ``valid`` (``n_agent_valid``), and
* the unrounded Wilson 95% lower bound of its valid precision is at least ``bar``.

Trust is judged **as of each confirmation's** ``confirmed_at``, never retroactively.
:meth:`TrustGate.history` replays the ledger at every time a person confirmed
something (the only moments a paired check can appear or change) and returns a
:class:`GateSnapshot` each time an agent's numbers change. A snapshot is in force
from its ``effective_at`` until the agent's next snapshot. A new ``reviewer_id``
has no paired checks, so no snapshot, so it starts untrusted; an agent whose every
paired check is withdrawn (people later say ``unsure`` or disagree) gets an empty,
untrusted snapshot.

:meth:`TrustGate.trusted_snapshot_id` is the lookup
:func:`~llm_dojo_scoring.grounding.labels.derive_valid_labels` uses (``TrustLookup``),
and :meth:`TrustGate.regressions` is the regression guard: when an agent falls below
the bar, it lists the labels that rested on its trust since it last passed, for a
person to re-review. Nothing is stored; everything is recomputed from the ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping

from ..config import GroundingSettings, get_settings
from .agreement import AgreementCounts, PairedCheck, ReviewerAgreement, _agreement_over, paired_checks
from .audit import SCHEMA_VERSION
from .labels import TRUSTED_AGENT_BASIS, ValidLabel
from .ledger import HUMAN, HUMAN_ID_PREFIX, ConfirmationLedger


@dataclass(frozen=True)
class GateSnapshot:
    """One agent's trust from ``effective_at`` until its next snapshot.

    ``snapshot_id`` hashes the reviewer id, the window bounds, the counts and the gate
    thresholds, so the same evidence under the same gate always has the same id.
    """

    snapshot_id: str
    reviewer_id: str
    effective_at: float
    trusted: bool
    bar: float
    min_n: int
    window: int
    window_start: float | None
    window_end: float | None
    n_checked: int
    n_agent_valid: int
    n_valid_confirmed: int
    valid_precision: float | None
    valid_precision_lower_95: float | None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GateSnapshot":
        """Rebuild a snapshot from :meth:`as_dict` output; unknown keys are ignored."""
        names = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in names})


@dataclass(frozen=True)
class Regression:
    """An agent fell below the bar: the labels that rested on its earlier trust.

    ``failed`` is the first untrusted snapshot after a passing run; ``passing`` are the
    ids of that run's snapshots; ``labels`` are the ``trusted_agent`` labels whose
    ``gate_snapshot_id`` is one of them, for a person to re-review.
    """

    reviewer_id: str
    failed: GateSnapshot
    passing: tuple[str, ...]
    labels: tuple[ValidLabel, ...]

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {
            "schema_version": SCHEMA_VERSION, "reviewer_id": self.reviewer_id,
            "failed": self.failed.as_dict(), "passing": list(self.passing),
            "labels": [label.as_dict() for label in self.labels],
        }


def _snapshot_id(fields: Mapping[str, Any]) -> str:
    """Stable id: sha256 of the identifying fields as canonical JSON."""
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TrustGate:
    """Decides, from the ledger alone, which agents were trusted and when.

    Thresholds default to ``get_settings().grounding`` (``trust_bar``,
    ``trust_min_n``, ``trust_window``, ``certainty_floor``), are validated together and
    are read-only afterwards (``history`` is cached per ledger).
    ``certainty_floor`` is not part of trust; :func:`derive_valid_labels` uses it when
    given this gate and no floor of its own.
    """

    def __init__(self, bar: float | None = None, min_n: int | None = None, window: int | None = None,
                 certainty_floor: float | None = None) -> None:
        """Read the defaults from settings, apply the overrides, and validate them."""
        base = get_settings().grounding
        overrides = {key: value for key, value in (
            ("trust_bar", bar), ("trust_min_n", min_n), ("trust_window", window),
            ("certainty_floor", certainty_floor)) if value is not None}
        checked: GroundingSettings = replace(base, **overrides)
        checked.validate()
        self._bar = float(checked.trust_bar)
        self._min_n = int(checked.trust_min_n)
        self._window = int(checked.trust_window)
        self._certainty_floor = float(checked.certainty_floor)
        self._cache: tuple[ConfirmationLedger, tuple[GateSnapshot, ...]] | None = None

    @property
    def bar(self) -> float:
        """Least unrounded Wilson lower bound of valid precision (read-only)."""
        return self._bar

    @property
    def min_n(self) -> int:
        """Least checked ``valid`` verdicts (read-only)."""
        return self._min_n

    @property
    def window(self) -> int:
        """Latest paired checks per agent the gate looks at (read-only)."""
        return self._window

    @property
    def certainty_floor(self) -> float:
        """Least certainty an agent ``valid`` needs to count (read-only)."""
        return self._certainty_floor

    def __repr__(self) -> str:
        """The thresholds, for logs."""
        return (f"TrustGate(bar={self.bar!r}, min_n={self.min_n!r}, window={self.window!r}, "
                f"certainty_floor={self.certainty_floor!r})")

    def _snapshot(self, reviewer_id: str, at: float, agreement: Any) -> GateSnapshot:
        """The snapshot for one agent's agreement as of ``at``."""
        counts = agreement.overall
        lower = counts.valid_precision_lower_95
        trusted = counts.n_agent_valid >= self.min_n and lower is not None and lower >= self.bar
        identity = {
            "reviewer_id": reviewer_id, "bar": self.bar, "min_n": self.min_n, "window": self.window,
            "window_start": None if agreement.window_start is None else float(agreement.window_start),
            "window_end": None if agreement.window_end is None else float(agreement.window_end),
            "n_checked": counts.n_checked, "n_agent_valid": counts.n_agent_valid,
            "n_valid_confirmed": counts.n_valid_confirmed, "trusted": trusted,
        }
        return GateSnapshot(
            snapshot_id=_snapshot_id(identity), reviewer_id=reviewer_id, effective_at=at,
            trusted=trusted, bar=self.bar, min_n=self.min_n, window=self.window,
            window_start=agreement.window_start, window_end=agreement.window_end,
            n_checked=counts.n_checked, n_agent_valid=counts.n_agent_valid,
            n_valid_confirmed=counts.n_valid_confirmed, valid_precision=counts.valid_precision,
            valid_precision_lower_95=lower,
        )

    def history(self, ledger: ConfirmationLedger) -> list[GateSnapshot]:
        """Every agent's snapshots, in ``(effective_at, reviewer_id)`` order.

        The ledger is replayed at each distinct ``confirmed_at`` of a human
        confirmation; an agent gets a new snapshot only when its numbers change. Each
        step equals ``reviewer_agreement(ledger, window=self.window, as_of=t)``; it is
        computed incrementally, because a candidate's pairs depend only on that
        candidate's own confirmations. The result for the same ledger object is cached
        (ledgers are immutable).
        """
        if self._cache is not None and self._cache[0] is ledger:
            return list(self._cache[1])
        by_candidate: dict[str, list[Any]] = defaultdict(list)
        for c in ledger.confirmations:
            by_candidate[c.candidate_id].append(c)
        events: dict[float, set[str]] = defaultdict(set)
        for c in ledger.confirmations:
            if c.reviewer_kind == HUMAN:
                events[c.confirmed_at].add(c.candidate_id)
        current: dict[str, dict[str, PairedCheck]] = defaultdict(dict)  # reviewer -> candidate -> pair
        last: dict[str, str] = {}
        snapshots: list[GateSnapshot] = []
        for at in sorted(events):
            touched: set[str] = set()
            for cid in events[at]:
                own = ConfirmationLedger(candidates=ledger.candidates, confirmations=tuple(by_candidate[cid]))
                fresh = {pair.reviewer_id: pair for pair in paired_checks(own, as_of=at)}
                for reviewer_id in set(fresh) | {r for r, pairs in current.items() if cid in pairs}:
                    if current[reviewer_id].get(cid) != fresh.get(reviewer_id):
                        touched.add(reviewer_id)
                    if reviewer_id in fresh:
                        current[reviewer_id][cid] = fresh[reviewer_id]
                    else:
                        current[reviewer_id].pop(cid, None)
            for reviewer_id in sorted(touched):
                pairs = sorted(current[reviewer_id].values(),
                               key=lambda p: (p.human_confirmed_at, p.candidate_id, p.reviewer_id))
                agreement = (_agreement_over(reviewer_id, pairs, self.window) if pairs else
                             ReviewerAgreement(reviewer_id, self.window, None, None, AgreementCounts()))
                snapshot = self._snapshot(reviewer_id, at, agreement)
                if last.get(reviewer_id) != snapshot.snapshot_id:
                    last[reviewer_id] = snapshot.snapshot_id
                    snapshots.append(snapshot)
        self._cache = (ledger, tuple(snapshots))
        return snapshots

    def snapshot_at(self, ledger: ConfirmationLedger, reviewer_id: str, at: float) -> GateSnapshot | None:
        """The snapshot in force for ``reviewer_id`` at ``at`` (inclusive), or ``None``."""
        current = None
        for snapshot in self.history(ledger):
            if snapshot.effective_at > at:
                break
            if snapshot.reviewer_id == reviewer_id:
                current = snapshot
        return current

    def trusted_snapshot_id(self, ledger: ConfirmationLedger, reviewer_id: str, at: float) -> str | None:
        """Id of the passing snapshot in force for ``reviewer_id`` at ``at``, else ``None``.

        People are never gated: a ``human:`` reviewer id always gives ``None``.
        """
        if reviewer_id.startswith(HUMAN_ID_PREFIX):
            return None
        snapshot = self.snapshot_at(ledger, reviewer_id, at)
        return snapshot.snapshot_id if snapshot is not None and snapshot.trusted else None

    def regressions(self, ledger: ConfirmationLedger, labels: Iterable[ValidLabel]) -> list[Regression]:
        """The regression guard: each fall below the bar, with the labels to re-review.

        For every agent snapshot that is untrusted right after a trusted one, the
        ``trusted_agent`` labels whose ``gate_snapshot_id`` is a snapshot of that
        passing run (in candidate-id order).
        """
        labels = [label for label in labels if label.validity_basis == TRUSTED_AGENT_BASIS]
        found: list[Regression] = []
        run: dict[str, list[str]] = {}
        for snapshot in self.history(ledger):
            passing = run.setdefault(snapshot.reviewer_id, [])
            if snapshot.trusted:
                passing.append(snapshot.snapshot_id)
                continue
            if passing:
                ids = set(passing)
                affected = tuple(sorted((label for label in labels if label.gate_snapshot_id in ids),
                                        key=lambda label: label.source_candidate_id))
                found.append(Regression(snapshot.reviewer_id, snapshot, tuple(passing), affected))
            run[snapshot.reviewer_id] = []
        return found

