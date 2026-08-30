# Changelog

All notable changes to `llm-dojo-scoring` are documented here.
Format based on Keep a Changelog; versioning is SemVer.

## [Unreleased]

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
- Package version **0.10.0**. Consumer pin:

  ```
  llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.10.0
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
- Package version **0.9.0**.

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
