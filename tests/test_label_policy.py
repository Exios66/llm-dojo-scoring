"""One label policy for every consumer: stale Hub labels out, reviewed overlays in (#164, #171, #94)."""

from __future__ import annotations

import copy
import json

import pytest

from llm_dojo_scoring.schemas.label_policy import (
    apply_label_overlays,
    doc_sha,
    drop_stale_hub_labels,
    stale_hub_labels,
)
from llm_dojo_scoring.scoring.doc_scorers.common import score_common
from llm_dojo_scoring.scoring.extraction_scope import scope_extraction_pair

CORP_TEMPLATE = "bylaws of DentonX Inc  (DNTX)  (CIK 0002093375) (SEC EDGAR exhibit). AMENDED AND RESTATED BY-LAWS"
CORP_STALE = {
    "subject_matter": CORP_TEMPLATE,
    "keywords": ["bylaws", "EX-3.2", "S-1/A", "0001193125-10-012345"],
    "intent": "governance",
    "intent_source": "heuristic",
}
CORR_STALE = {
    "subject_matter": "Correspondence concerning general_business.",
    "keywords": ["general_business", "email", "allen-p", "_sent_mail", "2000-06-26T09:40:00+00:00"],
    "intent": "notice",
    "intent_source": "heuristic",
}
TEXT = "From: Phillip Allen\nTo: John Lavorato\nDate: June 26, 2000\nGas prices moved again."


def test_stale_hub_labels_name_each_defect() -> None:
    """Templated subject_matter, provenance/metadata keywords and heuristic intent are stale."""
    assert stale_hub_labels("corporate_record", CORP_STALE) == {
        "intent": "intent_heuristic",
        "subject_matter": "subject_matter_template",
        "keywords": "keywords_provenance_ids",
    }
    assert stale_hub_labels("correspondence", CORR_STALE) == {
        "intent": "intent_heuristic",
        "subject_matter": "subject_matter_templated",
        "keywords": "keywords_metadata",
    }


@pytest.mark.parametrize(
    ("doc_class", "gt"),
    [
        ("correspondence", {"intent": "request", "intent_source": "llm_zero_shot"}),
        ("correspondence", {"intent": "request", "intent_source": "manual"}),
        ("correspondence", {"subject_matter": "Gas price update for the West desk"}),
        ("correspondence", {"keywords": ["press release", "Meeting Request", "letter"]}),
        ("corporate_record", {"subject_matter": "Amended and restated bylaws of DentonX Inc."}),
        ("corporate_record", {"keywords": ["Certificate of Amendment", "Reverse Stock Split"]}),
        ("contract", {"subject_matter": "Correspondence concerning general_business."}),
        ("correspondence", {"intent": "", "intent_source": "heuristic"}),
        ("correspondence", "not json at all {"),
        ("correspondence", None),
    ],
)
def test_real_labels_are_kept(doc_class: str, gt: object) -> None:
    """Adjudicated intents, prose subjects, content keywords and blanks are not stale."""
    assert stale_hub_labels(doc_class, gt) == {}


def test_drop_keeps_presence_form_and_never_mutates() -> None:
    """A dropped field becomes ``pending_annotation`` in the row's own presence format."""
    gt = {**CORR_STALE, "sender": "Phillip Allen", "gt_presence": json.dumps({"sender": "populated"})}
    before = copy.deepcopy(gt)
    fields, dropped = drop_stale_hub_labels("correspondence", gt)
    assert gt == before
    assert set(dropped) == {"intent", "subject_matter", "keywords"}
    assert {"intent", "subject_matter", "keywords"}.isdisjoint(fields)
    presence = json.loads(fields["gt_presence"])
    assert presence == {"sender": "populated", "intent": "pending_annotation",
                        "subject_matter": "pending_annotation", "keywords": "pending_annotation"}


def test_scope_drops_stale_fields_from_both_sides() -> None:
    """A field with no truth is neither a miss nor a false positive."""
    pred = {"subject_matter": "Gas price update", "keywords": ["gas"], "intent": "update", "sender": "Phillip Allen"}
    scoped_pred, scoped_exp = scope_extraction_pair("correspondence", pred, {**CORR_STALE, "sender": "Phillip Allen"})
    assert scoped_pred == {"sender": "Phillip Allen"}
    assert scoped_exp == {"sender": "Phillip Allen"}


