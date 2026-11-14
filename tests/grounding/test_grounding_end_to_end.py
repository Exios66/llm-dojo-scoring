"""Unlabelled-value grounding end to end: audit → candidates → ledger → spot-checks → gate → labels."""

from __future__ import annotations

import pytest
from grounding_inputs import DOC_TEXT

from llm_dojo_scoring.config import clear_settings_cache
from llm_dojo_scoring.grounding.agreement import reviewer_agreement, select_spot_checks
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import review_candidates
from llm_dojo_scoring.grounding.io import read_jsonl, write_jsonl
from llm_dojo_scoring.grounding.labels import (
    AGENT_UNTRUSTED,
    HUMAN_BASIS,
    TRUSTED_AGENT_BASIS,
    ValidLabel,
    derive_valid_labels,
)
from llm_dojo_scoring.grounding.ledger import ingest_confirmations
from llm_dojo_scoring.grounding.trust import TrustGate


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Every test starts on default settings."""
    clear_settings_cache()
    yield
    clear_settings_cache()


def _audits(n):
    """Synthetic extractions with one unlabelled ``adjuster`` value per document."""
    audits = []
    for i in range(n):
        audits += audit_unlabelled_values({}, {"adjuster": f"Robin Example {i}"}, doc_class="insurance_claim",
                                          doc_text=DOC_TEXT, doc_id=f"doc-{i}", extractor="insurance_claims_specialist")
    return audits


def _agent(cid, at):
    """The boss confirming a value as valid."""
    return {"candidate_id": cid, "verdict": "valid", "reviewer_kind": "agent", "reviewer_id": "boss@v1",
            "certainty": 0.97, "confirmed_at": at}


def _human(cid, at):
    """A person confirming a value as valid."""
    return {"candidate_id": cid, "verdict": "valid", "reviewer_kind": "human", "reviewer_id": "human:a",
            "confirmed_at": at}


def test_spot_checked_agent_earns_trust_and_its_later_verdicts_become_labels(tmp_path):
    """The whole loop, with the ledger round-tripped through JSONL between steps."""
    candidates = review_candidates(_audits(40))
    assert len(candidates) == 40
    ids = [c.candidate_id for c in candidates]
    path = tmp_path / "ledger.jsonl"

    # Round 1: the boss confirms the first 30; every one is sent to people.
    write_jsonl([_agent(cid, 10.0) for cid in ids[:30]], path)
    ledger = ingest_confirmations(read_jsonl(path), candidates, now=1e6)
    default = select_spot_checks(ledger)  # 10% drawn, topped up to 20 (nothing checked yet)
    assert len(default) == 20 and set(default) <= set(ids[:30])
    sample = select_spot_checks(ledger, rate=1.0, min_per_agent=0)
    assert sample == sorted(ids[:30])
    write_jsonl([_human(cid, 20.0 + i) for i, cid in enumerate(sample)], path, append=True)

    # Round 2: once trusted, the boss confirms the rest; nobody checks them.
    write_jsonl([_agent(cid, 100.0) for cid in ids[30:]], path, append=True)
    ledger = ingest_confirmations(read_jsonl(path), candidates, now=1e6)
    gate = TrustGate(bar=0.85, min_n=25)
    assert reviewer_agreement(ledger)["boss@v1"].overall.n_valid_confirmed == 30
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 10.0) is None
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 100.0)

    result = derive_valid_labels(ledger, gate)
    basis = {label.source_candidate_id: label.validity_basis for label in result.labels}
    assert {cid for cid, b in basis.items() if b == HUMAN_BASIS} == set(ids[:30])
    assert {cid for cid, b in basis.items() if b == TRUSTED_AGENT_BASIS} == set(ids[30:])
    assert result.pending == {} and result.conflicts == {} and gate.regressions(ledger, result.labels) == []

    # Labels survive export and come back unchanged.
    write_jsonl([label.as_dict() for label in result.labels], tmp_path / "labels.jsonl")
    assert tuple(ValidLabel.from_dict(row) for row in read_jsonl(tmp_path / "labels.jsonl")) == result.labels


def test_without_spot_checks_agent_verdicts_stay_pending():
    """No human check, no trust: agent-only confirmations never become labels."""
    candidates = review_candidates(_audits(10))
    ledger = ingest_confirmations([_agent(c.candidate_id, 1.0) for c in candidates], candidates, now=1e6)
    result = derive_valid_labels(ledger, TrustGate())
    assert result.labels == ()
    assert set(result.pending.values()) == {AGENT_UNTRUSTED}
