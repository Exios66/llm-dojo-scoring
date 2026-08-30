# Scoring (v0.12.1)

Canonical scoring reference for `llm-dojo-scoring`. The metric **source of truth**
is [`llm_dojo_scoring/registry.py`](../llm_dojo_scoring/registry.py) `DEFAULT_METRICS_YAML`
plus citation / inclusion / ground-truth metadata on each T0/T1 `MetricDef`.
This document does not invent KPIs and does not change formulas shipped in v0.10.0.

Related: [PROMPTS.md](PROMPTS.md) (importable prompt catalog), [MIGRATION.md](MIGRATION.md).

Tiers:

- **T0 HEADLINE** — `headline_metrics(agent)`: bundle ∩ T0. Board view.
- **T1 CORE** — `dashboard_metrics(agent)` adds the rest of the bundle at T0+T1.
- **T2 / T3** — opt-in exploration / logs. Not tabulated here.

These T0 lists are **not** the README `score_task` “headline” column (that surface is
task-kind specific: sorter exact, ContractEval F2, etc.).

## Per-agent T0 / T1

| Agent | Bundle | T0 (`headline_metrics`) | T1 extras on the dashboard (`dashboard_metrics` − T0) |
|---|---|---|---|
| `sorter` | `classification` | `accuracy`, `f1_macro` | `classification_correct`, `precision`, `recall`, `f2`, `precision_macro`, `recall_macro`, `f2_macro`, `false_positive_rate`, `false_negative_rate`, `exact_accuracy`, `aligned_accuracy`, `subclass_accuracy`, `subclass_f1_macro`, `subclass_precision_macro`, `subclass_recall_macro`, `subclass_f2_macro`, `estimated_cost_usd`, `cost_per_document`, `schema_valid`, `parse_error`, `success_rate` |
| `contracts_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `jaccard_similarity`, `laziness_rate`, `date_mae_days`, `money_mae_usd` |
| `corporate_records_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `date_mae_days` |
| `due_diligence_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `date_mae_days` |
| `correspondence_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2`, `content_topic_f1_macro` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `date_mae_days`, `money_mae_usd`, `content_topic_accuracy`, `sentiment_accuracy`, `sentiment_f1_macro` |
| `compliance_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `date_mae_days` |
| `court_opinions_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `legalbench_accuracy`, `legalbench_macro_f1`, `date_mae_days` |
| `insurance_claims_specialist` | `extraction` | `extraction_overall_score`, `extraction_f1`, `extraction_f2` | `extraction_precision`, `extraction_recall`, `field_presence`, `entity_list_precision`, `entity_list_recall`, `entity_list_f1`, `verified_precision`, `completeness`, `schema_valid`, `parse_error`, `success_rate`, `estimated_cost_usd`, `cost_per_document`, `date_mae_days`, `money_mae_usd`, `determination_consistency`, `amount_exactness` |
| `reporter` | `reporter` | `accuracy`, `f1_macro`, `extraction_overall_score` | `success_rate`, `cost_per_document` |
| `judge` | `classification` | `accuracy`, `f1_macro` | `classification_correct`, `precision`, `recall`, `f2`, `precision_macro`, `recall_macro`, `f2_macro`, `false_positive_rate`, `false_negative_rate`, `exact_accuracy`, `aligned_accuracy`, `subclass_accuracy`, `subclass_f1_macro`, `subclass_precision_macro`, `subclass_recall_macro`, `subclass_f2_macro`, `estimated_cost_usd`, `cost_per_document`, `schema_valid`, `parse_error`, `success_rate` |
| `boss` | `reporter` | `accuracy`, `f1_macro`, `extraction_overall_score` | `success_rate`, `cost_per_document` |
| `pdf_transcriber` | `transcription` | `accuracy`, `f1_macro` | `wer`, `cer`, `word_accuracy` |
| `image_extractor` | `transcription` | `accuracy`, `f1_macro` | `wer`, `cer`, `word_accuracy` |
| `archivist` | `cost` | — | `estimated_cost_usd`, `cost_per_document` |
| `intake` | `intake` | `accuracy`, `f1_macro` | `intake_prep_completeness`, `intake_changed_rate`, `intake_messy_rate`, `success_rate`, `cost_per_document` |
| `audit_agent` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `sorter_reviewer` | `classification` | `accuracy`, `f1_macro` | `classification_correct`, `precision`, `recall`, `f2`, `precision_macro`, `recall_macro`, `f2_macro`, `false_positive_rate`, `false_negative_rate`, `exact_accuracy`, `aligned_accuracy`, `subclass_accuracy`, `subclass_f1_macro`, `subclass_precision_macro`, `subclass_recall_macro`, `subclass_f2_macro`, `estimated_cost_usd`, `cost_per_document`, `schema_valid`, `parse_error`, `success_rate` |
| `contract_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `corporate_records_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `due_diligence_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `correspondence_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `compliance_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `court_opinions_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `insurance_claims_auditor` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `arbiter` | `audit` | — | `audit_disagreement_rate`, `audit_resolution_rate`, `verified_precision`, `cost_per_document` |
| `local_vs_api` | `serving` | `ttft_seconds`, `tokens_per_second` | `tpot_seconds`, `e2e_latency_seconds`, `ttft_p50`, `ttft_p95`, `e2e_p50`, `e2e_p95`, `output_tokens_per_second`, `prompt_tokens_per_second`, `requests_per_second`, `docs_per_second`, `gpu_utilization`, `kv_cache_utilization`, `gpu_memory_used_gb`, `queue_time_seconds`, `error_rate`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`, `cost_per_document` |

Notes:

