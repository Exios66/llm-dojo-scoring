# Primary scoring ownership in 0.23.0

Implementation changes originate and merge in this independent repository.
Consumers adopt the reviewed release and Digital-Mailroom imports the merged
source revisions before generating its sandbox vendor copies.

| Engine | Source consumers |
| --- | --- |
| `pipeline_scoring`, `legalbench_scoring`, `pipeline_verdict` | Pipeline classification, experiment/LegalBench quality, deterministic verdicts; visualizer offline evaluation |
| `sandbox_scoring`, `sandbox_agent_scoring`, `sandbox_composite` | Sandbox MAUD/CUAD rubrics, isolated-agent predicates and fixed chained composite |
| `sandbox_schema_adherence`, `scorecard_honesty.aggregate_quality_honest` | Sandbox payload/schema/floor policies and supported-row extraction means |
| `pilot_labels`, `pilot_summary`, `field_support` | Pipeline pilot matching, class/subclass populations and required/schema/factuality support |
| Existing field engines, diagnostics and bootstrap APIs | Shared field scoring, extraction diagnostics and statistical inference |

Producers retain parsing, schema discovery/validation facts, prompt/catalog
assembly, transport, row adaptation and report rendering. Display telemetry,
cost projections and report-only summaries do not define alternate scoring
engines. Legacy rubric names/populations stay distinct; MAUD and CUAD identities
are not interchangeable. Missing extraction support is `None`, actual zero is
scored, and the chained composite refuses a missing half.

Structural schema fallback keeps the old truthiness but serializes a boolean;
it cannot leak a set into an experiment record. Scorer version identifies the
loaded source/wheel, independent of unrelated installed metadata.
