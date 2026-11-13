"""Judge, arbiter, boss and review-tray scorecards on one realistic mixed batch.

The batch is synthetic, shaped like mailroom ``RunRecord.model_dump()`` rows
with the human-review fields (``gold.human_resolution`` and friends). It mixes
what a deployed pipeline produces in a day: clean archives, a judge escalation a
person corrected, retries that helped and retries that did not, boss reviews a
person approved as is, rejections, an audit sample, and rows with no gold at
all. Every expected number below is counted by hand from ``_batch``.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

import llm_dojo_scoring
from llm_dojo_scoring.metrics.registry import get_registry
from llm_dojo_scoring.metrics.scorecard_honesty import _METRIC_ID_BY_NAME, metric_id_for
from llm_dojo_scoring.scoring.decision_lanes import (
    score_arbiter_lane,
    score_boss_lane,
    score_judge_lane,
    score_review_tray,
)

DOC_TYPE = "insurance_claim"
_NAMES_WITH_IDS = {n for n, i in _METRIC_ID_BY_NAME.items() if i.startswith("decision.")}


def rec(
    doc_id: str,
    *,
    scores: tuple[float, ...] = (),
    judge: tuple[str, int] | None = None,
    rulings: tuple[tuple[str, int], ...] = (),
    boss: str | None = None,
    resolution: str | None = None,
    corrections: dict[str, Any] | None = None,
    reject_reason: str | None = None,
    causes: tuple[str, ...] = (),
    stage: str = "archived",
    label_source: str | None = None,
) -> dict[str, Any]:
    """One RunRecord-shaped mapping; ``judge`` is ``(verdict, judged attempt)``."""
    gold: dict[str, Any] = {"expected_doc_type": DOC_TYPE}
    if resolution:
        gold["human_resolution"] = resolution
        gold["label_source"] = label_source or "human"
    elif label_source:
        gold["label_source"] = label_source
    if corrections is not None:
        gold["human_fields"] = corrections
    if reject_reason:
        gold["human_reject_reason"] = reject_reason
    row: dict[str, Any] = {
        "doc_id": doc_id,
        "run": {"run_id": "r1", "dataset_revision": "rev-synthetic", "split": "test", "mode": "mock"},
        "gold": gold,
        "extraction": [
            {"attempt": i + 1, "doc_type": DOC_TYPE, "extraction_score": s}
            for i, s in enumerate(scores)
        ],
        "judge": {"ran": False},
        "arbiters": [
            {"ran": True, "decision": d, "on_attempt": a, "doc_type": DOC_TYPE} for d, a in rulings
        ],
        "actual": {"final_stage": stage, "review_causes": list(causes)},
    }
    if judge:
        row["judge"] = {
            "ran": True,
            "verdict": judge[0],
            "on_attempt": judge[1],
            "doc_type": DOC_TYPE,
        }
    if boss:
        row["boss"] = {"decision": boss}
    return row


def _batch() -> list[dict[str, Any]]:
    """Twenty-six documents, one line per story (see the module docstring)."""
    rows = [
        # Clean archives: judged complete against a 0.95 dataset score.
        *[rec(f"clean-{i}", scores=(0.95,), judge=("complete", 1)) for i in range(1, 5)],
        # The judge escalated a good extraction; the arbiter accepted it anyway.
        rec("over-flag", scores=(0.95,), judge=("partial", 1), rulings=(("accept_with_caveats", 1),)),
        # The judge missed a bad extraction (0.30) and called it complete.
        rec("missed", scores=(0.30,), judge=("complete", 1)),
        # The judge escalated, the arbiter parked it, a person corrected fields.
        rec("esc-1", scores=(0.70,), judge=("partial", 1), rulings=(("human_review", 1),),
            resolution="correct", corrections={"claimed_amount": "1200", "adjuster": "A. Reyes"},
            causes=("judge_escalation",), stage="review"),
        rec("esc-2", scores=(0.70,), judge=("partial", 1), rulings=(("human_review", 1),),
            resolution="correct", corrections={"claimed_amount": "88"},
            causes=("judge_escalation",), stage="review"),
        # Human gold says partial while the dataset score says incomplete.
        rec("esc-3", scores=(0.20,), judge=("incomplete", 1), rulings=(("human_review", 1),),
            resolution="correct", corrections={"adjuster": "B. Okafor"},
            causes=("judge_escalation",), stage="review"),
        # Retries that helped: +0.50, then +0.05 exactly (0.85 - 0.80 is 0.0499... in floats).
        rec("retry-up-1", scores=(0.40, 0.90), judge=("incomplete", 1),
            rulings=(("retry_extraction", 1), ("accept_with_caveats", 2))),
        rec("retry-up-2", scores=(0.80, 0.85), judge=("partial", 1),
            rulings=(("retry_extraction", 1), ("accept_with_caveats", 2))),
        # Retries that did not: +0.02 and -0.10; each then parked and a person resolved it.
        rec("retry-flat", scores=(0.40, 0.42), judge=("incomplete", 1),
            rulings=(("retry_extraction", 1), ("human_review", 2)),
            resolution="reject", reject_reason="unreadable",
            causes=("extraction_failed",), stage="review"),
        rec("retry-down", scores=(0.60, 0.50), judge=("partial", 1),
            rulings=(("retry_extraction", 1), ("human_review", 2)),
            resolution="correct", corrections={"adjuster": "C. Lind", "claimed_amount": "9"},
            causes=("extraction_failed",), stage="review"),
        # A retry with no second dataset score cannot be graded.
        rec("retry-blind", scores=(0.55,), judge=("partial", 1), rulings=(("retry_extraction", 1),)),
        # Boss reviews a person approved as is (needless), one the person reclassified.
        rec("boss-needless-1", boss="review", resolution="approve_as_is", causes=("conflict",), stage="review"),
        rec("boss-needless-2", boss="review", resolution="approve_as_is", causes=("conflict",),
            rulings=(("human_review", 1),), stage="review"),
        rec("boss-needed", boss="review", resolution="reclassify", causes=("conflict",), stage="review"),
        # Boss approvals that reached a person through the audit sample.
        rec("audit-bad", boss="approved", resolution="correct", corrections={"claim_number": "C-77"},
            rulings=(("accept_with_caveats", 1),), causes=("audit_sample",), stage="review"),
        rec("audit-good", boss="approved", resolution="approve_as_is", causes=("audit_sample",), stage="review"),
        rec("audit-none", boss="approved"),
        # Rejections: the judge agreed, the judge missed, no judge ran.
        rec("reject-dup", judge=("incomplete", 1), rulings=(("human_review", 1),), resolution="reject",
            reject_reason="duplicate", causes=("low_confidence",), stage="review"),
        rec("reject-scope", judge=("complete", 1), rulings=(("human_review", 1),), resolution="reject",
            reject_reason="not_a_legal_document", causes=("low_confidence",), stage="review"),
        rec("reject-bare", resolution="reject", causes=("low_confidence",), stage="review"),
        # No gold anywhere: a judged document with no score and no resolution.
        rec("no-gold", judge=("partial", 1), rulings=(("accept_with_caveats", 1),)),
        # A failed judge on a still-parked document; the dataset score still grades the arbiter.
        rec("judge-failed", scores=(0.40,), judge=("judge_error", 1), rulings=(("human_review", 1),),
            causes=("judge_error",), stage="review"),
        # Nothing ran.
        rec("empty"),
    ]
    assert len(rows) == 26
    return rows


@pytest.fixture(name="batch")
def _batch_fixture() -> list[dict[str, Any]]:
    """A fresh copy of the mixed batch."""
    return _batch()


def _envelope_holds(card: dict[str, Any]) -> None:
    """Every scorecard accounts for every unit: scored plus unscored equals ``n``."""
    assert card["n"] == card["n_scored"] + sum(card["n_unscored_by_reason"].values())
    assert sum(card["provenance"]["gold_source"].values()) == card["n_scored"]


def test_judge_lane_on_the_mixed_batch(batch):
    """Verdicts are graded against human gold first, then the dataset score."""
    card = score_judge_lane(batch)
    m = card["metrics"]
    assert (card["n"], card["n_scored"]) == (26, 16)
    assert card["n_unscored_by_reason"] == {"judge_error": 1, "judge_not_run": 8, "no_gold": 1}
    assert card["provenance"]["gold_source"] == {"corpus": 9, "human": 7}
    assert m["verdict_accuracy"] == 0.75  # 12 of 16
    assert m["escalation_recall"] == 0.8182  # 9 of the 11 not-complete documents
    assert m["false_escalation_rate"] == 0.2  # over-flag, 1 of 5 complete
    assert m["error_rate"] == round(1 / 18, 4)  # 18 judge runs, one judge_error
    # complete 8/11, incomplete 6/9, partial 10/12 as F1; macro mean.
    assert m["macro_f1"] == round((8 / 11 + 6 / 9 + 10 / 12) / 3, 4)
    assert card["verdicts_by_expected"] == {
        "complete": {"complete": 4, "partial": 1},
        "incomplete": {"complete": 2, "incomplete": 3},
        "partial": {"incomplete": 1, "partial": 5},
    }
    assert card["band"] == [0.5, 0.85]
    _envelope_holds(card)


def test_arbiter_lane_on_the_mixed_batch(batch):
    """Each ruling is graded on its own outcome; ungradable rulings stay unscored."""
    card = score_arbiter_lane(batch)
    m = card["metrics"]
    assert (card["n"], card["n_scored"]) == (30, 17)  # 19 rulings + 11 documents with none
    assert card["n_unscored_by_reason"] == {"arbiter_not_run": 11, "no_gold": 1, "no_retry_scores": 1}
    assert card["provenance"]["gold_source"] == {"corpus": 8, "human": 9}
    assert card["by_decision"] == {
        "accept_with_caveats": {"right": 3, "wrong": 1},
        "human_review": {"right": 8, "wrong": 1},
        "retry_extraction": {"right": 2, "wrong": 2},
    }
    assert m["decision_accuracy"] == round(13 / 17, 4)
    assert m["retry_usefulness"] == 0.5
    assert m["wrongful_accept_rate"] == 0.25  # audit-bad: accepted, person corrected
    assert m["unnecessary_escalation_rate"] == round(1 / 9, 4)  # boss-needless-2
    assert card["epsilon"] == 0.05
    _envelope_holds(card)


def test_boss_lane_on_the_mixed_batch(batch):
    """Only a person's outcome grades the boss; an approval nobody reviewed is no_boss_gold."""
    card = score_boss_lane(batch)
    assert (card["n"], card["n_scored"]) == (26, 5)
    assert card["n_unscored_by_reason"] == {"boss_not_run": 20, "no_boss_gold": 1}
    assert card["provenance"]["gold_source"] == {"human": 5}
    assert card["metrics"] == {"wrongful_approve_rate": 0.5, "needless_review_rate": 0.6667}
    assert card["by_decision"] == {
        "approved": {"n": 2, "wrongful": 1},
        "review": {"n": 3, "needless": 2},
    }
    _envelope_holds(card)


