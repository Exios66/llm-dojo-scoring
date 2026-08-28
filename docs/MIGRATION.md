# Migrating llm-entity-extraction / llm-mailroom to llm-dojo-scoring

The scoring code that lives in the pipeline projects is now consolidated in
`llm-dojo-scoring`. Migrating is a drop-in import swap — every public name is
kept (same signatures, same return shapes) so the eval runners, Braintrust
scorers, and reporting scripts keep working with minimal edits.

## 1. Install the package

```bash
# in llm-entity-extraction / llm-mailroom — pin the published tag
pip install "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.1"
# or from a local checkout
pip install -e /path/to/llm-dojo-scoring
```

`pyproject.toml` / `requirements.txt`:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.1
```

Do not pin a merge SHA. Release notes: https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.12.1

## 2. Import swap table

### Field scoring — `src/field_scoring.py`

```python
# OLD
from src.field_scoring import score_extraction, score_field, score_entity_list
from src.field_scoring import EntityListScore, ExtractionScoreResult
from src.field_scoring import get_ambiguous_band, get_bipartite_match_threshold

# NEW
from llm_dojo_scoring import (
    score_extraction, score_field, score_entity_list,
    EntityListScore, ExtractionScoreResult,
)
from llm_dojo_scoring.field_scoring import (
    get_ambiguous_band, get_bipartite_match_threshold,
    get_partial_gt_fields, get_containment_fields,
    verification_enabled, get_verification_coverage,
)
```

Notes:

- `get_field_types(doc_class)` now takes an optional `taxonomy` dict —
  pass your own loaded taxonomy: `get_field_types("contract", load_taxonomy())`.
- The `taxonomy.yaml` `field_scoring:` block is read via the package `Settings`
  (same keys). Point `LLM_DOJO_SCORING_CONFIG` at your taxonomy, or call
  `configure(...)`.
- The embedding remote fallback reads `OPENROUTER_API_KEY` /
  `OPENROUTER_BASE_URL` directly from the environment (no `src.env_utils`).

### Classification scorers — `src/scorers.py`

```python
# OLD
from src.scorers import normalize_label, exact_match, failure, cost
from src.scorers import per_class_stats, macro_accuracy, ERROR_PREFIX

# NEW
from llm_dojo_scoring.classification import (
    normalize_label, exact_match, failure, per_class_stats, macro_accuracy,
    ERROR_PREFIX, confusion_matrix, binary_metrics,
)
from llm_dojo_scoring.cost import tokens_summary  # cost() is input["cost"] -> inline it
```

### CIs — `src/bootstrap.py`

```python
# OLD
from src.bootstrap import bootstrap_ci, delta_significance

# NEW
from llm_dojo_scoring.bootstrap import bootstrap_ci, delta_significance, wilson_ci
```

### Cost — `src/cost_models.py` / `experiment_log.tokens_summary`

```python
# OLD
from src.cost_models import estimate_cost, estimate_for_record
from src.experiment_log import tokens_summary

# NEW
from llm_dojo_scoring.cost import estimate_cost, estimate_for_record, tokens_summary
```

### Diagnostics — `src/metrics.py`

```python
# OLD
from src.metrics import extraction_diagnostics, parse_duration_days

# NEW
from llm_dojo_scoring.diagnostics import extraction_diagnostics, parse_duration_days
```

`extraction_diagnostics` no longer imports `cuad_ground_truth` /
`master_labels`; pass an `expected_resolver(master, filename, field, fallback)`
callable to reproduce master-label preference.

### Experiment log — `src/experiment_log.py`

```python
# OLD
from src.experiment_log import append_experiment, git_snapshot, mean

# NEW
from llm_dojo_scoring.experiment import append_experiment, git_snapshot, mean
from llm_dojo_scoring.experiment import load_records, dotted_get, record_date
```

The `experiment_log_markdown` / `render_full_log` renderers stay in the
pipeline repo (they are report-layer, not scoring-layer).

### Failure modes — `scripts/eval/run_subtype_eval.py::classify_failure`

```python
# OLD
from scripts.eval.run_subtype_eval import classify_failure

