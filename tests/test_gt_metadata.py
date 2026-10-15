"""Hub GT metadata handling — mailroom-dataset ``gt_fields`` parity.

Fixtures mirror real rows from ``Lucius-Morningstar/mailroom-dataset``
(config ``ground_truth``, 2026-10-04): union field dict + stringified
``gt_presence`` map. The tests lock the two failure modes fixed in v0.19.0:

* stringified ``"[]"`` / ``"{}"`` GT values must be empty, not required
  events (a model that correctly emits nothing is not penalized);
* fields marked ``not_applicable`` / ``schema_documented_absence`` /
  ``pending_annotation`` must never reach extraction scoring — only the
  class's own schema fields (plus the content differentiators its suite
  carries) are scored.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.field_scoring import ExtractionScoreResult
from llm_dojo_scoring.gt_metadata import (
    ABSENT_PRESENCE_STATUSES,
    ANNOTATION_KEYS,
    CUAD_PRESENCE_KEY,
    GT_PRESENCE_KEY,
    derive_presence_from_gt,
    gt_presence_map,
    is_empty_value,
    normalize_field_values,
    parse_gt_fields,
    parse_json_container,
    presence_expectations_from_cuad_labels,
    scoring_gt_fields,
)

# ---------------------------------------------------------------------------
# Fixtures — structurally exact abridgements of real rows
# ---------------------------------------------------------------------------

_CORPORATE_GT = {
    "adjuster": "",
    "claim_number": "",
    "claim_type": "",
    "claimed_amount": "",
    "clause_count": "",
    "content_topic": "",
    "context_window_band": "<=32k",
    "coverage_determination": "",
    "cuad_clause_labels": "{}",
    "damages_description": "",
    "date_filed": "",
    "date_of_loss": "",
    "denial_reasons": "[]",
    "gt_presence": json.dumps(
        {
            "adjuster": "not_applicable",
            "claim_number": "not_applicable",
            "claim_type": "not_applicable",
            "claimed_amount": "not_applicable",
            "content_topic": "not_applicable",
            "coverage_determination": "not_applicable",
            "cuad_clause_labels": "not_applicable",
            "damages_description": "not_applicable",
            "date_filed": "not_applicable",
            "date_of_loss": "not_applicable",
            "denial_reasons": "not_applicable",
            "insured_party": "not_applicable",
            "insurer": "not_applicable",
            "intent": "populated",
            "keywords": "populated",
            "maud_clause_labels": "not_applicable",
            "policy_number": "not_applicable",
            "sentiment_label": "not_applicable",
            "subject_matter": "populated",
            "supporting_documents": "not_applicable",
        }
    ),
    "insured_party": "",
    "insurer": "",
    "intent": "entity_formation",
    "intent_confidence": "0.9",
    "intent_source": "heuristic",
    "intent_status": "auto_labeled",
    "keywords": (
        '["articles_of_incorporation", "NMI Holdings, Inc.  (NMIH)  '
        '(CIK 0001547903)", "EX-4.2"]'
    ),
    "label_evidence": "",
    "maud_clause_labels": "{}",
    "maud_label_count": "",
    "policy_number": "",
    "related_document_ids": "[]",
    "relationships": "[]",
    "sentiment_evidence": "",
    "sentiment_label": "",
    "sentiment_score": "",
    "subject_matter": (
        "articles_of_incorporation of NMI Holdings, Inc.  (NMIH)  "
        "(CIK 0001547903) (SEC EDGAR exhibit: EXHIBIT 4.2)."
    ),
    "supporting_documents": "[]",
    "token_estimate": "22744",
    "topic_evidence": "",
}

_CORPORATE_PRED = {
    "intent": "entity_formation",
    "keywords": [
        "articles_of_incorporation",
        "NMI Holdings, Inc.  (NMIH)  (CIK 0001547903)",
        "EX-4.2",
    ],
    "subject_matter": _CORPORATE_GT["subject_matter"],
}

_INSURANCE_GT = {
    "adjuster": "",
    "claim_number": "887093388938040",
    "claim_type": "health",
    "claimed_amount": "40.0",
    "clause_count": "",
    "content_topic": "",
    "context_window_band": "<=4k",
    "coverage_determination": "approved",
    "cuad_clause_labels": "{}",
    "damages_description": (
        "Physician/supplier professional services 2008-04-29 to 2008-04-29; "
        "diagnoses (ICD-9): 4910; 1 billed service lines."
    ),
    "date_filed": "2008-04-29",
    "date_of_loss": "2008-04-29",
    "denial_reasons": "[]",
    "gt_presence": json.dumps(
        {
            "adjuster": "schema_documented_absence",
            "claim_number": "populated",
            "claim_type": "populated",
            "claimed_amount": "populated",
            "content_topic": "not_applicable",
            "coverage_determination": "populated",
            "cuad_clause_labels": "not_applicable",
            "damages_description": "populated",
            "date_filed": "populated",
            "date_of_loss": "populated",
            "denial_reasons": "schema_documented_absence",
            "insured_party": "populated",
            "insurer": "populated",
            "intent": "populated",
            "keywords": "populated",
            "maud_clause_labels": "not_applicable",
            "policy_number": "populated",
            "sentiment_label": "not_applicable",
            "subject_matter": "populated",
            "supporting_documents": "populated",
        }
    ),
    "insured_party": "WILSON, DAVID",
    "insurer": "CMS Medicare",
    "intent": "claim_data_record",
    "intent_confidence": "1.0",
    "intent_source": "manual",
    "intent_status": "manual",
    "keywords": (
        '["Medicare Summary Notice", "PHYSICIAN/SUPPLIER CLAIM", "approved", '
        '"WILSON, DAVID", "$50.00 paid", "HCPCS 99214", "2008-04-29"]'
    ),
    "label_evidence": "",
    "maud_clause_labels": "{}",
    "maud_label_count": "",
    "policy_number": "E5633BC61725000F",
    "related_document_ids": "[]",
    "relationships": "[]",
    "sentiment_evidence": "",
    "sentiment_label": "",
    "sentiment_score": "",
    "subject_matter": (
        "Medicare Summary Notice for WILSON, DAVID showing approved claim for "
        "service on 2008-04-29 with payment of $50.00."
    ),
    "supporting_documents": '["provider NPI 6915056717", "HCPCS detail (1 codes)"]',
    "token_estimate": "274",
    "topic_evidence": "",
}

_INSURANCE_PRED = {
    "claim_number": "887093388938040",
    "claim_type": "health",
    "claimed_amount": "40.0",
    "coverage_determination": "approved",
    "damages_description": _INSURANCE_GT["damages_description"],
    "date_filed": "2008-04-29",
    "date_of_loss": "2008-04-29",
    "insured_party": "WILSON, DAVID",
    "insurer": "CMS Medicare",
    "intent": "claim_data_record",
    "keywords": [
        "Medicare Summary Notice",
        "PHYSICIAN/SUPPLIER CLAIM",
        "approved",
        "WILSON, DAVID",
        "$50.00 paid",
        "HCPCS 99214",
        "2008-04-29",
    ],
    "policy_number": "E5633BC61725000F",
    "subject_matter": _INSURANCE_GT["subject_matter"],
    "supporting_documents": ["provider NPI 6915056717", "HCPCS detail (1 codes)"],
}

_CORRESPONDENCE_GT = {
    "content_topic": "general_business",
    "cuad_clause_labels": "{}",
    "denial_reasons": "[]",
    "gt_presence": json.dumps(
        {
            "content_topic": "populated",
            "cuad_clause_labels": "not_applicable",
            "denial_reasons": "not_applicable",
            "intent": "populated",
            "keywords": "populated",
            "sentiment_label": "populated",
            "subject_matter": "populated",
        }
    ),
    "intent": "request",
    "intent_confidence": "0.95",
    "intent_source": "aeslc_join",
    "intent_status": "auto_labeled",
    "keywords": (
        '["general_business", "demand", "bailey-s", "deleted_items", '
        '"2002-03-06T15:35:16+00:00"]'
    ),
    "label_evidence": "demand markers",
    "maud_clause_labels": "{}",
    "related_document_ids": "[]",
    "relationships": "[]",
    "sentiment_evidence": "1 lexicon hit(s), net +0.2 [thanks]",
    "sentiment_label": "neutral",
    "sentiment_score": "0.0476",
    "subject_matter": "Correspondence concerning general_business.",
    "supporting_documents": "[]",
    "token_estimate": "55",
    "topic_evidence": "no specific topic markers; ordinary business content",
}

_CORRESPONDENCE_PRED = {
    "content_topic": "general_business",
    "intent": "request",
    "keywords": [
        "general_business",
        "demand",
        "bailey-s",
        "deleted_items",
        "2002-03-06T15:35:16+00:00",
    ],
    "sentiment_label": "neutral",
    "subject_matter": "Correspondence concerning general_business.",
}

_CONTRACT_PRESENCE_GT = {
    "clause_count": "3",
    "context_window_band": "<=32k",
    "cuad_clause_labels": json.dumps(
        {
            "Governing Law": [
                {
                    "start": 10,
                    "text": (
                        "This Agreement shall be governed by the laws of the "
                        "State of Delaware."
                    ),
                }
            ],
            "Anti-Assignment": [
                {
                    "start": 200,
                    "text": (
                        "Neither party may assign this Agreement without the "
                        "prior written consent of the other party, and any "
                        "purported assignment in violation of this section "
                        "shall be void."
                    ),
                }
            ],
            "Notice Period To Terminate Renewal": [],
        }
    ),
    "gt_presence": json.dumps(
        {
            "clause_count": "not_applicable",
            "context_window_band": "not_applicable",
            "cuad_clause_labels": "populated",
            "maud_clause_labels": "not_applicable",
        }
    ),
    "maud_clause_labels": "{}",
    "related_document_ids": "[]",
    "relationships": "[]",
    "token_estimate": "8193",
}

_CONTRACT_PRESENCE_PRED = {
    "cuad_clauses": [
        (
            "Anti-Assignment: Neither party may assign this Agreement without "
            "the prior written consent of the other party, and any purported "
            "assignment in violation of this section shall be void."
        ),
        (
            "Governing Law: This Agreement shall be governed by the laws of "
            "the State of Delaware."
        ),
    ]
}

_CONTRACT_EMPTY_GT = {
    "cuad_clause_labels": "{}",
    "gt_presence": json.dumps(
        {
            "cuad_clause_labels": "not_applicable",
            "maud_clause_labels": "schema_documented_absence",
        }
    ),
    "maud_clause_labels": "{}",
    "token_estimate": "8193",
}

# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


def test_parse_json_container_round_trips_containers():
    assert parse_json_container("[]") == []
    assert parse_json_container("{}") == {}
    assert parse_json_container('["Bylaws", "stockholders"]') == ["Bylaws", "stockholders"]
    assert parse_json_container('{"Governing Law": []}') == {"Governing Law": []}


def test_parse_json_container_leaves_scalars_and_prose():
    assert parse_json_container("41") == "41"
    assert parse_json_container("Bylaws of Revenue.com") == "Bylaws of Revenue.com"
    assert parse_json_container(None) is None
    assert parse_json_container(["already", "a", "list"]) == ["already", "a", "list"]


def test_is_empty_value_treats_stringified_containers_and_null_tokens():
    for empty in (None, "", "   ", "[]", "{}", "null", "none", "N/A", "n/a", "n.a.", [], {}):
        assert is_empty_value(empty), empty
    for value in (0, 0.0, False, "0", "41", "not_applicable", ["x"], {"k": "v"}):
        assert not is_empty_value(value), value


def test_parse_gt_fields_accepts_json_and_python_repr():
    from_json = parse_gt_fields('{"intent": "request", "keywords": "[]"}')
    assert from_json == {"intent": "request", "keywords": []}
    from_repr = parse_gt_fields("{'intent': 'request', 'keywords': '[]'}")
    assert from_repr == {"intent": "request", "keywords": []}
    assert parse_gt_fields({GT_PRESENCE_KEY: "{}", "intent": "request"})[
        GT_PRESENCE_KEY
    ] == {}


def test_parse_gt_fields_rejects_garbage():
    with pytest.raises(ValueError):
        parse_gt_fields("not a metadata string")
    with pytest.raises(TypeError):
        parse_gt_fields(42)


# ---------------------------------------------------------------------------
# Scoping / alignment
# ---------------------------------------------------------------------------


def test_scoring_gt_fields_keeps_only_class_surface_and_drops_annotation():
    suite = get_suite("corporate_records_specialist")
    scoped = scoring_gt_fields(
        _CORPORATE_GT, field_types=suite.field_types, drop_unmapped=True
    )
    assert set(scoped) == {"intent", "keywords", "subject_matter"}
    assert not set(scoped) & ANNOTATION_KEYS
    assert scoped["keywords"] == _CORPORATE_PRED["keywords"]


def test_scoring_gt_fields_blanks_documented_absence():
    suite = get_suite("insurance_claims_specialist")
    scoped = scoring_gt_fields(
        _INSURANCE_GT, field_types=suite.field_types, drop_unmapped=True
    )
    assert scoped["denial_reasons"] == ""
    assert scoped["adjuster"] == ""
    assert scoped["claim_number"] == "887093388938040"


@pytest.mark.parametrize(
    "suite_name",
    [
        "contracts_specialist",
        "merger_agreement_specialist",
        "corporate_records_specialist",
        "correspondence_specialist",
        "insurance_claims_specialist",
    ],
)
def test_every_live_class_keeps_its_own_schema_fields(suite_name):
    """Each document type's GT label set aligns with its extraction schema."""
    suite = get_suite(suite_name)
    gt = {key: f"v-{key}" for key in suite.field_types}
    gt[GT_PRESENCE_KEY] = json.dumps(
        {key: "populated" for key in suite.field_types}
    )
    scoped = scoring_gt_fields(gt, field_types=suite.field_types, drop_unmapped=True)
    assert set(scoped) == set(suite.field_types)


