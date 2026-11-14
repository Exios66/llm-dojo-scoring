"""Every live document class computes its headline metric honestly from Hub rows.

The rows below copy the structure of ``Lucius-Morningstar/mailroom-dataset``
``ground_truth`` rows (every column a string, blank labels as ``""``, JSON
columns as JSON text, ``gt_presence`` as JSON text), with invented values. Each
case goes through the public per-document entry point,
``get_suite(doc_class).score_document(gt_fields, predicted, doc_subclass=...)``,
which is the path consumers use for Hub-grounded runs.

The contract, for each class:

* an oracle prediction scores the headline 1.0 and field-micro F1 1.0 (or null
  when the class has no labelled extraction field);
* an empty prediction scores the headline 0.0;
* a correct value on a schema field the dataset leaves blank is neither a hit
  nor a false positive (unlabelled fields are excluded on both sides);
* a label the dataset writes as the literal ``"nan"`` is not ground truth;
* a row with no labels at all is unscorable, never a 0.0.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.scoring.field_scoring import ExtractionScoreResult

#: The payload key that carries each headline ``metric_id``.
HEADLINE_KEY = {
    "pipeline.extraction.overall": "overall_score",
    "cuad.clause_presence.micro_f1": "extraction_category_presence",
    "maud.question.micro_accuracy": "maud_question_accuracy",
}

#: Hub text columns that are blank unless a class labels them.
_TEXT_COLUMNS = (
    "adjuster", "claim_number", "claim_type", "claimed_amount", "clause_count",
    "content_topic", "coverage_determination", "damages_description",
    "date_filed", "date_of_loss", "insured_party", "insurer", "intent",
    "intent_confidence", "intent_source", "intent_status", "keywords",
    "label_evidence", "maud_label_count", "policy_number", "sentiment_evidence",
    "sentiment_label", "sentiment_score", "subject_matter", "topic_evidence",
)


def hub_row(**labels: Any) -> str:
    """One synthetic ``gt_fields`` value shaped like a Hub ``ground_truth`` row."""
    row: dict[str, Any] = {name: "" for name in _TEXT_COLUMNS}
    row.update(
        cuad_clause_labels="{}",
        maud_clause_labels="{}",
        denial_reasons="[]",
        supporting_documents="[]",
        related_document_ids="[]",
        relationships="[]",
    )
    for name, value in labels.items():
        row[name] = value if isinstance(value, str) else json.dumps(value)
    return json.dumps(row)


CONTRACT_GT = hub_row(
    clause_count="3",
    cuad_clause_labels={
        "Governing Law": [{"text": "governed by the laws of Delaware", "start": 120}],
        "Cap On Liability": [{"text": "liability shall not exceed the fees paid", "start": 480}],
        "Audit Rights": [],
    },
)
CONTRACT_ORACLE = {
    "cuad_clauses": [
        "This Agreement is governed by the laws of Delaware.",
        "Total liability shall not exceed the fees paid in the prior year.",
    ],
}

MERGER_GT = hub_row(
    maud_label_count="2",
    maud_clause_labels={
        "Absence of Litigation Closing Condition": {"answer": "Pending", "category": "Conditions"},
        "Fiduciary exception": {"answer": "Yes", "category": "Deal Protection"},
    },
)
#: The labels give two answered questions; the row's subclass (``all_cash`` in
#: ``LIVE_CLASS_ROWS``) gives ``merger_consideration``. Both are extraction gold.
MERGER_ORACLE = {
    "maud_clauses": [
        "Absence of Litigation Closing Condition: Pending",
        "Fiduciary exception: Yes",
    ],
    "merger_consideration": "all_cash",
}

CORPORATE_LABELS = {
    "intent": "governance_rules",
    "keywords": ["bylaws", "board of directors", "quorum"],
    "subject_matter": "Bylaws of Example Holdings Inc. governing board meetings.",
    "record_type": "bylaws",
    "entity_name": "Example Holdings Inc.",
}
CORPORATE_GT = hub_row(**CORPORATE_LABELS)
CORPORATE_ORACLE = {
    **CORPORATE_LABELS,
    "keywords": ["bylaws", "board of directors", "quorum"],
}

CORRESPONDENCE_LABELS = {
    "intent": "other",
    "keywords": ["quarterly budget", "forecast"],
    "subject_matter": "Correspondence about the quarterly budget forecast.",
}
CORRESPONDENCE_GT = hub_row(
    **CORRESPONDENCE_LABELS, content_topic="general_business", sentiment_label="neutral"
)
CORRESPONDENCE_ORACLE = {
    **CORRESPONDENCE_LABELS,
    "content_topic": "general_business",
    "sentiment_label": "neutral",
}

INSURANCE_LABELS = {
    "claim_number": "CLM-0001",
    "policy_number": "POL-1234",
    "insurer": "Example Mutual Insurance",
    "insured_party": "Jordan Example",
    "claim_type": "property",
    "date_of_loss": "2024-02-03",
    "date_filed": "2024-02-10",
    "claimed_amount": "1250.00",
    "damages_description": "Water damage to a kitchen ceiling after a pipe burst.",
    "coverage_determination": "approved",
    "intent": "claim_submission",
    "subject_matter": "Property claim for water damage.",
    "keywords": ["water damage", "property claim"],
}
INSURANCE_GT = hub_row(**INSURANCE_LABELS)
INSURANCE_ORACLE = dict(INSURANCE_LABELS)

#: (doc_class, doc_subclass, gt_fields, oracle prediction, expected headline metric_id)
LIVE_CLASS_ROWS = [
    ("contract", "License_Agreements", CONTRACT_GT, CONTRACT_ORACLE,
     "cuad.clause_presence.micro_f1"),
    ("merger_agreement", "all_cash", MERGER_GT, MERGER_ORACLE,
     "pipeline.extraction.overall"),
    ("corporate_record", "bylaws", CORPORATE_GT, CORPORATE_ORACLE,
     "pipeline.extraction.overall"),
    ("correspondence", "email", CORRESPONDENCE_GT, CORRESPONDENCE_ORACLE,
     "pipeline.extraction.overall"),
    ("insurance_claim", "property", INSURANCE_GT, INSURANCE_ORACLE,
     "pipeline.extraction.overall"),
]
_IDS = [row[0] for row in LIVE_CLASS_ROWS]


def score(doc_class: str, gt_fields: str, predicted: dict, subclass: str) -> dict[str, Any]:
    """Score one document through the public per-document entry point."""
    return get_suite(doc_class).score_document(gt_fields, predicted, doc_subclass=subclass)


def headline(payload: dict[str, Any]) -> float | None:
    """The value of the payload's own headline metric."""
    return payload.get(HEADLINE_KEY[payload["metric_id"]])


