# Issue alignment — v0.19.0 (updated for Unreleased, planned v0.22.0)

Status of the open scoring issues after the v0.19.0 release-completion
patch (adversarial audit of PR #23 + this patch). **Stale** = already
satisfied, no further code needed. **Relevant** = still open, with the
smallest remaining unit named.

## This repository

| Issue | Status | Landed | Remaining |
|---|---|---|---|
| [#16](https://github.com/Exios66/llm-dojo-scoring/issues/16) fail-closed unscorable GT | **Relevant** (partially closed) | `assess_extraction_gt`, `unscorable_extraction_result`, `aggregate_quality_honest` (`n_scored` / `n_unscorable`, never folds 0.0), `export_quality_verdict`; v0.19.0 stops suppressing content-only correspondence and MAUD-only merger rows that the suite can genuinely score; Unreleased: per-row assessment in batches (batch `n_unscorable` / `export_verdict`), archive block `status` / `reason`, ITT and grid rows exclude unscorable docs | Corpus audit of live triage-only rows (`lucius`, mailroom-dataset `46a4d3c2`); keep the hub data-card fix moving |
| [#17](https://github.com/Exios66/llm-dojo-scoring/issues/17) metric identity | **Closed in code** | `_CLASS_METRIC_IDS` now covers all five live classes; `extraction_f2` allowed per class; Enron topic/sentiment ids mapped; `metric_id_allowed()`; `assert_comparable_metric_ids`; `compare_serving` incomparable flag; grid rows refuse mixed ids; **`metric_id_for` is strict** (`UnknownMetricNameError`, no fabricated ids) with a docs↔code parity test (`tests/test_metric_id_strict.py`); Unreleased: one-sided / mixed ids are incomparable and suppress the quality delta; archive and `score_document` refuse a contradicting claimed id; precision/recall ids allowed per class | — |
| [#18](https://github.com/Exios66/llm-dojo-scoring/issues/18) `schema_valid` headline gate | **Closed in code** | `schema_valid` / `parse_ok` / `schema_adherence` in the registry (T1); emitted on every detailed payload (`score_document()`, `detailed=True`, any dict-returning `score()`; the bare single-document `score()` result is an `ExtractionScoreResult` without it); **promotion gate on all five classes** (`SCHEMA_PROMOTION_GATES`, batch + single); batch format layer scored per item (was always 1.0) and padded to the GT length so a short prediction list cannot pass; registry guard that T0+T1 views show `schema_valid` / `parse_ok` for every live specialist | Spend-gated experiment stays [hub #230](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/230) |
| [#19](https://github.com/Exios66/llm-dojo-scoring/issues/19) MAUD distinct keys / ambiguous GT | **Stale** (closed by PR #23, verified) | `score_maud_extraction` distinct Hub keys; `detect_maud_gt_ambiguity`; `n_ambiguous`; micro-accuracy over clean keys only | — |
| [#20](https://github.com/Exios66/llm-dojo-scoring/issues/20) format vs extraction + empty fields | **Stale** (closed by PR #23, verified) | `score_format_layer`; `classify_extraction_failure`; `score_empty_field_contract`; spurious fill = FP | — |
| [#21](https://github.com/Exios66/llm-dojo-scoring/issues/21) completion / ITT / cost / serving | **Stale** (closed by PR #23, verified) | `summarize_run_completion` + error histogram; `aggregate_quality_itt`; `resolve_cost_basis`; honest `serving_kind` | — |
| [#22](https://github.com/Exios66/llm-dojo-scoring/issues/22) provenance stamps | **Closed in code** | `stamp_provenance` on every suite extraction path; `validate_comparison_provenance`; `PROVENANCE_KEYS`; **`Emitter.emit_score` requires a stamp** (`EMIT_REQUIRED_PROVENANCE`, `cost_basis` on USD metrics); **archive scoring block carries `provenance`**; Unreleased: comparison gate `vary` axis + `cost_basis` validation, provenance-keyed `pair_comparable_runs`, `compare_serving(require_provenance=)`, `token_price_estimate` basis | local-mailroom-sandbox calls `emit_serving_scorecard` without provenance (`eval/scoring.py` `emit_local_vs_api_scorecard`): once it re-vendors, it must pass `dataset_revision` (or record it on its serving records); its tests monkeypatch `Emitter` and miss this. llm-mailroom calls none of the emit APIs |

## Upstream mailroom-issues (dojo side done; mailroom side open)

| Issue | Status | Dojo side | Remaining (llm-mailroom) |
|---|---|---|---|
| [#236](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/236) pipeline + archive row | **Relevant** | `format_audit_entry` / `prepare_archivist_handoff` / `archivist_sign_off`; hash-v2 parity with `compute_audit_hash` (this release) | Archivist files the single `archived` row with `judge_score` + scoring block; per-stage appends stop for the terminal record |
| [#237](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/237) unified scoring block | **Relevant** | `score_archive_block` (method, field map + SHA, overall, schema, per-field, micro P/R/F1/F2 with TP/FP/FN only when countable); merger is `MergerAgreementExtraction` | llm-mailroom / Digital-Mailroom field maps must copy the live `taxonomy.yaml` before filing |
| [#238](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/238) one block per document | **Relevant** | `upsert_archive_scoring` replaces `detail.scoring`, never appends; F1/F2 null without counts | The DB write is llm-mailroom's; dojo does not open the hash chain |

## Adversarial audit corrections to PR #23

- The PR body says **421 passed**; the merged tree ran **454 passed, 5
  skipped** (the body was stale at submission; the merged commit content
  equals the PR head). v0.19.0 adds 67 tests → **521 passed, 5 skipped**.
- The PR's "hash version 2" claim was only true for dojo's own
  round-trip; cross-package canonicalization differed from llm-mailroom.
  Fixed in this release with a parity oracle.
- The digest printed in mailroom-issues #236 is not reproducible from the
  payload as shown by either package; tests pin the live mailroom
  algorithm instead.
- `EXTRACT_CLASS_ALIASES == {}`, the five-class live roster, merger as its
  own suite, `compliance_filing` retired, MAUD ambiguity, format layer,
  empty-field credit, completion/ITT, and cost-basis rules were verified
  in code and tests.