def test_hub_row_never_scores_another_class_fields():
    suite = get_suite("corporate_records_specialist")
    gt = dict(_CORPORATE_GT)
    gt["sender"] = "Pat"          # correspondence schema
    gt["recipient"] = "Alex"      # correspondence schema
    gt["claim_number"] = "CLM-1"  # insurance schema
    scoped = scoring_gt_fields(gt, field_types=suite.field_types, drop_unmapped=True)
    assert "sender" not in scoped
    assert "recipient" not in scoped
    assert "claim_number" not in scoped


def test_presence_expectations_from_cuad_labels():
    labels = parse_gt_fields(_CONTRACT_PRESENCE_GT)[CUAD_PRESENCE_KEY]
    expectations = presence_expectations_from_cuad_labels(labels)
    assert expectations["Governing Law"]["expected"] is True
    assert expectations["Governing Law"]["answer"].startswith("This Agreement")
    assert expectations["Notice Period To Terminate Renewal"]["expected"] is False
    assert derive_presence_from_gt(parse_gt_fields(_CONTRACT_EMPTY_GT)) is None


def test_presence_expectations_skip_placeholder_spans():
    labels = {
        "Parties": [{"start": 1, "text": "____________________"}],
        "Anti-Assignment": [{"start": 2, "text": "."}],
        "Agreement Date": [
            {"start": 3, "text": "[*]"},
            {"start": 4, "text": "31st day of March, 2000"},
        ],
        "Governing Law": [],
    }
    expectations = presence_expectations_from_cuad_labels(labels)
    assert "Parties" not in expectations
    assert "Anti-Assignment" not in expectations
    assert expectations["Agreement Date"]["answer"] == "31st day of March, 2000"
    assert expectations["Governing Law"]["expected"] is False


