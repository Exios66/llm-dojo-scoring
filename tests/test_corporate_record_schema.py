"""Per-subclass corporate-record schema, unlabeled-GT scoring, and label audit."""

from __future__ import annotations

import json

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.corporate_record_schema import (
    CORE_FIELDS,
    RECORD_TYPES,
    SUBCLASS_SCHEMAS,
    audit_gt_row,
    audit_gt_rows,
    corporate_record_json_schema,
    render_prompt_section,
    render_subclass_block,
    scored_field_types,
    subclass_schema,
    unlabeled_fields,
)
from llm_dojo_scoring.corpus import DOC_TYPE_SUBCLASSES
from llm_dojo_scoring.prompts import get_prompt
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES

_GT = {
    "intent": "entity_formation",
    "subject_matter": "Articles of Acme Inc.",
    "keywords": '["articles"]',
    "entity_name": "",
    "record_type": "",
    "effective_date": "",
    "signatories": "[]",
    "jurisdiction": "",
    "filing_number": "",
}
_PRED = {
    "entity_name": "Acme Inc.",
    "record_type": "articles_of_incorporation",
    "effective_date": "2020-01-01",
    "signatories": ["Jane Doe"],
    "jurisdiction": "Delaware",
    "filing_number": None,
    "registered_agent": "CT Corporation",
    "intent": "entity_formation",
    "subject_matter": "Articles of Acme Inc.",
    "keywords": ["articles"],
}


def test_every_subclass_has_a_schema_and_valid_record_type():
    assert set(SUBCLASS_SCHEMAS) == set(DOC_TYPE_SUBCLASSES["corporate_record"])
    for s in SUBCLASS_SCHEMAS.values():
        assert s.record_type in RECORD_TYPES
        assert set(s.core_applicable) <= set(CORE_FIELDS)


def test_subclasses_are_not_one_blanket_schema():
    shapes = {
        s.subclass: (s.core_applicable, tuple(e.key for e in s.entities))
        for s in SUBCLASS_SCHEMAS.values()
    }
    assert len({v for v in shapes.values()}) >= 9
    assert "attorneys_in_fact" in shapes["powers_of_attorney"][1]
    assert "trustee" in shapes["indenture"][1]
    assert "subsidiaries" in shapes["subsidiary_list"][1]
    assert "filing_number" not in shapes["bylaws"][0]
    assert "signatories" not in shapes["subsidiary_list"][0]


def test_sorter_subclass_maps_to_record_type():
    assert subclass_schema("charter_amendment").record_type == "articles_of_incorporation"
    assert subclass_schema("indenture").record_type == "other"
    assert subclass_schema("Powers of Attorney").record_type == "powers_of_attorney"
    assert subclass_schema("nonsense").subclass == "other"


def test_scored_field_types_gates_extension_entities_on_labels():
    core = scored_field_types("indenture")
    assert "trustee" not in core and "filing_number" not in core
    labeled = scored_field_types("indenture", {"trustee": "Wells Fargo", "guarantors": "[]"})
    assert labeled["trustee"] == "name"
    assert "guarantors" not in labeled
    documented = scored_field_types(
        "indenture", {"gt_presence": json.dumps({"guarantors": "schema_documented_absence"})}
    )
    assert documented["guarantors"] == "entity_list:name"
    for ft in (core, labeled, documented):
        for k in set(ft) & set(CORE_FIELDS):
            assert ft[k] == DEFAULT_FIELD_TYPES["corporate_record"][k]


def test_json_schema_is_per_subclass():
    poa = corporate_record_json_schema("powers_of_attorney")
    assert "principal" in poa["properties"] and "trustee" not in poa["properties"]
    assert poa["properties"]["record_type"] == {"enum": [*RECORD_TYPES, None]}
    assert set(corporate_record_json_schema()["properties"]) == set(CORE_FIELDS)


def test_unlabeled_vs_documented_absence():
    assert set(unlabeled_fields("articles_of_incorporation", _GT)) >= {
        "entity_name", "filing_number", "registered_agent"
    }
    gt = dict(_GT, gt_presence=json.dumps({"filing_number": "schema_documented_absence"}))
    assert "filing_number" not in unlabeled_fields("articles_of_incorporation", gt)