- Live specialists share T0 `extraction_overall_score` + `extraction_f1` + `extraction_f2`.
  Correspondence **also** has T0 `content_topic_f1_macro` (Enron topic imbalance).
- Sorter / reviewer / judge T0 is `accuracy` + `f1_macro`.
- Audit profiles have **no T0** names in the audit bundle; the dashboard is T1
  `audit_disagreement_rate` / `audit_resolution_rate`.
- Archivist is cost-only (procedural store). Intake T0 still lists `accuracy` /
  `f1_macro` because those names sit on the intake bundle; the clerk contract
  itself is `intake_prep_completeness` (structural, T1).
- `field_presence` appears on extraction dashboards but **is not emitted** by
  `score_extraction` — see the metric catalog.
- `local_vs_api` T0 is TTFT + tokens/s. GPU / KV / VRAM are T1 and local-only.
  Serving names do not apply to sorter or specialists.

## Extraction confusion model

Implemented in `extraction_metrics.extraction_binary_metrics`. Additive on top of
the soft mean from `field_scoring.score_extraction` (`extraction_overall_score`).

- Each **expected** field with a non-empty ground-truth value is one event.
- **TP**: that field's typed score is `>= 1.0` (exact, or list F1 of 1.0).
- **FN**: expected field scored `< 1.0`. Partial list matches are **not** TP;
  they stay in `extraction_overall_score`.
- **FP**: predicted extra keys not in expected, **or** unmatched predicted items
  on an `entity_list` field (`EntityListScore.unmatched_predicted`).
- Then `P = TP/(TP+FP)`, `R = TP/(TP+FN)`, `F1 = 2PR/(P+R)`, `F2 = 5PR/(4P+R)`
  (van Rijsbergen β=2). Empty/null GT fields are skipped, not FN.

Typed field scores (the soft mean) use:

- `id` — normalize then exact.
- `date` — parse to ISO, exact with containment / partial-credit fallbacks.
- `money` — one-cent tolerance after currency parse.
- `name` — Jaro–Winkler + token-set ratio, containment first.
- `free_text` — SQuAD token-F1 over token multisets.
- `entity_list` — Hungarian bipartite match (scipy `linear_sum_assignment`),
  then P/R/F1 on the matched set.

## Field maps (`DEFAULT_FIELD_TYPES`)

Copied from `llm_dojo_scoring.suites.DEFAULT_FIELD_TYPES` — mailroom v0.6.0
`config/taxonomy.yaml` / `EXTRACTION_SCHEMAS` mirror (pared checklists +
semantic trio). Open-ended `key_obligations` / `termination_clauses` /
`key_provisions` / long `key_points` are **not** on the live board; use
`LEGACY_FULL_EXTRACTION_FIELD_TYPES` (or `field_types=`) only for historical
free-text dumps. Override with `field_types=` on `suite.score()`.

### `contract` (11 fields)

| Field | Type |
|---|---|
| `document_name` | `name` |
| `parties` | `entity_list:name` |
| `effective_date` | `date` |
| `term_length` | `free_text` |
| `governing_law` | `name` |
| `contract_value` | `money` |
| `renewal_terms` | `free_text` |
| `cuad_family` | `name` |
| `merger_consideration` | `name` |
| `cuad_clauses` | `entity_list:free_text` |
| `maud_clauses` | `entity_list:free_text` |

### `corporate_record` (9 fields)

| Field | Type |
|---|---|
| `entity_name` | `name` |
| `record_type` | `name` |
| `effective_date` | `date` |
| `signatories` | `entity_list:name` |
| `jurisdiction` | `name` |
| `filing_number` | `id` |
| `intent` | `name` |
| `subject_matter` | `free_text` |
| `keywords` | `entity_list:name` |

### `due_diligence` (7 fields)

| Field | Type |
|---|---|
| `target_entity` | `name` |
| `diligence_type` | `name` |
| `material_findings` | `entity_list:free_text` |
| `risk_flags` | `entity_list:free_text` |
| `outstanding_items` | `entity_list:free_text` |
| `document_date` | `date` |
| `prepared_by` | `name` |

### `correspondence` (11 fields)

| Field | Type |
|---|---|
| `sender` | `name` |
| `recipient` | `name` |
| `additional_recipients` | `entity_list` |
| `communication_type` | `name` |
| `communication_date` | `date` |
| `demand_amount` | `money` |
| `action_items` | `entity_list` |
| `urgency` | `name` |
| `intent` | `name` |
| `subject_matter` | `free_text` |
| `keywords` | `entity_list:name` |

### `compliance_filing` (8 fields)

| Field | Type |
|---|---|
| `filing_type` | `name` |
| `regulatory_body` | `name` |
| `filing_date` | `date` |
| `due_date` | `date` |
| `entity_name` | `name` |
| `key_requirements` | `entity_list:free_text` |
| `status` | `name` |
| `reference_number` | `id` |

### `court_opinion` (11 fields)

| Field | Type |
|---|---|
| `case_name` | `name` |
| `court` | `name` |
| `date_decided` | `date` |
| `docket_number` | `id` |
| `opinion_type` | `name` |
| `parties` | `entity_list:name` |
| `holding` | `free_text` |
| `legal_issues` | `entity_list:free_text` |
| `outcome` | `free_text` |
| `citations` | `entity_list:id` |
| `authored_by` | `name` |

### `insurance_claim` (17 fields)