def test_review_tray_on_the_mixed_batch(batch):
    """The tray reports what people did with what was parked, and which causes earned it."""
    card = score_review_tray(batch)
    assert (card["n"], card["n_scored"]) == (26, 13)
    assert card["n_unscored_by_reason"] == {"not_parked": 12, "unresolved": 1}
    assert card["resolutions"] == {"approve_as_is": 3, "correct": 5, "reclassify": 1, "reject": 4}
    assert card["metrics"] == {
        "wasted_review_rate": 0.2308,  # 3 of 13: boss-needless-1, boss-needless-2, audit-good
        "correction_rate": 0.3846,
        "reject_rate": 0.3077,
    }
    assert card["reject_reasons"] == {
        "duplicate": 1, "not_a_legal_document": 1, "unreadable": 1, "unspecified": 1,
    }
    # Over the 8 reviews that checked fields (approve_as_is and correct).
    assert card["field_correction_rate"] == {"adjuster": 0.375, "claim_number": 0.125, "claimed_amount": 0.375}
    assert card["by_review_cause"] == {
        "audit_sample": {"n": 2, "changed": 1, "precision": 0.5},
        "conflict": {"n": 3, "changed": 1, "precision": 0.3333},
        "extraction_failed": {"n": 2, "changed": 2, "precision": 1.0},
        "judge_escalation": {"n": 3, "changed": 3, "precision": 1.0},
        "low_confidence": {"n": 3, "changed": 3, "precision": 1.0},
    }
    _envelope_holds(card)


