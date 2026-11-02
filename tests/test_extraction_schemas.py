"""Five-class extraction schema registry: doc-type + subtype schemas (v9 lineage)."""

from __future__ import annotations

import json

import pytest

import llm_dojo_scoring as dojo
from llm_dojo_scoring.schemas.corpus import DOC_TYPE_SUBCLASSES
from llm_dojo_scoring.schemas.extraction_schemas import (
    FIELD_STATUSES,
    MAILROOM_DOC_TYPES,
    extraction_schema,
    extraction_status_source,
    extraction_subtypes,
    iter_extraction_schemas,
    registry_violations,
    schema_coverage,
)
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES, get_suite


def test_registry_has_no_drift():
    """Taxonomy, live field maps and the frozen status data agree."""
    assert registry_violations() == []


def test_five_classes_from_the_v9_lineage():
    """All five mailroom classes, frozen from a v9.x Hub revision."""
    assert MAILROOM_DOC_TYPES == tuple(dojo.LIVE_DOC_TYPES) == (
        "contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim",
    )
    source = extraction_status_source()
    assert source["dataset"] == "Lucius-Morningstar/mailroom-dataset"
    assert source["revision"].startswith("v9")
    assert source["rows"] == 3302


@pytest.mark.parametrize("doc_type", MAILROOM_DOC_TYPES)
def test_every_class_has_a_doc_type_schema_and_one_per_subtype(doc_type):
    """Each class and each catalogued subtype resolves to a schema over the full live map."""
    base = extraction_schema(doc_type)
    assert base.subtype is None and base.rows > 0
    assert set(DEFAULT_FIELD_TYPES[doc_type]) <= set(base.fields)
    assert set(DOC_TYPE_SUBCLASSES[doc_type]) <= set(extraction_subtypes(doc_type))
    for subtype in extraction_subtypes(doc_type):
        schema = extraction_schema(doc_type, subtype)
        assert schema.subtype == subtype
        assert schema.schema_id == f"{doc_type}/{subtype}@{source_rev()}"
        assert set(DEFAULT_FIELD_TYPES[doc_type]) <= set(schema.fields)
        assert {spec.status for spec in schema.fields.values()} <= set(FIELD_STATUSES)
        assert json.loads(json.dumps(schema.as_dict()))["schema_id"] == schema.schema_id


def source_rev() -> str:
    """The frozen revision tag."""
    return extraction_status_source()["revision"]


def test_iter_covers_every_schema_once():
    """Five doc-type schemas plus one per subtype, no duplicates."""
    ids = [s.schema_id for s in iter_extraction_schemas()]
    expected = len(MAILROOM_DOC_TYPES) + sum(len(extraction_subtypes(d)) for d in MAILROOM_DOC_TYPES)
    assert len(ids) == len(set(ids)) == expected


def test_insurance_subtypes_follow_the_gt():
    """CMS / property document adjuster absent; auto labels it on some rows."""
    pde = extraction_schema("insurance_claim", "pde")
    assert pde.fields["cms_source_table"].status == "derived"
    assert pde.fields["supporting_documents"].field_type == "entity_list:cms_doc_ref"
    assert set(pde.documented_absent_fields) == {"adjuster", "denial_reasons"}
    prop = extraction_schema("insurance_claim", "property")
    assert "cms_source_table" not in prop.fields
    assert prop.fields["adjuster"].status == "documented_absent"
    auto = extraction_schema("insurance_claim", "auto")
    assert auto.fields["adjuster"].status == "partial"
    assert auto.fields["claim_checklist"].status == "pending_annotation"


def test_contract_truth_comes_from_cuad_labels_per_family():
    """Families with labelled CUAD rows derive; families mostly pending report pending."""
    lic = extraction_schema("contract", "License_Agreements")
    assert lic.subtype == "license"
    assert lic.fields["parties"].status == "derived"
    assert lic.fields["parties"].source == "cuad_clause_labels"
    assert lic.fields["cuad_family"].source == "subtype"
    assert lic.fields["maud_clauses"].status == "not_applicable"
    assert lic.salient  # salient CUAD categories for the family
    assert extraction_schema("contract", "consulting").fields["parties"].status == "pending_annotation"


def test_merger_and_corporate_subtypes_carry_their_guidance():
    """MAUD priority questions per consideration; corporate subclass entities."""
    cash = extraction_schema("merger_agreement", "all_cash")
    assert cash.fields["maud_clauses"].status == "derived"
    assert cash.fields["merger_consideration"].source == "subtype"
    assert cash.fields["intent"].status == "not_applicable"
    assert "Type of Consideration" in cash.salient
    indenture = extraction_schema("corporate_record", "indenture")
    assert "trustee" in indenture.fields
    assert "trustee" in indenture.extensions
    assert indenture.fields["record_type"].status == "derived"
    assert set(indenture.scored_fields) >= {"intent", "subject_matter", "keywords"}


