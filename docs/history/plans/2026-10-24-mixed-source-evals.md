# Retire deprecated packages: primary core + `mixed_source` artifact bundle

Tracking issue: #66 (RETIRE DEPRECATED PACKAGES). Branch: `refactor/66-mixed-source-evals`.
Target release: **v0.25.0** (additive moves, deprecation shims) → **v0.26.0** (shim removal).

## Goal

Split the dojo into two tiers:

1. **Primary** — everything the Mailroom constellation calls: the four primary task
   families, the full pipeline scoring plumbing, and every name a dependent repo imports.
   Stays importable from `llm_dojo_scoring` exactly as today.
2. **Mixed-source evals artifact** — rarely used, non-pipeline benchmark scorers, moved to
   `llm_dojo_scoring.mixed_source`. Still installed and callable; no longer eagerly imported
   or exported from the package root.

No metric ID, score name or number changes. Each move is a relocation with a
re-export shim, guarded by a pinned consumer-surface contract test.

## Evidence (audit on 2026-10-24, `main` @ 263bbd6)

AST scan of every `from llm_dojo_scoring… import …` in the sibling repos:

| Consumer | Uses |
| --- | --- |
| `llm-mailroom` | `field_scoring` (scorers, `ExtractionScoreResult`, embeddings), `get_suite`/`list_suites`, `configure[_from_taxonomy]`, `intake`, `intents`, `mailroom.score_aligned_classification`, `prompts`, `corpus`, `registry.MetricTier`, `load_registry`, `pruning.headline_metrics`, `serving.compare_serving`, `archive.archive_entry_hash`, `content_scoring.peel_non_extraction_fields`, `scorecard_honesty.SCORER_VERSION` |
| `local-mailroom-sandbox` | `score_task` (**`docclass` and `legalbench`**), `get_suite('sorter' / 'local_vs_api')`, `suite_for_doc_type`, `serving.*`, `scorecard_honesty.*`, `emitter`, `experiment`, `extraction_metrics`, `maud.MAUD_ANSWER_CLASSES`, `maud_schema`, `mailroom` trace constants, `prompts` lineage, `corporate_record_schema`, `schema_contract`, `bootstrap_ci`, `accuracy`, `exact_match`, `headline_metrics` |
| `eval-environment` | `configure_from_taxonomy`, `get_field_types`, `intake.looks_messy`, `cost.estimate_cost` |
| `mailroom-ml` | `corpus`, `intake` |
| `Mailroom-Corpus-EDA` | `corporate_record_schema`, `mailroom.HUB_SUBCLASS_INVENTORIES`, `gt_metadata`, `corporate_record_relabel` |
| `The-Mailroom` (visualizer) | No Python import — reads **Langfuse score names** (`mailroom.LANGFUSE_SCORE_NAME_ALIASES`, registry metric IDs) and the offline-evaluation engines in `docs/PRIMARY_ENGINE_OWNERSHIP.md` |

Live suites (`suites.DEFAULT_SUITES`, not retired): sorter, judge, sorter_reviewer, intake,
pdf_transcriber, image_extractor, local_vs_api, reporter, boss, archivist, arbiter,
audit_agent, and the contract / corporate_records / correspondence / insurance_claims /
merger_agreement specialists + auditors. Retired: compliance, court_opinions, due_diligence
(specialist + auditor each).

## Tier assignment

### Primary — task families (as specified)

| Task keys | Scope | Metric contract |
| --- | --- | --- |
| `subtype` / `doc_class` / `multiclass` | CUAD 25-family subtype, primary doc-class, generic multi-class | exact match + CI, macro accuracy, per-class, confusion |
| `docclass` / `maud_docclass` | Hierarchical doc_type + second-level subclass | doc_type accuracy + macro P/R/F1/F2, subclass accuracy |
| `maud_question` / `maud_extraction` (+ `maud_clause`) | MAUD consideration answers + 22 Hub questions | exact match + CI, per-class, macro |
| `enron_topic` / `enron_sentiment` (+ `content_topic`, `sentiment`) | Enron correspondence topics & sentiment | accuracy, macro-F1, per-class |

### Primary — pipeline plumbing (needed by the constellation, not in the list above)

These are **kept primary** because a live suite or dependent repo calls them:

