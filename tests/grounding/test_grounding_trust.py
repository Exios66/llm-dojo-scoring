"""The trust gate: thresholds, trust as of each confirmation, snapshots and the regression guard."""

from __future__ import annotations

import json
import random

import pytest
from grounding_inputs import DOC_TEXT

from llm_dojo_scoring.config import clear_settings_cache, configure
from llm_dojo_scoring.grounding.agreement import AgreementCounts, ReviewerAgreement, reviewer_agreement
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import review_candidates
from llm_dojo_scoring.grounding.labels import (
    AGENT_UNTRUSTED,
    BELOW_CERTAINTY_FLOOR,
    TRUSTED_AGENT_BASIS,
    derive_valid_labels,
)
from llm_dojo_scoring.grounding.ledger import ingest_confirmations
from llm_dojo_scoring.grounding.trust import GateSnapshot, TrustGate


def _candidates(n):
    """``n`` synthetic candidates on one field, ``doc-0`` … ``doc-{n-1}``."""
    audits = []
    for i in range(n):
        audits += audit_unlabelled_values({}, {"adjuster": f"Robin Example {i}"},
                                          doc_class="insurance_claim", doc_text=DOC_TEXT, doc_id=f"doc-{i}")
    return review_candidates(audits)


def _ledger(candidates, rows):
    """A ledger from ``(index, kind, reviewer, verdict, at[, certainty])`` rows."""
    records = []
    for index, kind, reviewer, verdict, at, *certainty in rows:
        record = {"candidate_id": candidates[index].candidate_id, "verdict": verdict,
                  "reviewer_kind": kind, "reviewer_id": reviewer, "confirmed_at": at}
        if kind == "agent":
            record["certainty"] = certainty[0] if certainty else 0.95
        records.append(record)
    ledger = ingest_confirmations(records, candidates, now=1e6)
    assert ledger.rejects == ()
    return ledger


def _checks(start, outcomes, *, reviewer="boss@v1", t0=0):
    """Spot-checked candidates ``start…``: the agent says valid, a person gives ``outcome``."""
    rows = []
    for offset, outcome in enumerate(outcomes):
        index, at = start + offset, t0 + 2 * offset
        rows += [(index, "agent", reviewer, "valid", at), (index, "human", "human:a", outcome, at + 1)]
    return rows


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Every test starts on default settings."""
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_defaults_come_from_settings_and_are_validated():
    """The gate reads ``grounding`` settings; overrides are checked together."""
    gate = TrustGate()
    assert (gate.bar, gate.min_n, gate.window, gate.certainty_floor) == (0.95, 50, 200, 0.9)
    configure(grounding__trust_bar=0.9, grounding__trust_min_n=10)
    assert (TrustGate().bar, TrustGate().min_n) == (0.9, 10)
    assert TrustGate(bar=0.8).bar == 0.8
    assert (TrustGate(min_n=5.0, window=10.0).min_n, type(TrustGate(min_n=5.0).min_n)) == (5, int)
    for bad in ({"bar": 1.5}, {"min_n": 0}, {"window": 5, "min_n": 10}, {"bar": float("nan")}):
        with pytest.raises(ValueError):
            TrustGate(**bad)


def test_default_bar_needs_73_clean_checks():
    """With the 0.95 bar a perfect record passes only at n = 73 (Wilson bound 1 / (1 + z²/n))."""
    c = _candidates(73)
    gate = TrustGate()
    almost = _ledger(c, _checks(0, ["valid"] * 72))
    assert not gate.history(almost)[-1].trusted
    assert gate.history(almost)[-1].valid_precision_lower_95 == pytest.approx(1 / (1 + 1.96 ** 2 / 72))
    passed = _ledger(c, _checks(0, ["valid"] * 73))
    assert TrustGate().history(passed)[-1].trusted


def test_min_n_counts_valid_verdicts():
    """Below ``min_n`` valid verdicts an agent is untrusted, however precise."""
    c = _candidates(5)
    gate = TrustGate(bar=0.5, min_n=5)
    assert not gate.history(_ledger(c, _checks(0, ["valid"] * 4)))[-1].trusted
    snapshots = TrustGate(bar=0.5, min_n=5).history(_ledger(c, _checks(0, ["valid"] * 5)))
    assert [s.trusted for s in snapshots] == [False] * 4 + [True]
    assert [s.effective_at for s in snapshots] == [1, 3, 5, 7, 9]


def test_trust_is_judged_as_of_each_confirmation():
    """An agent verdict made before it earned trust stays pending; one made after is a label."""
    c = _candidates(7)
    rows = _checks(0, ["valid"] * 5) + [(5, "agent", "boss@v1", "valid", 4), (6, "agent", "boss@v1", "valid", 20)]
    ledger = _ledger(c, rows)
    gate = TrustGate(bar=0.5, min_n=5)
    result = derive_valid_labels(ledger, gate)
    assert result.pending == {c[5].candidate_id: AGENT_UNTRUSTED}
    (label,) = [x for x in result.labels if x.validity_basis == TRUSTED_AGENT_BASIS]
    assert label.source_candidate_id == c[6].candidate_id
    assert label.gate_snapshot_id == gate.history(ledger)[-1].snapshot_id
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 8.9) is None
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 9) == label.gate_snapshot_id


def test_new_version_and_people_are_never_trusted():
    """A different ``reviewer_id`` starts untrusted; a ``human:`` id is never gated."""
    c = _candidates(5)
    ledger = _ledger(c, _checks(0, ["valid"] * 5))
    gate = TrustGate(bar=0.5, min_n=5)
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 100)
    assert gate.trusted_snapshot_id(ledger, "boss@v2", 100) is None
    assert gate.trusted_snapshot_id(ledger, "human:a", 100) is None


def test_gate_certainty_floor_is_used_by_label_derivation():
    """``derive_valid_labels`` takes the gate's floor when it is given none."""
    c = _candidates(6)
    ledger = _ledger(c, _checks(0, ["valid"] * 5) + [(5, "agent", "boss@v1", "valid", 20, 0.85)])
    strict = derive_valid_labels(ledger, TrustGate(bar=0.5, min_n=5))
    assert strict.pending == {c[5].candidate_id: BELOW_CERTAINTY_FLOOR}
    lenient = derive_valid_labels(ledger, TrustGate(bar=0.5, min_n=5, certainty_floor=0.8))
    assert c[5].candidate_id in {x.source_candidate_id for x in lenient.labels}
    assert derive_valid_labels(ledger, TrustGate(bar=0.5, min_n=5, certainty_floor=0.8),
                               certainty_floor=0.9).pending == strict.pending