# NEW
from llm_dojo_scoring.failure_modes import classify_failure
from llm_dojo_scoring.failure_modes import summarize_failures, per_subtype_accuracy
```

### Equivalences — `agents/sorter_agent.py`

```python
# OLD
from agents.sorter_agent import (
    SUBTYPE_EQUIVALENCES, equivalent_subtypes, normalize_subtype,
    SUBTYPE_UNKNOWN, CONTRACT_SUBTYPE_KEYS,
)

# NEW
from llm_dojo_scoring.equivalences import (
    equivalent_subtypes, normalize_subtype, equivalent_doc_subclasses,
)
from llm_dojo_scoring.config import (
    SUBTYPE_EQUIVALENCES, SUBTYPE_UNKNOWN, CONTRACT_SUBTYPE_KEYS, PER_SUBTYPE,
)
```

Keep using `SorterAgent` for the *runtime* classification call; only the
scoring constants/helpers come from the package.

### Excel export — `scripts/reporting/export_experiment_results.py` / `export_sweep_results.py`

```python
# OLD
from scripts.reporting.export_experiment_results import (
    sorter_columns, extraction_columns, write_workbook, write_codebook, load_records,
)

# NEW
from llm_dojo_scoring.export import (
    sorter_columns, extraction_columns, write_workbook, write_codebook,
    load_records, sorter_records, extraction_records, build_sweep_workbook,
)
```

The column specs are byte-identical to the reference workbooks; you can delete
both reporting scripts and call `dojo-export` instead.

## 3. One-time wiring

- Point `LLM_DOJO_SCORING_CONFIG` at your `config/taxonomy.yaml` (or call
  `configure(...)` before the run) so thresholds match your deployment.
- Delete now-redundant modules once imports are swapped:
  `src/field_scoring.py`, `src/metrics.py`, `src/bootstrap.py`,
  `src/cost_models.py`, `src/scorers.py` (keep `src/experiment_log.py` for the
  markdown renderers), the `export_*` reporting scripts.

## 3b. Live sync (Langfuse / Phoenix)

The `run_langfuse_*_eval.py` traces are now re-readable by the dojo suite —
no manual workbook export step needed for analysis:

```python
from llm_dojo_scoring import langfuse_sync as lf

client = lf.LangfuseClient()            # reads LANGFUSE_* env / langfuse.env
records = lf.fetch_run_records(client, task=lf.SORTER_TRACE,
                               session_filter="<experiment_name>")
frame = lf.records_to_sorter_frame(records)
```

or from the CLI:

```bash
dojo-sync --task subtype_classification --session <experiment_name> --outdir reports/live
dojo-sync --check-phoenix                # local OTLP sink status
dojo-analyze "langfuse:subtype_classification" --max-items 2000
```

Your `langfuse.env` (with `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` /
`LANGFUSE_BASE_URL` / `LANGFUSE_PROJECT=llm-dojo`) is picked up automatically;
credentials set in the shell win.

## 3c. Adopting the unified scoring layer (v0.5+, optional)

Beyond the drop-in swap above, consumers can route their score emission
through the package's organizational layer instead of maintaining ad-hoc
score lists:

```python
import llm_dojo_scoring as dojo

# One agent's scoring identity: task-derived bundle, fallback, ground-truth flag.
profile = dojo.get_profile("sorter")                 # 25 default profiles; YAML overlay
bundle = profile.resolve_bundle()                    # registry-validated metric set