- `pipeline` / `document-pipeline` task kind; `pipeline_scoring`, `pipeline_verdict`, `pilot_labels`, `pilot_summary`, `field_support` (ownership engines, v0.23.0).
- `intake` task kind + `intake` module (`get_suite("intake")`, mailroom/eval-env/mailroom-ml).
- `transcription` / `wer` / `cer` + `asr` — **backs the live `pdf_transcriber` and `image_extractor` suites.** Flagged as missed from the list; keep primary.
- `sandbox_scoring`, `sandbox_agent_scoring`, `sandbox_composite`, `sandbox_schema_adherence` (sandbox ownership engines).
- Field/extraction engines: `field_scoring`, `extraction_metrics`, `content_scoring`, `diagnostics`, `schema_contract`, `cuad_schema`, `maud`, `maud_schema`, `corporate_record_schema`, `corporate_record_relabel`, `gt_metadata`, `corpus`, `equivalences`, `intents`.
- Suites/profiles/config: `suites`, `profiles`, `config`, `classification`, `bootstrap`, `_paired`.
- Emission & honesty: `registry`, `metric_meta`, `emitter`, `scorecard_honesty`, `pruning`, `bundles`, `doc_bundles`, `archive`, `experiment`, `serving`, `cost`, `mailroom`, `prompts`, `trace_knobs`.
- Tooling: `cli`, `io`, `export`, `visualize`, `grid`, `report`, `interpret`, `error_analysis`, `failure_modes`, `claims_consistency`, `langfuse_sync`, `phoenix_sync`, `update_awareness`, `agent_rubrics`.

### Mixed-source evals artifact (`llm_dojo_scoring.mixed_source`)

| Scorer | Current home | Notes |
| --- | --- | --- |
| LegalBench (`legalbench_score`, `normalize_legalbench`, `LEGALBENCH_*`, `legalbench_scoring.py`) | `tasks.py`, `config.py`, `legalbench_scoring.py` | **Decision gate:** the sandbox calls `score_task("legalbench")` and the ownership doc names it for visualizer offline eval. `score_task` dispatch must keep working. |
| ContractEval (`contracteval_*`, `get_jaccard`, `said_no_related`, `CONTRACTEVAL_*`) | `tasks.py`, `config.py` | `bundles.py` and `registry.py` reference `contracteval_false_no_related`; metric ID stays registered. |
| `court_opinion` scorer + retired court_opinions / compliance / due_diligence suites & profiles | `tasks.py`, `config.py`, `suites.py`, `profiles.py` | Doc classes already retired (sorter emits `unknown`). |
| Generic `chained` (`tasks.chained_composite`, `chained_summary`) | `tasks.py` | **Duplicate:** `sandbox_composite.chained_composite` has a different signature, no rounding and refuses a missing half. Sandbox version stays primary; the generic one moves or is aliased. |

## Mechanics

- `llm_dojo_scoring/mixed_source/__init__.py` with submodules `legalbench.py`, `contracteval.py`, `court_opinion.py`, `chained.py`, `retired_suites.py`.
- `tasks.score_task` keeps the same task keys and routes the artifact kinds through a lazy import of `mixed_source` (like the `content_scoring` / `asr` branches already do).
- The root `llm_dojo_scoring` keeps a module `__getattr__` shim for moved names. It emits a `DeprecationWarning` that points to the new path for one minor release (v0.25.x), then the shim is removed in v0.26.0. Exception: any name in the consumer-surface manifest stays exported until every consumer has been re-vendored.
- `registry.py` / `metric_meta.py` `source:` strings get updated to the new paths. Metric IDs don't change.
- The `dojo-analyze` CLI still accepts every task key.

## Guardrails

1. `tests/fixtures/consumer_surface.json` — generated by `scripts/audit_consumer_surface.py` (the AST scan above) over the sibling repos. `tests/test_consumer_compat.py` asserts every pinned name still imports from its recorded path.
2. Golden-number tests: before any move, freeze `score_task` outputs for every task key on the fixtures. After the move they must be byte-identical.
3. Import-time budget: `import llm_dojo_scoring` must not import `mixed_source`.
4. Langfuse score-name parity with The-Mailroom: the `LANGFUSE_SCORE_NAME_ALIASES` and registry IDs snapshot must not change.

## Sub-issues (attached to #66, in order)

Issue numbers: 01 = #84, then 02–18 = #67–#83.