def test_regression_guard_lists_labels_from_the_passing_run():
    """A fall below the bar lists the labels that rested on the agent's earlier trust."""
    c = _candidates(9)
    rows = (_checks(0, ["valid"] * 5) + [(5, "agent", "boss@v1", "valid", 20), (6, "agent", "boss@v1", "valid", 22)]
            + _checks(7, ["hallucinated"], t0=30) + [(8, "agent", "boss@v1", "valid", 40)])
    ledger = _ledger(c, rows)
    gate = TrustGate(bar=0.5, min_n=5)
    result = derive_valid_labels(ledger, gate)
    trusted = sorted(x.source_candidate_id for x in result.labels if x.validity_basis == TRUSTED_AGENT_BASIS)
    assert trusted == sorted([c[5].candidate_id, c[6].candidate_id])
    assert result.pending == {c[8].candidate_id: AGENT_UNTRUSTED}
    (regression,) = gate.regressions(ledger, result.labels)
    assert regression.reviewer_id == "boss@v1" and not regression.failed.trusted
    assert regression.failed.effective_at == 31
    assert sorted(x.source_candidate_id for x in regression.labels) == trusted
    assert all(x.validity_basis == TRUSTED_AGENT_BASIS for x in regression.labels)
    assert json.loads(json.dumps(regression.as_dict()))["schema_version"] == 1


def test_thresholds_are_read_only_and_ids_ignore_int_vs_float():
    """``bar=1`` and ``bar=1.0`` give the same ids; thresholds cannot change under the cache."""
    c = _candidates(5)
    ledger = _ledger(c, _checks(0, ["valid"] * 5))
    ids = [s.snapshot_id for s in TrustGate(bar=1, min_n=5).history(ledger)]
    assert ids == [s.snapshot_id for s in TrustGate(bar=1.0, min_n=5).history(ledger)]
    gate = TrustGate()
    with pytest.raises(AttributeError):
        gate.bar = 0.5


