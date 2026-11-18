"""MAUD question labels are merger extraction gold, the way CUAD labels feed contracts.

A Hub merger row labels MAUD questions categorically (``maud_clause_labels``:
``{question: {"answer": <Hub class>, ...}}``) and names its consideration type
(``expected_subclass``). There are no text spans, so the conversion into the merger
extraction schema is: one ``'<Question>: <Hub class>'`` line per answered question
(``maud_clauses``) plus the consideration token (``merger_consideration``).

These tests run synthetic Hub-shaped rows (invented rows; questions and answers are
the public MAUD catalog's) through the public per-document entry point,
``get_suite("merger_agreement").score_document``, and pin what a deployment sees:
the headline, field-micro P/R/F1, the MAUD content extras beside them, and the
rows that must stay unscorable.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from test_class_headline_contract import hub_row

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.schemas import maud_schema
from llm_dojo_scoring.schemas.maud_schema import (
    MAUD_QUESTIONS,
    MAUD_TYPE_OF_CONSIDERATION_TO_TOKEN,
    MergerAgreementExtraction,
    hub_merger_expected_fields,
    maud_question,
    parse_maud_clause,
)

#: A row's answered questions, in no particular order. ``Invented Deal Point`` is not
#: in the catalog (the Hub is the ground truth, so it is kept verbatim).
ANSWERS = {
    "Specific Performance": '"entitled to" specific performance',
    "Type of Consideration": "All Cash",
    "No-Shop": "Yes",
    "Invented Deal Point": "Maybe",
    "Breach of No Shop": "No",
    "Knowledge Definition": "Actual knowledge",
}
#: Hub columns can also carry unanswered questions (blank, ``nan``); they are not labels.
UNANSWERED = {"Breach of Meeting Covenant": "", "FTR Triggers": "nan"}
#: What the conversion must produce for ``ANSWERS``: catalog order, unknown last.
GOLD_LINES = [
    "Breach of No Shop: No",
    "Knowledge Definition: Actual knowledge",
    "No-Shop: Yes",
    "Specific Performance: \"entitled to\" specific performance",
    "Type of Consideration: All Cash",
    "Invented Deal Point: Maybe",
]
#: A prediction identical to the labels.
ORACLE = {"maud_clauses": list(GOLD_LINES), "merger_consideration": "all_cash"}


def labels(answers: dict[str, str] = ANSWERS) -> dict[str, dict[str, Any]]:
    """Hub-shaped ``maud_clause_labels`` records for ``{question: answer}``."""
    return {
        question: {
            "answer": answer,
            "category": "General Information",
            "excerpt_chars": 0,
            "label_idx": "0",
            "valid_classes": [answer],
        }
        for question, answer in answers.items()
    }


def merger_row(answers: dict[str, str] = ANSWERS, *, subclass: str = "", **extra: Any) -> str:
    """A synthetic Hub merger ``gt_fields`` value (every column a string)."""
    return hub_row(
        maud_label_count=str(sum(1 for a in answers.values() if a.strip() and a != "nan")),
        maud_clause_labels=labels(answers),
        expected_subclass=subclass,
        **extra,
    )


ROW = merger_row(subclass="all_cash")


def score(gt: str, predicted: dict | None, subclass: str | None = "all_cash") -> dict[str, Any]:
    """Score one merger document through the public per-document entry point."""
    return get_suite("merger_agreement").score_document(gt, predicted, doc_subclass=subclass)


def test_hub_row_converts_to_the_merger_extraction_fields():
    """Answered questions become canonical lines in catalog order; the token comes from the label."""
    row = merger_row({**ANSWERS, **UNANSWERED}, subclass="all_cash")
    assert hub_merger_expected_fields(row) == {
        "maud_clauses": GOLD_LINES,
        "merger_consideration": "all_cash",
    }
    # Same conversion from the parsed mapping, and from the scored row itself.
    assert hub_merger_expected_fields(json.loads(row)) == hub_merger_expected_fields(row)
    assert hub_merger_expected_fields(ROW) == hub_merger_expected_fields(row)


def test_conversion_uses_the_verbatim_hub_class_and_never_invents_gold():
    """A known answer is the catalog's own class; blank / nan answers are not labels."""
    got = hub_merger_expected_fields(
        merger_row({"No-Shop": " yes ", "Breach of No Shop": "", "FTR Triggers": "nan"})
    )
    assert got == {"maud_clauses": ["No-Shop: Yes"]}  # no consideration answer, no subclass: no token
    assert hub_merger_expected_fields(merger_row({})) == {}
    assert hub_merger_expected_fields("") == {}
    assert hub_merger_expected_fields(None) == {}