def test_na_date_values_are_not_required_events():
    """Train-split rows carry date_filed / date_of_loss = 'N/A'."""
    suite = get_suite("insurance_claims_specialist")
    gt = {
        "claim_number": "CLM-1",
        "date_filed": "N/A",
        "date_of_loss": "n/a",
        "gt_presence": json.dumps(
            {
                "claim_number": "populated",
                "date_filed": "populated",
                "date_of_loss": "populated",
            }
        ),
    }
    scoped = scoring_gt_fields(gt, field_types=suite.field_types, drop_unmapped=True)
    pred = {"claim_number": "CLM-1", "date_filed": "N/A", "date_of_loss": "n/a"}
    metrics = extraction_binary_metrics(scoped, pred, field_map=suite.field_types)
    assert metrics["expected_events"] == 1
    assert metrics["fn"] == 0
    assert metrics["fp"] == 0
    assert metrics["n_spurious_fill"] == 0
    assert metrics["extraction_f1"] == 1.0


# ---------------------------------------------------------------------------
# End-to-end: a perfect prediction is not penalized
# ---------------------------------------------------------------------------


def test_corporate_hub_row_perfect_prediction_has_no_penalty():
    suite = get_suite("corporate_records_specialist")
    out = suite.score_document(json.dumps(_CORPORATE_GT), _CORPORATE_PRED)
    assert out.get("status") != "unscorable"
    assert out["extraction"].field_scores == {
        "intent": 1.0,
        "keywords": 1.0,
        "subject_matter": 1.0,
    }
    assert out["extraction"].overall_score == 1.0
    assert out["extraction_f1"] == 1.0
    assert out["extraction_precision"] == 1.0
    assert out["extraction_recall"] == 1.0


