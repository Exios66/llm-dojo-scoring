"""v0.26.0 truth fixes found by the sandbox extraction-gate vetting.

- CUAD ``Parties``: an annotated legal name is right when its core is a span.
- CUAD ``Effective Date``: the Agreement Date stands in when CUAD labels none.
- CMS rows: the source table is scored as its own field, orthogonal to ``claim_type`` (#93).
"""
from __future__ import annotations

import json

from llm_dojo_scoring.corpus import CMS_SOURCE_TABLES, cms_source_table
from llm_dojo_scoring.field_scoring import score_extraction
from llm_dojo_scoring.sandbox_scoring import (
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
    right = score_extraction("insurance_claim", {}, {"claim_type": "carrier"}, exp)
    assert right.field_scores == {"claim_type": 1.0, "cms_source_table": 1.0}
    wrong = score_extraction("insurance_claim", {}, {"claim_type": "outpatient"}, exp)
    assert wrong.field_scores == {"claim_type": 1.0, "cms_source_table": 0.0}
    health = score_extraction("insurance_claim", {}, {"claim_type": "health"}, exp)
    assert health.field_scores == {"claim_type": 1.0, "cms_source_table": 0.0}
    # Without a cms_source_table expectation nothing changes.
    plain = score_extraction("insurance_claim", {}, {"claim_type": "carrier"}, {"claim_type": "health"})
    assert plain.field_scores == {"claim_type": 1.0}
