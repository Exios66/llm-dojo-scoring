# llm-dojo-scoring

Dedicated **scoring, error-analysis, visualization, and interpretation** suite
for LLM document pipelines — a single importable library that replaces the
project-local scoring code spread across the `llm-entity-extraction` and
`llm-mailroom` repositories.

Import it into those projects and the exact same scoring definitions run
everywhere: inside eval runners, Braintrust-scorer lookups, post-hoc manifest
re-scoring, Excel report export, and offline analysis of the resulting
artifacts (`Sorter_Experiment_Results.xlsx`, `Sorter_Model_Sweep_Results.xlsx`,
`Sorter_Experiment_Codebook.csv`, …).

## Install

Published release: [v0.9.0](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.9.0)
(`f815544` on `main`). Dependents pin the **tag**, not a floating SHA.

```bash
pip install "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.9.0"
pip install -e .                # from a local checkout
```

In **llm-entity-extraction** / **llm-mailroom** `pyproject.toml`:

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.9.0
```

```python
from llm_dojo_scoring import score_extraction, bootstrap_ci, tokens_summary
from llm_dojo_scoring import get_suite, apply_intake, score_task
```

## Quickstart

Analyze a downloaded results workbook (one row per run) into a Markdown
report + plots:

```bash
dojo-analyze Sorter_Experiment_Results.xlsx --target 0.94 --min-n 100
# -> Sorter_Experiment_Results.xlsx.report.md  (+ *_plots/*.png)
```

Regenerate the canonical workbooks + codebooks from an experiment log:

```bash
dojo-export --task sorter --log reports/experiment_log.jsonl --outdir .
dojo-export --task all --sweep --log reports/experiment_log.jsonl
```

## Live sync from Langfuse / Phoenix

The eval runners trace every per-document classification to the `llm-dojo`
Langfuse project (`sessionId` = experiment name, structured output + per-row
scores). `dojo-sync` re-reads those traces and reconstructs the reference
workbook directly — no manual export needed:

```bash
# Credentials: env vars, or a langfuse.env / .env file
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://us.cloud.langfuse.com

# Sync ALL subtype-classification runs
dojo-sync --task subtype_classification --outdir reports/live

# Sync one experiment (session) — fast, rate-limit friendly
dojo-sync --task subtype_classification \
          --session qwen3.7-flash_sorter_v13_subtype_langfuse --outdir reports/live

# Probe the local Phoenix/OTLP sink too
dojo-sync --check-phoenix
```

`dojo-analyze` also accepts a live source directly:

```bash
dojo-analyze "langfuse:subtype_classification" --max-items 2000
```

Library API:

```python
from llm_dojo_scoring import langfuse_sync as lf

records = lf.fetch_run_records(lf.LangfuseClient(), task=lf.SORTER_TRACE,
                               session_filter="qwen3.7-flash_sorter_v13_subtype_langfuse")
frame = lf.records_to_sorter_frame(records)   # -> normalize_results_frame -> analyze
```

Notes:

- Langfuse list endpoints rate-limit aggressively (~15 req/min on `/traces`);
  the client backs off on 429 (`Retry-After`) automatically. A full 4,000-trace
  sync takes a few minutes; syncing one session is ~11 requests.
- The local Phoenix sink (`http://localhost:6006`) is read through
  `llm_dojo_scoring.phoenix_sync` (uses the `arize-phoenix` client when the
  sink is running); when it is down the suite reports a clear status instead
  of failing (`dojo-sync --check-phoenix`).

Or use the library directly:

```python
import llm_dojo_scoring as dojo

# 1. Score one extraction (field-type-aware, with factuality audit)
result = dojo.score_extraction(
    "contract", field_types, predicted, expected, doc_text=text,
)
print(result.overall_score, result.ambiguous_fields)

# 2. Bootstrap a CI over per-document scores
ci = dojo.bootstrap_ci([1.0, 0.0, 1.0, 1.0])

# 3. Aggregate tokens/cost
summary = dojo.tokens_summary(usage_records, model="qwen/qwen3.7-flash")

# 4. Analyze a workbook artifact
result = dojo.io.read_workbook("Sorter_Experiment_Results.xlsx")
frame = dojo.io.normalize_results_frame(result.frame)
interp = dojo.interpret(frame, target=0.94)
print(dojo.render_notes(interp))
```

