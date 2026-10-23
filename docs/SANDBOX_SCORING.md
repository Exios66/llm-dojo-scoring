# Additive sandbox scoring API (DMR-091 draft)

`score_sandbox_maud(predicted, maud_clause_labels)` and
`score_sandbox_cuad(predicted, cuad_clause_labels)` transfer the sandbox's
872b081 rubrics into Dojo. All former sandbox report keys, labeled universes,
clean-subset definitions, conflict reduction and null conventions remain.
Existing Dojo task/suite entry points retain their behavior and functionality.

These are distinct rubric populations, not renamed current suite scores:
MAUD all-label accuracy and its frozen CLEAN_QUESTIONS subset differ from
`score_maud_extraction`'s dynamically assessed clean GT population. CUAD category
DETECTION differs from `score_category_presence`'s positive-span coverage.
Never compare their metric identities as if they were the same experiment.

Use `sandbox_metric_scores("maud" | "cuad", result)` to obtain registry-valid
emission names. Compatibility output `maud_precision_answered` explicitly maps
to `sandbox_maud_precision_answered`; it must not be emitted as the existing
clean-MAUD answer-presence metric. Unknown names raise. Counters remain report
support. Empty labeled populations produce no emitted quality rates. Existing
Emitter/ScoreRecord/provenance validation still applies; this API performs no
network access and never synthesizes provenance.

The sandbox remains responsible for row loading, producer schema validation,
run stores, item identities, prompt selection/lineage, and file rendering.
Its old scoring modules re-export Dojo APIs. Current pipeline corporate v6
and sandbox evaluation v7 prompt families are untouched.

This draft is source-owned and additive. It requires a reviewed Dojo release
and explicit consuming source-pin adoption wherever a package pins a released
Dojo. Sandbox standalone installs require its generated vendor snapshot to
include this committed Dojo source before these facades can land. Do not ship
consumer-only imports against the old vendor tree.


`aggregate_sandbox_scores(benchmark, rows)` owns cross-document event pooling.
It accepts already selected score rows, sums MAUD question / answer events or
CUAD TP/FP/FN counts, and computes micro scores once. It does not average per-doc
F1. A labeled total miss is 0.0, whereas no labeled documents yield None. This
corrects the sandbox grid card's old truthiness branch which displayed a total
miss as null. The pooling API preserves report keys and returns additive
`clean_accuracy` support on MAUD rows. Return values use Dojo's existing fbeta
rounding, so pooled CUAD F1 is four decimals; consumers may format it further.
