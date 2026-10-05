"""Archive scoring contract (mailroom-issues #236 / #237 / #238).

Network-free. One wrapper, one block per document; merger is
MergerAgreementExtraction, not a contract alias.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from llm_dojo_scoring.archive import (
    ARCHIVE_SCORING_KEYS,
    ARCHIVE_SCORING_METHOD,
    AUDIT_DETAIL_KEYS,
    AUDIT_ENTRY_KEYS,
    HAPPY_PATH_NODES,
    LIVE_ARCHIVE_DOC_TYPES,
    archivist_sign_off,
    archive_entry_hash,
    canonical_json,
    empty_archive_scoring_block,
    empty_audit_log_entry,
    format_audit_entry,
    prepare_archivist_handoff,
    score_archive_block,
    upsert_archive_scoring,
    validate_audit_entry,
)
from llm_dojo_scoring.mailroom import EXTRACT_CLASS_ALIASES, resolve_extract_class
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite


def _fill_schema(doc_class: str, values: dict) -> dict:
    """Every live field for ``doc_class`` defaulted to ``None``, overridden by ``values``."""
    out = {key: None for key in DEFAULT_FIELD_TYPES[doc_class]}
    out.update(values)
    return out


def test_empty_block_has_every_archivist_key():
    """The empty scoring block has every archivist key with null numeric slots."""
    block = empty_archive_scoring_block()
    assert tuple(block) == ARCHIVE_SCORING_KEYS
    assert block["method"] == ARCHIVE_SCORING_METHOD
    assert block["field_scores"] == {}
    assert block["extraction_f1"] is None
    assert block["tp"] is None
    assert block["trace"]["confidence"] is None
    assert block["trace"]["reasoning"] is None


def test_merger_is_not_scored_as_contract():
    """Merger agreement is its own extraction class, not a contract alias."""
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
    assert block["trace"]["confidence"] == 0.99
    assert block["trace"]["reasoning"]["summary"] == "trace"
    assert block["trace"]["n_reasoning_entries"] == 0
    assert "effective_time" in block["field_scores"]
    assert block["overall_score"] == 1.0
    assert block["method"] == ARCHIVE_SCORING_METHOD
    assert block["field_map"] == "taxonomy.yaml"
    assert block["field_map_sha"]
    assert block["schema_valid"] is True


@pytest.mark.parametrize("doc_class", LIVE_ARCHIVE_DOC_TYPES)
def test_score_archive_block_covers_live_classes(doc_class):
    """A perfect match scores 1.0 and counts a TP for every live doc class."""
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
    """F1/F2/TP/FP/FN stay null when there are no expected or predicted events."""
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
    """A CUAD headline ``method`` renames ``method`` only; extraction_f1 stays field-micro."""
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
    """Scoring the same document twice overwrites, rather than appends, the row."""
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
    """A failed extraction still gets scored and filed, not skipped."""
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
    """Retired prompt keys are never scored, even when present on both sides."""
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
    """The hash is deterministic and insensitive to detail key ordering."""
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


def _complete_detail(scoring: dict | None = None, **overrides) -> dict:
    """A fully-filled ``detail`` object for a happy-path archived row, with overrides."""
    body = {
        "stage": "archived",
        "pipeline_success": True,
        "nodes_visited": list(HAPPY_PATH_NODES),
        "doc_type": "contract",
        "doc_subclass": "service",
        "classification_confidence": 0.98,
        "extraction_confidence": 0.91,
        "classification_attempts": 1,
        "extraction_attempts": 1,
        "judge_verdict": "complete",
        "judge_score": 1.0,
        "scoring": scoring or empty_archive_scoring_block(),
        "report_path": "matters/EXAMPLE/reports/doc_example.json",
        "archive_path": "archive/EXAMPLE/contract/doc_example.pdf",
        "file_sha256": "0" * 64,
        "review_decision": None,
        "arbiter_decision": None,
        "escalation_reason": None,
    }
    body.update(overrides)
    return body


def test_empty_audit_log_entry_is_the_archivist_template():
    """The empty log entry has the right top-level and detail keys, in order."""
    row = empty_audit_log_entry()
    assert tuple(row)[:9] == AUDIT_ENTRY_KEYS
    assert tuple(row["detail"]) == AUDIT_DETAIL_KEYS
    assert row["event"] == "archived"
    assert row["actor"] == "archivist"
    assert row["prev_hash"] == ""
    assert row["entry_hash"] is None
    assert row["detail"]["scoring"]["method"] == ARCHIVE_SCORING_METHOD


def test_format_audit_entry_computes_stable_entry_hash():
    """Formatting the same inputs twice yields the same entry hash and scoring block."""
    expected = _fill_schema(
        "contract",
        {
            "document_name": "MSA",
            "parties": ["Acme"],
            "effective_date": "2024-03-03",
            "governing_law": "Delaware",
        },
    )
    scoring = score_archive_block("contract", expected, expected)
    entry = format_audit_entry(
        doc_id="doc_example",
        matter_id="EXAMPLE",
        entry_id="00000000-0000-4000-8000-000000000001",
        timestamp="2026-10-02T23:55:00+00:00",
        prev_hash="a" * 64,
        seq=6,
        scoring=scoring,
        detail=_complete_detail(scoring, judge_score=scoring["overall_score"]),
    )
    assert list(entry) == [*AUDIT_ENTRY_KEYS, "detail"]
    assert entry["entry_hash"]
    assert len(entry["entry_hash"]) == 64
    again = format_audit_entry(
        doc_id="doc_example",
        matter_id="EXAMPLE",
        entry_id="00000000-0000-4000-8000-000000000001",
        timestamp="2026-10-02T23:55:00+00:00",
        prev_hash="a" * 64,
        seq=6,
        scoring=scoring,
        detail=_complete_detail(scoring, judge_score=scoring["overall_score"]),
    )
    assert again["entry_hash"] == entry["entry_hash"]
    assert again["detail"]["scoring"]["overall_score"] == scoring["overall_score"]


def test_format_normalizes_specialist_and_langfuse_node_aliases():
    """Specialist / langfuse node aliases fold onto the canonical #236 node names."""
    entry = format_audit_entry(
        doc_id="doc_example",
        matter_id="EXAMPLE",
        entry_id="e1",
        timestamp="2026-10-02T23:55:00+00:00",
        nodes_visited=[
            "intake-document",
            "classify-document",
            "contracts_specialist",
            "compiler-report" if False else "compile-report",
            "deterministic_judge",
            "archive-document",
        ],
        detail=_complete_detail(),
    )
    assert entry["detail"]["nodes_visited"] == list(HAPPY_PATH_NODES)


