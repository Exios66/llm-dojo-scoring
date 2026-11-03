# llm-dojo-scoring documentation

The docs are grouped by purpose. The package layout itself is described in
[`llm_dojo_scoring/README.md`](../llm_dojo_scoring/README.md).

## Guides: using the Dojo

| Doc | Read it for |
|:---|:---|
| [`guides/SCORING.md`](guides/SCORING.md) | How every score is computed: field types, entity lists, classification, factuality audit, task keys |
| [`guides/COMPARABILITY.md`](guides/COMPARABILITY.md) | Scorer-release guards, the release ledger, and `dojo-rescore` |
| [`guides/PUBLIC_API.md`](guides/PUBLIC_API.md) | The supported surface other repos rely on, from the consumer scan |
| [`guides/MIGRATION.md`](guides/MIGRATION.md) | Moving a pipeline project onto the Dojo; the v0.26.0 subpackage layout |
| [`guides/PROMPTS.md`](guides/PROMPTS.md) | The importable prompt catalog and frozen eval-environment lineage |
| [`guides/GRID_REPORTS.md`](guides/GRID_REPORTS.md) | Specialist grid reports for local → Modal GPU studies |
| [`guides/UPDATE_AWARENESS.md`](guides/UPDATE_AWARENESS.md) | Opt-in release discovery and `dojo-version` |
| [`guides/RELEASES.md`](guides/RELEASES.md) | Cutting and publishing a release with `scripts/release.py` |

## Schemas: what the dataset rows mean

| Doc | Covers |
|:---|:---|
| [`schemas/EXTRACTION_SCHEMAS.md`](schemas/EXTRACTION_SCHEMAS.md) | Live extraction schemas for the five mailroom-dataset classes, including the CMS source-table mapping |
| [`schemas/GT_METADATA.md`](schemas/GT_METADATA.md) | Hub `gt_fields` parsing, `gt_presence` and per-class label scoping |
| [`schemas/CUAD_SCHEMA.md`](schemas/CUAD_SCHEMA.md) | CUAD: 41 categories, families, questions, JSON Schema |
| [`schemas/MAUD_SCHEMA.md`](schemas/MAUD_SCHEMA.md) | MAUD: the 22 questions, allowed answers and grammar |
| [`schemas/MAUD_LABELS.md`](schemas/MAUD_LABELS.md) | MAUD answer-class catalogs (no guessing on GT labels) |
| [`schemas/CORPORATE_RECORD_SCHEMA.md`](schemas/CORPORATE_RECORD_SCHEMA.md) | Per-subclass corporate-record contracts and the label audit |

## Contracts: what a score means and how it is emitted

| Doc | Covers |
|:---|:---|
| [`contracts/METRIC_IDS.md`](contracts/METRIC_IDS.md) | Metric identity by doc class: which scores may be compared |
| [`contracts/SCORECARD_HONESTY.md`](contracts/SCORECARD_HONESTY.md) | Fail-closed GT, format vs extraction, completion and cost, captured knobs |
| [`contracts/SANDBOX_SCORING.md`](contracts/SANDBOX_SCORING.md) | Sandbox MAUD/CUAD rubrics and the v0.26.0 contract truth corrections |
| [`contracts/REVIEWER_SCORING.md`](contracts/REVIEWER_SCORING.md) | Decision/LLM reviewer records, risk bounds, calibration, routing, and cost |
| [`contracts/ARCHIVE_SCORING.md`](contracts/ARCHIVE_SCORING.md) | The archivist scoring block and audit row |

## History: proposals and status records

These docs record decisions and their status when they were written. They are not kept current. The CHANGELOG
is the record of what shipped.

| Doc | Records |
|:---|:---|
| [`history/CORE_ENGINE_TRANSFER.md`](history/CORE_ENGINE_TRANSFER.md) | DMR-091 core evaluation engine transfer proposal |
| [`history/FINAL_QUALITY_TRANSFER.md`](history/FINAL_QUALITY_TRANSFER.md) | DMR-091 final primary quality proposal |
| [`history/PRIMARY_ENGINE_OWNERSHIP.md`](history/PRIMARY_ENGINE_OWNERSHIP.md) | Primary scoring ownership as of 0.23.0 |
| [`history/ISSUE_ALIGNMENT.md`](history/ISSUE_ALIGNMENT.md) | Issue-by-issue alignment as of v0.19–v0.22 |
| [`history/TODOS.md`](history/TODOS.md) | Connected-repo TODOs at the time of the prompt-catalog transfer |
| [`history/plans/`](history/plans/) | Implementation plans |

Open work that is still being tracked lives in [`plans/BUG_SWEEP.md`](plans/BUG_SWEEP.md), not under history.

`assets/readme/` holds the generated README artwork (`generate.py`).
