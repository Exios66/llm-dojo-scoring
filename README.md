<div align="center">

<picture>
  <source media="(max-width: 640px)" srcset="docs/assets/readme/hero-mobile.svg"/>
  <img src="docs/assets/readme/hero.svg" alt="Ground truth and predictions converge on a field-type matcher, which produces metrics, intervals, diagnostics and reports." width="100%"/>
</picture>

# LLM Dojo Scoring

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge)](pyproject.toml)
[![Release v0.24.0](https://img.shields.io/badge/release-v0.24.0-6C63FF?style=for-the-badge)](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.24.0)
[![Offline core](https://img.shields.io/badge/scoring-offline_core-22C55E?style=for-the-badge)](docs/SCORING.md)
[![MIT](https://img.shields.io/badge/license-MIT-0EA5E9?style=for-the-badge)](pyproject.toml)

**[Quickstart](#quickstart)** · **[How it works](#how-it-works)** · **[Workflows](#workflows)** · **[API](#library-usage)** · **[Docs](#documentation)**

</div>

---

## What this does

**The shared, field-type-aware scoring engine for the Mailroom constellation.**
Use one importable library to compare document classifications and structured
extractions, quantify uncertainty, inspect failure modes and produce reports.
The pipeline and sandbox consume this source; they do not maintain separate
implementations of its metrics.

<div align="center">
<img src="docs/assets/readme/stats.svg" alt="Field-aware extraction scoring, task suites, uncertainty intervals, and diagnostics." width="100%"/>
</div>

## Install

<div align="center">

```bash
pip install "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.24.0"
pip install -e .                # from a local checkout
```

</div>

<details>
<summary>Optional extras</summary>

```bash
pip install -e ".[embeddings]"   # sentence-transformers + openai (embedding rescue)
pip install -e ".[tracing]"      # langfuse + phoenix + dotenv + OTLP
pip install -e ".[jellyfish]"    # no-op alias; jellyfish is already core
pip install -e ".[dev]"          # pytest
pip install -e ".[all]"          # embeddings + tracing + dev
```

</details>

A standalone consumer can pin this release explicitly:

```toml
[project]
dependencies = [
    "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.24.0",
]
```

The pipeline currently pins **v0.23.1** in its own source. A new Dojo
release and a consuming application's pin are separate decisions; update
consumers through their release workflow rather than treating this example
as their current configuration.

## Quickstart

After installing, score three document-class predictions entirely offline:

```python
from llm_dojo_scoring import score_task

scores = score_task(
    "doc_class",
    expected=["contract", "correspondence", "insurance_claim"],
    predicted=["contract", "contract", "insurance_claim"],
)
print(scores)
```

Two of the three labels match. The returned dictionary includes task metrics
and confidence intervals; the one correspondence error remains visible in
the class-level results. No model, API key or tracing service is required.
For extraction, use the field-type-aware API in [Library Usage](#library-usage).

## How it works

Ground truth and predictions enter a task suite. The engine normalizes and
aligns their fields or labels, computes metrics and uncertainty, then exposes
errors for analysis and export. Optional embedding rescue and tracing sinks
are separate integrations; the deterministic core does not require them.

| Layer | Responsibility | Entry point |
| :--- | :--- | :--- |
| Task suite | Agent-specific scoring contract | `get_suite(...)` |
| Comparison | Typed fields or task labels | `score_extraction(...)`, `score_task(...)` |
| Uncertainty | Confidence intervals and comparisons | `bootstrap_ci(...)` |
| Explanation | Failure modes, field diagnostics, reports | `dojo-analyze`, `dojo-export` |

## Workflows

### Analyze a workbook

```bash
dojo-analyze Sorter_Experiment_Results.xlsx --target 0.94 --min-n 100
# -> Sorter_Experiment_Results.xlsx.report.md  (+ *_plots/*.png)
```

### Regenerate workbooks from experiment log

```bash
dojo-export --task sorter --log reports/experiment_log.jsonl --outdir .
dojo-export --task all --sweep --log reports/experiment_log.jsonl
```

### Live sync from Langfuse / Phoenix

```bash
# Sync ALL subtype-classification runs
dojo-sync --task subtype_classification --outdir reports/live

# Sync one experiment (session) — fast, rate-limit friendly
dojo-sync --task subtype_classification \
          --session qwen3.7-flash_sorter_v13_subtype_langfuse --outdir reports/live

# Probe the local Phoenix/OTLP sink too
dojo-sync --check-phoenix
```

### Check the loaded Dojo version and available releases

```bash
dojo-version
dojo-version --check --force --json
dojo-version --check --offline --json
```

The opt-in `llm_dojo_scoring.update_awareness.UpdateChecker` shares a daily
per-user cache across application startup hooks and limits notices per consumer
and release. Pure imports and scoring stay offline. Set
`LLM_DOJO_UPDATE_CHECK=0` to disable all update checks and cache I/O. No packages
are upgraded automatically. See [update awareness](docs/UPDATE_AWARENESS.md)
for startup semantics, failure/exit codes, privacy and concurrency limits.
Available in v0.24.0; dependency pins remain operator controlled.

## Module Map

<div align="center">

| Module | What it does |
|:---|:---|
| `update_awareness` | Opt-in shared release discovery, startup cache and `dojo-version` |
| `field_scoring` | Field-type-aware deterministic extraction scoring (date/money/id/name/free_text/entity_list) |
| `classification` | Label normalization, exact match, per-class P/R/F1/F2, macro-PRF, confusion matrices |
| `extraction_metrics` | Field-micro extraction P/R/F1/F2 over (field, value) events |
| `claims_consistency` | Insurance `determination_consistency` and `amount_exactness` |
| `failure_modes` | Failure-mode taxonomy + `classify_failure`, per-subtype accuracy |
| `bootstrap` | Bootstrap CIs, two-sample delta significance, Wilson intervals |
| `cost` | Price lookup, cost estimation, usage aggregation |
| `diagnostics` | Run-level diagnostics: date/duration/money MAE+R², span drift, field error decomposition |
| `experiment` | JSONL record append/load, dotted-path access, git snapshot |
| `tasks` | Task-aware scoring across the full document hierarchy (MAUD, LegalBench, chained, etc.) |
| `suites` | Dedicated scoring suite per pipeline agent — the API consumers should call |
| `registry` | Metric definitions registry: every score name → tier (T0 HEADLINE → T3 LOG) |
| `bundles` | Eleven pre-built task bundles (classification, extraction, cost, factuality, etc.) |
| `profiles` | 26 agent profiles — each agent's scoring identity |
| `emitter` | Unified score emitter: JSONL manifest sink + inert Langfuse sink |
| `langfuse_sync` | Pull live experiment traces into run records + reference workbook |
| `phoenix_sync` | Local Phoenix/OTLP sink probe + span reader |

</div>

## Task Coverage

`score_task(task, expected, predicted, ...)` is the single entry point for every classification task:

<div align="center">

| Task key | What it scores | Headline metrics |
|:---|:---|:---|
| `subtype` / `doc_class` / `multiclass` | CUAD 25-family subtype, primary doc-class, generic multi-class | exact match + CI, macro accuracy, per-class, confusion |
| `docclass` / `maud_docclass` | Hierarchical doc_type + second-level subclass | doc_type accuracy + macro P/R/F1/F2, subclass accuracy |
| `maud_question` / `maud_extraction` | MAUD consideration answers + 22 Hub questions | exact match + CI, per-class, macro |
| `enron_topic` / `enron_sentiment` | Enron correspondence topics & sentiment | accuracy, macro-F1, per-class |
| `legalbench` | LegalBench binary Yes/No | exact match + CI, per-class, binary P/R/F1 |
| `chained` | Composite sorter→extractor runs | sorter exact + extractor overall, weighted composite |
| `contracteval` | ContractEval clause-mapping benchmark | F2, Jaccard, no-related rate, per-category |
| `transcription` / `wer` | PDF→text / OCR hypothesis vs reference | WER, CER, word_accuracy |

</div>

## Library Usage

```python
import llm_dojo_scoring as dojo

# 1. Score one extraction (field-type-aware, with factuality audit)
result = dojo.score_extraction(
    "contract", field_types, predicted, expected, doc_text=text,
)

# 2. Bootstrap a CI over per-document scores
ci = dojo.bootstrap_ci([1.0, 0.0, 1.0, 1.0])

# 3. Aggregate tokens/cost
summary = dojo.tokens_summary(usage_records, model="qwen/qwen3.7-flash")

# 4. Dedicated suite: the import mailroom projects should use
suite = dojo.get_suite("insurance_claims_specialist")
result = suite.score(expected_fields, predicted_fields)

# 5. Emit through sinks; query scorecards
emitter = dojo.Emitter(sinks=[
    dojo.LocalManifestSink("reports/scores_manifest.jsonl"),
    dojo.LangfuseSink(),
])
emitter.emit_score(
    "sorter", "doc_17", "accuracy", 0.93, run_id="exp_42",
    # Required (#22); USD metrics also need cost_basis.
    provenance={"dataset_revision": "46a4d3c2", "prompt_id": "sorter_v3",
                "serving_kind": "api", "model_id": "qwen/qwen3.7-flash"},
)
```

## Configuration

All thresholds, equivalence sets, subtype lists, cost tables, and failure-mode definitions live in one `Settings` object:

```python
from llm_dojo_scoring import configure, load_settings

configure(field_scoring__bipartite_match_threshold=0.7)
settings = load_settings("config/taxonomy.yaml")
```

Set `LLM_DOJO_SCORING_CONFIG` to a YAML path for the process-wide override.

## Testing

<a id="tests"></a>

```bash
pip install -e ".[dev]"
python -m pytest
```

Docstrings are required for every Python module, class, and function, including
private helpers, nested definitions, scripts, examples, and tests. Run the
repository-wide coverage gate with
`python -m pytest tests/test_docstring_coverage.py`.

## CLI Reference

<div align="center">

```
dojo-version [--check [--force|--offline]] [--json]
dojo-analyze INPUT [-o REPORT.md] [--plots DIR] [--metric COL] [--target 0.94]
                  [--min-n N] [--cost-column COL] [--task T] [--max-items N]
dojo-export  [--task sorter|extraction|all] [--sweep] [--log LOG] [--outdir DIR]
dojo-sync    [--task TRACE_NAME] [--session NAME] [--max-items N]
             [--env-file FILE] [--outdir DIR] [--no-workbook] [--check-phoenix]
```

</div>

## Documentation

<a id="migration"></a>

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the exact import swap. Scoring tables: [`docs/SCORING.md`](docs/SCORING.md). Prompt catalog and eval-environment prompt lineage (`list_prompt_versions`, `prompt_chain`, `diff_prompt_versions`): [`docs/PROMPTS.md`](docs/PROMPTS.md).

## Releases & monorepo sync

This package is the shared scoring engine consumed by llm-mailroom
and the sandbox (vendored) — version bumps are cross-package
events.

- **Source ownership**: this independent repository owns scoring implementation.
  Review and merge changes here first. The
  [Digital-Mailroom](https://github.com/LLM-Mailroom-Services/Digital-Mailroom)
  monorepo then imports the exact merged revision into
  `packages/llm-dojo-scoring` and refreshes its sandbox vendor snapshot.
  Do not export downstream implementation patches over completed source work.
- **Release-time pin law**: cutting a release means bumping the version here
  AND updating every consuming pin — llm-mailroom /
  sandbox `pyproject.toml` git pins and the sandbox vendor snapshot.
  The dojo pin is bumped ONLY at release time of this package, via
  `src/scripts/bump_dojo_scoring.py` in the llm-mailroom source — never delete a
  pin line. After the release, import the merged source revision and refresh
  the sandbox vendor tree (`scripts/sync_vendor.py`). Verify the changed
  package and every dependant; source and vendor imports must identify the
  same release code, even when unrelated distribution metadata is installed.

---

<div align="center">

**[Digital-Mailroom](https://github.com/LLM-Mailroom-Services/Digital-Mailroom)** ·
**[llm-mailroom](https://github.com/Exios66/llm-mailroom)** ·
**[llm-dojo-scoring](https://github.com/Exios66/llm-dojo-scoring)** ·
**[The-Mailroom](https://github.com/Exios66/The-Mailroom)** ·
**[local-mailroom-sandbox](https://github.com/Exios66/local-mailroom-sandbox)** ·
**[Mailroom-Corpus-EDA](https://github.com/Exios66/Mailroom-Corpus-EDA)** ·
**[mailroom-ml](https://github.com/LLM-Mailroom-Services/mailroom-ml)**

<sub>The Mailroom constellation · independent source repositories, shared interfaces.</sub>
<br/>
<sub>Core packages integrate in Digital-Mailroom; mailroom-ml is a standalone contractor.</sub>
<br/>
<sub>Local artwork: <a href="docs/assets/readme/README.md">design and regeneration</a>.</sub>

</div>
