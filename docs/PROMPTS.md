
# Prompt catalog (v0.22.0)

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
| --- | --- |
| `production` (default) | Live mailroom prompt bodies, re-vendored verbatim by `scripts/sync_production_prompts.py` from a mailroom checkout (each row records `source_commit`). Sorter is `sorter_v14`. The five specialists are the frozen v1 bytes: they equal `production_prompts` (`version: v1`, `source_key: frozen_v1`). `reporter` is `kind: deterministic`. |
| `docclass` | Latest key from entity-extraction `src/prompts_docclass.py` (`sorter_docclass_v7`, `*_specialist_docclass_v1`, `reviewer_docclass_v1`, `judge_*_docclass_v1`, `arbiter_docclass_v1`, `boss_docclass_v1`). |
| `production_prompts` | Frozen eval-environment **v1** specialist lineage (`mailroom-dataset-v1`, frozen 2026-09-26T05:09:29+00:00). Five sha256-locked stems; not grouped with `docclass`. |

This catalog does **not** vendor the ~1.8MB historical prompt archive.

## Frozen `production_prompts` v1 lineage

The five live specialists have a frozen v1 stem that Modal / vLLM specialist
evals inject. The dojo stores them as `family="production_prompts"`,
`version="v1"`, derived from the sandbox `config/prompts/<stem>.txt`
files and sha256-pinned on each record (hash over the loaded text plus a
trailing newline, matching the sandbox lineage's normalization).

Corporate-record and correspondence stems carry field-guidance corrections that
eval-environment froze as the mutations `corporate_records_specialist_v6` and
`correspondence_specialist_v7` (2026-10-16, #29; byte-identical, same digests).
Their `source_key` names those mutation keys and their provenance comments keep
the superseded v1 digests. eval-environment's default for both roles stays `_v1`;
select the corrected text there with `--prompt-version`. Other stems remain
byte-identical to the frozen v1 source. Catalog digests identify the current text.

| Agent | Eval-environment key | Sandbox stem | `sha256` (prefix) |
| --- | --- | --- | --- |
| `contracts_specialist` | `contracts_specialist_v1` | `contracts_specialist_v33_simplified` | `d91de396…` |
| `corporate_records_specialist` | `corporate_records_specialist_v6` (corrects `_v1`) | `corporate_records_specialist_simplified` | `fe13501f…` |
| `correspondence_specialist` | `correspondence_specialist_v7` (corrects `_v1`) | `correspondence_specialist_simplified` | `2b0b81ff…` |
| `insurance_claims_specialist` | `insurance_claims_specialist_v1` | `insurance_claims_specialist_simplified` | `6c2776bc…` |
| `merger_agreement_specialist` | `merger_agreement_specialist_v1` | `merger_agreement_specialist_simplified` | `00323258…` |

`tests/test_production_prompts.py` recomputes every digest from the imported
`PromptRecord.text`; do not edit a template without a sanctioned
re-freeze and a matching catalog/test update.

Field maps those stems emit (and the scorer grades) are documented in
[`EXTRACTION_SCHEMAS.md`](EXTRACTION_SCHEMAS.md).

## eval-environment prompt lineage

`eval_environment_lineage.json` vendors **every** version of the eval-environment
`mailroom-dataset-v1` lineage, not just the five specialist stems above: the
archived production prompts (`<role>_v0`, plus `contracts_specialist_v33`), the
frozen `<role>_v1` snapshot, and the GEPA / manual mutations (`<role>_v2` ...).
40 versions, 15 roles, pinned to eval-environment commit `bdba24c`
(`LINEAGE_SOURCE`). eval-environment's live `production` kind is not a frozen
version and is not included. The texts are historical eval-environment bytes:
the anti-priming rule below is not applied to them.

```python
from llm_dojo_scoring.prompts import (
    get_prompt_version, prompt_chain, diff_prompt_versions, default_prompt_version,
)

v = get_prompt_version("correspondence_specialist_v7")
v.text, v.memo, v.parent, v.changes["sections_changed"]
[x.key for x in prompt_chain("correspondence_specialist")]   # v0 -> v7
print(diff_prompt_versions("correspondence_specialist_v6", "correspondence_specialist_v7"))
default_prompt_version("sorter").key                          # "sorter_v1"
```

| Call | Returns |
| --- | --- |
| `list_prompt_versions(role=None, lineage=None)` | `list[PromptVersion]` sorted by `(role, version)`; `lineage` is `archived`, `frozen` or `mutation` |
| `get_prompt_version(key)` | one version; `KeyError` with close-match suggestions on an unknown key |
| `prompt_roles()` | sorted role names (key minus `_v<N>`; roles may contain hyphens) |
| `prompt_chain(key_or_role)` | oldest to newest along `predecessor` links; a role name means the chain ending at `latest_prompt_version(role)` |
| `latest_prompt_version(role)` | highest-version `frozen` or `mutation` entry (archived only if a role has nothing else) |
| `default_prompt_version(role)` | the frozen `<role>_v1` (eval-environment's default) |
| `diff_prompt_versions(a, b, context=3)` | unified diff of the two texts, labelled with the keys |
| `LINEAGE_SOURCE` | `{source_repo, source_commit, lineage_id}` |

`PromptVersion` fields: `key`, `role`, `version`, `lineage`, `parent`
(mutations), `supersedes` (frozen v1 to its archived `_v0`), `memo`,
`anchor_head`, `created_at`, `source`, `sha256`, `chars`, `text`, `changes`;
`predecessor` is `parent or supersedes`. `changes` (None for roots) compares
against the predecessor: `against`, `lines_added`, `lines_removed`,
`chars_delta`, `sections_changed` (heading-like lines whose block changed),
`added_excerpt` / `removed_excerpt` (first 5 non-blank lines, 160 chars max),
and `notes` (data-quality observations, usually empty).

**Digests.** `sha256` here is eval-environment's: `sha256(text.encode("utf-8"))`
over the raw text. The `production_prompts` catalog above hashes the text with a
trailing newline ensured. They are equal for the specialist stems (those texts
end in `"\n"`), so `correspondence_specialist_v7` / `corporate_records_specialist_v6`
are byte-equal to `get_prompt(<role>, family="production_prompts").text` with the
same digest. Prompts without a trailing newline (sorter, judges) would differ
between the two conventions.

**Quirks in the source data** (recorded, not corrected):

- `created_at` is not monotonic along the sorter chain: `sorter_v2` / `sorter_v3`
  were created 2026-09-16, before the 2026-09-26 freeze of `sorter_v1`.
- `sorter_v3` contains its corporate_record block twice (known upstream defect);
  its `changes.notes` says so. `sorter_v4` removes the duplicate (also noted in
  its `changes.notes`) and, once its single corporate_record block is cut out,
  equals the `production` sorter (`sorter_v14`) text plus the catalog's trailing
  newline (lineage texts are raw; dojo templates end in exactly one `"\n"`).
- `contracts_specialist_v33` (Modal parity prompt) is a re-keyed copy of the
  archived `contracts_specialist_v0`: its text equals `_v0` apart from a trailing
  newline (the entry's memo says so). It has no predecessor and the highest
  number, so `latest_prompt_version(role)` skips archived entries (unless a role
  has nothing else) and returns `contracts_specialist_v3`; `prompt_chain` of the
  role walks v0 to v3. `list_prompt_versions` still lists v33 and
  `prompt_chain("contracts_specialist_v33")` works for the explicit key. Its
  manifest `chars` is a UTF-8 byte count; the entry stores the character count.

| Role | Versions | Latest |
| --- | --- | --- |
| `arbiter` | v1 | `arbiter_v1` |
| `boss` | v1 | `boss_v1` |
| `contracts_specialist` | v0, v1, v2, v3, v33 | `contracts_specialist_v3` |
| `corporate_records_specialist` | v0 to v6 | `corporate_records_specialist_v6` |
| `correspondence_specialist` | v0 to v7 | `correspondence_specialist_v7` |
| `insurance_claims_specialist` | v0 to v3 | `insurance_claims_specialist_v3` |
| `intake` | v1 | `intake_v1` |
| `judge` | v1 | `judge_v1` |
| `judge-classification` | v1 | `judge-classification_v1` |
| `judge-correctness` | v1 | `judge-correctness_v1` |
| `merger_agreement_specialist` | v1 to v3 | `merger_agreement_specialist_v3` |
| `pipeline_quality` | v1 | `pipeline_quality_v1` |
| `pipeline_verdict` | v1 | `pipeline_verdict_v1` |
| `sorter` | v1 to v4 | `sorter_v4` |
| `sorter_reviewer` | v1 | `sorter_reviewer_v1` |

Re-sync (reads the data files and parses the Python sources with `ast`; no
eval-environment code runs, `llm` is not needed):

```bash
python scripts/sync_eval_environment_lineage.py --eval-env <eval-environment>          # write
python scripts/sync_eval_environment_lineage.py --eval-env <eval-environment> --check  # exit 1 on drift
```

The sync fails on any sha256 mismatch against the manifests, a missing
predecessor, or uncommitted lineage changes in the checkout. The JSON is
byte-deterministic: `synced_at` is the source commit date, never wall-clock.
`--check` ignores a moved `source_commit` when the version content is identical.

## `PromptRecord`

| Field | Role |
| --- | --- |
| `agent` | Profile / judge-variant name |
| `family` | `production`, `docclass`, or `production_prompts` |
| `version` | Source key / version tag (`v1` on the frozen lineage) |
| `kind` | `llm` \| `deterministic` \| `procedural` \| `proposed` |
| `text` | Model-visible body (`""` when `kind != llm`) |
| `metrics_bundle` | Bundle the output is scored against |
| `doc_bundle` | Field-map document class, if any |
| `source_repo` / `source_key` | Provenance |
| `source_commit` | Mailroom commit a `production` row was last synced from (else `""`) |
| `sha256` | Freeze digest on `production_prompts` records (else `""`) |
| `priming` | Flags for colloquial or JSON-schema collisions (see below) |
| `notes` | Human contract for non-LLM roles |

## Which roles have no LLM body

| Role | `kind` | What the catalog stores |
| --- | --- | --- |
| `reporter` | `deterministic` | Procedural matter-record assembler: the pipeline formats classification and extraction fields; no LLM call. The template file keeps the live procedural text for provenance; `text` stays `""`. |
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
| --- | --- |
| `colloquial_precision` | Docclass contracts specialist text says “precision” in English (the production body is frozen v1 and no longer does). |
| `colloquial_completeness` | Docclass contracts / judge-docclass text says “completeness” in English. |
| `schema_valid` / `classification_correct` / `extraction_correctness` | Live judge JSON schema keys that collide with registry names. Left as output keys, not eval priming. |

New dojo-authored keys stay clean (no registry ids in `text`).

## Re-vendoring the `production` family

```bash
OPENROUTER_API_KEY=dummy PYTHONPATH=<mailroom>/src \
  python scripts/sync_production_prompts.py --mailroom <mailroom>          # write
  python scripts/sync_production_prompts.py --mailroom <mailroom> --check  # exit 1 on drift
```

The script imports mailroom's `llm.prompts.prompt_templates()`, writes every
live body to `<agent>.production.md` verbatim behind a provenance comment, and
updates the matching catalog rows. Agents retired in mailroom (for example
`compliance_specialist`) keep their last vendored body and are not touched.

### Not vendored

`gmail_triage`, `intake` (LLM prompt) and `relations` are live mailroom agents
with no dojo profile in `DEFAULT_PROFILES`, so they have no `production` row.
`intake` stays catalogued as the deterministic clerk. Add a profile first if
the dojo should score them.
