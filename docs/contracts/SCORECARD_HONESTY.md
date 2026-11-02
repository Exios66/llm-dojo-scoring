# Scorecard honesty (#19–#21)

Companion to the v0.18 live-run calibration and the archive contract in
[`ARCHIVE_SCORING.md`](ARCHIVE_SCORING.md). These rules keep quality,
format, and fleet reliability from collapsing into one number.

## MAUD collapsed GT (#19)

`score_maud_extraction` accepts **distinct sub-question keys** (Hub names
such as `No-Shop` vs `Fiduciary exception:  Board determination (no-shop)`
vs `Breach of No Shop`). Coverage and micro-accuracy use **clean keys
only**. `n_ambiguous` is always emitted.

When the dataset collapses several answers onto one Hub key — a list, a
`Yes / Strict liability / Reasonable standard` string, or two spans that
parse to the same key with different answers — that item is
`gt_ambiguous` / `unscorable`. The scorer does not pick an arbitrary
single-answer match. If every expected key is ambiguous, the document
status is `unscorable` with `reason: gt_ambiguous`. Mixed rows stay
`scored` on the clean keys.

## Format vs extraction and empty fields (#20)

`parse_ok` / `schema_adherence` (`score_format_layer`) are not field
extraction. Prose-wrapped JSON is a **parse fail**. If a caller still has
a structured payload, field-micro P/R/F1 is scored on that payload and is
**not zeroed** because parse failed. `classify_extraction_failure` tags
`format_parse` / `format_schema` vs `capability_miss`.

Empty-field contract (`score_empty_field_contract`, also on
`extraction_binary_metrics`):

| GT | Prediction | Overall / archive mean | Field-micro | Empty-field credit |
|---|---|---|---|---|
| empty | empty / missing | skipped (not in `overall_score`) | not FN | **1.0** |
| empty | spurious value | skipped | **FP** (configurable) | 0.0 |
| nonempty | miss | scored | FN | n/a |

Archive `overall_score` remains the unweighted mean of **nonempty**
expected fields so a correspondence row with ~18 empty keys cannot inflate
the mean.

## Specialist suite emission (v0.19)

Every extraction suite emits its class scores on the per-document surface:

- `suite.score_document(expected, predicted)` returns one payload per
  document: `extraction`, flattened `overall_score`, field-micro
  P/R/F1/F2, `schema_valid` / `parse_ok` / `schema_adherence`, class extras
  (content/MAUD, insurance `determination_consistency` / `amount_exactness`),
  `schema_promotion_gate` (every live class, `SCHEMA_PROMOTION_GATES`),
  `metric_id`, and `provenance`.
- Plain batch `score([...])` always carries `schema_valid` / `parse_ok`,
  computed over exactly the GT rows (a missing prediction counts as an
  unparsed row), plus `n_scored` / `n_unscorable` / `quality_mean` /
  `export_verdict` — GT-less rows are `unscorable`, never zeros.
- An unscorable single document still carries the format layer (it does
  not need GT) and its `schema_promotion_gate`.
- `score_document(..., metric_id=..., cost_basis=...)` checks both: a
  contradicting `metric_id` or a `cost_basis` outside `COST_BASIS_VALUES`
  raises `ProvenanceExportError`.
  The single-document `score(dict)` keeps the historical
  `ExtractionScoreResult` return unless `detailed=True` is passed.
- Content-only GT rows are scored on their content metric: correspondence
  with only `content_topic` / `sentiment_label`, merger with only
  `maud_clause_labels`. Triage-only contract rows (`contract_subtype` /
  `doc_type`, no scored field) stay `unscorable`, and a document with no
  nonempty expected field has `overall_score = None` — never a fabricated
  zero.
- Hub `gt_fields` metadata (union field dict + stringified `gt_presence`) is
  parsed and scoped to the document type's own schema before any of the
  above: `"[]"` / `"{}"` are empty, `not_applicable` /
  `schema_documented_absence` are never required events, and annotation
  stats never reach extraction. See [`GT_METADATA.md`](../schemas/GT_METADATA.md).

## Completion, ITT, cost, serving (#21)

`summarize_run_completion` always emits `n_attempted`, `n_completed`,
`n_errored`, `completion_rate`, and an error-class histogram. LengthFinish
variants bucket as `LengthFinish`; context-window overflows as
`context_overflow`.

Quality aggregates name the population:

- `quality_mean_completed` — scored / completed-only
- `quality_mean_itt` — intention-to-treat: attempted docs, errors as 0;
  unscorable docs (no GT) leave the denominator (`n_attempted_scorable`)

Cost helpers (`estimate_for_record`, `tokens_summary`) always stamp
`cost_basis`: one of `COST_BASIS_VALUES` (`busy_window`,
`billed_incl_cold`, or `token_price_estimate` when the records carry it).
Mixing two labels in one table raises, as does mixing labeled and
unlabeled rows. Wholly unlabeled inputs keep the default (`busy_window`).
Serving cost cards label USD computed from tokens × the provider price
table `token_price_estimate` (`COST_BASIS_TOKEN_PRICE`).
`validate_comparison_provenance` refuses any basis outside
`COST_BASIS_VALUES`, and refuses two legs whose bases differ (so a
price-table estimate is never compared with a metered figure).

