"""Archivist scoring block for the single ``archived`` audit row.

Mailroom-issues #236 (report → judge → archive), #237 (unified scoring
block), and #238 (one call, one block per document). This package does
not write the hash-chain DB. It returns the ``detail.scoring`` payload
the archivist files after the deterministic report exists.

Do not invent a second formula: :func:`score_extraction` is the overall
score, and :func:`extraction_binary_metrics` is field-micro F1/F2.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, MutableMapping

from .extraction_metrics import extraction_binary_metrics
from .field_scoring import (
    NEVER_SCORED_FIELDS,
    RETIRED_PROMPT_KEYS,
    score_extraction,
)
from .scorecard_honesty import score_format_layer
from .trace_knobs import capture_trace_knobs, empty_trace_payload

__all__ = [
    "ARCHIVE_HASH_VERSION",
    "ARCHIVE_SCORING_KEYS",
    "ARCHIVE_SCORING_METHOD",
    "LIVE_ARCHIVE_DOC_TYPES",
    "NEVER_SCORED_FIELDS",
    "RETIRED_PROMPT_KEYS",
    "archive_entry_hash",
    "canonical_json",
    "empty_archive_scoring_block",
    "field_map_digest",
    "score_archive_block",
    "upsert_archive_scoring",
]

#: Hash version 2: SHA-256 of canonical JSON over the fields listed in
#: :func:`archive_entry_hash` (mailroom-issues #236).
ARCHIVE_HASH_VERSION = 2

ARCHIVE_SCORING_METHOD = "unweighted_mean_of_nonempty_expected_fields"

#: Keys the archivist ``detail.scoring`` object always carries.
ARCHIVE_SCORING_KEYS: tuple[str, ...] = (
    "method",
    "field_map",
    "field_map_sha",
    "overall_score",
    "schema_valid",
    "n_fields_scored",
    "field_scores",
    "extraction_precision",
    "extraction_recall",
    "extraction_f1",
    "extraction_f2",
    "tp",
    "fp",
    "fn",
    "trace",
)

#: Live extraction classes that reach the archive (#238).
LIVE_ARCHIVE_DOC_TYPES: tuple[str, ...] = (
    "contract",
    "merger_agreement",
    "corporate_record",
    "correspondence",
    "insurance_claim",
)

#: CUAD / MAUD headline names that must not overwrite field-micro F1.
_HEADLINE_METHOD_ALIASES: dict[str, str] = {
    "extraction_category_presence": "cuad.clause_presence.micro_f1",
    "cuad.clause_presence.micro_f1": "cuad.clause_presence.micro_f1",
    "maud_question_accuracy": "maud.question.micro_accuracy",
    "maud.question.micro_accuracy": "maud.question.micro_accuracy",
    "maud_clause_presence": "maud.clause_presence.rate",
    "maud.clause_presence.rate": "maud.clause_presence.rate",
}


def canonical_json(obj: Any) -> str:
    """RFC-8785-style compact JSON with sorted keys (hash version 2)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def field_map_digest(
    field_types: Mapping[str, str],
    *,
    taxonomy_bytes: bytes | None = None,
) -> str:
    """SHA of the field map used for this score.

    When ``taxonomy_bytes`` is the live ``taxonomy.yaml`` blob, this is the
    git-blob SHA-1 of those bytes. Otherwise SHA-256 of canonical JSON of
    the field-type map actually scored.
    """
    if taxonomy_bytes is not None:
        header = f"blob {len(taxonomy_bytes)}\0".encode("utf-8")
        return hashlib.sha1(header + taxonomy_bytes).hexdigest()
    payload = canonical_json(dict(field_types))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def empty_archive_scoring_block() -> dict[str, Any]:
    """Shape of the archivist scoring block with every numeric slot null."""
    return {
        "method": ARCHIVE_SCORING_METHOD,
        "field_map": "taxonomy.yaml",
        "field_map_sha": None,
        "overall_score": None,
        "schema_valid": None,
        "n_fields_scored": None,
        "field_scores": {},
        "extraction_precision": None,
        "extraction_recall": None,
        "extraction_f1": None,
        "extraction_f2": None,
        "tp": None,
        "fp": None,
        "fn": None,
        "trace": empty_trace_payload(),
    }


