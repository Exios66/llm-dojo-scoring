"""Agent agreement with human spot-checks: pairing, valid precision, Wilson bound, kappa."""

from __future__ import annotations

import hashlib
import json

import pytest
from grounding_inputs import DOC_TEXT

from llm_dojo_scoring.config import clear_settings_cache, configure
from llm_dojo_scoring.grounding.agreement import (
    METRIC_IDS,
    AgreementCounts,
    agreement_score_records,
    paired_checks,
    reviewer_agreement,
    _draw,
    select_spot_checks,
)
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import review_candidates
from llm_dojo_scoring.grounding.ledger import ingest_confirmations
from llm_dojo_scoring.metrics.emitter import Emitter


def _candidates(n):
    """``n`` synthetic candidates on one field, ``doc-0`` … ``doc-{n-1}``."""
    audits = []
    for i in range(n):
        audits += audit_unlabelled_values({}, {"adjuster": f"Robin Example {i}"},
                                          doc_class="insurance_claim", doc_text=DOC_TEXT, doc_id=f"doc-{i}")
    return review_candidates(audits)


def _ledger(candidates, rows):
    """A ledger from ``(index, kind, reviewer, verdict, at, extra)`` rows."""
    records = []
    for index, kind, reviewer, verdict, at, *extra in rows:
        record = {"candidate_id": candidates[index].candidate_id, "verdict": verdict,
                  "reviewer_kind": kind, "reviewer_id": reviewer, "confirmed_at": at}
        if kind == "agent":
            record["certainty"] = 0.95
        record.update(extra[0] if extra else {})
        records.append(record)
    ledger = ingest_confirmations(records, candidates)
    assert ledger.rejects == ()
    return ledger


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Every test starts on default settings."""
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_pairs_need_a_human_truth():
    """Unsure, human disagreement and agent-only candidates are not paired."""
    c = _candidates(4)
    ledger = _ledger(c, [
        (0, "agent", "boss@v1", "valid", 1), (0, "human", "human:a", "valid", 5),
        (1, "agent", "boss@v1", "valid", 1), (1, "human", "human:a", "unsure", 5),
        (2, "agent", "boss@v1", "valid", 1), (2, "human", "human:a", "valid", 5),
        (2, "human", "human:b", "hallucinated", 6),
        (3, "agent", "boss@v1", "unsure", 1), (3, "human", "human:a", "valid", 5),
    ])
    (pair,) = paired_checks(ledger)
    assert (pair.candidate_id, pair.agent_verdict, pair.human_verdict) == (c[0].candidate_id, "valid", "valid")
    assert pair.field == "insurance_claim.adjuster"


def test_valid_with_a_different_value_is_a_miss():
    """An agent valid on a value people corrected counts against the agent."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1),
                         (0, "human", "human:a", "valid", 5, {"corrected_value": "Robin Other"})])
    (pair,) = paired_checks(ledger)
    assert (pair.human_verdict, pair.agrees) == ("hallucinated", False)
    assert reviewer_agreement(ledger)["boss@v1"].overall.valid_precision == 0.0


def test_matching_correction_is_a_hit():
    """An agent correction equal to people's (case and spacing aside) is a hit."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1, {"corrected_value": "robin  other"}),
                         (0, "human", "human:a", "valid", 5, {"corrected_value": "Robin Other"})])
    assert paired_checks(ledger)[0].agrees


def test_counts_precision_wilson_and_kappa():
    """Precision is over the agent's valid verdicts; kappa needs both verdicts on both sides."""
    c = _candidates(10)
    rows = []
    # agent valid ×8: people confirm 6, reject 2; agent hallucinated ×2: people agree once.
    for i, (agent, human) in enumerate([("valid", "valid")] * 6 + [("valid", "hallucinated")] * 2
                                       + [("hallucinated", "hallucinated"), ("hallucinated", "valid")]):
        rows += [(i, "agent", "jev-1", agent, i), (i, "human", "human:a", human, 100 + i)]
    result = reviewer_agreement(_ledger(c, rows))["jev-1"]
    counts = result.overall
    assert (counts.n_checked, counts.n_agent_valid, counts.n_valid_confirmed, counts.n_agree) == (10, 8, 6, 7)
    assert counts.valid_precision == 0.75
    assert counts.valid_precision_lower_95 == pytest.approx(0.4093, abs=1e-4)
    assert counts.agreement == 0.7
    # p_o = 0.7; p_e = (8*7 + 2*3) / 100 = 0.62; kappa = 0.08 / 0.38
    assert counts.kappa == pytest.approx(0.08 / 0.38)
    assert (result.window_start, result.window_end) == (100, 109)
    assert set(result.by_field) == {"insurance_claim.adjuster"}