def test_insurance_hub_row_perfect_prediction_has_no_penalty():
    suite = get_suite("insurance_claims_specialist")
    out = suite.score_document(json.dumps(_INSURANCE_GT), _INSURANCE_PRED)
    assert out.get("status") != "unscorable"
    assert out["extraction"].overall_score == 1.0
    assert out["extraction_f1"] == 1.0
    # Documented-absence fields are not scored, and the stringified "[]"
    # denial_reasons is empty — never an FN for a model that omits it.
    assert "denial_reasons" not in out["extraction"].field_scores
    assert "adjuster" not in out["extraction"].field_scores
    assert out["extraction"].field_scores == {
        key: 1.0
        for key in (
            "claim_number",
            "claim_type",
            "claimed_amount",
            "coverage_determination",
            "damages_description",
            "date_filed",
            "date_of_loss",
            "insured_party",
            "insurer",
            "intent",
            "keywords",
            "policy_number",
            "subject_matter",
            "supporting_documents",
        )
    }


def test_correspondence_hub_row_scores_content_without_penalty():
    suite = get_suite("correspondence_specialist")
    out = suite.score_document(json.dumps(_CORRESPONDENCE_GT), _CORRESPONDENCE_PRED)
    assert out.get("status") != "unscorable"
    assert set(out["extraction"].field_scores) == {"intent", "keywords", "subject_matter"}
    assert out["extraction"].overall_score == 1.0
    assert out["content_topic_accuracy"] == 1.0
    assert out["sentiment_accuracy"] == 1.0
    assert out["extraction_f1"] == 1.0