## Module map

| Module | Replaces (in llm-entity-extraction / llm-mailroom) | What it does |
|---|---|---|
| `field_scoring` | `src/field_scoring.py` | Field-type-aware deterministic extraction scoring (`score_extraction`, scalar/list scorers, factuality audit, category presence) |
| `classification` | `src/scorers.py` | Label normalization, exact match, per-class stats, macro accuracy, confusion matrices, binary P/R/F1 |
| `failure_modes` | `scripts/eval/run_subtype_eval.py` | Failure-mode taxonomy + `classify_failure`, per-subtype accuracy, confusion builders |
| `equivalences` | `agents/sorter_agent.py` (constants) | Subtype/doc-subclass normalization + equivalence helpers |
| `bootstrap` | `src/bootstrap.py` | Bootstrap CIs, two-sample delta significance, Wilson intervals |
| `cost` | `src/cost_models.py` + `experiment_log.tokens_summary` | Price lookup, cost estimation, usage aggregation |
| `diagnostics` | `src/metrics.py` | Run-level diagnostics: date/duration/money MAE+R², span drift, field error decomposition |
| `experiment` | `src/experiment_log.py` (core) | JSONL record append/load, dotted-path access, git snapshot |
| `export` | `scripts/reporting/export_experiment_results.py`, `export_sweep_results.py` | Reference-format Excel workbooks + codebooks |
| `io` | — (new) | Load Excel/CSV/JSONL artifacts, parse experiment names, normalized analysis frames |
| `error_analysis` | — (new) | Best run, group summaries, trend, per-subtype hotspots, failure drivers, regression alerts |
| `interpret` | — (new) | Verdicts: champion, significance, version/model leaderboards, reliability, recommendations |
| `visualize` | — (new) | matplotlib plots: CI bars, prompt-version bars, subtype heatmap, failure stacks, cost scatter |
| `report` | — (new) | Full Markdown report builder |
| `registry` | — (new) | Metric definitions registry: every score name → tier (**T0 HEADLINE** / **T1 CORE** / **T2 DEEP** / **T3 LOG**), units, aggregation, applicable agents; YAML-backed (`LLM_DOJO_SCORING_REGISTRY`) |
| `bundles` | — (new) | Ten pre-built **task** bundles (classification, extraction, extraction_open, cost, factuality, laziness_detection, audit, reporter, transcription, intake), fail-fast validated against the registry |
| `profiles` | — (new) | **25 agent profiles** — each agent's scoring identity (task-derived bundle resolution, fallback bundle, ground-truth flag); YAML overlay via `LLM_DOJO_SCORING_PROFILES` |
| `suites` | — (new) | **Dedicated scoring suite per pipeline agent** — importable `get_suite` / `score_suite` with field-type maps, doc-type aliases, and honest-gap notes; the API mailroom consumers should call. `list_suites(live_only=True)` hides retired court/DD specialists |
| `doc_bundles` | — (new) | **Document-type-aware bundles** for the eight processed document classes; honest-gap mandate where type-specific scorers are still pending (insurance determination-consistency, retired court/DD, zero-row compliance, corporate_record with no external extraction benchmark) |
| `mailroom` | — (new) | Live LLM-Mailroom / The-Mailroom contract: five extract classes, `unknown`, merger extract alias, Hub inventories, Langfuse observation types, 35-char score alias, exact vs aligned HF accuracy |
| `content_scoring` | — (new) | Enron `content_topic` / `sentiment_label` accuracy + macro-F1; MAUD per-question extraction over the 22 Hub keys |
| `asr` | — (new) | WER / CER / word-accuracy for PDF transcription and OCR |
| `intake` | — (new) | Pre-sorter clerk: NFC / hyphen unwrap / whitespace prep; deterministic gold, LLM intake scored against it |
| `emitter` | — (new) | Unified score emitter: `ScoreRecord`, network-free JSONL manifest sink + credential-checked inert-unless-configured Langfuse sink; scorecards & headline comparison |
| `pruning` | — (new) | Tier-based dashboard filtering: `dashboard_metrics(agent)` (profile bundle ∩ tier cap), `headline_metrics(agent)` (strictly T0), `prune_records` |
| `langfuse_sync` | — (new) | Pull live experiment traces (Langfuse) into run records + reference workbook — subtype sessions **and** mailroom `document-pipeline` traces (intake span, exact/aligned HF accuracy, `user_id` / `release`) |
| `phoenix_sync` | — (new) | Local Phoenix/OTLP sink probe + span reader (graceful when down) |
| `tasks` | — (new) | Task-aware scoring across the additional document hierarchy (MAUD consideration + 22-question extraction, LegalBench, chained runs, multiclass, court opinions, Enron topic/sentiment, WER/CER, intake, `pipeline` HF eval) |
| `cli` | — (new) | `dojo-analyze`, `dojo-export`, `dojo-sync` commands |

