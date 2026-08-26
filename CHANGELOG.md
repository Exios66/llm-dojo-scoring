# Changelog

All notable changes to `llm-dojo-scoring` are documented here.
Format based on Keep a Changelog; versioning is SemVer.

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