def test_rows_without_gold_are_unscored_never_zero():
    """A lone ungradable row leaves every metric None, and never moves a graded batch."""
    lonely = [rec("x", judge=("partial", 1), rulings=(("accept_with_caveats", 1),), boss="approved")]
    for score in (score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray):
        card = score(lonely)
        assert card["n_scored"] == 0
        # error_rate needs no gold: the judge did run, and it did not fail.
        gold_metrics = {k: v for k, v in card["metrics"].items() if k != "error_rate"}
        assert all(value is None for value in gold_metrics.values()), score.__name__
        _envelope_holds(card)
    assert score_judge_lane(lonely)["metrics"]["error_rate"] == 0.0
    assert score_judge_lane(lonely)["n_unscored_by_reason"] == {"no_gold": 1}
    assert score_arbiter_lane(lonely)["n_unscored_by_reason"] == {"no_gold": 1}
    assert score_boss_lane(lonely)["n_unscored_by_reason"] == {"no_boss_gold": 1}
    assert score_review_tray(lonely)["n_unscored_by_reason"] == {"not_parked": 1}

    graded = _batch()
    without = [r for r in graded if r["doc_id"] not in {"no-gold", "empty"}]
    for score in (score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray):
        with_rows, without_rows = score(graded)["metrics"], score(without)["metrics"]
        with_rows.pop("error_rate", None)  # counts every judge run, gold or not
        without_rows.pop("error_rate", None)
        assert with_rows == without_rows, score.__name__


