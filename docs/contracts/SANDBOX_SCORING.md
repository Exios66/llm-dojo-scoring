# Sandbox scoring API

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

Shipped in v0.23.0 (DMR-091) and additive to the existing suites. The sandbox imports it from the installed
release first, falling back to its vendored snapshot; both must identify the same release.

`aggregate_sandbox_scores(benchmark, rows)` owns cross-document event pooling.
It accepts already selected score rows, sums MAUD question / answer events or
CUAD TP/FP/FN counts, and computes micro scores once. It does not average per-doc
F1. A labeled total miss is 0.0, whereas no labeled documents yield None. This
corrects the sandbox grid card's old truthiness branch which displayed a total
miss as null. The pooling API preserves report keys and returns additive
`clean_accuracy` support on MAUD rows. Return values use Dojo's existing fbeta
rounding, so pooled CUAD F1 is four decimals; consumers may format it further.

## Contract truth corrections (v0.26.0)

The sandbox's extraction-gate vetting found two places where the CUAD labels
marked a correct contract extraction wrong. Both are fixed here, from the Hub's own CUAD
evidence only:

| Field | CUAD behaviour | Rule |
| --- | --- | --- |
| `parties` | The `Parties` spans mix legal names, defined terms and pronouns. An annotated legal name (`NMS CORP. ("Seller")`) failed containment. Only 34% of party lists that named every party correctly scored right. | Strip defined-term annotations (`party_core`) before the containment check. |
| `effective_date` | `Effective Date` is empty when a contract states only its agreement date. The extracted date then counted as a presence false positive. | When CUAD labels no Effective Date and the value equals an `Agreement Date` span, it is right (`effective_from_agreement`). It is dropped from the presence confusion and counted in `cuad_effective_from_agreement`. |

`field_value_ok(field, value, cuad_clause_labels)` gives the per-field truth that
consumers previously rebuilt from `_value_ok`. It returns `None` when the row's CUAD
universe lacks the field's category.

**Comparability (#97).** `cuad_value_correct` and the CUAD presence counts can rise
on rows that carry annotated party names or an agreement date without an effective
date. Re-score older runs before you compare them with v0.26.0+ cards.
