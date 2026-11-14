"""Confirmation validation and the append-only ledger."""

from __future__ import annotations

import re

import pytest
from grounding_inputs import sample_candidates

from llm_dojo_scoring.grounding.ledger import Confirmation, ingest_confirmations

CANDIDATES = sample_candidates()
CID = CANDIDATES["adjuster"].candidate_id


def _record(**overrides):
    """A valid human confirmation of the adjuster candidate, with overrides."""
    record = {"candidate_id": CID, "verdict": "valid", "reviewer_kind": "human",
              "reviewer_id": "human:a", "confirmed_at": 100}
    record.update(overrides)
    return record


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"candidate_id": "nope"}, "unknown candidate_id"),
    ({"verdict": "maybe"}, "verdict must be one of"),
    ({"reviewer_kind": "robot"}, "reviewer_kind must be one of"),
    ({"reviewer_id": " "}, "missing reviewer_id"),
    ({"reviewer_id": None}, "missing reviewer_id"),
    ({"confirmed_at": "yesterday"}, "confirmed_at"),
    ({"confirmed_at": True}, "confirmed_at"),
    ({"reviewer_kind": "agent", "reviewer_id": "boss@v1"}, "needs a certainty"),
    ({"reviewer_kind": "agent", "reviewer_id": "boss@v1", "certainty": 1.5}, r"in \[0, 1\]"),
    ({"certainty": 0.9}, "carries no certainty"),
    ({"note": 3}, "note must be text"),
])
def test_invalid_records_are_rejected_with_a_reason(overrides, reason):
    """Every invalid record is kept as a reject with its reason, never dropped."""
    ledger = ingest_confirmations([_record(**overrides)], CANDIDATES.values())
    assert ledger.confirmations == ()
    (reject,) = ledger.rejects
    assert reject.index == 0
    assert re.search(reason, reject.reason)
    assert reject.as_dict()["record"] == _record(**overrides)


def test_non_mapping_rejected():
    """A record that is not a mapping is rejected."""
    ledger = ingest_confirmations(["oops"], CANDIDATES.values())
    assert ledger.rejects[0].reason == "not a mapping (str)"


def test_accepts_confirmation_objects_and_agent_records():
    """Confirmation objects and agent records with a certainty are accepted."""
    ledger = ingest_confirmations(
        [Confirmation(CID, "valid", "human", "human:a", 1.0),
         _record(reviewer_kind="agent", reviewer_id="boss@v1", certainty=0.95, note="ok")],
        CANDIDATES.values(),
    )
    assert ledger.rejects == ()
    assert [c.reviewer_id for c in ledger.confirmations] == ["human:a", "boss@v1"]
    assert ledger.confirmations[1].certainty == 0.95


def test_latest_per_reviewer_and_tie_goes_to_later():
    """Only each reviewer's latest confirmation counts; on a tie the later record wins."""
    ledger = ingest_confirmations(
        [_record(confirmed_at=200, verdict="hallucinated"), _record(confirmed_at=100),
         _record(reviewer_id="human:b", confirmed_at=50, verdict="valid"),
         _record(reviewer_id="human:b", confirmed_at=50, verdict="unsure")],
        CANDIDATES.values(),
    )
    latest = ledger.latest()[CID]
    assert latest["human:a"].verdict == "hallucinated"
    assert latest["human:b"].verdict == "unsure"


def test_extend_appends_and_leaves_the_original_unchanged():
    """extend returns a new ledger; reject indexes count every record ingested."""
    first = ingest_confirmations([_record()], CANDIDATES.values())
    second = first.extend([_record(verdict="bad"), _record(confirmed_at=300)])
    assert len(first.confirmations) == 1 and first.rejects == ()
    assert len(second.confirmations) == 2
    assert second.rejects[0].index == 1
