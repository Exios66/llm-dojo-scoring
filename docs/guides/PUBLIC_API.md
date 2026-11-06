# Supported public API

This page is the surface that other repositories rely on. A change to anything listed here is a
cross-package event: `llm-mailroom` and the `local-mailroom-sandbox` `vendor/` snapshot need a
coordinated bump. Everything else that `import llm_dojo_scoring` exposes is importable but is
**not** covered by this promise; it can be renamed or removed in a minor release after a
deprecation notice in `CHANGELOG.md`.

The lists come from `tests/fixtures/consumer_surface.json`, a static scan of the consumer
repositories made by `scripts/audit_consumer_surface.py`. `tests/test_public_api_doc.py` fails
when a name in that fixture is missing here, so regenerate the fixture first and then update this
page.

## Package root (`from llm_dojo_scoring import …`)

| Name | Defined in | Used by |
|:---|:---|:---|
| `__version__` | `__init__` | llm-mailroom |
| `accuracy` | `scoring.classification` | local-mailroom-sandbox |
| `agent_rubrics` | `scoring.agent_rubrics` | llm-mailroom |
| `aggregate_sandbox_scores` | `pipeline.sandbox_scoring` | local-mailroom-sandbox |
| `bootstrap` | `analysis.bootstrap` | llm-mailroom |
| `bootstrap_ci` | `analysis.bootstrap` | local-mailroom-sandbox |
| `classify_serving_kind` | `analysis.serving` | local-mailroom-sandbox |
| `configure` | `config` | llm-mailroom |
| `configure_from_taxonomy` | `config` | llm-mailroom |
| `contract_empty_payload` | `schemas.schema_contract` | llm-mailroom |
| `contract_violations` | `schemas.schema_contract` | llm-mailroom |
| `diagnostics` | `analysis.diagnostics` | llm-mailroom |
| `embed_texts` | `scoring.field_scoring` | llm-mailroom |
| `emit_serving_scorecard` | `analysis.serving` | local-mailroom-sandbox |
| `Emitter` | `metrics.emitter` | local-mailroom-sandbox |
| `EntityListScore` | `scoring.field_scoring` | llm-mailroom |
| `exact_match` | `scoring.classification` | local-mailroom-sandbox |
| `ExtractionScoreResult` | `scoring.field_scoring` | llm-mailroom |
| `field_scoring` | `scoring.field_scoring` | llm-mailroom |
| `get_ambiguous_band` | `scoring.field_scoring` | llm-mailroom |
| `get_field_types` | `scoring.field_scoring` | llm-mailroom |
| `get_suite` | `scoring.suites` | llm-mailroom, local-mailroom-sandbox |
| `headline_metrics` | `metrics.pruning` | local-mailroom-sandbox |
| `is_entity_list` | `scoring.field_scoring` | llm-mailroom |
| `legalbench_scoring` | `scoring.legalbench_scoring` | llm-mailroom |
| `list_suites` | `scoring.suites` | llm-mailroom |
| `load_registry` | `metrics.registry` | llm-mailroom |
| `LocalManifestSink` | `metrics.emitter` | local-mailroom-sandbox |
| `normalize_text` | `scoring.field_scoring` | llm-mailroom |
| `pipeline_scoring` | `pipeline.pipeline_scoring` | llm-mailroom, The-Mailroom |
| `score_category_presence` | `scoring.field_scoring` | llm-mailroom |
| `score_extraction` | `scoring.field_scoring` | llm-mailroom, local-mailroom-sandbox |
| `score_serving_run` | `analysis.serving` | local-mailroom-sandbox |
| `score_task` | `scoring.tasks` | local-mailroom-sandbox |
| `ScoreRecord` | `metrics.emitter` | local-mailroom-sandbox |
| `suite_for_doc_type` | `scoring.suites` | local-mailroom-sandbox |
| `warm_embedding_model` | `scoring.field_scoring` | llm-mailroom |

## Archive scoring contract (mailroom-issues #237 and #238)

Not yet called by a consumer, but these are the functions the llm-mailroom archivist is
meant to use to file one scoring block per document. Treat them as stable:

- `score_archive_block` (`pipeline.archive`)
- `upsert_archive_scoring` (`pipeline.archive`)
- `format_audit_entry` (`pipeline.archive`)
- `prepare_archivist_handoff` (`pipeline.archive`)
- `archivist_sign_off` (`pipeline.archive`)
- `archive_entry_hash` (`pipeline.archive`)
- `ARCHIVE_HASH_VERSION` (`pipeline.archive`)
- `ARCHIVE_SCORING_METHOD` (`pipeline.archive`)

`score_archive_block` gained keyword-only `doc_subclass=` in 0.27.0 and five block keys
(`headline_score`, `headline_metric`, `unlabeled_fields`, `entity_list_f1`, `scorer`;
listed in `ARCHIVE_SCORING_V027_KEYS`). Every earlier key keeps its meaning, and
`validate_audit_entry` does not require the new keys on older rows.

Reading the new keys (0.27.1):

- `entity_list_f1` is null whenever the block is not countable, and `unlabeled_fields` is
  null when `reason` is `gt_missing`. A block never carries them for a row it calls
  unscorable for lack of ground truth.
- `status` is the field-map verdict and stays unchanged for MAUD and CUAD rows, which have
  no field-map ground truth. Rows with a non-null `headline_score` are judged by the
  headline; readers that filter on `status == 'scored'` must also keep rows whose
  `headline_score` is not null.
- With `expected_subclass=None`, `doc_subclass` derives the CMS `cms_source_table` for
  insurance rows, as `score_document` does. When both are given, `expected_subclass` wins
  for the field-map score.
