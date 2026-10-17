"""Deterministic corporate_record GT repair."""

from __future__ import annotations

import json

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.corporate_record_relabel import company_from_template, relabel_row
from llm_dojo_scoring.corporate_record_schema import audit_gt_row

_TEMPLATE_ROW = {
    "expected": "corporate_record",
    "expected_subclass": "bylaws",
    "gt_fields": json.dumps(
        {
            "intent": "governance_rules",
            "intent_source": "heuristic",
            "subject_matter": "bylaws of DentonX Inc  (DNTX)  (CIK 0002093375) (SEC EDGAR exhibit). AMENDED AND RESTATED BY-LAWS",
            "keywords": json.dumps(["bylaws", "EX-3.2", "S-1/A", "0002093375-26-000004", "DentonX Inc  (CIK 0002093375)"]),
            "gt_presence": json.dumps({"claim_number": "not_applicable"}),
        }
    ),
}


def test_company_from_template_strips_ticker_and_cik():
    assert company_from_template(
        "bylaws of DentonX Inc  (DNTX)  (CIK 0002093375) (SEC EDGAR exhibit). X"
    ) == "DentonX Inc"
    assert company_from_template("Bylaws of Revenue.com Corporation, a Nevada corporation") is None


def test_relabel_repairs_template_row_without_mutating_input():
    before = json.dumps(_TEMPLATE_ROW, sort_keys=True)
    new, changes = relabel_row(_TEMPLATE_ROW)
    assert json.dumps(_TEMPLATE_ROW, sort_keys=True) == before
    gt = json.loads(new["gt_fields"])
    presence = json.loads(gt["gt_presence"])
    assert gt["entity_name"] == "DentonX Inc"
    assert gt["subject_matter"] == "Bylaws of DentonX Inc."
    assert json.loads(gt["keywords"]) == ["Bylaws", "DentonX Inc"]
    assert gt["record_type"] == "bylaws"
    assert presence["entity_name"] == presence["record_type"] == "populated"
    assert presence["filing_number"] == "not_applicable"
    assert presence["claim_number"] == "not_applicable"
    assert {"entity_name", "subject_matter", "keywords", "record_type"} <= set(changes)
    defects = audit_gt_row("bylaws", gt)
    assert "subject_matter_template" not in defects
    assert "keywords_provenance_ids" not in defects
    assert "entity_unlabeled:entity_name" not in defects
    assert "entity_unlabeled:record_type" not in defects
    assert "entity_unlabeled:jurisdiction" in defects  # still honestly unlabeled


def test_relabel_reassigns_conflicting_subclass_and_intent():
    row = {
        "expected": "corporate_record",
        "expected_subclass": "articles_of_incorporation",
        "gt_fields": json.dumps({"intent": "entity_formation", "subject_matter": "Bylaws of Acme, Inc., governing meetings."}),
    }
    new, changes = relabel_row(row)
    assert new["expected_subclass"] == "bylaws"
    assert json.loads(new["gt_fields"])["intent"] == "governance_rules"
    assert "expected_subclass:articles_of_incorporation->bylaws" in changes


def test_non_corporate_rows_pass_through():
    row = {"expected": "contract", "expected_subclass": "license", "gt_fields": "{}"}
    assert relabel_row(row) == (row, [])


def test_relabeled_row_scores_entities_end_to_end():
    new, _ = relabel_row(_TEMPLATE_ROW)
    pred = {
        "entity_name": "DentonX Inc",
        "record_type": "bylaws",
        "intent": "governance_rules",
        "subject_matter": "Bylaws of DentonX Inc.",
        "keywords": ["Bylaws", "DentonX Inc"],
        "jurisdiction": "Nevada",
    }
    out = get_suite("corporate_records_specialist").score_document(
        new["gt_fields"], pred, doc_subclass=new["expected_subclass"]
    )
    assert out["extraction"].field_scores["entity_name"] == 1.0
    assert out["extraction"].field_scores["record_type"] == 1.0
    assert out["extraction_precision"] == 1.0
    wrong = dict(pred, entity_name="Other Corp")
    bad = get_suite("corporate_records_specialist").score_document(
        new["gt_fields"], wrong, doc_subclass="bylaws"
    )
    assert bad["extraction"].field_scores["entity_name"] < 1.0