@pytest.mark.parametrize("score", [score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray])
def test_empty_input_is_an_empty_scorecard(score):
    """No records give a well-formed scorecard with null metrics."""
    card = score([])
    assert (card["n"], card["n_scored"], card["n_unscored_by_reason"]) == (0, 0, {})
    assert all(value is None for value in card["metrics"].values())


def test_human_gold_overrides_corpus_in_judge_and_arbiter():
    """A person's resolution wins over a dataset score that says the opposite."""
    # Dataset score 0.95 says complete / accept right; the person rejected it.
    row = rec("override", scores=(0.95,), judge=("complete", 1), rulings=(("accept_with_caveats", 1),),
              resolution="reject", reject_reason="duplicate")
    judge = score_judge_lane([row])
    assert judge["provenance"]["gold_source"] == {"human": 1}
    assert judge["metrics"]["verdict_accuracy"] == 0.0
    assert judge["verdicts_by_expected"] == {"incomplete": {"complete": 1}}
    arbiter = score_arbiter_lane([row])
    assert arbiter["provenance"]["gold_source"] == {"human": 1}
    assert arbiter["metrics"]["wrongful_accept_rate"] == 1.0
    # The same row graded by the dataset alone is right on both counts.
    corpus_only = rec("corpus", scores=(0.95,), judge=("complete", 1), rulings=(("accept_with_caveats", 1),))
    assert score_judge_lane([corpus_only])["metrics"]["verdict_accuracy"] == 1.0
    assert score_arbiter_lane([corpus_only])["metrics"]["wrongful_accept_rate"] == 0.0