def test_archivist_signs_off_when_pipeline_and_hash_are_clean():
    """A clean, complete happy-path row signs off with no revisions."""
    expected = _fill_schema(
        "correspondence",
        {"sender": "Pat", "recipient": "Alex"},
    )
    scoring = score_archive_block("correspondence", expected, expected)
    handoff = prepare_archivist_handoff(
        doc_id="doc_ok",
        matter_id="EXAMPLE",
        entry_id="e-ok",
        timestamp="2026-10-02T23:55:00+00:00",
        prev_hash="",
        seq=1,
        scoring=scoring,
        detail=_complete_detail(
            scoring,
            doc_type="correspondence",
            doc_subclass="letter",
            judge_score=scoring["overall_score"],
            report_path="matters/EXAMPLE/reports/doc_ok.json",
            archive_path="archive/EXAMPLE/correspondence/doc_ok.pdf",
        ),
    )
    assert handoff["file_as_final"] is True
    assert handoff["sign_off"]["signed_off"] is True
    assert handoff["sign_off"]["status"] == "signed_off"
    assert handoff["sign_off"]["revisions"] == []
    assert handoff["sign_off"]["hash_ok"] is True
    assert handoff["sign_off"]["pipeline_ok"] is True
    assert handoff["sign_off"]["scoring_ok"] is True
    assert handoff["entry"]["detail"]["scoring"] == scoring