def test_consideration_prefers_the_label_then_the_subclass_and_skips_other():
    """The ``Type of Consideration`` answer wins; the subclass is the fallback; ``other`` is no gold."""
    stock_row = merger_row({"Type of Consideration": "All Stock"}, subclass="all_cash")
    assert hub_merger_expected_fields(stock_row)["merger_consideration"] == "all_stock"
    no_answer = merger_row({"No-Shop": "Yes"})
    assert hub_merger_expected_fields(no_answer, "mixed_cash_stock")["merger_consideration"] == (
        "mixed_cash_stock"
    )
    assert "merger_consideration" not in hub_merger_expected_fields(no_answer, "other")
    assert "merger_consideration" not in hub_merger_expected_fields(no_answer, "not a subclass")
    own = merger_row({"No-Shop": "Yes"}, subclass="all_stock")  # the row's own expected_subclass
    assert hub_merger_expected_fields(own)["merger_consideration"] == "all_stock"


@pytest.mark.parametrize("status", ["pending_annotation", "not_applicable", "schema_documented_absence"])
def test_labels_marked_absent_give_no_clause_gold(status):
    """An absent ``gt_presence`` status voids stale labels; only the subclass can still speak."""
    row = merger_row(gt_presence={"maud_clause_labels": status})
    assert hub_merger_expected_fields(row) == {}
    assert hub_merger_expected_fields(row, "all_cash") == {"merger_consideration": "all_cash"}


def test_oracle_prediction_scores_one_on_the_extraction_headline():
    """A prediction equal to the labels scores 1.0 overall, with the MAUD extras beside it."""
    payload = score(ROW, ORACLE)
    assert payload["metric_id"] == "pipeline.extraction.overall"
    assert payload["overall_score"] == 1.0
    assert payload["extraction"].field_scores == {"maud_clauses": 1.0, "merger_consideration": 1.0}
    for key in ("extraction_precision", "extraction_recall", "extraction_f1"):
        assert payload[key] == 1.0, key
    assert payload["maud_question_accuracy"] == 1.0
    assert payload["maud_clause_presence"] == 1.0
    assert payload["n_questions"] == len(GOLD_LINES)


def test_empty_prediction_scores_zero_with_zero_extras():
    """An empty prediction misses both gold fields and every MAUD question."""
    payload = score(ROW, {})
    assert payload["metric_id"] == "pipeline.extraction.overall"
    assert payload["overall_score"] == 0.0
    assert payload["extraction_f1"] == 0.0
    assert payload["maud_question_accuracy"] == 0.0


def test_wrong_consideration_token_costs_only_that_field():
    """A wrong closed-label token scores 0 on its field and leaves the MAUD answers alone."""
    payload = score(ROW, {**ORACLE, "merger_consideration": "all_stock"})
    assert payload["extraction"].field_scores["merger_consideration"] == 0.0
    assert payload["extraction"].field_scores["maud_clauses"] == 1.0
    assert payload["overall_score"] == 0.5
    assert payload["maud_question_accuracy"] == 1.0


