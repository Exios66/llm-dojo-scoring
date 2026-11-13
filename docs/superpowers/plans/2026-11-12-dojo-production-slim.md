# Dojo Production Slim-Down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (the repo's `.claude/rules/orchestration.md` already mandates it: `implementer` = Sonnet, `runner` = Haiku, never an Opus subagent). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One open PR on `Exios66/llm-dojo-scoring` (branch `claude/vibrant-sagan-fltg8i`) that (1) records the evidence-backed diagnosis of CI, consumer usage and ground-truth coverage, (2) makes one dataset-derived registry the source for document classes, extraction fields and field types, (3) deletes code that neither `llm-mailroom` nor `local-mailroom-sandbox` reaches, and (4) fixes the still-valid open issues that belong to this work.

**Architecture:** A new leaf module `schemas/doc_classes.py` becomes the only hand-edited table of classes and fields; every other class/field table derives from it, and field *scoreability* derives from `schemas/data/extraction_status.json`, regenerated from the pinned live dataset. Deletion is decided mechanically: a script computes the import closure of everything the two consumers (and the open audit-row PR stack) import; modules outside the closure and not on a named hold list are removed. Root `__init__` becomes lazy (PEP 562), so trimmed names stay reachable and consumer imports keep working.

**Tech Stack:** Python 3.11, uv (`uv.lock` generated), pytest, ruff 0.17.3, CircleCI.

**Spec:** this file (no separate spec). At execution, copy it to `docs/superpowers/plans/2026-11-12-dojo-production-slim.md` in the PR. It implements Dojo epic **#66** ("RETIRE DEPRECATED PACKAGES") sub-issues #78, #79, #80, #84 and prepares #74–#77.

## Context (what the research found)

- **CI is green today** on the latest heads of all three repos (Dojo `ci/circleci: test`, mailroom `test-1`, sandbox `lint` + `test`). The problems are structural, not red builds:
  - Dojo: five test modules silently skip in CI (`pydantic` / `jsonschema` are not in the `dev` extra); no skip report; a dead `if [ -f … ]` guard; a publish test that can wait out a 60 s network timeout; `uv lock --check`, coverage-status and consumer-surface checks never run in CI; docs disagree with CI commands.
  - mailroom (documented, not changed here): no lockfile; the daily Dojo auto-bump PR is red by design because `bump_dojo_scoring.py` does not refresh `vendor/`; the mock experiment gate cannot see extraction regressions; no parallelism, full suite >10 min.
  - sandbox (documented, not changed here): `test_vendor_drift.py` always skips in CI; lint tools unpinned behind a static cache key; uncached apt shellcheck.
- **Dojo size:** 33,136 package lines in 81 modules, 303 root exports. 204 of 272 non-module exports (75%) have no consumer; 45 modules (13,952 lines) have no direct consumer reference. Both consumers import almost everything through legacy flat paths (`_layout.LEGACY_MODULES`), so aliases for kept modules must stay.
- **Editing cost today:** adding one field touches ~11 places; a class list exists in ~10 files, a per-class field list in ~8 (`suites.DEFAULT_FIELD_TYPES`, `corpus.CORPUS_EXTRACTION_FIELDS`, `cuad_schema`, `maud_schema`, `corporate_record_schema`, fixtures, docs), with hard-coded counts (`== 17`, `!= 21`).
- **Live dataset** (`Lucius-Morningstar/mailroom-dataset`, head `ccd040f6a1b6b414bdefd161cdc622b68f6dacf8` = v9.3, the commit mailroom pins; 3,302 rows), measured this session from the `ground_truth` config:

  | Class | Rows | Fields with populated GT | Live schema fields with no GT |
  |:--|--:|:--|:--|
  | contract | 600 | `cuad_clause_labels` on 509 (91 pending) → 7 derived fields + `cuad_family` | 9 of 17 |
  | merger_agreement | 152 | `maud_clause_labels` on 152 → `maud_clauses`, `merger_consideration` | 16 of 21 |
  | corporate_record | 450 | `intent`, `keywords`, `subject_matter`, `record_type` 450; `entity_name` 412 | `effective_date`, `jurisdiction`, `signatories`, (`filing_number`) |
  | correspondence | 1,000 | `intent`, `keywords`, `subject_matter` 1,000 (+ label tasks `content_topic`, `sentiment_label`) | 7 of 11 |
  | insurance_claim | 1,100 | 14 fields ≥99%; `adjuster` 150; `denial_reasons` 36 | `claim_checklist` |

  The three repos pin three different dataset revisions (sandbox v9.1, Dojo status file v9.2.1, mailroom v9.3).
