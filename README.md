<div align="center">

# ⚖️ llm-dojo-scoring

**The deterministic, field-type-aware scoring engine for the LLM-Mailroom constellation — one importable library replacing project-local scoring across llm-entity-extraction and llm-mailroom.**

Scoring · Error analysis · Visualization · Interpretation

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v0.13.0-2EA043)](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.13.0)
[![Tests](https://img.shields.io/badge/pytest-passing-brightgreen)](tests/)

</div>

---

## Install

<div align="center">

```bash
pip install "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.13.0"
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

In **llm-entity-extraction** / **llm-mailroom** `pyproject.toml`:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.13.0
# mailroom:     llm-dojo-scoring[tracing] @ git+...@v0.13.0
# entity:       llm-dojo-scoring[embeddings,tracing] @ git+...@v0.13.0
```

## Quickstart

<div align="center">

```python
from llm_dojo_scoring import score_extraction, bootstrap_ci, tokens_summary
from llm_dojo_scoring import get_suite, apply_intake, score_task, compare_serving
from llm_dojo_scoring.prompts import get_prompt
```

</div>

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

## Module Map

<div align="center">

| Module | What it does |
|:---|:---|
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
emitter.emit_score("sorter", "doc_17", "accuracy", 0.93, run_id="exp_42")
```

## Configuration

All thresholds, equivalence sets, subtype lists, cost tables, and failure-mode definitions live in one `Settings` object:

```python
from llm_dojo_scoring import configure, load_settings

configure(field_scoring__bipartite_match_threshold=0.7)
settings = load_settings("config/taxonomy.yaml")
```

Set `LLM_DOJO_SCORING_CONFIG` to a YAML path for the process-wide override.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

## CLI Reference

<div align="center">

```
dojo-analyze INPUT [-o REPORT.md] [--plots DIR] [--metric COL] [--target 0.94]
                  [--min-n N] [--cost-column COL] [--task T] [--max-items N]
dojo-export  [--task sorter|extraction|all] [--sweep] [--log LOG] [--outdir DIR]
dojo-sync    [--task TRACE_NAME] [--session NAME] [--max-items N]
             [--env-file FILE] [--outdir DIR] [--no-workbook] [--check-phoenix]
```

</div>

## Migration

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the exact import swap. Scoring tables: [`docs/SCORING.md`](docs/SCORING.md). Prompt catalog: [`docs/PROMPTS.md`](docs/PROMPTS.md).

---

<div align="center">

**[llm-mailroom](https://github.com/Exios66/llm-mailroom)** ·
**[llm-entity-extraction](https://github.com/Exios66/llm-entity-extraction)** ·
**[llm-mailroom](https://github.com/Exios66/llm-mailroom)** ·
**[The-Mailroom](https://github.com/Exios66/The-Mailroom)**

<sub>Built by the governed evaluation family under <a href="https://github.com/Exios66">@Exios66</a> · 2026</sub>

</div>
