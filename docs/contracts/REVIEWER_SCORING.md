# Reviewer-lane scoring

The reviewer lane is the pipeline's second classifier: an LLM or decision model
sees a document (and, in the 3.x question sets, the sorter handoff) and either
continues it unattended, corrects its class/subclass, or parks it for a person.
It is not a second sorter. It has a routing contract, a risk bar, and a model
verdict that a plain label-accuracy number cannot express.

`score_review_lane` is the deterministic scorecard for that lane. It is
network-free, consumer-agnostic, and additive to the existing
`get_suite("sorter_reviewer")` label scorer.

## Record contract

`ReviewRecord` (or any mapping with these aliases) is the input:

| Field | Meaning |
| --- | --- |
| `doc_id` | Stable document id (`id` / `item_id` accepted) |
| `expected_doc_type` | Verified class target (`expected_doc_class` accepted) |
| `expected_doc_subclass` | Verified subclass target (`expected_subclass` accepted) |
| `expected_subclass_scorable` | False for merger `other` and blank targets |
| `sorter_doc_type`, `sorter_doc_subclass`, `sorter_confidence` | The handoff the reviewer saw |
| `sorter_below_low_band` | The sorter was unsure; a reviewer override is allowed |
| `reviewer_doc_type`, `reviewer_doc_subclass`, `reviewer_confidence` | The reviewer's answer |
| `reviewer_model`, `question_set` | Model id and question-set version/hash |
| `reviewer_verdict` | Raw model verdict (`continue_sorter_correct`, `reclassify`, …) |
| `route` | Pipeline destination (`extract` / `human_review` / `failed`) |
| `route_verdict` | Pipeline route label (`decision_accepts` / `decision_escalates`) |
| `causes` | Structured review causes (`review_causes` accepted) |
| `cutoff` | Class cutoff applied to the reviewer confidence |
| `has_text`, `eligible`, `error` | Availability and eligibility evidence |
| `human_decision`, `human_doc_type`, `human_doc_subclass` | Optional human resolution |
| `prompt_tokens`, `completion_tokens`, `cost_usd` | Measured reviewer cost |
| `dataset_revision`, `split`, `draw_seed`, `model_id`, `serving_kind` | Provenance |

A consumer that only has `(confidence, correct)` pairs can still use
`analysis.calibration` directly; the scorecard expects the routing evidence
because acceptance, causes, and verdicts are the point.

## Scorecard

`score_review_lane(records, risk=0.01, confidence=0.95, target_accuracy=0.95)`
returns:

| Section | Contents |
| --- | --- |
| `quality` | Class accuracy/CI/macro, per-class P/R/F1, confusion, coverage; subclass accuracy; verdict accuracy/confusion |
| `acceptance` | Accepted count (split into graded, `n_accepted_without_truth` with no GT label, and `n_accepted_unanswered` labelled but with no usable reviewer answer), wrong accepts, wrong rate, exact 95% upper bound, required accepts, shortfall, `meets_risk_bar`, accepted accuracy |
| `calibration` | ECE, Brier, reliability bins, mean confidence overall/correct/wrong |
| `routing` | Human-review count/rate/by class, cause counts/rates, accept-rule violations |
| `cost` | Priced/unpriced counts, total only when every row is priced, per accepted |
| `operating_points` | Per predicted class: target cutoff, cross-fit holdout, risk cutoff, compact curve |
| `by_model`, `by_question_set` | The same core sections per identity |
| `provenance` | Dataset revision, split, seed, question set, model, scorer version, `review.lane.class_accuracy` metric id |

The report keeps the sandbox's established keys at the top level:
`routed_to_human_review`, `routed_to_human_review_rate`,
`routed_to_human_review_by_class`, `routed_to_human_review_basis`,
`subclass_accuracy`, `subclass_correct`, `subclass_scored`, and
`verdicts_by_expected`.

## Risk math

The qualification bar is **at most 1% wrong auto-accepts at a 95% one-sided
upper bound**, not 95% accuracy. The exact Clopper-Pearson bound is:

| Accepted | Wrong | 95% upper bound | Meets 1%? |
| ---: | ---: | ---: | --- |
| 149 | 0 | 1.99% | no |
| 299 | 0 | 0.997% | yes |
| 405 | 1 | 1.17% | no |
| 473 | 1 | 0.999% | yes |
| 135 | 0 | 2.19% | no |

`required_samples(errors, risk=0.01, confidence=0.95)` returns 299 for zero
errors and 473 for one. A class with fewer accepted documents reports the
bound the data supports and `meets_risk_bar: false`; it is not called
qualified.

The existing v3 full-train report is a useful example:

| Class | Accepted | Wrong | 95% upper | 1% bar |
| --- | ---: | ---: | ---: | --- |
| contract | 536 | 0 | 0.56% | yes |
| corporate_record | 405 | 1 | 1.17% | **no** |
| correspondence | 896 | 1 | 0.53% | yes |
| insurance_claim | 985 | 0 | 0.30% | yes |
| merger_agreement | 135 | 0 | 2.19% | **no** |

Those two classes need more clean accepts, not a lower bar.

## Accept-rule audit

For every `route == "extract"` row the scorecard checks: text is usable, the
reviewer label is present and eligible, no causes are recorded, a cutoff is
configured, confidence meets it, the reviewer agrees with a medium/high sorter
(unless the sorter was below its low band), and the model did not answer a
human verdict. Any failure becomes an `accept_rule_violations` entry and sets
`accept_rule_ok: false`. A run gate should fail rather than archive a document
accepted outside the rule.

## Cutoffs and cross-fit

`operating_points` reports, per predicted class:

- `cutoff_at_target`: lowest confidence whose accepted set reaches
  `target_accuracy` (the sandbox's existing tuning target);
- `risk_cutoff`: lowest confidence whose exact upper bound clears `risk`;
- `holdout_*`: five-fold cross-fit from `analysis.calibration.cross_fit_cutoffs`;
- `curve`: a compact accuracy/wrong-rate/review-rate curve.

The dojo owns the math. The sandbox keeps run loading, verified target files,
question sets, and applying the selected cutoffs.

## Consumer mapping

- **Sandbox calibration runs**: `review_record_from_run_item(item, truth=...,
  handoff=..., cutoffs=..., lock=...)` joins `item["pred"]` (`doc_type`,
  `doc_subclass`, `confidence`, `verdict`, `route_to_human`, `usage`) with the
  dataset row, the saved sorter handoff, and the frozen cutoffs. It leaves
  `route` unset when the model did not force a human route, so the scorecard
  applies the cutoff and agreement rule itself.
- **Pipeline runs**: map the manifest's `review_causes`, `review_verdict`,
  `reviewer_*`, `doc_type`, and `classification_confidence`. The raw model
  verdict and the sorter's original label are not durable on current manifests;
  persisting them upstream is required before pipeline-level verdict and
  accept-rule scoring is complete.
- **Extraction gate**: score it separately; its `accept_probability` is a
  different question from the classification reviewer's `doc_type` probability.

## Compatibility

`get_suite("sorter_reviewer").score(expected, predicted)` keeps its current
`docclass` behavior. `score_review_lane` is additive. No existing metric is
removed, and the existing sandbox report keys are preserved.