def test_kappa_none_without_both_verdicts_and_empty_counts():
    """Kappa is None when a rater used one verdict; empty counts give None rates."""
    assert AgreementCounts(n_checked=3, n_agent_valid=3, n_valid_confirmed=3, n_agree=3,
                           n_human_valid=3).kappa is None
    empty = AgreementCounts()
    assert (empty.valid_precision, empty.valid_precision_lower_95, empty.agreement, empty.kappa) == (
        None, None, None, None)


def test_window_keeps_latest_by_human_time_and_follows_settings():
    """Only the latest ``window`` pairs count, ordered by the human's time; default from settings."""
    c = _candidates(5)
    rows = []
    for i in range(5):
        rows += [(i, "agent", "boss@v1", "valid", 1),
                 (i, "human", "human:a", "hallucinated" if i < 2 else "valid", 50 - i)]
    ledger = _ledger(c, rows)
    assert reviewer_agreement(ledger, window=3)["boss@v1"].overall.valid_precision == 1.0 / 3
    assert reviewer_agreement(ledger)["boss@v1"].overall.n_checked == 5
    configure(grounding__trust_min_n=1, grounding__trust_window=2)
    latest_two = reviewer_agreement(ledger)["boss@v1"]
    assert (latest_two.window, latest_two.overall.n_checked, latest_two.overall.n_valid_confirmed) == (2, 2, 0)
    for bad in (0, -1, 2.5, True, "3", float("nan")):
        with pytest.raises(ValueError, match="window must be a whole number"):
            reviewer_agreement(ledger, window=bad)


def test_window_is_coerced_like_the_setting():
    """A whole float window (from YAML or numpy) works as the int does."""
    c = _candidates(3)
    ledger = _ledger(c, [row for i in range(3) for row in (
        (i, "agent", "boss@v1", "valid", 1), (i, "human", "human:a", "valid", 10 + i))])
    as_float = reviewer_agreement(ledger, window=2.0)["boss@v1"]
    assert as_float == reviewer_agreement(ledger, window=2)["boss@v1"]
    assert type(as_float.window) is int


def test_as_of_sees_only_what_was_known():
    """With as_of, later confirmations (agent or human) are ignored."""
    c = _candidates(2)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "human", "human:a", "valid", 10),
                         (1, "agent", "boss@v1", "valid", 1), (1, "human", "human:a", "hallucinated", 20),
                         (1, "human", "human:a", "valid", 30)])
    assert reviewer_agreement(ledger, as_of=5) == {}
    assert reviewer_agreement(ledger, as_of=25)["boss@v1"].overall.valid_precision == 0.5
    assert reviewer_agreement(ledger)["boss@v1"].overall.valid_precision == 1.0


