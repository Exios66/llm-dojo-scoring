# Metric identity (v0.19, updated for v0.22)

Cross-leg comparisons must use the **same** `metric_id` on both sides. Mixing
CUAD clause-presence F1 with pipeline extraction overall is **incomparable**
(Exios66/llm-dojo-scoring #17). `assert_comparable_metric_ids` refuses a
mismatch; `compare_serving` sets `incomparable: true` on the quality block.

## Canonical metric_ids

| Registry / headline name | `metric_id` |
|---|---|
| `extraction_overall_score` / `overall_score` | `pipeline.extraction.overall` |
| `extraction_f1` | `pipeline.extraction.field_micro_f1` |
| `extraction_f2` | `pipeline.extraction.field_micro_f2` |
| `extraction_precision` | `pipeline.extraction.field_micro_precision` |
| `extraction_recall` | `pipeline.extraction.field_micro_recall` |
| `extraction_category_presence` | `cuad.clause_presence.micro_f1` |
| `maud_question_accuracy` | `maud.question.micro_accuracy` |
| `maud_clause_presence` | `maud.clause_presence.rate` |
| `content_topic_accuracy` | `pipeline.enron.topic_accuracy` |
| `content_topic_f1_macro` | `pipeline.enron.topic_f1_macro` |
| `sentiment_accuracy` | `pipeline.enron.sentiment_accuracy` |
| `sentiment_f1_macro` | `pipeline.enron.sentiment_f1_macro` |
| `f1_macro` | `pipeline.classification.f1_macro` |
| `accuracy` | `pipeline.classification.accuracy` |

Resolve helpers: `llm_dojo_scoring.scorecard_honesty.metric_id_for(...)`,
`metric_ids_for_class(...)`, `metric_id_allowed(...)`.

## Doc class → allowed metric_ids

All five live extract classes are covered.

| Doc class / suite | Allowed `metric_id` values |
|---|---|
| `contract` | `pipeline.extraction.overall`, `cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall`, `maud.question.micro_accuracy` |
| `merger_agreement` | `pipeline.extraction.overall`, `maud.question.micro_accuracy`, `maud.clause_presence.rate`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall` |
| `corporate_record` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall` |
| `insurance_claim` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall` |
| `correspondence` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall`, `pipeline.enron.topic_accuracy`, `pipeline.enron.topic_f1_macro`, `pipeline.enron.sentiment_accuracy`, `pipeline.enron.sentiment_f1_macro` |

`compare_serving` sets `incomparable: true` (and leaves the quality delta
`None`) when the local and API legs carry different `metric_id` values
(`metric_id_mismatch`), when only one leg carries one (`metric_id_missing`),
or when one leg mixes ids across its runs (`metric_id_mixed`, listed in the
leg's `metric_id_conflict`). It also refuses to compare quality for a leg that
pools runs with different identities — dataset revision, split, draw seed,
fingerprint, prompt, task, model or serving kind (`identity_mixed`, listed in
the leg's `identity_conflict`). `assert_comparable_metric_ids` uses the same
metric rule; two legs with no id at all are legacy data and come back
`metric_id_unverified` from both. A grid row that mixes
metric ids raises (`llm_dojo_scoring.grid.specialist_grid_rows`) rather than
averaging two different scales.

## Strict resolution

`metric_id_for` resolves only the names in the table above. Any other name
raises `UnknownMetricNameError` (a `KeyError`); it no longer fabricates
`pipeline.<class>.<name>` or `maud.<name>`. A made-up id never matches the
other leg's, so it hid an incomparable pair instead of refusing it. To score
a new metric across legs, add it to `_METRIC_ID_BY_NAME` in
`scorecard_honesty.py` **and** to this page: `tests/test_metric_id_strict.py`
fails if the two disagree.

## Emitted records and archive blocks

Three paths stamp a `metric_id`, and they agree:

* `metric_id_for` (comparisons, suite payloads) is strict, as above.
* `Emitter.emit_score` stamps the canonical id for names in the table and
  `registry:<name>` for every other registry metric (latency, cost, token
  counts, ...). A `registry:` id names the registry entry itself; it is never
  a cross-leg comparison id. A caller-supplied `metric_id` that differs from
  the stamped one is refused (`ProvenanceExportError`), including falsy
  values such as `""`.
* `score_archive_block` stamps `pipeline.extraction.overall` for the default
  method, the canonical id for the headline aliases, and otherwise resolves
  `method` through `metric_id_for` (unknown names raise). A contradicting
  claimed `metric_id` is refused.
