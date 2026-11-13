**Merger headline.** A Hub `merger_agreement` row's MAUD labels are extraction
gold (`schemas.maud_schema.hub_merger_expected_fields`): `maud_clauses` (one
`'<Question>: <Hub class>'` line per answered question) and `merger_consideration`
(the `Type of Consideration` answer, else the subtype token). A row that answers
at least one MAUD question therefore has a score, and its payload carries
`pipeline.extraction.overall` with the MAUD content extras beside it
(`maud.question.micro_accuracy` keeps its own value). Only a payload whose ground
truth labels no extraction field and yields no such gold (a label map that answers
no question, or MAUD scored through `expected_maud=`) carries
`maud.question.micro_accuracy` as its `metric_id`, since its
`pipeline.extraction.overall` is null; a batch takes it only when every row is
in that state. A pending or absent label map, or a bare subclass, is unscorable,
not scored. A run that mixes the two kinds of row carries two ids across its
per-document payloads, and `compare_serving` reports it as `metric_id_mixed`
rather than pooling two different headlines. A single batch payload that mixes
the two keeps `pipeline.extraction.overall`.

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
| `reviewer_class_accuracy` | `review.lane.class_accuracy` |
| `reviewer_class_macro_accuracy` | `review.lane.macro_accuracy` |
| `reviewer_accepted_accuracy` | `review.lane.accepted_accuracy` |
| `reviewer_wrong_accept_rate` | `review.lane.wrong_accept_rate` |
| `reviewer_wrong_accept_upper_95` | `review.lane.wrong_accept_upper_95` |
| `reviewer_routed_to_human_review_rate` | `review.lane.human_review_rate` |
| `reviewer_accept_rule_violations` | `review.lane.accept_rule_violations` |
| `reviewer_subclass_accuracy` | `review.lane.subclass_accuracy` |
| `reviewer_verdict_accuracy` | `review.lane.verdict_accuracy` |
| `reviewer_confidence_ece` | `review.lane.confidence_ece` |
| `reviewer_confidence_brier` | `review.lane.confidence_brier` |
| `reviewer_cost_per_accepted_usd` | `review.lane.cost_per_accepted_usd` |
| `judge_verdict_accuracy` | `decision.judge.verdict_accuracy` |
| `judge_verdict_macro_f1` | `decision.judge.macro_f1` |
| `judge_escalation_recall` | `decision.judge.escalation_recall` |
| `judge_false_escalation_rate` | `decision.judge.false_escalation_rate` |
| `judge_error_rate` | `decision.judge.error_rate` |
| `arbiter_decision_accuracy` | `decision.arbiter.decision_accuracy` |
| `arbiter_retry_usefulness` | `decision.arbiter.retry_usefulness` |
| `arbiter_wrongful_accept_rate` | `decision.arbiter.wrongful_accept_rate` |
| `arbiter_unnecessary_escalation_rate` | `decision.arbiter.unnecessary_escalation_rate` |
| `boss_wrongful_approve_rate` | `decision.boss.wrongful_approve_rate` |
| `boss_needless_review_rate` | `decision.boss.needless_review_rate` |
| `review_tray_wasted_review_rate` | `decision.review_tray.wasted_review_rate` |
| `review_tray_correction_rate` | `decision.review_tray.correction_rate` |
| `review_tray_reject_rate` | `decision.review_tray.reject_rate` |
| `f1_macro` | `pipeline.classification.f1_macro` |
| `accuracy` | `pipeline.classification.accuracy` |
| `sandbox_maud_accuracy` | `maud.sandbox_labeled.micro_accuracy` |
| `sandbox_maud_clean_accuracy` | `maud.sandbox_clean_subset.micro_accuracy` |
| `sandbox_maud_precision_answered` | `maud.sandbox_answered.precision` |
| `sandbox_cuad_presence_f1` | `cuad.sandbox_category_detection.micro_f1` |
| `sandbox_cuad_presence_precision` | `cuad.sandbox_category_detection.micro_precision` |
| `sandbox_cuad_presence_recall` | `cuad.sandbox_category_detection.micro_recall` |

Resolve helpers: `llm_dojo_scoring.metrics.scorecard_honesty.metric_id_for(...)`,
`metric_ids_for_class(...)`, `metric_id_allowed(...)`.

