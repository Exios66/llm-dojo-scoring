"""Regression tests for the 0.30.0 follow-ups the sandbox re-vendor needs.

#159 (llm-mailroom ``RunRecord`` gold in the decision lanes), #160 (Wilson rounding at
the budget gate, ambiguous attempts and cross-class human gold in the decision lanes,
stale MAUD ``calibration_error``, off-vocabulary ``Type of Consideration`` ties),
#161 (retired classes in the archive block) and #162 (month-first date phrases).
All inputs are synthetic.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.analysis.bootstrap import round_down, round_up, wilson_bounds, wilson_ci
from llm_dojo_scoring.ml.metrics import score_intake_model
from llm_dojo_scoring.pipeline import archive
from llm_dojo_scoring.schemas.doc_classes import LIVE_DOC_TYPES, RETIRED_DOC_TYPES
from llm_dojo_scoring.scoring import field_scoring as fs
from llm_dojo_scoring.scoring.content_scoring import score_maud_extraction
from llm_dojo_scoring.scoring.decision_lanes import (
    score_arbiter_lane,
    score_boss_lane,
    score_judge_lane,
    score_review_tray,
)
from llm_dojo_scoring.scoring.suites import get_suite

# ---------------------------------------------------------------------------
# #162: month-first two-word dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("container", "target"),
    [
        ("effective on August 18 per the notice", "August 18"),
        ("effective on 18 August per the notice", "18 August"),
        ("signed in August 2014 by both parties", "August 2014"),
        ("dated 2014-08-18 at noon", "2014-08-18"),
    ],
)
def test_two_word_date_phrase_found_in_longer_text(container, target):
    """Two word date phrase found in longer text."""
    assert fs._date_phrase_contained(container, target)


@pytest.mark.parametrize(
    ("container", "target"),
    [
        ("effective on August 1, 2014", "August 18"),  # a different day
        ("effective on August 18, 2014", "August 1"),  # never inside a longer number
        ("the party may terminate on June 1", "May"),  # a lone month word is not a date
    ],
)
def test_two_word_date_phrase_negative_cases(container, target):
    """Two word date phrase negative cases."""
    assert not fs._date_phrase_contained(container, target)


def test_month_first_partial_date_scores_full_credit():
    """Month first partial date scores full credit."""
    assert fs.score_date_field("effective on August 18 per the notice", "August 18") == 1.0


# ---------------------------------------------------------------------------
# #161: retired classes have no archive field map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc_class", RETIRED_DOC_TYPES)
def test_retired_class_has_no_live_field_map(doc_class):
    """Retired class has no live field map."""
    with pytest.raises(KeyError, match="no live field map"):
        archive._live_field_types(doc_class, None)
    with pytest.raises(KeyError, match="no live field map"):
        archive.score_archive_block(doc_class, {"document_name": "X"}, {"document_name": "X"})


@pytest.mark.parametrize("doc_class", LIVE_DOC_TYPES)
def test_live_class_keeps_its_field_map(doc_class):
    """Live class keeps its field map."""
    assert archive._live_field_types(doc_class, None)


def test_explicit_field_types_still_score_a_retired_class():
    """Explicit field types still score a retired class."""
    assert archive._live_field_types("due_diligence", {"x": "name"}) == {"x": "name"}


# ---------------------------------------------------------------------------
# #160 item 1: Wilson bounds are rounded outward
# ---------------------------------------------------------------------------


def test_wilson_upper_bound_never_rounds_under_the_exact_bound():
    """Wilson upper bound never rounds under the exact bound."""
    exact = wilson_bounds(0.0, 379)[1]
    assert exact > 0.01
    assert wilson_ci(0.0, 379)["hi"] > 0.01
    assert wilson_ci(0.0, 379)["hi"] >= exact


@pytest.mark.parametrize("n", [3, 7, 50, 172, 379, 380, 1000])
@pytest.mark.parametrize("errors", [0, 1, 3])
def test_wilson_ci_contains_the_exact_interval(errors, n):
    """Wilson ci contains the exact interval."""
    lo, hi = wilson_bounds(errors / n, n)
    ci = wilson_ci(errors / n, n)
    assert ci["lo"] <= lo and ci["hi"] >= hi


def test_round_up_and_down_keep_exact_values():
    """Round up and down keep exact values."""
    assert round_up(0.01, 4) == 0.01 and round_down(0.01, 4) == 0.01
    assert round_up(0.010001, 4) == 0.0101
    assert round_down(0.009999, 4) == 0.0099
    assert round_up(1.0, 4) == 1.0 and round_down(0.0, 4) == 0.0


def test_selective_risk_upper_fails_the_budget_at_n_379():
    """Selective risk upper fails the budget at n 379."""
    records = [
        {"doc_type": "contract", "pred_doc_type": "contract", "fast_path": True} for _ in range(379)
    ]
    upper = score_intake_model(records)["metrics"]["selective_risk_upper"]
    assert upper > 0.01
    assert upper >= wilson_bounds(0.0, 379)[1]


# ---------------------------------------------------------------------------
# #160 items 2 and 3: ambiguous attempts and cross-class human gold
# ---------------------------------------------------------------------------


def _two_class_record(order, *, judge_doc_type=None, gold=None, arbiter=None):
    """Two class record."""
    scores = {"contract": 0.2, "merger_agreement": 0.9}
    record = {
        "doc_id": "d1",
        "extraction": [
            {"attempt": 1, "doc_type": kind, "extraction_score": scores[kind]} for kind in order
        ],
        "judge": {"ran": True, "verdict": "incomplete", "on_attempt": 1, "doc_type": judge_doc_type},
        "gold": gold or {"label_source": "corpus"},
    }
    if arbiter:
        record["arbiters"] = [arbiter]
    return record


@pytest.mark.parametrize("order", [("contract", "merger_agreement"), ("merger_agreement", "contract")])
def test_judge_without_doc_type_on_an_ambiguous_attempt_is_unscored(order):
    """Judge without doc type on an ambiguous attempt is unscored."""
    card = score_judge_lane([_two_class_record(order)])
    assert card["n_scored"] == 0
    assert card["n_unscored_by_reason"] == {"ambiguous_attempt": 1}


@pytest.mark.parametrize("order", [("contract", "merger_agreement"), ("merger_agreement", "contract")])
def test_judge_with_doc_type_is_graded_by_that_extraction(order):
    """Judge with doc type is graded by that extraction."""
    card = score_judge_lane([_two_class_record(order, judge_doc_type="merger_agreement")])
    assert card["verdicts_by_expected"] == {"complete": {"incomplete": 1}}


@pytest.mark.parametrize("order", [("contract", "merger_agreement"), ("merger_agreement", "contract")])
def test_arbiter_accept_without_doc_type_on_an_ambiguous_attempt_is_unscored(order):
    """Arbiter accept without doc type on an ambiguous attempt is unscored."""
    record = _two_class_record(order, arbiter={"decision": "accept_with_caveats", "on_attempt": 1})
    card = score_arbiter_lane([record])
    assert card["metrics"]["wrongful_accept_rate"] is None
    assert card["n_unscored_by_reason"] == {"ambiguous_attempt": 1}


def test_arbiter_retry_on_an_ambiguous_attempt_is_unscored():
    """Arbiter retry on an ambiguous attempt is unscored."""
    record = _two_class_record(
        ("contract", "merger_agreement"), arbiter={"decision": "retry_extraction", "on_attempt": 1}
    )
    record["extraction"].append({"attempt": 2, "doc_type": "contract", "extraction_score": 0.9})
    card = score_arbiter_lane([record])
    assert card["n_unscored_by_reason"] == {"ambiguous_attempt": 1}


def test_human_gold_does_not_grade_a_judge_of_another_class():
    """Human gold does not grade a judge of another class."""
    record = {
        "doc_id": "d1",
        "extraction": [
            {"attempt": 1, "doc_type": "contract", "extraction_score": 0.95},
            {"attempt": 1, "doc_type": "merger_agreement", "extraction_score": 0.10},
        ],
        "judge": {"ran": True, "verdict": "incomplete", "on_attempt": 1, "doc_type": "merger_agreement"},
        "gold": {
            "label_source": "human",
            "human_resolution": "approve_as_is",
            "human_doc_type": "contract",
        },
    }
    card = score_judge_lane([record])
    assert card["provenance"]["gold_source"] == {"corpus": 1}
    assert card["metrics"]["verdict_accuracy"] == 1.0


def test_human_gold_still_grades_a_judge_of_the_resolved_class():
    """Human gold still grades a judge of the resolved class."""
    record = {
        "doc_id": "d1",
        "extraction": [{"attempt": 1, "doc_type": "contract", "extraction_score": 0.10}],
        "judge": {"ran": True, "verdict": "complete", "on_attempt": 1, "doc_type": "contract"},
        "gold": {
            "label_source": "human",
            "human_resolution": "approve_as_is",
            "human_doc_type": "contract",
        },
    }
    card = score_judge_lane([record])
    assert card["provenance"]["gold_source"] == {"human": 1}
    assert card["metrics"]["verdict_accuracy"] == 1.0


def test_reclassify_gold_still_grades_the_judge_of_the_wrong_class():
    """A reclassify resolves the model's class: the judge that saw it is graded by the person."""
    record = {
        "doc_id": "d1",
        "extraction": [{"attempt": 1, "doc_type": "contract", "extraction_score": 0.95}],
        "judge": {"ran": True, "verdict": "complete", "on_attempt": 1, "doc_type": "contract"},
        "gold": {
            "label_source": "human",
            "human_resolution": "reclassify",
            "human_doc_type": "merger_agreement",
        },
    }
    card = score_judge_lane([record])
    assert card["provenance"]["gold_source"] == {"human": 1}
    assert card["verdicts_by_expected"] == {"incomplete": {"complete": 1}}