def test_an_explicit_corpus_label_source_is_not_human_gold():
    """``label_source="corpus"`` keeps the dataset as gold even when a resolution is present."""
    row = rec("corpus-labelled", scores=(0.95,), judge=("complete", 1), resolution="reject",
              label_source="corpus")
    card = score_judge_lane([row])
    assert card["provenance"]["gold_source"] == {"corpus": 1}
    assert card["metrics"]["verdict_accuracy"] == 1.0
    assert score_boss_lane([{**row, "boss": {"decision": "approved"}}])["n_unscored_by_reason"] == {
        "no_boss_gold": 1
    }


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.85, "complete"), (0.8499, "partial"), (0.5001, "partial"), (0.5, "incomplete"), (0.0, "incomplete")],
)
def test_judge_band_edges_are_inclusive_like_the_pipeline_verdict(score, expected):
    """High is inclusive for complete and low inclusive for incomplete, as in deterministic_verdict_label."""
    card = score_judge_lane([rec("edge", scores=(score,), judge=(expected, 1))])
    assert card["metrics"]["verdict_accuracy"] == 1.0


def test_judge_band_can_be_overridden_and_is_validated():
    """A caller band replaces the configured one; a malformed band is refused."""
    row = rec("custom", scores=(0.70,), judge=("complete", 1))
    assert score_judge_lane([row])["metrics"]["verdict_accuracy"] == 0.0  # 0.70 is partial by default
    assert score_judge_lane([row], band=(0.2, 0.7))["metrics"]["verdict_accuracy"] == 1.0
    for bad in [(0.9, 0.5), (0.5, 0.5), (-0.1, 0.5), (0.5, 1.5)]:
        with pytest.raises(ValueError, match="band"):
            score_judge_lane([row], band=bad)


def test_judge_grades_the_extraction_it_judged_not_the_final_one():
    """After a retry, a verdict on attempt 1 is graded against attempt 1's score."""
    row = rec("judged-first", scores=(0.20, 0.95), judge=("incomplete", 1))
    assert score_judge_lane([row])["metrics"]["verdict_accuracy"] == 1.0
    row = rec("judged-second", scores=(0.20, 0.95), judge=("complete", 2))
    assert score_judge_lane([row])["metrics"]["verdict_accuracy"] == 1.0


@pytest.mark.parametrize(
    ("scores", "epsilon", "useful"),
    [
        ((0.80, 0.85), 0.05, True),  # 0.85 - 0.80 is 0.04999999999999993 unrounded
        ((0.40, 0.4499), 0.05, False),
        ((0.40, 0.45), 0.05, True),
        ((0.40, 0.45), 0.10, False),
        ((0.90, 0.40), 0.05, False),
    ],
)
def test_retry_usefulness_threshold(scores, epsilon, useful):
    """A retry is useful when the next attempt rose by at least epsilon."""
    row = rec("retry", scores=scores, rulings=(("retry_extraction", 1),))
    card = score_arbiter_lane([row], epsilon=epsilon)
    assert card["metrics"]["retry_usefulness"] == (1.0 if useful else 0.0)
    assert card["epsilon"] == epsilon


def test_retry_is_graded_on_the_attempt_it_was_ruled_on():
    """A ruling after attempt 2 compares attempts 2 and 3, not 1 and 2."""
    row = rec("second-retry", scores=(0.30, 0.31, 0.90), rulings=(("retry_extraction", 2),))
    assert score_arbiter_lane([row])["metrics"]["retry_usefulness"] == 1.0
    row = rec("first-retry", scores=(0.30, 0.31, 0.90), rulings=(("retry_extraction", 1),))
    assert score_arbiter_lane([row])["metrics"]["retry_usefulness"] == 0.0


def test_a_later_human_approval_does_not_prove_a_retry_helped():
    """Retry gold is the dataset score only; a resolution without scores leaves it unscored."""
    row = rec("approved-after-retry", rulings=(("retry_extraction", 1),), resolution="approve_as_is")
    card = score_arbiter_lane([row])
    assert card["n_unscored_by_reason"] == {"no_retry_scores": 1}
    assert card["metrics"]["retry_usefulness"] is None


def test_arbiter_parameters_are_validated():
    """A negative or non-finite epsilon and a malformed band are refused."""
    for bad in (-0.01, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="epsilon"):
            score_arbiter_lane([], epsilon=bad)
    with pytest.raises(ValueError, match="band"):
        score_arbiter_lane([], band=(0.9, 0.1))


