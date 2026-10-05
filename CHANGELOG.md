# Changelog

All notable changes to `llm-dojo-scoring` are documented here.
Format based on Keep a Changelog; versioning is SemVer.

## [0.19.1] - 2026-10-05

### Added

- **Frozen `production_prompts` v1 lineage** — the five eval-environment
  frozen specialist stems (`mailroom-dataset-v1`, frozen
  2026-09-26T05:09:29+00:00) are now importable from the dojo prompt catalog
  as `get_prompt(<agent>, family="production_prompts")`, sha256-pinned per
  record (`PromptRecord.sha256`; three byte-identical to the sandbox
  `config/prompts/<stem>.txt` freeze). Stored separately from the `docclass`
  family. `tests/test_production_prompts.py` recomputes every digest from the
  imported text.
- **Dojo re-freeze of two `production_prompts` v1 records** — CodeRabbit
  PR #27 follow-up, applied in-repo only (upstream mirrors untouched):
  `correspondence_specialist` no longer emits the unregistered
  `communication_type` token `other` (fallback is null per the registered
  8-token vocabulary); `corporate_records_specialist` keeps `filing_number`
  null for subsidiary schedules whose only number is a parent-agreement
  exhibit ID. Provenance comments, catalog pins, docs, and tests updated to
  the corrected bytes.

### Notes

- Connected-repo follow-ups for the frozen prompt mirrors (eval-environment
  re-freeze scripts, sandbox lineage mirror, downstream imports) are tracked
  in [`docs/TODOS.md`](docs/TODOS.md).

## [0.19.0] - 2026-10-04