def test_archivist_requests_revision_when_report_is_not_before_judge():
    """Reporting after the judge violates pipeline order and is flagged for revision."""
    scoring = empty_archive_scoring_block()
    entry = format_audit_entry(
        doc_id="doc_bad",
        matter_id="EXAMPLE",
        entry_id="e-bad",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=scoring,
        detail=_complete_detail(
            scoring,
            nodes_visited=[
                "intake",
                "sorter",
                "document_type_specialist",
                "deterministic_judge",
                "deterministic_reporter",
                "archivist",
            ],
        ),
    )
    verdict = archivist_sign_off(entry)
    assert verdict["signed_off"] is False
    assert verdict["status"] == "revision_required"
    codes = {item["code"] for item in verdict["revisions"]}
    assert "pipeline_order" in codes
    assert verdict["pipeline_ok"] is False


def test_tampered_hash_is_not_signed_off():
    """A post-hash edit to ``detail`` is caught and withheld from sign-off."""
    scoring = empty_archive_scoring_block()
    entry = format_audit_entry(
        doc_id="doc_tamper",
        matter_id="EXAMPLE",
        entry_id="e-tamper",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=scoring,
        detail=_complete_detail(scoring),
    )
    entry["detail"]["judge_verdict"] = "tampered"
    verdict = archivist_sign_off(entry)
    assert verdict["signed_off"] is False
    assert verdict["hash_ok"] is False
    assert any(item["code"] == "hash_mismatch" for item in verdict["revisions"])


def test_failed_extraction_path_still_signs_off_after_report_judge_archive():
    """A failed-extraction job still signs off once it visits report, judge, archive."""
    expected = _fill_schema(
        "insurance_claim",
        {"claim_number": "CLM-1", "insurer": "Acme", "claimed_amount": 100.0},
    )
    predicted = _fill_schema("insurance_claim", {"claim_number": "wrong"})
    scoring = score_archive_block("insurance_claim", predicted, expected)
    handoff = prepare_archivist_handoff(
        doc_id="doc_fail",
        matter_id="EXAMPLE",
        entry_id="e-fail",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=scoring,
        pipeline_success=False,
        nodes_visited=[
            "intake",
            "sorter",
            "document_type_specialist",
            "arbiter",
            "specialist_retry",
            "human_review_extraction",
            "deterministic_reporter",
            "deterministic_judge",
            "archivist",
        ],
        detail=_complete_detail(
            scoring,
            pipeline_success=False,
            doc_type="insurance_claim",
            doc_subclass="auto",
            extraction_attempts=2,
            judge_verdict="incomplete",
            judge_score=scoring["overall_score"],
            report_path="matters/EXAMPLE/reports/doc_fail.json",
            archive_path="archive/EXAMPLE/insurance_claim/doc_fail.pdf",
            review_decision="cleared",
        ),
    )
    assert handoff["sign_off"]["signed_off"] is True
    assert handoff["entry"]["detail"]["pipeline_success"] is False
    assert handoff["entry"]["detail"]["scoring"]["overall_score"] == scoring["overall_score"]


def test_incomplete_template_is_still_passed_to_the_archivist():
    """The formatter always hands the templated row through; sign-off withholds filing."""
    handoff = prepare_archivist_handoff(
        doc_id="doc_draft",
        matter_id="EXAMPLE",
        entry_id="e-draft",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=empty_archive_scoring_block(),
        detail={"stage": "archived", "pipeline_success": True},
    )
    assert handoff["entry"]["doc_id"] == "doc_draft"
    assert handoff["entry"]["entry_hash"]
    assert tuple(handoff["entry"]["detail"])[:5] == AUDIT_DETAIL_KEYS[:5]
    assert handoff["file_as_final"] is False
    assert handoff["sign_off"]["status"] == "revision_required"
    codes = {item["code"] for item in handoff["sign_off"]["revisions"]}
    assert "happy_path_incomplete" in codes or "pipeline_order" in codes
    assert "missing_judge_verdict" in codes
    assert "missing_path" in codes


