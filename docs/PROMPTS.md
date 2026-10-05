# Prompt catalog (v0.16.0)

Importable catalog of the prompts the dojo scores against. This package
**does not execute agents** — it vendors the live production template, the
latest docclass-merged family, and the eval-environment frozen
`production_prompts` v1 lineage so dependents can import one copy.

Metric names live on catalog **metadata** (`metrics_bundle`, `doc_bundle`).
They are not eval targets in the model-visible string.

## Import

```python
from llm_dojo_scoring.prompts import get_prompt, list_prompts

get_prompt("sorter")                       # production (mailroom sorter_v14)
get_prompt("sorter", family="docclass")    # docclass-merged arm (sorter_docclass_v7)
get_prompt("contracts_specialist", family="production_prompts")  # frozen eval-environment v1
get_prompt("intake")                       # kind=deterministic, text=""
```

Pin the package, then swap the in-repo constant:

```python
from llm_dojo_scoring.prompts import get_prompt
system = get_prompt("contracts_specialist", family="docclass").text
```

`list_prompts()` returns every catalog entry. Filter with `agent=`, `family=`,
or `kind=`. Every name in `DEFAULT_PROFILES` (26 agents) has at least one
entry. Judge variants (`judge-completeness`, `judge-classification`,
`judge-correctness`) are extra keys for the completeness / classification /
correctness arms.

## Families

| `family` | Meaning |
|---|---|
| `production` (default) | Live mailroom / entity production constant. Sorter remains `sorter_v14`; contracts specialist remains `contracts_specialist_v32`. |
| `docclass` | Latest key from entity-extraction `src/prompts_docclass.py` (`sorter_docclass_v7`, `*_specialist_docclass_v1`, `reviewer_docclass_v1`, `judge_*_docclass_v1`, `arbiter_docclass_v1`, `boss_docclass_v1`). |
| `production_prompts` | Frozen eval-environment **v1** specialist lineage (`mailroom-dataset-v1`, frozen 2026-09-26T05:09:29+00:00). Five sha256-locked stems; not grouped with `docclass`. |

This catalog does **not** vendor the ~1.8MB historical prompt archive.

## Frozen `production_prompts` v1 lineage

The five live specialists have a frozen v1 stem that Modal / vLLM specialist
evals inject. The dojo stores them as `family="production_prompts"`,
`version="v1"`, derived from the sandbox `config/prompts/<stem>.txt`
files and sha256-pinned on each record (hash over the loaded text plus a
trailing newline, matching the sandbox lineage's normalization).

Corporate-record and correspondence stems include local field-guidance corrections;
their provenance comments preserve the original source digests. Other stems remain
byte-identical to the frozen source. Catalog digests identify the current text.

| Agent | Eval-environment key | Sandbox stem | `sha256` (prefix) |
|---|---|---|---|
| `contracts_specialist` | `contracts_specialist_v1` | `contracts_specialist_v33_simplified` | `d91de396…` |
| `corporate_records_specialist` | `corporate_records_specialist_v1` | `corporate_records_specialist_simplified` | `fe13501f…` |
| `correspondence_specialist` | `correspondence_specialist_v1` | `correspondence_specialist_simplified` | `2b0b81ff…` |
| `insurance_claims_specialist` | `insurance_claims_specialist_v1` | `insurance_claims_specialist_simplified` | `6c2776bc…` |
| `merger_agreement_specialist` | `merger_agreement_specialist_v1` | `merger_agreement_specialist_simplified` | `00323258…` |

`tests/test_production_prompts.py` recomputes every digest from the imported
`PromptRecord.text`; do not edit a template without a sanctioned
re-freeze and a matching catalog/test update.

## `PromptRecord`

| Field | Role |
|---|---|
| `agent` | Profile / judge-variant name |
| `family` | `production`, `docclass`, or `production_prompts` |
| `version` | Source key / version tag (`v1` on the frozen lineage) |
| `kind` | `llm` \| `deterministic` \| `procedural` \| `proposed` |
| `text` | Model-visible body (`""` when `kind != llm`) |
| `metrics_bundle` | Bundle the output is scored against |
| `doc_bundle` | Field-map document class, if any |
| `source_repo` / `source_key` | Provenance |
| `sha256` | Freeze digest on `production_prompts` records (else `""`) |
| `priming` | Flags for colloquial or JSON-schema collisions (see below) |
| `notes` | Human contract for non-LLM roles |

## Which roles have no LLM body

| Role | `kind` | What the catalog stores |
|---|---|---|
| `intake` | `deterministic` | Clerk invariants (NFC, newline unify, NBSP, zero-width, C0, hyphen unwrap, blank-run / horizontal collapse, trim). Gold is `llm_dojo_scoring.intake`. |
| `archivist` | `procedural` | Content-addressed archive + audit hash. No system prompt. |
| `local_vs_api` | `procedural` | Serving comparison (TTFT, throughput, utilization, identity). No system prompt. Gold is recorded timings, not a quality label. |
| `corporate_records_auditor`, `due_diligence_auditor`, `correspondence_auditor`, `compliance_auditor`, `court_opinions_auditor`, `insurance_claims_auditor` | `proposed` | Stub pointing at the specialist field map + suite `score()`. **No LLM body.** |
| `audit_agent` / `contract_auditor` | `llm` | The only authored auditor prompt: entity-extraction `contracts_audit_v0`. |

Do not invent “you are an auditor, maximize F1” prompts for those stubs.
Authoring them is a pipeline-changing job, not a docs change.

## Anti-priming rule

Two layers, kept separate:

1. **Metadata (for authors):** each LLM entry lists the bundle + field map the
   output will be scored against. That lives in `catalog.yaml`, never as
   “you will be scored on `extraction_f1`” in the template.
2. **Template body:** task, output schema, catalogs (doc types, Enron topics,
   CUAD families). **Forbidden in model-visible text:** T0/T1 registry ids
   (`extraction_f1`, `f1_macro`, `determination_consistency`, …), “you will be
   scored”, F1/F2/precision/recall as eval targets, numeric leaderboard
   snippets.

English task language already in production (“extract with precision”,
“COMPLETENESS IS THE PRIORITY”) is **flagged**, not rewritten — rewriting
production would change eval numbers.

| Flag | Meaning |
|---|---|
| `colloquial_precision` | Live contracts specialist text says “precision” in English. |
| `colloquial_completeness` | Live contracts / judge-docclass text says “completeness” in English. |
| `schema_valid` / `classification_correct` / `extraction_correctness` | Live judge JSON schema keys that collide with registry names. Left as output keys, not eval priming. |

New dojo-authored keys stay clean (no registry ids in `text`).
