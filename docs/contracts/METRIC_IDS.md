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
| `ml_intake_doc_type_accuracy` | `ml.intake.doc_type_accuracy` |
| `ml_intake_doc_type_macro_f1` | `ml.intake.doc_type_macro_f1` |
| `ml_intake_doc_type_ece` | `ml.intake.doc_type_ece` |
| `ml_intake_subclass_accuracy` | `ml.intake.subclass_accuracy` |
| `ml_intake_subclass_macro_f1` | `ml.intake.subclass_macro_f1` |
| `ml_intake_subclass_ece` | `ml.intake.subclass_ece` |
| `ml_intake_fast_path_coverage` | `ml.intake.fast_path_coverage` |
| `ml_intake_selective_risk` | `ml.intake.selective_risk` |
| `ml_intake_selective_risk_upper` | `ml.intake.selective_risk_upper` |
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
| `pain_points_classification_mean` | `pipeline.pain_points.classification.mean_penalty` |
| `pain_points_extraction_mean` | `pipeline.pain_points.extraction.mean_penalty` |
| `pain_points_classification_score` | `pipeline.pain_points.classification.score` |
| `pain_points_extraction_score` | `pipeline.pain_points.extraction.score` |

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

### Intake classifier

`llm_dojo_scoring.ml.score_intake_model` scores the `mailroom-ml` intake classifier.
A record carries the gold `doc_type` and `subclass`, the predictions `pred_doc_type`
and `pred_subclass`, the head confidences `doc_type_confidence` and
`subclass_confidence`, and `fast_path` (the model's answer was used without the LLM
sorter). A record with no gold class (`None`, NaN, `pd.NA`, `pd.NaT` or a blank) is
counted under `n_unscored_by_reason`. Subclasses are compared after
`normalize_corpus_subclass`, the gold one by the gold class and the predicted one by the
predicted class; a subclass is right only when the class is right. The scorecard's `metrics` dict is keyed by the short
names (the registry name without `ml_intake_`).

| Registry name | `metric_id` |
|---|---|
| `ml_intake_doc_type_accuracy` | `ml.intake.doc_type_accuracy` |
| `ml_intake_doc_type_macro_f1` | `ml.intake.doc_type_macro_f1` |
| `ml_intake_doc_type_ece` | `ml.intake.doc_type_ece` |
| `ml_intake_subclass_accuracy` | `ml.intake.subclass_accuracy` |
| `ml_intake_subclass_macro_f1` | `ml.intake.subclass_macro_f1` |
| `ml_intake_subclass_ece` | `ml.intake.subclass_ece` |
| `ml_intake_fast_path_coverage` | `ml.intake.fast_path_coverage` |
| `ml_intake_selective_risk` | `ml.intake.selective_risk` |
| `ml_intake_selective_risk_upper` | `ml.intake.selective_risk_upper` |

The scorecard also carries `by_class`: per gold class, `n`, `n_class_right` and
`subclass_macro_f1`, which scores that class's subclasses only on documents whose class
was predicted right. That per-class figure is what the mailroom-ml release gates read.
`metrics.subclass_macro_f1` is end to end: a wrong class makes the subclass wrong. Macro
F1 is exact arithmetic over the gold labels, rounded once to six places.

`selective_risk_upper` is the Wilson upper bound of `selective_risk`, the exact bound
rounded up (never to nearest) to 4 places. Hold a release
gate on it, not on the point rate. The `ml.*` namespace is not a doc-class extraction
identity.

### Decision lanes

`llm_dojo_scoring.scoring.decision_lanes` scores the pipeline's routing
decisions: `score_judge_lane`, `score_arbiter_lane`, `score_boss_lane` and
`score_review_tray`. Each takes mailroom `RunRecord`-shaped mappings and returns a
scorecard with `n`, `n_scored`, `n_unscored_by_reason`, a `metrics` dict keyed by the
short names below, and `provenance` (`gold_source` counts, dataset revision, split,
`metric_ids`, `scorer_version`). A row with no gold is counted under
`n_unscored_by_reason` and is never scored 0. Gold per row: the person's resolution
(`human`), else the dataset extraction score (`corpus`).