Comparisons (`validate_comparison_provenance`, `validate_comparison_export`)
require every `PROVENANCE_KEYS` entry on both legs and equal, except the
`vary=` axis (present on both, may differ — `("serving_kind", "model_id")`
for local vs API) and `draw_seed`, which may be absent on both legs. `serving_kind` stays
`modal` / `api` / `local` — Modal is not remapped to local.

## Headline scope: which fields a class score covers (#95)

A class headline is only comparable with another class's headline when both
cover their whole live field map (`DEFAULT_FIELD_TYPES`). The merger
headline has historically been MAUD answer accuracy alone (`maud_clauses`),
and the correspondence GT carries only a few of its eleven fields, so neither
may sit unflagged beside a full-field score.

`metrics.scorecard_honesty.headline_scope(doc_class, field_counts, *, n_docs=None,
maud_only_docs=None, n_docs_with_fields=None)` reports:

| Key | Meaning |
| --- | --- |
| `headline_scope` | `"maud_only"` (every document scored on `maud_clauses` alone), `"mixed"` (merger: only *some* documents MAUD-only), `"partial"` (some live fields never carried GT), `"full"`, `"unknown"` (field data exists but no claim is possible), or `None` (nothing scored in the live map, no per-document context) |
| `headline_label` | Human label, e.g. `MAUD answers only (maud_clauses); not a field-level score`, `1 of 2 documents MAUD answers only; not a field-level score`, `3 of 11 fields carry GT (...)`, or the reason for `unknown` |
| `scored_fields` | field → number of scored documents |
| `unscored_fields` | live fields that no document scored (`None` for `unknown`) |
| `field_coverage` | share of live fields scored at least once (`None` for `unknown`) |
| `off_map_fields` | scored fields that are not in the live map (never count toward scope) |

Rules:

- A field counts as scored for a document only when its score is a real
  number (not `None`, not a bool). `field_counts` must be a mapping or a
  collection of names, never a `str` (`TypeError`); non-numeric or
  non-positive counts are skipped.
- Classes are stripped and lower-cased; `SPECIALIST_DOC_TYPES` names resolve.
- The scope is per document when `n_docs` / `maud_only_docs` are given
  (`maud_only_docs` = documents whose scored live fields are non-empty and
  all in `MAUD_HEADLINE_FIELDS`). One MAUD-only document beside a full-field
  one is `"mixed"`, never `"full"`. Without them the field-union rule applies.
- `"unknown"` is never silent: the class is unresolved (unknown specialist, or
  conflicting explicit `doc_class` values), some scored documents lack field
  data (`field data for 99 of 100 scored documents`), or no live field was
  scored. Rows with no field data at all make no scope claim.

`aggregate_quality_honest(rows, doc_class=...)` adds these keys when rows carry
`field_scores` (top level, `extraction.` or `scores.`); without `doc_class` the
result shape is unchanged. `specialist_grid_rows` adds `headline_scope`,
`headline_label`, `scored_fields` and `unscored_fields` **only on rows whose
scored documents carry field data** (`field_scores` or `scored_fields`, a list,
tuple, set or frozenset; a bare string is one field); a row without field data
has exactly the pre-#95 key set. The class comes from `doc_class`, the
specialist name, or `SPECIALIST_DOC_TYPES`.

The grid report marks MAUD-only and mixed scores with `†`, partial scores with
`‡` and unknown scores with `?`, each with a footnote naming what the score
covers. Footnotes are keyed on (specialist, scope, label); when one specialist
has several distinct notes each names its experiment(s), e.g.
`‡ **correspondence** (e1, e3): ...`.

## Confidence and reasoning knobs

`confidence` and `reasoning` are model-emitted traces, not extraction
fields. They never enter `overall_score` or field-micro F1.

`capture_trace_knobs` peels them into a stable `trace` payload (also on
`ExtractionScoreResult.trace` and the archive scoring block):

| Knob | Default | Effect |
|---|---|---|
| `capture_confidence` | true | Store the 0–1 score (or null) |
| `capture_reasoning` | true | Store `{summary, entries}` |
| `confidence_min` | null | Gate `below_min` when confidence is under the floor |
| `confidence_band` | null | Gate `in_band` for `[low, high)` |
| `reasoning_routes_presence` | true | CUAD presence may use `reasoning.entries` |
| `compute_calibration_error` | true | `|confidence − overall_score|` |
| `missing_confidence` | `absent` | `assume_1` / `assume_0` fill gating only |

Sweep with `configure(trace_knobs__confidence_min=0.7)` or a taxonomy
`trace_knobs:` block. Turning capture off stores nulls; it does not
score the keys as fields.
