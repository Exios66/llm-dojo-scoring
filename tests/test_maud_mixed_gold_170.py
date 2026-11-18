"""#170: MAUD gold lines that name no question stay in the denominator.

``parse_maud_labels`` keeps only the lines that name a question. With mixed gold the plain
text lines used to leave ``n_questions``, so the same prediction scored higher than it
should. Each plain gold line is now expected, and matched only by an equal predicted plain
line. Gold made only of plain lines still goes to the generic matcher, and gold made only
of question lines scores as before. All inputs are synthetic.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.scoring.suites import get_suite

QUESTION = "Type of Consideration: All Cash"
PLAIN = "the buyer pays cash at closing"


def _clauses(gold, pred):
    """The rescored ``maud_clauses`` field score and its entity-list score."""
    extraction = get_suite("merger_agreement").score_document(
        {"maud_clauses": gold}, {"maud_clauses": pred}
    )["extraction"]
    return extraction.field_scores["maud_clauses"], extraction.entity_list_scores["maud_clauses"]


def test_mixed_gold_counts_the_plain_line_as_expected_and_unmatched():
    """Answering only the question line leaves the plain gold line missed: recall 0.5, not 1.0."""
    score, entity = _clauses([QUESTION, PLAIN], [QUESTION])
    assert score == 0.5
    assert (entity.matched, entity.unmatched_expected, entity.unmatched_predicted) == (1, 1, 0)
    assert entity.recall == 0.5 and entity.precision == 1.0


def test_mixed_gold_plain_line_is_matched_by_an_equal_predicted_plain_line():
    """A predicted plain line equal to the gold one (bullet, case, spacing aside) matches it."""
    score, entity = _clauses([QUESTION, PLAIN], [QUESTION, "- The  buyer pays CASH at closing"])
    assert score == 1.0
    assert (entity.matched, entity.unmatched_expected, entity.unmatched_predicted) == (2, 0, 0)
    assert entity.precision == 1.0 and entity.recall == 1.0


def test_mixed_gold_a_different_plain_line_matches_nothing():
    """An unrelated predicted plain line is an unmatched prediction; the gold line stays missed."""
    score, entity = _clauses([QUESTION, PLAIN], [QUESTION, "an entirely different sentence"])
    assert score == 0.5
    assert (entity.matched, entity.unmatched_expected, entity.unmatched_predicted) == (1, 1, 1)


def test_mixed_gold_a_plain_prediction_matches_one_gold_line_once():
    """Two equal gold plain lines need two equal predicted lines; one prediction matches once."""
    score, entity = _clauses([QUESTION, PLAIN, PLAIN], [QUESTION, PLAIN])
    assert entity.matched == 2 and entity.unmatched_expected == 1
    assert score == round(2 / 3, 4)


def test_mixed_gold_wrong_answer_still_misses_alongside_a_matched_plain_line():
    """The question line is scored by its class, the plain line by its text."""
    score, entity = _clauses([QUESTION, PLAIN], ["Type of Consideration: All Stock", PLAIN])
    assert score == 0.5
    assert (entity.matched, entity.unmatched_expected, entity.unmatched_predicted) == (1, 1, 1)


@pytest.mark.parametrize("pred", [[QUESTION], ["Type of Consideration: All Stock"], []])
def test_gold_of_question_lines_only_scores_as_before(pred):
    """No plain gold line: the rescore is unchanged."""
    score, entity = _clauses([QUESTION], pred)
    assert score == (1.0 if pred == [QUESTION] else 0.0)
    assert entity.unmatched_expected == (0 if pred == [QUESTION] else 1)


def test_gold_of_plain_lines_only_stays_with_the_generic_matcher():
    """Gold naming no question is not rescored by question: the entity-list score is the generic one."""
    extraction = get_suite("merger_agreement").score_document(
        {"maud_clauses": [PLAIN]}, {"maud_clauses": [PLAIN]}
    )["extraction"]
    assert extraction.field_scores["maud_clauses"] == 1.0
    assert extraction.entity_list_scores["maud_clauses"].matched == 1


AMBIGUOUS = ["Type of Consideration: All Cash", "Type of Consideration: All Stock"]


@pytest.mark.parametrize("hub_metadata", [False, True])
def test_plain_gold_lines_survive_when_every_question_line_is_ambiguous(hub_metadata):
    """Conflicting question lines are unscored, but the plain gold line is still expected."""
    gold = {"maud_clauses": [*AMBIGUOUS, PLAIN]}
    if hub_metadata:
        gold["gt_presence"] = '{"maud_clauses": "populated"}'
    suite = get_suite("merger_agreement")
    missed = suite.score_document(gold, {"maud_clauses": []})["extraction"]
    assert missed.field_scores["maud_clauses"] == 0.0
    pred = {"maud_clauses": ["Type of Consideration: All Cash", PLAIN]}
    hit = suite.score_document(gold, pred)["extraction"]
    entity = hit.entity_list_scores["maud_clauses"]
    assert hit.field_scores["maud_clauses"] == 1.0
    assert (entity.matched, entity.unmatched_expected, entity.unmatched_predicted) == (1, 0, 0)


def test_gold_of_only_ambiguous_question_lines_stays_unscorable():
    """With no plain line left, ambiguous gold is still no gold (hub path)."""
    gold = {"maud_clauses": AMBIGUOUS, "gt_presence": '{"maud_clauses": "populated"}'}
    extraction = get_suite("merger_agreement").score_document(gold, {"maud_clauses": []}).get("extraction")
    assert extraction is None or "maud_clauses" not in extraction.field_scores
