# Prompt catalog (v0.12.0)

Importable catalog of the prompts the dojo scores against. This package
**does not execute agents** — it vendors the live production template plus
the latest docclass-merged family so dependents can import one copy.

Metric names live on catalog **metadata** (`metrics_bundle`, `doc_bundle`).
They are not eval targets in the model-visible string.

## Import

```python
from llm_dojo_scoring.prompts import get_prompt, list_prompts

get_prompt("sorter")                       # production (mailroom sorter_v14)
get_prompt("sorter", family="docclass")    # docclass-merged arm (sorter_docclass_v7)
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

This catalog does **not** vendor the ~1.8MB historical prompt archive.

## `PromptRecord`

| Field | Role |
|---|---|
| `agent` | Profile / judge-variant name |
| `family` | `production` or `docclass` |
| `version` | Source key / version tag |
| `kind` | `llm` \| `deterministic` \| `procedural` \| `proposed` |
| `text` | Model-visible body (`""` when `kind != llm`) |
| `metrics_bundle` | Bundle the output is scored against |
| `doc_bundle` | Field-map document class, if any |
| `source_repo` / `source_key` | Provenance |
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
