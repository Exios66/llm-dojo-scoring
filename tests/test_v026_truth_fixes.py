"""v0.26.0 truth fixes found by the sandbox extraction-gate vetting.

- CUAD ``Parties``: an annotated legal name is right when its core is a span.
- CUAD ``Effective Date``: the Agreement Date stands in when CUAD labels none.
- CMS rows: the source table is scored as its own field, orthogonal to ``claim_type`` (#93).
"""
from __future__ import annotations

import json

from llm_dojo_scoring.schemas.corpus import CMS_SOURCE_TABLES, cms_source_table
import pytest

from llm_dojo_scoring.scoring.field_scoring import score_extraction
from llm_dojo_scoring.pipeline.sandbox_scoring import (
    effective_from_agreement,
    field_value_ok,
    party_core,
    score_cuad,
)


def _labels(**cats):
    """Encode CUAD category spans as the Hub's ``cuad_clause_labels`` JSON."""
    return json.dumps({k: [{"text": t} for t in v] for k, v in cats.items()})


SPANS = _labels(**{"Parties": ["Seller", "NMS COMMUNICATIONS CORP.", "Backhaul", "VERSO BACKHAUL SOLUTIONS, INC."],
                   "Effective Date": [], "Agreement Date": ["December 20, 2007"]})


def test_party_core_strips_defined_terms():
    """Defined-term annotations are not part of a party name."""
    assert party_core('NMS COMMUNICATIONS CORP. ("Seller")') == "nms communications corp"
    assert party_core("Acme “Buyer”") == "acme"


def test_annotated_legal_names_are_right():
    """Annotated legal names that are CUAD Parties spans score right."""
    names = ['NMS COMMUNICATIONS CORP. ("Seller")', "Verso Backhaul Solutions, Inc. (\"Backhaul\")"]
    assert field_value_ok("parties", names, SPANS) is True
    assert field_value_ok("parties", ["NMS COMMUNICATIONS CORP.", "Someone Else LLC"], SPANS) is False
    out = score_cuad({"parties": names}, SPANS)
    assert (out["cuad_value_checked"], out["cuad_value_correct"]) == (1, 1)


def test_effective_date_falls_back_to_agreement_date():
    """The Agreement Date stands in only when CUAD labels no Effective Date."""
    gt = {"Effective Date": [], "Agreement Date": ["December 20, 2007"]}
    assert effective_from_agreement("2007-12-20", gt)
    assert not effective_from_agreement("2008-01-01", gt)
    assert not effective_from_agreement("2007-12-20", {**gt, "Effective Date": ["January 1, 2008"]})
    assert field_value_ok("effective_date", "2007-12-20", SPANS) is True
    assert field_value_ok("effective_date", "2008-01-01", SPANS) is False
    assert field_value_ok("effective_date", None, SPANS) is True  # nothing labelled, nothing claimed
    assert field_value_ok("governing_law", "Delaware", SPANS) is None  # category not in the universe


def test_agreement_date_effective_date_is_not_a_false_positive():
    """That effective date is not a presence false positive."""
    right = score_cuad({"effective_date": "2007-12-20"}, SPANS)
    wrong = score_cuad({"effective_date": "2008-01-01"}, SPANS)
    assert right["cuad_fp"] == 0 and right["cuad_effective_from_agreement"] == 1
    assert wrong["cuad_fp"] == 1 and wrong["cuad_effective_from_agreement"] == 0


def test_cms_mapping_is_one_table():
    """One table maps each CMS source table to claim type, subclass and intent."""
    assert set(CMS_SOURCE_TABLES) == {"carrier", "inpatient", "outpatient", "pde"}
    assert all(v["claim_type"] == "health" and v["intent"] == "claim_data_record" for v in CMS_SOURCE_TABLES.values())
    assert cms_source_table("insurance_claim", "Carrier") == "carrier"
    assert cms_source_table("insurance_claim", "property") is None
    assert cms_source_table("contract", "carrier") is None


