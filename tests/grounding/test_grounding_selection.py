"""Which predicted fields the grounding pass audits (spec §6.2, owner decision §10.1)."""

from __future__ import annotations

import pytest
from grounding_inputs import hub_row, with_presence

from llm_dojo_scoring.grounding.selection import UNLABELLED_STATUSES, unlabelled_fields

INSURANCE = {"insurer": "Acme Holdings", "claim_number": "AB-12/34", "adjuster": "Robin Example"}


def test_real_hub_row_with_blank_columns_selects_nothing():
    """A blank column with no presence status is labelled empty: the headline judges it."""
    assert unlabelled_fields(hub_row(), INSURANCE, doc_class="insurance_claim") == {}


def test_pending_annotation_is_selected_as_pending():
    """Pending annotation is selected as pending."""
    gt = with_presence(hub_row(), "insurer", "pending_annotation")
    assert unlabelled_fields(gt, INSURANCE, doc_class="insurance_claim") == {
        "insurer": "pending_annotation"
    }


def test_key_missing_from_gt_is_selected_as_absent():
    """Key missing from gt is selected as absent."""
    gt = {"claim_number": "AB-12/34"}
    assert unlabelled_fields(gt, INSURANCE, doc_class="insurance_claim") == {
        "insurer": "absent", "adjuster": "absent",
    }


@pytest.mark.parametrize("status", ["not_applicable", "schema_documented_absence"])
def test_labelled_empty_statuses_are_not_selected(status):
    """Labelled empty statuses are not selected."""
    gt = with_presence(hub_row(), "insurer", status)
    assert unlabelled_fields(gt, INSURANCE, doc_class="insurance_claim") == {}


def test_labelled_value_is_not_selected():
    """Labelled value is not selected."""
    gt = {"insurer": "Other Insurer", "claim_number": "X", "adjuster": "Y"}
    assert unlabelled_fields(gt, INSURANCE, doc_class="insurance_claim") == {}


@pytest.mark.parametrize(("field", "value"), [
    ("adjuster", "Robin Example"), ("denial_reasons", ["late filing"]),
])
def test_cms_documented_absent_fields_never_selected(field, value):
    """A CMS row's adjuster / denial_reasons are labelled empty by the CMS source schema."""
    gt = with_presence(hub_row(claim_type="health"), field, "pending_annotation")
    predicted = {field: value}
    assert unlabelled_fields(gt, predicted, doc_class="insurance_claim", doc_subclass="carrier") == {}
    non_cms = with_presence(hub_row(claim_type="carrier"), field, "pending_annotation")
    assert unlabelled_fields(non_cms, predicted, doc_class="insurance_claim") == {
        field: "pending_annotation"
    }


@pytest.mark.parametrize("empty", ["", None, [], "[]", "  "])
def test_empty_predictions_and_off_schema_keys_not_selected(empty):
    """Empty predictions and off schema keys not selected."""
    predicted = {"insurer": empty, "invented_field": "Acme Holdings"}
    assert unlabelled_fields({}, predicted, doc_class="insurance_claim") == {}


def test_unknown_doc_class_raises_key_error():
    """Unknown doc class raises key error."""
    with pytest.raises(KeyError):
        unlabelled_fields({}, {"insurer": "Acme"}, doc_class="not_a_class")


def test_statuses_constant():
    """Statuses constant."""
    assert UNLABELLED_STATUSES == ("absent", "pending_annotation")


def test_carried_cms_table_without_subclass_is_a_cms_row():
    """A GT row that carries cms_source_table is CMS for the headline, so here too."""
    gt = {"cms_source_table": "carrier", "claim_number": "1"}
    predicted = {"adjuster": "Bob", "denial_reasons": ["x"], "insurer": "Acme"}
    assert unlabelled_fields(gt, predicted, doc_class="insurance_claim") == {"insurer": "absent"}


def test_cms_subclass_with_non_health_claim_type_is_not_a_cms_row():
    """The headline treats a non-health row as non-CMS, so adjuster stays auditable."""
    gt = with_presence(hub_row(claim_type="property"), "adjuster", "pending_annotation")
    assert unlabelled_fields(gt, {"adjuster": "Bob"}, doc_class="insurance_claim",
                             doc_subclass="carrier") == {"adjuster": "pending_annotation"}


@pytest.mark.parametrize("predicted", [None, ["a"], "insurer"])
def test_non_mapping_prediction_raises_type_error(predicted):
    """A prediction that is not a field mapping fails loudly with a clear message."""
    with pytest.raises(TypeError, match="mapping"):
        unlabelled_fields({}, predicted, doc_class="insurance_claim")
