"""Valid-label derivation: human and trusted-agent rules, conflicts, pending, withdrawals."""

from __future__ import annotations

from grounding_inputs import sample_candidates

from llm_dojo_scoring.grounding.labels import (
    METRIC_IDS,
    ValidLabel,
    derive_valid_labels,
    label_score_records,
)
from llm_dojo_scoring.grounding.ledger import ingest_confirmations

CANDIDATES = sample_candidates()
CID = CANDIDATES["adjuster"].candidate_id


class FakeGate:
    """Trusts the listed agents from ``since`` on, under one snapshot id."""

    def __init__(self, *agents, since=0.0):
        """Remember which agents are trusted and from when."""
        self.agents, self.since = set(agents), since

    def trusted_snapshot_id(self, ledger, reviewer_id, at):
        """The snapshot id while trusted, else None."""
        return f"snap:{reviewer_id}" if reviewer_id in self.agents and at >= self.since else None


def human(verdict, who="human:a", at=100, **extra):
    """A human confirmation of the adjuster candidate."""
    return {"candidate_id": CID, "verdict": verdict, "reviewer_kind": "human",
            "reviewer_id": who, "confirmed_at": at, **extra}


def agent(verdict, who="boss@v1", at=100, certainty=0.95, **extra):
    """An agent confirmation of the adjuster candidate."""
    return {"candidate_id": CID, "verdict": verdict, "reviewer_kind": "agent",
            "reviewer_id": who, "confirmed_at": at, "certainty": certainty, **extra}


def derive(*records, gate=None, **kwargs):
    """Derive labels from these confirmation records."""
    return derive_valid_labels(ingest_confirmations(records, CANDIDATES.values()), gate, **kwargs)


def test_human_valid_makes_a_label_with_provenance():
    """One human valid → a human-basis label carrying the candidate's provenance."""
    (label,) = derive(human("valid")).labels
    assert (label.value, label.validity_basis, label.gate_snapshot_id) == ("Robin Example", "human", None)
    assert (label.doc_id, label.field, label.source_candidate_id) == ("d1", "adjuster", CID)
    assert label.extractor == "insurance_claims_specialist"
    assert label.confirmed_by == ({"reviewer_kind": "human", "reviewer_id": "human:a",
                                   "verdict": "valid", "certainty": None, "confirmed_at": 100.0},)


def test_human_hallucinated_rejects():
    """Every human says hallucinated → rejected, no label."""
    result = derive(human("hallucinated"), human("hallucinated", who="human:b"))
    assert (result.labels, result.rejected, result.conflicts) == ((), (CID,), {})


def test_humans_disagree_is_a_conflict():
    """valid against hallucinated, or two different corrections, is a conflict."""
    assert derive(human("valid"), human("hallucinated", who="human:b")).conflicts == {CID: "humans_disagree"}
    assert derive(human("valid", corrected_value="Robin Ex"),
                  human("valid", who="human:b", corrected_value="R. Example")).conflicts == {
        CID: "humans_disagree"}


def test_matching_corrections_become_the_value():
    """Corrections equal in normal form agree; the earliest backing correction is the value."""
    (label,) = derive(human("valid", corrected_value="Robin  Exemplar", at=10),
                      human("valid", who="human:b", corrected_value="robin exemplar", at=20)).labels
    assert label.value == "Robin  Exemplar"


def test_human_unsure_neither_validates_nor_blocks():
    """A human unsure leaves the decision to the agents."""
    result = derive(human("unsure"), agent("valid"), gate=FakeGate("boss@v1"))
    assert result.labels[0].validity_basis == "trusted_agent"
    assert derive(human("unsure")).pending == {CID: "only_unsure"}


def test_human_overrides_agents():
    """A human hallucinated removes a label agents had made valid."""
    gate = FakeGate("boss@v1")
    assert derive(agent("valid"), gate=gate).labels
    later = derive(agent("valid"), human("hallucinated", at=200), gate=gate)
    assert (later.labels, later.rejected) == ((), (CID,))


