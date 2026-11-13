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
