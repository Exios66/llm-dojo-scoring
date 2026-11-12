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
      `free_text`, `entity_list:<inner>`, or `label` for a closed enum (0.28.0: every
      `label` field needs its vocabulary in `schemas/scored_enums.py`, and the scorer folds
      aliases through `canonical_label` before the exact match). This map is the scoring contract and
      lives in one place, `schemas/doc_classes.py`; the Pydantic model and the taxonomy must match it
      exactly. Take the fields from the dataset's labelled columns (`docs/schemas/GT_COVERAGE.md`
      lists what each class's ground truth populates today); a field the dataset does not label yet
      can still go in the map and is reported `pending_annotation`, never scored.
- [ ] **Live or scored-later**:
      - A: rows already in mailroom-dataset → live class (all steps).
      - B: rows still pending → register scoring only (steps 1 and 3) with `live=False` and
        `in_corpus=False`, leave it out of the taxonomy, and record an `_HONEST_GAPS` note.
        The registry has no third state: a `live=False` class is listed with the retired ones
        (`RETIRED_DOC_TYPES`, `RETIRED_DOC_CLASS_KEYS`) until it goes live, so the classifier
        treats it as not live. The per-subtype schema registry (step 2) covers live classes only:
        `extraction_schema()` accepts `MAILROOM_DOC_TYPES`, which is `doc_classes.LIVE_DOC_TYPES`,
        so a scored-later type gets its schemas when you flip `live=True`.
- [ ] **Swap instead of add?** If a type is replacing another, do this checklist for the new
      one and the **Retire** section for the old one in the same release.

## 1. Dojo: the registry (`llm_dojo_scoring/`)

One table is edited by hand for the class and its fields: **`schemas/doc_classes.py`**. Append a
`DocClass` to `DOC_CLASSES`:

```python
DocClass(
    key="<type>",
    live=True,                      # False for a scored-later type (step 0, option B)
    specialist="<agent>",
    in_corpus=True,                 # the pinned dataset has ground-truth rows for it
    fields={"<field>": "<scorer type>", ...},   # in scoring order
)
```

Everything below derives from that entry, so it needs no edit (`tests/test_doc_classes.py`
fails when one of these tables disagrees with the registry): `scoring.suites`
`DEFAULT_FIELD_TYPES` / `SPECIALIST_DOC_TYPES` / `DOC_TYPE_ALIASES`, `schemas.corpus`
`CORPUS_EXTRACTION_FIELDS` / `CORPUS_DOC_TYPES` / `CORPUS_ABSENT_DOC_TYPES`,
`schemas.extraction_schemas.MAILROOM_DOC_TYPES`, `pipeline.mailroom` `LIVE_*` / `RETIRED_*`,
`config` `*_DOC_CLASS_KEYS`, `metrics.doc_bundles.DOC_TYPES`, `metrics.registry` specialist
rosters, `pipeline.archive.LIVE_ARCHIVE_DOC_TYPES`, the promotion gates, extraction scope and
adherence field sets, the v10 row configs and `scripts/build_extraction_status.py:FIVE`. A new
class is appended last in every table that keeps a legacy order.

Still edited by hand (they carry content the registry does not):

| Where | What to add |
|---|---|
| `schemas/cuad_schema.py` / `schemas/maud_schema.py` | **only for a new field on `contract` or `merger_agreement`**: its prompt descriptor (empty value and description). The import fails naming the field until it exists |
| `schemas/corpus.py` | `DOC_TYPE_SUBCLASSES[<type>]`, the raw surfaces in `_RAW_SUBCLASS_SURFACES[<type>]` (`CORPUS_SUBCLASS_SURFACES` adds the canonical keys itself, for the v10 `subclass` column), and the per-type tables lower in the file that every class has an entry in |
| `scoring/suites.py` | `_AGENT_EXTRAS[<agent>]` for class extras; `_HONEST_GAPS[<agent>]` for any known gap |
| `metrics/profiles.py` | a `DEFAULT_PROFILES` entry: `_p("<agent>", "<Title> Extraction", ("extract",), "extraction", doc_bundle="<type>")`. `DEFAULT_SUITES` is built from this, so `get_suite("<type>")` works once it exists |
| `metrics/doc_bundles.py` | `DOC_TYPE_BUNDLES[<type>]` (headline metrics) |
| `metrics/bundles.py` | the `<agent>` entry in the extraction bundle |
| `schemas/intents.py` | `INTENT_LABELS[<type>]` and `INTENT_DESCRIPTIONS[<type>]` |
| `schemas/scored_enums.py` | only if a field is a closed enum |
| `prompts/catalog.yaml` + `prompts/templates/` | `<agent>.docclass.md`, `<agent>.production.md`, `<agent>.production_prompts.md`; add `<type>` to the shared templates that list every class (`sorter_reviewer`, `judge*`, `arbiter`, `boss`) |