def test_insurance_spurious_absence_fill_is_still_an_fp():
    """Filling a documented-absence field is a spurious fill, not ignored."""
    suite = get_suite("insurance_claims_specialist")
    scoped = scoring_gt_fields(
        _INSURANCE_GT, field_types=suite.field_types, drop_unmapped=True
    )
    pred = dict(_INSURANCE_PRED)
    pred["denial_reasons"] = ["Claim denied because the policy lapsed."]
    metrics = extraction_binary_metrics(scoped, pred, field_map=suite.field_types)
    assert metrics["n_spurious_fill"] >= 1
    assert metrics["fp"] >= 1
    assert metrics["fn"] == 0


def test_contract_presence_only_row_uses_presence_not_zero_f1():
    suite = get_suite("contracts_specialist")
    out = suite.score_document(json.dumps(_CONTRACT_PRESENCE_GT), _CONTRACT_PRESENCE_PRED)
    assert out.get("status") != "unscorable"
    assert out["extraction_category_presence"] == 1.0
    # No extraction events -> P/R/F1/F2 stay null, never a misleading 0.0.
    assert out["extraction_f1"] is None
    assert out["extraction_f2"] is None
    assert out["extraction"].overall_score is None


def test_contract_zero_populated_row_is_unscorable():
    suite = get_suite("contracts_specialist")
    out = suite.score_document(json.dumps(_CONTRACT_EMPTY_GT), {"cuad_clauses": []})
    assert out["status"] == "unscorable"
    assert out["reason"] == "gt_no_extractable_fields"
    assert out["overall_score"] is None


