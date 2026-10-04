"""Archive scoring contract (mailroom-issues #236 / #237 / #238).

Network-free. One wrapper, one block per document; merger is
MergerAgreementExtraction, not a contract alias.
"""

from __future__ import annotations

import json

import pytest

from llm_dojo_scoring.archive import (
    ARCHIVE_SCORING_KEYS,
    ARCHIVE_SCORING_METHOD,
    LIVE_ARCHIVE_DOC_TYPES,
    archive_entry_hash,
    empty_archive_scoring_block,
    score_archive_block,
    upsert_archive_scoring,
)
from llm_dojo_scoring.mailroom import EXTRACT_CLASS_ALIASES, resolve_extract_class
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite


def _fill_schema(doc_class: str, values: dict) -> dict:
    out = {key: None for key in DEFAULT_FIELD_TYPES[doc_class]}
    out.update(values)
    return out


def test_empty_block_has_every_archivist_key():
    block = empty_archive_scoring_block()
    assert tuple(block) == ARCHIVE_SCORING_KEYS
    assert block["method"] == ARCHIVE_SCORING_METHOD
    assert block["field_scores"] == {}
    assert block["extraction_f1"] is None
    assert block["tp"] is None


def test_merger_is_not_scored_as_contract():
    assert EXTRACT_CLASS_ALIASES == {}
    assert resolve_extract_class("merger_agreement") == "merger_agreement"
    merger_map = DEFAULT_FIELD_TYPES["merger_agreement"]
    contract_map = DEFAULT_FIELD_TYPES["contract"]
    assert merger_map != contract_map
    assert "cuad_family" not in merger_map
    assert "cuad_clauses" not in merger_map
    assert "effective_time" in merger_map
    assert "intent" in merger_map
    assert "subject_matter" in merger_map
    assert "keywords" in merger_map
    assert get_suite("merger_agreement").name == "merger_agreement_specialist"
    assert get_suite("merger_agreement").doc_type == "merger_agreement"


def test_score_archive_block_rejects_contract_alias_for_merger():
    """#238: a test fails if the contract alias is used."""
    expected = _fill_schema(
        "merger_agreement",
        {
            "document_name": "Agreement and Plan of Merger",
            "parties": ["Parent Inc.", "Merger Sub LLC"],
            "effective_time": "10:00 a.m. Eastern Time",
            "intent": "acquire",
            "subject_matter": "all-cash merger",
            "keywords": ["merger", "all_cash"],
        },
    )
    predicted = dict(expected)
    # Contract-shaped extras must be ignored, not scored as CUAD.
    predicted["cuad_family"] = "other"
    predicted["cuad_clauses"] = ["Anti-Assignment: shall not assign"]
    predicted["confidence"] = 0.99
    predicted["reasoning"] = {"summary": "trace"}

    block = score_archive_block("merger_agreement", predicted, expected)
    assert "cuad_family" not in block["field_scores"]
    assert "cuad_clauses" not in block["field_scores"]
    assert "confidence" not in block["field_scores"]
    assert "reasoning" not in block["field_scores"]
    assert "effective_time" in block["field_scores"]
    assert block["overall_score"] == 1.0
    assert block["method"] == ARCHIVE_SCORING_METHOD
    assert block["field_map"] == "taxonomy.yaml"
    assert block["field_map_sha"]
    assert block["schema_valid"] is True


@pytest.mark.parametrize("doc_class", LIVE_ARCHIVE_DOC_TYPES)
def test_score_archive_block_covers_live_classes(doc_class):
    field_map = DEFAULT_FIELD_TYPES[doc_class]
    first = next(iter(field_map))
    expected = _fill_schema(doc_class, {first: "Acme"})
    predicted = _fill_schema(doc_class, {first: "Acme"})
    block = score_archive_block(doc_class, predicted, expected)
    assert tuple(block) == ARCHIVE_SCORING_KEYS
    assert block["n_fields_scored"] == 1
    assert first in block["field_scores"]
    assert block["extraction_f1"] is not None
    assert block["tp"] == 1
    assert block["fn"] == 0


def test_f1_null_when_no_countable_events():
    expected = _fill_schema("corporate_record", {"adjuster": None})
    # corporate_record has no adjuster — all live keys empty
    expected = {key: None for key in DEFAULT_FIELD_TYPES["corporate_record"]}
    predicted = dict(expected)
    predicted["confidence"] = 0.4
    block = score_archive_block("corporate_record", predicted, expected)
    assert block["overall_score"] is None
    assert block["n_fields_scored"] == 0
    assert block["extraction_f1"] is None
    assert block["extraction_f2"] is None
    assert block["tp"] is None
    assert block["fp"] is None
    assert block["fn"] is None


