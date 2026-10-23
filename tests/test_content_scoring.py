"""Enron topic/sentiment and MAUD per-question extraction scorers."""

from __future__ import annotations

import json
from functools import partial

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
from llm_dojo_scoring.gt_metadata import ANNOTATION_KEYS


@pytest.fixture(params=["direct", "dispatch"])
def maud_scorer(request):
    """Run MAUD document-pair cases through both supported scoring entry points."""
    if request.param == "direct":
        return score_maud_extraction
    return partial(score_task, "maud_extraction")


@pytest.fixture(
    params=[(False, False), (True, False), (False, True), (True, True)],
    ids=["native", "expected-json", "predicted-json", "both-json"],
)
def maud_inputs(request):
    """Encode each input independently to exercise batch recognition after JSON."""
    encode_expected, encode_predicted = request.param

    def encode(expected, predicted):
        """Preserve native values unless this case requires their JSON form."""
        return (
            json.dumps(expected) if encode_expected else expected,
            json.dumps(predicted) if encode_predicted else predicted,
        )

    return encode


@pytest.mark.parametrize("sizes", [(2, 0), (0, 2), (3, 2), (2, 3)])
def test_unequal_mixed_maud_batches_report_both_lengths(
    maud_scorer, maud_inputs, sizes
):
    """Mixed batches reject missing, extra, and entirely absent paired documents."""
    rows = [
        {"Type of Consideration": "All Cash"},
        "No-Shop: Yes",
        {"Type of Consideration": "All Stock"},
    ]
    n_expected, n_predicted = sizes
    expected, predicted = maud_inputs(rows[:n_expected], rows[:n_predicted])

    with pytest.raises(
        ValueError, match=rf"expected.*{n_expected}.*predicted.*{n_predicted}"
    ):
        maud_scorer(expected, predicted)


@pytest.mark.parametrize("reverse", [False, True], ids=["missing", "extra"])
def test_maud_cardinality_precedes_record_parsing(maud_scorer, reverse):
    """Incomplete batches fail on counts even when a retained row is malformed."""
    expected = [
        {"Type of Consideration": {"answer": "All Cash", "valid_classes": 1}},
        "No-Shop: Yes",
    ]
    predicted = [{"Type of Consideration": "All Cash"}]
    if reverse:
        expected, predicted = predicted, expected

    with pytest.raises(
        ValueError, match=rf"expected.*{len(expected)}.*predicted.*{len(predicted)}"
    ):
        maud_scorer(expected, predicted)


@pytest.mark.parametrize("reverse", [False, True], ids=["missing", "extra"])
def test_maud_empty_first_record_still_recognizes_a_mixed_batch(maud_scorer, reverse):
    """An empty first record identifies a batch regardless of its truthiness."""
    expected, predicted = [{}, "No-Shop: Yes"], [{}]
    if reverse:
        expected, predicted = predicted, expected

    with pytest.raises(
        ValueError, match=rf"expected.*{len(expected)}.*predicted.*{len(predicted)}"
    ):
        maud_scorer(expected, predicted)


def test_equal_mixed_maud_batches_score_every_document(maud_scorer, maud_inputs):
    """Keep row order and micro/macro denominators across record and span rows."""
    expected, predicted = maud_inputs(
        [
            {"Type of Consideration": "All Cash"},
            "No-Shop: Yes",
            {"Type of Consideration": "All Stock"},
        ],
        [
            {"Type of Consideration": "All Cash"},
            "No-Shop: No",
            {"Type of Consideration": "All Stock"},
        ],
    )
    result = maud_scorer(expected, predicted)

    assert result["n_documents"] == 3
    assert result["n_questions"] == 3
    assert [row["exact"] for row in result["per_document"]] == [1, 0, 1]
    assert result["maud_question_accuracy"] == 0.6667
    assert result["maud_question_macro_accuracy"] == 0.5
    assert result["maud_clause_presence"] == 1.0
    assert result["maud_valid_class_rate"] == 1.0
    assert result["per_question"]["Type of Consideration"]["n"] == 2
    assert result["per_question"]["No-Shop"]["accuracy"] == 0.0


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_maud_batch_versus_spans_keeps_pairing(maud_scorer, maud_inputs, reverse):
    """Unequal batch-versus-span inputs retain their documented pairing behavior."""
    expected = [{"Type of Consideration": "All Cash"}, "No-Shop: Yes"]
    predicted = ["Type of Consideration: All Cash"]
    if reverse:
        expected, predicted = predicted, expected
    expected, predicted = maud_inputs(expected, predicted)

    result = maud_scorer(expected, predicted)

    assert result["n_documents"] == 1
    assert result["n_questions"] == 1
    assert result["maud_question_accuracy"] == 1.0


def test_maud_span_first_list_with_later_record_is_one_document(maud_scorer):
    """A later record does not turn a span-first list into a document batch."""
    result = maud_scorer(
        [
            "No-Shop: Yes",
            {"question": "Type of Consideration", "answer": "All Cash"},
        ],
        ["No-Shop: Yes"],
    )

    assert result["n_documents"] == 1
    assert result["n_questions"] == 2
    assert result["maud_question_accuracy"] == 0.5
    assert result["maud_clause_presence"] == 0.5


