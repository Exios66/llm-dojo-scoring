"""How well each agent's confirmations agree with people's (human spot-checks).

A **paired check** is one candidate that an agent and people both decided:

* the agent's side is its blind verdict: its latest confirmation from before people
  first decided the candidate (later revisions never rewrite a pair);
* people's side is their latest confirmations; ``unsure`` from either side is left
  out (a person whose latest word is ``unsure`` no longer counts);
* the human verdict is the people's shared verdict; when people disagree with each
  other the candidate has no human truth and is not paired;
* an agent ``valid`` that people also call ``valid`` but with a different value
  (text unequal after casefolding and collapsing whitespace) is a disagreement:
  the agent vouched for a value people did not.

Per agent (``reviewer_id``), over its latest ``window`` paired checks ordered by
the human's ``confirmed_at``, :func:`reviewer_agreement` reports:

* **valid precision** — of the values the agent called ``valid``, the share people
  also called valid (with the same value), and its Wilson 95% lower bound. This is
  the number that gates trust (owner decision; the gate is ``grounding.trust.TrustGate``);
* **agreement** — the share of paired checks with the same verdict;
* **Cohen's κ** — agreement beyond chance, ``None`` unless both raters used both
  verdicts;
* the same counts per ``doc_class.field``.

:func:`select_spot_checks` picks which agent-decided candidates to send to people, so
the pairs above keep coming: a deterministic sample per agent, seeded by candidate id.

Pairs with the same human time are ordered by candidate id, so the window edge is
deterministic. The precision bound is unrounded (``analysis.bootstrap.wilson_ci``
rounds to four decimals, which could lift 0.94998 to a 0.95 bar), and its
denominator is ``n_agent_valid``, not ``n_checked``: the gate's ``trust_min_n``
counts ``valid`` verdicts, the only pairs that carry precision evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable, Mapping

from ..config import get_settings
from ..metrics.emitter import ScoreRecord
from .audit import SCHEMA_VERSION
from .ledger import AGENT, HALLUCINATED, HUMAN, VALID, Confirmation, ConfirmationLedger

VALID_PRECISION = "grounding_reviewer_valid_precision"
VALID_PRECISION_LOWER_95 = "grounding_reviewer_valid_precision_lower_95"
AGREEMENT = "grounding_reviewer_agreement"
KAPPA = "grounding_reviewer_kappa"
N_CHECKED = "grounding_reviewer_n_checked"

#: The metric ids :func:`agreement_score_records` emits, in emission order.
METRIC_IDS: tuple[str, ...] = (VALID_PRECISION, VALID_PRECISION_LOWER_95, AGREEMENT, KAPPA, N_CHECKED)


def _text(value: Any) -> str:
    """A value compared as text: casefolded, whitespace collapsed."""
    return " ".join(str(value).casefold().split())


@dataclass(frozen=True)
class PairedCheck:
    """One candidate decided by one agent and by people.

    ``human_verdict`` is people's verdict on the value the agent vouched for: when
    both say ``valid`` but for different values, it is ``hallucinated``.
    """

    candidate_id: str
    reviewer_id: str
    field: str
    agent_verdict: str
    human_verdict: str
    agent_confirmed_at: float
    human_confirmed_at: float

    @property
    def agrees(self) -> bool:
        """Whether people gave the agent's verdict."""
        return self.agent_verdict == self.human_verdict


def _decisive(confirmations: Iterable[Confirmation], kind: str) -> list[Confirmation]:
    """Latest ``valid`` / ``hallucinated`` confirmations of one reviewer kind."""
    return [c for c in confirmations if c.reviewer_kind == kind and c.verdict in (VALID, HALLUCINATED)]


def _wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """Unrounded Wilson score lower bound of ``successes / n`` (``n >= 1``).

    The same formula as ``analysis.bootstrap.wilson_ci``, which rounds to four
    decimals: a gate must not let 0.94998 round up to a 0.95 bar.
    """
    p = successes / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - margin)