### Reviewer lane

| Registry name | `metric_id` |
|---|---|
| `reviewer_class_accuracy` | `review.lane.class_accuracy` |
| `reviewer_class_macro_accuracy` | `review.lane.macro_accuracy` |
| `reviewer_accepted_accuracy` | `review.lane.accepted_accuracy` |
| `reviewer_wrong_accept_rate` | `review.lane.wrong_accept_rate` |
| `reviewer_wrong_accept_upper_95` | `review.lane.wrong_accept_upper_95` |
| `reviewer_routed_to_human_review_rate` | `review.lane.human_review_rate` |
| `reviewer_accept_rule_violations` | `review.lane.accept_rule_violations` |
| `reviewer_subclass_accuracy` | `review.lane.subclass_accuracy` |
| `reviewer_verdict_accuracy` | `review.lane.verdict_accuracy` |
| `reviewer_confidence_ece` | `review.lane.confidence_ece` |
| `reviewer_confidence_brier` | `review.lane.confidence_brier` |
| `reviewer_cost_per_accepted_usd` | `review.lane.cost_per_accepted_usd` |

The reviewer namespace is not a doc-class extraction identity. Do not compare a
`review.lane.*` number with `pipeline.extraction.*` or `cuad.*`; the reviewer
scorecard is a separate lane with its own target population, risk bar, and
question set.

### Decision lanes

`llm_dojo_scoring.scoring.decision_lanes` scores the pipeline's routing
decisions: `score_judge_lane`, `score_arbiter_lane`, `score_boss_lane` and
`score_review_tray`. Each takes mailroom `RunRecord`-shaped mappings and returns a
scorecard with `n`, `n_scored`, `n_unscored_by_reason`, a `metrics` dict keyed by the
short names below, and `provenance` (`gold_source` counts, dataset revision, split,
`metric_ids`, `scorer_version`). A row with no gold is counted under
`n_unscored_by_reason` and is never scored 0. Gold per row: the person's resolution
(`human`), else the dataset extraction score (`corpus`).

| Registry name | `metric_id` |
|---|---|
| `judge_verdict_accuracy` | `decision.judge.verdict_accuracy` |
| `judge_verdict_macro_f1` | `decision.judge.macro_f1` |
| `judge_escalation_recall` | `decision.judge.escalation_recall` |
| `judge_false_escalation_rate` | `decision.judge.false_escalation_rate` |
| `judge_error_rate` | `decision.judge.error_rate` |
| `arbiter_decision_accuracy` | `decision.arbiter.decision_accuracy` |
| `arbiter_retry_usefulness` | `decision.arbiter.retry_usefulness` |
| `arbiter_wrongful_accept_rate` | `decision.arbiter.wrongful_accept_rate` |
| `arbiter_unnecessary_escalation_rate` | `decision.arbiter.unnecessary_escalation_rate` |
| `boss_wrongful_approve_rate` | `decision.boss.wrongful_approve_rate` |
| `boss_needless_review_rate` | `decision.boss.needless_review_rate` |
| `review_tray_wasted_review_rate` | `decision.review_tray.wasted_review_rate` |
| `review_tray_correction_rate` | `decision.review_tray.correction_rate` |
| `review_tray_reject_rate` | `decision.review_tray.reject_rate` |

Gold and the rules behind each lane:

- **Judge.** Human: `approve_as_is` is `complete`, `correct` is `partial`, `reject` and
  `reclassify` are `incomplete`. Corpus: the dataset score of the judged extraction at or
  above the high edge of the ambiguous band (`get_ambiguous_band()`, default 0.5 / 0.85) is
  `complete`, at or below the low edge `incomplete`, between them `partial`. A
  `judge_error` verdict is unscored and counted in `error_rate`. `escalation_recall` is
  over documents whose gold is not `complete`, `false_escalation_rate` over those whose
  gold is `complete`.
- **Arbiter.** The unit is a ruling. A `retry_extraction` is useful when the dataset score
  of the next attempt is at least `epsilon` (default 0.05) above the attempt ruled on.
  An `accept_with_caveats` is right when the person approved as is or, with no resolution,
  the final dataset score is at or above the high edge. A `human_review` is needed when the
  person changed or refused the work or, with no resolution, the final score is below the
  high edge. The scorecard also carries `by_decision` right / wrong counts.