def test_a_wrong_answer_is_not_credited_as_a_near_match():
    """``No-Shop: No`` against gold ``Yes`` shares most tokens; it must still be a miss."""
    wrong = [line.replace("No-Shop: Yes", "No-Shop: No") for line in GOLD_LINES]
    payload = score(ROW, {**ORACLE, "maud_clauses": wrong})
    n = len(GOLD_LINES)
    assert payload["maud_question_accuracy"] == round((n - 1) / n, 4)
    assert payload["extraction"].field_scores["maud_clauses"] == round((n - 1) / n, 4)
    assert payload["overall_score"] < 1.0
    assert payload["extraction_recall"] < 1.0


def test_a_dropped_answer_lowers_recall_and_an_unlabelled_extra_lowers_precision():
    """Missing a labelled question is a false negative; answering an unlabelled one a false positive."""
    dropped = score(ROW, {**ORACLE, "maud_clauses": GOLD_LINES[:-1]})
    assert dropped["extraction"].field_scores["maud_clauses"] < 1.0
    extra = score(ROW, {**ORACLE, "maud_clauses": [*GOLD_LINES, "Breach of Meeting Covenant: Yes"]})
    assert extra["extraction"].field_scores["maud_clauses"] == 1.0  # all labelled answers found
    assert extra["extraction"].entity_list_scores["maud_clauses"].unmatched_predicted == 1
    assert extra["extraction_precision"] < 1.0


def _entity(payload: dict[str, Any]) -> Any:
    """The ``maud_clauses`` entity-list score of a scored merger document."""
    return payload["extraction"].entity_list_scores["maud_clauses"]


def test_answering_a_question_the_gold_skips_as_multi_label_is_not_a_false_positive():
    """A Hub multi-label question is unscored on both sides: answering it costs no precision."""
    lab = labels({"No-Shop": "Yes"})
    lab["Breach of No Shop"] = {"answer": ["Yes", "No"], "category": "Deal Protection"}
    row = hub_row(maud_label_count="2", maud_clause_labels=lab, expected_subclass="")
    assert hub_merger_expected_fields(row) == {"maud_clauses": ["No-Shop: Yes"]}
    silent = score(row, {"maud_clauses": ["No-Shop: Yes"]}, subclass=None)
    answered = score(row, {"maud_clauses": ["No-Shop: Yes", "Breach of No Shop: No"]}, subclass=None)
    for payload in (silent, answered):
        assert (_entity(payload).matched, _entity(payload).unmatched_predicted) == (1, 0)
        assert payload["extraction_precision"] == 1.0
        assert payload["extraction_f1"] == 1.0
    # An unrelated, unlabelled question still lowers precision.
    extra = score(row, {"maud_clauses": ["No-Shop: Yes", "Knowledge Definition: Actual knowledge"]},
                  subclass=None)
    assert _entity(extra).unmatched_predicted == 1


def test_answering_a_case_variant_question_with_conflicting_gold_is_not_a_false_positive():
    """``No-Shop`` and ``no-shop`` with different answers is one ambiguous question, unscored."""
    lab = labels({"Specific Performance": '"entitled to" specific performance', "No-Shop": "Yes"})
    lab["no-shop"] = {"answer": "No", "category": "Deal Protection"}
    row = hub_row(maud_label_count="3", maud_clause_labels=lab, expected_subclass="")
    gold = hub_merger_expected_fields(row)["maud_clauses"]
    assert 'Specific Performance: "entitled to" specific performance' in gold
    clean = 'Specific Performance: "entitled to" specific performance'
    for answer in ("Yes", "No"):
        payload = score(row, {"maud_clauses": [clean, f"No-Shop: {answer}"]}, subclass=None)
        assert (_entity(payload).matched, _entity(payload).unmatched_predicted) == (1, 0), answer
        assert payload["extraction_precision"] == 1.0, answer


