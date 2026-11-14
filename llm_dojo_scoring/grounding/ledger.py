"""Confirmations of review candidates, validated into an append-only ledger.

A confirmation is one reviewer's verdict on one candidate: ``valid``,
``hallucinated`` or ``unsure``, from a person (``reviewer_kind: "human"``) or an
agent such as the boss or JEV (``"agent"``, with a ``certainty`` in ``[0, 1]``).
Records come from the consumer (llm-mailroom, a human review tool) as mappings or
JSONL (:mod:`.io`).

The ledger is append-only: nothing is edited or deleted, and a change of mind is a
new confirmation. Only each reviewer's latest confirmation per candidate counts
(:meth:`ConfirmationLedger.latest`). A record that fails validation is kept as a
:class:`ConfirmationReject` with its reason, never dropped silently.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Iterable, Mapping

from .audit import SCHEMA_VERSION
from .candidates import ReviewCandidate

VALID = "valid"
HALLUCINATED = "hallucinated"
UNSURE = "unsure"

#: Every confirmation verdict.
CONFIRMATION_VERDICTS: tuple[str, ...] = (VALID, HALLUCINATED, UNSURE)

HUMAN = "human"
AGENT = "agent"

#: Every reviewer kind.
REVIEWER_KINDS: tuple[str, ...] = (HUMAN, AGENT)

#: Every human ``reviewer_id`` starts with this, and no agent's does, so an agent
#: cannot pass itself off as a person and skip the trust gate.
HUMAN_ID_PREFIX = "human:"

#: A ``confirmed_at`` further than this many seconds in the future is rejected, so a
#: far-future time cannot shadow every later change of mind.
MAX_CLOCK_SKEW_SECONDS = 86_400.0


@dataclass(frozen=True)
class Confirmation:
    """One reviewer's verdict on one candidate.

    ``reviewer_id`` names the reviewer and its version (``"human:<opaque id>"``,
    ``"boss@<prompt version>"``, ``"jev-1.13.0"``); a new agent version is a new
    reviewer. A human id starts with ``"human:"`` and an agent id never does.
    ``confirmed_at`` is Unix time. ``corrected_value``, when set, replaces
    the candidate's value in a resulting label.
    """

    candidate_id: str
    verdict: str
    reviewer_kind: str
    reviewer_id: str
    confirmed_at: float
    certainty: float | None = None
    corrected_value: Any = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Confirmation":
        """Build a confirmation from a mapping; unknown keys are ignored (no validation)."""
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})


@dataclass(frozen=True)
class ConfirmationReject:
    """A record that failed validation: its position in the input, the record and why."""

    index: int
    record: Any
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        record = self.record.as_dict() if isinstance(self.record, Confirmation) else self.record
        return {"schema_version": SCHEMA_VERSION, "index": self.index, "record": record,
                "reason": self.reason}


def _is_number(value: Any) -> bool:
    """A finite int or float that is not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _correction_problem(value: Any) -> str | None:
    """Why a ``corrected_value`` is unusable, or ``None`` when it is absent or usable."""
    if value is None:
        return None
    if isinstance(value, str):
        return None if value.strip() else "corrected_value must not be blank"
    if _is_number(value):
        return None
    return "corrected_value must be non-blank text or a finite number"


