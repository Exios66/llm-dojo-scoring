# Migrating llm-entity-extraction / llm-mailroom to llm-dojo-scoring

The scoring code that lives in the pipeline projects is now consolidated in
`llm-dojo-scoring`. Migrating is a drop-in import swap — every public name is
kept (same signatures, same return shapes) so the eval runners, Braintrust
scorers, and reporting scripts keep working with minimal edits.

## 1. Install the package

```bash
# in llm-entity-extraction / llm-mailroom
pip install -e "git+https://github.com/<org>/llm-dojo-scoring.git#egg=llm-dojo-scoring"
# or from a local checkout
pip install -e /path/to/llm-dojo-scoring
```

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
profile = dojo.get_profile("sorter")                 # 24 default profiles; YAML overlay
bundle = profile.resolve_bundle()                    # registry-validated metric set

# Dedicated suite — preferred import for mailroom / entity-extraction:
suite = dojo.get_suite("sorter")                     # or get_suite("insurance_claim")
result = suite.score(expected_labels, predicted_labels)

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