def test_a_skipped_question_is_skipped_per_row_in_a_batch():
    """Row 1 skips ``No-Shop``; row 2 labels it, so the same prediction is a miss there."""
    skipped = {"No-Shop": {"answer": ["Yes", "No"], "category": "Deal Protection"},
               **labels({"Specific Performance": "Yes"})}
    rows = [
        hub_row(maud_label_count="2", maud_clause_labels=skipped, expected_subclass=""),
        merger_row({"Specific Performance": "Yes", "No-Shop": "No"}),
    ]
    prediction = {"maud_clauses": ["Specific Performance: Yes", "No-Shop: Yes"]}
    payload = get_suite("merger_agreement").score_document(rows, [prediction, prediction])
    first, second = payload["extraction"][0], payload["extraction"][1]
    assert first.entity_list_scores["maud_clauses"].unmatched_predicted == 0
    assert second.entity_list_scores["maud_clauses"].unmatched_predicted == 1


@pytest.mark.parametrize("decorate", [
    lambda line: f"- {line}",
    lambda line: f"* {line}",
    lambda line: f"1. {line}",
    lambda line: line.lower(),
    lambda line: line.upper(),
    lambda line: f"`{line}`",
    lambda line: line.replace(": ", ":   ", 1),
    lambda line: line.replace('"', "“"),
])
def test_clause_lines_tolerate_bullets_case_quotes_and_spacing(decorate):
    """How a model formats a correct catalog line does not change its score."""
    lines = [
        line if line.startswith("Invented") else decorate(line)  # an unknown question is matched as written
        for line in GOLD_LINES
    ]
    payload = score(ROW, {**ORACLE, "maud_clauses": lines})
    assert payload["overall_score"] == 1.0
    assert payload["extraction"].field_scores["maud_clauses"] == 1.0


def test_object_shaped_clause_prediction_scores_like_lines():
    """The ``{question: class}`` object grammar scores the same as the line list."""
    as_object = dict(line.split(": ", 1) for line in GOLD_LINES)
    assert score(ROW, {**ORACLE, "maud_clauses": as_object})["overall_score"] == 1.0


def test_gold_the_row_carries_itself_is_not_overwritten():
    """An explicit ``maud_clauses`` / ``merger_consideration`` on the row beats the derived gold."""
    own = json.loads(merger_row(subclass="all_cash"))
    own["maud_clauses"] = json.dumps(["No-Shop: Yes"])
    own["merger_consideration"] = "all_stock"
    payload = score(json.dumps(own), {"maud_clauses": ["No-Shop: Yes"], "merger_consideration": "all_stock"})
    assert payload["overall_score"] == 1.0
    assert payload["extraction"].field_scores == {"maud_clauses": 1.0, "merger_consideration": 1.0}


@pytest.mark.parametrize("status", ["pending_annotation", "not_applicable", "schema_documented_absence"])
def test_row_whose_labels_are_absent_stays_unscorable(status):
    """A pending / not-applicable label map is never scored, even with a subclass to lean on."""
    payload = score(merger_row(gt_presence={"maud_clause_labels": status}), ORACLE)
    assert payload["status"] == "unscorable"
    assert payload["overall_score"] is None
    assert payload.get("extraction_f1") is None
    assert payload.get("maud_question_accuracy") is None


def test_row_without_answered_questions_stays_unscorable():
    """No labels, or only a subclass, is no ground truth: unscorable, never a 0.0 or a free 1.0."""
    for gt in (hub_row(), merger_row({}, subclass="all_cash")):
        payload = score(gt, ORACLE)
        assert payload["status"] == "unscorable"
        assert payload["overall_score"] is None


def test_labels_with_nothing_derivable_keep_the_maud_headline():
    """Labels that answer no question give no extraction gold: the MAUD headline stays."""
    blank = merger_row({"No-Shop": ""})
    payload = score(blank, {"maud_clauses": ["No-Shop: Yes"]})
    assert payload["metric_id"] == "maud.question.micro_accuracy"
    assert payload["overall_score"] is None
    assert payload["extraction_f1"] is None


