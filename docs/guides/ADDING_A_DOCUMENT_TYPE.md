# Adding, swapping or retiring a document type

This checklist covers adding a new mailroom document type end to end. The pieces are its
extraction schema per subtype, its scorers, its specialist agent, and the sandbox wiring
that evaluates it. Run the steps in order: **Dojo → llm-mailroom → sandbox**. Each repo pins
the one before it, so working out of order produces drift-test failures that point to the
wrong place.

Throughout, `<type>` is the new class key (snake_case, singular, e.g. `insurance_claim`),
`<agent>` is its specialist (plural, `_specialist`, e.g. `insurance_claims_specialist`),
and `<Schema>` is its Pydantic model (e.g. `InsuranceClaimExtraction`).

> **Ground truth default.** Field status, subtypes and every honest-gap note are derived
> from **`Lucius-Morningstar/mailroom-dataset`**. It is the default everywhere
> (`scripts/build_extraction_status.py:DATASET`, llm-mailroom `pipeline/hf_corpora.py`,
> sandbox `datasets.py:HF_DATASET`). A new type ships its labelled rows **into
> mailroom-dataset first**. Do not point a class at a different dataset. If a type has
> no rows there yet, it can be added as *scored-later* (step 0, option B), but it is not
> a live class until the rows exist.

## 0. Decide before you touch code

- [ ] **Key names**: `<type>`, `<agent>`, `<Schema>`, plus the auditor name if one is
      planned (`<type-plural>_auditor`).
- [ ] **Subtypes**: the canonical snake_case keys, and the corpus surfaces they normalise
      from (folder-style labels, Hub strings).
- [ ] **Field map**: each field and its scorer type: `name`, `date`, `money`, `id`,
      `free_text`, `entity_list:<inner>`, or a scored enum. This map is the scoring contract;
      the Pydantic model and the taxonomy must match it exactly.
- [ ] **Live or scored-later**:
      - A: rows already in mailroom-dataset → live class (all steps).
      - B: rows still pending → register scoring only (steps 1 and 3), leave it out of
        `LIVE_*`, `MAILROOM_DOC_TYPES` and the taxonomy, and record an `_HONEST_GAPS` note.
        The per-subtype schema registry (step 2) covers live classes only:
        `extraction_schema()` accepts `MAILROOM_DOC_TYPES`, which must equal
        `LIVE_DOC_TYPES`, so a scored-later type gets its registry entry when it goes live.
- [ ] **Swap instead of add?** If a type is replacing another, do this checklist for the new
      one and the **Retire** section for the old one in the same release.

## 1. Dojo: registries (`llm_dojo_scoring/`)

Every list below is checked by a drift test. Add `<type>` to all of them in one commit.

| Where | What to add |
|---|---|
| `config.py` | `DOC_CLASS_KEYS`; also `LIVE_DOC_CLASS_KEYS` if live |
| `pipeline/mailroom.py` | `LIVE_DOC_TYPES` and `LIVE_SPECIALISTS` (live), or `RETIRED_*` |
| `schemas/extraction_schemas.py` | `MAILROOM_DOC_TYPES` (must equal `LIVE_DOC_TYPES`) |
| `schemas/corpus.py` | `DOC_TYPE_SUBCLASSES[<type>]`, `CORPUS_SUBCLASS_SURFACES[<type>]`, and the per-type tables lower in the file that every class has an entry in |
| `scoring/suites.py` | `SPECIALIST_DOC_TYPES[<agent>] = <type>` (this drives `DOC_TYPE_ALIASES`); `DEFAULT_FIELD_TYPES[<type>]` (the field map); `_AGENT_EXTRAS[<agent>]` for class extras; `_HONEST_GAPS[<agent>]` for any known gap |
| `metrics/profiles.py` | a `DEFAULT_PROFILES` entry: `_p("<agent>", "<Title> Extraction", ("extract",), "extraction", doc_bundle="<type>")`. `DEFAULT_SUITES` is built from this, so `get_suite("<type>")` works once it exists |
| `metrics/doc_bundles.py` | `DOC_TYPES` and `DOC_TYPE_BUNDLES[<type>]` (headline metrics) |
| `metrics/bundles.py` | the `<agent>` entry in the extraction bundle |
| `schemas/intents.py` | `INTENT_LABELS[<type>]` and `INTENT_DESCRIPTIONS[<type>]` |
| `schemas/scored_enums.py` | only if a field is a closed enum |
| `prompts/catalog.yaml` + `prompts/templates/` | `<agent>.docclass.md`, `<agent>.production.md`, `<agent>.production_prompts.md`; add `<type>` to the shared templates that list every class (`sorter_reviewer`, `judge*`, `arbiter`, `boss`) |

## 2. Dojo: extraction schema per subtype

- [ ] Add `<type>` to the `FIVE` tuple in `scripts/build_extraction_status.py`; the
      script only reads and writes the classes listed there.
- [ ] Run it against the pinned Hub revision (pyarrow is not a Dojo dependency):
      `uv run --extra dev --with pyarrow python scripts/build_extraction_status.py
      --parquet-dir <path>/ground_truth --revision <tag> --commit <sha>`. It reads the
      mailroom-dataset `ground_truth` parquet and freezes per-subtype field status into
      `schemas/data/extraction_status.json`, with the revision recorded. Do not
      hand-edit the JSON; `--check` reports drift.