def test_snapshots_are_deterministic_and_round_trip():
    """Same evidence, same ids; ids change with the thresholds; records round-trip."""
    c = _candidates(5)
    ledger = _ledger(c, _checks(0, ["valid"] * 5))
    first = TrustGate(bar=0.5, min_n=5).history(ledger)
    assert [s.snapshot_id for s in first] == [s.snapshot_id for s in TrustGate(bar=0.5, min_n=5).history(ledger)]
    assert first[-1].snapshot_id != TrustGate(bar=0.5, min_n=4).history(ledger)[-1].snapshot_id
    assert len({s.snapshot_id for s in first}) == len(first)
    data = json.loads(json.dumps(first[-1].as_dict()))
    assert data["schema_version"] == 1
    assert GateSnapshot.from_dict({**data, "future_key": 1}) == first[-1]


def test_unchanged_numbers_make_no_new_snapshot():
    """A human confirmation that changes no agent's numbers adds no snapshot."""
    c = _candidates(3)
    rows = _checks(0, ["valid"] * 2) + [(2, "human", "human:b", "valid", 50)]
    snapshots = TrustGate(bar=0.5, min_n=1).history(_ledger(c, rows))
    assert [s.effective_at for s in snapshots] == [1, 3]


def _naive_history(gate, ledger):
    """The gate's definition, replayed slowly: ``reviewer_agreement`` as of every human time."""
    times = sorted({c.confirmed_at for c in ledger.confirmations if c.reviewer_kind == "human"})
    last, out = {}, []
    for at in times:
        found = reviewer_agreement(ledger, window=gate.window, as_of=at)
        for reviewer_id in sorted(set(found) | set(last)):
            agreement = found.get(reviewer_id) or ReviewerAgreement(reviewer_id, gate.window, None, None,
                                                                    AgreementCounts())
            snapshot = gate._snapshot(reviewer_id, at, agreement)
            if last.get(reviewer_id) != snapshot.snapshot_id:
                last[reviewer_id] = snapshot.snapshot_id
                out.append(snapshot)
    return out


def test_incremental_history_matches_the_naive_replay():
    """Random ledgers: the incremental replay equals ``reviewer_agreement`` as of each time.

    The sample must reach trusted snapshots, falls below the bar and withdrawn pairs, or
    the comparison proves little.
    """
    c = _candidates(12)
    trusted = falls = empty = 0
    for seed in range(300):
        rng = random.Random(seed)
        records = []
        for _ in range(rng.randint(10, 80)):
            kind = rng.choice(["agent", "agent", "human"])
            reviewer = rng.choice(["boss@v1", "jev-1"]) if kind == "agent" else rng.choice(["human:a", "human:b"])
            record = {"candidate_id": c[rng.randrange(12)].candidate_id, "reviewer_kind": kind,
                      "reviewer_id": reviewer, "verdict": rng.choice(["valid"] * 4 + ["hallucinated", "unsure"]),
                      "confirmed_at": float(rng.randrange(15))}
            if kind == "agent":
                record["certainty"] = 0.95
            if record["verdict"] == "valid" and rng.random() < 0.15:
                record["corrected_value"] = rng.choice(["Robin Other", "robin  other"])
            records.append(record)
        ledger = ingest_confirmations(records, c, now=1e6)
        gate = TrustGate(bar=rng.choice([0.1, 0.3, 0.5]), min_n=rng.choice([1, 2, 3]),
                         window=rng.choice([3, 4, 6, 10]))
        history = gate.history(ledger)
        assert history == _naive_history(gate, ledger), seed
        for reviewer in ("boss@v1", "jev-1", "nobody@v1"):
            for at in (t / 2 for t in range(-1, 32)):
                in_force = [s for s in history if s.reviewer_id == reviewer and s.effective_at <= at]
                assert gate.snapshot_at(ledger, reviewer, at) == (in_force[-1] if in_force else None), seed
        trusted += sum(s.trusted for s in history)
        empty += sum(s.n_checked == 0 for s in history)
        falls += len(gate.regressions(ledger, []))
    assert trusted > 100 and falls > 20 and empty > 10, (trusted, falls, empty)


def test_withdrawn_evidence_ends_trust():
    """When people withdraw every check (latest word ``unsure``), the agent is no longer trusted."""
    c = _candidates(2)
    rows = _checks(0, ["valid"] * 2) + [(0, "human", "human:a", "unsure", 10), (1, "human", "human:a", "unsure", 11)]
    ledger = _ledger(c, rows)
    gate = TrustGate(bar=0.1, min_n=1)
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 5)
    final = gate.history(ledger)[-1]
    assert (final.effective_at, final.n_checked, final.trusted) == (11, 0, False)
    assert gate.trusted_snapshot_id(ledger, "boss@v1", 12) is None