- **Owner decisions already taken:** PR = analysis + first cut in the Dojo only; delete unused now (consumer-used names keep working, legacy paths included); score every field the dataset populates, with no label-quality tiers.

## Open-issue ledger (checked 2026-11-12)

| Issue | Still valid? | Disposition in this PR |
|:--|:--|:--|
| Dojo #66 epic, #80 slim root `__init__`, #84 consumer-surface audit | Yes | Tasks 1, 5 |
| Dojo #79 prune legacy | Partly: `LEGACY_FULL_EXTRACTION_FIELD_TYPES`, `[jellyfish]` alias, `phoenix_sync` valid; registry "legacy" metrics `run_aborted` / `stage_completed` are in mailroom's 59 `SCORE_CONFIGS`, so they **stay**; no tracked `egg-info`/`__pycache__` (stale item) | Task 4 |
| Dojo #78 dedupe `chained_composite` | Yes (`scoring/tasks.py:485` and `pipeline/sandbox_composite.py:5`) | Task 4 |
| Dojo #74–#77 `mixed_source` moves (LegalBench, ContractEval, retired classes) | Yes, but consumers still call `legalbench_scoring` and `get_suite("court_opinion")` | Not moved; phase 2 in the roadmap doc (needs consumer PRs) |
| Dojo #67 golden freeze, #68 tiers | #67 delivered by `freeze_goldens.py`; note for close-out | Roadmap doc |
| Dojo #133 `_parse_money("1.2M USD")` → `None` | Yes (`field_scoring.py:510` suffix loop precedes `:515` tail strip) | Task 7 |
| Dojo #132 carrier `cms_source_table` caps a perfect oracle at 0.9412 | Reproduce first (Task 7 step 1); fix if red | Task 7 |
| Dojo #94, #95, #52 (GT gaps: correspondence 3/11, merger MAUD-only, corporate entities) | Yes, confirmed by the live counts above | Made visible and self-updating by Tasks 2–3; closing needs labels, not code |
| Dojo #96 grammar hints for scored enums | Yes | Roadmap (the registry in Task 3 is its prerequisite) |
| Dojo #129 re-vendor prompts | Looks done by merged PR #126 | Flag as stale in roadmap doc |
| Dojo #120 audit row, mailroom #150–#156, PRs #226–#229 | Active | `pipeline.archive`, `doc_scorers`, `score_document` are on the hold list |
| Dojo `docs/plans/BUG_SWEEP.md`: `audit_consumer_surface.py` pins developer paths and exits 2 | Yes (fixture `generated_from` holds macOS paths) | Task 1 (`--only`, record repo codes not local paths) |
| BUG_SWEEP: "Repo-owned CI entry point" (`scripts/ci.py`) and "Suite bloat" (profile, demote pinning-only tests) | Yes | Task 6 |
| BUG_SWEEP: insurance `claim_checklist` in the live map with no GT row (headline always `partial`) | Yes (0 of 1,100 rows on the live dataset) | Reported as `pending_annotation` by Tasks 2–3; dropping it from the map must move in step with llm-mailroom → roadmap |
| BUG_SWEEP: intents never seen in GT (`loss_report`, `other` for insurance) | Yes | Task 2 adds per-vocabulary value counts to the coverage page, listing values with zero GT rows |
| BUG_SWEEP: correspondence audit known gaps (44 templated rows), #94 steps 2–5 | Yes | Labelling work; `correspondence_gt_audit` stays (hold list); roadmap |
| BUG_SWEEP: CMS detection still key-sniffs `cms_source_table` | Yes, adjacent to #132 | Task 7 fixes only the #132 symptom; explicit-provenance detection → roadmap |
| mailroom #192 (taxonomy never wired into scoring) | **Fixed in code**: `build_graph.py:20`, `run_pilot.py:76`, `run_hf_pilot.py:97` import `scoring_wiring`; issue still open | Roadmap: close |
| mailroom #195 yearless-date scoring | Dojo part landed in PR #135, and mailroom's pin `f95c318` includes it | Roadmap: close after confirming the loader part |
| mailroom #198 release chain | `pyproject` now says 0.9.3 (the reported gap); changelog part not re-checked | Roadmap: verify with `release.py check`, then close |
| mailroom #187 "13 nodes" docs | **Still valid** (`README.md:11,103,127,276`) | Roadmap: mailroom docs follow-up |
| mailroom #196 unpinned corpora | Partly: a live-or-loud warning exists; pins not re-checked | Roadmap |
| mailroom #191, #193, #194, #197, #199–#201 | Linked PR #202 merged; issues still open; not re-verified one by one | Task 8 step 2 verifies each against `main` and lists "close" or "still valid" |
| mailroom #174 (v10 schemas/loaders), #183 (re-score insurance) | Yes | `schemas/v10_rows` on hold list; roadmap |
| mailroom #198 release chain, #187 docs, no lockfile, auto-bump red by design, posthoc `urgency="high"` outside the closed vocabulary | Yes (last three have no issue yet) | Roadmap doc as mailroom follow-ups |
| sandbox #216 corporate confidence prompt/schema mismatch | Partly: the production and simplified prompts now forbid `confidence`; `corporate_records_specialist_condensed_v1.txt:23` still asks for it | Roadmap: sandbox follow-up |
| sandbox #221 / Dojo #92 remote Dojo, #269 vendor audit | Yes | Roadmap doc; sandbox vendor refresh follows the Dojo merge |