def paired_checks(ledger: ConfirmationLedger, *, as_of: float | None = None) -> list[PairedCheck]:
    """Every agent/human pair in the ledger, ordered by the human's ``confirmed_at``.

    The human truth is people's latest decisive verdicts. The agent's side is its
    **blind** verdict: its latest confirmation made before people first decided the
    candidate: earlier in the ledger than the first human decision to arrive, and no
    later in ``confirmed_at`` than the earliest human decision time. A
    revision after people decided never rewrites the pair (an agent shown the human
    verdict cannot erase its miss), and a backdated record that arrived after the
    human one does not count. No blind decisive verdict, no pair.

    With ``as_of``, only confirmations made at or before it count. A pair is dated
    by the latest of people's deciding confirmations (when the truth was settled).
    """
    confirmations = [c for c in ledger.confirmations if as_of is None or c.confirmed_at <= as_of]
    if as_of is not None:
        ledger = ConfirmationLedger(candidates=ledger.candidates, confirmations=tuple(confirmations))
    first_human: dict[str, tuple[int, float]] = {}  # earliest arrival, earliest time
    for position, c in enumerate(confirmations):
        if c.reviewer_kind == HUMAN and c.verdict in (VALID, HALLUCINATED):
            seen = first_human.get(c.candidate_id)
            first_human[c.candidate_id] = (position, c.confirmed_at) if seen is None else (
                seen[0], min(seen[1], c.confirmed_at))
    blind: dict[tuple[str, str], Confirmation] = {}
    for position, c in enumerate(confirmations):
        if c.reviewer_kind != AGENT or c.candidate_id not in first_human:
            continue
        human_position, human_at = first_human[c.candidate_id]
        if position > human_position or c.confirmed_at > human_at:
            continue
        key = (c.candidate_id, c.reviewer_id)
        if key not in blind or c.confirmed_at >= blind[key].confirmed_at:
            blind[key] = c
    agents_by_candidate: dict[str, list[Confirmation]] = defaultdict(list)
    for (cid, _), c in blind.items():
        if c.verdict in (VALID, HALLUCINATED):
            agents_by_candidate[cid].append(c)

    pairs: list[PairedCheck] = []
    for cid, by_reviewer in ledger.latest().items():
        if cid not in agents_by_candidate:
            continue
        candidate = ledger.candidates[cid]

        def vouched(c: Confirmation) -> str:
            """The value a confirmation vouches for, as compared text."""
            return _text(candidate.value if c.corrected_value is None else c.corrected_value)

        humans = _decisive(by_reviewer.values(), HUMAN)
        if not humans or len({c.verdict for c in humans}) > 1:
            continue  # no human verdict, or people disagree: no truth to pair with
        human_values = {vouched(c) for c in humans}
        if humans[0].verdict == VALID and len(human_values) > 1:
            continue  # people agree it is valid but not on the value
        human_at = max(c.confirmed_at for c in humans)
        for agent in agents_by_candidate[cid]:
            human_verdict = humans[0].verdict
            if human_verdict == VALID and agent.verdict == VALID and vouched(agent) not in human_values:
                human_verdict = HALLUCINATED  # people did not confirm the agent's value
            pairs.append(PairedCheck(
                candidate_id=cid, reviewer_id=agent.reviewer_id,
                field=f"{candidate.doc_class}.{candidate.field}",
                agent_verdict=agent.verdict, human_verdict=human_verdict,
                agent_confirmed_at=agent.confirmed_at, human_confirmed_at=human_at,
            ))
    pairs.sort(key=lambda p: (p.human_confirmed_at, p.candidate_id, p.reviewer_id))
    return pairs