- [ ] Subtype-only fields and salient guidance go in `_build()` in
      `schemas/extraction_schemas.py` (see the CMS `cms_source_table` and the corporate-record
      subclass entities for examples).
- [ ] Check: `extraction_schema("<type>")` and `extraction_schema("<type>", "<subtype>")`
      both build, and `registry_violations() == []`.

## 3. Dojo: tests, release

- [ ] `tests/test_extraction_schemas.py` (`registry_violations`), `test_doc_bundles`, the
      suite and profile tests: add `<type>` wherever they parametrise over classes.
- [ ] Add a scoring smoke test:
      `get_suite("<type>").score([gt, gt], [gt, {}])` returns `headline_scope` and a
      non-null `quality_mean`.
- [ ] `uv run --extra dev pytest tests -q` and `uvx ruff check …` pass.
- [ ] This is a public-API change. Use `/cross-repo-bump` and
      `python scripts/release.py cut X.Y.0` (a minor version, because a class is new). `cut`
      is a dry run that prints the plan; review it, then rerun with `--apply` to stamp the
      changelog and move the version pins.

## 4. llm-mailroom: the specialist (`src/`)

| Where | What to add |
|---|---|
| `config/taxonomy.yaml` | a `doc_classes` entry (`key`, `label`, `schema: <Schema>`, `specialist: <agent>`, `description`, `field_types` = the Dojo map exactly) and a confidence `bands` entry (`high`, `low`, `judge_band_high`). The sorter reads its label set from here |
| `schemas/documents.py` + `schemas/__init__.py` | `class <Schema>(BaseModel)` and its registry entry |
| `langchain_agents/specialist_agents.py` | the `<TYPE>_SCHEMA` structured-output schema and its class-map entry |
| `langchain_agents/doc_inventories.py` | the subtype inventory and the `kind == "<type>"` branches |
| `langchain_agents/prompts.py` | the sorter class description and the class lists in the reviewer prompts |
| `agents/<agent>.py` | copy `insurance_claims_specialist.py`: `agent_name`, a `SYSTEM_PROMPT_V0` fallback, `extract()` |
| `llm/frozen_v1/<agent>.txt` + `lineage.json` | the frozen prompt bytes (these must match the Dojo `production` template) |
| `graph/build_graph.py` | the `"<agent>": _extract_<plural>` dispatch entry and its `_run_chunked_extraction` function |
| `observability/agent_eval.py` | the agent list, the `<type> → <agent>` map, and the module path |
| `pipeline/hf_corpora.py` | the Hub class list (mailroom-dataset) |
| `pyproject.toml` | bump the Dojo pin to the new release |

- [ ] `tests/test_dojo_parity.py`: add `<type>` to its `LIVE_DOC_TYPES`. It checks the prompts
      and `field_types` against the pinned Dojo.
- [ ] Add a `tests/test_<type>_class.py` modelled on `test_insurance_claim_class.py`
      (routing, schema, sorter label).
- [ ] Known gap: `observability/suite_scoring.py` does not pass the subclass kwargs to
      `score_document` yet. Any type with per-subtype fields depends on it.

## 5. Sandbox (`local-mailroom-sandbox`)

- [ ] Re-vendor both packages with `/vendor-sync` (never hand-edit `vendor/`). Update the
      `_VENDOR_PINS` and `requirements/dojo-release.txt` pins together.
- [ ] `src/mailroom_sandbox/eval/agents.py`: the `<agent> → <type>` map and the
      `("agents.<agent>", "<Class>")` import entry.
- [ ] `src/mailroom_sandbox/eval/schema_adherence.py`: the class field set and the class
      tuple in the agent-name fallback.
- [ ] `src/mailroom_sandbox/job/specialist_posture.py`: the per-class posture entry.
- [ ] `config/components.yaml`: enable `<agent>` and choose its prompt variant.
- [ ] Add a mock run config under `config/runs/`, then run `sandbox pilot --mock` (no spend).
      Paid runs go through `sandbox run preflight` and a human with initials.

## Retire (or swap out) a type

Keep the scorer so historical traces still score. Remove the class from the live surface only.

- [ ] Dojo: move it from `LIVE_DOC_CLASS_KEYS` / `LIVE_DOC_TYPES` / `LIVE_SPECIALISTS` to the
      matching `RETIRED_*` lists, and drop it from `MAILROOM_DOC_TYPES`. Add an
      `_HONEST_GAPS` note saying when and why (see `court_opinions_specialist`). Rebuild
      `extraction_status.json`.
- [ ] llm-mailroom: remove the `taxonomy.yaml` class (the sorter then emits `unknown`, which
      routes to human review) and the graph dispatch entry. Keep the agent module only if
      historical replays need it.
- [ ] Sandbox: re-vendor, and remove the class from the eval maps and `components.yaml`.

## Done when

- [ ] `registry_violations() == []` in Dojo, `test_dojo_parity.py` passes in llm-mailroom,
      and `test_vendor_drift.py` passes in the sandbox.
- [ ] `get_suite("<type>")`, `extraction_schema("<type>", <each subtype>)` and the specialist
      all resolve from the same key.
- [ ] Every honest gap for the class names mailroom-dataset row counts, not guesses.