| Field | Type |
|---|---|
| `claim_number` | `id` |
| `policy_number` | `id` |
| `insurer` | `name` |
| `insured_party` | `name` |
| `claim_type` | `name` |
| `date_of_loss` | `date` |
| `date_filed` | `date` |
| `claimed_amount` | `money` |
| `adjuster` | `name` |
| `damages_description` | `free_text` |
| `coverage_determination` | `name` |
| `denial_reasons` | `entity_list:free_text` |
| `supporting_documents` | `entity_list` |
| `intent` | `name` |
| `subject_matter` | `free_text` |
| `keywords` | `entity_list:name` |
| `claim_checklist` | `entity_list:free_text` |

### `merger_agreement` (11 fields)

| Field | Type |
|---|---|
| `document_name` | `name` |
| `parties` | `entity_list:name` |
| `effective_date` | `date` |
| `term_length` | `free_text` |
| `governing_law` | `name` |
| `contract_value` | `money` |
| `renewal_terms` | `free_text` |
| `cuad_family` | `name` |
| `merger_consideration` | `name` |
| `cuad_clauses` | `entity_list:free_text` |
| `maud_clauses` | `entity_list:free_text` |

## Honest gaps (`_HONEST_GAPS`)

Type-specific limitations. These are not pending scorers dressed up as KPIs.

### `insurance_claims_specialist`

HONEST GAP: CMS DE-SynPUF ground truth in the published merge is homogeneous — coverage_determination is all-approved and denial_reasons is empty — so determination_consistency is degenerate (always 1.0 on GT-shaped predictions). The scorer itself now exists (approved ⇒ empty reasons; denied/partial ⇒ non-empty). Mailroom claim_type accepts Hub source-table tokens plus legacy FNOL lines; those catalogs are orthogonal and are not a KPI. adjuster is Optional (null valid for CMS rows).

### `due_diligence_specialist`