- **Resolution keys.** `gold.human_resolution` (`approve_as_is`, `correct`,
  `reclassify`, `reject`) wins. Without it, llm-mailroom's `RunRecord.gold` is read
  through this alias table:

  | `human_decision` | Condition | Resolution |
  |---|---|---|
  | `rejected` | none | `reject` |
  | `approved` | `human_doc_type` names a class other than the final extraction's | `reclassify` |
  | `approved` | otherwise | `approve_as_is` |

  `human_fields` (the person's field corrections) turn an `approve_as_is` into a
  `correct`. `RunRecord` keeps no `removed_fields`, so a review that only removed
  fields reads as `approve_as_is`. `label_source: corpus` ignores both keys.
- **Class match.** Human gold grades a judge verdict or arbiter ruling only when the
  decision observed the class the person resolved: `human_doc_type`, or for a
  `reclassify` the final extraction's class. A decision on another class's
  extraction is graded by the corpus, and so is a typed decision when the resolved
  class is unknown and the final attempt has several classes. An untyped decision
  observed the final attempt's class, when it has one.
- **Ambiguous attempts.** A decision with no `doc_type` on an attempt that has
  extractions of several classes is unscored as `ambiguous_attempt`. A decision that
  names its class is graded by that class's extraction, not by an untyped one beside
  it; an untyped extraction grades it only on an attempt with no typed extraction.
  Its final score is the record's last attempt.

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
  `complete`, at or below the low edge `incomplete`, between them `partial`. An
  `approve_as_is` that also records removed or corrected fields counts as `correct`, in every
  lane. When a decision is about the final extraction and that attempt has no dataset score,
  the row has no gold (`no_gold`); an earlier attempt's score never stands in. A
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
  or `not_parked`. `wasted_review_rate` and `correction_rate` read the outcome, so an
  `approve_as_is` with edited or removed fields is a correction, not a wasted review.
  Beyond the three scalar metrics, the scorecard carries `resolutions`
  (mix, the person's label as given), `reject_reasons`, `field_correction_rate` (per field, over reviews that checked
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

`compare_serving` sets `incomparable: true` (and leaves the quality delta
`None`) when the local and API legs carry different `metric_id` values
(`metric_id_mismatch`), when only one leg carries one (`metric_id_missing`),
or when one leg mixes ids across its runs (`metric_id_mixed`, listed in the
leg's `metric_id_conflict`). It also refuses to compare quality for a leg that
pools runs with different identities — dataset revision, split, draw seed,
fingerprint, prompt, task, model or serving kind (`identity_mixed`, listed in
the leg's `identity_conflict`). `assert_comparable_metric_ids` uses the same
metric rule; two legs with no id at all are legacy data and come back
`metric_id_unverified` from both. The specialist grid report, which raised on a row that
mixed metric ids, was removed in 0.30.0; `assert_comparable_metric_ids` is the check that
remains, so two different scales are never averaged.

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

  For the field-map methods (`overall_score`, `extraction_f1` and their aliases),
  `method` and `provenance.metric_id` name the field-map score. Any other registry
  method resolves to its own id (for example `maud_question_accuracy` stamps
  `maud.question.micro_accuracy`). The block's `headline_metric` (`cuad_presence_f1`, `maud_accuracy`) names
  the separate benchmark number in `headline_score`; its canonical ids are the additive
  sandbox rubrics below (`sandbox_cuad_presence_f1`, `sandbox_maud_accuracy`). A bare
  family name such as `method="cuad"` is not a registry name and raises.

## Additive sandbox rubrics (DMR-091)

| Registry name | Metric identity | Inclusion |
| --- | --- | --- |
| `sandbox_maud_accuracy` | `maud.sandbox_labeled.micro_accuracy` | All labeled sandbox MAUD questions; missing answers and conflicts miss; None with no labels. |
| `sandbox_maud_clean_accuracy` | `maud.sandbox_clean_subset.micro_accuracy` | Frozen sandbox CLEAN_QUESTIONS subset; None with no supported questions. |
| `sandbox_maud_precision_answered` | `maud.sandbox_answered.precision` | Sandbox real answers only; placeholders excluded except catalog classes; conflicts count answered and wrong. |
| `sandbox_cuad_presence_f1` | `cuad.sandbox_category_detection.micro_f1` | Category detection within the row-labeled universe; empty universe is unscorable. |
| `sandbox_cuad_presence_precision` | `cuad.sandbox_category_detection.micro_precision` | TP/(TP+FP) within row-labeled categories; zero when no detected categories on a labeled row. |
| `sandbox_cuad_presence_recall` | `cuad.sandbox_category_detection.micro_recall` | TP/(TP+FN) within row-labeled categories; zero when no positive categories on a labeled row. |

## Pain-point composites

The four run headlines below are listed in the canonical table above. The means are penalty
points per document (0-4, **lower is better**); the scores are `1 - mean / max points` (0-1,
higher is better). The identities are comparable only under one `profile` (default `amfam-v1`).
Definitions, ladders and the per-experiment breakdown: [PAIN_POINT_SCORING.md](PAIN_POINT_SCORING.md).

| Registry name | Metric identity | Inclusion |
| --- | --- | --- |
| `pain_points_classification_mean` | `pipeline.pain_points.classification.mean_penalty` | Documents with an expected class; None with none. |
| `pain_points_extraction_mean` | `pipeline.pain_points.extraction.mean_penalty` | Documents with an expected class and a scored extraction row; None with none. |
| `pain_points_classification_score` | `pipeline.pain_points.classification.score` | As the mean; `1 - mean / max points`. |
| `pain_points_extraction_score` | `pipeline.pain_points.extraction.score` | As the mean; `1 - mean / max points`. |
