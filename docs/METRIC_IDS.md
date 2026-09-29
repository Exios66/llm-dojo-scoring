# Metric identity (v0.18)

Cross-leg comparisons must use the **same** `metric_id` on both sides. Mixing
CUAD clause-presence F1 with pipeline extraction overall is **incomparable**
(Exios66/llm-dojo-scoring #17).

## Canonical metric_ids

| Registry / headline name | `metric_id` |
|---|---|
| `extraction_overall_score` / `overall_score` | `pipeline.extraction.overall` |
| `extraction_f1` | `pipeline.extraction.field_micro_f1` |
| `extraction_category_presence` | `cuad.clause_presence.micro_f1` |
| `maud_question_accuracy` | `maud.question.micro_accuracy` |
| `maud_clause_presence` | `maud.clause_presence.rate` |
| `f1_macro` | `pipeline.classification.f1_macro` |

Resolve helpers: `llm_dojo_scoring.scorecard_honesty.metric_id_for(...)`.

## Doc class → allowed metric_ids

| Doc class / suite | Allowed `metric_id` values |
|---|---|
| `contract` | `pipeline.extraction.overall`, `cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1`, `maud.question.micro_accuracy` |
| `merger_agreement` | `pipeline.extraction.overall`, `maud.question.micro_accuracy`, `maud.clause_presence.rate` |
| `insurance_claim` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1` |
| `correspondence` | `pipeline.extraction.overall`, `pipeline.enron.topic_accuracy` |

`compare_serving` sets `incomparable: true` when local and API legs carry
different `metric_id` values on their quality blocks.
