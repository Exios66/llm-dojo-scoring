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

## Completion, ITT, cost, serving (#21)

`summarize_run_completion` always emits `n_attempted`, `n_completed`,
`n_errored`, `completion_rate`, and an error-class histogram. LengthFinish
variants bucket as `LengthFinish`; context-window overflows as
`context_overflow`.

Quality aggregates name the population:

- `quality_mean_completed` — scored / completed-only
- `quality_mean_itt` — intention-to-treat: attempted docs, errors as 0

Cost helpers (`estimate_for_record`, `tokens_summary`) always stamp
`cost_basis`: `busy_window` or `billed_incl_cold`. Mixing both in one
table raises. `serving_kind` stays `modal` / `api` / `local` — Modal is
not remapped to local.

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