def test_batch_scores_each_row_with_its_own_labels_and_subclass():
    """Derivation is per row: each row's labels and own subclass, never the first row's."""
    stock = merger_row({"No-Shop": "Yes", "Type of Consideration": "All Stock"}, subclass="all_stock")
    pending = merger_row(gt_presence={"maud_clause_labels": "pending_annotation"})
    payload = get_suite("merger_agreement").score_document(
        [ROW, stock, pending],
        [ORACLE, {"maud_clauses": ["No-Shop: Yes", "Type of Consideration: All Stock"],
                  "merger_consideration": "all_stock"}, ORACLE],
    )
    assert payload["metric_id"] == "pipeline.extraction.overall"
    assert payload["n_unscorable"] == 1  # the pending row, reported and not averaged in
    assert payload["extraction_f1"] == 1.0
    assert payload["maud_question_accuracy"] == 1.0
    rows = payload["extraction"]
    assert [getattr(r, "overall_score", None) for r in rows] == [1.0, 1.0, None]


def test_batch_with_a_wrong_row_averages_only_scorable_rows():
    """A wrong prediction on one row lowers the batch; a missing prediction is a miss, not a skip."""
    payload = get_suite("merger_agreement").score_document(
        [ROW, ROW], [ORACLE, {"merger_consideration": "all_stock"}]
    )
    assert payload["metric_id"] == "pipeline.extraction.overall"
    assert payload["extraction_recall"] < 1.0
    assert [r.overall_score for r in payload["extraction"]] == [1.0, 0.0]
    missing = get_suite("merger_agreement").score_document([ROW, ROW], [ORACLE])
    assert [r.overall_score for r in missing["extraction"]] == [1.0, 0.0]
    assert missing["n_missing_predictions"] == 1


def test_derived_gold_matches_what_the_merger_prompt_promises():
    """The gold is exactly the shape the specialist is asked to emit, so an oracle can reach it."""
    fields = {f.name: f for f in MergerAgreementExtraction.fields}
    assert fields["maud_clauses"].type == "entity_list:free_text"
    assert "'<Question>: <Hub valid_class>'" in fields["maud_clauses"].description
    assert "omit unanswered" in fields["maud_clauses"].description
    derived = hub_merger_expected_fields(ROW)
    assert set(derived) <= set(fields)
    assert derived["merger_consideration"] in re.findall(
        r"\w+", fields["merger_consideration"].description
    )
    known = [line for line in derived["maud_clauses"] if not line.startswith("Invented")]
    for line in known:
        question, answer = parse_maud_clause(line)  # a line the prompt shape round-trips through
        assert line == f"{question}: {answer}"
        assert answer in maud_question(question).valid_classes  # a verbatim Hub class
    # Every catalog question's own valid class converts to a line that parses back.
    for question in MAUD_QUESTIONS:
        answer = question.valid_classes[0]
        gold = hub_merger_expected_fields(merger_row({question.name: answer}))
        assert gold["maud_clauses"] == [f"{question.name}: {answer}"]
        assert parse_maud_clause(gold["maud_clauses"][0]) == (question.name, answer)


def test_every_consideration_class_converts_to_its_token():
    """Each Hub ``Type of Consideration`` class maps to the token the prompt names."""
    for hub_class, token in MAUD_TYPE_OF_CONSIDERATION_TO_TOKEN.items():
        got = hub_merger_expected_fields(merger_row({"Type of Consideration": hub_class}))
        assert got["merger_consideration"] == token
        assert got["maud_clauses"] == [f"Type of Consideration: {hub_class}"]


def test_helper_is_a_module_function_not_a_root_export():
    """The conversion is public in ``maud_schema`` only; the root package surface is unchanged."""
    import llm_dojo_scoring

    assert "hub_merger_expected_fields" in maud_schema.__all__
    assert not hasattr(llm_dojo_scoring, "hub_merger_expected_fields")


