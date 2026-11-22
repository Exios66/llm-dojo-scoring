# Pain-point composite scoring

`llm_dojo_scoring.pipeline.pain_points` scores a pipeline run on two **penalty composites**, one
for classification and one for entity extraction, built around a client's stated operating
costs: the volume of documents a person has to review, errors, and misarchived documents. Each
document earns **penalty points** from 0 (correct and complete) to 4 (sent to a person when the
pipeline could have finished it). **Lower is better.**

The module is scorer-agnostic and record-based. It reads one `PainPointDocument` per document and
never loads rows, runs a pipeline or calls a scorer. It is deterministic, makes no network call
and writes nothing. Its only Dojo imports are `schemas.gt_metadata.is_empty_value` and
`analysis.bootstrap.bootstrap_ci`, so `local-mailroom-sandbox` can vendor the single file.

## Profile `amfam-v1`

`PROFILE = "amfam-v1"` names the client's ladder. `PenaltyScale` carries the points; its
defaults are this profile.

**A scale whose values differ from the defaults must carry its own `profile` id.** Building
`PenaltyScale(partial=0.5)` (or any other changed value) under `amfam-v1` raises `ValueError`
("a custom scale needs its own profile id"), so a custom scale can never be reported as the
client's numbers. Every numeric value must be finite (NaN and infinity are refused before the
ordering checks), the ladder order is enforced (a needless review is the worst outcome on both
composites, a wrong subtype costs less than a wrong class, `fabricated > low_recall > partial`),
and `low_recall_below` lies in (0, 1). `score_run`, `breakdown` and `compare` echo `profile`
and `scale` so a number can be traced to its scale.

## Classification ladder

Worst reason wins; every reason that applied is kept in `Outcome.reasons`.

| Points | Reason | When |
|---:|:---|:---|
| 4 | `unnecessary_review` | Stage `review`, expected stage archived (or absent) |
| 4 | `pipeline_failure` | `failed`, or the stage is not `archived` / `review` |
| 3 | `wrong_doc_type` | Archived, predicted class differs from the expected class (case- and space-insensitive), or is blank |
| 2 | `missed_review` | Archived, expected stage `review` |
| 1 | `wrong_subtype` | Right class, `subclass_correct is False`; not added when `wrong_doc_type` applies |
| 0 | `necessary_review` | Stage `review`, expected stage `review` |
| 0 | `correct` | None of the above |

A document without an expected class is excluded (`None`): a missing label is never scored as
correct.

## Extraction ladder

