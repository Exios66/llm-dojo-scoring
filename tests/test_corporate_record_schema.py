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
    """Every sorter subclass has a schema with valid record type and core fields."""
    assert set(SUBCLASS_SCHEMAS) == set(DOC_TYPE_SUBCLASSES["corporate_record"])
    for s in SUBCLASS_SCHEMAS.values():
        assert s.record_type in RECORD_TYPES
        assert set(s.core_applicable) <= set(CORE_FIELDS)


def test_subclasses_are_not_one_blanket_schema():
    """Subclass schemas expose distinct entities and omit inapplicable core fields."""
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
    """Subclass lookup normalizes aliases and falls back to the other schema."""
    assert subclass_schema("charter_amendment").record_type == "articles_of_incorporation"
    assert subclass_schema("indenture").record_type == "other"
    assert subclass_schema("Powers of Attorney").record_type == "powers_of_attorney"
    assert subclass_schema("nonsense").subclass == "other"


def test_scored_field_types_gates_extension_entities_on_labels():
    """Score extension fields only when labeled, retaining canonical core types."""
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
    """Subclass JSON schemas expose their own entities and the record-type enum."""
    poa = corporate_record_json_schema("powers_of_attorney")
    assert "principal" in poa["properties"] and "trustee" not in poa["properties"]
    assert poa["properties"]["record_type"] == {"enum": [*RECORD_TYPES, None]}
    assert set(corporate_record_json_schema()["properties"]) == set(CORE_FIELDS)


def test_unlabeled_vs_documented_absence():
    """Blank entities are unlabeled unless presence metadata documents absence."""
    assert set(unlabeled_fields("articles_of_incorporation", _GT)) >= {
        "entity_name", "filing_number", "registered_agent"
    }
    gt = dict(_GT, gt_presence=json.dumps({"filing_number": "schema_documented_absence"}))
    assert "filing_number" not in unlabeled_fields("articles_of_incorporation", gt)


def test_correct_entity_extraction_not_penalized_on_unlabeled_gt():
    """Filled predictions for unlabeled entities do not reduce extraction scores."""
    suite = get_suite("corporate_records_specialist")
    out = suite.score_document(json.dumps(_GT), _PRED, doc_subclass="articles_of_incorporation")
    assert out["extraction_precision"] == 1.0
    assert out["extraction_recall"] == 1.0
    assert "entity_name" in out["unlabeled_fields"]
    assert set(out["extraction"].field_scores) == {"intent", "subject_matter", "keywords"}


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("serialized", [False, True])
def test_unlabeled_predictions_still_receive_document_audit(batch, serialized):
    suite = get_suite("corporate_records_specialist")
    predicted = dict(_PRED, signatories=["Jane Doe", "Imaginary Goblin"])
    predictions = [predicted, dict(predicted, entity_name="Phantom Holdings")]
    if serialized:
        predictions = [json.dumps(pred) for pred in predictions]
    text = "Articles of Acme Inc. in Delaware. Jane Doe. CT Corporation."
    out = suite.score(
        [json.dumps(_GT)] * 2 if batch else json.dumps(_GT),
        predictions if batch else predictions[0],
        doc_text=[text, text] if batch else text,
        doc_subclass=(
            ["articles_of_incorporation"] * 2 if batch else "articles_of_incorporation"
        ),
        detailed=True,
    )
    assert out["extraction_precision"] == out["extraction_recall"] == 1.0
    results = out["extraction"] if batch else [out["extraction"]]
    for idx, result in enumerate(results):
        assert set(result.field_scores) == {"intent", "subject_matter", "keywords"}
        audit = result.entity_list_audit
        assert audit["entity_name"]["verified_in_doc"] == int(idx == 0)
        assert audit["entity_name"]["hallucinated"] == int(idx != 0)
        assert audit["registered_agent"]["verified_in_doc"] == 1
        assert audit["signatories"]["n_predicted"] == 2
        assert audit["signatories"]["verified_in_doc"] == 1
        assert audit["signatories"]["hallucinated"] == 1
    assert predicted["signatories"] == ["Jane Doe", "Imaginary Goblin"]
    assert predicted["entity_name"] == "Acme Inc."


@pytest.mark.parametrize(
    ("verification", "text"), [(False, "Acme Inc."), (True, None), (True, "")]
)
def test_unlabeled_prediction_audit_requires_verification_and_document(
    monkeypatch, verification, text,
):
    from llm_dojo_scoring import field_scoring

    monkeypatch.setattr(field_scoring, "verification_enabled", lambda: verification)
    out = get_suite("corporate_records_specialist").score_document(
        json.dumps(_GT), _PRED, doc_subclass="articles_of_incorporation", doc_text=text,
    )
    assert out["extraction"].entity_list_audit == {}
    assert out["extraction_precision"] == out["extraction_recall"] == 1.0


def test_labeled_entities_are_scored_and_documented_absence_penalizes_fill():
    """Score labeled entities and penalize filling a field documented as absent."""
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
    """Batch scoring excludes unlabeled entities separately for each subclass."""
    suite = get_suite("corporate_records_specialist")
    out = suite.score(
        [json.dumps(_GT), json.dumps(_GT)],
        [_PRED, _PRED],
        doc_subclass=["articles_of_incorporation", "bylaws"],
    )
    assert out["extraction_precision"] == 1.0
    assert len(out["unlabeled_fields"]) == 2