# Dedicated suite — preferred import for mailroom / entity-extraction:
suite = dojo.get_suite("sorter")                     # or get_suite("insurance_claim")
result = suite.score(expected_labels, predicted_labels)
# Hierarchical sorter (doc type + per-class subclass from docclass-merged):
result = suite.score(
    expected_doc_types, predicted_doc_types,
    expected_subclass=expected_subclasses,
    predicted_subclass=predicted_subclasses,
)
# Merger agreements share the contracts specialist but bind MAUD subclasses:
assert dojo.get_suite("merger_agreement").subclasses[0] == "all_cash"
assert dojo.suite_schema("insurance_claim")["subclasses"] == [
    "carrier", "inpatient", "outpatient", "pde",
]

# Doc-type-aware scoring (KANBAN-067) with an EXPLICIT fallback marker:
doc_bundle, used_fallback = profile.resolve_doc_bundle(doc_type="contract")
if used_fallback:                                    # never a silent default
    ...  # dashboards surface the honesty flag

# Emit through sinks; query tier-capped views.
emitter = dojo.Emitter(sinks=[dojo.LocalManifestSink("reports/scores_manifest.jsonl")])
emitter.emit_score("sorter", doc_id="doc_17", metric_name="accuracy",
                   value=0.93, run_id="exp_42")
card = emitter.get_scorecard("sorter", "exp_42", min_tier=1)   # T0+T1 only
dojo.dashboard_metrics("contracts_specialist")       # bundle ∩ tier cap
```

Governance rules that make this safe to adopt incrementally:

- Every emitted name is validated against the registry at emit time
  (`KeyError` on unknown metrics — fail fast, not silently dropped). Register
  new names upstream first (built-in `DEFAULT_METRICS_YAML` or a
  `LLM_DOJO_SCORING_REGISTRY` YAML), then use them downstream.
- llm-mailroom validates its flat `SCORE_CONFIGS` list against
  `load_registry().metrics` at import time; llm-entity-extraction wraps the
  same layer behind a thin `score_emitter` bridge module. Mirror whichever
  pattern fits your repo.

## 3d. Pinning the v0.10.0 release

Dependents pin the published GitHub Release tag — not a merge SHA:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.10.0
```

https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.10.0

v0.10.0 is additive on the v0.9.0 surface (single-doc `get_suite(...).score()` still returns `ExtractionScoreResult`):

```python
import llm_dojo_scoring as dojo

# Specialist T0 now includes field-micro F1 (and F2); overall soft mean stays.
assert "extraction_f1" in dojo.headline_metrics("contracts_specialist")
assert "extraction_f2" in dojo.headline_metrics("insurance_claims_specialist")
assert "content_topic_f1_macro" in dojo.headline_metrics("correspondence_specialist")

# Sorter T0 `f1_macro` is actually computed.
out = dojo.score_task("docclass", ["contract", "insurance_claim"], ["contract", "correspondence"])
assert "f1_macro" in out and "precision" in out["per_class"]["contract"]

# Insurance determination-consistency is a real scorer (CMS GT is all-approved —
# pin the degenerate case instead of hiding it).
assert dojo.determination_consistency(
    {}, {"coverage_determination": "approved", "denial_reasons": []}
) == 1.0
assert dojo.determination_consistency(
    {}, {"coverage_determination": "denied", "denial_reasons": []}
) == 0.0
```

Honesty gaps that remain (do not invent KPIs): retired court/DD, zero-row compliance, corporate_record with no *external* extraction benchmark, CMS GT homogeneity (all-approved / empty denials).

## 3e. Pinning the v0.11.0 release (scoring docs + prompt catalog)

Dependents pin the published GitHub Release tag — not a merge SHA:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.11.0
```

https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.11.0

v0.11.0 is additive on the v0.10.0 scoring surface (formulas and T0 names are unchanged). New imports:

```python
from llm_dojo_scoring.prompts import get_prompt, list_prompts

# Live production template (mailroom sorter_v14 / contracts v32, …)
system = get_prompt("sorter").text

# Docclass-merged arm (entity-extraction prompts_docclass latest keys)
system = get_prompt("contracts_specialist", family="docclass").text

