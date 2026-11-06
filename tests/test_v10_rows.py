"""mailroom-dataset v10 alignment (0.28.0, Mailroom-Corpus-EDA plan G1).

The typed ``gt_<class>`` rows must score exactly like the legacy ``ground_truth`` row
they came from; the contract headline can reach ``full``; ``not_applicable`` has one
meaning for corporate records; closed labels score by exact match.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import llm_dojo_scoring as dojo
from llm_dojo_scoring.metrics.scorecard_honesty import headline_scope
from llm_dojo_scoring.schemas.corporate_record_schema import align_unlabeled, unlabeled_fields
from llm_dojo_scoring.schemas.gt_metadata import ANNOTATION_KEYS, scoring_gt_fields
from llm_dojo_scoring.schemas.v10_rows import (
    coverage_report,
    cuad_labels_from_long,
    gt_from_v10_row,
    maud_labels_from_long,
)
from llm_dojo_scoring.scoring.field_scoring import score_extraction
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

#: A legacy (v9 ``ground_truth``) contract row and the v10 ``gt_contract`` row
#: ``v10_build.class_record`` makes from it.
LEGACY_CONTRACT = {
    "document_name": "License Agreement",
    "parties": json.dumps(["Acme Technologies, Inc.", "Beta LLC"]),
    "effective_date": "2019-03-01",
    "governing_law": "This Agreement is governed by the laws of the State of New York.",
    "contract_value": "$2,000,000",
    "cuad_family": "license",
    "cuad_clause_labels": json.dumps({"License Grant": [{"start": 10, "text": "grants a license"}]}),
    "gt_presence": json.dumps({
        "document_name": "populated", "parties": "populated", "effective_date": "populated",
        "governing_law": "populated", "contract_value": "populated", "cuad_family": "populated",
        "cuad_clause_labels": "populated", "term_length": "schema_documented_absence",
        "renewal_terms": "pending_annotation",
    }),
    "expected_subclass": "License_Agreements",
}
V10_CONTRACT = {
    "document_id": "DOC-0123456789abcdef", "filename": "x.pdf", "subclass": "license",
    "source_subclass": "License_Agreements", "content_sha256": "a", "source_content_sha256": "a",
    "document_name": "License Agreement",
    "parties": np.array(["Acme Technologies, Inc.", "Beta LLC"]),
    "party_roles": None,
    "effective_date": "2019-03-01",
    "term_length": None,
    "renewal_terms": None,
    "governing_law": "This Agreement is governed by the laws of the State of New York.",
    "contract_value": 2000000.0,
    "cuad_family": "license",
    "cuad_clauses": [{"category": "License Grant", "start": 10, "end": 26, "text": "grants a license"}],
    "presence": {
        "document_name": "populated", "parties": "populated", "party_roles": None,
        "effective_date": "populated", "governing_law": "populated", "contract_value": "populated",
        "cuad_family": "populated", "cuad_clauses": "populated",
        "term_length": "schema_documented_absence", "renewal_terms": "pending_annotation",
    },
    "evidence": {"document_name": [{"start": 0, "end": 17, "text": "License Agreement"}]},
    "provenance": {"document_name": "gold:cuad", "subclass": "source"},
}

PREDICTED = {
    "document_name": "License Agreement",
    "parties": ["Acme Technologies, Inc.", "Beta LLC"],
    "effective_date": "2019-03-01",
    "governing_law": "governed by the laws of the State of New York",
    "contract_value": "$2,000,000",
    "cuad_family": "License_Agreements",
    "renewal_terms": "auto-renews yearly",
}


def test_v10_row_maps_to_the_legacy_shape():
    """Typed values, legacy keys, presence codes (None dropped) and label support."""
    gt = gt_from_v10_row(V10_CONTRACT)
    assert gt["parties"] == ["Acme Technologies, Inc.", "Beta LLC"]  # numpy -> list
    assert gt["cuad_clause_labels"] == {"License Grant": [{"start": 10, "text": "grants a license"}]}
    assert "cuad_clauses" not in gt and "party_roles" not in gt
    assert gt["gt_presence"]["cuad_clause_labels"] == "populated"
    assert "party_roles" not in gt["gt_presence"]
    assert gt["expected_subclass"] == "License_Agreements"
    assert gt["evidence"]["document_name"][0]["text"] == "License Agreement"
    assert {"evidence", "provenance"} <= ANNOTATION_KEYS
    assert not set(gt) & {"document_id", "filename", "subclass", "content_sha256"}
    with pytest.raises(TypeError):
        gt_from_v10_row(["not", "a", "row"])  # type: ignore[arg-type]


def test_v10_row_scores_like_the_legacy_row():
    """Through ``scoring_gt_fields`` + the suite, both shapes give identical scores."""
    types = DEFAULT_FIELD_TYPES["contract"]
    results = []
    for raw in (LEGACY_CONTRACT, gt_from_v10_row(V10_CONTRACT)):
        expected = scoring_gt_fields(raw, field_types=types, doc_type="contract")
        results.append(score_extraction("contract", types, PREDICTED, expected))
    legacy, v10 = results
    assert legacy.field_scores == v10.field_scores
    assert legacy.overall_score == v10.overall_score
    assert "renewal_terms" not in v10.field_scores  # pending_annotation never scores
    assert v10.field_scores["cuad_family"] == 1.0  # surface folds onto the label


def test_long_tables_pivot_to_label_maps():
    """``cuad_clauses`` / ``maud_answers`` long configs pivot back per document."""
    cuad = cuad_labels_from_long([
        {"document_id": "D1", "category": "Parties", "start": 0, "end": 4, "text": "Acme"},
        {"document_id": "D1", "category": "Parties", "start": 9, "end": 13, "text": "Beta"},
        {"document_id": "D2", "category": "Governing Law", "start": 5, "end": 9, "text": "N.Y."},
        {"document_id": None, "category": "Parties", "start": 0, "end": 1, "text": "x"},
    ])
    assert cuad["D1"] == {"Parties": [{"start": 0, "text": "Acme"}, {"start": 9, "text": "Beta"}]}
    assert set(cuad) == {"D1", "D2"}
    maud = maud_labels_from_long([
        {"document_id": "M1", "question": "Type of Consideration", "category": "General Information",
         "answer": "All Cash"},
    ])
    assert maud == {"M1": {"Type of Consideration": {"category": "General Information", "answer": "All Cash"}}}


def test_coverage_report_counts_presence_per_field():
    """Coverage is labeled / applicable; ``not_applicable`` leaves the denominator."""
    rows = [
        {"presence": {"a": "populated", "b": "not_applicable", "c": "pending_annotation"}},
        {"presence": {"a": "schema_documented_absence", "b": "populated", "c": None}},
    ]
    report = coverage_report(rows)
    assert report["a"]["coverage"] == 1.0
    assert report["b"]["applicable"] == 1 and report["b"]["coverage"] == 1.0
    assert report["c"]["pending_annotation"] == 1 and report["c"]["missing"] == 1
    assert report["c"]["coverage"] == 0.0


def test_package_root_exports_the_adapter():
    """Consumers (sandbox ``corpus.py``) import the adapter from the root."""
    assert dojo.gt_from_v10_row is gt_from_v10_row
    assert dojo.v10_coverage_report is coverage_report
    assert dojo.V10_GT_CONFIGS["contract"] == "gt_contract"


def test_contract_headline_can_reach_full():
    """With the parse-compat merger keys gone, every live contract field can carry GT."""
    scope = headline_scope("contract", {f: 1 for f in DEFAULT_FIELD_TYPES["contract"]})
    assert scope["headline_scope"] == "full"
    assert not {"merger_consideration", "maud_clauses"} & set(DEFAULT_FIELD_TYPES["contract"])


def test_contract_parse_compat_keys_are_not_scored_or_extra():
    """A v1 contract prediction still parses; its merger keys are neither scored nor extra."""
    expected = {"document_name": "MSA", "cuad_family": "license"}
    predicted = {**expected, "merger_consideration": "all_cash", "maud_clauses": ["x: y"]}
    doc = dojo.score_document("contract", predicted, expected)
    assert doc["extra_schema_keys"] == []
    assert doc["extraction_precision"] == 1.0  # the merger keys are no false positives


@pytest.mark.parametrize(
    ("doc_type", "field", "gold", "pred", "score"),
    [
        ("correspondence", "communication_type", "attorney_demand", "demand", 0.0),
        ("correspondence", "communication_type", "attorney_demand", "Attorney Demand", 1.0),
        ("correspondence", "urgency", "time-sensitive", "time sensitive", 1.0),
        ("insurance_claim", "coverage_determination", "approved", "approved (amended)", 0.0),
        ("insurance_claim", "coverage_determination", "partial", "Partially approved", 1.0),
        ("merger_agreement", "merger_consideration", "all_stock", "All Stock", 1.0),
        ("merger_agreement", "intent", "effect_merger", "plan_of_merger", 1.0),
        ("merger_agreement", "intent", "effect_merger", "amend_merger", 0.0),
        ("contract", "cuad_family", "license", "License Agreement", 1.0),
        ("contract", "cuad_family", "license", "licence-ish", 0.0),
    ],
)
def test_closed_labels_score_by_exact_match_after_folding(doc_type, field, gold, pred, score):
    """No containment credit on closed labels (``demand`` used to match ``attorney_demand``)."""
    types = DEFAULT_FIELD_TYPES[doc_type]
    result = score_extraction(doc_type, types, {field: pred}, {field: gold})
    assert result.field_scores[field] == score


def test_corporate_not_applicable_is_never_a_scoring_event():
    """``not_applicable`` is neither unlabeled nor expected-empty; it leaves both sides."""
    gt = {"entity_name": "Acme", "gt_presence": json.dumps({
        "entity_name": "populated", "jurisdiction": "not_applicable", "filing_number": "pending_annotation",
    })}
    unl = unlabeled_fields("bylaws", gt)
    assert "jurisdiction" not in unl and "filing_number" in unl
    expected = {"entity_name": "Acme", "jurisdiction": ""}
    predicted = {"entity_name": "Acme", "jurisdiction": "Delaware"}
    exp, pred, dropped = align_unlabeled("bylaws", gt, expected, predicted)
    assert "jurisdiction" not in exp and "jurisdiction" not in pred
    assert "jurisdiction" not in dropped


def test_pandas_missing_cells_are_absent():
    """``pandas.NA`` / ``NaT`` cells are missing values, never GT values."""
    import pandas as pd

    gt = gt_from_v10_row({**V10_CONTRACT, "term_length": pd.NA, "agreement_date": pd.NaT})
    assert "term_length" not in gt and "agreement_date" not in gt


def test_coverage_report_lists_requested_fields_with_no_codes():
    """A field no row codes still appears (all missing) when it is requested."""
    report = coverage_report([{"presence": {"a": "populated"}}], fields=["a", "b"])
    assert report["b"]["missing"] == 1 and report["b"]["coverage"] == 0.0


def test_merger_outside_date_schema_admits_a_relative_date():
    """``outside_date`` is ISO when stated as a date, else as printed."""
    from llm_dojo_scoring.schemas.maud_schema import maud_json_schema

    prop = maud_json_schema("object")["properties"]["outside_date"]
    assert prop == {"type": ["string", "null"]}
    assert "pattern" in maud_json_schema("object")["properties"]["effective_date"]


def test_contract_parse_compat_keys_survive_a_producer_schema_lookup():
    """A v2 producer model without the v1 keys still does not flag them as extra."""
    from llm_dojo_scoring.pipeline.sandbox_schema_adherence import schema_keys_for

    class _Model:
        """A stand-in producer model that lists only v2 keys."""

        model_fields = {"document_name": None, "cuad_family": None}

    keys = schema_keys_for("contract", schema_lookup=lambda _name: _Model)
    assert {"merger_consideration", "maud_clauses"} <= keys


def test_cuad_family_other_is_a_scored_token():
    """``other`` is a CUAD family (the guided schema allows it), so hints teach it."""
    from llm_dojo_scoring.schemas.cuad_schema import CUAD_FAMILY_KEYS
    from llm_dojo_scoring.schemas.scored_enums import scored_vocabulary

    assert scored_vocabulary("contract", "cuad_family") == CUAD_FAMILY_KEYS