Align scoring contracts with
[mailroom-issues #236](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/236),
[#237](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/237),
and [#238](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/238),
and close remaining honesty gaps in
[llm-dojo-scoring #19](https://github.com/Exios66/llm-dojo-scoring/issues/19),
[#20](https://github.com/Exios66/llm-dojo-scoring/issues/20), and
[#21](https://github.com/Exios66/llm-dojo-scoring/issues/21), with the
v0.19.0 release-completion patch: hash-chain parity with llm-mailroom,
per-document suite emission for all five live classes, metric identity
completion, and specialist grid reports.

### Fixed

- **Hash-chain parity with llm-mailroom** — `archive.canonical_json` now
  serializes byte-identically to llm-mailroom
  `src/schemas/audit.py::compute_audit_hash`
  (`json.dumps(sort_keys=True, default=str)`, `datetime` → `isoformat()`).
  The previous compact-separator form produced a different `entry_hash`
  for the same row, so a dojo-formatted `archived` row failed
  `verify_chain` in llm-mailroom. `tests/test_archive_scoring.py` carries
  the inline mailroom oracle plus a verification round-trip.
- **Hash fixture** — `test_issue_236_example_payload_hash_is_stable` now
  pins the llm-mailroom digest. The digest printed in mailroom-issues
  #236 is not reproducible from the payload as shown (noted in
  `docs/ARCHIVE_SCORING.md`).
- **Plain extraction paths carry format scores** — batch `score([...])`
  always emits `schema_valid` / `parse_ok` / `schema_adherence`;
  `score_document()` returns the full per-document payload (flattened
  `overall_score`, field-micro P/R/F1/F2, class extras, `metric_id`,
  provenance). Single-doc `score(dict)` keeps the historical
  `ExtractionScoreResult` unless `detailed=True` (#18 alignment).
- **Insurance single-document extras** — `determination_consistency`,
  `amount_exactness`, and `schema_promotion_gate` now run on
  `score_document()` for one claim, not only in batch.
- **Content-only GT no longer suppressed** — correspondence with only
  `content_topic` / `sentiment_label` and merger with only
  `maud_clause_labels` score their content metric; triage-only contract
  rows stay `unscorable` (#16 unchanged), and a document with no nonempty
  expected field keeps `overall_score = None`.
- **Metric identity completed for all five live classes** —
  `_CLASS_METRIC_IDS` covers contract, merger_agreement, corporate_record,
  correspondence, and insurance_claim; F2 is allowed for each; Enron
  topic/sentiment ids are mapped; `metric_id_allowed()` added (#17).
- **`resolve_cost_basis`** — reject a table that mixes labeled and
  unlabeled `cost_basis` / `usd_basis` rows. Wholly unlabeled inputs
  still stamp the default (`busy_window`).
- **Retired-class drift** — `config.RETIRED_DOC_CLASS_KEYS` now includes
  `compliance_filing` (retired; llm-mailroom `taxonomy.yaml` has no such
  class). The merger agreement specialist remains its own class/suite —
  never an alias of contract — and the compliance specialist is never on
  the live roster.
- **Hub `gt_fields` metadata is parsed and scoped per document type** —
  stringified `"[]"` / `"{}"` values are empty (no phantom FN), `gt_presence`
  `not_applicable` / `schema_documented_absence` fields are never required
  events, and annotation stats / other classes' fields never reach extraction
  scoring. `N/A` date placeholders are empty, and CUAD label spans with no
  alphanumeric content (`[*]`, `____`, `.`) are omitted from presence
  expectations. `pending_annotation` (label backfill not yet run) is treated
  as absent, so stale values on pending fields are never scored. A mis-passed
  class-label string fails closed (`gt_wrong_schema`) instead of crashing.
  Perfect-prediction replay over the
  **full corpus** (both splits, 3,302 rows, 19,924 extraction events):
  **0 FN / 0 FP / 0 spurious fills / 0 F1 or presence misses**; 91
  triage-only contract rows stay `unscorable`.

### Added

- **`llm_dojo_scoring.gt_metadata`** + **`docs/GT_METADATA.md`** —
  `parse_gt_fields`, `scoring_gt_fields`, `derive_presence_from_gt`,
  `is_empty_value`, `parse_json_container`; CUAD label spans become presence
  expectations (placeholder spans skipped); raw clause items are presence
  candidates (multi-sentence quotes are not lost to disaggregation). Tests:
  `tests/test_gt_metadata.py`.

- **`llm_dojo_scoring.grid`** — L4-style specialist grid reports
  (`build_grid_report`, `grid_scorecard`, `GridDocument`,
  `GridExperiment`): quality / `ok / n` / p50 latency / `$` per ok
  document, pooled serving efficiency (error rate, docs/min, tokens/s/GPU,
  GPU `$`/doc), and busy-window vs metered session cost. Missing metered
  input renders `n/a`; one row never mixes `metric_id`s.
- **`format_audit_entry` / `prepare_archivist_handoff`** — calculate and
  format the hash-chained `archived` audit row (hash version 2) that is
  passed to the archivist. The templated row is always handed through;
  `archivist_sign_off` files it as final only when the hash matches and
  the pipeline steps for that document need no revision (report → judge
  → archive; happy-path nodes on a successful job).
- **`docs/GRID_REPORTS.md`** and **`docs/ISSUE_ALIGNMENT.md`**.
- **Taxonomy authority fixture** — `tests/fixtures/taxonomy_field_types.json`
  + `tests/test_live_roster_parity.py`: the five live field maps pinned to
  llm-mailroom `taxonomy.yaml` blob
  `ca297bd8e55e62b79ee452b02b65926b5032bdf1`, with roster / merger /
  retirement guards and per-document payload tests.

- **`llm_dojo_scoring.archive`** — `score_archive_block` returns the
  archivist `detail.scoring` payload (method, field map SHA, overall
  score, schema validity, per-field scores, and field-micro P/R/F1/F2
  with TP/FP/FN). `upsert_archive_scoring` replaces the block for a
  `doc_id` and never appends a second row. `archive_entry_hash` is hash
  version 2 (SHA-256 of canonical JSON).
- **`docs/ARCHIVE_SCORING.md`** — example archive row and scoring block;
  sample numbers are not a measured run.
- **`merger_agreement_specialist`** profile / suite bound to
  `MergerAgreementExtraction`.
- **`docs/SCORECARD_HONESTY.md`** — MAUD collapsed GT (#19), format vs
  extraction and empty-field credit (#20), completion / ITT / `cost_basis`
  / honest `serving_kind` (#21).
- **`score_empty_field_contract`** — correctly-empty fields score 1.0
  without entering archive `overall_score`; spurious fill is a penalty.
- **`canonical_error_class` / `resolve_cost_basis`** — LengthFinish and
  context-overflow histogram buckets; refuse mixed `cost_basis` in one
  table.
- **`llm_dojo_scoring.trace_knobs`** — capture `confidence` / `reasoning`
  as experimental knobs (`TraceKnobSettings`: `confidence_min`,
  `confidence_band`, `reasoning_routes_presence`,
  `compute_calibration_error`). Filed on `ExtractionScoreResult.trace`
  and archive `detail.scoring.trace`; never mixed into `overall_score`.
- **MAUD answer-class catalogs — no guessing on merger-agreement labels**
  (`llm_dojo_scoring/maud.py`, `docs/MAUD_LABELS.md`). The 152 published
  merger rows (17 test + 135 train) each carry per-question
  `valid_classes`; the scorer previously dropped them and treated any
  non-empty answer as valid on 21 of 22 questions. Now:
  - `parse_maud_labels` preserves each record's `valid_classes`; repeated
    Hub keys union their class surfaces instead of last-wins;
  - `is_valid_maud_answer` / `normalize_maud_answer` accept the record's
    own classes first, fall back to the corpus union, and fail closed for
    unknown questions;
  - `maud_question_catalog(doc_type)` returns the fully populated
    22-question catalog for `merger_agreement` and `contract` (specialist
    aliases accepted; unknown doc types raise `KeyError`);
  - `maud_valid_class_rate` is emitted by the contract / merger suites and
    by `score_maud_extraction`.
- `scripts/gen_maud_catalog.py` — deterministic catalog generator plus
  `--check` verification against the pinned dataset revision.
- `scripts/verify_gt_penalties.py` — portable perfect-prediction replay
  over the real Hub GT (both splits) asserting zero FN/FP/spurious and
  MAUD parity / class membership on all merger rows.
- `tests/test_maud_catalog.py` — pins catalog completeness, per-doc-type
  dicts, fixture consistency, canonicalization, component-wise validity,
  and fail-closed behavior.
- `catalog` optional extra (`pyarrow`, `huggingface_hub`) for the
  reproducibility scripts.

### Changed

- **Live extract roster** — `contract`, `merger_agreement`,
  `corporate_record`, `correspondence`, `insurance_claim`.
  `EXTRACT_CLASS_ALIASES` is empty; merger is not scored as a contract.
  `compliance_filing` is retired from the live extract roster (suites
  remain for historical traces).
- **`DEFAULT_FIELD_TYPES["merger_agreement"]`** — dedicated 10-field map
  (`effective_time`, `intent`, `subject_matter`, `keywords`; no
  `cuad_family` / `cuad_clauses`).
- **`score_extraction`** — never scores `confidence` / `reasoning`;
  skips empty lists and retired prompt-catalog keys that are not on the
  live field map.
- **Aligned classification** — `merger_agreement` ≠ `contract`.
- **`score_maud_extraction`** — distinct sub-question keys score
  normally; collapsed multi-answer GT (list, slash-string, or repeated
  Hub spans) is `gt_ambiguous` / unscorable per item; micro-accuracy
  over clean keys only; `n_ambiguous` always surfaced (#19).
- **`score_format_layer` vs field-micro** — prose-wrapped JSON is
  `parse_ok=0` and does not zero extraction on a structured payload
  (#20).
- **`summarize_run_completion`** — LengthFinish histogram; ITT quality
  ≠ completed-only (#21). `classify_serving_kind` keeps Modal as
  `modal` (not in `LOCAL_PROVIDERS`).
- `tests/fixtures/maud_valid_classes.json` now records the pinned dataset
  revision and per-question answered-row / distinct-set counts.
- Package version **0.19.0**; tests: **645 passed, 5 skipped** (the release
  commit ran 521; CodeRabbit regression tests and the MAUD catalogs were
  added before the tag).

## [0.18.0] - 2026-09-29

Live-run calibration from hub release gate
[LLM-Mailroom-Services/mailroom-issues#233](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/233)
and Exios66/llm-dojo-scoring #16–#22.

### Added

- **`llm_dojo_scoring.scorecard_honesty`** — fail-closed unscorable GT (#16),
  distinct `metric_id`s + incomparable comparisons (#17), format layer
  (`parse_ok` / `schema_valid` / `schema_adherence`) (#18–#20), MAUD
  `gt_ambiguous` / `n_ambiguous` (#19), run completion + ITT aggregates (#21),
  provenance stamps + export refusal (#22).
- **`docs/METRIC_IDS.md`** — doc class → allowed `metric_id` map (#17).
- **`tests/test_v018_scorecard_honesty.py`** — fixtures locking each failure mode.

### Changed

- **Contracts triage-only Hub GT** → `status: unscorable` (never quality 0.0);
  aggregates expose `n_scored` / `n_unscorable`; exporters label **unproven**.
- **`compare_serving`** — sets `incomparable` when local/API `metric_id` differs.
- **`classify_serving_kind`** — honest **`modal`** kind (removed `modal-vllm` → `local` remap).
- **`score_maud_extraction`** — skips ambiguous collapsed keys; micro accuracy over clean keys only.
- **`extraction_binary_metrics`** — spurious fill on empty GT counts as FP (configurable).
- **`classify_extraction_failure`** — format vs capability taxonomy (#20).
- **`cost.estimate_for_record` / `tokens_summary`** — stamp `cost_basis`.
- Registry: **`schema_valid`**, **`parse_ok`**, **`schema_adherence`** computed via
  `scorecard_honesty.score_format_layer` (T1); insurance schema promotion gate default 0.90.
- Package version **0.18.0**.


### Added

- **BERT fast-path registry surface (#106 / mailroom-ml intake gate)** — five
  emitter-only metrics registered for llm-mailroom `SCORE_CONFIGS`:
  `bert_pass`, `bert_sorter_agreement`, `bert_fail_soft`, `bert_elapsed_ms`,
  `fast_path_est_cost_usd` (with `metric_meta` citations). Covered by
  `tests/test_consumer_compat.py` and registry preservation tests.

### Changed

- **Classification alignment with live mailroom taxonomy** — doc-class regex
  order prefers `merger_agreement` over `contract`; retired classes
  (`court_opinion`, `due_diligence`) drop out of default normalization;
  `accuracy` / macro helpers skip `ERROR:` rows like sibling eval loops;
  `confusion_matrix` extends explicit label lists with observed classes;
  `macro_prf(..., normalize=False)` no longer zeroes when labels are raw.
- **Corpus prose** — mailroom-dataset v9 GT-closure pin (`46a4d3c2`, 3,302
  rows) and Enron sentiment population counts.
- **Prompt catalog** — docclass family versions renamed to
  `*_mailroom_prompts_v0` / `sorter_mailroom_v0` (templates synced from the
  Digital-Mailroom constellation monorepo).
- Package version **0.16.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.16.0
  ```

## [0.15.0] - 2026-09-14

### Added

- **`configure_from_taxonomy(taxonomy)` — the single taxonomy→settings wiring
  path** (hub #62). Consuming projects (llm-mailroom, llm-entity-extraction,
  agent-mailroom) load their own `taxonomy.yaml` and pass the parsed dict
  here; the package applies the `field_scoring:` block (including the new
  `type_bands` overrides and `factuality_verification`), equivalence sets,
  cost models, doc-class field-type maps, and display labels in ONE place.
  Honors the `LLM_DOJO_SCORING_CONFIG` env-file escape hatch (external file
  wins wholesale). Before, each consumer re-implemented the coercion
  (`_apply_taxonomy_settings` / `apply_taxonomy_settings` in three copies).
- **Mailroom glue promoted into the package** — `get_type_bands()`,
  `field_is_ambiguous(field_type, score)`, and `warm_embedding_model()`
  (off-document-path embedding preload, O-10) now live in
  `llm_dojo_scoring.field_scoring` instead of per-package shims.
- **`get_field_types(doc_class)` auto-resolves** from the taxonomy wired via
  `configure_from_taxonomy()` (captured in `Settings.doc_class_field_types`)
  — no need to pass the taxonomy on every call.
- **`FieldScoringSettings.type_bands`** — per-field-type ambiguous-band
  overrides (`"always"` / `"never"` / `(low, high)`), populated by
  `configure_from_taxonomy()`.
- New top-level re-exports so dependants can `from llm_dojo_scoring import
  ...` instead of deep submodule imports: `get_type_bands`,
  `field_is_ambiguous`, `warm_embedding_model`, `configure_from_taxonomy`,
  `get_field_types`, `normalize_text`, `parse_date`, `parse_money`,
  `score_category_presence`, `peel_non_extraction_fields`, `get_jaccard`,
  `INTAKE_SPAN_KEYS`.

### Changed

- Package version **0.15.0**. Consumers upgrade their pin to
  `llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.15.0`
  and can drop their local field-scoring shims.

## [0.14.0] - 2026-09-13

### Changed

- **Corpus identity migrated to `Lucius-Morningstar/mailroom-dataset`**
  (v1, canonically **v9** of the mailroom corpus family, 3,302 rows; issue
  hub #18). `CORPUS_ID` in `llm_dojo_scoring/corpus.py` now points at
  `mailroom-dataset` — the old `docclass-merged` repo is deleted, and the
  frozen v8 `mailroom-corpus` remains only as lineage baseline. Module
  titles/docstrings aligned (`mailroom-dataset corpus alignment`).
- **v9 GT surface:** `doc_bundles.py` headline grounding count updated to
  3,302 GT rows; `suites.py` docclass-family prose aligned; insurance
  subclass vocabulary notes the v8/v9 synthetic LOB lines (`property` /
  `auto`, HUB-028/HUB-041) alongside the CMS DE-SynPUF source tokens.
- **Docs sweep:** README/SCORING/tests module docstrings updated to the
  `mailroom-dataset` identity (historical `docclass-merged` prompt-family
  identifiers retained as product names).
- Package version **0.14.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.14.0
  ```

## [0.13.0] - 2026-08-30

### Changed

- **Pared extraction field maps** aligned to llm-mailroom **v0.6.0**
  (`EXTRACTION_SCHEMAS` / `taxonomy.yaml` field_types):
  - **Retired from live `DEFAULT_FIELD_TYPES`:** open-ended
    `key_obligations`, `termination_clauses`, `key_provisions`, long
    `key_points`, `referenced_communications`.
  - **Contracts / mergers:** key entities + `cuad_clauses` / `maud_clauses`
    checklists (11 fields).
  - **Corporate / correspondence / insurance:** semantic trio
    (`intent` / `subject_matter` / `keywords`); insurance also has
    `claim_checklist`.
  - Default `partial_gt_fields` / `containment_fields` match mailroom
    (checklists + `subject_matter`; no obligation dumps).
  - Diagnostics `list_*` headlines prefer `cuad_clauses` →
    `claim_checklist` → legacy `key_obligations`.
  - `score_category_presence` default field is `cuad_clauses`.
- Package version **0.13.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.13.0
  ```

  Typed-field scoring formulas are unchanged; only which fields enter the
  soft overall mean / field-micro board changed.

### Added

- `LEGACY_FULL_EXTRACTION_FIELD_TYPES` — pre-v0.6.0 maps that still score
  free-text obligation dumps (historical rescoring only).
- `suite.score(..., presence_expectations=...)` wires
  `extraction_category_presence` the same way Enron/MAUD extras are peeled.
- `tests/test_pared_extraction.py` + `docs/MIGRATION.md` §3i.
- `docs/SCORING.md` field-map tables updated to the pared schema.

## [0.12.2] - 2026-08-30

### Changed

- **Core dependency alignment with consumer packages** (`llm-mailroom`,
  `llm-entity-extraction`, `local-mailroom-sandbox`):
  - **`jellyfish>=1.0` is now a core dependency** (was optional-only).
    Mailroom already requires it for Jaro–Winkler name scoring; shipping it
    in dojo core stops silent `difflib` fallback when consumers install dojo
    alone.
  - **`embeddings` extra** now also includes `openai>=1.30` (alongside
    `sentence-transformers`) so the OpenAI embedding rescue path matches
    consumer `openai` pins.
  - New **`tracing` extra**: `langfuse`, `arize-phoenix`, `python-dotenv`,
    `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` — mirrors
    mailroom / entity optional tracing stacks.
  - New **`all` extra**: `embeddings` + `tracing` + `dev`.
  - The standalone `jellyfish` extra remains as a no-op alias for older
    install lines.
- Package version **0.12.2**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.2
  ```

  Recommended extras: `llm-dojo-scoring[tracing]` (mailroom) /
  `llm-dojo-scoring[embeddings,tracing]` (entity-extraction).

Scoring formulas from v0.12.1 / v0.12.0 / v0.11.0 / v0.10.0 are unchanged.

### Added

- `tests/test_consumer_compat.py` — network-free contract tests that pin the
  mailroom / entity / sandbox import surface, SCORE_CONFIGS names, and
  serving table/scorecard fields against this package.
- `docs/MIGRATION.md` §3h — consumer pin matrix and recommended extras.

## [0.12.1] - 2026-08-28

### Added

- **Serving scoring table + scorecard.** `compare_serving` / `get_suite("local_vs_api").score`
  now return `table` (every T0/T1 serving metric, including missing elements as
  `None`), `scorecard` (T0 headlines, T0+T1 dashboard, identity, cost
  calculations, `missing` list), `cost` (token × OpenRouter price-table
  breakdown per side), and `markdown`.
- **`serving_table_rows` / `serving_table_markdown` / `serving_scorecard` /
  `serving_cost_card` / `serving_card_markdown` / `emit_serving_scorecard`.**
  Emitter writes local and API values as separate runs (`run_id:local` /
  `run_id:api`) so `get_scorecard("local_vs_api")` does not average the two sides.
- Remaining serving T1 names documented in [`docs/SCORING.md`](docs/SCORING.md).

Honesty: missing metrics stay `None` (status `missing` / `local_only`);
local Ollama cost stays `None` without a price table.

### Changed

- Package version **0.12.1**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.1
  ```

Scoring formulas from v0.12.0 / v0.11.0 / v0.10.0 are unchanged.

## [0.12.0] - 2026-08-28

### Added

- **`local_vs_api` serving suite** — 26th profile, 11th bundle (`serving`).
  Compare a local run (Ollama / vLLM / llama.cpp / LM Studio) against an
  API-key run (OpenRouter / OpenAI / …) on the metrics both sides can
  actually record: TTFT, TPOT, e2e latency + p50/p95, decode and prefill
  throughput, requests/docs per second, queue time, error rate, token
  counts, and cost when a price table exists.
- **`llm_dojo_scoring.serving`** — `compare_serving`, `score_serving_run`,
  `split_local_api`, `pair_comparable_runs`, plus identity tags (model,
  quantization, dtype, GPU, max_model_len, provider, profile).
  `get_suite("local_vs_api").score(local_records, api_records)` is the
  importable entry point for dependents (including
  `local-mailroom-sandbox`).
- Registry T0 `ttft_seconds` / `tokens_per_second` and T1 serving names
  are **SERVING-only** — sorter headlines stay `accuracy` + `f1_macro`.

Honesty (do not invent KPIs):

- TTFT is `None` unless a first-token timestamp or explicit `ttft_seconds`
  is recorded. Never inferred from e2e / n_tokens.
- GPU / KV-cache / VRAM are local-only and stripped on API-key records.
- Local Ollama tags without an OpenRouter price table leave
  `estimated_cost_usd` `None` (no fabricated electricity).

### Changed

- Package version **0.12.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.0
  ```

Scoring formulas and T0 names from v0.10.0 / v0.11.0 are unchanged.

## [0.11.0] - 2026-08-27

### Added

- **`docs/SCORING.md`** — canonical scoring reference: per-agent T0/T1 from
  `headline_metrics` / `dashboard_metrics`, `DEFAULT_FIELD_TYPES` field maps,
  full `_HONEST_GAPS` prose, extraction confusion model, and every T0/T1
  metric with citation, inclusion, and ground-truth label.
- **Registry metadata** on `MetricDef`: `citation`, `inclusion`,
  `ground_truth` (`required` | `optional` | `structural` | `none`). Filled
  for all T0/T1 names. Emitter-only mailroom aliases keep `source: null` and
  `ground_truth: none`. `field_presence` documents that `score_extraction`
  does not emit it (honesty gap, not a new scorer).
- **`llm_dojo_scoring.prompts`** — importable catalog of production + latest
  docclass-merged templates (`get_prompt`, `list_prompts`, `PromptRecord`).
  Covers all 25 `DEFAULT_PROFILES` plus judge completeness / classification /
  correctness variants. Intake is `kind=deterministic`, archivist
  `procedural`, remaining `*_auditor` roles `proposed` with empty `text`.
  Metric bundle / field map stay in catalog metadata; snake_case T0/T1
  registry ids are forbidden in LLM bodies. Live colloquial “precision” /
  “completeness” and judge JSON keys that collide with registry names are
  flagged on `priming`, not rewritten.
- **`docs/PROMPTS.md`** — import API, production vs `family="docclass"`,
  non-LLM roles, anti-priming rule.

### Changed

- Package version **0.11.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.11.0
  ```

Scoring formulas and T0 names from v0.10.0 are unchanged.

## [0.10.0] - 2026-08-26

### Added

- **Field-micro extraction P/R/F1/F2** (`extraction_metrics.extraction_binary_metrics`)
  over (field, value) events. TP requires typed score `>= 1.0`; partial list
  matches stay in the soft `extraction_overall_score` mean. F2 uses van
  Rijsbergen β=2 (`5PR/(4P+R)`). Registered as `extraction_precision` /
  `extraction_recall` / `extraction_f1` (T0) / `extraction_f2` (T0) plus
  `entity_list_f1` (existing diagnostics `entity_list_raw_f1`).
- **Classification macro-PRF** (`classification.fbeta`, `macro_prf`).
  `binary_metrics` now returns `f2`. `per_class_stats` gains precision /
  recall / f1 / f2. `score_task("docclass")` and `score_task("pipeline")`
  attach `f1_macro` / `precision_macro` / `recall_macro` / `f2_macro` on
  doc_type and `subclass_*` macros when subclasses are present. Registry
  T1 names `precision` / `recall` / `f2` are filled with the macros.
- **Insurance claims extras** (`claims_consistency`): `determination_consistency`
  (approved ⇒ empty denial reasons; denied/partial ⇒ non-empty) and
  `amount_exactness` (money-field exact after the existing one-cent
  normalize). CMS GT homogeneity (all-approved) is pinned, not hidden.
- Correspondence **`content_topic_f1_macro` promoted to T0** and wired onto
  the extraction bundle override so `headline_metrics("correspondence_specialist")`
  includes it.

### Changed

- Sorter T0 `f1_macro` is actually computed (`classification.macro_prf`);
  registry `source:` for `f1_macro` no longer points at `binary_metrics`.
- Insurance honest-gap text shrinks from “scorer pending” to GT homogeneity.
- Corporate-records honest gap keeps “no *external* extraction benchmark”
  (39-row GT is enough for field-micro; do not claim CUAD/MAUD-grade coverage).
- Package version **0.15.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.15.0
  ```

Single-doc `get_suite(<specialist>).score(dict, dict)` still returns
`ExtractionScoreResult`. Batch extraction returns a dict with run-level
`extraction_*` keys when those are present.

## [0.9.0] - 2026-08-26

### Added

- **`llm_dojo_scoring.mailroom`** — live LLM-Mailroom / The-Mailroom
  pipeline contract (PRs #21–#29 / The-Mailroom #10). Live five-class
  roster, `unknown` routing token, `merger_agreement` → `contract`
  extract alias, Hub subclass inventories, Langfuse observation-type
  map, score transport aliases, `user_id` / `release` identity, and
  exact vs aligned HF classification (`merger_agreement` ≡ `contract`).
- **25th agent profile: `intake`** — pre-sorter intake clerk (span
  `normalize-intake`). Tasks `prepare`/`normalize`; dedicated `intake`
  bundle. Deterministic clerk gold (NFC, newline unify, NBSP, zero-width,
  C0, hyphen unwrap, blank-run collapse, horizontal-space collapse,
  trim) with LLM intake scored against the same gold. Handoff is
  `classify-document` (sorter). Computable — not emit-only.
- **CUAD / MAUD inventory fields** on the contracts / merger extraction
  maps: `cuad_family`, `merger_consideration`, `cuad_clauses`,
  `maud_clauses` (mailroom Hub specialist hardening).
- **Hub SEC form-body inventory** as the `compliance_filing` subclass
  catalog (zero corpus rows still; inventory is live extract enum).
- Registry: `extraction_verified_precision` (35-char Langfuse wire
  alias of `extraction_overall_verified_precision`),
  `mailroom-pipeline-judge`, `mailroom-pipeline-quality`,
  `exact_accuracy`, `aligned_accuracy`, `subclass_accuracy`.
  Family token `LIVE_SPECIALISTS`.
- Langfuse sync understands `document-pipeline` traces (filename,
  `expected_hf_class`, exact/aligned, `user_id`, `release`,
  `environment`, `normalize-intake` span stats). Config reads
  `LANGFUSE_RELEASE`, `MAILROOM_TRACE_USER_ID`, `LANGFUSE_FLUSH_AT` /
  `LANGFUSE_FLUSH_INTERVAL`, `OBSERVABILITY_ENVIRONMENT`.
- `LangfuseSink` emits the short transport alias on the wire.
- `list_suites(live_only=True)` hides retired specialists.
- `score_task("pipeline" | "document-pipeline")` for HF eval.
- **Enron content scorers** (`content_scoring.score_content_topic` /
  `score_sentiment`) — 11-topic + 3-class sentiment accuracy / macro-F1
  over correspondence GT differentiators (`content_topic`,
  `sentiment_label`). Wired as extras on `correspondence_specialist`.
- **MAUD per-question extraction** (`score_maud_extraction` /
  `score_task("maud_extraction")`) — exact / valid-class / presence /
  category over the 22 Hub `maud_clause_labels` keys (or specialist
  `'<Question>: <Answer>'` spans). Distinct from the legacy
  `maud_question` consideration-type classifier. Rebound onto
  `get_suite("merger_agreement")`.
- **WER/CER** (`asr.word_error_rate` / `character_error_rate`) —
  word- and character-level Levenshtein over reference length, plus
  `word_accuracy = max(0, 1 - WER)`. `pdf_transcriber` /
  `image_extractor` `score()` now returns these alongside token-F1.

### Changed

- **Retired live specialists** `court_opinions_specialist` and
  `due_diligence_specialist` (and their auditors) are flagged
  `ScoringSuite.retired=True`. Suites remain for historical traces and
  LegalBench; the sorter emits `unknown` instead of extracting.
- Insurance `claim_type` enum includes CMS source-table tokens
  (`pde`/`inpatient`/`outpatient`/`carrier`) plus legacy FNOL lines.
  `adjuster` null matches empty (CMS rows).
- Package version **0.9.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.16.0
  ```

Honesty mandate unchanged for remaining gaps: insurance
determination-consistency, retired court/DD, zero-row compliance, and
corporate_record (no external extraction benchmark). Enron topic/
sentiment, MAUD per-question extraction, and WER/CER now ship as real
scorers.

Suite: 294 passed / 5 skipped.

## [0.8.1] - 2026-08-25

### Added

- **`llm_dojo_scoring.corpus`** — single source mapping each mailroom
  class to the published
  [`Lucius-Morningstar/docclass-merged`](https://huggingface.co/datasets/Lucius-Morningstar/docclass-merged)
  schema (1,210 GT rows: 1,081 train / 129 test). Exports subclass
  catalogs, extraction-field sets, type-specific GT differentiators,
  CUAD (41) / MAUD (22 questions, 7 categories) clause surfaces,
  correspondence topics, and `normalize_corpus_subclass` /
  `suite_schema`.
- **Per-type subclass catalogs on every specialist suite**
  (`ScoringSuite.subclasses` / `differentiators` / `in_corpus`):
  CUAD 25-family (contract), MAUD consideration (merger_agreement),
  CMS DE-SynPUF source table `carrier|inpatient|outpatient|pde`
  (insurance_claim — orthogonal to specialist `claim_type`), Enron
  form (correspondence), record type (corporate_record). Native
  classes with zero rows (`due_diligence`, `compliance_filing`,
  `court_opinion`) stay honest: empty subclass catalog + gap note.

### Fixed

- **Hierarchical `docclass` scoring no longer forces every subclass
  through the MAUD consideration normalizer.** CUAD folder labels,
  CMS source tables, and Enron forms were collapsing to `"other"`.
  `score_task("docclass")` now scopes normalization to the *expected*
  parent class.
- **`get_suite("merger_agreement")` rebinds the MAUD catalog** instead
  of silently inheriting the contracts specialist's CUAD families.
  Shared `ContractExtraction` field map (incl. `document_name`) is
  unchanged; `suite.doc_type` / subclasses / differentiators match
  the requested class.
- Sorter default task is hierarchical `docclass` (not label-only
  `doc_class`). `normalize_subclass` without a parent type returns
  `"other"` so CUAD prefixes cannot rewrite unlabeled CMS / Enron
  values; pass `doc_type=` once the parent class is known.
- `DOC_CLASS_KEYS` includes `insurance_claim`. Subtype alias lookup
  strips non-alphanumerics so CUAD folder labels
  (`License_Agreements`, `Joint Venture _ Filing`) resolve.

### Changed

- Package version **0.8.1**.
- Honest-gap notes record corpus-absent types and the insurance
  CMS-table vs `claim_type` split (`adjuster` / `denial_reasons`
  are on the schema but empty in the current GT; all
  `coverage_determination=approved`).

Suite: 244 passed / 5 skipped (was 229/5).

## [0.8.0] - 2026-08-25

### Added

- **Dedicated per-agent scoring suites:** new module
  `llm_dojo_scoring.suites` — one importable `ScoringSuite` per pipeline
  agent so llm-mailroom / llm-entity-extraction call
  `get_suite("sorter").score(...)` / `get_suite("insurance_claim").score(...)`
  instead of assembling a profile + bundle + field-type map. Suites
  embed the mailroom taxonomy field-type maps, materialize an
  `agent:<name>` bundle, route `score()` to existing package functions
  (`score_task`, `score_extraction`, audit disagreement as
  `1 - overall_score`, transcription token-F1), and document honest
  gaps where type-specific scorers are still pending. Doc-type aliases
  cover all eight processed classes (incl. `merger_agreement` →
  contracts specialist).
- **24th agent profile: `insurance_claims_auditor`** — companion auditor
  for the seventh specialist, matching the KANBAN-062/063 per-specialist
  auditor pattern.
- **Registry family tokens** (`SPECIALISTS`, `AUDITORS`, `CLASSIFIERS`,
  `TRANSCRIBERS`) so a newly added specialist cannot be omitted from
  extraction `applicable_agents` (the v0.7.0 `insurance_claims_specialist`
  gap). `insurance_claims_specialist` is now on every extraction metric
  that the other specialists already had.
- **Diagnostic metrics registered:** `date_mae_days`, `money_mae_usd`
  (T1) and `duration_mae_days` (T2) — existing
  `diagnostics.extraction_diagnostics` surface, now emit-able from
  every specialist suite.
- **Per-specialist extraction extras** on the task and doc-type
  bundles (date/money diagnostics + hallucination) so every specialist
  has a dedicated extras set, not just contracts and court opinions.
- Sorter / reviewer / judge classification extras; audit metrics now
  apply to every named auditor + arbiter. `insurance_claim` added to
  the default classification label table.

### Changed

- Specialist profiles now bind their native `doc_bundle` (contract,
  corporate_record, …) so `resolve_doc_bundle()` no longer falls back
  to the task bundle for those seven agents. Agents without a native
  doc type (sorter, judge, …) still return `used_fallback=True`.
- YAML profile overlays persist `doc_bundle`. Bundle validation now
  checks `agent_overrides` extras against the registry (previously
  looked up the wrong key).
- Package version **0.8.0** (`pyproject.toml` + `__init__.__version__`).
- Langfuse env-file loader: stdlib KEY=VALUE fallback when
  `python-dotenv` is not installed (the previous silent no-op left
  explicit `langfuse.env` files unread).

Suite: 229 passed / 5 skipped (was 209/5).

## [0.7.0] - 2026-08-21

### Added

- **Document-type-aware metric bundles (KANBAN-067):** new module
  `llm_dojo_scoring.doc_bundles` with `DOC_TYPE_BUNDLES` — one bundle per
  processed document class (`contract`, `corporate_record`, `due_diligence`,
  `correspondence`, `compliance_filing`, `court_opinion`, `insurance_claim`,
  `merger_agreement`). Same `Bundle` shape and registry validation as task
  bundles, but a SEPARATE namespace (names prefixed `doc:`) so the task-bundle
  surface is untouched. Where real scoring logic exists today, type-specific
  metrics ship: contracts get laziness/hallucination overrides,
  court_opinions get LegalBench metrics. Where they don't, the bundle
  description says so in plain language (HONEST GAP: MAUD-derived merger
  scorers, Enron-derived demand-letter/email scorers, DE-SynPUF-grounded
  claims scorers all PENDING) instead of inventing numbers — the honest-gap
  mandate from issue #32. New scorers land by adding to the matching key;
  the registry is the modular extension point.
- **`AgentProfile.doc_bundle` + explicit-fallback resolver:** optional
  per-profile doc-type bundle field, plus
  `AgentProfile.resolve_doc_bundle(doc_type=None, *, fallback=True) ->
  tuple[Bundle, bool]`. Resolution order: explicit doc_type → profile's
  `doc_bundle` → task bundle with `used_fallback=True` (an EXPLICIT honesty
  marker for callers/dashboards — never a silent default); `fallback=False`
  raises rather than pretending. Additive-only: every v0.6.0 profile keeps
  its exact tasks/bundle/fallback/ground_truth (pinned by a regression test).
- **23rd agent profile: `insurance_claims_specialist`** (tasks extract,
  bundle extraction) — companion to llm-mailroom's insurance_claim document
  class shipped in Phase 1 of this card (mailroom commit `99536d8`).
  `test_bundles.py::test_default_profiles` re-pinned deliberately; the full
  doc-type surface + preexisting-profiles-unchanged regression live in
  `tests/test_doc_bundles.py` (16 new network-free pins).

Suite: 209 passed / 5 skipped (was 193/5).

## [0.6.0] - 2026-08-21

### Added

- Review/audit profile registry for the pipeline architecture alignment
  (KANBAN-062/063) — eight new agent profiles in `profiles.py`:
  - `sorter_reviewer` — Classification Review (tasks classify/review, bundle
    `classification`): the Lane A second-opinion reviewer after the sorter.
  - `contract_auditor`, `corporate_records_auditor`,
    `due_diligence_auditor`, `correspondence_auditor`,
    `compliance_auditor`, `court_opinions_auditor` — one named companion
    auditor per specialist (tasks verify/review, bundle `audit`, fallback
    `extraction`, ground-truth-free): dispatch targets for the audit-manager
    pattern.
  - `arbiter` — Judgment Arbitration (tasks verify/review, bundle `audit`,
    ground-truth-free): escalation lane when an in-pipeline judge verdict
    fails.
  Audit profiles never require ground truth (they verify specialist output,
  not GT fields). All bundles resolve eagerly; existing 14 profiles unchanged.

## [0.5.1] - 2026-08-21

### Added

- Registry completeness for the llm-mailroom SCORE_CONFIGS schema: all 12
  remaining mailroom score names are now registered, so `load_registry()`
  covers 100% of both consumers' emission surfaces (KANBAN-061):
  - T1 (score): `class_correct`, `stage_correct`, `extraction_correctness`,
    `extraction_needs_judge_review`, `expected_field_presence` (alias of
    `field_presence`), `extraction_overall_verified_precision` (alias of
    `verified_precision`), `extraction_hallucination_rate`
  - T2 (aggregate): `extraction_field_score`, `extraction_category_presence`,
    `completeness_label`, `extraction_correctness_label`
  - T3 (log): `classification_quality`

### Fixed

- `classification_quality` registered as numeric (it was briefly annotated
  as free-text); it is a NUMERIC Langfuse config in mailroom.

## [0.5.0] - 2026-08-21

### Added — unified scoring layer (KANBAN-061, entity-extraction issue #27)

- **`registry`** — YAML-backed metric definitions registry: every metric name
  mapped to a tier (`T0 HEADLINE` / `T1 CORE` / `T2 DEEP` / `T3 LOG`), units,
  aggregation, applicable agents, and the existing package function that
  computes it. Built-in default embeds the full current surface including all
  37 flat llm-mailroom `SCORE_CONFIGS` names as preserved aliases/notes.
  Override via `LLM_DOJO_SCORING_REGISTRY` env var or explicit path.
- **`bundles`** — nine pre-built metric bundles (classification, extraction,
  extraction_open, cost, factuality, laziness_detection, audit, reporter,
  transcription) with fail-fast validation against the registry and optional
  per-agent overrides.
- **`profiles`** — agent profile system: 14 default profiles (sorter, six
  specialists, judge, boss, pdf_transcriber, image_extractor, archivist,
  audit_agent) with task-derived bundle resolution, fallback bundles, and
  YAML overlay via `LLM_DOJO_SCORING_PROFILES`.
- **`emitter`** — unified score emitter: `ScoreRecord`, network-free
  `LocalManifestSink` (JSONL), credential-checked inert-unless-configured
  `LangfuseSink`; `emit_score` / `get_scorecard(min_tier=...)` /
  `compare_headlines`.
- **`pruning`** — tier-based dashboard filtering: `prune_metrics`,
  `dashboard_metrics(agent)` (profile-bundle ∩ tier cap),
  `headline_metrics(agent)` (strictly T0), `prune_records`.
- New exports in `__init__`; 37 new network-free tests
  (`tests/test_registry.py`, `tests/test_bundles.py`,
  `tests/test_emitter.py`). Full suite: 187 passed, 5 skipped.

### Unchanged

- All calculation modules and their APIs — this release is purely additive
  organization on top of the engine (Hungarian matching, embedding rescue,
  bootstrap CI, CUAD equivalences untouched).