No issue is closed or commented on by this work; the PR body says `Fixes #133` (and `#132` if reproduced) and `Refs` the rest.

## Global Constraints

- Work only in `/home/user/llm-dojo-scoring` on `claude/vibrant-sagan-fltg8i`; never force-push; never edit `uv.lock` by hand (`uv lock`); never hand-edit versions (no `release.py cut` without the owner's go-ahead; propose 0.29.0 in the PR).
- `uv run --locked python scripts/freeze_goldens.py --check` must exit 0 after every task except Task 7, the only task allowed to change a score (`--write --reason`, before/after table, `CHANGELOG.md`, `score_changelog`).
- Every name in `tests/fixtures/consumer_surface.json` and `tests/fixtures/contract_surface.json` keeps importing from the same path, including legacy flat paths.
- Every function, tests included, needs a docstring (`tests/test_docstring_coverage.py`). Tests load scripts with `tests/conftest.py:load_script(name)`.
- Gates after every task: `uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples`; `uv run --locked --extra dev pytest tests -q`; the golden check. No type checker exists; never claim one.
- Subagents never push, comment or open PRs. No `dojo-sync`, no hosted-service writes.

## Review Focus

1. A consumer imports a legacy flat path of a module this PR keeps but whose alias was dropped by mistake → must still import (test in Task 4).
2. An unscanned consumer (eval-environment was never scanned) uses a root name removed from `__all__` → must still resolve lazily, or fail with a message naming the changelog (test in Task 5).
3. A new dataset revision adds or drops a GT field → `extraction_schema()` status and the coverage doc must change with no code edit (test in Task 2).
4. `import llm_dojo_scoring` with only core deps installed → must not import `pandas`, `matplotlib` or `openpyxl` (subprocess test in Task 5).
5. A registry edit that forgets a derived table → the suite must fail loudly, not score with a stale map (identity tests in Task 3).

---

### Task 1: Consumer closure tool and keep/delete/hold decision

**Files:**
- Create: `scripts/consumer_closure.py`, `tests/test_consumer_closure.py`, `docs/analysis/data/consumer_closure.json`
- Modify: `scripts/audit_consumer_surface.py` (add `--only CODES`)

**Interfaces:**
- Produces: `consumer_closure.py --mailroom PATH --sandbox PATH [--extra-ref GITREF…] --write|--check`; JSON `{"roots": {...}, "modules": {"<dotted>": {"decision": "keep"|"delete"|"hold", "reason": str, "lines": int}}}`. Functions `import_graph(package_dir: Path) -> dict[str, set[str]]`, `closure(roots: set[str], graph: dict[str, set[str]]) -> set[str]`.
- Hold list (constant `HOLD` with the issue number as reason): `pipeline.archive`, `scoring.doc_scorers.*`, `scoring.extraction_scope`, `pipeline.sandbox_schema_adherence` (#120, mailroom #226–#229); `schemas.v10_rows` (mailroom #174); `schemas.correspondence_gt_audit`, `schemas.corporate_record_relabel` (#94, #52); `integrations.update_awareness` (release tooling).

- [ ] Step 1: Write failing tests on a temp fake package: `closure` follows function-level and relative imports; a module imported only by `__init__` is not kept; `HOLD` entries get `decision == "hold"`; `--check` exits 1 on drift.
- [ ] Step 2: Run `uv run --extra dev pytest tests/test_consumer_closure.py -q` → FAIL (script missing).
- [ ] Step 3: Implement. Roots = fixture names (all scanned consumers) ∪ `contract_surface.json` ∪ a fresh AST scan of `/home/user/llm-mailroom` (src, tools, experiments), `/home/user/local-mailroom-sandbox` (src, scripts, tests, deploy, api-evals **and** `vendor/llm-mailroom/src`) ∪ the mailroom branches `stack/01-audit-storage`, `stack/02-diagnostics-workbench`, `stack/03-audit-live-row`, `claude/howdy-n8vcc1` (read with `git show`/`git archive` after `git fetch`). Reuse the AST scanner in `audit_consumer_surface.py`. Dynamic dispatch counts as a root: every key consumers pass to `get_suite` / `score_task` / `suite_for_doc_type` keeps the modules those dispatch to.
- [ ] Step 4: `--only MAIL,SBX` on `audit_consumer_surface.py` rescans just those codes and leaves other consumers' recorded entries untouched (exit 2 only when a requested checkout is missing), and `generated_from` records the repo code and commit, never a local filesystem path. Tick the matching `docs/plans/BUG_SWEEP.md` boxes in the tasks that resolve them. Run it with `--write`; commit the refreshed fixture.
- [ ] Step 5: Run the tool with `--write`; review the JSON by hand against the expected delete set in Task 4; tests PASS; commit.

### Task 2: Ground-truth status from the pinned live dataset

**Files:**
- Modify: `scripts/build_extraction_status.py`, `llm_dojo_scoring/schemas/data/extraction_status.json`, `llm_dojo_scoring/schemas/corpus.py` (docstring pin), `.circleci/config.yml`
- Create: `scripts/render_gt_coverage.py`, `docs/schemas/GT_COVERAGE.md` (generated), `tests/test_gt_coverage_doc.py`

**Interfaces:**
- Produces: `build_extraction_status.py --from-hub --commit <40-hex> --revision <tag>` (downloads the two `ground_truth` shards from `/resolve/<commit>/…` with `urllib`, then the existing `build()`); `render_gt_coverage.py --write|--check` (network-free, reads only the JSON); `render(status: Mapping) -> str`.

- [ ] Step 1: Failing tests: `render` on a two-field synthetic status lists each field once with its status and populated count; `--check` exits 1 when the doc differs; a synthetic status where `adjuster` goes from 150 to 1,100 populated flips `extraction_schema("insurance_claim").fields["adjuster"].status` from `partial` to `scored` with no code change (Review Focus 3; inject via the module's `_status_data` cache).
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement `--from-hub`; run `uv run --extra dev --with pyarrow python scripts/build_extraction_status.py --from-hub --commit ccd040f6a1b6b414bdefd161cdc622b68f6dacf8 --revision v9.3`. Compare the per-class counts with the table in Context; any difference is a finding for the analysis doc.
- [ ] Step 3b: Extend `build()` with `"vocabulary"`: for each closed-vocabulary field (`intent`, `claim_type`, `coverage_determination`, `record_type`, `content_topic`, `sentiment_label`) the count of GT rows per value; test that a vocabulary value with zero rows (insurance `loss_report`) is listed under "never seen in ground truth" in the rendered page.
- [ ] Step 4: Implement `render_gt_coverage.py`; write the doc; add a CI step `uv run --frozen --no-sync python scripts/render_gt_coverage.py --check`.
- [ ] Step 5: Gates (golden check must exit 0: the status file does not feed scores; if it does not exit 0, stop and report); commit.

### Task 3: One registry for classes, fields and field types

**Files:**
- Create: `llm_dojo_scoring/schemas/doc_classes.py`, `tests/test_doc_classes.py`, `tests/fixtures/doc_class_tables_before.json` (snapshot of today's tables, captured before any edit)
- Modify (derive, do not restate): `scoring/suites.py` (`DEFAULT_FIELD_TYPES`, `SPECIALIST_DOC_TYPES`), `schemas/corpus.py` (`CORPUS_EXTRACTION_FIELDS`, `CORPUS_DOC_TYPES`), `schemas/extraction_schemas.py` (`MAILROOM_DOC_TYPES`, `_live_types`), `pipeline/mailroom.py` (`LIVE_DOC_TYPES`, `RETIRED_DOC_TYPES`), `config.py` (`*DOC_CLASS_KEYS`), `metrics/doc_bundles.py` (`DOC_TYPES`), `schemas/cuad_schema.py`, `schemas/maud_schema.py` (replace the literal 17 / 21 with `len(field_types(...))`), `schemas/corporate_record_schema.py`, `schemas/schema_contract.py`, `scripts/build_extraction_status.py` (`FIVE`), `docs/guides/ADDING_A_DOCUMENT_TYPE.md`, `docs/schemas/EXTRACTION_SCHEMAS.md` (stale "v0.20.0", "58 field slots")

**Interfaces:**
- Produces, in `schemas/doc_classes.py` (stdlib only, imports nothing from the package):
  `@dataclass(frozen=True) class DocClass: key: str; live: bool; specialist: str; fields: Mapping[str, str]`;
  `DOC_CLASSES: Mapping[str, DocClass]`; `LIVE_DOC_TYPES: tuple[str, ...]`; `RETIRED_DOC_TYPES: tuple[str, ...]`;
  `field_types(doc_type: str) -> dict[str, str]`; `field_names(doc_type: str) -> tuple[str, ...]`.
- Produces, in `schemas/extraction_schemas.py`: `scoreable_fields(doc_type: str, subtype: str | None = None) -> tuple[str, ...]` = fields whose status is in `SCORED_STATUSES` ("score everything the dataset populates"; no quality tiers).

- [ ] Step 1: Capture the snapshot fixture from the current tables (a throwaway script; commit only the JSON).
- [ ] Step 2: Failing tests: every derived table equals the snapshot value-for-value and in order; `suites.DEFAULT_FIELD_TYPES[c] == doc_classes.field_types(c)` for all eight classes; `mailroom.LIVE_DOC_TYPES == doc_classes.LIVE_DOC_TYPES`; `scoreable_fields("correspondence") == ("intent", "subject_matter", "keywords")` as a set; `scoreable_fields("insurance_claim")` contains `adjuster` and excludes `claim_checklist`; monkeypatching one extra field into `DOC_CLASSES` and rebuilding via the public accessors surfaces it in `field_types` (Review Focus 5); no module under `schemas/` imports `scoring` (AST check).
- [ ] Step 3: Run → FAIL.
- [ ] Step 4: Implement the registry with exactly today's values, then switch each table to derive from it. Where `corpus.CORPUS_EXTRACTION_FIELDS` differs from `DEFAULT_FIELD_TYPES` today, keep the difference as a named, commented override in `corpus.py` and pin it in the test; do not "fix" it here.
- [ ] Step 5: Rewrite the Dojo section of `ADDING_A_DOCUMENT_TYPE.md` to the new path (edit `doc_classes.py` → rerun the status build when GT exists → goldens → changelog); gates incl. `tests/test_consumer_compat.py`, `tests/test_public_api_doc.py`, golden check exit 0; commit.

### Task 4: Delete what no consumer reaches

**Files (expected set; the closure JSON from Task 1 is the authority, and anything it marks `keep` or `hold` stays):**
- Delete: `llm_dojo_scoring/cli.py`; `analysis/{export,io,report,interpret,visualize,error_analysis,grid,failure_modes}.py`; `integrations/{langfuse_sync,phoenix_sync}.py`; `scoring/rescore.py`; `pipeline/{sandbox_agent_scoring,sandbox_composite}.py`; their tests, fixtures and `_layout.LEGACY_MODULES` entries
- Modify: `pyproject.toml` (remove entry points `dojo-analyze`, `dojo-export`, `dojo-rescore`, `dojo-sync`; remove the `[jellyfish]` alias extra and `arize-phoenix`; move `pandas`, `openpyxl`, `matplotlib` out of core only if `grep` finds no remaining import), `uv.lock` (via `uv lock`), `scoring/suites.py` (drop `LEGACY_FULL_EXTRACTION_FIELD_TYPES`), `scoring/tasks.py` (single `chained_composite`; keep the signature the root exports today), `CHANGELOG.md` (`[Unreleased]` → Removed, with a one-line replacement note per item), `README.md`, `AGENTS.md`, `CLAUDE.md`, `llm_dojo_scoring/README.md`, `docs/guides/PUBLIC_API.md`
- Test: `tests/test_legacy_aliases_kept.py` (new)

- [ ] Step 1: Failing test: for every module path in `consumer_surface.json` `modules` and every hold-list module, `importlib.import_module("llm_dojo_scoring.<flat>")` succeeds and each recorded attribute exists (Review Focus 1); `LEGACY_MODULES` has no entry pointing at a missing file.
- [ ] Step 2: Delete per the closure JSON, one area per commit (CLIs + analysis tooling; integrations; rescore/sandbox leftovers; legacy constants + extras). After each commit: full gates, golden check exit 0.
- [ ] Step 3: `uv lock`, `uv lock --check`, `uv sync --frozen --extra dev`, suite again.
- [ ] Step 4: Update docs so every command, path and count still named is true (`dojo-version` is the only CLI left).
- [ ] Step 5: Record `wc -l` before/after per subpackage for the PR; commit.

### Task 5: Lazy root `__init__` and tiered `__all__` (#80)

**Files:**
- Modify: `llm_dojo_scoring/__init__.py`, `tests/test_import_cost.py`, `docs/guides/PUBLIC_API.md`
- Test: `tests/test_root_surface.py` (new)

**Interfaces:**
- Produces: `__all__` = root names in `consumer_surface.json` ∪ `contract_surface.json` ∪ kept submodule names; module-level `__getattr__(name)` backed by `_LAZY: dict[str, str]` (name → defining module) for every other previously exported name that still exists; names whose module was deleted raise `AttributeError("… removed in the production slim-down; see CHANGELOG.md")`.

- [ ] Step 1: Failing tests: every fixture root name is in `__all__` and resolves; a previously exported, unconsumed, still-existing name (use `wilson_ci`) resolves through `__getattr__` and is not in `__all__`; a removed name raises the message above (Review Focus 2); in a subprocess, `import llm_dojo_scoring` leaves `pandas`, `matplotlib`, `openpyxl` out of `sys.modules` (Review Focus 4); `import llm_dojo_scoring.field_scoring` still returns the same object as `llm_dojo_scoring.scoring.field_scoring`.
- [ ] Step 2: Run → FAIL. Step 3: implement. Step 4: gates + `tests/test_consumer_compat.py`, `tests/test_public_api_doc.py`. Step 5: commit.

### Task 6: CI and test-suite repairs (Dojo)

**Files:** `.circleci/config.yml`, `pyproject.toml` (`dev` += `jsonschema`, `pydantic`), `uv.lock`, `tests/test_release_tools.py`, `tests/README.md`, `CLAUDE.md`, `AGENTS.md`

- [ ] Step 1: Add the two packages to `dev`, `uv lock`; run the suite with `-rs` and confirm `test_schema_contract.py`, `test_maud_schema.py`, `test_corporate_record_schema.py`, `test_cuad_schema.py` no longer skip; fix any test that was hidden-red.
- [ ] Step 2: CI: add `-rs` to pytest; add `uv lock --check`; drop the dead `if [ -f scripts/freeze_goldens.py ]` guard and its stale comment.
- [ ] Step 3: `test_cli_publish_dry_run_json`: catch `subprocess.TimeoutExpired` and skip with the reason; lower the timeout to 20 s.
- [ ] Step 3b (BUG_SWEEP "repo-owned CI entry point"): create `scripts/ci.py` with `--tier smoke|full` and `--json PATH`; `full` runs, in order, ruff, `uv lock --check`, pytest, the golden check, `render_gt_coverage.py --check`; `smoke` runs ruff plus `tests/test_consumer_compat.py tests/test_root_surface.py tests/test_doc_classes.py tests/test_golden_scores.py`; the JSON lists each step's name, exit code and seconds; exit code is the first failure. Test `tests/test_ci_script.py` with stubbed step commands (a failing step stops the run and is reported). CircleCI calls `scripts/ci.py --tier full`.
- [ ] Step 3c (BUG_SWEEP "suite bloat"): run `pytest tests -q --durations=25`, put the table in the analysis doc; change no test tiers beyond the smoke list above.
- [ ] Step 4: Make docs match CI (`tests/README.md` "fail" → "skipped" for the tag test; one documented test command; remove `--python 3.12` hints). Gates; commit.

### Task 7: Scoring bug fixes (#133, #132) — the only score-changing task

**Files:** `llm_dojo_scoring/scoring/field_scoring.py`, `tests/test_field_scoring.py` (or the file that owns `parse_money`), `metrics/score_changelog.py`, `CHANGELOG.md`, goldens if they move

- [ ] Step 1: Failing tests: `parse_money("1.2M USD") == 1_200_000.0`, `parse_money("USD 1.2M") == 1_200_000.0`, `parse_money("$1.2M") == 1_200_000.0`, `parse_money("3 dollars") ` unchanged from today; and the #132 oracle: `get_suite("insurance_claims_specialist").score(expected=row, predicted=row, doc_subclass="carrier")` with a synthetic 16-field carrier row has `overall_extraction_score == 1.0`.
- [ ] Step 2: Run. #133 must be red. If the #132 test is already green on `main`, keep it as a regression test, change nothing, and report the issue as not reproduced.
- [ ] Step 3: #133: strip the currency-word tail (and a leading currency word) before the K/M/B loop. #132: when the row does not label `cms_source_table`, treat it as derived from `doc_subclass` exactly as the corporate path treats `record_type` (never an expected-but-missing event).
- [ ] Step 4: `freeze_goldens.py --check`; if it reports drift, paste the diff, then `--write --reason "…#133/#132"`, add the before/after table, `CHANGELOG.md` and `score_changelog` entries. Commit.

### Task 8: Consumer verification, analysis doc, PR

**Files:** Create `docs/analysis/2026-11-production-surface.md`; copy this plan to `docs/superpowers/plans/2026-11-12-dojo-production-slim.md`

- [ ] Step 1 (no pushes to consumers): mailroom — `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` in `/home/user/llm-mailroom`, then `.venv/bin/pip install --no-deps -e /home/user/llm-dojo-scoring`, run the test files that reference `llm_dojo_scoring`; expected failures are only the pin-bound tests (`test_dojo_source.py`, `test_dojo_v012.py`, pin checks in `test_docs_truth.py`): name each. sandbox — venv per its `CLAUDE.md`, `DOJO_SRC=/home/user/llm-dojo-scoring`, run `tests/test_scoring_outputs_golden.py tests/test_eval.py tests/test_serving_parity.py tests/test_scoring_ownership.py tests/test_prompt_versions_dojo.py tests/test_prompt_catalog.py -n 0 --no-cov`. Any non-pin failure is a Dojo regression: fix in the Dojo, not in the consumer.
- [ ] Step 2: Write the analysis doc: CI diagnosis for all three repos; consumer usage matrix; keep/delete/hold table with line counts before/after; GT coverage and the schema-vs-GT gap per class; the issue ledger above with verified status; phase 2 roadmap (#74–#77 `mixed_source`, metric registry/profiles/bundles consolidation onto the registry, retired classes, #96, v10, one shared dataset pin across the three repos, mailroom bump-script vendor refresh + lockfile, sandbox CI skips). Every number comes from a command run in this session.
- [ ] Step 3: Orchestration: three adversarial-review rounds (public API + scoring change = tier 3), each a new `adversarial-reviewer`; fix BLOCKING/MAJOR; orchestrator reads the full diff and re-runs every gate on the final commit.
- [ ] Step 4: `pr-flow.md`: clean tree, `git fetch origin main`, gates, self-review checklist, fresh `pre-pr-reviewer`, then `git push -u origin claude/vibrant-sagan-fltg8i`, open a **draft** PR from `.github/pull_request_template.md`, subscribe to PR activity, mark ready once `ci/circleci: test` is green on the pushed commit.
- [ ] Step 5: PR "Cross-repo impact": consumers need a coordinated bump after merge (`/dojo-bump` in mailroom incl. vendor refresh; `/vendor-sync` in the sandbox, which can then drop `pandas`/`openpyxl` from its base deps). Both are user-invoked and not part of this PR.

## Verification (end to end)

```bash
git status --short                                   # empty
uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples
uv run --locked --extra dev pytest tests -q -rs      # summary line + named skips
uv run --locked python scripts/freeze_goldens.py --check
uv lock --check
uv run --locked python scripts/render_gt_coverage.py --check
uv run --locked python scripts/consumer_closure.py --mailroom /home/user/llm-mailroom --sandbox /home/user/local-mailroom-sandbox --check
uv run --locked python scripts/audit_consumer_surface.py --only MAIL,SBX --check
python scripts/release.py check                      # quote WARN lines
python -c "import llm_dojo_scoring, sys; print([m for m in ('pandas','matplotlib','openpyxl') if m in sys.modules])"   # []
```

Plus the consumer runs in Task 8 step 1, and the package line count before and after.

## Not in this PR (stated so nobody assumes otherwise)

- No changes pushed to `llm-mailroom` or `local-mailroom-sandbox`; no version cut or tag; no issue closed.
- Retired classes, LegalBench/ContractEval, the 161-metric registry, profiles and bundles are untouched: consumers reach them today.
- Pipeline schema fields without ground truth stay in the schema as `pending_annotation` (reported, never scored); removing them from the mailroom's Pydantic models is a mailroom decision.
