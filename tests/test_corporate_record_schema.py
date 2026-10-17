"""Per-subclass corporate-record schema, unlabeled-GT scoring, and label audit."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.corporate_record_schema import (
    CORE_FIELDS,
    RECORD_TYPES,
    SUBCLASS_SCHEMAS,
    align_unlabeled,
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


def test_labeled_extension_entity_is_scored_both_ways():
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
    gt = dict(_GT, gt_presence=json.dumps({"entity_name": "pending_annotation"}))
    assert "entity_name" in unlabeled_fields("articles_of_incorporation", gt)
    suite = get_suite("corporate_records_specialist")
    out = suite.score_document(json.dumps(gt), _PRED, doc_subclass="articles_of_incorporation")
    assert out["extraction_precision"] == 1.0
    assert "entity_name" in out["unlabeled_fields"]


def test_json_schema_accepts_prompt_compliant_output_for_inapplicable_keys():
    from llm_dojo_scoring.corporate_record_schema import corporate_record_json_schema as js

    sch = js("bylaws")
    assert set(sch["required"]) >= set(CORE_FIELDS)
    assert sch["properties"]["filing_number"] == {"type": "null"}
    assert js("subsidiary_list")["properties"]["signatories"]["maxItems"] == 0


@pytest.mark.parametrize("key", ["entity_name", "registered_agent"])
@pytest.mark.parametrize("value", [None, "", "  ", "null", "N/A", [], "[]", {}, "{}"])
def test_empty_entity_representations_remain_unlabeled(key, value):
    assert key in unlabeled_fields("articles_of_incorporation", {key: value})


@pytest.mark.parametrize(
    "status,value,scored,is_unlabeled",
    [
        (None, "CT Corporation", True, False),
        (None, "", False, True),
        ("populated", "CT Corporation", True, False),
        ("populated", "", True, True),
        ("schema_documented_absence", "", True, False),
        ("not_applicable", "", False, False),
        ("pending_annotation", "", False, True),
        ("pending_annotation", "Stale agent", False, True),
    ],
)
def test_extension_label_status_controls_scoring(status, value, scored, is_unlabeled):
    gt = {"registered_agent": value, "gt_presence": {}}
    if status is not None:
        gt["gt_presence"]["registered_agent"] = status
    for raw in (gt, json.dumps(gt)):
        types = scored_field_types("articles_of_incorporation", raw)
        assert ("registered_agent" in types) is scored
        assert ("registered_agent" in unlabeled_fields("articles_of_incorporation", raw)) is is_unlabeled


def test_alignment_drops_unlabeled_and_foreign_entities_without_mutation():
    gt = dict(_GT, registered_agent="CT Corporation")
    expected = dict(gt, principal="Unannotated principal")
    predicted = dict(_PRED, principal="Jane Doe")
    before = deepcopy((gt, expected, predicted))

    aligned_gt, aligned_pred, dropped = align_unlabeled(
        "articles_of_incorporation", gt, expected, predicted
    )

    assert (gt, expected, predicted) == before
    assert "entity_name" in dropped
    assert "registered_agent" not in dropped
    assert aligned_gt["registered_agent"] == aligned_pred["registered_agent"] == "CT Corporation"
    assert "principal" not in aligned_gt and "principal" not in aligned_pred
    assert "entity_name" not in aligned_gt and "entity_name" not in aligned_pred
    assert aligned_gt["intent"] == aligned_pred["intent"] == "entity_formation"


def test_alignment_preserves_labeled_entities_even_from_another_subclass():
    gt = dict(_GT, trustee="BNY Mellon", gt_presence={"trustee": "populated"})
    expected, predicted, _ = align_unlabeled("bylaws", gt, gt, {"trustee": "BNY Mellon"})
    assert expected["trustee"] == predicted["trustee"] == "BNY Mellon"


def test_alignment_returns_independent_dicts_when_no_fields_are_dropped():
    gt = {key: "Labeled" for key in CORE_FIELDS}
    expected, predicted, dropped = align_unlabeled("other", gt, gt, gt)
    assert dropped == ()
    assert expected == predicted == gt
    assert expected is not gt and predicted is not gt and expected is not predicted


@pytest.mark.parametrize("subclass", [None, *SUBCLASS_SCHEMAS])
def test_json_schema_validates_complete_empty_payloads(subclass):
    jsonschema = pytest.importorskip("jsonschema")
    schema = corporate_record_json_schema(subclass)
    jsonschema.Draft202012Validator.check_schema(schema)
    payload = {
        key: [] if "array" in spec.get("type", []) else None
        for key, spec in schema["properties"].items()
    }
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(payload)

    # Every declared key is required, including empty extension entities.
    for key in payload:
        incomplete = {name: value for name, value in payload.items() if name != key}
        assert not validator.is_valid(incomplete), key
    assert not validator.is_valid(dict(payload, invented_entity="Acme"))
    assert not validator.is_valid(dict(payload, record_type="indenture"))


@pytest.mark.parametrize(
    "subclass,key,valid,invalid",
    [
        ("bylaws", "filing_number", None, "12345"),
        ("subsidiary_list", "signatories", [], ["Jane Doe"]),
        ("subsidiary_list", "jurisdiction", None, "Delaware"),
        ("powers_of_attorney", "attorneys_in_fact", ["Jane Doe"], "Jane Doe"),
        ("rights_instrument", "exercise_price", "$10.00", 10),
        ("indenture", "maturity_date", "2030-01-01", 20300101),
    ],
)
def test_json_schema_enforces_entity_types_and_inapplicable_core(subclass, key, valid, invalid):
    jsonschema = pytest.importorskip("jsonschema")
    schema = corporate_record_json_schema(subclass)
    payload = {
        name: [] if "array" in spec.get("type", []) else None
        for name, spec in schema["properties"].items()
    }
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(dict(payload, **{key: valid}))
    assert not validator.is_valid(dict(payload, **{key: invalid}))


def test_audit_aggregates_clean_malformed_and_unknown_subclass_rows():
    clean = {
        "intent": "other",
        "gt_presence": {key: "schema_documented_absence" for key in CORE_FIELDS},
    }
    rows = [
        {"expected": "corporate_record", "expected_subclass": "unknown", "gt_fields": clean},
        {"expected": "corporate_record", "expected_subclass": "other", "gt_fields": "{bad"},
        {"expected": "corporate_record", "expected_subclass": "bylaws", "gt_fields": "[]"},
        {"expected": "contract", "gt_fields": "{bad"},
    ]
    before = deepcopy(rows)
    report = audit_gt_rows(iter(rows))
    assert report == {
        "n_rows": 3,
        "totals": {"rows": 3, "gt_unparseable": 2},
        "by_subclass": {
            "other": {"rows": 2, "gt_unparseable": 1},
            "bylaws": {"rows": 1, "gt_unparseable": 1},
        },
    }
    assert rows == before
    assert audit_gt_rows([]) == {"n_rows": 0, "totals": {}, "by_subclass": {}}


@pytest.mark.parametrize("key", ["entity_name", "registered_agent"])
def test_stale_pending_entity_is_excluded_from_both_sides_of_suite_scoring(key):
    gt = dict(_GT, **{key: "Stale label"}, gt_presence={key: "pending_annotation"})
    out = get_suite("corporate_records_specialist").score_document(
        gt, _PRED, doc_subclass="articles_of_incorporation"
    )
    assert key in out["unlabeled_fields"]
    assert key not in out["extraction"].field_scores
    assert out["extraction_precision"] == out["extraction_recall"] == 1.0


def test_documented_absence_of_extension_penalizes_prediction():
    gt = dict(_GT, registered_agent="", gt_presence={"registered_agent": "schema_documented_absence"})
    suite = get_suite("corporate_records_specialist")
    filled = suite.score_document(gt, _PRED, doc_subclass="articles_of_incorporation")
    empty = suite.score_document(gt, dict(_PRED, registered_agent=None), doc_subclass="articles_of_incorporation")
    assert "registered_agent" not in filled["unlabeled_fields"]
    assert filled["extraction_precision"] < empty["extraction_precision"] == 1.0
    assert filled["extraction_recall"] == empty["extraction_recall"] == 1.0


def test_extension_entity_lists_use_list_scoring_without_expanding_format_requirements():
    gt = dict(_GT, incorporators='["Alice Brown", "David Smith"]', gt_presence={"incorporators": "populated"})
    suite = get_suite("corporate_records_specialist")
    core_pred = {key: value for key, value in _PRED.items() if key in CORE_FIELDS}
    hit = suite.score_document(
        gt, dict(core_pred, incorporators=["David Smith", "Alice Brown"]),
        doc_subclass="articles_of_incorporation",
    )
    missing = suite.score_document(gt, core_pred, doc_subclass="articles_of_incorporation")
    assert hit["extraction"].field_scores["incorporators"] == 1.0
    assert hit["extraction_recall"] == 1.0
    assert missing["extraction_recall"] < hit["extraction_recall"]
    assert missing["schema_valid"] == 1.0
    incomplete = {key: value for key, value in core_pred.items() if key != "entity_name"}
    incomplete_score = suite.score_document(gt, incomplete, doc_subclass="articles_of_incorporation")
    assert incomplete_score["schema_valid"] == round((len(CORE_FIELDS) - 1) / len(CORE_FIELDS), 4)


@pytest.mark.parametrize("subclass_kw", ["doc_subclass", "expected_subclass"])
def test_batch_label_status_is_local_to_each_row_and_preserves_inputs(subclass_kw):
    rows = [
        dict(_GT, gt_presence={"registered_agent": "pending_annotation"}),
        dict(_GT, registered_agent="CT Corporation", gt_presence={"registered_agent": "populated"}),
        dict(_GT, registered_agent="", gt_presence={"registered_agent": "schema_documented_absence"}),
    ]
    predictions = [deepcopy(_PRED) for _ in rows]
    before = deepcopy((rows, predictions))
    suite = get_suite("corporate_records_specialist")
    out = suite.score(rows, predictions, **{subclass_kw: ["articles_of_incorporation"] * 3})
    assert (rows, predictions) == before
    assert "registered_agent" in out["unlabeled_fields"][0]
    assert "registered_agent" not in out["unlabeled_fields"][1]
    assert "registered_agent" not in out["unlabeled_fields"][2]
    assert out["extraction_precision"] < 1.0
    predictions[2]["registered_agent"] = None
    repaired = suite.score(rows, predictions, **{subclass_kw: "articles_of_incorporation"})
    assert repaired["extraction_precision"] == repaired["extraction_recall"] == 1.0


def test_batch_alignment_handles_invalid_gt_short_subclass_list_and_surplus_predictions():
    out = get_suite("corporate_records_specialist").score(
        ["{bad GT", _GT, _GT], [_PRED, _PRED, _PRED, {"entity_name": "Surplus"}],
        doc_subclass=["bylaws", "articles_of_incorporation"],
    )
    assert out["unlabeled_fields"] == [
        [], list(unlabeled_fields("articles_of_incorporation", _GT)),
        list(unlabeled_fields(None, _GT)),
    ]