@pytest.mark.parametrize(("doc_class", "subclass", "gt", "oracle", "metric_id"),
                         LIVE_CLASS_ROWS, ids=_IDS)
def test_oracle_prediction_scores_the_headline_one(doc_class, subclass, gt, oracle, metric_id):
    """A prediction equal to the labels scores 1.0 on the class headline."""
    payload = score(doc_class, gt, oracle, subclass)
    assert payload["metric_id"] == metric_id
    assert headline(payload) == 1.0
    assert payload.get("extraction_f1") in (1.0, None)


@pytest.mark.parametrize(("doc_class", "subclass", "gt", "oracle", "metric_id"),
                         LIVE_CLASS_ROWS, ids=_IDS)
def test_empty_prediction_scores_the_headline_zero(doc_class, subclass, gt, oracle, metric_id):
    """An empty prediction scores 0.0 on the class headline."""
    payload = score(doc_class, gt, {}, subclass)
    assert payload["metric_id"] == metric_id
    assert headline(payload) == 0.0


@pytest.mark.parametrize(("doc_class", "extra"), [
    ("correspondence", {"communication_type": "email", "sender": "Avery Example"}),
    ("corporate_record", {"jurisdiction": "Delaware", "effective_date": "2020-01-01"}),
    ("insurance_claim", {"claim_checklist": ["proof of loss"]}),
])
def test_value_on_an_unlabelled_field_is_not_a_false_positive(doc_class, extra):
    """A schema field the dataset leaves blank is excluded on both sides."""
    _, subclass, gt, oracle, _ = next(row for row in LIVE_CLASS_ROWS if row[0] == doc_class)
    payload = score(doc_class, gt, {**oracle, **extra}, subclass)
    assert payload["overall_score"] == 1.0
    assert payload["extraction_precision"] == 1.0
    assert payload["extraction_f1"] == 1.0