def test_agents_are_separate_and_score_records():
    """Each reviewer_id is reported alone; records carry reviewer_id and denominators."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "agent", "boss@v2", "hallucinated", 1),
                         (0, "human", "human:a", "valid", 5)])
    agreements = reviewer_agreement(ledger)
    assert list(agreements) == ["boss@v1", "boss@v2"]
    records = agreement_score_records(agreements, run_id="r1")
    assert [r.metric for r in records] == list(METRIC_IDS) * 2
    v2 = [r for r in records if r.metadata["reviewer_id"] == "boss@v2"]
    assert {r.agent for r in v2} == {"boss@v2"}
    assert [r.value for r in v2] == [None, None, 0.0, None, 1]
    assert v2[0].metadata == {"scope": "reviewer", "reviewer_id": "boss@v2", "window": 200, "denominator": 0}
    assert agreements["boss@v1"].as_dict()["schema_version"] == 1


def test_each_reviewer_has_its_own_scorecard():
    """Through the emitter, one reviewer's precision never hides behind another's."""
    c = _candidates(2)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "human", "human:a", "valid", 2),
                         (1, "agent", "boss@v2", "valid", 1), (1, "human", "human:a", "hallucinated", 2)])
    records = agreement_score_records(reviewer_agreement(ledger), run_id="r1")
    emitter = Emitter(sinks=[], require_provenance=False)
    for r in records:
        emitter.emit_score(r.agent, r.doc_id, r.metric, r.value, r.metadata, r.run_id)
    assert emitter.get_scorecard("boss@v1", "r1")["grounding_reviewer_valid_precision"] == 1.0
    assert emitter.get_scorecard("boss@v2", "r1")["grounding_reviewer_valid_precision"] == 0.0


def test_wilson_bound_is_unrounded_below_the_bar():
    """169 of 172 is just under 0.95; rounding to four decimals would make it pass."""
    from llm_dojo_scoring.analysis.bootstrap import wilson_ci

    counts = AgreementCounts(n_checked=172, n_agent_valid=172, n_valid_confirmed=169, n_agree=169,
                             n_human_valid=169)
    assert counts.valid_precision_lower_95 < 0.95
    assert wilson_ci(169 / 172, 172)["lo"] == 0.95
    assert counts.valid_precision_lower_95 == pytest.approx(0.94998, abs=1e-5)


def test_revision_after_people_decided_keeps_the_miss():
    """An agent that changes its mind after the human verdict cannot erase its miss."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "human", "human:a", "hallucinated", 5),
                         (0, "agent", "boss@v1", "hallucinated", 10)])
    counts = reviewer_agreement(ledger)["boss@v1"].overall
    assert (counts.n_agent_valid, counts.n_valid_confirmed, counts.n_agree) == (1, 0, 0)


def test_backdated_or_late_agent_verdicts_are_not_blind():
    """A verdict made after people decided, or arriving after them backdated, is not paired."""
    c = _candidates(2)
    ledger = _ledger(c, [(0, "human", "human:a", "valid", 5), (0, "agent", "boss@v1", "valid", 6),
                         (1, "human", "human:a", "valid", 5), (1, "agent", "boss@v1", "valid", 1)])
    assert paired_checks(ledger) == []


def test_human_whose_latest_word_is_unsure_no_longer_counts():
    """A person who withdraws to unsure leaves the candidate without human truth."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "human", "human:a", "valid", 5),
                         (0, "human", "human:a", "unsure", 9)])
    assert paired_checks(ledger) == []


def test_backdated_late_human_record_moves_the_cutoff_back():
    """The blind cutoff is the earliest human decision time, even if that record arrived later."""
    c = _candidates(1)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 5), (0, "human", "human:a", "valid", 10),
                         (0, "human", "human:b", "valid", 3)])
    assert paired_checks(ledger) == []


def _draw_expected(seed, reviewer_id, candidate_id):
    """The documented draw, recomputed independently: sha256 of the JSON list, first 64 bits."""
    payload = json.dumps([seed, reviewer_id, candidate_id], separators=(",", ":")).encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:16], 16) / 2.0 ** 64


def _agent_rows(n, reviewer="boss@v1", verdict="valid"):
    """Agent verdicts on candidates ``0…n-1``, no human yet."""
    return [(i, "agent", reviewer, verdict, i) for i in range(n)]


def test_spot_checks_rate_floor_and_eligibility():
    """About ``rate`` of each agent's decided candidates, at least ``min_per_agent``; humans done are skipped."""
    c = _candidates(200)
    ledger = _ledger(c, _agent_rows(200) + [(0, "human", "human:a", "valid", 500)]
                     + [(1, "human", "human:a", "unsure", 500)] + [(2, "agent", "jev-1", "unsure", 3)])
    picked = select_spot_checks(ledger, rate=0.1, min_per_agent=0)
    assert 10 <= len(picked) <= 35 and picked == sorted(picked)
    assert c[0].candidate_id not in select_spot_checks(ledger, rate=1.0)
    assert c[1].candidate_id in select_spot_checks(ledger, rate=1.0)  # unsure is not a decision
    assert len(select_spot_checks(ledger, rate=0.0, min_per_agent=20)) == 19  # candidate 0 is already a check
    assert select_spot_checks(ledger, rate=0.0, min_per_agent=0) == []
    assert len(select_spot_checks(_ledger(c, _agent_rows(5)), rate=0.0, min_per_agent=20)) == 5