@pytest.mark.parametrize("question", [
    "Agreement provides for matching rights in connection with COR",
    "Agreement provides for matching rights in connection with FTR",
    "Fiduciary exception to COR covenant",
    "Fiduciary exception:  Board determination (no-shop)",
])
def test_the_hub_class_none_is_an_answer_not_a_blank(question):
    """``None`` is a catalog class (no matching right / no exception), so it is gold."""
    row = merger_row({question: "None"}, subclass="all_cash")
    gold = maud_schema.hub_merger_expected_fields(row)
    assert len(gold["maud_clauses"]) == 1
    assert gold["maud_clauses"][0].endswith(": None")
    oracle = score(row, {"maud_clauses": gold["maud_clauses"], "merger_consideration": "all_cash"})
    assert oracle["overall_score"] == 1.0
    wrong = score(row, {"maud_clauses": [gold["maud_clauses"][0][: -len("None")] + "Yes"],
                        "merger_consideration": "all_cash"})
    assert wrong["overall_score"] < 1.0


# --- review findings on the conversion and the question-by-question rescore -------------


def flagged_labels(flag: str) -> dict[str, dict[str, Any]]:
    """Hub labels where ``No-Shop`` carries an explicit ambiguity flag."""
    out = labels({"No-Shop": "Yes", "Specific Performance": '"entitled to" specific performance'})
    out["No-Shop"][flag] = True
    return out


@pytest.mark.parametrize("flag", ["gt_ambiguous", "ambiguous"])
def test_a_label_flagged_ambiguous_is_not_gold(flag):
    """The MAUD scorer excludes a flagged question; the conversion must not turn it into gold."""
    row = hub_row(maud_label_count="2", maud_clause_labels=flagged_labels(flag), expected_subclass="")
    assert hub_merger_expected_fields(row) == {
        "maud_clauses": ['Specific Performance: "entitled to" specific performance']
    }


def test_a_row_whose_every_label_is_ambiguous_stays_unscorable():
    """No clean question, no clause gold: the row is unscorable, not scored on a flagged answer."""
    lab = labels({"No-Shop": "Yes"})
    lab["No-Shop"]["gt_ambiguous"] = True
    row = hub_row(maud_label_count="1", maud_clause_labels=lab, expected_subclass="")
    assert hub_merger_expected_fields(row) == {}
    payload = score(row, {"maud_clauses": ["No-Shop: Yes"]}, subclass=None)
    assert payload["overall_score"] is None
    assert payload["extraction_f1"] is None


@pytest.mark.parametrize("answer", [["Yes", "No"], '["Yes", "No"]', "Yes / Strict liability"])
def test_a_multi_answer_label_is_ambiguous_not_one_joined_answer(answer):
    """A Hub list of answers (or a slash-collapsed one) is unscorable, never gold like ``'Yes, No'``."""
    record = {"answer": answer, "category": "Deal Protection"}
    row = hub_row(maud_label_count="1", maud_clause_labels={"No-Shop": record}, expected_subclass="")
    assert hub_merger_expected_fields(row) == {}


def test_a_list_answer_with_one_distinct_value_is_that_answer():
    """``["Yes", "yes"]`` is one answer; it is not rendered as ``'Yes, yes'``."""
    record = {"answer": ["Yes", "yes", ""], "category": "Deal Protection"}
    row = hub_row(maud_label_count="1", maud_clause_labels={"No-Shop": record}, expected_subclass="")
    assert hub_merger_expected_fields(row) == {"maud_clauses": ["No-Shop: Yes"]}


def test_a_free_text_predicted_clause_is_an_unmatched_prediction():
    """An entry the parser rejects still counts against precision; recall is unchanged."""
    row = merger_row({"No-Shop": "Yes"}, subclass="all_cash")
    payload = score(row, {"maud_clauses": ["No-Shop: Yes", "unsupported clause text"],
                          "merger_consideration": "all_cash"})
    entity = payload["extraction"].entity_list_scores["maud_clauses"]
    assert (entity.matched, entity.unmatched_predicted, entity.unmatched_expected) == (1, 1, 0)
    assert entity.precision == 0.5
    assert entity.recall == 1.0
    assert payload["extraction"].field_scores["maud_clauses"] == 1.0
    assert payload["extraction_precision"] < 1.0