# Honest non-LLM roles — no fake auditor/intake system prompts
assert get_prompt("intake").kind == "deterministic" and get_prompt("intake").text == ""
assert get_prompt("archivist").kind == "procedural"
assert get_prompt("insurance_claims_auditor").kind == "proposed"

# T0/T1 metrics now carry citation / inclusion / ground_truth
m = __import__("llm_dojo_scoring").load_registry().get("extraction_f1")
assert m.citation and m.ground_truth == "required"
```

Canonical scoring tables (per-agent T0/T1, field maps, honest gaps, metric catalog): [`docs/SCORING.md`](SCORING.md). Prompt catalog rules: [`docs/PROMPTS.md`](PROMPTS.md).

Do not push pin PRs to llm-mailroom / llm-entity-extraction / The-Mailroom from this package PR — consumers bump when they choose.

## 3f. Pinning the v0.12.0 release (local vs API serving suite)

Dependents pin the published GitHub Release tag — not a merge SHA:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.0
```

https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.12.0

v0.12.0 is additive on the v0.10.0 / v0.11.0 scoring surface (formulas and T0 names for specialists / sorter are unchanged). New imports:

```python
from llm_dojo_scoring import get_suite, compare_serving, split_local_api
from llm_dojo_scoring.serving import score_serving_run

# expected = local run(s), predicted = API-key run(s)
cmp = get_suite("local_vs_api").score(
    {"provider": "ollama", "model": "qwen3:8b", "quantization": "q4_k_m",
     "ttft_seconds": 0.4, "e2e_latency_seconds": 2.4, "completion_tokens": 50},
    {"provider": "openrouter", "model": "qwen/qwen3-8b",
     "ttft_seconds": 0.15, "e2e_latency_seconds": 0.9, "completion_tokens": 50},
)
assert cmp["metrics"]["ttft_seconds"]["local"] == 0.4
assert cmp["metrics"]["gpu_utilization"]["api"] is None  # local-only

# Partition an experiment log, then pair on task + prompt + fingerprint
local, api, unknown = split_local_api(records)
```

Serving T0 (`ttft_seconds`, `tokens_per_second`) applies only to `local_vs_api`.
Sorter headlines stay `accuracy` + `f1_macro`. TTFT is `None` unless a
first-token timestamp or explicit `ttft_seconds` is recorded.

Do not push pin PRs to llm-mailroom / llm-entity-extraction / The-Mailroom /
local-mailroom-sandbox from this package PR — consumers bump when they choose.

## 3g. Pinning the v0.12.1 release (serving table + scorecard)

Dependents pin the published GitHub Release tag — not a merge SHA:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.12.1
```

https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.12.1

v0.12.1 is additive on v0.12.0. `compare_serving` now returns a scoring **table**
(every T0/T1 serving metric, missing elements as `None`) and a **scorecard**
with identity + token × price-table cost calculations:

```python
from llm_dojo_scoring import get_suite
from llm_dojo_scoring.serving import emit_serving_scorecard

cmp = get_suite("local_vs_api").score(local_records, api_records)
assert {r["metric"] for r in cmp["table"]}  # includes queue_time_seconds even when None
assert cmp["scorecard"]["cost"]["local"]["estimated_cost_usd"] is None  # Ollama slug
assert cmp["markdown"].startswith("# local vs API serving scorecard")
emit_serving_scorecard(cmp, run_id="exp_1")
```

Do not push pin PRs to dependents from this package PR.

## 4. Verification

After the swap, run the suite and re-export — numbers must be unchanged:

```bash
python -m pytest                                # pipeline's own tests
python scripts/eval/run_subtype_eval.py --dry-run
dojo-export --task all --log reports/experiment_log.jsonl
```

The regenerated `Sorter_Experiment_Results.xlsx` must match the previous
artifact row-for-row (the reference artifacts were produced by this exact
logic).