def test_trusted_agent_label_names_its_snapshot():
    """A trusted, certain agent valid → a trusted_agent label with the snapshot id."""
    (label,) = derive(agent("valid", corrected_value="Robin Q. Example"), gate=FakeGate("boss@v1")).labels
    assert (label.validity_basis, label.gate_snapshot_id) == ("trusted_agent", "snap:boss@v1")
    assert label.value == "Robin Q. Example"


def test_agent_pending_reasons():
    """Untrusted, uncertain or hallucinated-only agent verdicts stay pending."""
    assert derive(agent("valid")).pending == {CID: "agent_untrusted"}
    assert derive(agent("valid"), gate=FakeGate("jev-1")).pending == {CID: "agent_untrusted"}
    assert derive(agent("valid"), gate=FakeGate("boss@v1", since=500)).pending == {CID: "agent_untrusted"}
    assert derive(agent("valid", certainty=0.5), gate=FakeGate("boss@v1")).pending == {
        CID: "below_certainty_floor"}
    assert derive(agent("valid", certainty=0.5), gate=FakeGate("boss@v1"),
                  certainty_floor=0.5).labels
    assert derive(agent("hallucinated"), gate=FakeGate("boss@v1")).pending == {CID: "agent_hallucinated"}


def test_agents_disagree_is_a_conflict():
    """One agent valid and another hallucinated, or different corrections, is a conflict."""
    gate = FakeGate("boss@v1", "jev-1")
    assert derive(agent("valid"), agent("hallucinated", who="jev-1"), gate=gate).conflicts == {
        CID: "agents_disagree"}
    assert derive(agent("valid", corrected_value="A"), agent("valid", who="jev-1", corrected_value="B"),
                  gate=gate).conflicts == {CID: "agents_disagree"}


def test_change_of_mind_uses_the_latest_verdict():
    """A reviewer's later confirmation replaces the earlier one."""
    assert derive(human("valid", at=1), human("hallucinated", at=2)).rejected == (CID,)
    assert derive(human("hallucinated", at=1), human("valid", at=2)).labels


def test_withdrawn_lists_previous_labels_not_derived_again():
    """A previous label whose basis is gone is listed as withdrawn."""
    gate = FakeGate("boss@v1")
    before = derive(agent("valid"), gate=gate).labels
    after = derive(agent("valid"), human("hallucinated", at=200), gate=gate, previous=before)
    assert after.withdrawn == before
    assert derive(agent("valid"), gate=gate, previous=before).withdrawn == ()


def test_round_trip_and_score_records():
    """Labels round-trip through as_dict, and the run counts are emitted."""
    result = derive(human("valid"))
    (label,) = result.labels
    assert ValidLabel.from_dict(label.as_dict()) == label
    assert result.as_dict()["labels"][0]["schema_version"] == 1
    records = label_score_records(CANDIDATES.values(), result, agent="insurance_claims_specialist",
                                  run_id="r1")
    assert [(r.metric, r.value) for r in records] == list(zip(METRIC_IDS, (3, 1, 0)))
    assert records[1].metadata["by_basis"] == {"human": 1}


def test_differently_spelled_amounts_conflict():
    """On a money field, ``$1,250.00`` against ``-1250.00`` is a conflict, never merged."""
    amount = CANDIDATES["claimed_amount"].candidate_id
    result = derive(human("valid", candidate_id=amount),
                    human("valid", who="human:b", candidate_id=amount, corrected_value="-1250.00"))
    assert (result.labels, result.conflicts) == ((), {amount: "humans_disagree"})


def test_blank_snapshot_id_is_not_trust():
    """A gate that returns an empty snapshot id does not trust the agent."""

    class BlankGate:
        """Returns an empty snapshot id."""

        def trusted_snapshot_id(self, ledger, reviewer_id, at):
            """Always blank."""
            return ""

    assert derive(agent("valid"), gate=BlankGate()).pending == {CID: "agent_untrusted"}