def test_correct_free_text_answer_is_not_a_miss_against_a_template() -> None:
    """#164: a correct reading scores on the real label, not against the template."""
    gt = {**CORR_STALE, "sender": "Phillip Allen"}
    pred = {"subject_matter": "Gas price update", "keywords": ["gas"], "intent": "update", "sender": "Phillip Allen"}
    result = score_common("correspondence", pred, gt)
    assert result["overall_extraction_score"] == 1.0
    assert result["extraction_f1"] == 1.0


def test_corporate_row_with_only_stale_labels_is_unscorable() -> None:
    """With every label stale there is nothing to score, so no number is invented."""
    pred = {"subject_matter": "Bylaws of DentonX Inc.", "keywords": ["Bylaws"], "intent": "compliance"}
    result = score_common("corporate_record", pred, CORP_STALE, doc_subclass="bylaws")
    assert result["overall_extraction_score"] is None


def _rec(labels: dict, *, text: str = TEXT, doc_class: str = "correspondence") -> dict:
    """One overlay record bound to *text*."""
    return {"doc_id": "DOC-1", "doc_class": doc_class, "doc_sha256": doc_sha(text), "labels": labels}


def _lab(value: object, status: str = "gap_fill", *, truth: bool = True, hub_value: object = None) -> dict:
    """One interim label."""
    return {"value": value, "status": status, "use_as_truth": truth, "hub_value": hub_value}


def test_gap_fill_applies_only_where_the_hub_is_silent() -> None:
    """The Hub label wins; an empty field takes the overlay value."""
    merged = apply_label_overlays(
        {"sender": "Hub Sender"},
        doc_class="correspondence",
        doc_text=TEXT,
        interim=_rec({"sender": _lab("Phillip Allen"), "recipient": _lab("John Lavorato")}),
    )
    assert merged.fields["sender"] == "Hub Sender"
    assert merged.fields["recipient"] == "John Lavorato"
    assert merged.sources == {"recipient": "interim:gap_fill"}
    assert merged.report["superseded"] == ["sender"]
    assert merged.fields["gt_presence"] == {"recipient": "populated"}


def test_correction_applies_only_while_the_hub_value_is_the_one_corrected() -> None:
    """A Hub revision that changes the value wins over an old correction."""
    lab = _lab(["Acme: licensor"], "correction", hub_value=["Acme"])
    still = apply_label_overlays({"party_roles": ["Acme"]}, doc_class="contract", doc_text=TEXT,
                                 interim=_rec({"party_roles": lab}, doc_class="contract"))
    assert still.fields["party_roles"] == ["Acme: licensor"]
    assert still.sources == {"party_roles": "interim:correction"}
    moved = apply_label_overlays({"party_roles": ["Acme Corp"]}, doc_class="contract", doc_text=TEXT,
                                 interim=_rec({"party_roles": lab}, doc_class="contract"))
    assert moved.fields["party_roles"] == ["Acme Corp"]
    assert moved.report["superseded"] == ["party_roles"]


def test_correction_of_a_blank_hub_field_applies_until_the_hub_fills_it() -> None:
    """CUAD corrections carry ``hub_value: null``: the Hub field is blank, the span label wrong."""
    lab = _lab(["TOWN OF VINTON", "ROANOKE GAS COMPANY"], "correction", hub_value=None)
    blank = apply_label_overlays({"parties": None}, doc_class="contract", doc_text=TEXT,
                                 interim=_rec({"parties": lab}, doc_class="contract"))
    assert blank.sources == {"parties": "interim:correction"}
    filled = apply_label_overlays({"parties": ["Town of Vinton"]}, doc_class="contract", doc_text=TEXT,
                                  interim=_rec({"parties": lab}, doc_class="contract"))
    assert filled.fields["parties"] == ["Town of Vinton"]
    assert filled.report["superseded"] == ["parties"]


def test_correction_of_a_stale_hub_label_is_judged_against_the_hub_value() -> None:
    """Dropping a stale label must not hide the value a correction was written against."""
    hub = {"intent": "notice", "intent_source": "heuristic"}
    lab = _lab("request", "correction", hub_value="notice")
    merged = apply_label_overlays(hub, doc_class="correspondence", doc_text=TEXT,
                                  interim=_rec({"intent": lab}))
    assert merged.fields["intent"] == "request"
    assert merged.sources == {"intent": "interim:correction"}
    assert merged.report["stale"] == {"intent": "intent_heuristic"}
    moved = apply_label_overlays({"intent": "payment_demand", "intent_source": "heuristic"},
                                 doc_class="correspondence", doc_text=TEXT, interim=_rec({"intent": lab}))
    assert "intent" not in moved.fields and moved.report["superseded"] == ["intent"]