Only documents with an `extraction` row (the document's scored extraction, i.e. field truth) are
scored; the rest are excluded. Failure and review outcomes come first, exactly as above. Then:

| Points | Reason | When |
|---:|:---|:---|
| 3 | `fabricated` | Values were stated and none is supported: `correct == 0`, `near_miss == 0`, `invented > 0` |
| 2 | `low_recall` | `correct / targeted` is under `low_recall_below` (1/3), including nothing stated |
| 1 | `partial` | Share under 1, or `invented > 0` |
| 0 | `complete` | Every targeted entity right and nothing invented |

`targeted <= 0` (the truth holds only empty fields): `invented > 0` is `fabricated`, else
`complete`. Exactly a third is `partial`, not `low_recall`.

### Reading the extraction row

- **Event counts.** When the row has numeric `tp` and `fn`: `correct = tp`,
  `targeted = tp + fn`. Otherwise `n_value_correct` and `n_targeted` (the detailed suite path,
  corporate records and any row with a subclass, returns no `tp` / `fn`).
- **Invented** = `fp` when numeric, else `n_hallucinated` (default 0), plus `n_value_wrong`.
- **Near miss** = `n_value_partial`: wrong, but not invented.
- **Clause-label rows** (`scoring_method` containing `+maud` or `+cuad`) and rows with no counts
  at all use `overall_extraction_score` as the share: at least 1 is `complete`, under the bar is
  `low_recall`, else `partial`. They are never `fabricated`. A missing share excludes the row.
- Booleans are never numbers.

`field_value_outcomes(expected, predicted, field_scores)` derives `n_targeted`, `n_value_correct`,
`n_value_wrong` and `n_value_partial` from the Dojo's per-field scores. Over expected fields with
a non-blank value and a numeric (non-bool) field score: a score of 1.0 or more is correct; else a
blank prediction is a plain miss; else a score under `FABRICATION_MAX_FIELD_SCORE` (0.5) is wrong
and anything from 0.5 up is a near miss. A value is blank when `is_empty_value` says so (`None`,
`n/a`, `nan`, `"[]"`, ...) or it is a list or tuple whose items are all blank, so a placeholder
is a miss and never an invented value. It returns `{}` when `field_scores` is not a mapping.

## Inputs

`PainPointDocument` (frozen dataclass; all fields optional):

| Field | Meaning |
|:---|:---|
| `doc_id` | Identity used by `compare` to pair documents across experiments |
| `expected_class` / `predicted_class` | Expected and predicted document class |
| `stage` | Final stage the document reached; `archived` and `review` are final |
| `expected_stage` | `review` when a person had to see the document; `None` means archived |
| `failed` | True when the document errored |
| `subclass_correct` | True / False when the document has subclass truth, else `None` |
| `extraction` | The scored extraction row, or `None` without field truth |
| `groups` | Breakdown labels, for example `{"experiment": ..., "model": ..., "prompt": ..., "arm": ...}` |

**Consumers own row loading, stage naming and scoring.** They map their rows to
`PainPointDocument` and attach the scored extraction row (for example from `score_extraction` and
`extraction_binary_metrics`, plus `field_value_outcomes`). Stages, like classes, are compared
stripped and lower-cased (`" Archived"` is `archived`); `failed` must be the boolean `True` to
count. Counts (`tp`, `fn`, `fp`, `n_*`) are used only when finite and non-negative, so a NaN
count (a pandas round trip fills a missing one with NaN) falls back to the next source and is
never read as `complete`; `n_value_correct` above `n_targeted` is no usable figure. A
run without expected stages cannot separate needed from needless reviews, so every review counts
as needless; read the `necessary_review` count before comparing such runs.

## Outputs

- `score_document(doc, scale)` is the per-document evaluation:
  `{"doc_id", "expected_class", "groups", "classification", "extraction"}`, each composite
  `{"points", "reason", "reasons"}` or `None` when the document is not scored on it.
- `score_run(docs, scale)` is `{"profile", "scale", "classification", "extraction"}`. A summary is
  `{n, excluded, points, mean, score, reasons, by_class}`. `mean` is the mean penalty over the
  `n` scored documents; `score = 1 - mean / max_points` on a 0-1 scale (higher is better);
  `reasons` lists every reason, counted under each document's worst reason; both are `None` with
  no scored document.
- `breakdown(docs, by=("experiment",), scale, n_boot=2000, seed=42)` groups documents by key
  names and returns `{"profile", "scale", "by", "groups": [...]}`. There is one entry per distinct
  key tuple, sorted, each `{"key": {name: value}, "classification": summary, "extraction": summary}`
  where every summary also carries `ci`. The key `"doc_class"` reads the expected class
  (lower-cased); any other key reads `doc.groups`, and a missing or blank label is `"unknown"`.
  `ci` is `bootstrap_ci` over the group's per-document points, on the penalty-point scale like
  `mean`, and `None` under two scored documents. Group counts add up to the run's.
- `compare(docs, by="experiment", baseline=..., scale, n_boot, seed)` compares every other value
  of one key against `baseline`. It returns `{"profile", "scale", "by", "baseline",
  "classification": [...], "extraction": [...]}`, one row per candidate (sorted) and composite:
  `candidate, n_paired, baseline_mean, candidate_mean, delta, ci, only_baseline, only_candidate`.
  Documents pair on `doc_id` among those scored on that composite in both groups. The means are
  over the paired documents. **`delta = candidate - baseline`, so positive means more penalty,
  which is worse.** `ci` is `bootstrap_ci` over the per-document differences (`None` under two
  pairs); `only_*` count documents scored on the composite in one group only. Unpaired documents
  never enter a mean or a delta. Documents without a label under `by` form the `"unknown"`
  group, compared like any other; `baseline` is stripped like the labels. It raises `ValueError`
  for an unknown baseline, a missing `doc_id`, or a duplicate `doc_id` inside one group.
- `headline_scores(run)` maps a `score_run` result to the four registry names below (`None` for a
  composite that scored no document).

The bootstrap is stdlib-only and seeded, and `breakdown` sorts each group's points first, so the
same documents give the same interval in any order. `n_boot` must be a positive integer; `by`
key names are stripped and may not repeat.

## Registry and metric ids

| Registry name | Metric identity | Direction |
|:---|:---|:---|
| `pain_points_classification_mean` | `pipeline.pain_points.classification.mean_penalty` | lower is better |
| `pain_points_extraction_mean` | `pipeline.pain_points.extraction.mean_penalty` | lower is better |
| `pain_points_classification_score` | `pipeline.pain_points.classification.score` | higher is better |
| `pain_points_extraction_score` | `pipeline.pain_points.extraction.score` | higher is better |

The registry has no direction field; the means say "lower is better" in their description. These
are run-level headlines (`aggregation: none`): `headline_scores(score_run(...))` emits them, and the
per-document points are the `score_document` payload. Never compare a penalty mean with a 0-1
score, or a run scored under another `profile`.

## Python

```python
from llm_dojo_scoring import PainPointDocument, compare_pain_points, pain_point_breakdown, score_pain_points

docs = [PainPointDocument(doc_id="d1", expected_class="contract", predicted_class="contract",
                          stage="archived", groups={"experiment": "A"}), ...]
score_pain_points(docs)                                  # run summary
pain_point_breakdown(docs, by=("experiment", "doc_class"))
compare_pain_points(docs, by="experiment", baseline="A")
```

Tests: `tests/test_pain_points.py`. Consumer impact: `local-mailroom-sandbox` vendors the module as
its interim hotfix; `llm-mailroom` has no reader yet.
