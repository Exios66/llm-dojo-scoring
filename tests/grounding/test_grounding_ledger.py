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
    ({"candidate_id": ["x"]}, "unknown candidate_id"),
    ({"candidate_id": {"a": 1}}, "unknown candidate_id"),
    ({"reviewer_id": "boss@v3"}, "must start with 'human:'"),
    ({"reviewer_kind": "agent", "reviewer_id": "human:b", "certainty": 0.9}, "must not start with"),
    ({"confirmed_at": 1e300}, "in the future"),
    ({"confirmed_at": float("nan")}, "confirmed_at"),
    ({"corrected_value": ""}, "must not be blank"),
    ({"corrected_value": False}, "non-blank text or a finite number"),
    ({"corrected_value": float("nan")}, "non-blank text or a finite number"),
    ({"corrected_value": []}, "non-blank text or a finite number"),
    ({"corrected_value": {"a": 1}}, "non-blank text or a finite number"),
])
def test_invalid_records_are_rejected_with_a_reason(overrides, reason):
    """Every invalid record is kept as a reject with its reason, never dropped."""
    ledger = ingest_confirmations([_record(**overrides)], CANDIDATES.values())
    assert ledger.confirmations == ()
    (reject,) = ledger.rejects
    assert reject.index == 0
    assert re.search(reason, reject.reason)
    assert reject.as_dict()["record"].keys() == _record(**overrides).keys()


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


def test_now_bounds_confirmed_at():
    """confirmed_at may run up to a day ahead of now, not more."""
    ok = ingest_confirmations([_record(confirmed_at=1000 + 86_000)], CANDIDATES.values(), now=1000)
    late = ingest_confirmations([_record(confirmed_at=1000 + 90_000)], CANDIDATES.values(), now=1000)
    assert (len(ok.confirmations), len(late.rejects)) == (1, 1)


def test_numeric_and_text_corrections_accepted():
    """A finite number or non-blank text is a usable correction."""
    ledger = ingest_confirmations([_record(corrected_value=12.5), _record(corrected_value="Robin X")],
                                  CANDIDATES.values())
    assert [c.corrected_value for c in ledger.confirmations] == [12.5, "Robin X"]