def test_unknown_labels_are_unscored_not_guessed():
    """An unknown judge verdict or arbiter ruling is reported, not mapped to a class."""
    odd = rec("odd", scores=(0.9,), judge=("excellent", 1), rulings=(("shrug", 1),), boss="maybe",
              resolution="approve_as_is")
    assert score_judge_lane([odd])["n_unscored_by_reason"] == {"unknown_verdict": 1}
    assert score_arbiter_lane([odd])["n_unscored_by_reason"] == {"unknown_decision": 1}
    assert score_boss_lane([odd])["n_unscored_by_reason"] == {"unknown_decision": 1}


def test_flat_keys_and_json_noise_are_tolerated():
    """Flat keys work like nested ones; NaN, bool and text scores are ignored, not scored."""
    flat = {
        "doc_id": "flat",
        "judge": {"ran": True, "verdict": " Complete "},
        "human_resolution": "approve_as_is",
        "boss_decision": "review",
        "arbiter_decision": "human_review",
        "review_causes": ["conflict"],  # ignored: causes are read from ``actual``
    }
    assert score_judge_lane([flat])["metrics"]["verdict_accuracy"] == 1.0
    assert score_boss_lane([flat])["metrics"]["needless_review_rate"] == 1.0
    assert score_arbiter_lane([flat])["metrics"]["unnecessary_escalation_rate"] == 1.0
    noisy = rec("noisy", judge=("complete", 1))
    noisy["extraction"] = [
        {"attempt": 1, "extraction_score": float("nan")},
        {"attempt": 2, "extraction_score": True},
        {"attempt": 3, "extraction_score": "0.9"},
        "not a mapping",
    ]
    assert score_judge_lane([noisy])["n_unscored_by_reason"] == {"no_gold": 1}


def test_non_mapping_record_is_rejected():
    """A record that is not a mapping is a caller error, named by position."""
    with pytest.raises(TypeError, match="record 1"):
        score_judge_lane([rec("ok"), "oops"])  # type: ignore[list-item]


def test_scoring_is_pure_and_order_independent(batch):
    """Inputs are not mutated and the batch order does not matter."""
    before = copy.deepcopy(batch)
    lanes = (score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray)
    first = [lane(batch) for lane in lanes]
    assert batch == before
    reversed_cards = [lane(list(reversed(batch))) for lane in lanes]
    assert first == reversed_cards


def test_provenance_names_the_run_and_the_metric_ids(batch):
    """Each scorecard carries dataset revision, split, scorer version and canonical metric ids."""
    for lane in (score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray):
        prov = lane(batch)["provenance"]
        assert prov["dataset_revision"] == ["rev-synthetic"]
        assert prov["split"] == ["test"]
        assert prov["scorer_version"] == llm_dojo_scoring.__version__
        assert prov["metric_ids"]
        assert all(mid.startswith("decision.") for mid in prov["metric_ids"].values())


@pytest.mark.parametrize(
    "score", [score_judge_lane, score_arbiter_lane, score_boss_lane, score_review_tray]
)
def test_every_scorecard_metric_is_registered_with_a_decision_id(score, batch):
    """Each scalar metric has a registry entry whose canonical id is ``decision.<lane>.<key>``."""
    card = score(batch)
    registry = get_registry()
    by_id = {metric_id_for(name): name for name in registry.names() if name in _NAMES_WITH_IDS}
    assert set(card["provenance"]["metric_ids"]) == set(card["metrics"])
    for key, metric_id in card["provenance"]["metric_ids"].items():
        lane = metric_id.split(".")[1]
        assert metric_id == f"decision.{lane}.{key}"
        assert registry.get(by_id[metric_id]).source.startswith("decision_lanes.score_")


def test_decision_lanes_stay_off_the_package_root():
    """The consumer surface is unchanged: the lanes are imported from their module only."""
    for name in ("score_judge_lane", "score_arbiter_lane", "score_boss_lane", "score_review_tray"):
        assert name not in dir(llm_dojo_scoring)
        assert not hasattr(llm_dojo_scoring, name)