def test_correct_entity_extraction_not_penalized_on_unlabeled_gt():
    suite = get_suite("corporate_records_specialist")
    out = suite.score_document(json.dumps(_GT), _PRED, doc_subclass="articles_of_incorporation")
    assert out["extraction_precision"] == 1.0
    assert out["extraction_recall"] == 1.0
    assert "entity_name" in out["unlabeled_fields"]
    assert set(out["extraction"].field_scores) == {"intent", "subject_matter", "keywords"}


def test_labeled_entities_are_scored_and_documented_absence_penalizes_fill():
    suite = get_suite("corporate_records_specialist")
    gt = dict(
        _GT,
        entity_name="Acme Inc.",
        gt_presence=json.dumps({"entity_name": "populated", "filing_number": "schema_documented_absence"}),
    )
    ok = suite.score_document(json.dumps(gt), _PRED, doc_subclass="articles_of_incorporation")
    assert ok["extraction"].field_scores["entity_name"] == 1.0
    bad = suite.score_document(
        json.dumps(gt), dict(_PRED, filing_number="12345"), doc_subclass="articles_of_incorporation"
    )
    assert bad["extraction_precision"] < ok["extraction_precision"]


def test_batch_scoring_aligns_unlabeled_per_row():
    suite = get_suite("corporate_records_specialist")
    out = suite.score(
        [json.dumps(_GT), json.dumps(_GT)],
        [_PRED, _PRED],
        doc_subclass=["articles_of_incorporation", "bylaws"],
    )
    assert out["extraction_precision"] == 1.0


def test_audit_flags_published_label_defects():
    gt = {
        "intent": "investor_rights",
        "subject_matter": "indenture of X Ltd. (CIK 0001900035) (SEC EDGAR exhibit).",
        "keywords": '["indenture", "EX-4.5", "S-1/A", "0001493152-23-024269", "X Ltd. (CIK 0001900035)"]',
        "intent_source": "heuristic",
        "gt_presence": "{}",
    }
    defects = audit_gt_row("officer_certificate", gt)
    assert "subject_matter_template" in defects
    assert "keywords_provenance_ids" in defects
    assert "intent_mismatch" in defects
    assert "intent_heuristic" in defects
    assert "entity_unlabeled:certifying_officer" in defects
    assert audit_gt_row("indenture", dict(gt, trustee="BNY"))[0] != ""
    rows = [{"expected": "corporate_record", "expected_subclass": "indenture", "gt_fields": json.dumps(gt)},
            {"expected": "contract", "expected_subclass": "license", "gt_fields": "{}"}]
    report = audit_gt_rows(rows)
    assert report["n_rows"] == 1
    assert report["by_subclass"]["indenture"]["subject_matter_template"] == 1


def test_wrong_subclass_entity_is_flagged():
    gt = dict(_GT, trustee="BNY")
    assert "entity_wrong_subclass:trustee" in audit_gt_row("bylaws", gt)


@pytest.mark.parametrize("family", ["production", "production_prompts"])
def test_specialist_prompt_embeds_generated_subclass_schema(family):
    text = get_prompt("corporate_records_specialist", family=family).text
    assert render_prompt_section() in text
    for sub in SUBCLASS_SCHEMAS:
        if sub != "certificate_of_formation":  # folded into articles_of_incorporation
            assert render_subclass_block(sub) in text
    assert len(text) <= 5865  # never longer than the frozen v1 baseline
    assert "key_provisions" not in text.replace("Do not emit the retired key `key_provisions`", "")


def test_audit_flags_subclass_content_conflict_on_prose_subject():
    gt = {"intent": "entity_formation", "subject_matter": "Bylaws of Acme Inc., governing meetings."}
    assert "subclass_content_conflict:bylaws" in audit_gt_row("articles_of_incorporation", gt)
    assert not [d for d in audit_gt_row("bylaws", gt) if d.startswith("subclass_content")]
    template = {"subject_matter": "bylaws of Acme (CIK 1) (SEC EDGAR exhibit)."}
    assert not [d for d in audit_gt_row("indenture", template) if d.startswith("subclass_content")]
