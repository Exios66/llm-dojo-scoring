# Core evaluation engines (DMR-091 proposal)

**Release prerequisite:** these additive module APIs are not provided by the
published v0.22.0 dependency. Review and release Dojo first, then adopt its
immutable release pin in each source consumer. Workspace resolution alone is
not adoption evidence. Existing Dojo APIs/defaults are unchanged.

## Pipeline and visualizer policies

`llm_dojo_scoring.pipeline_scoring` provides:

- `normalize_class`, `classes_match`, `score_exact_classification`: nonempty
  trimmed/lowercase class tokens; no regex recovery, class collapse or error
  exclusion. Missing GT/prediction is a miss; the legacy three-decimal
  `aligned_*` keys equal exact. Unequal sequences (including generators) now
  raise instead of silently truncating GT. This is an explicit correctness fix.
- `raw_classification_stats`: unrounded counts/rates over a caller-selected
  population. Supplied correctness flags are trusted; raw group labels remain
  raw. Expected-only mode counts raw predictions in each group. Union mode
  credits successful normalized hits to their GT group and adds truthy raw
  false-positive labels. It exists to preserve the two concrete legacy report
  contracts; it does not infer GT, filter errors, normalize unknowns, or impose
  a new universal classifier rubric.
- `score_experiment_rows`: four-decimal accuracy over all rows, macro class
  accuracy over expected groups, macro F1 over expected plus false-positive
  classes; stage accuracy only where `has_stage` is true. Empty input yields
  `{}`. Missing prediction remains wrong; no-stage accuracy key stays absent.
- `pipeline_labels_equal`: literal equality for nonblank labels; absent GT is never a hit. Trace/report
  adapters retain their original GT guards and call this predicate.
- `pipeline_classes_aligned`: visualizer literal class equality and the empty
  historical alias hook. This is deliberately different from `classes_match`.
  Case/whitespace are significant for nonblank labels. Absent GT/prediction
  and absent alias entries cannot match. This fixes the old missing-GT alias
  false positive without changing valid-label behavior.
- `pipeline_subclass_match`: case-insensitive equality after checking input
  nonblank content, with no equivalence/unknown collapse. Whitespace-only
  tokens are absent; missing either side fails.
- `classify_pipeline_failure`: lifecycle priority failed/error, review, class
  miss, aligned class hit, empty public extraction, terminal stage, unknown
  stage. This is not `failure_modes.classify_failure` (sorter taxonomy).
  `archived` bypasses empty-extract failure; `archive` does not. Error text on
  archived rows is ignored by this historical lifecycle policy.
- `score_pipeline_rows`: trusts supplied `exact_ok`/`aligned_ok` flags across
  **all** input rows. No GT stays in accuracy support and sparse confusion under
  `unknown`/`none`. Subclass support is only rows with nonblank expected subclass,
  including failed rows; explicit `subclass_ok=False` wins, `None` falls back
  to comparison with an already lifted predicted subclass. A prediction-only
  subclass has no support. Empty subclass support returns None. Output contains
  quality keys/counts only, with unrounded visualizer rates.

The consumer lifts `predicted_subclass` -> `doc_subclass` -> `contract_subtype`
(first truthy value, then strip), leaving the producer field adapter local.
Sparse confusion and by-class support are engine-owned. Telemetry sums, display
latency, and intake counts remain presentation aggregation; the old missing
telemetry defaults and nonfinite behavior are retained, not new measurement
claims.

## LegalBench reports

`llm_dojo_scoring.legalbench_scoring.score_binary` and `.score_multiclass`
retain the pipeline's exact report keys and producer `correct` flags. Only
`status == 'ok'` and predicted not None/`error` enter quality support; excluded
rows become `n_error`. An `ok` row with absent GT is still included under the
historical trusted-producer contract. This is not independently verified GT.

Binary macro accuracy is over dataset categories, not yes/no labels. Yes F1
uses unrounded precision/recall until final rounding. Family macro F1 uses only
GT family groups; predicted-only families do not enlarge the macro population.
Family grouping can differ from expected labels: supplied grouping and flags
remain authoritative. Equivalent family accuracy uses canonical Dojo
`equivalent_subtypes` directly, without normalizing unknowns to `other`.

`expected_calibration_error(pairs, bins=10)` is binned ECE, rounded once to four
decimals, not mean absolute per-row calibration error. Report callers exclude
non-numeric, out-of-range, NaN and infinite confidences via the existing [0,1]
filter; bool retains numeric semantics. Empty confidence support -> 0.0.
Direct helper calls preserve the old caller-validates contract: NaN propagates,
positive infinity raises during binning; empty pairs -> 0.0. Private legacy
helper names remain available through the pipeline facade. No new score names
are emitted into Langfuse or added to the registry by this transfer.

Existing `fbeta`/`macro_prf` cannot replace these calculations: they round
intermediate rates, recover labels and/or choose a different population.
`_paired.require_equal_lengths` is reused; existing subtype equivalences and
`cost.tokens_summary` stay canonical. No sandbox scoring implementation changes.

## Isolation rubrics and pack diagnostics

`llm_dojo_scoring.agent_rubrics` provides dependency-free functions:
`token_set_f1` (lowercase whitespace sets; blank/blank=1; punctuation retained),
`key_presence` (case-sensitive substring in serialized producer output, even
inside values; no expected keys -> None), and `decision_valid` (literal enum
membership). These preserve the historical rubric; token set F1 is not SQuAD
multiset F1 and substring presence is not JSON schema completeness.

The same module owns `insurance_gt_is_homogeneous`,
`insurance_expected_set_is_homogeneous`, and
`determination_consistency_is_quality`. Empty/unlabeled sets do not establish
homogeneity; all labeled rows must be approved aliases with empty denial
reasons. Legacy reason-list normalization is preserved (a None list member
stringifies to 'None' and counts as present). Quality gate metadata for a
single unlabeled row remains True; this is a compatibility flag, not permission
to score nonexistent GT. Producer internal-invariant diagnostics are separate
from the registered structural consistency metric and stay producer-owned.

## Verification

`tests/test_core_engine_transfer.py` pins hand-counted counts/populations,
error/missing/nonfinite behavior, literal failure priorities and rubrics.
Consumer tests observe real Dojo function entries without replacing scorers.
Parent must run full source/dependent gates after release adoption, regenerate
vendor snapshots through their owner tooling, and import reviewed main commits.