def test_cms_source_table_is_scored_orthogonally():
    """The source table is scored apart from ``claim_type``."""
    exp = {"claim_type": "health", "cms_source_table": "carrier"}
    # #93: claim_type scores the product line only; the table its own field.
    right = score_extraction("insurance_claim", {}, {"claim_type": "carrier"}, exp)
    assert right.field_scores == {"claim_type": 0.0, "cms_source_table": 1.0}
    both = score_extraction(
        "insurance_claim", {}, {"claim_type": "health", "cms_source_table": "carrier"}, exp
    )
    assert both.field_scores == {"claim_type": 1.0, "cms_source_table": 1.0}
    wrong = score_extraction("insurance_claim", {}, {"claim_type": "outpatient"}, exp)
    assert wrong.field_scores == {"claim_type": 0.0, "cms_source_table": 0.0}
    health = score_extraction("insurance_claim", {}, {"claim_type": "health"}, exp)
    assert health.field_scores == {"claim_type": 1.0, "cms_source_table": 0.0}
    # A non-CMS row (no cms_source_table expectation) keeps generic name scoring.
    plain = score_extraction("insurance_claim", {}, {"claim_type": "auto"}, {"claim_type": "auto"})
    assert plain.field_scores == {"claim_type": 1.0}


def test_blank_or_null_source_table_falls_back_to_claim_type():
    """An empty or null-token table field does not hide the table reported on claim_type."""
    exp = {"claim_type": "health", "cms_source_table": "carrier"}
    for blank in ("", "null", "  ", None):
        out = score_extraction("insurance_claim", {}, {"claim_type": "carrier", "cms_source_table": blank}, exp)
        assert out.field_scores["cms_source_table"] == 1.0, blank
    stated = score_extraction("insurance_claim", {}, {"claim_type": "carrier", "cms_source_table": "inpatient"}, exp)
    assert stated.field_scores["cms_source_table"] == 0.0  # a stated table is scored as stated


def test_parenthetical_that_is_part_of_the_name_still_matches():
    """``ACME (US) LLC`` matches its span as written; the stripped core is tried first."""
    spans = _labels(Parties=["ACME (US) LLC", "Beta Inc."])
    assert field_value_ok("parties", ["ACME (US) LLC", 'Beta Inc. ("Buyer")'], spans) is True
    assert field_value_ok("parties", ["ACME (UK) LLC"], spans) is False


def test_qualifiers_are_kept_and_names_never_span_two_entries():
    """``(UK)`` is not a defined term, and a name must lie within one span."""
    assert party_core("ACME (US) LLC") == "acme us llc"
    spans = _labels(Parties=["ACME LLC", "ACME (US) LLC"])
    assert field_value_ok("parties", ["ACME (UK) LLC"], spans) is False
    assert field_value_ok("parties", ['ACME (US) LLC ("Buyer")'], spans) is True
    split = _labels(Parties=["ACME (US)", "Holdings LLC"])
    assert field_value_ok("parties", ["ACME (US) Holdings LLC"], split) is False



# --- #93 CMS insurance mapping ---------------------------------------------

_CMS_GT = {
    "claim_type": "health",
    "claim_number": "887013387879564",
    "adjuster": "",
    "denial_reasons": "",
    "supporting_documents": '["provider NPI 5040521237", "HCPCS detail (1 codes)"]',
}


def test_suite_derives_cms_source_table_from_the_subclass():
    """CMS rows get the table from expected_subclass; non-CMS subclasses never do."""
    from llm_dojo_scoring import get_suite

    suite = get_suite("insurance_claims_specialist")
    pred = {**_CMS_GT, "cms_source_table": "carrier"}
    cms = suite.score_document(dict(_CMS_GT), pred, expected_subclass="carrier")
    fields = cms["extraction"].field_scores
    assert fields["cms_source_table"] == 1.0
    auto = suite.score_document(dict(_CMS_GT), pred, expected_subclass="auto")
    auto_fields = auto["extraction"].field_scores
    assert "cms_source_table" not in auto_fields