@dataclass(frozen=True)
class AgreementCounts:
    """Paired-check counts for one agent, or one agent on one field."""

    n_checked: int = 0
    n_agent_valid: int = 0
    n_valid_confirmed: int = 0
    n_agree: int = 0
    n_agent_hallucinated: int = 0
    n_human_valid: int = 0

    @property
    def valid_precision(self) -> float | None:
        """Share of the agent's ``valid`` verdicts people also called valid."""
        return self.n_valid_confirmed / self.n_agent_valid if self.n_agent_valid else None

    @property
    def valid_precision_lower_95(self) -> float | None:
        """Unrounded Wilson 95% lower bound of :attr:`valid_precision` (what the gate compares)."""
        if not self.n_agent_valid:
            return None
        return _wilson_lower(self.n_valid_confirmed, self.n_agent_valid)

    @property
    def agreement(self) -> float | None:
        """Share of paired checks where people gave the agent's verdict."""
        return self.n_agree / self.n_checked if self.n_checked else None

    @property
    def kappa(self) -> float | None:
        """Cohen's κ between agent and people; ``None`` unless both used both verdicts."""
        n = self.n_checked
        agent_valid, human_valid = self.n_agent_valid, self.n_human_valid
        if not (0 < agent_valid < n and 0 < human_valid < n):
            return None
        expected = (agent_valid * human_valid + (n - agent_valid) * (n - human_valid)) / (n * n)
        return (self.n_agree / n - expected) / (1 - expected)

    def as_dict(self) -> dict[str, Any]:
        """Counts and rates as plain data."""
        return {**asdict(self), "valid_precision": self.valid_precision,
                "valid_precision_lower_95": self.valid_precision_lower_95,
                "agreement": self.agreement, "kappa": self.kappa}


def _count(pairs: Iterable[PairedCheck]) -> AgreementCounts:
    """Fold paired checks into counts."""
    n = valid = confirmed = agree = hallucinated = human_valid = 0
    for pair in pairs:
        n += 1
        agree += pair.agrees
        human_valid += pair.human_verdict == VALID
        if pair.agent_verdict == VALID:
            valid += 1
            confirmed += pair.human_verdict == VALID
        else:
            hallucinated += 1
    return AgreementCounts(n, valid, confirmed, agree, hallucinated, human_valid)


@dataclass(frozen=True)
class ReviewerAgreement:
    """One agent's agreement with people over its window of paired checks."""

    reviewer_id: str
    window: int
    window_start: float | None
    window_end: float | None
    overall: AgreementCounts
    by_field: Mapping[str, AgreementCounts] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {
            "schema_version": SCHEMA_VERSION, "reviewer_id": self.reviewer_id,
            "window": self.window, "window_start": self.window_start, "window_end": self.window_end,
            "overall": self.overall.as_dict(),
            "by_field": {name: counts.as_dict() for name, counts in self.by_field.items()},
        }


def reviewer_agreement(
    ledger: ConfirmationLedger, *, window: int | None = None, as_of: float | None = None
) -> dict[str, ReviewerAgreement]:
    """Agreement per agent over its latest ``window`` paired checks (sorted by reviewer id).

    ``window`` defaults to ``get_settings().grounding.trust_window``. With
    ``as_of``, only what was known at that time counts (see :func:`paired_checks`).
    An agent with no paired check is not listed.
    """
    if window is None:
        window = get_settings().grounding.trust_window
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError(f"window must be a whole number >= 1, got {window!r}")
    by_agent: dict[str, list[PairedCheck]] = defaultdict(list)
    for pair in paired_checks(ledger, as_of=as_of):
        by_agent[pair.reviewer_id].append(pair)
    return {reviewer_id: _agreement_over(reviewer_id, by_agent[reviewer_id], window)
            for reviewer_id in sorted(by_agent)}


