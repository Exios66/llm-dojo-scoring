"""Per-value audit records for unlabelled values."""

from __future__ import annotations

import hashlib
import json

import pytest
from grounding_inputs import DOC_TEXT

from llm_dojo_scoring.grounding.audit import UnlabelledValueAudit, audit_unlabelled_values


def test_stringified_list_audited_item_by_item():
    """Stringified list audited item by item."""
    records = audit_unlabelled_values(
        {}, {"keywords": '["Acme Holdings", "Globex"]'},
        doc_class="insurance_claim", doc_text=DOC_TEXT,
    )
    assert [(r.field, r.item_index, r.value, r.verdict) for r in records] == [
        ("keywords", 0, "Acme Holdings", "grounded"),
        ("keywords", 1, "Globex", "not_found"),
    ]
    assert {r.field_type for r in records} == {"name"}


def test_scalar_record_carries_status_type_and_verdict():
    """Scalar record carries status type and verdict."""
    (record,) = audit_unlabelled_values(
        {}, {"claimed_amount": "$1,250.00"}, doc_class="insurance_claim", doc_text=DOC_TEXT,
        doc_id="d1", run_id="r1", extractor="insurance_claims_specialist",
    )
    assert (record.field, record.field_type, record.item_index) == ("claimed_amount", "money", None)
    assert (record.verdict, record.gt_status) == ("grounded", "absent")
    assert (record.doc_id, record.run_id, record.extractor) == ("d1", "r1", "insurance_claims_specialist")


def test_records_follow_registry_field_order():
    """Records follow registry field order."""
    predicted = {"claimed_amount": "$1,250.00", "claim_number": "AB-12/34", "insurer": "Acme"}
    records = audit_unlabelled_values({}, predicted, doc_class="insurance_claim", doc_text=DOC_TEXT)
    assert [r.field for r in records] == ["claim_number", "insurer", "claimed_amount"]


def test_record_carries_hash_not_text():
    """Record carries hash not text."""
    (record,) = audit_unlabelled_values({}, {"insurer": "Acme"}, doc_class="insurance_claim",
                                        doc_text=DOC_TEXT)
    assert record.doc_text_sha256 == hashlib.sha256(DOC_TEXT.encode("utf-8")).hexdigest()
    assert DOC_TEXT not in json.dumps(record.as_dict())


def test_missing_text_gives_unverifiable_and_no_hash():
    """Missing text gives unverifiable and no hash."""
    (record,) = audit_unlabelled_values({}, {"insurer": "Acme"}, doc_class="insurance_claim",
                                        doc_text=None)
    assert (record.verdict, record.doc_text_sha256) == ("unverifiable", None)


def test_record_round_trips_through_dict():
    """Record round trips through dict."""
    (record,) = audit_unlabelled_values({}, {"insurer": "Acme"}, doc_class="insurance_claim",
                                        doc_text=DOC_TEXT)
    data = record.as_dict()
    assert data["schema_version"] == 1
    assert UnlabelledValueAudit.from_dict(json.loads(json.dumps(data))) == record


def test_labelled_fields_produce_no_records():
    """Labelled fields produce no records."""
    assert audit_unlabelled_values({"insurer": "Acme"}, {"insurer": "Acme"},
                                   doc_class="insurance_claim", doc_text=DOC_TEXT) == []


@pytest.mark.parametrize("doc_class", ["contract", "correspondence", "merger_agreement"])
def test_every_live_class_audits_without_error(doc_class):
    """Every live class audits without error."""
    assert isinstance(audit_unlabelled_values({}, {"intent": "x"}, doc_class=doc_class,
                                              doc_text=DOC_TEXT), list)


def test_mapping_and_list_items_are_checked_by_their_values():
    """Keys of a structured list item are not document text."""
    records = audit_unlabelled_values(
        {}, {"keywords": ["Acme Holdings", {"name": "Acme Holdings"}, ["Globex"]]},
        doc_class="insurance_claim", doc_text=DOC_TEXT,
    )
    assert [(r.value, r.verdict) for r in records] == [
        ("Acme Holdings", "grounded"), ("Acme Holdings", "grounded"), ("Globex", "not_found"),
    ]


def test_cms_row_supporting_documents_use_the_cms_doc_ref_rule():
    """On a CMS row the headline's CMS field types apply, so items are cms_doc_ref, not names."""
    text = "Carrier claim. Supporting: provider NPI 5040521237 and NDC 00703051002."
    predicted = {"supporting_documents": ["NPI 5040521237", "NPI 504052"]}
    cms = audit_unlabelled_values({"cms_source_table": "carrier", "claim_number": "1"}, predicted,
                                  doc_class="insurance_claim", doc_text=text)
    assert [(r.field_type, r.verdict) for r in cms] == [("cms_doc_ref", "grounded"), ("cms_doc_ref", "not_found")]
    plain = audit_unlabelled_values({"claim_number": "1"}, predicted, doc_class="insurance_claim", doc_text=text)
    assert {r.field_type for r in plain} == {"name"}