## 2. Dojo: which fields are scored (from the dataset)

Whether a field counts toward the score is not set in the registry: it comes from the labels the
pinned dataset actually populates, frozen in `schemas/data/extraction_status.json`.

- [ ] When the dataset has (new) labels for the class, re-freeze the status from the pinned Hub
      revision (pyarrow is not a Dojo dependency):
      `uv run --extra dev --with pyarrow python scripts/build_extraction_status.py
      --from-hub --commit <40-hex sha> --revision <tag>`. It downloads the
      mailroom-dataset `ground_truth` parquet of that commit and writes per-subtype field status,
      with the revision recorded, for every live class in the registry. Do not
      hand-edit the JSON; add `--check` to report drift.
- [ ] Regenerate the coverage page: `uv run python scripts/render_gt_coverage.py --write`
      (`--check` is the CI gate). Commit it with the JSON.
- [ ] Subtype-only fields and salient guidance go in `_build()` in
      `schemas/extraction_schemas.py` (see the CMS `cms_source_table` and the corporate-record
      subclass entities for examples).
- [ ] Check: `extraction_schema("<type>")` and `extraction_schema("<type>", "<subtype>")`
      both build, `scoreable_fields("<type>")` lists what you expect, and
      `registry_violations() == []`.
- [ ] If a score moves (a field became scored, a type changed), run
      `uv run --locked python scripts/freeze_goldens.py --check`; when the change is intended,
      `--write --reason "…"`, then add a `CHANGELOG.md` entry and a before/after table.

## 3. Dojo: tests, release

- [ ] `tests/test_doc_classes.py`, `tests/test_extraction_schemas.py` (`registry_violations`),
      `test_doc_bundles`, the suite and profile tests: add `<type>` wherever they parametrise over
      classes. `test_table_equals_pre_refactor_snapshot` pins the tables as they were before the
      registry existed (it proved the registry refactor changed nothing); the first intended
      registry edit makes it fail, and that is the cue to delete that test and
      `tests/fixtures/doc_class_tables_before.json`, not to edit the fixture.
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

- [ ] Dojo: set `live=False` (and `in_corpus=False` once the dataset has no rows for it) on its
      `DocClass`. That moves it from the `LIVE_*` tables to the matching `RETIRED_*` ones and drops
      it from `MAILROOM_DOC_TYPES` and the status script's class list. Add an `_HONEST_GAPS` note
      saying when and why (see `court_opinions_specialist`). Then rebuild
      `extraction_status.json` and re-render `GT_COVERAGE.md` (step 2), so the status file and
      `MAILROOM_DOC_TYPES` still agree.
- [ ] llm-mailroom: remove the `taxonomy.yaml` class and the graph dispatch entry, so the
      sorter's label set no longer offers it and those documents fall to `unknown` and human
      review. Check that nothing still routes the old label (a sorter prompt or cached
      prediction that emits it must be rejected, not dispatched). Keep the agent module only
      if historical replays need it.
- [ ] llm-mailroom: remove the class from `LIVE_DOC_TYPES` in `src/tests/test_dojo_parity.py`
      (it indexes the taxonomy by that tuple) and from `HUB_CLASSES` in
      `src/pipeline/hf_corpora.py`, so a pilot over historical rows does not score the
      sorter's correct `unknown` as a class error; adjust the checks that count classes.
- [ ] Sandbox: re-vendor, and remove the class from the eval maps and `components.yaml`.

## Done when

- [ ] `registry_violations() == []` in Dojo, `test_dojo_parity.py` passes in llm-mailroom,
      and `test_vendor_drift.py` passes in the sandbox.
- [ ] Live type: `get_suite("<type>")`, `extraction_schema("<type>", <each subtype>)` and the
      specialist all resolve from the same key.
- [ ] Scored-later type: `get_suite("<type>")` resolves and scores; the schema registry and
      the specialist are checked when the type goes live (Option A).
- [ ] Every honest gap for the class names mailroom-dataset row counts, not guesses.
