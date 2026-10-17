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


def _row(sub, gt):
    return {"expected": "corporate_record", "expected_subclass": sub, "gt_fields": json.dumps(gt)}


def test_relabel_is_idempotent():
    once, _ = relabel_row(_TEMPLATE_ROW)
    twice, changes = relabel_row(once)
    assert twice == once
    assert "keywords" not in changes and "record_type" not in changes


def test_company_from_template_ticker_lists_and_codes():
    tpl = "bylaws of {} (CIK 0000000001) (SEC EDGAR exhibit: EXHIBIT 4.2). X"
    assert company_from_template(tpl.format("PureCycle Technologies, Inc. (PCT, PCTTU, PCTTW)")) == "PureCycle Technologies, Inc."
    assert company_from_template(tpl.format("SOURCE ENERGY CORP /UT/")) == "SOURCE ENERGY CORP"
    assert company_from_template(tpl.format("Foo Holdings (UK)")) == "Foo Holdings (UK)"


def test_no_double_period_and_paren_exhibit_keywords():
    gt = {
        "intent": "entity_formation",
        "subject_matter": "articles_of_incorporation of ClubCorp Holdings, Inc. (CIK 0001) (SEC EDGAR exhibit). X",
        "keywords": json.dumps(["articles of incorporation", "EX-3.1(A)"]),
    }
    new, _ = relabel_row(_row("articles_of_incorporation", gt))
    out = json.loads(new["gt_fields"])
    assert out["subject_matter"] == "Articles of incorporation of ClubCorp Holdings, Inc."
    assert json.loads(out["keywords"]) == ["Articles of incorporation", "ClubCorp Holdings, Inc."]


def test_relabel_never_overwrites_stated_labels():
    gt = {
        "intent": "other",
        "intent_source": "human_adjudicated",
        "record_type": "rights_instrument",
        "filing_number": "123",
        "gt_presence": json.dumps({"filing_number": "populated"}),
        "keywords": json.dumps(["indenture", "x"]),
    }
    new, changes = relabel_row(_row("indenture", gt))
    out = json.loads(new["gt_fields"])
    assert out["intent"] == "other" and out["record_type"] == "rights_instrument"
    assert out["filing_number"] == "123"
    assert json.loads(out["gt_presence"])["filing_number"] == "populated"
    assert json.loads(out["keywords"]) == ["indenture", "x"]
    assert "record_type" not in changes


def test_relabel_rows_survives_malformed_gt():
    bad = {"expected": "corporate_record", "expected_subclass": "bylaws", "gt_fields": "{not json"}
    from llm_dojo_scoring.corporate_record_relabel import relabel_rows

    ((row, changes),) = list(relabel_rows([bad]))
    assert row == bad and changes == ["gt_unparseable"]


def test_relabel_rows_survives_non_mapping_gt_fields():
    """A list / int ``gt_fields`` raises ``TypeError`` inside :func:`relabel_row`;
    the batch must report ``gt_unparseable`` and keep going, not abort."""
    from llm_dojo_scoring.corporate_record_relabel import relabel_rows

    bad_list = {"expected": "corporate_record", "expected_subclass": "bylaws", "gt_fields": ["not", "a", "mapping"]}
    bad_int = {"expected": "corporate_record", "expected_subclass": "bylaws", "gt_fields": 42}
    good = dict(_TEMPLATE_ROW)
    out = list(relabel_rows([bad_list, good, bad_int]))
    assert len(out) == 3
    assert out[0][1] == ["gt_unparseable"] and out[0][0] == bad_list
    assert "entity_name" in out[1][1]  # the good row was repaired
    assert json.loads(out[1][0]["gt_fields"])["entity_name"] == "DentonX Inc"
    assert out[2][1] == ["gt_unparseable"] and out[2][0] == bad_int