def test_human_gold_does_not_grade_an_arbiter_of_another_class():
    """Human gold does not grade an arbiter of another class."""
    record = {
        "doc_id": "d1",
        "extraction": [
            {"attempt": 1, "doc_type": "contract", "extraction_score": 0.95},
            {"attempt": 1, "doc_type": "merger_agreement", "extraction_score": 0.10},
        ],
        "arbiters": [{"decision": "accept_with_caveats", "on_attempt": 1, "doc_type": "merger_agreement"}],
        "gold": {"label_source": "human", "human_resolution": "approve_as_is", "human_doc_type": "contract"},
    }
    card = score_arbiter_lane([record])
    assert card["provenance"]["gold_source"] == {"corpus": 1}
    assert card["metrics"]["wrongful_accept_rate"] == 1.0


# ---------------------------------------------------------------------------
# #159: llm-mailroom RunRecord gold (human_decision / human_doc_type / human_fields)
# ---------------------------------------------------------------------------


#: ``Gold`` fields of llm-mailroom ``src/schemas/run_record.py`` at ``v0.30.0`` (``98c89b8``).
#: The fixture below carries exactly these keys, so a renamed or added field shows up here
#: when the pin moves; ``test_mailroom_gold_fixture_matches_the_pinned_fields`` checks it.
MAILROOM_GOLD_FIELDS = (
    "expected_doc_type",
    "expected_doc_subclass",
    "expected_stage",
    "review_expected",
    "human_decision",
    "human_doc_type",
    "human_doc_subclass",
    "human_fields",
    "label_source",
)