def test_batch_unlabeled_fields_stay_aligned_across_unparseable_rows():
    """Per-row ``unlabeled_fields`` is aligned to GT row order even when an
    earlier row's model answer does not parse: the skipped row reports ``[]``
    instead of skipping the entry, so later rows are not shifted."""
    suite = get_suite("corporate_records_specialist")
    out = suite.score(
        [json.dumps(_GT), json.dumps(_GT)],
        ["{not json", _PRED],
        doc_subclass=["articles_of_incorporation", "bylaws"],
    )
    fields = out["unlabeled_fields"]
    assert len(fields) == 2
    assert fields[0] == []  # unparseable prediction: no alignment, no entry skipped
    # The aligned partner row still sees its own bylaws unlabeled set, not the
    # set of the row that was skipped — proving no shift-against-GT alignment.
    assert fields[1] == list(unlabeled_fields("bylaws", _GT))
    # A padded missing prediction reports ``[]`` too.
    short = suite.score(
        [json.dumps(_GT)],
        [],
        doc_subclass=["articles_of_incorporation"],
    )
    assert short["unlabeled_fields"] == [[]]


def test_audit_flags_published_label_defects():
    """Audit detects known label defects and aggregates only corporate rows."""
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
    # The stated own-subclass entity is labeled: no unlabeled/wrong-subclass
    # defect for it, the pin (investor_rights) is honored, and the template /
    # provenance / heuristic defects from the shared fixture are still there.
    trustee_labeled = audit_gt_row("indenture", dict(gt, trustee="BNY"))
    assert "entity_unlabeled:trustee" not in trustee_labeled
    assert "entity_wrong_subclass:trustee" not in trustee_labeled
    assert "intent_mismatch" not in trustee_labeled
    assert "intent_heuristic" in trustee_labeled
    assert "subject_matter_template" in trustee_labeled
    assert "keywords_provenance_ids" in trustee_labeled
    rows = [{"expected": "corporate_record", "expected_subclass": "indenture", "gt_fields": json.dumps(gt)},
            {"expected": "contract", "expected_subclass": "license", "gt_fields": "{}"}]
    report = audit_gt_rows(rows)
    assert report["n_rows"] == 1
    assert report["by_subclass"]["indenture"]["subject_matter_template"] == 1


def test_wrong_subclass_entity_is_flagged():
    """Audit flags populated entities belonging to a different subclass."""
    gt = dict(_GT, trustee="BNY")
    assert "entity_wrong_subclass:trustee" in audit_gt_row("bylaws", gt)


@pytest.mark.parametrize("family", ["production", "production_prompts"])
def test_specialist_prompt_embeds_generated_subclass_schema(family):
    """Both prompt families embed generated subclass guidance within the size cap."""
    text = get_prompt("corporate_records_specialist", family=family).text
    assert render_prompt_section() in text
    for sub in SUBCLASS_SCHEMAS:
        if sub != "certificate_of_formation":  # folded into articles_of_incorporation
            assert render_subclass_block(sub) in text
    assert len(text) <= 5865  # never longer than the frozen v1 baseline
    assert "key_provisions" not in text.replace("Do not emit the retired key `key_provisions`", "")


def test_audit_flags_subclass_content_conflict_on_prose_subject():
    """Prose can reveal subclass conflicts; provenance templates cannot."""
    gt = {"intent": "entity_formation", "subject_matter": "Bylaws of Acme Inc., governing meetings."}
    assert "subclass_content_conflict:bylaws" in audit_gt_row("articles_of_incorporation", gt)
    assert not [d for d in audit_gt_row("bylaws", gt) if d.startswith("subclass_content")]
    template = {"subject_matter": "bylaws of Acme (CIK 1) (SEC EDGAR exhibit)."}
    assert not [d for d in audit_gt_row("indenture", template) if d.startswith("subclass_content")]


def test_labeled_extension_entity_is_scored_both_ways():
    """Labeled extensions reward matches and penalize wrong or missing predictions."""
    suite = get_suite("corporate_records_specialist")
    gt = dict(
        _GT,
        registered_agent="CT Corp",
        gt_presence=json.dumps({"registered_agent": "populated"}),
    )
    sub = "articles_of_incorporation"
    hit = suite.score_document(json.dumps(gt), dict(_PRED, registered_agent="CT Corp"), doc_subclass=sub)
    assert hit["extraction"].field_scores["registered_agent"] == 1.0
    assert hit["extraction_precision"] == hit["extraction_recall"] == 1.0
    wrong = suite.score_document(json.dumps(gt), dict(_PRED, registered_agent="Other"), doc_subclass=sub)
    assert wrong["extraction"].field_scores["registered_agent"] < 0.5
    missing = {k: v for k, v in _PRED.items() if k != "registered_agent"}
    assert suite.score_document(json.dumps(gt), missing, doc_subclass=sub)["extraction_recall"] < 1.0


def test_pending_annotation_is_unlabeled_not_expected_empty():
    """Pending entity annotations are excluded from scoring and reported unlabeled."""
    gt = dict(_GT, gt_presence=json.dumps({"entity_name": "pending_annotation"}))
    assert "entity_name" in unlabeled_fields("articles_of_incorporation", gt)
    suite = get_suite("corporate_records_specialist")
    out = suite.score_document(json.dumps(gt), _PRED, doc_subclass="articles_of_incorporation")
    assert out["extraction_precision"] == 1.0
    assert "entity_name" in out["unlabeled_fields"]


def test_json_schema_accepts_prompt_compliant_output_for_inapplicable_keys():
    """Required inapplicable core keys accept only null or empty list values."""
    from llm_dojo_scoring.corporate_record_schema import corporate_record_json_schema as js

    sch = js("bylaws")
    assert set(sch["required"]) >= set(CORE_FIELDS)
    assert sch["properties"]["filing_number"] == {"type": "null"}
    assert js("subsidiary_list")["properties"]["signatories"]["maxItems"] == 0