def test_blank_predicted_clause_entries_are_silence_not_unmatched():
    """Empty entries are not predictions."""
    row = merger_row({"No-Shop": "Yes"}, subclass="all_cash")
    payload = score(row, {"maud_clauses": ["No-Shop: Yes", "", "   ", None],
                          "merger_consideration": "all_cash"})
    entity = payload["extraction"].entity_list_scores["maud_clauses"]
    assert entity.unmatched_predicted == 0
    assert entity.precision == 1.0


def test_derived_gold_stays_inside_a_callers_field_map():
    """A caller who scopes ``field_types`` is not charged for fields outside that map."""
    gt = json.loads(merger_row({"No-Shop": "Yes"}, subclass="all_cash"))
    gt["document_name"] = "Acme Merger Agreement"
    suite = get_suite("merger_agreement")
    payload = suite.score_document(
        json.dumps(gt),
        {"document_name": "Acme Merger Agreement"},
        doc_subclass="all_cash",
        field_types={"document_name": "name"},
    )
    assert payload["extraction"].field_scores == {"document_name": 1.0}
    assert payload["overall_score"] == 1.0
    # Without a caller map the suite's own map covers the derived fields.
    default = suite.score_document(json.dumps(gt), {"document_name": "Acme Merger Agreement"},
                                   doc_subclass="all_cash")
    assert {"maud_clauses", "merger_consideration"} <= set(default["extraction"].field_scores)


def test_predicted_clause_objects_are_one_document_not_a_batch():
    """Correct clause objects in another order than the gold lines still score 1.0."""
    row = merger_row({"No-Shop": "Yes", "Specific Performance": '"entitled to" specific performance'},
                     subclass="")
    objects = [
        {"question": "Specific Performance", "answer": '"entitled to" specific performance'},
        {"question": "No-Shop", "answer": "Yes"},
    ]
    payload = score(row, {"maud_clauses": objects}, subclass=None)
    assert payload["extraction"].field_scores["maud_clauses"] == 1.0
    entity = payload["extraction"].entity_list_scores["maud_clauses"]
    assert (entity.matched, entity.unmatched_predicted) == (2, 0)
    extra = [*objects, {"question": "Breach of No Shop", "answer": "No"}]
    payload = score(row, {"maud_clauses": extra}, subclass=None)
    assert payload["extraction"].field_scores["maud_clauses"] == 1.0
    assert payload["extraction"].entity_list_scores["maud_clauses"].unmatched_predicted == 1


def test_gold_lines_that_are_all_ambiguous_are_not_scored_by_the_generic_matcher():
    """Lines the MAUD scorer calls unscorable must not keep a fuzzy-match ``maud_clauses`` score."""
    suite = get_suite("merger_agreement")
    payload = suite.score_document(
        {"maud_clauses": ["No-Shop: Yes / No"]}, {"maud_clauses": ["No-Shop: Yes / No"]}
    )
    assert payload["status"] == "unscorable"
    assert payload["overall_score"] is None
    assert payload.get("extraction_f1") is None
    # A clean question beside an ambiguous one is still scored, on the clean one.
    mixed = suite.score_document(
        {"maud_clauses": ["No-Shop: Yes / No", "Specific Performance: Yes"]},
        {"maud_clauses": ["No-Shop: Yes / No", "Specific Performance: Yes"]},
    )
    assert mixed["extraction"].field_scores["maud_clauses"] == 1.0