def test_result_shares_no_objects_with_the_hub_row() -> None:
    """Changing a merged list never reaches the caller's ground truth."""
    hub = {"keywords": ["gas prices"]}
    merged = apply_label_overlays(hub, doc_class="correspondence", doc_text=TEXT,
                                  interim=_rec({"sender": _lab("Phillip Allen")}))
    merged.fields["keywords"].append("x")
    assert hub == {"keywords": ["gas prices"]}


def test_disputed_and_non_truth_labels_never_apply() -> None:
    """``disputed`` and ``use_as_truth: false`` stay out of the gold."""
    merged = apply_label_overlays(
        {}, doc_class="correspondence", doc_text=TEXT,
        interim=_rec({"sender": _lab("X", "disputed", truth=False), "recipient": _lab("Y", truth=False)}),
    )
    assert merged.sources == {}
    assert sorted(merged.report["disputed"]) == ["recipient", "sender"]


def test_text_or_class_mismatch_applies_nothing() -> None:
    """A label binds to the exact text and class it was read from."""
    wrong_text = apply_label_overlays({}, doc_class="correspondence", doc_text=TEXT + " edited",
                                      interim=_rec({"sender": _lab("Phillip Allen")}))
    wrong_class = apply_label_overlays({}, doc_class="contract", doc_text=TEXT,
                                       interim=_rec({"sender": _lab("Phillip Allen")}))
    assert wrong_text.sources == {} and wrong_class.sources == {}
    assert "text differs" in wrong_text.report["rejected"][0]
    assert "is not contract" in wrong_class.report["rejected"][0]


def test_closed_vocabulary_and_cms_rules() -> None:
    """A raw subclass is not a record_type; a CMS claim is health."""
    corp = apply_label_overlays(
        {}, doc_class="corporate_record", doc_text=TEXT,
        interim=_rec({"record_type": _lab("board_resolution", "derived")}, doc_class="corporate_record"),
    )
    assert corp.sources == {}
    assert corp.report["rejected"][0].startswith("record_type:")
    ok = apply_label_overlays(
        {}, doc_class="corporate_record", doc_text=TEXT,
        interim=_rec({"record_type": _lab("bylaws", "derived")}, doc_class="corporate_record"),
    )
    assert ok.fields["record_type"] == "bylaws"
    cms = apply_label_overlays(
        {}, doc_class="insurance_claim", doc_text=TEXT, doc_subclass="carrier",
        interim=_rec({"claim_type": _lab("carrier", "correction", hub_value=None)}, doc_class="insurance_claim"),
    )
    assert cms.sources == {}


def test_null_truth_label_is_a_documented_absence() -> None:
    """A null gap fill says the document does not state the field."""
    merged = apply_label_overlays(
        {"gt_presence": "{}"}, doc_class="corporate_record", doc_text=TEXT,
        interim=_rec({"filing_number": _lab(None)}, doc_class="corporate_record"),
    )
    assert merged.fields["filing_number"] is None
    assert json.loads(merged.fields["gt_presence"]) == {"filing_number": "schema_documented_absence"}


def test_near_gold_fills_only_what_nothing_else_labels() -> None:
    """Precedence: Hub, then interim truth, then near-gold."""
    near = _rec({
        "sender": {"value": "NG Sender", "basis": "near_gold:two_pass_agree"},
        "recipient": {"value": "NG Recipient", "basis": "near_gold:two_pass_agree"},
        "communication_date": {"value": "2000-06-26", "basis": "near_gold:opus_reviewed_correct"},
        "urgency": {"value": "routine", "basis": "gate_accept"},
    })
    merged = apply_label_overlays(
        {"sender": "Hub Sender"}, doc_class="correspondence", doc_text=TEXT,
        interim=_rec({"recipient": _lab("John Lavorato")}), near_gold=near,
    )
    assert merged.fields["sender"] == "Hub Sender"
    assert merged.fields["recipient"] == "John Lavorato"
    assert merged.fields["communication_date"] == "2000-06-26"
    assert merged.sources == {"recipient": "interim:gap_fill",
                              "communication_date": "near_gold:opus_reviewed_correct"}
    assert "urgency" not in merged.fields