def test_f1_not_derived_from_overall_and_not_overwritten_by_cuad_method():
    expected = _fill_schema(
        "contract",
        {
            "document_name": "MSA",
            "parties": ["Acme"],
            "effective_date": "2024-03-03",
            "governing_law": "Delaware",
        },
    )
    predicted = dict(expected)
    predicted["effective_date"] = "2024-03-01"  # 0.67 — not TP
    block = score_archive_block(
        "contract",
        predicted,
        expected,
        method="extraction_category_presence",
    )
    assert block["method"] == "cuad.clause_presence.micro_f1"
    assert block["overall_score"] != block["extraction_f1"]
    assert block["extraction_f1"] < 1.0
    assert block["fn"] == 1
    assert block["tp"] == 3


def test_one_block_per_document_second_score_replaces_row():
    expected = _fill_schema("correspondence", {"sender": "Pat", "recipient": "Alex"})
    predicted = dict(expected)
    first = score_archive_block("correspondence", predicted, expected)
    log: dict[str, dict] = {}
    row = upsert_archive_scoring(
        log,
        "doc_example",
        first,
        detail={"pipeline_success": True, "stage": "archived"},
    )
    assert list(log) == ["doc_example"]
    assert row["detail"]["scoring"] == first
    assert row["event"] == "archived"

    predicted["sender"] = "Patricia"
    second = score_archive_block("correspondence", predicted, expected)
    upsert_archive_scoring(log, "doc_example", second)
    assert list(log) == ["doc_example"]
    assert log["doc_example"]["detail"]["scoring"] == second
    assert log["doc_example"]["detail"]["scoring"] != first


def test_failed_extraction_still_files_the_block():
    expected = _fill_schema(
        "insurance_claim",
        {"claim_number": "CLM-1", "insurer": "Acme", "claimed_amount": 100.0},
    )
    predicted = _fill_schema("insurance_claim", {"claim_number": "wrong"})
    block = score_archive_block("insurance_claim", predicted, expected)
    assert block["overall_score"] is not None
    assert block["overall_score"] < 1.0
    log: dict[str, dict] = {}
    upsert_archive_scoring(
        log,
        "doc_fail",
        block,
        detail={"pipeline_success": False},
    )
    assert log["doc_fail"]["detail"]["pipeline_success"] is False
    assert log["doc_fail"]["detail"]["scoring"]["overall_score"] == block["overall_score"]


def test_retired_prompt_keys_are_ignored():
    expected = _fill_schema(
        "contract",
        {
            "document_name": "NDA",
            "key_obligations": ["keep secrets"],
            "termination_clauses": ["90 days"],
        },
    )
    predicted = dict(expected)
    block = score_archive_block("contract", predicted, expected)
    assert "key_obligations" not in block["field_scores"]
    assert "termination_clauses" not in block["field_scores"]
    assert block["field_scores"]["document_name"] == 1.0


def test_archive_entry_hash_is_stable():
    detail = {
        "stage": "archived",
        "pipeline_success": True,
        "scoring": {
            "method": ARCHIVE_SCORING_METHOD,
            "overall_score": 0.902,
        },
    }
    digest = archive_entry_hash(
        prev_hash="a" * 64,
        doc_id="doc_example",
        entry_id="00000000-0000-4000-8000-000000000001",
        matter_id="EXAMPLE",
        actor="archivist",
        timestamp="2026-10-02T23:55:00+00:00",
        event="archived",
        detail=detail,
    )
    again = archive_entry_hash(
        prev_hash="a" * 64,
        doc_id="doc_example",
        entry_id="00000000-0000-4000-8000-000000000001",
        matter_id="EXAMPLE",
        actor="archivist",
        timestamp="2026-10-02T23:55:00+00:00",
        event="archived",
        detail=detail,
    )
    assert digest == again
    assert len(digest) == 64
    # Reordering detail keys must not change the hash.
    shuffled = json.loads(json.dumps(detail))
    shuffled = {"scoring": shuffled["scoring"], "stage": shuffled["stage"],
                "pipeline_success": shuffled["pipeline_success"]}
    assert archive_entry_hash(
        prev_hash="a" * 64,
        doc_id="doc_example",
        entry_id="00000000-0000-4000-8000-000000000001",
        matter_id="EXAMPLE",
        actor="archivist",
        timestamp="2026-10-02T23:55:00+00:00",
        event="archived",
        detail=shuffled,
    ) == digest
