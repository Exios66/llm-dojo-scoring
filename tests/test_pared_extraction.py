"""Pared extraction field maps (mailroom v0.6.0) — network-free."""

from __future__ import annotations

from llm_dojo_scoring import (
    DEFAULT_FIELD_TYPES,
    LEGACY_FULL_EXTRACTION_FIELD_TYPES,
    get_suite,
)
from llm_dojo_scoring.corpus import CORPUS_EXTRACTION_FIELDS
from llm_dojo_scoring.config import FieldScoringSettings


# Live mailroom extract classes after the obligation-dump retirement.
_PARED_LIVE = (
    "contract",
    "merger_agreement",
    "corporate_record",
    "correspondence",
    "compliance_filing",
    "insurance_claim",
)

_RETIRED_OBLIGATION_FIELDS = {
    "key_obligations",
    "termination_clauses",
    "key_provisions",
    "key_points",
    "referenced_communications",
}


def test_default_field_types_drop_open_ended_obligation_dumps():
    for doc_type in _PARED_LIVE:
        fields = set(DEFAULT_FIELD_TYPES[doc_type])
        leaked = fields & _RETIRED_OBLIGATION_FIELDS
        assert not leaked, f"{doc_type} still scores retired fields: {leaked}"


def test_default_field_types_match_corpus_and_mailroom_pared_schema():
    assert set(DEFAULT_FIELD_TYPES["contract"]) == set(CORPUS_EXTRACTION_FIELDS["contract"])
    assert "cuad_clauses" in DEFAULT_FIELD_TYPES["contract"]
    assert "intent" in DEFAULT_FIELD_TYPES["correspondence"]
    assert "subject_matter" in DEFAULT_FIELD_TYPES["corporate_record"]
    assert "keywords" in DEFAULT_FIELD_TYPES["insurance_claim"]
    assert "claim_checklist" in DEFAULT_FIELD_TYPES["insurance_claim"]
    assert DEFAULT_FIELD_TYPES["contract"] == DEFAULT_FIELD_TYPES["merger_agreement"]


def test_legacy_full_map_keeps_key_obligations_for_historical_rescoring():
    assert "key_obligations" in LEGACY_FULL_EXTRACTION_FIELD_TYPES["contract"]
    assert "termination_clauses" in LEGACY_FULL_EXTRACTION_FIELD_TYPES["contract"]
    assert "key_points" in LEGACY_FULL_EXTRACTION_FIELD_TYPES["correspondence"]
    assert "key_provisions" in LEGACY_FULL_EXTRACTION_FIELD_TYPES["corporate_record"]


def test_suite_score_emits_category_presence_from_kwargs():
    suite = get_suite("contracts_specialist")
    predicted = {
        "parties": ["Acme Corp"],
        "cuad_clauses": ["Anti-Assignment: shall not assign without consent"],
    }
    expected = {
        "parties": ["Acme Corp"],
        "cuad_clauses": ["Anti-Assignment: shall not assign without consent"],
    }
    presence = {
        "Anti-Assignment": {
            "expected": True,
            "answer": "shall not assign without consent",
            "field": "cuad_clauses",
        },
        "Governing Law": {"expected": False, "answer": "", "field": "cuad_clauses"},
    }
    out = suite.score(expected, predicted, presence_expectations=presence)
    assert isinstance(out, dict)
    assert out["extraction_category_presence"] == 1.0
    assert out["extraction"].overall_score == 1.0


def test_partial_gt_defaults_prefer_checklists():
    settings = FieldScoringSettings()
    assert "cuad_clauses" in settings.partial_gt_fields
    assert "claim_checklist" in settings.partial_gt_fields
    assert "key_obligations" not in settings.partial_gt_fields
    assert "subject_matter" in settings.containment_fields