- **Boss.** Human outcome only. `approved` is wrongful when the person corrected,
  reclassified or rejected the document; `review` is needless when the person approved as
  is. A row without a resolution is `no_boss_gold`. Approved documents reach a person only
  when they are sampled for audit, so `wrongful_approve_rate` describes the audited ones.
- **Review tray.** Rows with a resolution are scored; others are `unresolved` (still parked)
  or `not_parked`. Beyond the three scalar metrics, the scorecard carries `resolutions`
  (mix), `reject_reasons`, `field_correction_rate` (per field, over reviews that checked
  fields: `approve_as_is` and `correct`) and `by_review_cause` (per cause: parks, parks where
  the person changed the work, and their ratio).

The `decision.*` namespace is not a doc-class extraction identity. Do not compare a
`decision.*` number with `pipeline.extraction.*`, `cuad.*` or `review.lane.*`.

## Doc class → allowed metric_ids

All five live extract classes are covered.

| Doc class / suite | Allowed `metric_id` values |
|---|---|
| `contract` | `pipeline.extraction.overall`, `cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall`, `maud.question.micro_accuracy`, `cuad.sandbox_category_detection.micro_f1`, `cuad.sandbox_category_detection.micro_precision`, `cuad.sandbox_category_detection.micro_recall` |
| `merger_agreement` | `pipeline.extraction.overall`, `maud.question.micro_accuracy`, `maud.clause_presence.rate`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall`, `maud.sandbox_labeled.micro_accuracy`, `maud.sandbox_clean_subset.micro_accuracy`, `maud.sandbox_answered.precision` |
| `corporate_record` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall` |
| `insurance_claim` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall` |
| `correspondence` | `pipeline.extraction.overall`, `pipeline.extraction.field_micro_f1`, `pipeline.extraction.field_micro_f2`, `pipeline.extraction.field_micro_precision`, `pipeline.extraction.field_micro_recall`, `pipeline.enron.topic_accuracy`, `pipeline.enron.topic_f1_macro`, `pipeline.enron.sentiment_accuracy`, `pipeline.enron.sentiment_f1_macro` |

**Merger headline.** A `merger_agreement` payload whose ground truth labels no
extraction field (every row of mailroom-dataset v9.3 is MAUD-only) carries
`maud.question.micro_accuracy` as its `metric_id`, since its
`pipeline.extraction.overall` is null. A batch takes it only when every row is
MAUD-only. A run that mixes MAUD-only rows with rows that label extraction
fields therefore carries two ids across its per-document payloads, and
`compare_serving` reports it as `metric_id_mixed` rather than pooling two
different headlines. A single batch payload that mixes the two keeps
`pipeline.extraction.overall`.

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
metric ids raises (`llm_dojo_scoring.analysis.grid.specialist_grid_rows`) rather than
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

## Additive sandbox rubrics (DMR-091)

| Registry name | Metric identity | Inclusion |
| --- | --- | --- |
| `sandbox_maud_accuracy` | `maud.sandbox_labeled.micro_accuracy` | All labeled sandbox MAUD questions; missing answers and conflicts miss; None with no labels. |
| `sandbox_maud_clean_accuracy` | `maud.sandbox_clean_subset.micro_accuracy` | Frozen sandbox CLEAN_QUESTIONS subset; None with no supported questions. |
| `sandbox_maud_precision_answered` | `maud.sandbox_answered.precision` | Sandbox real answers only; placeholders excluded except catalog classes; conflicts count answered and wrong. |
| `sandbox_cuad_presence_f1` | `cuad.sandbox_category_detection.micro_f1` | Category detection within the row-labeled universe; empty universe is unscorable. |
| `sandbox_cuad_presence_precision` | `cuad.sandbox_category_detection.micro_precision` | TP/(TP+FP) within row-labeled categories; zero when no detected categories on a labeled row. |
| `sandbox_cuad_presence_recall` | `cuad.sandbox_category_detection.micro_recall` | TP/(TP+FN) within row-labeled categories; zero when no positive categories on a labeled row. |