def _agreement_over(reviewer_id: str, pairs: list[PairedCheck], window: int) -> ReviewerAgreement:
    """One agent's agreement over the last ``window`` of its non-empty, ordered ``pairs``."""
    recent = pairs[-window:]
    fields_: dict[str, list[PairedCheck]] = defaultdict(list)
    for pair in recent:
        fields_[pair.field].append(pair)
    return ReviewerAgreement(
        reviewer_id=reviewer_id, window=window,
        window_start=recent[0].human_confirmed_at, window_end=recent[-1].human_confirmed_at,
        overall=_count(recent),
        by_field={name: _count(fields_[name]) for name in sorted(fields_)},
    )


def agreement_score_records(
    agreements: Mapping[str, ReviewerAgreement], *, agent: str, run_id: str | None = None
) -> list[ScoreRecord]:
    """The five ``grounding_reviewer_*`` metrics per reviewer (``reviewer_id`` in metadata)."""
    records: list[ScoreRecord] = []
    for reviewer_id, result in agreements.items():
        counts = result.overall
        values = (
            (VALID_PRECISION, counts.valid_precision, counts.n_agent_valid),
            (VALID_PRECISION_LOWER_95, counts.valid_precision_lower_95, counts.n_agent_valid),
            (AGREEMENT, counts.agreement, counts.n_checked),
            (KAPPA, counts.kappa, counts.n_checked),
            (N_CHECKED, counts.n_checked, counts.n_checked),
        )
        records += [
            ScoreRecord(agent=agent, metric=metric, value=value, run_id=run_id,
                        metadata={"scope": "reviewer", "reviewer_id": reviewer_id,
                                  "window": result.window, "denominator": denominator})
            for metric, value, denominator in values
        ]
    return records


def _draw(seed: int, reviewer_id: str, candidate_id: str) -> float:
    """A fixed pseudo-random number in ``[0, 1)`` for one agent and candidate."""
    payload = json.dumps([seed, reviewer_id, candidate_id], separators=(",", ":"))
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16) / 2.0 ** 64


def select_spot_checks(
    ledger: ConfirmationLedger, *, rate: float | None = None, min_per_agent: int | None = None,
    seed: int = 0,
) -> list[str]:
    """Candidate ids to send to people for spot-checks, in candidate-id order.

    For each agent, the eligible candidates are those whose latest confirmation by that
    agent is ``valid`` or ``hallucinated`` and that no person has decided yet (a person
    whose latest word is ``unsure`` has not decided). Each gets a fixed draw in
    ``[0, 1)`` from ``sha256([seed, reviewer_id, candidate_id])``; a draw below ``rate``
    is sampled, so a candidate's selection never changes as the ledger grows. When that
    gives an agent fewer than ``min_per_agent``, its lowest remaining draws top it up (or
    all its eligible candidates, if fewer). A candidate sampled for several agents is
    listed once.

    ``rate`` and ``min_per_agent`` default to ``grounding.spot_check_rate`` and
    ``grounding.spot_check_min_per_agent`` and are validated like them; ``seed`` must
    be a whole number.
    """
    overrides = {key: value for key, value in (
        ("spot_check_rate", rate), ("spot_check_min_per_agent", min_per_agent)) if value is not None}
    checked = replace(get_settings().grounding, **overrides)
    checked.validate()
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be a whole number, got {seed!r}")
    rate, minimum = float(checked.spot_check_rate), int(checked.spot_check_min_per_agent)
    eligible: dict[str, list[str]] = defaultdict(list)
    for cid, by_reviewer in ledger.latest().items():
        if _decisive(by_reviewer.values(), HUMAN):
            continue
        for c in _decisive(by_reviewer.values(), AGENT):
            eligible[c.reviewer_id].append(cid)
    chosen: set[str] = set()
    for reviewer_id, cids in eligible.items():
        ranked = sorted(cids, key=lambda cid: (_draw(seed, reviewer_id, cid), cid))
        drawn = [cid for cid in ranked if _draw(seed, reviewer_id, cid) < rate]
        chosen.update(ranked[:max(len(drawn), minimum)])
    return sorted(chosen)