## Task coverage — the additional document hierarchy

`score_task(task, expected, predicted, ...)` is the single entry point for
every classification task the eval loop produces, generalizing the CUAD
subtype focus to the full merged taxonomy:

| Task key | What it scores | Headline metrics |
|---|---|---|
| `subtype` / `doc_class` / `multiclass` | CUAD 25-family subtype, primary doc-class, generic multi-class | exact match + CI, macro accuracy, per-class, confusion, top confusions |
| `docclass` / `maud_docclass` | hierarchical doc_type **+** second-level subclass (MAUD consideration type) | doc_type accuracy + CI, subclass accuracy strict/equiv, exact match, per-subclass |
| `maud_question` | MAUD Type-of-Consideration answers (`All Cash` → `all_cash`) | exact match + CI, per-class, macro |
| `maud_extraction` | MAUD 22 Hub `maud_clause_labels` questions (or `'<Question>: <Answer>'` spans) | per-question exact / valid-class / presence / category |
| `enron_topic` / `content_topic` | Enron correspondence topics (11 labels) | accuracy, macro-F1, per-class, confusion |
| `enron_sentiment` / `sentiment` | Enron sentiment (`negative` / `neutral` / `positive`) | accuracy, macro-F1, per-class |
| `transcription` / `wer` | PDF→text / OCR hypothesis vs reference | WER, CER, word_accuracy |
| `intake` | Pre-sorter text prep (deterministic clerk gold; LLM intake scored against it) | exact cleaned-text match, token-F1, prep-step completeness, messy/changed |
| `legalbench` | LegalBench task-mode binary Yes/No | exact match + CI, per-class, binary P/R/F1 |
| `court_opinion` | court_opinion doc-class classification | exact match + CI, per-class, confusion |
| `chained` | composite sorter→extractor runs (`chained_composite` / `chained_summary`) | sorter exact + subtype, extractor overall + presence, weighted composite (default 0.25/0.75) |
| `contracteval` | ContractEval clause-mapping benchmark (arXiv 2508.03080 rubric, `contracteval_metrics` / `contracteval_score`) | confusion accuracy/P/R/F1 + recall-weighted **F2**, token-set **Jaccard** over positive pairs, no-related & false-no-related rates (own + paper's 1,244 denominator), per-category breakdown with `categories=` |

Normalization is task-aware: MAUD consideration answers (`"All Cash"`,
`"Mixed Cash & Stock (Election)"` → canonical keys) and LegalBench Yes/No
forms degrade to canonical labels, and consideration-type equivalence
(`mixed_cash_stock` ↔ `mixed_cash_stock_election`) is honored by the
equiv metrics. Everything is a deterministic pure function over
`(predicted, expected)` pairs — offline rescoring and live
Langfuse/Braintrust scoring can never disagree.

## Unified scoring layer — tiers, bundles, profiles, doc-type bundles

On top of the calculation engine (v0.5.0+) the package ships the
organizational layer consumers emit through:

- **`registry`** — the single source mapping every metric name to its tier:
  **T0 HEADLINE** (board-level, one number per agent) → **T1 CORE**
  ("what broke yesterday?": P/R/F1/F2, rates, cost) → **T2 DEEP** (confusion,
  failure modes, bootstrap CIs, calibration) → **T3 LOG** (audit trail only).
  The built-in default covers this package's full surface plus all 37 flat
  llm-mailroom `SCORE_CONFIGS` names, the Langfuse 35-char transport alias
  (`extraction_verified_precision`), and The-Mailroom judge scores; override
  via `LLM_DOJO_SCORING_REGISTRY`
  or an explicit path.
- **`bundles`** — ten task bundles (what the agent *does*): classification,
  extraction, extraction_open, cost, factuality, laziness_detection, audit,
  reporter, transcription, intake. Every metric must resolve in the registry.
- **`profiles`** — 25 default **agent profiles**, each one agent's scoring
  identity: task-derived bundle resolution, a fallback bundle for degraded
  runs, and a ground-truth flag. Includes the sorter, seven specialists
  (five live + two retired), judge/boss/reporter/transcribers/archivist/
  intake clerk, the audit agent, and the Lane A/B review set
  (`sorter_reviewer`, seven per-specialist auditors including
  `insurance_claims_auditor`, `arbiter`) that never require ground truth.
  Overlay with your own YAML via `LLM_DOJO_SCORING_PROFILES`.
- **`suites`** — one dedicated, importable scoring suite per pipeline agent
  (and a doc-type alias so `get_suite("insurance_claim")` resolves the
  specialist). `suite.score(expected, predicted)` routes to the existing
  calculation (`score_task` / `score_extraction` / audit disagreement /
  transcription WER/CER + token-F1 / intake prep). Type-specific extras ship where real
  scorers exist (CUAD laziness, LegalBench, Enron topic/sentiment, MAUD
  per-question extraction, WER/CER); honest-gap notes record the rest.
  Each specialist suite binds the extraction fields, subclass catalog,
  and GT differentiators for its document class from **`corpus`** (pinned to
  `Lucius-Morningstar/docclass-merged`). `get_suite("merger_agreement")`
  shares the contracts specialist but rebinds the MAUD consideration
  catalog — it does not inherit CUAD families.
- **`corpus`** — published-merge alignment: native vs corpus-present
  classes, per-type subclass surfaces (CUAD folder labels, MAUD
  consideration, CMS source table, Enron form, record type), extraction
  field sets, and `normalize_corpus_subclass` / `suite_schema`.
- **`mailroom`** — live pipeline contract for LLM-Mailroom / The-Mailroom:
  five live extract classes, `unknown` routing token, merger extract
  alias, Hub inventories, Langfuse observation types, score transport
  aliases, and exact vs aligned HF accuracy.
- **`doc_bundles`** — the same idea grouped by the KIND of document processed:
  eight `DOC_TYPE_BUNDLES` (`contract`, `merger_agreement`,
  `corporate_record`, `due_diligence`, `correspondence`, `compliance_filing`,
  `court_opinion`, `insurance_claim`). Honesty mandate: type-specific metrics
  ship ONLY where real scoring logic exists today (contracts get
  CUAD-grounded laziness/hallucination overrides, merger agreements get
  MAUD per-question extraction, correspondence gets Enron topic/sentiment,
  court opinions get LegalBench); types whose scorers are still future work
  say so in their description instead of inventing numbers. `AgentProfile.resolve_doc_bundle()`
  degrades to a task bundle with an EXPLICIT `used_fallback=True` marker —
  never a silent default.
- **`emitter`** — one fan-out point for score records: registry-validated
  `emit_score` → sinks (`LocalManifestSink` JSONL always available;
  `LangfuseSink` inert unless credentials resolve), then aggregated
  `get_scorecard(agent, run_id, min_tier=...)` and T0-only
  `compare_headlines`.
- **`pruning`** — what a dashboard panel shows: profile-bundle ∩ tier cap.

```python
import llm_dojo_scoring as dojo

# 1. Registry: every score name -> tier / units / aggregation / agents
reg = dojo.load_registry()
reg.names_for(max_tier=1, agent="sorter")        # T0+T1 slice for one agent

# 2. Dedicated suite: the import mailroom projects should use
suite = dojo.get_suite("insurance_claims_specialist")          # 25 defaults
result = suite.score(expected_fields, predicted_fields)       # field-type-aware
assert suite.name == dojo.get_suite("insurance_claim").name   # doc-type alias

# 2b. Agent profiles: the scoring identity of each pipeline agent
profile = dojo.get_profile("insurance_claims_specialist")
bundle = profile.resolve_bundle()                             # validated vs registry

# 3. Doc-type bundles: metrics grouped by the kind of document
doc_bundle, used_fallback = profile.resolve_doc_bundle("insurance_claim")
assert not used_fallback          # explicit honesty marker — never a silent default

# 4. Emit through sinks; query scorecards
emitter = dojo.Emitter(sinks=[
    dojo.LocalManifestSink("reports/scores_manifest.jsonl"),   # network-free
    dojo.LangfuseSink(),                                       # inert w/o creds
])
emitter.emit_score("sorter", "doc_17", "accuracy", 0.93, run_id="exp_42")
card = emitter.get_scorecard("sorter", "exp_42", min_tier=1)   # dashboard view

# 5. Tier-based pruning
dojo.dashboard_metrics("contracts_specialist")   # profile bundle ∩ T0+T1
dojo.headline_metrics("judge")                   # strictly T0

# 6. v0.9.0 extras — intake clerk, live-only suites
raw = "A hyphen-\nated  line"
cleaned, _stats = dojo.apply_intake(raw)
intake = dojo.get_suite("intake").score(raw, cleaned)
live = dojo.list_suites(live_only=True)            # hides retired court/DD
```

## Configuration

All thresholds, equivalence sets, subtype lists, cost tables, and failure-mode
definitions live in one `Settings` object (`llm_dojo_scoring.config`):

```python
from llm_dojo_scoring import configure, load_settings

configure(field_scoring__bipartite_match_threshold=0.7)   # inline override
settings = load_settings("config/taxonomy.yaml")          # or a YAML file
```

```yaml
# config/taxonomy.yaml (subset)
field_scoring:
  ambiguous_band: [0.5, 0.85]
  bipartite_match_threshold: 0.6
  embedding_enabled: false
  partial_gt_fields: [parties, key_obligations, termination_clauses]
  containment_fields: [governing_law, term_length, renewal_terms]
  factuality_verification:
    enabled: true
    token_coverage: 0.7
subtype_equivalences:
  - [reseller, distributor]
  - [maintenance, license]
  - [development, license]
  - [affiliate, joint_venture]
cost_models:
  qwen/qwen3.7-flash: [0.03, 0.13]
```

Set `LLM_DOJO_SCORING_CONFIG` to a YAML path for the process-wide override.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

## Migration

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the exact import swap for
`llm-entity-extraction` / `llm-mailroom`.

## CLI reference

```
dojo-analyze INPUT [-o REPORT.md] [--plots DIR] [--metric COL] [--target 0.94]
                  [--min-n N] [--cost-column COL] [--task T] [--max-items N]
                  [--no-plots]        # INPUT may be xlsx | jsonl | langfuse:<name>
dojo-export  [--task sorter|extraction|all] [--sweep] [--log LOG] [--outdir DIR]
dojo-sync    [--task TRACE_NAME] [--session NAME] [--max-items N]
             [--env-file FILE] [--outdir DIR] [--no-workbook] [--check-phoenix]
```