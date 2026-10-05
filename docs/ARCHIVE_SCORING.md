# Archive scoring contract (v0.19)

Companion to [mailroom-issues #236](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/236)
(pipeline order: deterministic report, then deterministic judge and scoring,
then archive), [#237](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/237)
(unified scoring block), and [#238](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/238)
(one block per document from this package).

This package does **not** write the hash-chain audit DB. Call
`score_archive_block` after the deterministic report exists, then
`format_audit_entry` / `prepare_archivist_handoff` to build the hashed
`archived` row. The archivist validates that template against the
pipeline steps for the document and signs off when there is nothing to
revise.

Numbers in the examples below are the **shape**, not a measured run. Do not
backfill `extraction_f1` / `extraction_f2` from `overall_score`.

## One call

```python
from llm_dojo_scoring import score_archive_block

block = score_archive_block(
    "merger_agreement",
    predicted,
    expected,
    taxonomy_bytes=open("taxonomy.yaml", "rb").read(),  # optional git-blob SHA
)
```

`overall_score` is `score_extraction`: unweighted mean of typed scores on
expected fields that are non-null and non-empty. No field weights.
`confidence` and `reasoning` are never scored. They are **captured** on
`trace` as experimental knobs (`docs/SCORECARD_HONESTY.md`) — sweep
`confidence_min`, `confidence_band`, and `reasoning_routes_presence` via
`configure(trace_knobs__…)` or a `trace_knobs:` YAML block. Keys not on
the live model (`key_obligations`, `cuad_family` on a merger, …) are
ignored.

Merger is `MergerAgreementExtraction` (`effective_time`, `intent`,
`subject_matter`, `keywords`; no `cuad_family` / `cuad_clauses`). The
`merger_agreement` → `contract` extract alias is gone.

Field-micro F1 / F2 come from `extraction_binary_metrics`. One event per
non-empty expected field; TP only when that field scores 1.0;
`F1 = 2PR/(P+R)`, `F2 = 5PR/(4P+R)`. They stay `null` unless TP/FP/FN
counts exist. CUAD category-presence micro-F1 and MAUD accuracy are
different metrics — pass them as `method=` if that run used them; they
never overwrite `extraction_f1`.

`schema_valid` is whether every live-map key is present on the prediction.
It is not part of `overall_score`.

A second `score_archive_block` on the same `doc_id` **replaces**
`detail.scoring` (`upsert_archive_scoring`). It does not append a row.

## Archivist scoring block

```json
{
  "method": "unweighted_mean_of_nonempty_expected_fields",
  "field_map": "taxonomy.yaml",
  "field_map_sha": "<blob of the taxonomy used>",
  "overall_score": 0.902,
  "schema_valid": true,
  "n_fields_scored": 4,
  "field_scores": {
    "document_name": 1.0,
    "parties": 1.0,
    "effective_date": 1.0,
    "governing_law": 1.0
  },
  "extraction_precision": null,
  "extraction_recall": null,
  "extraction_f1": null,
  "extraction_f2": null,
  "tp": null,
  "fp": null,
  "fn": null,
  "trace": {
    "confidence": 0.91,
    "reasoning": {"summary": "parties on signature page", "entries": []},
    "confidence_gate": "pass",
    "calibration_error": 0.008,
    "n_reasoning_entries": 0
  }
}
```

Illustrative. Not a document that was processed. `extraction_f1` and
`extraction_f2` stay null unless that run stored true-positive,
false-positive, and false-negative counts.

## Example `archived` row (#236)

`entry_hash` is SHA-256 of canonical JSON over `hash_version`, `prev_hash`,
`doc_id`, `entry_id`, `matter_id`, `actor`, `timestamp`, `event`, `detail`.
Canonicalization is **byte-identical to llm-mailroom**
`src/schemas/audit.py::compute_audit_hash`:
`json.dumps(payload, sort_keys=True, default=str)` (default separators), with
a `datetime` timestamp rendered via `isoformat()`. Any difference in
serialization breaks cross-package chain verification even though each side
round-trips its own rows; the parity oracle lives in
`tests/test_archive_scoring.py::test_archive_hash_matches_llm_mailroom_compute_audit_hash`.
Use `llm_dojo_scoring.format_audit_entry` (which calls
`archive_entry_hash`). `prev_hash` is the previous document's
`entry_hash` (empty string only for the first row in the DB).

## Format the audit row and hand it to the archivist

Dojo still does **not** write the hash-chain DB. It formats the same
row the archivist would append and validates it against the pipeline
steps for that document. The templated entry is always passed through;
the archivist files it as final only when there is nothing to revise.

```python
from llm_dojo_scoring import prepare_archivist_handoff, score_archive_block

block = score_archive_block("contract", predicted, expected)
handoff = prepare_archivist_handoff(
    doc_id="doc_example",
    matter_id="EXAMPLE",
    entry_id="00000000-0000-4000-8000-000000000001",
    timestamp="2026-10-02T23:55:00+00:00",
    prev_hash="a" * 64,
    seq=6,
    scoring=block,
    nodes_visited=[
        "intake",
        "sorter",
        "document_type_specialist",
        "deterministic_reporter",
        "deterministic_judge",
        "archivist",
    ],
    pipeline_success=True,
    detail={
        "doc_type": "contract",
        "doc_subclass": "service",
        "judge_verdict": "complete",
        "judge_score": block["overall_score"],
        "report_path": "matters/EXAMPLE/reports/doc_example.json",
        "archive_path": "archive/EXAMPLE/contract/doc_example.pdf",
        "file_sha256": "0" * 64,
    },
)
# handoff["entry"] is the hashed row. Pass it to the archivist even when
# handoff["file_as_final"] is False — that is the template to revise.
assert handoff["sign_off"]["signed_off"]  # nothing to revise
```

`format_audit_entry` fills every `detail` key from the template
(`empty_audit_log_entry`), embeds `scoring`, and writes `entry_hash`.
Langfuse / specialist names (`intake-document`, `contracts_specialist`,
`compile-report`, …) fold onto the #236 node list.

`archivist_sign_off` recomputes the hash and checks the pipeline:

- `event=archived`, `actor=archivist`
- `deterministic_reporter` then `deterministic_judge` then `archivist`
  (report → judge → archive). Successful jobs also require intake →
  sorter → document-type specialist before that tail.
- `judge_verdict`, `judge_score` (when `overall_score` is filed), and
  the scoring block keys
- `doc_type`, archive/report paths, `file_sha256`

Sign-off never mutates the hashed row. A failed extraction that still
reached the reporter uses the same checks with `pipeline_success` false.

```json
{
  "entry_id": "00000000-0000-4000-8000-000000000001",
  "doc_id": "doc_example",
  "matter_id": "EXAMPLE",
  "seq": 6,
  "event": "archived",
  "actor": "archivist",
  "timestamp": "2026-10-02T23:55:00+00:00",
  "prev_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "entry_hash": "<sha256 of hash version 2 payload>",
  "detail": {
    "stage": "archived",
    "pipeline_success": true,
    "nodes_visited": [
      "intake",
      "sorter",
      "document_type_specialist",
      "deterministic_reporter",
      "deterministic_judge",
      "archivist"
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
      "field_map": "taxonomy.yaml",
      "field_map_sha": "<blob of the taxonomy used>",
      "overall_score": 0.902,
      "schema_valid": true,
      "n_fields_scored": 4,
      "field_scores": {
        "document_name": 1.0,
        "parties": 1.0,
        "effective_date": 1.0,
        "governing_law": 1.0
      },
      "extraction_precision": null,
      "extraction_recall": null,
      "extraction_f1": null,
      "extraction_f2": null,
      "tp": null,
      "fp": null,
      "fn": null,
      "trace": {
        "confidence": 0.91,
        "reasoning": {"summary": "parties on signature page", "entries": []},
        "confidence_gate": "pass",
        "calibration_error": 0.008,
        "n_reasoning_entries": 0
      }
    },
    "report_path": "matters/EXAMPLE/reports/doc_example.json",
    "archive_path": "archive/EXAMPLE/contract/doc_example.pdf",
    "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "review_decision": null,
    "arbiter_decision": null,
    "escalation_reason": null
  }
}
```

A document that failed extraction twice, cleared human review, and was
still reported uses the same block. `pipeline_success` is false and
`overall_score` is whatever the judge computed after the report, including
a low score. Do not omit the block because the job was not clean.
