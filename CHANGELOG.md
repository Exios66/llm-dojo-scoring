# Changelog

All notable changes to `llm-dojo-scoring` are documented here.
Format based on Keep a Changelog; versioning is SemVer.

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