def test_correspondence_label_task_fields_are_not_extraction_fields():
    """Topic / sentiment are label tasks; the form is the subtype."""
    email = extraction_schema("correspondence", "email")
    assert email.fields["content_topic"].status == "label_task"
    assert "content_topic" not in email.field_types
    assert email.fields["communication_type"].source == "subtype"
    assert "sender" in email.pending_fields


def test_json_schema_is_strict_and_typed():
    """Guided-decoding schema: every extraction field, each with a type."""
    js = extraction_schema("insurance_claim", "carrier").json_schema()
    assert js["additionalProperties"] is False
    assert set(js["required"]) == set(js["properties"])
    assert all("type" in prop for prop in js["properties"].values())
    assert "cms_source_table" in js["properties"]


def test_unknown_class_or_subtype_is_rejected():
    """Only the five classes and their catalogued subtypes resolve."""
    with pytest.raises(KeyError):
        extraction_schema("due_diligence")
    with pytest.raises(KeyError):
        extraction_schema("insurance_claim", "marine")


def test_schema_coverage_reports_labelled_and_pending_fields():
    """A row's scorable fields, its unlabelled scored fields, and pending fields."""
    gt = {"claim_number": "1", "claim_type": "health", "adjuster": "", "denial_reasons": ""}
    cov = schema_coverage("insurance_claim", "pde", gt)
    assert cov["schema_id"].startswith("insurance_claim/pde@")
    assert {"claim_number", "adjuster", "denial_reasons", "cms_source_table"} <= set(cov["scorable_fields"])
    assert "policy_number" in cov["unlabelled_fields"]
    assert cov["pending_fields"] == ["claim_checklist"]


def test_score_document_names_its_schema():
    """Per-document payloads say which subtype schema they were scored under."""
    suite = get_suite("insurance_claims_specialist")
    gt = {"claim_number": "1", "claim_type": "health"}
    out = suite.score_document(gt, dict(gt), expected_subclass="pde")
    assert out["schema"]["schema_id"].startswith("insurance_claim/pde@")
    plain = suite.score_document(gt, dict(gt))
    assert plain["schema"]["subtype"] is None


def test_registry_is_exported_from_the_root():
    """Consumers import the registry from the package root."""
    for name in ("extraction_schema", "iter_extraction_schemas", "schema_coverage",
                 "ExtractionSchema", "FieldSchema", "extraction_subtypes"):
        assert name in dojo.__all__ and hasattr(dojo, name)


def test_corporate_entity_name_is_labelled_from_the_relabel():
    """v9.2.1 labels the registrant; subclass entities stay pending everywhere."""
    assert extraction_schema("corporate_record").fields["entity_name"].status in {"scored", "partial"}
    indenture = extraction_schema("corporate_record", "indenture")
    assert "entity_name" in indenture.scored_fields
    assert all(indenture.fields[name].status == "pending_annotation" for name in indenture.extensions)


def test_label_derived_fields_need_the_rows_labels():
    """CUAD-derived fields are scorable only when the row carries live clause labels."""
    labels = json.dumps({"Parties": [{"text": "Acme"}]})
    with_labels = schema_coverage("contract", "license", {"cuad_clause_labels": labels})
    assert "parties" in with_labels["scorable_fields"]
    bare = schema_coverage("contract", "license", {})
    assert "parties" in bare["unlabelled_fields"] and "parties" not in bare["scorable_fields"]
    stale = schema_coverage("contract", "license", {
        "cuad_clause_labels": labels,
        "gt_presence": {"cuad_clause_labels": "pending_annotation"},
    })
    assert "parties" in stale["unlabelled_fields"]
    assert "cuad_family" in bare["scorable_fields"]  # subtype-derived needs no label


def test_pending_presence_overrides_a_stale_gt_value():
    """A ``pending_annotation`` field is unlabelled even with a value attached."""
    gt = {"claim_number": "1", "claim_type": "health", "gt_presence": {"claim_number": "pending_annotation"}}
    cov = schema_coverage("insurance_claim", "carrier", gt)
    assert "claim_number" in cov["unlabelled_fields"]


def test_direct_field_value_counts_without_clause_labels():
    """A ``parties`` value supplied directly is scored, so coverage counts it."""
    cov = schema_coverage("contract", "license", {"parties": ["Acme"]})
    assert "parties" in cov["scorable_fields"]
    pending = schema_coverage("contract", "license", {
        "parties": ["Acme"], "gt_presence": {"parties": "pending_annotation"},
    })
    assert "parties" in pending["unlabelled_fields"]


def test_documented_absence_counts_only_on_cms_rows():
    """Field scoring credits an empty adjuster only on CMS rows."""
    prop = schema_coverage("insurance_claim", "property", {"claim_type": "property", "adjuster": ""})
    assert "adjuster" not in prop["scorable_fields"]
    cms = schema_coverage("insurance_claim", "pde", {"claim_type": "health", "cms_source_table": None})
    assert {"adjuster", "denial_reasons"} <= set(cms["scorable_fields"])