def _mailroom_record(decision, *, human_doc_type="contract", human_fields=None, boss="review"):
    """A ``RunRecord.model_dump()``-shaped row as llm-mailroom's ``export_review_labels`` writes it."""
    return {
        "doc_id": f"doc-{decision}-{human_doc_type}-{bool(human_fields)}",
        "gold": {
            "expected_doc_type": human_doc_type,
            "expected_doc_subclass": None,
            "expected_stage": None,
            "review_expected": None,
            "human_decision": decision,
            "human_doc_type": human_doc_type,
            "human_doc_subclass": None,
            "human_fields": human_fields,
            "label_source": "human",
        },
        "extraction": [{"attempt": 1, "doc_type": "contract", "confidence": 0.9}],
        "boss": {"ran": True, "decision": boss},
        "actual": {"final_stage": "review", "review_causes": ["low_confidence"]},
    }


def test_mailroom_gold_fixture_matches_the_pinned_fields():
    """The fixture's ``gold`` keys are llm-mailroom's ``Gold`` fields, no more and no fewer."""
    assert tuple(_mailroom_record("approved")["gold"]) == MAILROOM_GOLD_FIELDS


def test_mailroom_shaped_records_score_as_resolved():
    """Mailroom shaped records score as resolved."""
    records = [
        _mailroom_record("approved"),  # approve_as_is: wasted review
        _mailroom_record("approved", human_fields={"parties": ["A"]}),  # correct
        _mailroom_record("approved", human_doc_type="merger_agreement"),  # reclassify
        _mailroom_record("rejected"),  # reject
    ]
    tray = score_review_tray(records)
    assert tray["n_scored"] == 4
    assert tray["n_unscored_by_reason"] == {}
    assert tray["resolutions"] == {
        "approve_as_is": 2,
        "reclassify": 1,
        "reject": 1,
    }
    # Hand-computed: 1 of 4 approved as is with no edits, 1 of 4 corrected, 1 of 4 rejected.
    assert tray["metrics"] == {
        "wasted_review_rate": 0.25,
        "correction_rate": 0.25,
        "reject_rate": 0.25,
    }