HONEST GAP: due_diligence was RETIRED from the live llm-mailroom pipeline (v0.5.0 / PR #21). The sorter emits unknown (human review) instead of extracting. This suite remains for historical traces; zero rows in Lucius-Morningstar/docclass-merged.

### `court_opinions_specialist`

HONEST GAP: court_opinion was RETIRED from the live llm-mailroom pipeline (v0.5.0 / PR #21). The sorter emits unknown. LegalBench metrics still ship as the real benchmark surface.

### `corporate_records_specialist`

HONEST GAP: no *external* extraction benchmark (CUAD/MAUD-grade coverage is not claimed). The published merge covers 39 corporate_record rows with record-type subclasses (articles_of_incorporation, rights_instrument, …). Suite scores typed-extraction field-micro P/R/F1/F2 plus that subclass catalog.

### `compliance_specialist`

HONEST GAP: compliance_filing has zero rows in Lucius-Morningstar/docclass-merged. Hub SEC form-body inventory (10-K, 10-Q, 8-K, …) is the live subclass catalog; suite scores typed-extraction plus that inventory (no corpus-backed rows yet).

### `local_vs_api`

HONEST GAP: TTFT is None unless a first-token timestamp or explicit ttft_seconds is recorded — never inferred from e2e/n_tokens. GPU utilization, KV-cache occupancy, and GPU memory are local-only; API-key providers (OpenRouter, …) cannot supply them. Local Ollama tags without an OpenRouter price table leave estimated_cost_usd None (do not fabricate electricity).

## Local vs API serving

Importable comparison for any consumer that has paired local and API-key runs
(including `local-mailroom-sandbox`):

```python
from llm_dojo_scoring import get_suite
cmp = get_suite("local_vs_api").score(local_records, api_records)
```

`expected` is the local side; `predicted` is the API-key side.
Identity (model, quantization, dtype, GPU, max_model_len, provider, profile)
is registered on each side, not scored as quality.

Formulas (vLLM / NVIDIA NIM / OpenAI streaming conventions):

- **TTFT** = `t_first_token − t_start` (or explicit `ttft_seconds`)
- **e2e** = `t_end − t_start` (or recorded latency)
- **TPOT** = `(e2e − ttft) / (completion_tokens − 1)`
- **tokens/s** = `completion_tokens / e2e`
- **decode tokens/s** = `completion_tokens / (e2e − ttft)`
- **prefill tokens/s** = `prompt_tokens / ttft`
- **req/s** = `n_requests / sum(e2e)`
- GPU util values `> 1` are treated as percent and stored in `[0, 1]`

Canonical record keys: `llm_dojo_scoring.serving.CANONICAL_SERVING_KEYS`.

### Scoring table and scorecard

`compare_serving` (and `get_suite("local_vs_api").score`) now return a full
**scoring table** (every T0/T1 serving metric, including missing elements as
`None`) and a **scorecard** with identity + cost calculations:

```python
from llm_dojo_scoring import get_suite
from llm_dojo_scoring.serving import serving_card_markdown, emit_serving_scorecard

cmp = get_suite("local_vs_api").score(local_records, api_records)
cmp["table"]       # list of {metric, tier, local, api, delta, ratio, status, note}
cmp["scorecard"]   # headlines, dashboard, identity, cost, missing, honest_gaps
cmp["cost"]        # token × price-table breakdown per side
print(cmp["markdown"])
emit_serving_scorecard(cmp, run_id="exp_1")  # local → exp_1:local, api → exp_1:api
```

`status` is `compared` | `local_only` | `api_only` | `missing`. GPU/KV/VRAM
are `local_only`. Metrics neither side recorded appear under **Missing
elements** as `None`, never `0.0`. Cost uses `cost.estimate_cost` against the
OpenRouter price table; Ollama tags without a table entry stay `None`.

## T0 / T1 metric catalog

Every headline and core name with citation, inclusion, ground-truth requirement,
and compute `source`. Ground-truth labels:

- **required** — needs gold labels / expected fields.
- **optional** — computed when gold is present; otherwise skipped.
- **structural** — check on the prediction (or clerk invariants), not a GT score.
- **none** — not a quality-vs-gold metric (cost, emitter aliases).

Emitter-only mailroom aliases have `source: null` and are **not computed here**.

### `accuracy` (T0)

Overall exact-match accuracy

- **source:** `classification.accuracy`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Exact-match accuracy after task-aware normalize_label (classification.accuracy).
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels dropped.

### `content_topic_f1_macro` (T0)

Enron correspondence content_topic macro-F1 over expected topics (imbalanced 11-way)

- **source:** `content_scoring.score_content_topic`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Enron 11-topic catalog; unweighted macro-F1 (content_scoring.score_content_topic).
- **inclusion:** Computed when a content_topic gold label is present; skipped when the field is empty/null.
- **notes:** Promoted to T0 — topic imbalance makes macro-F1 the correspondence board number

### `extraction_f1` (T0)

Field-micro F1 over (field, value) events (ACE / CoNLL / SemEval slot filling)

- **source:** `extraction_metrics.extraction_binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ACE / CoNLL / SemEval slot filling; TP requires typed score ≥ 1.0. F1 is van Rijsbergen β=1.
- **inclusion:** Skipped when expected is empty/null. Empty GT field values are not FN. List F1 is None if no list fields.

### `extraction_f2` (T0)

Field-micro F2 (β=2, van Rijsbergen) — recall-weighted; insurance claims board number

- **source:** `extraction_metrics.extraction_binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ACE / CoNLL / SemEval slot filling; F2 is van Rijsbergen Fβ with β=2 (5PR/(4P+R)).
- **inclusion:** Same inclusion as extraction_f1. Partial list matches are not TP.
- **notes:** Partial list matches are not TP; they stay in extraction_overall_score

### `extraction_overall_score` (T0)

Specialist headline: overall extraction score for the run

- **source:** `field_scoring.score_extraction`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Mean of per-field typed scores from field_scoring.score_extraction (soft mean; partial list credit stays here).
- **inclusion:** None when there are no scorable fields. Empty/null expected dict yields no overall score.

### `f1_macro` (T0)

Macro-averaged F1 across classes — the universal classifier headline

- **source:** `classification.macro_prf`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Unweighted macro-average of one-vs-rest F1 (classification.macro_prf); F1 is van Rijsbergen Fβ with β=1.
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels dropped. score_task drops ERROR_PREFIX rows.

### `aligned_accuracy` (T1)

HF pipeline aligned doc-type accuracy (merger_agreement ≡ contract)

- **source:** `mailroom.score_aligned_classification`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** HF pipeline aligned doc-type accuracy; merger_agreement ≡ contract (mailroom.score_aligned_classification).
- **inclusion:** Requires paired predicted/expected doc types. Empty sequences skipped.

### `amount_exactness` (T1)

Claimed-amount exact match after money normalize (complement of money_mae_usd)

- **source:** `claims_consistency.amount_exactness`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Money-field exact after one-cent normalize (claims_consistency.amount_exactness).
- **inclusion:** None if either side is empty or unparseable.

### `audit_disagreement_rate` (T1)

Rate where the audit pass disagrees with the specialist output

- **source:** `suites.ScoringSuite._score_audit`
- **ground_truth:** `optional`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Complement of typed extraction overall_score between auditor output and the reference dict (suites.ScoringSuite._score_audit). No new algorithm — 1 − score_extraction.overall_score.
- **inclusion:** None when overall_score is None (no scorable fields). Requires two dicts.
- **notes:** NEW (KANBAN-061) — feeds KANBAN-060's contracts_audit_v0 pass; shared by every named auditor + arbiter

### `audit_resolution_rate` (T1)

Rate where the specialist adopts the audit pass correction

- **source:** `suites.ScoringSuite._score_audit`
- **ground_truth:** `optional`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Typed extraction overall_score of auditor vs reference — the rate the audit pass agrees with (and would correct toward) the reference (suites.ScoringSuite._score_audit).
- **inclusion:** None when overall_score is None. Requires two dicts.
- **notes:** NEW (KANBAN-061); shared by every named auditor + arbiter

### `cer` (T1)

Character error rate (character-level Levenshtein / |reference|); lower is better

- **source:** `asr.character_error_rate`
- **ground_truth:** `required`
- **units:** `error_rate` · **aggregation:** `mean`
- **citation:** Character error rate: character-level Levenshtein / |reference| (asr.character_error_rate).
- **inclusion:** Requires a non-empty reference transcript.

### `class_correct` (T1)

Per-document class correctness (mailroom pipeline pilot)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name; alias of classification_correct

### `classification_correct` (T1)

Per-document classification correctness (strict/equiv)

- **source:** `classification.exact_match`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Per-document exact-match after normalize_label (classification.exact_match).
- **inclusion:** Skipped when either side is empty/null.

### `completeness` (T1)

Numeric completeness of the required output shape

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom completeness_label (CATEGORICAL) folds into this numeric score; not computed in this package

### `content_topic_accuracy` (T1)

Enron correspondence content_topic exact-match accuracy (11 topics)

- **source:** `content_scoring.score_content_topic`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Enron 11-topic exact-match accuracy (content_scoring.score_content_topic).
- **inclusion:** Skipped when content_topic gold is empty/null.

### `contracteval_false_no_related` (T1)

Rate of 'no related clause' answers when ground truth expects content

- **source:** `tasks.contracteval_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ContractEval (arXiv 2508.03080) no-related rate: model says no related clause when GT expects content (tasks.contracteval_metrics).
- **inclusion:** ContractEval rows only; skipped outside that task.
- **notes:** alias: laziness (KANBAN-054); mirrors ContractEval no_related_rate

### `cost_per_document` (T1)

Total cost / documents processed

- **source:** `cost.estimate_for_record`
- **ground_truth:** `none`
- **units:** `USD` · **aggregation:** `mean`
- **citation:** Total estimated cost / documents processed (cost.estimate_for_record).
- **inclusion:** None when document count is 0.

### `date_mae_days` (T1)

Mean absolute date error in days (run-level diagnostic)

- **source:** `diagnostics.extraction_diagnostics`
- **ground_truth:** `required`
- **units:** `days` · **aggregation:** `mean`
- **citation:** Mean absolute error in days after date parse (diagnostics.extraction_diagnostics).
- **inclusion:** None when neither side parses to a date. Empty GT dates skipped.
- **notes:** Existing diagnostics surface; registered so every specialist suite can emit it

### `determination_consistency` (T1)

Insurance coverage_determination agrees with denial_reasons (approved ⇒ empty; denied/partial ⇒ non-empty)

- **source:** `claims_consistency.determination_consistency`
- **ground_truth:** `structural`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Structural check on the prediction; ground truth is unused (claims_consistency.determination_consistency).
- **inclusion:** Always defined on a predicted dict; 0.0 when determination is missing. CMS GT homogeneity makes GT-shaped predictions degenerate (always 1.0).

### `entity_list_f1` (T1)

Mean entity-list bipartite F1 (dashboard name for diagnostics.entity_list_raw_f1)

- **source:** `extraction_metrics.mean_entity_list_f1`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Optimal bipartite matching (Hungarian / Kuhn–Munkres via scipy linear_sum_assignment) over a pairwise similarity matrix, then P/R/F1 on the matched set. Mean list F1 (extraction_metrics.mean_entity_list_f1); dashboard name for diagnostics.entity_list_raw_f1.
- **inclusion:** None if the document has no list fields.
- **notes:** existing diagnostics.entity_list_raw_f1 registered under this name

### `entity_list_precision` (T1)

Precision over extracted list items (bipartite match)

- **source:** `field_scoring.score_entity_list`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Optimal bipartite matching (Hungarian / Kuhn–Munkres via scipy linear_sum_assignment) over a pairwise similarity matrix, then P/R/F1 on the matched set. Per-list-field precision from field_scoring.score_entity_list.
- **inclusion:** None if the document has no entity_list fields. Empty GT lists are not FN.

### `entity_list_recall` (T1)

Recall over extracted list items (bipartite match)

- **source:** `field_scoring.score_entity_list`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Optimal bipartite matching (Hungarian / Kuhn–Munkres via scipy linear_sum_assignment) over a pairwise similarity matrix, then P/R/F1 on the matched set. Per-list-field recall from field_scoring.score_entity_list.
- **inclusion:** None if the document has no entity_list fields.

### `estimated_cost_usd` (T1)

Estimated USD cost of the call/run

- **source:** `cost.estimate_cost`
- **ground_truth:** `none`
- **units:** `USD` · **aggregation:** `sum`
- **citation:** USD cost from token counts × model table (cost.estimate_cost).
- **inclusion:** 0 when usage is missing. Not a quality score.

### `exact_accuracy` (T1)

HF pipeline exact doc-type accuracy (merger_agreement ≠ contract)

- **source:** `mailroom.score_aligned_classification`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** HF pipeline exact doc-type accuracy; merger_agreement ≠ contract (mailroom.score_aligned_classification).
- **inclusion:** Requires paired predicted/expected doc types. Empty sequences skipped.

### `expected_field_presence` (T1)

Share of expected fields populated

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name; alias of field_presence

### `extraction_correctness` (T1)

Per-document extraction correctness (mailroom pilot)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name

### `extraction_hallucination_rate` (T1)

Share of reported values not grounded in GT or the source doc

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name; complement of verified precision

### `extraction_needs_judge_review` (T1)

Routing signal: extraction ambiguous enough to escalate to the judge

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name

### `extraction_overall_verified_precision` (T1)

Precision restricted to doc-verifiable items

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name; alias of verified_precision

### `extraction_precision` (T1)

Field-micro precision over (field, value) extraction events

- **source:** `extraction_metrics.extraction_binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ACE / CoNLL / SemEval slot-filling: (field, value) events. TP requires the typed field score ≥ 1.0; partial list matches are not TP. Source: extraction_metrics.extraction_binary_metrics.
- **inclusion:** Skipped when expected is empty/null (no events). Empty GT field values are not FN. ERROR_PREFIX predictions are dropped by the suite. entity_list F1 is None when the document has no list fields.

### `extraction_recall` (T1)

Field-micro recall over (field, value) extraction events

- **source:** `extraction_metrics.extraction_binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ACE / CoNLL / SemEval slot-filling: (field, value) events. TP requires the typed field score ≥ 1.0; partial list matches are not TP. Source: extraction_metrics.extraction_binary_metrics.
- **inclusion:** Skipped when expected is empty/null (no events). Empty GT field values are not FN. ERROR_PREFIX predictions are dropped by the suite. entity_list F1 is None when the document has no list fields.

### `extraction_verified_precision` (T1)

Langfuse wire alias of extraction_overall_verified_precision (35-char config limit)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom LANGFUSE_SCORE_NAME_ALIASES transport name

### `f2` (T1)

F-beta beta=2 — recall-weighted; flags false negatives early (legal work)

- **source:** `classification.binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic mean (β=1), F2 uses β=2 so 5PR/(4P+R). classification.binary_metrics / macro_prf.
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `f2_macro` (T1)

Unweighted mean of one-vs-rest F2 (doc_type)

- **source:** `classification.macro_prf`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta. van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic mean (β=1), F2 uses β=2 so 5PR/(4P+R).
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `false_negative_rate` (T1)

FN / (FN + TP)

- **source:** `classification.binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** FN/(FN+TP) from classification.binary_metrics.
- **inclusion:** Undefined (None) when FN+TP is 0.

### `false_positive_rate` (T1)

FP / (FP + TN)

- **source:** `classification.binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** FP/(FP+TN) from classification.binary_metrics.
- **inclusion:** Undefined (None) when FP+TN is 0.

### `field_presence` (T1)

Share of expected fields populated by the model

- **source:** `field_scoring.score_extraction`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** ACE-style expected-field presence. Registry source points at score_extraction, which does not emit this name.
- **inclusion:** Not computed in this package as of 0.11.0 — honesty gap, not a scorer. Do not treat a missing key as 0.0.
- **notes:** mailroom alias: expected_field_presence. HONEST GAP: score_extraction does not emit this name as of 0.11.0.

### `intake_changed_rate` (T1)

Share of documents whose intake clerk mutated the transcribed text

- **source:** `intake.score_intake`
- **ground_truth:** `optional`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of documents whose intake clerk mutated the transcribed text (intake.score_intake).
- **inclusion:** Requires paired pre/post text; skipped on empty runs.

### `intake_messy_rate` (T1)

Share of documents flagged looks_messy after intake (OCR residue / wrap artifacts)

- **source:** `intake.looks_messy`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of documents flagged looks_messy after intake (OCR residue / wrap artifacts) (intake.looks_messy).
- **inclusion:** Computed on predicted (post-intake) text.

### `intake_prep_completeness` (T1)

Share of intake prep-step invariants that hold before sorter handoff

- **source:** `intake.intake_prep_completeness`
- **ground_truth:** `structural`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of intake prep-step invariants that hold (NFC, newline unify, NBSP, zero-width, C0, hyphen unwrap, blank-run collapse, horizontal space, trim). Structural check on predicted text vs the clerk contract; not a labeled GT score (intake.intake_prep_completeness).
- **inclusion:** Computed whenever predicted text is a string. Empty string still scores the invariants (trim/NFC hold; content is empty).
- **notes:** NFC, newline unify, NBSP, zero-width, C0, hyphen unwrap, blank-run collapse, horizontal space, trim

### `jaccard_similarity` (T1)

Token-set Jaccard over positive spans (ContractEval method)

- **source:** `tasks.get_jaccard`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Token-set Jaccard over positive spans; ContractEval method (arXiv 2508.03080) via tasks.get_jaccard.
- **inclusion:** Skipped when both sides are empty. ContractEval tasks only.
- **notes:** Promoted to T1 per proposal section 3.1 (section 2.2 draft had T2); KANBAN-054 made ContractEval KPIs core.

### `laziness_rate` (T1)

Laziness detector — empty/bail responses when content is expected

- **source:** `tasks.said_no_related`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Record-level alias of contracteval_false_no_related (tasks.said_no_related): empty/bail responses when content is expected.
- **inclusion:** ContractEval / contracts specialist rows; skipped when GT expects empty.
- **notes:** alias of contracteval_false_no_related at record level

### `legalbench_accuracy` (T1)

LegalBench binary accuracy

- **source:** `tasks.legalbench_score`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** LegalBench binary accuracy (tasks.legalbench_score).
- **inclusion:** Court-opinion / LegalBench rows only; skipped when no questions.
- **notes:** part of the legalbench_* cluster — one bundle entry, sub-fields

### `legalbench_macro_f1` (T1)

LegalBench macro F1

- **source:** `tasks.legalbench_score`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** LegalBench macro-F1. Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Court-opinion / LegalBench rows only; skipped when no questions.
- **notes:** legalbench_* cluster

### `mailroom-pipeline-judge` (T1)

The-Mailroom LLM-as-judge verdict (CORRECT / PARTIAL / MISS)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** The-Mailroom JUDGE_VERDICT_SCORES; CATEGORICAL

### `mailroom-pipeline-quality` (T1)

The-Mailroom LLM-as-judge quality (0..1)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** The-Mailroom JUDGE_QUALITY_SCORES; NUMERIC

### `maud_clause_presence` (T1)

Share of expected MAUD questions present in the prediction

- **source:** `content_scoring.score_maud_extraction`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of expected MAUD questions present in the prediction.
- **inclusion:** None when the expected MAUD map is empty.

### `maud_question_accuracy` (T1)

MAUD per-question micro exact-answer accuracy over the 22 Hub keys

- **source:** `content_scoring.score_maud_extraction`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** MAUD per-question micro exact-answer accuracy over the 22 Hub keys (content_scoring.score_maud_extraction).
- **inclusion:** None when no MAUD questions are present on the row.

### `maud_question_macro_accuracy` (T1)

MAUD per-question macro accuracy (unweighted mean over questions)

- **source:** `content_scoring.score_maud_extraction`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** MAUD per-question macro accuracy (unweighted mean over questions) (content_scoring.score_maud_extraction).
- **inclusion:** None when no MAUD questions are present on the row.

### `maud_valid_class_rate` (T1)

Share of predicted MAUD answers in the question's known class set

- **source:** `content_scoring.score_maud_extraction`
- **ground_truth:** `optional`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of predicted MAUD answers in the question's known class set.
- **inclusion:** None when there are no predicted MAUD answers.

### `money_mae_usd` (T1)

Mean absolute money-field error in USD (run-level diagnostic)

- **source:** `diagnostics.extraction_diagnostics`
- **ground_truth:** `required`
- **units:** `USD` · **aggregation:** `mean`
- **citation:** Mean absolute money-field error in USD after one-cent normalize (diagnostics.extraction_diagnostics / field_scoring.parse_money).
- **inclusion:** None when either side is unparseable. Empty GT amounts skipped.
- **notes:** Existing diagnostics surface; registered so money-bearing specialist suites can emit it

### `parse_error` (T1)

Output failed to parse (quick health check — promoted per pruning plan)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name preserved; not computed in this package

### `precision` (T1)

Precision (TP / (TP + FP))

- **source:** `classification.binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** One-vs-rest / binary precision TP/(TP+FP). van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic mean (β=1), F2 uses β=2 so 5PR/(4P+R). score_task fills this from classification.macro_prf for multiclass.
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `precision_macro` (T1)

Unweighted mean of one-vs-rest precision (doc_type)

- **source:** `classification.macro_prf`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `recall` (T1)

Recall (TP / (TP + FN))

- **source:** `classification.binary_metrics`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** One-vs-rest / binary recall TP/(TP+FN). van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic mean (β=1), F2 uses β=2 so 5PR/(4P+R).
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `recall_macro` (T1)

Unweighted mean of one-vs-rest recall (doc_type)

- **source:** `classification.macro_prf`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Computed when expected and predicted label sequences are non-empty. Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. Returns 0.0 with n=0 rather than inventing a score on an empty run.

### `schema_valid` (T1)

Output parsed to the expected schema (quick health check — promoted per pruning plan)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name preserved; not computed in this package

### `sentiment_accuracy` (T1)

Enron correspondence sentiment_label accuracy (negative/neutral/positive)

- **source:** `content_scoring.score_sentiment`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Enron sentiment_label exact-match (negative/neutral/positive) (content_scoring.score_sentiment).
- **inclusion:** Skipped when sentiment gold is empty/null.

### `sentiment_f1_macro` (T1)

Enron correspondence sentiment_label macro-F1

- **source:** `content_scoring.score_sentiment`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Enron sentiment_label macro-F1 (content_scoring.score_sentiment).
- **inclusion:** Skipped when sentiment gold is empty/null.

### `stage_correct` (T1)

Per-stage correctness (mailroom pipeline pilot)

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** mailroom SCORE_CONFIGS name

### `subclass_accuracy` (T1)

HF pipeline subclass accuracy (CUAD family / CMS table / Enron form / …)

- **source:** `tasks.score_task`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Exact-match accuracy over the document subclass catalog (CUAD family / CMS table / Enron form / record type).
- **inclusion:** Attached by score_task only when subclass kwargs (or per-row subclass labels) are present; otherwise the subclass_* keys are omitted / None.

### `subclass_f1_macro` (T1)

Macro-F1 over doc subclasses (CUAD family / CMS table / Enron form / …)

- **source:** `tasks.score_task`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Macro-F1 over document subclasses. Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Attached by score_task only when subclass kwargs (or per-row subclass labels) are present; otherwise the subclass_* keys are omitted / None.

### `subclass_f2_macro` (T1)

Macro F2 over doc subclasses

- **source:** `tasks.score_task`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Macro F2 over document subclasses. Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta. van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic mean (β=1), F2 uses β=2 so 5PR/(4P+R).
- **inclusion:** Attached by score_task only when subclass kwargs (or per-row subclass labels) are present; otherwise the subclass_* keys are omitted / None.

### `subclass_precision_macro` (T1)

Macro precision over doc subclasses

- **source:** `tasks.score_task`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Macro precision over document subclasses. Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Attached by score_task only when subclass kwargs (or per-row subclass labels) are present; otherwise the subclass_* keys are omitted / None.

### `subclass_recall_macro` (T1)

Macro recall over doc subclasses

- **source:** `tasks.score_task`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Macro recall over document subclasses. Unweighted macro-average of one-vs-rest P/R/Fβ over the label set (Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta.
- **inclusion:** Attached by score_task only when subclass kwargs (or per-row subclass labels) are present; otherwise the subclass_* keys are omitted / None.

### `success_rate` (T1)

Runs completing without abort/stage failure

- **source:** `null (emitter-only)`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse transport alias preserved so consolidation is lossless.
- **inclusion:** Never produced by this package's scorers; value is whatever the pipeline emits. Skip when the emitter omits the key.
- **notes:** consolidates mailroom stage_completed + run_aborted; not computed in this package

### `verified_precision` (T1)

Precision restricted to doc-verifiable items

- **source:** `field_scoring.audit_list_field`
- **ground_truth:** `optional`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Precision restricted to doc-verifiable list items (field_scoring.audit_list_field token-coverage check).
- **inclusion:** None when verification is disabled or the row has no audited list fields.
- **notes:** mailroom alias: extraction_overall_verified_precision

### `wer` (T1)

Word error rate (word-level Levenshtein / |reference|); lower is better

- **source:** `asr.word_error_rate`
- **ground_truth:** `required`
- **units:** `error_rate` · **aggregation:** `mean`
- **citation:** Word error rate: word-level Levenshtein / |reference| (NIST ASR; asr.word_error_rate). May exceed 1.0 when the hypothesis is longer.
- **inclusion:** Requires a non-empty reference transcript. Empty hypothesis is WER=1.0 when reference is non-empty.
- **notes:** WER may exceed 1.0 when the hypothesis is longer than the reference

### `word_accuracy` (T1)

max(0, 1 - WER) complementary transcription headline

- **source:** `asr.word_accuracy`
- **ground_truth:** `required`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** max(0, 1 − WER) complementary transcription headline (asr.word_accuracy).
- **inclusion:** Same inclusion as wer.

### `ttft_seconds` (T0)

Time to first token (streaming first-token timestamp − request start)

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `mean`
- **citation:** Time to first token: t_first_token − t_request_start (vLLM / NVIDIA NIM / OpenAI streaming). serving.score_serving_run.
- **inclusion:** None unless first-token timestamp or explicit ttft_seconds is recorded. Never inferred from e2e / n_tokens.

### `tokens_per_second` (T0)

Decode throughput: completion_tokens / e2e latency

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `tokens/s` · **aggregation:** `mean`
- **citation:** Decode throughput: completion_tokens / e2e_latency (vLLM tokens/s convention).
- **inclusion:** None when e2e ≤ 0 or completion_tokens missing.

### `tpot_seconds` (T1)

Time per output token after the first: (e2e − ttft) / (completion_tokens − 1)

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `mean`
- **citation:** Time per output token after the first: (e2e − ttft) / (completion_tokens − 1) (NVIDIA NIM TPOT / inter-token latency).
- **inclusion:** None when TTFT missing, completion_tokens ≤ 1, or e2e < ttft.

### `e2e_latency_seconds` (T1)

End-to-end request wall-clock (start → last token)

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `mean`
- **citation:** End-to-end wall-clock from request start to last token (or recorded latency).
- **inclusion:** None when neither duration nor start/end timestamps are present.

### `gpu_utilization` (T1)

Local GPU SM utilization in [0,1]. None on API-key runs

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Local GPU SM utilization in [0,1] from nvidia-smi / vLLM. Values >1 treated as percent.
- **inclusion:** None on API-key providers and when the local run did not record utilization.

### `kv_cache_utilization` (T1)

vLLM KV-cache / prefix-cache occupancy in [0,1]. None on API-key runs

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** vLLM KV-cache / prefix-cache occupancy in [0,1].
- **inclusion:** None on API-key providers and when the local engine did not expose cache stats.

### `gpu_memory_used_gb` (T1)

Local GPU memory used (GiB). None on API-key runs

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `GB` · **aggregation:** `mean`
- **citation:** Local GPU memory used (GiB).
- **inclusion:** None on API-key providers and when memory was not recorded.

### `ttft_p50` (T1)

Median TTFT over per-request observations

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `none`
- **citation:** Median TTFT over per-request observations (linear interpolation percentile).
- **inclusion:** None when no request has TTFT.

### `ttft_p95` (T1)

95th-percentile TTFT over per-request observations

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `none`
- **citation:** 95th-percentile TTFT over per-request observations.
- **inclusion:** None when no request has TTFT.

### `e2e_p50` (T1)

Median end-to-end latency over per-request observations

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `none`
- **citation:** Median end-to-end latency over per-request observations.
- **inclusion:** None when no request has e2e.

### `e2e_p95` (T1)

95th-percentile end-to-end latency over per-request observations

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `none`
- **citation:** 95th-percentile end-to-end latency over per-request observations.
- **inclusion:** None when no request has e2e.

### `output_tokens_per_second` (T1)

Decode-only throughput: completion_tokens / (e2e − ttft)

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `tokens/s` · **aggregation:** `mean`
- **citation:** Decode-only throughput: completion_tokens / (e2e − ttft).
- **inclusion:** None when TTFT missing or e2e ≤ ttft.

### `prompt_tokens_per_second` (T1)

Prefill throughput: prompt_tokens / ttft

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `tokens/s` · **aggregation:** `mean`
- **citation:** Prefill throughput: prompt_tokens / ttft.
- **inclusion:** None when TTFT missing or prompt_tokens missing.

### `requests_per_second` (T1)

n_requests / summed e2e window (sequential serving throughput)

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `req/s` · **aggregation:** `mean`
- **citation:** n_requests / summed e2e window (sequential serving throughput).
- **inclusion:** None when no e2e observations.

### `docs_per_second` (T1)

n_docs / summed e2e window

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `docs/s` · **aggregation:** `mean`
- **citation:** n_docs / summed e2e window (documents processed per second).
- **inclusion:** None when no e2e observations or n_docs is 0.

### `queue_time_seconds` (T1)

Scheduler wait before generation (vLLM waiting_time / queue_time)

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `seconds` · **aggregation:** `mean`
- **citation:** Scheduler wait before generation (vLLM waiting_time / queue_time).
- **inclusion:** None when the engine did not record queue wait.

### `error_rate` (T1)

Share of serving requests flagged error/failed

- **source:** `serving.aggregate_serving`
- **ground_truth:** `none`
- **units:** `float[0,1]` · **aggregation:** `mean`
- **citation:** Share of serving requests flagged error/failed.
- **inclusion:** 0.0 when n_requests > 0 and none failed. None when there are no requests.

### `prompt_tokens` (T1)

Sum of prompt/input tokens over observations

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `count` · **aggregation:** `sum`
- **citation:** Sum of prompt/input tokens over observations (OpenAI usage.prompt_tokens).
- **inclusion:** None when no observation recorded prompt tokens.

### `completion_tokens` (T1)

Sum of completion/output tokens over observations

- **source:** `serving.score_serving_run`
- **ground_truth:** `none`
- **units:** `count` · **aggregation:** `sum`
- **citation:** Sum of completion/output tokens over observations (OpenAI usage.completion_tokens).
- **inclusion:** None when no observation recorded completion tokens.