1. Consumer-surface audit script + pinned manifest + contract test
2. Golden-number freeze for every task key (pre-move baseline)
3. Primary tier definition: `docs/PACKAGE_TIERS.md` + `PRIMARY_TASK_KINDS` / `MIXED_SOURCE_TASK_KINDS` in config
4. Perfect primary family: subtype / doc_class / multiclass
5. Perfect primary family: docclass / maud_docclass
6. Perfect primary family: maud_question / maud_extraction
7. Perfect primary family: enron_topic / enron_sentiment
8. Preserve pipeline plumbing as primary (pipeline, intake, transcription/ASR, sandbox + ownership engines, visualizer score names)
9. Scaffold the `llm_dojo_scoring.mixed_source` artifact package + lazy dispatch
10. Move LegalBench into mixed_source (with a decision gate for sandbox usage)
11. Move ContractEval into mixed_source
12. Move court_opinion + retired doc-class suites into mixed_source
13. Deduplicate `chained_composite` (tasks vs sandbox_composite)
14. Prune deprecated/legacy code
15. Slim the root `__init__` + tiered `__all__` + import-time test
16. Docs, CHANGELOG, MIGRATION and the v0.25.0 release
17. Downstream adoption: re-vendor llm-mailroom, local-mailroom-sandbox and eval-environment, plus a The-Mailroom parity check

## Dedicated pipeline package: `llm-dojo-pipeline` (#83)

This work lives on the long-lived branch `feat/66-pipeline-scoring-package`, which is
stacked on `refactor/66-mixed-source-evals`. It does **not** merge to `main`
until #66 is complete. The skeleton is at `packages/llm-dojo-pipeline/`
(import `dojo_pipeline`) and has its own pyproject. It will be released with
`pipeline-vX.Y.Z` tags.

- **Families:** classification, hierarchical, maud, correspondence and
  **transcription** (PDF transcriber, image transcriber / OCR, `transcription`/`wer`/`cer`).
  `score_family` delegates to `llm_dojo_scoring.score_task`, so the numbers are
  identical to the core, and checks each result against `contracts.CONTRACTS`.
- **Sink-agnostic emission:**
  - `ScoreEvent` gives typed fields for the trace, observation and session
    targets, the data type and the comment.
  - `TraceSink` is the protocol. The adapters are `LocalManifestTraceSink`,
    `LangfuseTraceSink` (dojo alias table, refuses unattached scores) and
    `FanoutSink`.
  - `PhoenixTraceSink` and `OTelTraceSink` are planned stubs.
- `PipelineScorer` maps graph nodes to families. Nodes without a primary family
  raise `NotImplementedError` explicitly.

### Recon findings (2026-10-24, four parallel Sonnet scouts)

**Trace sinks**
- `emitter.ScoreSink` is already a neutral protocol. However, `LangfuseSink`
  reads `trace_id`, `data_type` and `comment` from untyped metadata, and it
  drops provenance.
- Failure counters are module-global.
- The Langfuse alias table has three copies: the dojo, mailroom
  `observability/scores.py`, and the sandbox fallback in `eval/tracing.py`.
  The dojo copy must be the single source.
- Judge score names are hyphenated (`mailroom-pipeline-judge` / `-quality`).
  Keep them as they are, because the visualizer reads them.
- The sandbox already has a second sink (Braintrust), but it is hard-coded as
  an `if` branch in the consumer.
- Phoenix is read-only today.

**Family scorers**
- Contract gaps, now tracked in `CONTRACTS.planned`:
  - Enron has no CI or per-class P/R/F1, and it counts an `"error:"`
    pseudo-label in its stats.
  - `maud_extraction` has its own shape, with no `accuracy`/`n`/CI.
  - `docclass` without a subclass has no `exact_match` or `confusion`, and it
    ignores `valid=` for doc_type.
  - `subtype` does not canonicalize aliases.
- There is a circular import between `content_scoring` and `tasks`.
- `content_scoring` pulls in `field_scoring` and `scorecard_honesty` only to
  build `NON_EXTRACTION_KEYS`.

**Live callers**
- Only intake and extraction are scored by the dojo inside `llm-mailroom`.
- The sandbox calls `score_task` only for `docclass` (fallback) and `legalbench`.
- No consumer calls `enron_*`, `maud_*` or `asr.score_transcription` yet. The
  pipeline package is meant to become their caller.

**Packaging**
- llm-mailroom pins `llm-dojo-scoring @ git+…@v0.22.0`. A
  `bump-dojo-scoring.yml` workflow polls `releases/latest`, so pipeline tags
  must be prefixed.
- The sandbox vendors the dojo (`vendor/`, `scripts/sync_vendor.py`,
  `fetch-deps`) and needs a third vendor entry.
- eval-environment resolves the dojo transitively.
- The dojo repo has no `.github/` workflows.
