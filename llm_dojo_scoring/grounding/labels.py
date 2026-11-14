"""Valid labels derived from the confirmation ledger, with full provenance.

A value becomes a **valid label** only when a person confirms it, or a trusted agent
does with enough certainty and nothing contradicts it. :func:`derive_valid_labels` is
a pure function of the ledger (and the trust gate), recomputed every time: a label
that loses its basis simply is not derived again, and comparing with a previous export
lists it as withdrawn.

Per candidate, only each reviewer's latest confirmation counts:

* **Humans decide** when any human has a latest ``valid`` or ``hallucinated``
  verdict (``unsure`` neither validates nor blocks). Every such human says ``valid``
  with the same value (text equal after casefolding and collapsing whitespace) →
  label (``validity_basis: "human"``); every one says
  ``hallucinated`` → rejected; a mix, or ``valid`` with different values → conflict.
* **Otherwise agents may decide.** An agent's ``valid`` counts only when the gate
  trusted that agent as of its ``confirmed_at`` and its ``certainty`` is at least the
  floor. One or more counting ``valid`` verdicts that agree on the value, and no agent
  ``hallucinated`` → label (``validity_basis: "trusted_agent"``, with the gate
  snapshot id). Agents that disagree → conflict, for a person to settle. Anything
  else → pending, with the reason.

``corrected_value`` becomes the label's value. Without a gate no agent is trusted, so
only human-confirmed labels are derived.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, fields
from typing import Any, Iterable, Mapping, Protocol

from ..config import GroundingSettings, get_settings
from ..metrics.emitter import ScoreRecord
from .audit import SCHEMA_VERSION
from .candidates import ReviewCandidate
from .ledger import AGENT, HALLUCINATED, HUMAN, UNSURE, VALID, Confirmation, ConfirmationLedger

HUMAN_BASIS = "human"
TRUSTED_AGENT_BASIS = "trusted_agent"

# Why a candidate is in ``conflicts``.
HUMANS_DISAGREE = "humans_disagree"
AGENTS_DISAGREE = "agents_disagree"

# Why a candidate is in ``pending``.
ONLY_UNSURE = "only_unsure"
AGENT_UNTRUSTED = "agent_untrusted"
BELOW_CERTAINTY_FLOOR = "below_certainty_floor"
AGENT_HALLUCINATED = "agent_hallucinated"

N_CANDIDATES = "grounding_n_candidates"
N_VALID_LABELS = "grounding_n_valid_labels"
N_LABEL_CONFLICTS = "grounding_n_label_conflicts"

#: The metric ids :func:`label_score_records` emits, in emission order.
METRIC_IDS: tuple[str, ...] = (N_CANDIDATES, N_VALID_LABELS, N_LABEL_CONFLICTS)


class TrustLookup(Protocol):
    """What :func:`derive_valid_labels` needs from a trust gate (``grounding.trust.TrustGate``).

    A gate may also carry a numeric ``certainty_floor``; :func:`derive_valid_labels`
    uses it when given no floor of its own.
    """

    def trusted_snapshot_id(self, ledger: ConfirmationLedger, reviewer_id: str, at: float) -> str | None:
        """Id of the passing snapshot in force for ``reviewer_id`` at ``at``, or ``None``."""
        ...


@dataclass(frozen=True)
class ValidLabel:
    """One confirmed value, ready for the dataset, with who confirmed it and why it counts."""

    doc_id: str
    doc_class: str
    field: str
    item_index: int | None
    value: Any
    source_candidate_id: str
    extractor: str | None
    doc_text_sha256: str | None
    confirmed_by: tuple[dict[str, Any], ...]
    validity_basis: str
    gate_snapshot_id: str | None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        data = asdict(self)
        data["confirmed_by"] = list(data["confirmed_by"])
        return {"schema_version": SCHEMA_VERSION, **data}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidLabel":
        """Rebuild a record from :meth:`as_dict` output; unknown keys are ignored."""
        names = {f.name for f in fields(cls)}
        kwargs = {key: value for key, value in data.items() if key in names}
        kwargs["confirmed_by"] = tuple(dict(entry) for entry in kwargs.get("confirmed_by", ()))
        return cls(**kwargs)


@dataclass(frozen=True)
class LabelDerivation:
    """The outcome for every confirmed candidate.

    ``labels`` are valid labels; ``rejected`` are candidate ids people called
    hallucinated; ``conflicts`` and ``pending`` map candidate ids to a reason;
    ``withdrawn`` are labels of a previous export not derived this time.
    """

    labels: tuple[ValidLabel, ...]
    rejected: tuple[str, ...]
    conflicts: dict[str, str]
    pending: dict[str, str]
    withdrawn: tuple[ValidLabel, ...]

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable outcome, with ``schema_version``."""
        return {
            "schema_version": SCHEMA_VERSION,
            "labels": [label.as_dict() for label in self.labels],
            "rejected": list(self.rejected),
            "conflicts": dict(self.conflicts),
            "pending": dict(self.pending),
            "withdrawn": [label.as_dict() for label in self.withdrawn],
        }


def _provenance(confirmation: Confirmation) -> dict[str, Any]:
    """The provenance entry for one confirmation."""
    return {
        "reviewer_kind": confirmation.reviewer_kind,
        "reviewer_id": confirmation.reviewer_id,
        "verdict": confirmation.verdict,
        "certainty": confirmation.certainty,
        "confirmed_at": confirmation.confirmed_at,
    }


def _label_value(candidate: ReviewCandidate, confirmation: Confirmation) -> Any:
    """The value a ``valid`` confirmation vouches for (its correction, else the candidate's)."""
    return candidate.value if confirmation.corrected_value is None else confirmation.corrected_value


