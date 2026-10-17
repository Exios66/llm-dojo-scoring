"""Deterministic corporate_record GT repair."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.corporate_record_relabel import company_from_template, relabel_row, relabel_rows
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


@pytest.mark.parametrize(
    "subject,company",
    [
        ("  bylaws of Acme\n  Holdings (ACME) /DE/ (CIK 123) (SEC EDGAR exhibit).", "Acme Holdings"),
        ("bylaws of Acme /DE/ (ACME) (CIK 123) (SEC EDGAR exhibit: EX-3.2).", "Acme"),
        ("bylaws of Acme (LLC) (CIK 123) (SEC EDGAR exhibit).", "Acme (LLC)"),
        ("bylaws of Acme (CIK 123).", None),
        ("Narrative mentioning bylaws of Acme (CIK 123) (SEC EDGAR exhibit).", None),
        ("", None),
    ],
)
def test_company_template_boundaries(subject, company):
    assert company_from_template(subject) == company


@pytest.mark.parametrize("encoding", ["mapping", "json", "python_literal"])
def test_relabel_accepts_gt_encodings_without_mutating_nested_metadata(encoding):
    gt = {
        "intent": "governance_rules", "intent_source": "human_adjudicated",
        "keywords": ["governance", "EX-3.2", "8-K", "0000000001-26-000001", "Acme (CIK 123)"],
        "gt_presence": {"claim_number": "not_applicable"},
        "label_evidence": {"source": "manual"},
    }
    raw = gt if encoding == "mapping" else json.dumps(gt) if encoding == "json" else repr(gt)
    row = dict(_TEMPLATE_ROW, gt_fields=raw, document_id="synthetic-1")
    before = deepcopy(row)
    new, changes = relabel_row(row)
    result = json.loads(new["gt_fields"])
    assert row == before
    assert new["document_id"] == "synthetic-1"
    assert json.loads(result["keywords"]) == ["governance"]
    assert json.loads(result["label_evidence"]) == {"source": "manual"}
    assert json.loads(result["gt_presence"])["claim_number"] == "not_applicable"
    assert "keywords" in changes
    twice, repeated_changes = relabel_row(new)
    assert twice == new and repeated_changes == []


@pytest.mark.parametrize("source", [None, "", "heuristic", "human_adjudicated"])
def test_conflict_repair_updates_schema_but_preserves_adjudicated_intent(source):
    gt = {
        "intent": "entity_formation", "record_type": "articles_of_incorporation",
        "subject_matter": "Bylaws of Acme, Inc., governing annual meetings.",
    }
    if source is not None:
        gt["intent_source"] = source
    new, changes = relabel_row(_row("articles_of_incorporation", gt))
    result = json.loads(new["gt_fields"])
    assert new["expected_subclass"] == "bylaws"
    assert result["record_type"] == "bylaws"
    assert json.loads(result["gt_presence"])["filing_number"] == "not_applicable"
    if source == "human_adjudicated":
        assert result["intent"] == "entity_formation"
        assert not any(change.startswith("intent:") for change in changes)
    else:
        assert result["intent"] == "governance_rules"
        assert "intent:entity_formation->governance_rules" in changes
    assert result.get("intent_source") == source


@pytest.mark.parametrize(
    "subclass,subject",
    [
        ("articles_of_incorporation", "Organizational minutes approving the bylaws of Acme."),
        ("bylaws", "Bylaws of Acme attached to a secretary's certificate."),
    ],
)
def test_relabel_leaves_ambiguous_or_own_subclass_prose_for_review(subclass, subject):
    new, changes = relabel_row(_row(subclass, {"subject_matter": subject}))
    assert new["expected_subclass"] == subclass
    assert json.loads(new["gt_fields"])["subject_matter"] == subject
    assert not any(change.startswith("expected_subclass:") for change in changes)


@pytest.mark.parametrize("record_type", [None, "", "indenture", "not_a_record"])
def test_relabel_fills_invalid_record_type_without_inventing_entities(record_type):
    new, changes = relabel_row(_row("subsidiary_list", {"record_type": record_type}))
    gt = json.loads(new["gt_fields"])
    assert gt["record_type"] == "other"
    assert "record_type" in changes
    assert json.loads(gt["gt_presence"]) == {
        "record_type": "populated", "signatories": "not_applicable",
        "jurisdiction": "not_applicable", "filing_number": "not_applicable",
    }
    assert not {"entity_name", "effective_date", "subsidiaries", "subsidiary_jurisdictions"} & gt.keys()


def test_relabel_preserves_stated_inapplicable_values_and_populated_status():
    gt = {
        "signatories": ["Jane Doe"], "jurisdiction": "Delaware", "filing_number": "",
        "gt_presence": {"filing_number": "populated"},
    }
    new, _ = relabel_row(_row("subsidiary_list", gt))
    result = json.loads(new["gt_fields"])
    assert json.loads(result["signatories"]) == ["Jane Doe"]
    assert result["jurisdiction"] == "Delaware"
    assert result["filing_number"] == ""
    assert json.loads(result["gt_presence"]) == {"filing_number": "populated", "record_type": "populated"}


def test_keyword_repair_removes_only_provenance_and_keeps_business_terms():
    keywords = ["EX-3.1(A)", "10-Q/A", "S-1", "stock", "EX-3.1 provisions", "Series S-1 preferred"]
    new, _ = relabel_row(_row("rights_instrument", {"keywords": keywords}))
    assert json.loads(json.loads(new["gt_fields"])["keywords"]) == [
        "stock", "EX-3.1 provisions", "Series S-1 preferred",
    ]


@pytest.mark.parametrize("bad_gt", ["{bad", "[]", "null", "42", ["not a mapping"], 42])
def test_batch_relabel_continues_after_each_invalid_gt_shape(bad_gt):
    bad = dict(_TEMPLATE_ROW, gt_fields=bad_gt)
    skipped = {"expected": "contract", "gt_fields": "{bad"}
    before = deepcopy((bad, skipped, _TEMPLATE_ROW))
    results = list(relabel_rows(iter([bad, skipped, _TEMPLATE_ROW])))
    assert results[0] == (bad, ["gt_unparseable"])
    assert results[1] == (skipped, [])
    assert json.loads(results[2][0]["gt_fields"])["entity_name"] == "DentonX Inc"
    assert (bad, skipped, _TEMPLATE_ROW) == before
