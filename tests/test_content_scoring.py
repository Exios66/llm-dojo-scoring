"""Enron topic/sentiment and MAUD per-question extraction scorers."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.content_scoring import (
    normalize_content_topic,
    normalize_maud_answer,
    normalize_maud_question_key,
    normalize_sentiment_label,
    parse_maud_labels,
    peel_non_extraction_fields,
    score_content_topic,
    score_correspondence_content,
    score_maud_extraction,
    score_sentiment,
)
from llm_dojo_scoring.corpus import (
    CORRESPONDENCE_SENTIMENT_LABELS,
    CORRESPONDENCE_TOPICS,
    MAUD_QUESTION_KEYS,
)
from llm_dojo_scoring.suites import get_suite
from llm_dojo_scoring.tasks import maud_extraction_score, score_task


def test_normalize_content_topic_aliases():
    assert normalize_content_topic("Legal Contracts") == "legal_contracts"
    assert normalize_content_topic("hr-personnel") == "hr_personnel"
    assert normalize_content_topic("IT Systems") == "it_systems"
    assert normalize_content_topic("") == ""
    assert set(CORRESPONDENCE_TOPICS) == {
        "announcements", "energy_market", "finance_earnings",
        "general_business", "hr_personnel", "it_systems", "legal_contracts",
        "marketing_clients", "regulatory", "scheduling", "travel_logistics",
    }


def test_normalize_sentiment_aliases():
    assert normalize_sentiment_label("POS") == "positive"
    assert normalize_sentiment_label("Neg") == "negative"
    assert normalize_sentiment_label("neu") == "neutral"
    assert tuple(CORRESPONDENCE_SENTIMENT_LABELS) == (
        "negative", "neutral", "positive",
    )


def test_content_topic_perfect_and_mismatch():
    expected = ["legal_contracts", "scheduling", "hr_personnel"]
    perfect = score_content_topic(expected, expected)
    assert perfect["content_topic_accuracy"] == 1.0
    assert perfect["content_topic_f1_macro"] == 1.0
    assert perfect["n"] == 3

    mixed = score_content_topic(expected, ["legal_contracts", "travel_logistics", "hr_personnel"])
    assert mixed["content_topic_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert mixed["per_class"]["scheduling"]["accuracy"] == 0.0
    assert mixed["per_class"]["legal_contracts"]["accuracy"] == 1.0


def test_sentiment_macro_f1_on_imbalance():
    expected = ["negative", "negative", "positive"]
    predicted = ["negative", "neutral", "positive"]
    out = score_sentiment(expected, predicted)
    assert out["sentiment_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["f1_macro"] < 1.0
    assert out["per_class"]["negative"]["n"] == 2


def test_score_task_routes_enron_keys():
    topics = score_task(
        "enron_topic",
        ["legal_contracts"],
        ["Legal Contracts"],
    )
    assert topics["content_topic_accuracy"] == 1.0
    sent = score_task("sentiment", ["negative"], ["neg"])
    assert sent["sentiment_accuracy"] == 1.0


def test_correspondence_suite_scores_content_without_polluting_extraction():
    expected = {
        "sender": "Jeffrey Skilling",
        "recipient": "Kenneth Lay",
        "content_topic": "legal_contracts",
        "sentiment_label": "negative",
        "topic_evidence": "see clause 4",
    }
    predicted = {
        "sender": "Jeffrey Skilling",
        "recipient": "Kenneth Lay",
        "content_topic": "legal_contracts",
        "sentiment_label": "negative",
    }
    out = get_suite("correspondence_specialist").score(expected, predicted)
    assert isinstance(out, dict)
    assert out["content_topic_accuracy"] == 1.0
    assert out["sentiment_accuracy"] == 1.0
    assert "sender" in out["extraction"].field_scores
    assert "content_topic" not in out["extraction"].field_scores
    assert "topic_evidence" not in out["extraction"].field_scores


def test_correspondence_extraction_only_still_returns_dataclass():
    expected = {"sender": "A", "recipient": "B"}
    predicted = {"sender": "A", "recipient": "B"}
    out = get_suite("correspondence_specialist").score(expected, predicted)
    assert out.overall_score == 1.0
    assert get_suite("correspondence_specialist").honest_gap is None
    names = set(get_suite("correspondence_specialist").metric_names())
    assert {
        "content_topic_accuracy",
        "content_topic_f1_macro",
        "sentiment_accuracy",
        "sentiment_f1_macro",
    } <= names


def test_correspondence_kwargs_topic_sentiment():
    out = get_suite("correspondence_specialist").score(
        {"sender": "A"},
        {"sender": "A"},
        expected_topic="scheduling",
        predicted_topic="travel_logistics",
        expected_sentiment="positive",
        predicted_sentiment="positive",
    )
    assert out["content_topic_accuracy"] == 0.0
    assert out["sentiment_accuracy"] == 1.0


def test_peel_leaves_extraction_fields():
    exp, pred, payload = peel_non_extraction_fields(
        {"sender": "A", "content_topic": "regulatory", "maud_clause_labels": {}},
        {"sender": "B", "content_topic": "regulatory"},
    )
    assert exp == {"sender": "A"}
    assert pred == {"sender": "B"}
    assert payload["content_topic"] == ("regulatory", "regulatory")
    assert "maud" in payload


def test_parse_maud_labels_from_json_and_spans():
    labels = parse_maud_labels({
        "Type of Consideration": {
            "answer": "All Cash",
            "category": "General Information",
        },
        "No-Shop": {"answer": "Yes", "category": "Deal Protection and Related Provisions"},
    })
    assert labels["Type of Consideration"]["answer"] == "All Cash"
    assert labels["No-Shop"]["category"] == "Deal Protection and Related Provisions"

    spans = parse_maud_labels([
        "Type of Consideration: All Cash",
        "Fiduciary exception:  Board determination (no-shop): Yes",
    ])
    assert "Type of Consideration" in spans
    assert "Fiduciary exception:  Board determination (no-shop)" in spans
    assert spans["Fiduciary exception:  Board determination (no-shop)"]["answer"] == "Yes"


def test_maud_extraction_exact_presence_valid_class():
    expected = {
        "Type of Consideration": {"answer": "All Cash", "category": "General Information"},
        "No-Shop": {"answer": "Yes", "category": "Deal Protection and Related Provisions"},
        "MAE Definition": {"answer": "standard MAE", "category": "Material Adverse Effect"},
    }
    predicted = {
        "Type of Consideration": {"answer": "all cash", "category": "General Information"},
        "No-Shop": {"answer": "No"},
        # MAE Definition missing
    }
    out = score_maud_extraction(expected, predicted)
    assert out["n_questions"] == 3
    assert out["maud_clause_presence"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["maud_question_accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    assert out["per_question"]["Type of Consideration"]["accuracy"] == 1.0
    assert out["per_question"]["No-Shop"]["accuracy"] == 0.0
    assert out["per_question"]["MAE Definition"]["presence"] == 0.0
    assert out["maud_valid_class_rate"] == 1.0  # All Cash + No are valid
    assert out["maud_category_accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    assert len(MAUD_QUESTION_KEYS) == 22


def test_maud_extraction_from_clause_spans_and_task_router():
    expected = [
        "Type of Consideration: All Stock",
        "No-Shop: Yes",
    ]
    predicted = [
        "Type of Consideration: All Stock",
        "No-Shop: Yes",
    ]
    out = score_task("maud_extraction", expected, predicted)
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_clause_presence"] == 1.0
    assert maud_extraction_score(expected, predicted)["maud_question_macro_accuracy"] == 1.0


def test_normalize_maud_question_and_consideration_answer():
    assert normalize_maud_question_key("type of consideration") == "Type of Consideration"
    assert normalize_maud_answer("Type of Consideration", "All Cash") == "all_cash"
    assert normalize_maud_answer("No-Shop", "YES") == "yes"


def test_merger_suite_scores_maud_labels_and_has_no_honest_gap():
    suite = get_suite("merger_agreement")
    assert suite.honest_gap is None
    names = set(suite.metric_names())
    assert {
        "maud_question_accuracy",
        "maud_question_macro_accuracy",
        "maud_clause_presence",
        "maud_valid_class_rate",
        "maud_category_accuracy",
    } <= names

    expected = {
        "parties": ["Acme Inc", "Beta LLC"],
        "maud_clause_labels": {
            "Type of Consideration": {"answer": "All Cash", "category": "General Information"},
            "No-Shop": {"answer": "Yes"},
        },
    }
    predicted = {
        "parties": ["Acme Inc", "Beta LLC"],
        "maud_clauses": [
            "Type of Consideration: All Cash",
            "No-Shop: Yes",
        ],
    }
    out = suite.score(expected, predicted)
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_clause_presence"] == 1.0
    assert "parties" in out["extraction"].field_scores
    assert "maud_clause_labels" not in out["extraction"].field_scores