def _validate(
    record: Any, candidates: Mapping[str, ReviewCandidate], now: float
) -> tuple[Confirmation | None, str | None]:
    """The confirmation a record describes, or the reason it is rejected."""
    if isinstance(record, Confirmation):
        record = asdict(record)
    if not isinstance(record, Mapping):
        return None, f"not a mapping ({type(record).__name__})"
    cid = record.get("candidate_id")
    if not isinstance(cid, str) or cid not in candidates:
        return None, f"unknown candidate_id {cid!r}"
    if record.get("verdict") not in CONFIRMATION_VERDICTS:
        return None, f"verdict must be one of {CONFIRMATION_VERDICTS}, got {record.get('verdict')!r}"
    kind = record.get("reviewer_kind")
    if kind not in REVIEWER_KINDS:
        return None, f"reviewer_kind must be one of {REVIEWER_KINDS}, got {kind!r}"
    reviewer_id = record.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        return None, "missing reviewer_id"
    if (kind == HUMAN) != reviewer_id.startswith(HUMAN_ID_PREFIX):
        return None, f"a {kind} reviewer_id {'must' if kind == HUMAN else 'must not'} start with {HUMAN_ID_PREFIX!r}"
    confirmed_at = record.get("confirmed_at")
    if not _is_number(confirmed_at):
        return None, "confirmed_at must be a Unix time (a finite number)"
    if confirmed_at > now + MAX_CLOCK_SKEW_SECONDS:
        return None, "confirmed_at is in the future"
    certainty = record.get("certainty")
    if kind == AGENT:
        if certainty is None:
            return None, "an agent confirmation needs a certainty"
        if not _is_number(certainty) or not 0.0 <= certainty <= 1.0:
            return None, f"certainty must be a number in [0, 1], got {certainty!r}"
    elif certainty is not None:
        return None, "a human confirmation carries no certainty"
    problem = _correction_problem(record.get("corrected_value"))
    if problem:
        return None, problem
    note = record.get("note")
    if note is not None and not isinstance(note, str):
        return None, "note must be text"
    return Confirmation(
        candidate_id=record["candidate_id"], verdict=record["verdict"], reviewer_kind=kind,
        reviewer_id=reviewer_id, confirmed_at=float(record["confirmed_at"]),
        certainty=None if certainty is None else float(certainty),
        corrected_value=record.get("corrected_value"), note=note,
    ), None


@dataclass(frozen=True)
class ConfirmationLedger:
    """The candidates under review and every accepted confirmation, in arrival order."""

    candidates: Mapping[str, ReviewCandidate]
    confirmations: tuple[Confirmation, ...] = ()
    rejects: tuple[ConfirmationReject, ...] = ()

    def latest(self) -> dict[str, dict[str, Confirmation]]:
        """Each reviewer's latest confirmation per candidate: ``{candidate_id: {reviewer_id: c}}``.

        Latest is the greatest ``confirmed_at``; on a tie the one ingested later wins.
        """
        latest: dict[str, dict[str, Confirmation]] = {}
        for confirmation in self.confirmations:
            by_reviewer = latest.setdefault(confirmation.candidate_id, {})
            current = by_reviewer.get(confirmation.reviewer_id)
            if current is None or confirmation.confirmed_at >= current.confirmed_at:
                by_reviewer[confirmation.reviewer_id] = confirmation
        return latest

    def extend(self, records: Iterable[Any], *, now: float | None = None) -> "ConfirmationLedger":
        """A new ledger with ``records`` validated and appended (this one is unchanged).

        ``now`` (Unix time, default the clock) bounds ``confirmed_at``: a record more
        than :data:`MAX_CLOCK_SKEW_SECONDS` ahead of it is rejected.
        """
        now = time.time() if now is None else now
        accepted: list[Confirmation] = []
        rejected: list[ConfirmationReject] = []
        start = len(self.confirmations) + len(self.rejects)
        for offset, record in enumerate(records):
            confirmation, reason = _validate(record, self.candidates, now)
            if confirmation is None:
                rejected.append(ConfirmationReject(index=start + offset, record=record, reason=reason or ""))
            else:
                accepted.append(confirmation)
        return ConfirmationLedger(
            candidates=self.candidates,
            confirmations=self.confirmations + tuple(accepted),
            rejects=self.rejects + tuple(rejected),
        )


def ingest_confirmations(
    records: Iterable[Any], candidates: Iterable[ReviewCandidate], *, now: float | None = None
) -> ConfirmationLedger:
    """Validate confirmation records against ``candidates`` into a new ledger.

    Accepts mappings (for example :func:`.io.read_jsonl` output) or
    :class:`Confirmation` objects. Rejected records, with their input position and
    reason, are on ``ledger.rejects``. Grow the ledger later with
    :meth:`ConfirmationLedger.extend`.
    """
    ledger = ConfirmationLedger(candidates={c.candidate_id: c for c in candidates})
    return ledger.extend(records, now=now)