def test_value_on_a_field_labelled_empty_is_a_false_positive():
    """Insurance labels a blank ``adjuster`` as documented absence: a value is an FP."""
    payload = score("insurance_claim", INSURANCE_GT,
                    {**INSURANCE_ORACLE, "adjuster": "Casey Example"}, "property")
    assert payload["extraction_precision"] < 1.0


def test_off_schema_key_is_still_a_false_positive():
    """A key that is not in the class schema at all still lowers precision."""
    payload = score("correspondence", CORRESPONDENCE_GT,
                    {**CORRESPONDENCE_ORACLE, "invented_field": "x"}, "email")
    assert payload["overall_score"] == 1.0
    assert payload["extraction_precision"] < 1.0


@pytest.mark.parametrize("doc_class", ["insurance_claim", "correspondence"])
def test_nan_literal_label_is_not_ground_truth(doc_class):
    """``"nan"`` topic / sentiment labels emit no topic or sentiment score."""
    _, subclass, _, oracle, _ = next(row for row in LIVE_CLASS_ROWS if row[0] == doc_class)
    labels = INSURANCE_LABELS if doc_class == "insurance_claim" else CORRESPONDENCE_LABELS
    gt = hub_row(**labels, content_topic="nan", sentiment_label="nan",
                 sentiment_score="nan", topic_evidence="nan")
    prediction = {k: v for k, v in oracle.items() if k not in ("content_topic", "sentiment_label")}
    payload = score(doc_class, gt, prediction, subclass)
    for key in ("content_topic_accuracy", "content_topic_f1_macro",
                "sentiment_accuracy", "sentiment_f1_macro"):
        assert payload.get(key) is None, key
    assert payload["overall_score"] == 1.0


def test_labelled_topic_still_scores_a_wrong_prediction():
    """A real topic label is scored, so a wrong topic is a 0.0, not a skip."""
    payload = score("correspondence", CORRESPONDENCE_GT,
                    {**CORRESPONDENCE_ORACLE, "content_topic": "legal"}, "email")
    assert payload["content_topic_accuracy"] == 0.0
    assert payload["sentiment_accuracy"] == 1.0


def test_merger_labels_are_extraction_gold_with_field_micro():
    """MAUD labels give merger extraction gold, so field-micro P/R/F1 are real numbers."""
    payload = score("merger_agreement", MERGER_GT, MERGER_ORACLE, "all_cash")
    assert payload["maud_question_accuracy"] == 1.0
    for key in ("extraction_precision", "extraction_recall",
                "extraction_f1", "extraction_f2"):
        assert payload[key] == 1.0, key


@pytest.mark.parametrize(("subclass", "record_type"), [
    ("board_resolution", "other"),
    ("charter_amendment", "articles_of_incorporation"),
    ("indenture", "other"),
])
def test_corporate_record_type_comes_from_the_label_not_the_subclass(subclass, record_type):
    """The labelled ``record_type`` is the gold, whatever the subclass is called."""
    labels = {**CORPORATE_LABELS, "record_type": record_type}
    payload = score("corporate_record", hub_row(**labels), dict(labels), subclass)
    assert payload["overall_score"] == 1.0
    assert payload["extraction"].field_scores["record_type"] == 1.0


@pytest.mark.parametrize("doc_class", _IDS)
def test_row_without_labels_is_unscorable(doc_class):
    """A Hub row with no labels for the class is unscorable, never a 0.0."""
    _, subclass, _, oracle, _ = next(row for row in LIVE_CLASS_ROWS if row[0] == doc_class)
    payload = score(doc_class, hub_row(), oracle, subclass)
    assert payload.get("status") == "unscorable"
    assert payload.get("overall_score") is None
    assert payload.get("extraction_f1") is None


