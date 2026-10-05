# Metric identity (v0.19)

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
| `contract` | `pipeline.extraction.overall`, `cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `maud.question.micro_accuracy` |
| `merger_agreement` | `pipeline.extraction.overall`, `maud.question.micro_accuracy`, `maud.clause_presence.rate`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2` |
| `corporate_record` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2` |
| `insurance_claim` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2` |
| `correspondence` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.enron.topic_accuracy`, `pipeline.enron.topic_f1_macro`, `pipeline.enron.sentiment_accuracy`, `pipeline.enron.sentiment_f1_macro` |

`compare_serving` sets `incomparable: true` when local and API legs carry
different `metric_id` values on their quality blocks. A grid row that mixes
metric ids raises (`llm_dojo_scoring.grid.specialist_grid_rows`) rather than
averaging two different scales.

## Not a KPI

`metric_id_for` still fabricates `pipeline.<class>.<name>` for a registry
metric that has no canonical mapping. Prefer an explicit mapping above; the
fabricated id exists for historical exports only and is tracked as remaining
#17 work in [`ISSUE_ALIGNMENT.md`](ISSUE_ALIGNMENT.md).