def test_spot_checks_are_deterministic_and_stable_as_the_ledger_grows():
    """Same seed, same sample; earlier draws keep their selection when more candidates arrive."""
    c = _candidates(120)
    small = select_spot_checks(_ledger(c, _agent_rows(60)), rate=0.2, min_per_agent=0)
    large = select_spot_checks(_ledger(c, _agent_rows(120)), rate=0.2, min_per_agent=0)
    assert small == select_spot_checks(_ledger(c, _agent_rows(60)), rate=0.2, min_per_agent=0)
    assert set(small) == {cid for cid in large if cid in {x.candidate_id for x in c[:60]}}
    assert small != select_spot_checks(_ledger(c, _agent_rows(60)), rate=0.2, min_per_agent=0, seed=1)


def test_spot_checks_are_per_agent_and_follow_settings():
    """Each agent gets its own floor; defaults come from settings and are validated."""
    c = _candidates(40)
    ledger = _ledger(c, _agent_rows(20) + [(i, "agent", "jev-1", "hallucinated", i) for i in range(20, 40)])
    picked = set(select_spot_checks(ledger, rate=0.0, min_per_agent=3))
    assert len(picked & {x.candidate_id for x in c[:20]}) == 3
    assert len(picked & {x.candidate_id for x in c[20:]}) == 3
    configure(grounding__spot_check_rate=0.0, grounding__spot_check_min_per_agent=2)
    assert len(select_spot_checks(ledger)) == 4
    for bad in ({"rate": 1.5}, {"min_per_agent": -1}, {"seed": 1.5}, {"seed": True}):
        with pytest.raises(ValueError):
            select_spot_checks(ledger, **bad)


def test_floor_counts_checks_people_already_made():
    """Once people checked the first sample, a second call tops up only to the floor."""
    c = _candidates(300)
    rows = _agent_rows(300)
    first = select_spot_checks(_ledger(c, rows), rate=0.1, min_per_agent=20)
    index = {x.candidate_id: i for i, x in enumerate(c)}
    rows += [(index[cid], "human", "human:a", "valid", 1000) for cid in first]
    second = select_spot_checks(_ledger(c, rows), rate=0.1, min_per_agent=20)
    assert not set(first) & set(second)
    drawn_only = select_spot_checks(_ledger(c, rows), rate=0.1, min_per_agent=0)
    assert second == drawn_only  # the window already holds 20+ checks: no top-up



def test_floor_is_capped_at_the_trust_window():
    """A floor above trust_window would never be met (only the window counts): it is capped there."""
    configure(grounding__trust_min_n=1, grounding__trust_window=5)
    c = _candidates(40)
    rows = _agent_rows(40)
    first = select_spot_checks(_ledger(c, rows), rate=0.0, min_per_agent=20)
    assert len(first) == 5
    index = {x.candidate_id: i for i, x in enumerate(c)}
    rows += [(index[cid], "human", "human:a", "valid", 1000) for cid in first]
    assert select_spot_checks(_ledger(c, rows), rate=0.0, min_per_agent=20) == []

def test_draws_are_pinned_and_shared_candidates_listed_once():
    """The draw is a fixed function of (seed, reviewer, candidate); a candidate two agents decided appears once."""
    assert _draw(0, "boss@v1", "abc") == _draw_expected(0, "boss@v1", "abc") == 0.5334060011203018
    c = _candidates(30)
    ledger = _ledger(c, _agent_rows(30) + _agent_rows(30, reviewer="jev-1"))
    picked = select_spot_checks(ledger, rate=0.0, min_per_agent=30)
    assert picked == sorted({x.candidate_id for x in c})


def test_revisions_and_unsure_people_follow_the_latest_word():
    """An agent's latest unsure drops it; a person's unsure then decisive verdict removes the candidate."""
    c = _candidates(3)
    ledger = _ledger(c, [(0, "agent", "boss@v1", "valid", 1), (0, "agent", "boss@v1", "unsure", 2),
                         (1, "agent", "boss@v1", "valid", 1), (1, "human", "human:a", "unsure", 2),
                         (1, "human", "human:a", "valid", 3), (2, "agent", "boss@v1", "hallucinated", 1)])
    assert select_spot_checks(ledger, rate=1.0) == [c[2].candidate_id]