def test_batch_payloads_follow_the_single_document_rules():
    """A batch of Hub rows keeps the same headline, null and label rules."""
    merger = get_suite("merger_agreement").score_document(
        [MERGER_GT, MERGER_GT], [MERGER_ORACLE, MERGER_ORACLE], doc_subclass="all_cash"
    )
    assert merger["metric_id"] == "pipeline.extraction.overall"
    assert merger["maud_question_accuracy"] == 1.0
    assert merger["extraction_f1"] == 1.0

    stray = hub_row(claim_type="property")
    with_unscorable = get_suite("merger_agreement").score_document(
        [MERGER_GT, stray], [MERGER_ORACLE, {"intent": "acquisition"}], doc_subclass="all_cash"
    )
    assert with_unscorable["metric_id"] == "pipeline.extraction.overall"
    assert with_unscorable["n_unscorable"] == 1
    assert with_unscorable["extraction_f1"] == 1.0

    nan_gt = hub_row(**CORRESPONDENCE_LABELS, content_topic="nan", sentiment_label="nan")
    letters = get_suite("correspondence").score_document(
        [CORRESPONDENCE_GT, nan_gt],
        [{**CORRESPONDENCE_ORACLE, "communication_type": "email"}, dict(CORRESPONDENCE_LABELS)],
        doc_subclass="email",
    )
    assert letters["content_topic_accuracy"] == 1.0
    assert letters["sentiment_accuracy"] == 1.0
    assert letters["extraction_precision"] == 1.0


def test_mixed_merger_batch_keeps_the_extraction_headline():
    """A batch with one row that labels extraction fields keeps the overall headline."""
    labels = {"intent": "acquisition", "subject_matter": "Merger of Example Corp into Example Sub."}
    labelled = hub_row(
        maud_label_count="2",
        maud_clause_labels=json.loads(json.loads(MERGER_GT)["maud_clause_labels"]),
        **labels,
    )
    payload = get_suite("merger_agreement").score_document(
        [MERGER_GT, labelled], [MERGER_ORACLE, {**MERGER_ORACLE, **labels}],
        doc_subclass="all_cash",
    )
    assert payload["metric_id"] == "pipeline.extraction.overall"


def test_empty_label_batch_is_not_scored():
    """An empty expected label list is no labels at all, not a length error."""
    result = get_suite("correspondence").score(
        dict(CORRESPONDENCE_LABELS), dict(CORRESPONDENCE_LABELS),
        expected_topic=[], predicted_topic=["general_business"],
    )
    assert isinstance(result, ExtractionScoreResult)
    assert result.overall_score == 1.0


def test_cms_row_value_on_an_omitted_documented_absent_field_is_a_false_positive():
    """A CMS row that omits ``adjuster`` still treats a stated adjuster as an FP."""
    from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics
    from llm_dojo_scoring.schemas.doc_classes import field_types

    expected = {"claim_type": "health", "claim_number": "CLM-0002", "cms_source_table": "carrier"}
    predicted = {**expected, "adjuster": "Casey Example"}
    counts = extraction_binary_metrics(
        expected, predicted, field_types=field_types("insurance_claim"), doc_class="insurance_claim"
    )
    assert counts["fp"] == 1
    assert counts["extraction_precision"] < 1.0


def test_batch_row_with_no_expected_fields_adds_no_false_positives():
    """A batch row whose expected dict is empty contributes no field-micro events."""
    labels = dict(CORRESPONDENCE_LABELS)
    payload = get_suite("correspondence").score_document(
        [labels, {}], [dict(labels), {"invented_field": "x"}], doc_subclass="email"
    )
    assert payload["extraction_precision"] == 1.0


def test_cms_omitted_field_without_a_field_map_is_one_false_positive():
    """Without a field map, an omitted CMS adjuster is still one FP, not two."""
    from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics

    expected = {"claim_type": "health", "claim_number": "CLM-0002", "cms_source_table": "carrier"}
    counts = extraction_binary_metrics(
        expected, {**expected, "adjuster": "Casey Example"}, doc_class="insurance_claim"
    )
    assert counts["fp"] == 1


@pytest.mark.parametrize("with_field_map", [True, False])
@pytest.mark.parametrize("omitted", [True, False])
def test_cms_blank_list_items_are_silence(omitted, with_field_map):
    """``denial_reasons: [None, ""]`` on a CMS row is silence, as in ``score_extraction``."""
    from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics
    from llm_dojo_scoring.schemas.doc_classes import field_types

    expected = {"claim_type": "health", "claim_number": "CLM-0002", "cms_source_table": "carrier"}
    if not omitted:
        expected["denial_reasons"] = ""
    counts = extraction_binary_metrics(
        expected, {**expected, "denial_reasons": [None, ""]},
        field_types=field_types("insurance_claim") if with_field_map else None,
        doc_class="insurance_claim",
    )
    assert counts["fp"] == 0