@pytest.mark.parametrize("clean_name", ["no-shop", "No Shop", "NO-SHOP"])
def test_a_skipped_variant_does_not_unscore_a_clean_gold_question(clean_name):
    """A multi-label Hub key and a clean case variant of it: the clean line is gold.

    The prediction for it is a match, so it must stay in the precision
    denominator (precision never exceeds 1.0, unmatched never goes negative).
    """
    lab = labels({"Specific Performance": "Yes"})
    lab["No-Shop"] = {"answer": ["Yes", "No"], "category": "x"}
    lab[clean_name] = {"answer": "Yes", "category": "x", "valid_classes": ["Yes"]}
    row = hub_row(maud_label_count="3", maud_clause_labels=lab, expected_subclass="")
    scored = get_suite("merger_agreement").score_document(
        row, {"maud_clauses": ["Specific Performance: Yes", "No-Shop: Yes"]}, subclass=None
    )
    clauses = scored["extraction"].entity_list_scores["maud_clauses"]
    assert (clauses.matched, clauses.unmatched_predicted) == (2, 0)
    assert clauses.precision == 1.0
    assert scored["extraction_precision"] == 1.0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("fallback", [None, "all_stock"])
def test_conflicting_consideration_variants_do_not_derive_scalar_gold(reverse, fallback):
    """Conflicting canonical questions cannot select scalar gold by insertion order."""
    lab = labels({"Type of Consideration": "All Cash", "type of consideration": "All Stock", "No-Shop": "Yes"})
    if reverse:
        lab = dict(reversed(list(lab.items())))
    row = hub_row(maud_label_count="3", maud_clause_labels=lab, expected_subclass=fallback or "")
    expected = {"maud_clauses": ["No-Shop: Yes"]}
    if fallback:
        expected["merger_consideration"] = fallback
    assert hub_merger_expected_fields(row) == expected
    prediction = {"maud_clauses": ["No-Shop: Yes", "Type of Consideration: All Cash"], "merger_consideration": "all_cash"}
    single = score(row, prediction, subclass=None)
    batch = get_suite("merger_agreement").score_document([row, row], [prediction, prediction])
    expected_score = 0.5 if fallback else 1.0
    assert single["overall_score"] == expected_score
    assert batch["quality_mean"] == expected_score
    assert set(single["extraction"].field_scores) == set(expected)
    assert all(set(item.field_scores) == set(expected) for item in batch["extraction"])
    assert hub_merger_expected_fields(row, "mixed_cash_stock")["merger_consideration"] == "mixed_cash_stock"


@pytest.mark.parametrize("variant", ["all_cash", "all cash", "ALL CASH"])
def test_equivalent_consideration_variants_keep_one_gold_answer(variant):
    lab = labels({"Type of Consideration": "All Cash", "type of consideration": variant, "No-Shop": "Yes"})
    expected = {"maud_clauses": ["No-Shop: Yes", "Type of Consideration: All Cash"], "merger_consideration": "all_cash"}
    for ordered in (lab, dict(reversed(list(lab.items())))):
        row = hub_row(maud_label_count="3", maud_clause_labels=ordered, expected_subclass="")
        assert hub_merger_expected_fields(row) == expected
        assert score(row, expected, subclass=None)["overall_score"] == 1.0


@pytest.mark.parametrize("reverse", [False, True])
def test_clean_consideration_variant_survives_flagged_variant(reverse):
    lab = {"Type of Consideration": {"answer": "All Cash", "gt_ambiguous": True}, "type of consideration": {"answer": "All Stock"}, "No-Shop": {"answer": "Yes"}}
    if reverse:
        lab = dict(reversed(list(lab.items())))
    row = hub_row(maud_label_count="3", maud_clause_labels=lab, expected_subclass="all_cash")
    expected = {"maud_clauses": ["No-Shop: Yes", "Type of Consideration: All Stock"], "merger_consideration": "all_stock"}
    assert hub_merger_expected_fields(row) == expected
    assert score(row, expected, subclass=None)["overall_score"] == 1.0