- The tiered keys are computed behind a guard: if they fail they are null and every
  earlier key is unaffected.

## Document scoring (0.27.0, unified audit row)

Pinned by `tests/fixtures/contract_surface.json` until consumers adopt them. Added for
llm-mailroom's scoring node family and the sandbox's `score_extraction_row`
wrapper (spec: llm-mailroom `docs/superpowers/specs/2026-11-03-unified-audit-row-design.md`).
Treat as stable:

- `score_document(doc_type, predicted, expected, *, doc_text=None, doc_subclass=None,
  expected_subclass=None, schema_lookup=None) -> dict` (`scoring.doc_scorers.dispatch`):
  the sandbox's `score_extraction_row` payload with every field score unchanged, plus
  `scorer` (`doc_type`, `module`, `subclass`, `tiers_run`) and the type extras
  (correspondence topic/sentiment, insurance claims consistency). Adherence is checked
  on the prediction as given, and `None` is a parse error. It never raises on a bad
  prediction or a bad field value: a failing type extras or headline keeps the tier 0
  score and appends `+extras-failed` to `scoring_method`.
- `assess_extraction_payload(predicted, doc_type, doc_subclass=None, *, schema_lookup=None)`
  (`pipeline.sandbox_schema_adherence`): parse and schema-adherence facts. Pydantic models
  come from `schema_lookup(doc_type)`, so the dojo never imports mailroom.
- `get_doc_scorer(doc_type)` (`scoring.doc_scorers`): the per-type scorer (tiers 1 and 2),
  `generic` for unknown types; specialist agent names resolve like their doc type.

## Modules imported directly

Consumers import these modules, or names from them, by path. Both the subpackage path and the
pre-0.26 flat path work (see [MIGRATION.md](MIGRATION.md#legacy-flat-import-paths)).

| Module | Names used | Used by |
|:---|---:|:---|
| `llm_dojo_scoring.analysis.bootstrap` | 5 | llm-mailroom |
| `llm_dojo_scoring.analysis.cost` | 1 | llm-mailroom |
| `llm_dojo_scoring.analysis.diagnostics` | 6 | llm-mailroom |
| `llm_dojo_scoring.analysis.experiment` | 4 | local-mailroom-sandbox |
| `llm_dojo_scoring.analysis.serving` | 9 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.config` | 1 | llm-mailroom |
| `llm_dojo_scoring.metrics.emitter` | 1 | local-mailroom-sandbox |
| `llm_dojo_scoring.metrics.pruning` | 1 | llm-mailroom |
| `llm_dojo_scoring.metrics.registry` | 1 | llm-mailroom |
| `llm_dojo_scoring.metrics.scorecard_honesty` | 3 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.pipeline.archive` | 3 | llm-mailroom |
| `llm_dojo_scoring.pipeline.intake` | 7 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.pipeline.mailroom` | 8 | Mailroom-Corpus-EDA, llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.pipeline.pilot_labels` | 8 | llm-mailroom |
| `llm_dojo_scoring.pipeline.pilot_summary` | 2 | llm-mailroom |
| `llm_dojo_scoring.pipeline.pipeline_scoring` | 4 | llm-mailroom |
| `llm_dojo_scoring.pipeline.pipeline_verdict` | 1 | llm-mailroom |
| `llm_dojo_scoring.pipeline.sandbox_scoring` | 15 | local-mailroom-sandbox |
| `llm_dojo_scoring.prompts` | 8 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.corporate_record_relabel` | 1 | Mailroom-Corpus-EDA |
| `llm_dojo_scoring.schemas.corporate_record_schema` | 6 | Mailroom-Corpus-EDA, local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.corpus` | 3 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.equivalences` | 1 | local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.gt_metadata` | 1 | Mailroom-Corpus-EDA |
| `llm_dojo_scoring.schemas.intents` | 4 | llm-mailroom |
| `llm_dojo_scoring.schemas.maud_schema` | 1 | local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.schema_contract` | 1 | local-mailroom-sandbox |
| `llm_dojo_scoring.schemas.sorter_guide` | 1 | llm-mailroom |
| `llm_dojo_scoring.scoring.agent_rubrics` | 6 | llm-mailroom |
| `llm_dojo_scoring.scoring.content_scoring` | 1 | llm-mailroom |
| `llm_dojo_scoring.scoring.extraction_metrics` | 1 | local-mailroom-sandbox |
| `llm_dojo_scoring.scoring.field_scoring` | 17 | llm-mailroom, local-mailroom-sandbox |
| `llm_dojo_scoring.scoring.field_support` | 2 | llm-mailroom |
| `llm_dojo_scoring.scoring.legalbench_scoring` | 6 | llm-mailroom |
| `llm_dojo_scoring.scoring.suites` | 1 | llm-mailroom |

The per-name detail (which file and line uses each attribute) is in the fixture.

## Patch targets

Consumer tests patch these names, so they must stay patchable at this path:

- `llm_dojo_scoring.embed_texts`

## Dispatch entry points

Consumers pick scorers through these, so the suite and task keys they accept are part of the
contract too: `get_suite`, `score_task`, `suite_for_doc_type`.

## Scan coverage

| Repository | Scanned |
|:---|:---|
| Mailroom-Corpus-EDA | yes, at `8d730fc1` |
| eval-environment | no: path does not exist |
| llm-mailroom | yes, at `a7d7bf0b` |
| mailroom-ml | yes, at `bd8557a8` |
| local-mailroom-sandbox | yes, at `93b76d42` |
| The-Mailroom | yes, at `8b0bee5b` |