def _is_empty(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return True
    return False


def _live_field_types(doc_class: str, field_types: Mapping[str, str] | None) -> dict[str, str]:
    if field_types:
        return dict(field_types)
    from .suites import DEFAULT_FIELD_TYPES

    mapped = DEFAULT_FIELD_TYPES.get(doc_class)
    if mapped:
        return dict(mapped)
    raise KeyError(
        f"no live field map for {doc_class!r}; known: {sorted(LIVE_ARCHIVE_DOC_TYPES)}"
    )


def _filter_to_live_map(
    record: Mapping[str, Any] | None,
    field_types: Mapping[str, str],
) -> dict[str, Any]:
    src = dict(record or {})
    out: dict[str, Any] = {}
    for key, value in src.items():
        if key in NEVER_SCORED_FIELDS or key in RETIRED_PROMPT_KEYS:
            continue
        if key not in field_types:
            continue
        out[key] = value
    return out


def score_archive_block(
    doc_class: str,
    predicted: Mapping[str, Any] | None,
    expected: Mapping[str, Any] | None,
    *,
    field_types: Mapping[str, str] | None = None,
    field_map: str = "taxonomy.yaml",
    field_map_sha: str | None = None,
    taxonomy_bytes: bytes | None = None,
    method: str | None = None,
    doc_text: str | None = None,
) -> dict[str, Any]:
    """One scoring block for one document (mailroom-issues #237 / #238).

    ``overall_score`` is the unweighted mean of typed scores on expected
    fields that are non-null and non-empty. ``schema_valid`` is the share
    of required keys present on the prediction, filed as a bool (True
    iff every live-map key is present). Field-micro F1/F2 are filled only
    when TP/FP/FN counts exist. CUAD / MAUD headline names passed as
    ``method`` replace ``method`` only — they never overwrite
    ``extraction_f1``.
    """
    ftypes = _live_field_types(doc_class, field_types)
    exp = _filter_to_live_map(expected, ftypes)
    pred = _filter_to_live_map(predicted, ftypes)

    result = score_extraction(
        doc_class, ftypes, pred, exp, doc_text=doc_text
    )
    format_scores = score_format_layer(
        predicted=dict(predicted or {}),
        required_keys=list(ftypes.keys()),
    )
    schema_share = format_scores.get("schema_valid")
    schema_valid: bool | None
    if schema_share is None:
        schema_valid = None
    else:
        schema_valid = float(schema_share) >= 1.0

    prf = extraction_binary_metrics(
        exp, pred, field_map=ftypes, doc_class=doc_class, result=result
    )
    countable = int(prf.get("expected_events") or 0) > 0 or int(prf.get("fp") or 0) > 0
    resolved_method = ARCHIVE_SCORING_METHOD
    if method:
        resolved_method = _HEADLINE_METHOD_ALIASES.get(method, method)

    digest = field_map_sha
    if digest is None:
        digest = field_map_digest(ftypes, taxonomy_bytes=taxonomy_bytes)

    block = empty_archive_scoring_block()
    block["method"] = resolved_method
    block["field_map"] = field_map
    block["field_map_sha"] = digest
    block["overall_score"] = result.overall_score
    block["schema_valid"] = schema_valid
    block["n_fields_scored"] = len(result.field_scores)
    block["field_scores"] = dict(result.field_scores)
    if countable:
        block["extraction_precision"] = prf.get("extraction_precision")
        block["extraction_recall"] = prf.get("extraction_recall")
        block["extraction_f1"] = prf.get("extraction_f1")
        block["extraction_f2"] = prf.get("extraction_f2")
        block["tp"] = prf.get("tp")
        block["fp"] = prf.get("fp")
        block["fn"] = prf.get("fn")
    block["trace"] = capture_trace_knobs(
        predicted,
        expected=expected,
        correctness=result.overall_score,
    )
    return block


def archive_entry_hash(
    *,
    prev_hash: str,
    doc_id: str,
    entry_id: str,
    matter_id: str,
    actor: str,
    timestamp: str,
    event: str,
    detail: Mapping[str, Any],
    hash_version: int = ARCHIVE_HASH_VERSION,
) -> str:
    """SHA-256 of canonical JSON over hash version 2 fields (#236)."""
    payload = {
        "hash_version": hash_version,
        "prev_hash": prev_hash,
        "doc_id": doc_id,
        "entry_id": entry_id,
        "matter_id": matter_id,
        "actor": actor,
        "timestamp": timestamp,
        "event": event,
        "detail": detail,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def upsert_archive_scoring(
    log: MutableMapping[str, dict[str, Any]],
    doc_id: str,
    scoring: Mapping[str, Any],
    *,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace ``detail.scoring`` for ``doc_id``; never append a second row.

    Dojo does not persist the audit DB. Consumers (llm-mailroom archivist
    tests) use this contract: a second score of the same ``doc_id``
    overwrites the scoring block inside the existing row.
    """
    row = log.get(doc_id)
    if row is None:
        row = {
            "doc_id": doc_id,
            "event": "archived",
            "actor": "archivist",
            "detail": dict(detail or {}),
        }
        log[doc_id] = row
    elif detail:
        merged = dict(row.get("detail") or {})
        merged.update(detail)
        row["detail"] = merged
    row.setdefault("detail", {})
    row["detail"]["scoring"] = dict(scoring)
    return row