def _agree(candidate: ReviewCandidate, confirmations: list[Confirmation]) -> bool:
    """Whether every ``valid`` confirmation vouches for the same value.

    Strict on purpose: values agree only when their text matches after casefolding
    and collapsing whitespace, so ``$1,250.00`` and ``-1250.00`` (or ``1250``) are a
    disagreement for a person to settle, never silently merged.
    """
    forms = {" ".join(str(_label_value(candidate, c)).casefold().split()) for c in confirmations}
    return len(forms) == 1


def _label(candidate: ReviewCandidate, backing: list[Confirmation], latest: Iterable[Confirmation],
           basis: str, snapshot_id: str | None) -> ValidLabel:
    """The label for ``candidate``, valued by its earliest backing confirmation."""
    first = min(backing, key=lambda c: c.confirmed_at)
    return ValidLabel(
        doc_id=candidate.doc_id, doc_class=candidate.doc_class, field=candidate.field,
        item_index=candidate.item_index, value=_label_value(candidate, first),
        source_candidate_id=candidate.candidate_id, extractor=candidate.extractor,
        doc_text_sha256=candidate.doc_text_sha256,
        confirmed_by=tuple(_provenance(c) for c in sorted(latest, key=lambda c: c.confirmed_at)),
        validity_basis=basis, gate_snapshot_id=snapshot_id,
    )


def derive_valid_labels(
    ledger: ConfirmationLedger,
    gate: TrustLookup | None = None,
    *,
    certainty_floor: float | None = None,
    previous: Iterable[ValidLabel] = (),
) -> LabelDerivation:
    """Apply the validity rules (module docstring) to every confirmed candidate.

    ``gate`` decides which agents were trusted when they confirmed; ``None`` trusts
    no agent. ``certainty_floor`` defaults to the gate's ``certainty_floor`` when it has
    one, else ``get_settings().grounding.certainty_floor`` (0.9 unless configured); an
    explicit floor is validated like the setting (``ValueError`` outside ``[0, 1]``).
    ``previous`` is an earlier export: its labels not derived now are returned as
    ``withdrawn``. Outputs are in candidate-id order.
    """
    if certainty_floor is None:
        certainty_floor = getattr(gate, "certainty_floor", None)
    if certainty_floor is None:
        certainty_floor = get_settings().grounding.certainty_floor
    certainty_floor = GroundingSettings(certainty_floor=certainty_floor).coerced().certainty_floor
    labels: list[ValidLabel] = []
    rejected: list[str] = []
    conflicts: dict[str, str] = {}
    pending: dict[str, str] = {}
    for cid, by_reviewer in sorted(ledger.latest().items()):
        candidate = ledger.candidates[cid]
        latest = list(by_reviewer.values())
        humans = [c for c in latest if c.reviewer_kind == HUMAN and c.verdict != UNSURE]
        if humans:
            valid = [c for c in humans if c.verdict == VALID]
            if len(valid) == len(humans) and _agree(candidate, valid):
                labels.append(_label(candidate, valid, latest, HUMAN_BASIS, None))
            elif not valid:
                rejected.append(cid)
            else:
                conflicts[cid] = HUMANS_DISAGREE
            continue
        agents = [c for c in latest if c.reviewer_kind == AGENT and c.verdict != UNSURE]
        valid = [c for c in agents if c.verdict == VALID]
        if not agents:
            pending[cid] = ONLY_UNSURE
        elif not valid:
            pending[cid] = AGENT_HALLUCINATED
        elif any(c.verdict == HALLUCINATED for c in agents) or not _agree(candidate, valid):
            conflicts[cid] = AGENTS_DISAGREE
        else:
            sure = [c for c in valid if c.certainty is not None and c.certainty >= certainty_floor]
            trusted = [(c, gate.trusted_snapshot_id(ledger, c.reviewer_id, c.confirmed_at))
                       for c in sure] if gate is not None else []
            trusted = [(c, sid) for c, sid in trusted if isinstance(sid, str) and sid]
            if trusted:
                first, snapshot_id = min(trusted, key=lambda pair: pair[0].confirmed_at)
                labels.append(_label(candidate, [first], latest, TRUSTED_AGENT_BASIS, snapshot_id))
            else:
                pending[cid] = AGENT_UNTRUSTED if sure else BELOW_CERTAINTY_FLOOR
    current = {label.source_candidate_id for label in labels}
    withdrawn = tuple(label for label in previous if label.source_candidate_id not in current)
    return LabelDerivation(tuple(labels), tuple(rejected), conflicts, pending, withdrawn)


def label_score_records(
    candidates: Iterable[ReviewCandidate], derivation: LabelDerivation, *, agent: str,
    run_id: str | None = None,
) -> list[ScoreRecord]:
    """Run-level counts: candidates, valid labels (by basis in metadata) and conflicts."""
    basis = Counter(label.validity_basis for label in derivation.labels)
    return [
        ScoreRecord(agent=agent, metric=N_CANDIDATES, value=sum(1 for _ in candidates), run_id=run_id,
                    metadata={"scope": "run"}),
        ScoreRecord(agent=agent, metric=N_VALID_LABELS, value=len(derivation.labels), run_id=run_id,
                    metadata={"scope": "run", "by_basis": {key: basis[key] for key in sorted(basis)}}),
        ScoreRecord(agent=agent, metric=N_LABEL_CONFLICTS, value=len(derivation.conflicts), run_id=run_id,
                    metadata={"scope": "run", "by_reason": dict(Counter(derivation.conflicts.values()))}),
    ]