def test_overlay_may_fill_a_field_whose_hub_label_was_stale() -> None:
    """A stale Hub label is no label, so a reviewed value can take its place."""
    merged = apply_label_overlays(
        dict(CORR_STALE), doc_class="correspondence", doc_text=TEXT,
        near_gold=_rec({"subject_matter": {"value": "Gas price update", "basis": "near_gold:two_pass_agree"}}),
    )
    assert merged.report["stale"]["subject_matter"] == "subject_matter_templated"
    assert merged.fields["subject_matter"] == "Gas price update"
    assert "intent" not in merged.fields and "keywords" not in merged.fields


def test_archive_block_drops_stale_labels_like_score_document() -> None:
    """Review MAJOR 1: the pipeline's archive block and score_document agree on one row."""
    from llm_dojo_scoring.pipeline.archive import score_archive_block
    from llm_dojo_scoring.scoring.doc_scorers.dispatch import score_document

    gt = {**CORR_STALE, "sender": "Phillip Allen"}
    pred = {"subject_matter": "Gas price update", "keywords": ["gas"], "intent": "update", "sender": "Phillip Allen"}
    block = score_archive_block("correspondence", pred, gt)
    doc = score_document("correspondence", pred, gt)
    assert block["overall_score"] == doc["overall_extraction_score"] == 1.0
    assert block["extraction_f1"] == 1.0
    assert set(block.get("field_scores") or {}) <= {"sender"}


def test_archive_block_with_only_stale_labels_is_not_scored() -> None:
    """A corporate row whose labels are all stale has no truth for the block to count."""
    from llm_dojo_scoring.pipeline.archive import score_archive_block

    block = score_archive_block("corporate_record", {"intent": "compliance"}, CORP_STALE)
    assert block["status"] != "scored"
    assert block["extraction_f1"] is None


def test_stale_label_is_dropped_whatever_its_presence_code() -> None:
    """Review MINOR 4: a ``pending_annotation`` code does not keep a heuristic intent scored."""
    gt = {"intent": "notice", "intent_source": "heuristic", "sender": "A",
          "gt_presence": {"intent": "pending_annotation"}}
    _, expected = scope_extraction_pair("correspondence", {}, gt)
    assert expected == {"sender": "A"}


def test_result_shares_no_objects_with_the_overlay() -> None:
    """Review MINOR 5: editing the merged gold never edits the overlay record."""
    near = _rec({"additional_recipients": {"value": ["a", "b"], "basis": "near_gold:two_pass_agree"}})
    merged = apply_label_overlays({}, doc_class="correspondence", doc_text=TEXT, near_gold=near)
    merged.fields["additional_recipients"].append("z")
    assert near["labels"]["additional_recipients"]["value"] == ["a", "b"]


def test_malformed_records_are_reported_not_raised() -> None:
    """A broken overlay file cannot take scoring down; it is reported."""
    bad_labels = apply_label_overlays({}, doc_class="correspondence", doc_text=TEXT,
                                      interim={**_rec({}), "labels": ["sender"]})
    bad_label = apply_label_overlays({}, doc_class="correspondence", doc_text=TEXT,
                                     interim=_rec({"sender": "Phillip Allen"}),
                                     near_gold=_rec({"recipient": "John"}))
    assert bad_labels.sources == {} and "malformed" in bad_labels.report["rejected"][0]
    assert bad_label.sources == {}
    assert bad_label.report["rejected"] == ["sender: malformed label", "recipient: basis '' is not near_gold"]


def test_dict_repr_gt_string_is_read_and_garbage_stays_loud() -> None:
    """GT text is parsed like Hub ``gt_fields``; unreadable GT still raises."""
    fields, dropped = drop_stale_hub_labels("correspondence", str({**CORR_STALE, "sender": "A"}))
    assert fields == {"intent_source": "heuristic", "sender": "A"} and len(dropped) == 3
    with pytest.raises(ValueError):
        drop_stale_hub_labels("correspondence", "not json at all {")


def test_enum_label_is_stored_as_the_scored_token() -> None:
    """A padded or upper-case enum value is admitted and stored canonical."""
    merged = apply_label_overlays({}, doc_class="correspondence", doc_text=TEXT,
                                  interim=_rec({"urgency": _lab(" URGENT ")}))
    assert merged.fields["urgency"] == "urgent"