def test_pending_annotation_stale_labels_are_never_scored():
    """Backfill-not-run status: a stale non-empty label is not a GT event.

    The current corpus has 91 contract rows with ``cuad_clause_labels`` in
    ``pending_annotation``; a row whose only label is pending must stay
    unscorable even if a stale placeholder value is still attached.
    """
    assert "pending_annotation" in ABSENT_PRESENCE_STATUSES
    suite = get_suite("contracts_specialist")
    gt = {
        "cuad_clause_labels": json.dumps(
            {"Governing Law": [{"start": 1, "text": "stale placeholder text"}]}
        ),
        "gt_presence": json.dumps(
            {
                "cuad_clause_labels": "pending_annotation",
                "governing_law": "pending_annotation",
                "maud_clause_labels": "not_applicable",
            }
        ),
        "governing_law": "stale governing law value",
        "maud_clause_labels": "{}",
    }
    scoped = scoring_gt_fields(gt, field_types=suite.field_types, drop_unmapped=True)
    # Annotation/presence inputs never survive scoping; pending schema fields
    # are blanked even when a stale value is attached.
    assert "cuad_clause_labels" not in scoped
    assert scoped["governing_law"] == ""
    assert derive_presence_from_gt(parse_gt_fields(gt)) is None
    out = suite.score_document(gt, {"cuad_clauses": []})
    assert out["status"] == "unscorable"
    assert out["reason"] == "gt_no_extractable_fields"
    assert out["overall_score"] is None


def test_mispassed_label_string_fails_closed_without_crashing():
    """The dataset's ``expected`` column is a class label, not fields."""
    suite = get_suite("contracts_specialist")
    out = suite.score_document("contract", {"document_name": "X"})
    assert out["status"] == "unscorable"
    assert out["reason"] == "gt_wrong_schema"
    assert out["overall_score"] is None


@pytest.mark.parametrize("raw", ['["field"]', '"contract"', "null", "true", "42"])
def test_parse_gt_fields_rejects_valid_json_with_wrong_shape(raw):
    with pytest.raises(ValueError, match="must decode to a mapping"):
        parse_gt_fields(raw)


@pytest.mark.parametrize("raw", [None, [], 0, False])
def test_parse_gt_fields_rejects_non_mapping_inputs(raw):
    with pytest.raises(TypeError, match="must be a mapping or string"):
        parse_gt_fields(raw)


@pytest.mark.parametrize("raw", ["[broken]", "{broken}", "[1,]", "{'key': 'value'}", '"quoted"', "true"])
def test_container_parser_preserves_malformed_containers_and_json_scalars(raw):
    assert parse_json_container(raw) == raw


def test_normalize_field_values_preserves_scalars_and_does_not_mutate_input():
    record = {1: ' ["Alice", "Bob"] ', "amount": "0", "enabled": False}
    original = deepcopy(record)
    assert normalize_field_values(record) == {
        "1": ["Alice", "Bob"], "amount": "0", "enabled": False,
    }
    assert record == original


@pytest.mark.parametrize("raw", [None, "not json", "[]", "null", [], 42])
def test_invalid_presence_map_is_ignored(raw):
    assert gt_presence_map({GT_PRESENCE_KEY: raw}) == {}


@pytest.mark.parametrize("status", sorted(ABSENT_PRESENCE_STATUSES))
@pytest.mark.parametrize("stringified", [False, True])
def test_absent_status_suppresses_stale_fields_and_presence_without_mutation(status, stringified):
    presence = {"governing_law": status, CUAD_PRESENCE_KEY: status}
    fields = {
        "governing_law": "Delaware",
        CUAD_PRESENCE_KEY: {"Governing Law": [{"text": "Delaware law applies."}]},
        GT_PRESENCE_KEY: json.dumps(presence) if stringified else presence,
    }
    original = deepcopy(fields)
    assert scoring_gt_fields(fields, field_types={"governing_law": "name"}) == {
        "governing_law": "",
    }
    assert derive_presence_from_gt(fields) is None
    assert fields == original


def test_scoping_retains_declared_content_extras_but_never_annotation_fields():
    fields = {
        "sender": "Alice", "content_topic": "legal_contracts",
        "claim_number": "CLM-1", "token_estimate": 200,
    }
    assert scoring_gt_fields(
        fields, field_types={"sender": "name", "token_estimate": "id"},
        extra_keys=("content_topic", "token_estimate"),
    ) == {"sender": "Alice", "content_topic": "legal_contracts"}
    assert scoring_gt_fields(fields, field_types={"sender": "name"}, drop_unmapped=False) == {
        "sender": "Alice", "content_topic": "legal_contracts", "claim_number": "CLM-1",
    }