def test_mailroom_shaped_records_grade_the_boss():
    """Mailroom shaped records grade the boss."""
    records = [_mailroom_record("approved", boss="review"), _mailroom_record("rejected", boss="approved")]
    card = score_boss_lane(records)
    assert card["n_scored"] == 2
    assert card["metrics"]["needless_review_rate"] == 1.0
    assert card["metrics"]["wrongful_approve_rate"] == 1.0


def test_explicit_resolution_wins_over_mailroom_decision():
    """Explicit resolution wins over mailroom decision."""
    record = _mailroom_record("approved")
    record["gold"]["human_resolution"] = "reject"
    assert score_review_tray([record])["resolutions"] == {"reject": 1}


def test_corpus_label_source_ignores_mailroom_decision():
    """Corpus label source ignores mailroom decision."""
    record = _mailroom_record("approved")
    record["gold"]["label_source"] = "corpus"
    record["actual"]["final_stage"] = "archive"
    assert score_review_tray([record])["n_unscored_by_reason"] == {"not_parked": 1}


def test_unknown_mailroom_decision_is_unresolved():
    """Unknown mailroom decision is unresolved."""
    assert score_review_tray([_mailroom_record("maybe")])["n_unscored_by_reason"] == {"unresolved": 1}


# ---------------------------------------------------------------------------
# #160 item 4: calibration_error follows the MAUD rescore
# ---------------------------------------------------------------------------


def _maud_extraction(expected, predicted):
    """Maud extraction."""
    return get_suite("merger_agreement").score_document(expected, predicted)["extraction"]


def test_maud_rescore_recomputes_calibration_error():
    """Maud rescore recomputes calibration error."""
    expected = {"maud_clauses": ["Type of Consideration: All Cash"]}
    predicted = {"maud_clauses": ["Type of Consideration: All Stock"], "confidence": 1.0}
    result = _maud_extraction(expected, predicted)
    assert result.overall_score == 0.0
    assert result.trace["calibration_error"] == 1.0


def test_maud_rescore_calibration_error_with_two_fields():
    """Maud rescore calibration error with two fields."""
    expected = {"acquirer": "Acme Corp", "maud_clauses": ["Type of Consideration: All Cash"]}
    predicted = {
        "acquirer": "Acme Corp",
        "maud_clauses": ["Type of Consideration: All Stock"],
        "confidence": 0.9,
    }
    result = _maud_extraction(expected, predicted)
    assert result.overall_score == 0.5
    assert result.trace["calibration_error"] == 0.4


# ---------------------------------------------------------------------------
# #160 item 6: off-vocabulary Type of Consideration answers do not tie at "other"
# ---------------------------------------------------------------------------


def _toc(gold, pred, question="Type of Consideration"):
    """Toc."""
    return score_maud_extraction([f"{question}: {gold}"], [f"{question}: {pred}"])["maud_question_accuracy"]


def test_different_off_vocabulary_considerations_do_not_match():
    """Different off vocabulary considerations do not match."""
    assert _toc("Zebra stripes", "Quantum foam") == 0.0
    assert _toc("Cash plus contingent value rights", "Convertible debt instruments") == 0.0


def test_equal_off_vocabulary_considerations_still_match():
    """Equal off vocabulary considerations still match."""
    assert _toc("Zebra stripes", "zebra  stripes") == 1.0


def test_catalog_considerations_are_unchanged():
    """Catalog considerations are unchanged."""
    assert _toc("All Cash", "All Cash") == 1.0
    assert _toc("All Cash", "All Stock") == 0.0