def test_issue_236_example_payload_hash_is_stable():
    """Lock canonical JSON over the published #236 example (without extra scoring keys)."""
    detail = {
        "stage": "archived",
        "pipeline_success": True,
        "nodes_visited": [
            "intake",
            "sorter",
            "document_type_specialist",
            "deterministic_reporter",
            "deterministic_judge",
            "archivist",
        ],
        "doc_type": "contract",
        "doc_subclass": "service",
        "classification_confidence": 0.98,
        "extraction_confidence": 0.91,
        "classification_attempts": 1,
        "extraction_attempts": 1,
        "judge_verdict": "complete",
        "judge_score": 0.902,
        "scoring": {
            "method": "unweighted_mean_of_nonempty_expected_fields",
            "overall_score": 0.902,
            "schema_valid": True,
            "field_scores": {
                "document_name": 1.0,
                "parties": 1.0,
                "effective_date": 1.0,
                "governing_law": 1.0,
            },
            "extraction_f1": None,
            "extraction_f2": None,
        },
        "report_path": "matters/EXAMPLE/reports/doc_example.json",
        "archive_path": "archive/EXAMPLE/contract/doc_example.pdf",
        "file_sha256": "0" * 64,
        "review_decision": None,
        "arbiter_decision": None,
        "escalation_reason": None,
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
    # Hash version 2 of the published #236 example payload under the
    # llm-mailroom canonicalization (json.dumps sort_keys=True, default
    # separators). The issue's printed digest is not reproducible from the
    # payload as shown; the parity test below pins the live writer contract.
    assert digest == "4afd352d29e4be1b70605dbaa5a4bd486f187ac908c986e5e8d5feaed8e8bef4"


def _mailroom_compute_audit_hash(
    *,
    prev_hash: str,
    doc_id: str,
    entry_id: str,
    event: str,
    detail: dict,
    matter_id: str = "",
    actor: str = "",
    timestamp=None,
    hash_version: int = 2,
) -> str:
    """Verbatim re-implementation of llm-mailroom ``compute_audit_hash``.

    llm-mailroom ``src/schemas/audit.py`` is the writer of record for the
    hash-chain DB. Dojo never imports mailroom, so this oracle pins the
    serialization contract: ``json.dumps(..., sort_keys=True, default=str)``
    over the v2 field set, with ``datetime`` rendered via ``isoformat()``.
    If mailroom ever changes its canonicalization, both repos must change
    together (the parity test goes red here first).
    """
    import hashlib
    from datetime import datetime, timezone

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    ts = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
    payload = json.dumps(
        {
            "hash_version": hash_version,
            "prev_hash": prev_hash,
            "doc_id": doc_id,
            "entry_id": entry_id,
            "matter_id": matter_id,
            "actor": actor,
            "timestamp": ts,
            "event": event,
            "detail": detail,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_archive_hash_matches_llm_mailroom_compute_audit_hash():
    """Same payload → same digest as the live llm-mailroom writer."""
    detail = {
        "stage": "archived",
        "pipeline_success": True,
        "nodes_visited": [
            "intake",
            "sorter",
            "document_type_specialist",
            "deterministic_reporter",
            "deterministic_judge",
            "archivist",
        ],
        "doc_type": "contract",
        "doc_subclass": "service",
        "judge_verdict": "complete",
        "judge_score": 0.902,
        "scoring": {"overall_score": 0.902, "schema_valid": True, "field_scores": {}},
    }
    kwargs = dict(
        prev_hash="a" * 64,
        doc_id="doc_example",
        entry_id="00000000-0000-4000-8000-000000000001",
        matter_id="EXAMPLE",
        actor="archivist",
        timestamp="2026-10-02T23:55:00+00:00",
        event="archived",
        detail=detail,
    )
    assert archive_entry_hash(**kwargs) == _mailroom_compute_audit_hash(**kwargs)


def test_archive_hash_datetime_matches_mailroom_isoformat():
    """A ``datetime`` timestamp hashes as mailroom's ``isoformat()`` form."""
    from datetime import datetime, timezone

    ts = datetime(2026, 10, 2, 23, 55, tzinfo=timezone.utc)
    detail = {"stage": "archived", "scoring": {}}
    kwargs = dict(
        prev_hash="",
        doc_id="doc_dt",
        entry_id="e-dt",
        matter_id="M",
        actor="archivist",
        timestamp=ts,
        event="archived",
        detail=detail,
    )
    assert archive_entry_hash(**kwargs) == _mailroom_compute_audit_hash(**kwargs)


def test_mailroom_oracle_hash_row_verifies_in_dojo():
    """A row whose entry_hash was computed by mailroom verifies in dojo."""
    scoring = empty_archive_scoring_block()
    entry = format_audit_entry(
        doc_id="doc_mailroom",
        matter_id="EXAMPLE",
        entry_id="e-mailroom",
        timestamp="2026-10-02T23:55:00+00:00",
        prev_hash="b" * 64,
        scoring=scoring,
        detail={
            "doc_type": "correspondence",
            "judge_verdict": "complete",
            "judge_score": None,
            "report_path": "matters/EXAMPLE/reports/doc_mailroom.json",
            "archive_path": "archive/EXAMPLE/correspondence/doc_mailroom.pdf",
            "file_sha256": "c" * 64,
            "nodes_visited": list(HAPPY_PATH_NODES),
            "pipeline_success": True,
        },
    )
    mailroom_digest = _mailroom_compute_audit_hash(
        prev_hash=entry["prev_hash"],
        doc_id=entry["doc_id"],
        entry_id=entry["entry_id"],
        matter_id=entry["matter_id"],
        actor=entry["actor"],
        timestamp=entry["timestamp"],
        event=entry["event"],
        detail=entry["detail"],
    )
    assert entry["entry_hash"] == mailroom_digest
    entry["entry_hash"] = mailroom_digest
    from llm_dojo_scoring.archive import verify_entry_hash

    assert verify_entry_hash(entry) is True


def test_validate_rejects_unknown_pipeline_nodes():
    """An unrecognized node name in ``nodes_visited`` is flagged as a revision."""
    scoring = empty_archive_scoring_block()
    entry = format_audit_entry(
        doc_id="doc_unknown",
        matter_id="EXAMPLE",
        entry_id="e-unknown",
        timestamp="2026-10-02T23:55:00+00:00",
        scoring=scoring,
        detail=_complete_detail(
            scoring,
            nodes_visited=[
                "intake",
                "sorter",
                "mystery_agent",
                "document_type_specialist",
                "deterministic_reporter",
                "deterministic_judge",
                "archivist",
            ],
        ),
    )
    codes = {item["code"] for item in validate_audit_entry(entry)}
    assert "unknown_pipeline_node" in codes


def test_canonical_json_preserves_mailroom_spacing_escaping_and_default_str():
    payload = {"z": "café", "a": {"amount": Decimal("12.50"), "ok": True}}
    assert canonical_json(payload) == (
        '{"a": {"amount": "12.50", "ok": true}, "z": "caf\\u00e9"}'
    )


@pytest.mark.parametrize("timestamp", [
    datetime(2026, 10, 2, 23, 55, 1, 123456),
    datetime(2026, 10, 2, 23, 55, 1, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    "2026-10-02T23:55:01.123456Z",
    0,
])
def test_archive_hash_timestamp_variants_match_mailroom(timestamp):
    kwargs = dict(
        prev_hash="a" * 64, doc_id="doc-unicode", entry_id="entry-1",
        matter_id="M", actor="archivist", timestamp=timestamp, event="archived",
        detail={"name": "café", "amount": Decimal("12.50")},
    )
    assert archive_entry_hash(**kwargs) == _mailroom_compute_audit_hash(**kwargs)
    normalized = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
    assert archive_entry_hash(**kwargs) == archive_entry_hash(**{**kwargs, "timestamp": normalized})


def test_archive_hash_ignores_mapping_order_but_detects_nested_content_changes():
    kwargs = dict(
        prev_hash="", doc_id="doc-1", entry_id="entry-1", matter_id="M",
        actor="archivist", timestamp="2026-10-02T23:55:00+00:00", event="archived",
    )
    original = {"stage": "archived", "scoring": {"a": 1, "b": 0}}
    reordered = {"scoring": {"b": 0, "a": 1}, "stage": "archived"}
    changed = {"stage": "archived", "scoring": {"a": 1, "b": 1}}
    digest = archive_entry_hash(**kwargs, detail=original)
    assert digest == archive_entry_hash(**kwargs, detail=reordered)
    assert digest != archive_entry_hash(**kwargs, detail=changed)


@pytest.mark.parametrize("empty", ["[]", "{}", " N/A ", "null"])
def test_archive_empty_metadata_does_not_create_false_negatives(empty):
    block = score_archive_block(
        doc_class="insurance_claim", expected={"claim_number": "CLM-1", "denial_reasons": empty},
        predicted={"claim_number": "CLM-1"},
    )
    assert block["extraction_f1"] == 1.0
    assert block["fn"] == 0