def test_documented_absent_fields_are_strict_on_cms_rows_only():
    """A stated adjuster is a false positive on a CMS row and skipped elsewhere."""
    exp_cms = {"claim_type": "health", "cms_source_table": "pde", "adjuster": "", "denial_reasons": ""}
    stated = score_extraction("insurance_claim", {}, {"claim_type": "health", "cms_source_table": "pde",
                                                      "adjuster": "JOHN D.", "denial_reasons": ["late"]}, exp_cms)
    assert stated.field_scores["adjuster"] == 0.0
    assert stated.field_scores["denial_reasons"] == 0.0
    silent = score_extraction("insurance_claim", {}, {"claim_type": "health", "cms_source_table": "pde"}, exp_cms)
    assert silent.field_scores["adjuster"] == 1.0
    non_cms = score_extraction("insurance_claim", {}, {"claim_type": "auto", "adjuster": "JOHN D."},
                               {"claim_type": "auto", "adjuster": ""})
    assert "adjuster" not in non_cms.field_scores


@pytest.mark.parametrize(
    ("pred", "exp", "score"),
    [
        ("NPI 5040521237", "provider NPI 5040521237", 1.0),
        ("provider NPI 5040521238", "provider NPI 5040521237", 0.0),
        ("NDC 00703-0510-02", "NDC 00703051002", 1.0),
        ("NDC 00703051003", "NDC 00703051002", 0.0),
        ("facility provider 4500PK", "facility provider 4500PK", 1.0),
        ("HCPCS detail (3 codes)", "HCPCS detail (1 codes)", 1.0),
        ("invoice", "provider NPI 5040521237", 0.0),
    ],
)
def test_cms_supporting_documents_match_by_identifier(pred, exp, score):
    """Identifiers match exactly by kind; descriptors by type label; prose never."""
    from llm_dojo_scoring.scoring.field_scoring import score_cms_doc_ref

    assert score_cms_doc_ref(pred, exp) == score


# --- PR #106 adversarial review regressions --------------------------------


@pytest.mark.parametrize("token", ["pde", "inpatient", "outpatient", "carrier"])
def test_table_token_on_claim_type_scores_zero_without_cms_detection(token):
    """No expected_subclass / table key: a table token still earns no fuzzy credit."""
    out = score_extraction("insurance_claim", {"claim_type": "name"}, {"claim_type": token},
                           {"claim_type": "health"})
    assert out.field_scores["claim_type"] == 0.0


@pytest.mark.parametrize("pred", [None, {}])
def test_null_prediction_earns_no_documented_absent_credit(pred):
    """A missing or unparseable prediction must not collect credit for silence."""
    exp = {"claim_type": "health", "cms_source_table": "carrier", "adjuster": "", "denial_reasons": ""}
    out = score_extraction("insurance_claim", {}, pred, exp)
    assert "adjuster" not in out.field_scores
    assert "denial_reasons" not in out.field_scores


def test_blank_items_in_denial_reasons_count_as_empty():
    """``[""]`` / ``[None]`` are silence, not a stated reason."""
    exp = {"claim_type": "health", "cms_source_table": "pde", "denial_reasons": ""}
    for blank in ([""], [None], ["  "]):
        out = score_extraction("insurance_claim", {}, {"claim_type": "health", "denial_reasons": blank}, exp)
        assert out.field_scores["denial_reasons"] == 1.0, blank


def test_auditor_does_not_apply_cms_rules_to_a_specialist_reference():
    """The auditor compares two model outputs; CMS GT rules must not apply."""
    from llm_dojo_scoring import get_suite

    reference = {"claim_type": "health", "cms_source_table": "carrier", "adjuster": None, "denial_reasons": []}
    auditor = {"claim_type": "health", "cms_source_table": "carrier", "adjuster": "J Smith", "denial_reasons": []}
    out = get_suite("insurance_claims_auditor").score(reference, auditor)
    assert "adjuster" not in out["extraction"].field_scores
    assert out["audit_disagreement_rate"] == 0.0


@pytest.mark.parametrize(
    ("pred", "exp", "score"),
    [
        ("facility provider identifier 0505ZK", "facility provider 0505ZK", 1.0),
        ("facility provider id: 0505ZK", "facility provider 0505ZK", 1.0),
        ("facility provider id", "facility provider 0505ZK", 0.0),
    ],
)
def test_facility_id_requires_a_digit_bearing_token(pred, exp, score):
    """Filler words (id / identifier / number) are never captured as the id."""
    from llm_dojo_scoring.scoring.field_scoring import score_cms_doc_ref

    assert score_cms_doc_ref(pred, exp) == score