@pytest.mark.parametrize(
    "predicted",
    [
        {"Type of Consideration": "All Cash", "No-Shop": "Yes"},
        "Type of Consideration: All Cash\nNo-Shop: Yes",
    ],
    ids=["label-map", "multiline-spans"],
)
def test_mixed_maud_batches_broadcast_scalar_predictions(maud_scorer, predicted):
    """Scalar predictions remain reusable for every row in an expected mixed batch."""
    result = maud_scorer(
        [{"Type of Consideration": "All Cash"}, "No-Shop: Yes"], predicted
    )

    assert result["n_documents"] == 2
    assert result["n_questions"] == 2
    assert [row["exact"] for row in result["per_document"]] == [1, 1]
    assert result["maud_question_accuracy"] == 1.0


def test_empty_maud_span_lists_remain_one_document(maud_scorer):
    """Two empty span lists have no batch marker and no scorable questions."""
    result = maud_scorer([], [])

    assert result["n_documents"] == 1
    assert result["n_questions"] == 0
    assert result["per_document"][0]["n_questions"] == 0
    assert result["maud_question_accuracy"] is None


def test_peeling_annotations_preserves_trace_fields_and_content_payload():
    """Separate annotations and content labels without losing prediction trace fields."""
    expected = {key: "annotation" for key in ANNOTATION_KEYS}
    expected.update(sender="Alice", content_topic="legal_contracts")
    predicted = {key: "different annotation" for key in ANNOTATION_KEYS}
    predicted.update(sender="Alice", content_topic="legal_contracts", confidence=0.9, reasoning="Evidence")
    exp_fields, pred_fields, payload = peel_non_extraction_fields(expected, predicted)
    assert exp_fields == {"sender": "Alice"}
    assert pred_fields == {"sender": "Alice", "confidence": 0.9, "reasoning": "Evidence"}
    assert payload["content_topic"] == ("legal_contracts", "legal_contracts")
    assert expected["content_topic"] == "legal_contracts"
    assert ANNOTATION_KEYS <= predicted.keys()


def test_normalize_content_topic_aliases():
    """Canonicalize topic aliases and pin the supported correspondence vocabulary."""
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
    """Canonicalize sentiment abbreviations into the three supported labels."""
    assert normalize_sentiment_label("POS") == "positive"
    assert normalize_sentiment_label("Neg") == "negative"
    assert normalize_sentiment_label("neu") == "neutral"
    assert tuple(CORRESPONDENCE_SENTIMENT_LABELS) == (
        "negative", "neutral", "positive",
    )


def test_content_topic_perfect_and_mismatch():
    """Compute topic accuracy and per-class scores for perfect and mixed predictions."""
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
    """Reflect an imbalanced sentiment error in aggregate and per-class scores."""
    expected = ["negative", "negative", "positive"]
    predicted = ["negative", "neutral", "positive"]
    out = score_sentiment(expected, predicted)
    assert out["sentiment_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["f1_macro"] < 1.0
    assert out["per_class"]["negative"]["n"] == 2


def test_score_task_routes_enron_keys():
    """Route Enron topic and sentiment task aliases to their dedicated scorers."""
    topics = score_task(
        "enron_topic",
        ["legal_contracts"],
        ["Legal Contracts"],
    )
    assert topics["content_topic_accuracy"] == 1.0
    sent = score_task("sentiment", ["negative"], ["neg"])
    assert sent["sentiment_accuracy"] == 1.0


def test_correspondence_suite_scores_content_without_polluting_extraction():
    """Score correspondence labels separately from extraction fields and evidence."""
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
    """Retain the extraction-only result type while exposing content metrics."""
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
    """Score explicit topic and sentiment keyword pairs independently."""
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
    """Retain sender fields while separating topic and MAUD payloads."""
    exp, pred, payload = peel_non_extraction_fields(
        {"sender": "A", "content_topic": "regulatory", "maud_clause_labels": {}},
        {"sender": "B", "content_topic": "regulatory"},
    )
    assert exp == {"sender": "A"}
    assert pred == {"sender": "B"}
    assert payload["content_topic"] == ("regulatory", "regulatory")
    assert "maud" in payload


def test_parse_maud_labels_from_json_and_spans():
    """Parse MAUD mappings and spans without splitting colons inside question names."""
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
    """Separate MAUD answer accuracy, presence, valid classes, and category accuracy."""
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
    """Score matching MAUD spans through task routing and the scoring alias."""
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
    """Canonicalize MAUD question names and question-specific answer labels."""
    assert normalize_maud_question_key("type of consideration") == "Type of Consideration"
    assert normalize_maud_answer("Type of Consideration", "All Cash") == "all_cash"
    assert normalize_maud_answer("No-Shop", "YES") == "yes"


def test_merger_suite_scores_maud_labels_and_has_no_honest_gap():
    """Expose computable MAUD metrics without treating clause labels as extraction fields."""
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