def test_presence_uses_first_scorable_span_and_custom_field():
    labels = {
        "Governing Law": json.dumps([
            {"text": "[*]"}, {"start": 4}, "malformed span",
            {"text": "Delaware law applies."}, {"text": "Later answer."},
        ]),
        "Parties": [],
        "Term": [{"text": "____"}, {"text": "."}],
    }
    assert presence_expectations_from_cuad_labels(labels, field="clauses") == {
        "Governing Law": {"expected": True, "answer": "Delaware law applies.", "field": "clauses"},
        "Parties": {"expected": False, "answer": "", "field": "clauses"},
    }


def test_pending_labels_become_scorable_when_backfilled():
    suite = get_suite("contracts_specialist")
    fields = {
        "governing_law": "",
        CUAD_PRESENCE_KEY: {"Governing Law": [{"text": "Delaware law applies."}]},
        GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: "pending_annotation"},
    }
    prediction = {"cuad_clauses": ["Delaware law applies."]}
    assert suite.score_document(fields, prediction)["status"] == "unscorable"
    fields[GT_PRESENCE_KEY][CUAD_PRESENCE_KEY] = "populated"
    result = suite.score_document(fields, prediction)
    assert result["extraction_category_presence"] == 1.0
    assert result["metric_id"] == "cuad.clause_presence.micro_f1"
    assert result["extraction_f1"] is None


def test_pending_annotation_only_document_is_unscorable():
    result = get_suite("contracts_specialist").score_document(
        {
            CUAD_PRESENCE_KEY: {"Governing Law": [{"text": "Delaware law applies."}]},
            GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: "pending_annotation"},
        },
        {"cuad_clauses": ["Delaware law applies."]},
    )
    assert result.get("status") == "unscorable"
    assert result["reason"] == "gt_no_extractable_fields"


def test_batch_presence_keeps_pending_and_populated_rows_aligned():
    label = {"Governing Law": [{"text": "Delaware law applies."}]}
    expected = [
        {CUAD_PRESENCE_KEY: label, GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: status}}
        for status in ("pending_annotation", "populated")
    ]
    result = get_suite("contracts_specialist").score(
        expected, [{"cuad_clauses": []}, {"cuad_clauses": ["Delaware law applies."]}],
    )
    assert result["extraction_category_presence"] == 1.0
    assert len(result["extraction"]) == 2
    assert result["extraction_f1"] is None
    assert result["extraction_f2"] is None


def test_batch_annotation_only_row_is_unscorable_and_aligned():
    label = {"Governing Law": [{"text": "Delaware law applies."}]}
    expected = [
        {
            CUAD_PRESENCE_KEY: label,
            GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: "pending_annotation"},
        },
        {
            CUAD_PRESENCE_KEY: label,
            GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: "populated"},
        },
    ]
    result = get_suite("contracts_specialist").score(
        expected, [{"cuad_clauses": []}, {"cuad_clauses": ["Delaware law applies."]}],
    )
    assert len(result["extraction"]) == 2
    # Pending annotation row: unscorable, not silently scored as gt_empty.
    assert result["extraction"][0]["status"] == "unscorable"
    assert result["extraction"][0]["reason"] == "gt_no_extractable_fields"
    # Populated row: presence-only row stays scored, alignment preserved.
    assert isinstance(result["extraction"][1], ExtractionScoreResult)


def test_batch_presence_only_row_does_not_leak_spurious_field_micro():
    label = {"Governing Law": [{"text": "Delaware law applies."}]}
    expected = [
        {"parties": ["Acme"]},
        {
            CUAD_PRESENCE_KEY: label,
            GT_PRESENCE_KEY: {CUAD_PRESENCE_KEY: "populated"},
        },
    ]
    predicted = [
        {"parties": ["Acme"]},
        {"cuad_clauses": ["Governing Law: Delaware law applies."]},
    ]
    result = get_suite("contracts_specialist").score(expected, predicted)
    # Presence-only row is scored by the presence metric...
    assert result["extraction_category_presence"] == 1.0
    # ...and its predicted clause spans are not field false positives.
    assert result["extraction_precision"] == 1.0
    assert result["extraction_f1"] == 1.0
