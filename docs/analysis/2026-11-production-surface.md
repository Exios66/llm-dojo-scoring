# Production surface, CI and ground-truth coverage (November 2026)

Analysis behind the production slim-down (Dojo epic #66, PR #136). Plan:
[`docs/superpowers/plans/2026-11-12-dojo-production-slim.md`](../superpowers/plans/2026-11-12-dojo-production-slim.md).

**How to read the evidence.** Every figure is tagged.

| Tag | Meaning |
|:---|:---|
| **[M]** | Measured in this session by a command listed in [Reproduce](#reproduce). |
| **[S]** | Reported by the orchestrator from a session that ran against a consumer checkout; quoted verbatim where marked. |
| **[P]** | Taken from the plan's "Context" or "Open-issue ledger" (research of 2026-11-12). **Not re-verified here.** |

Measured at branch head `fb4abe2` (base `origin/main` = `f95c318`). The commit that adds this page touches only `docs/`.

## 1. Summary

| Area | Before (`origin/main`) | After (branch) | Tag |
|:---|:---|:---|:---|
| Package `.py` lines / modules (non-`__init__`) | 33,136 / 81 | 28,483 / 69 | [M] |
| Root `__all__` | 303 names, eager | 284 names, lazy (PEP 562) | [M] |
| Package modules loaded by `import llm_dojo_scoring` | 77 | 2 | [M] |
| Heavy deps loaded by that import | `pandas`, `openpyxl` | none | [M] |
| CLIs | 5 | 1 (`dojo-version`) | [M] (`pyproject.toml` diff) |
| Hand-edited tables of document classes and fields | ~10 class lists, ~8 field maps | 1 (`schemas/doc_classes.py`) | [P] before, [M] after (`tests/test_doc_classes.py`) |
| Tests collected / skipped in CI | 3,625 / 26 (`test_release_tools.py` not run on the export) | 3,712 / 2 | [M] |
| Perfect `insurance_claim` carrier oracle (#132) | 0.9412 | 1.0 | [M] |
| `parse_money("1.2M USD")` (#133) | `None` | `1200000.0` | [M] |
| Golden scores | -- | unchanged (`freeze_goldens.py --check` exit 0) | [M] |

## 2. CI diagnosis

### 2.1 Dojo (verified from the repository)

Source: `git diff origin/main...HEAD -- .circleci scripts/ci.py pyproject.toml tests/test_release_tools.py`.
CI was green on `main` before this branch; the defects were structural.

| # | Finding on `origin/main` | Evidence | Fixed in this branch |
|:--|:---|:---|:---|
| 1 | 26 skips in the CI environment, 21 of them silent and avoidable: `pydantic` and `jsonschema` were not in the `dev` extra. 4 modules: `test_schema_contract.py` (one module-level skip hiding its 14 tests), `test_corporate_record_schema.py` (18), `test_cuad_schema.py` (1), `test_maud_schema.py` (1). The other 5 skips belonged to tests since deleted (4 need a local results workbook, 1 a live Langfuse run). | `pytest -rs` on an `origin/main` export with `--extra dev`: `3564 passed, 26 skipped, 35 deselected` (release tests deselected: an export has no git history). The plan said "five test modules"; four were measured. | Yes, `fae660b`: `dev` gains `jsonschema`, `pydantic`; the 21 schema-contract skips run and pass. |
| 2 | No skip report in CI (`pytest -q` without `-rs`). | `.circleci/config.yml` at `origin/main`. | Yes: `-rs` in `scripts/ci.py`. |
| 3 | Dead guard `if [ -f scripts/freeze_goldens.py ]` with a stale "lands with PR #104" comment. | Same file; the script exists. | Yes: guard removed; the golden check is a `ci.py` step. |
| 4 | `test_cli_publish_dry_run_json` could wait out a 60 s network timeout. | `tests/test_release_tools.py` diff. | Yes: 20 s, skips on `TimeoutExpired`. |
| 5 | `uv lock --check` never ran in CI. | Not a step in the old config. | Yes: `ci.py` step `lock`. |
| 6 | The consumer-surface checks and the GT coverage page were not CI steps. | Not steps in the old config. | Partly: `ci.py` runs `render_gt_coverage.py --check`. `audit_consumer_surface.py --check` still needs consumer checkouts, so it is not in CI. |
| 7 | Docs disagreed with CI (`tests/README.md`: the tag test "fails"; it skips). | `tests/README.md` diff. | Yes. |
| 8 | No repo-owned CI entry point; steps lived only in YAML. | -- | Yes: `scripts/ci.py --tier full\|smoke [--json] [--junit]`; CircleCI now calls `--tier full`. `tests/test_ci_script.py` pins it. |

`scripts/ci.py --tier full` runs, in order and stopping at the first failure: `ruff` (`uvx ruff@0.17.3`),
`uv lock --check`, `pytest tests -q -rs`, `freeze_goldens.py --check`, `render_gt_coverage.py --check`.
`--tier smoke`: ruff plus `tests/test_consumer_compat.py`, `test_root_surface.py`, `test_doc_classes.py`,
`test_golden_scores.py`. The `release-chain` job and the tree-hash "already green" cache are unchanged.
Still open (BUG_SWEEP): building the wheel into a clean venv from `uv.lock`.

### 2.2 llm-mailroom and local-mailroom-sandbox **[P], not re-verified here**

Neither repo's CI was read in this session. From the plan:

| Repo | Finding | Fix lives in |
|:---|:---|:---|
| llm-mailroom | No lockfile. | Roadmap (section 9). |
| llm-mailroom | The daily Dojo auto-bump PR is red by design: `bump_dojo_scoring.py` does not refresh `vendor/`. | Roadmap. |
| llm-mailroom | The mock experiment gate cannot see extraction regressions. | Roadmap. |
| llm-mailroom | No parallelism; full suite over 10 minutes. | Roadmap. |
| sandbox | `test_vendor_drift.py` always skips in CI. | Roadmap. |
| sandbox | Lint tools unpinned behind a static cache key; uncached apt `shellcheck`. | Roadmap. |

## 3. Consumer usage matrix

Sources: `tests/fixtures/consumer_surface.json` (AST scan of imports, dispatch keys and monkeypatches) and
`docs/analysis/data/consumer_closure.json` (import closure). Both **[M]** (read from the committed files; the
scans themselves were not re-run, no consumer checkouts here). Names are root-level exports; modules are
`llm_dojo_scoring.<sub>` paths, 33 of 39 recorded through legacy flat paths.

| Consumer | Commit scanned | Files scanned | Root names used | Modules used | Closure roots | Dispatch / patches |
|:---|:---|--:|--:|--:|--:|:---|
| `llm-mailroom` (MAIL) | `5bcfe44` | 387 | 25 | 28 | 30 | `get_suite` at 20 sites (6 dynamic); 3 monkeypatches of `llm_dojo_scoring.embed_texts` |
| `local-mailroom-sandbox` (SBX) | `c81a79a` | 360 (505 in the closure scan, which includes its vendored `llm-mailroom`) | 15 | 16 | 33 | `get_suite` 5, `score_task` 1, `suite_for_doc_type` 5 |
| `The-Mailroom` (TMR) | `8b0bee5` | 107 | 1 (`pipeline_scoring`) | 0 | -- | -- |
| `Mailroom-Corpus-EDA` (EDA) | `8d730fc` | 68 | 0 | 4 (`pipeline.mailroom`, `schemas.corporate_record_relabel`, `schemas.corporate_record_schema`, `schemas.gt_metadata`) | -- | -- |
| `mailroom-ml` (ML) | `bd8557a` | 84 | 0 | 0 | -- | -- |
| `eval-environment` (EE) | **never scanned** (path did not exist) | 0 | -- | -- | -- | See review focus 2 of the plan: unscanned names resolve lazily or fail naming the changelog |

Notes:

- 38 distinct root names are consumed; 3 are used by more than one consumer. Three names (`agent_rubrics`,
  `legalbench_scoring`, `pipeline_scoring`) are module names recorded with `in_all: false`; `5230b85` added them to `__all__`.
- Closure also roots the four open mailroom audit-row branches (`stack/01-audit-storage` 30 roots,
  `stack/02-diagnostics-workbench` 30, `stack/03-audit-live-row` 31, `claude/howdy-n8vcc1` 33), read by `git show`.
  Commits recorded in `docs/analysis/data/consumer_closure.json`.
- Dynamic dispatch counts as a root: keys passed to `get_suite`
  (`contract`, `corporate_records_specialist`, `correspondence_specialist`, `court_opinion`, `due_diligence`,
  `intake`, `local_vs_api`, `merger_agreement`, `sorter`), `score_task` (`docclass`) and `suite_for_doc_type`
  (`corporate_record`) keep the modules they dispatch to.
- Of the 73 kept modules, 45 (22,111 lines) are imported directly by a consumer or a recorded surface and 24
  (4,266 lines) are reached only through a kept module; `__init__`, `_layout`, `metrics`, `scoring` are structural.
- Mailroom fixture refresh at `16a3725` found new use of `get_doc_scorer`, `analysis.calibration`,
  `scoring.reviewer`, `scoring.doc_scorers`, `config.clear_settings_cache`; nothing removed.

## 4. Keep / delete / hold, with line counts

Decision by `scripts/consumer_closure.py`. At `8eda0f0` (before deletion) the committed closure said:
72 keep (27,040 lines), 4 hold (1,123), **14 delete (4,974)**. Commit `0fde80b` deleted 13 modules (4,790 lines);
`analysis.failure_modes` (184 lines) moved from delete to **hold** because it is the source of the registry
metric `failure_mode_breakdown`. Closure now: 73 keep (27,176), 5 hold (1,307), 0 delete.

### Hold list (current closure)

| Module | Lines | Why held |
|:---|--:|:---|
| `analysis.failure_modes` | 184 | source of registry metric `failure_mode_breakdown` (sorter bundle), #66 |
| `integrations` (package) | 1 | package of the held module below |
| `integrations.update_awareness` | 530 | release tooling behind `dojo-version`, #66 |
| `schemas.correspondence_gt_audit` | 346 | correspondence ground-truth audit, #94 |
| `schemas.v10_rows` | 246 | v10 dataset row loaders, mailroom #174 |

The plan also listed `pipeline.archive`, `scoring.doc_scorers.*`, `scoring.extraction_scope` and
`pipeline.sandbox_schema_adherence` for hold. The closure shows all of them **kept by consumer import** (mailroom
audit-row branches), so they are not on the hold list. `schemas.corporate_record_relabel` is kept via the
`EDA` scan.

### Deleted (13 modules, 4,790 lines) **[M]**

`cli` (335); `analysis.{export 700, io 233, report 183, interpret 321, visualize 314, error_analysis 272, grid 949}`;
`integrations.{langfuse_sync 720, phoenix_sync 150}`; `scoring.rescore` (567);
`pipeline.{sandbox_agent_scoring 33, sandbox_composite 13}`. Also removed: the 4 CLIs, 11 legacy flat aliases (`_layout.LEGACY_MODULES`, 11 lines removed), `suites.LEGACY_FULL_EXTRACTION_FIELD_TYPES`, the `[jellyfish]` alias extra, and
`arize-phoenix`, `python-dotenv`, OpenTelemetry from `[tracing]`. `pandas`, `openpyxl`, `matplotlib` stay core
dependencies (llm-mailroom imports pandas without declaring it; CHANGELOG states this).

### Package lines per subpackage **[M]**

| Subpackage | Files before | Lines before | Files after | Lines after | Delta |
|:---|--:|--:|--:|--:|--:|
| (root: `__init__`, `_layout`, `config`, `cli`) | 4 | 1,558 | 3 | 1,423 | -135 |
| `analysis` | 15 | 5,873 | 8 | 2,901 | -2,972 |
| `integrations` | 4 | 1,401 | 2 | 531 | -870 |
| `metrics` | 10 | 4,900 | 10 | 4,892 | -8 |
| `pipeline` | 12 | 3,346 | 10 | 3,242 | -104 |
| `prompts` | 2 | 442 | 2 | 442 | 0 |
| `schemas` | 16 | 6,731 | 17 | 6,968 | +237 |
| `scoring` | 27 | 8,885 | 26 | 8,084 | -801 |
| **Total** | **90** | **33,136** | **78** | **28,483** | **-4,653** |

Growth is deliberate: `schemas/doc_classes.py` (new registry) and the lazy root `__init__` (467 to 684 lines:
the `_LAZY`, `_SUBMODULES` and `_REMOVED` tables). Files changed in the package beyond deletions: `scoring/suites.py`
(-182), `schemas/corpus.py` (-111), `scoring/extraction_scope.py` (-88): their class and field tables now derive
from the registry.

Whole-branch diff: 103 files, +12,410 / -11,015 lines; package 39 files (+1,418 / -5,957); tests 38 files
(+7,808 / -2,504) **[M]** (`git diff --shortstat origin/main...HEAD`).

## 5. Ground-truth coverage and the schema-vs-GT gap

Dataset `Lucius-Morningstar/mailroom-dataset` config `ground_truth`, revision `v9.3`, commit
`ccd040f6a1b6b414bdefd161cdc622b68f6dacf8`, 3,302 rows. Source: `llm_dojo_scoring/schemas/data/extraction_status.json`
as rendered into [`docs/schemas/GT_COVERAGE.md`](../schemas/GT_COVERAGE.md) (generated; the per-field table is there).
Status counts below were tallied from that page **[M]**. Status rule: scored statuses are `scored`, `partial`,
`derived`, `documented_absent`; everything the dataset populates is scored (no quality tiers).

| Class | Rows | Schema fields | Scored now | `pending_annotation` (no GT) | `not_applicable` | `label_task` | Notes |
|:---|--:|--:|--:|--:|--:|--:|:---|
| contract | 600 | 17 | 8 (all `derived`) | 9 | 0 | 0 | `cuad_clause_labels` populated on 509 / 600 (91 pending). Pending: `party_roles`, `signatories`, `agreement_date`, `expiration_date`, `termination_notice_period`, `dispute_forum`, `contract_value`, `payment_terms`, `territory` |
| merger_agreement | 152 | 21 | 2 (`merger_consideration`, `maud_clauses`; both `derived`) | 16 | 3 (`intent`, `subject_matter`, `keywords`) | 0 | Every other extraction field has no GT. MAUD labels only |
| corporate_record | 450 | 9 | 5 (3 `scored`, 1 `partial`, 1 `derived`) | 3 (`effective_date`, `jurisdiction`, `signatories`) | 1 (`filing_number`) | 0 | `entity_name` 412 / 450 (`partial`) |
| correspondence | 1,000 | 13 | 4 (3 `scored`, 1 `derived`) | 7 (`sender`, `recipient`, `additional_recipients`, `communication_date`, `demand_amount`, `action_items`, `urgency`) | 0 | 2 (`content_topic`, `sentiment_label`) | 7 of 11 schema fields unlabelled (the 13 include the 2 label tasks) |
| insurance_claim | 1,100 | 18 | 17 (14 `scored`, `adjuster` `partial` 150 / 1,100, `denial_reasons` `documented_absent` 36 / 1,100, `cms_source_table` `derived`) | 1 (`claim_checklist`, 0 / 1,100) | 0 | 0 | Closest to full coverage |

Caveats on the counts (from `GT_COVERAGE.md`):

- `derived` CUAD and MAUD fields show **source-container coverage** (rows whose `cuad_clause_labels` /
  `maud_clause_labels` is populated), not rows that answer that field's own category.
- `insurance_claim.cms_source_table` is 600 / 1,100 (CMS tables only), not 100%.

Closed-vocabulary values the scorer accepts but no GT row uses **[M]**: `insurance_claim.claim_type`:
`liability`, `life`, `other`, `workers_comp`; `coverage_determination`: `partial`; `intent`: `loss_report`, `other`.
`merger_agreement.intent` (3 values) is marked not applicable. No GT value falls outside the scored vocabulary.

Comparison with the plan's live-dataset table **[P]** (measured 2026-11-12 from the same commit): per-class row
counts and per-field populated counts agree with the rendered page; the plan's "9 of 17", "16 of 21", "7 of 11"
gaps match the `pending_annotation` column above. The re-pin from v9.2.1 to v9.3 (`80c4a6c`) changed no per-field
status; it added the vocabulary counts. `ExtractionSchema.schema_id` embeds the revision, so goldens carry five
relabelled ids (`<class>@v9.2.1` to `<class>@v9.3`) with no score value moved.

Three repos pin three dataset revisions (sandbox v9.1, Dojo status file now v9.3, mailroom v9.3; before this branch
Dojo was v9.2.1) **[P]**, not re-verified.

## 6. Issue ledger

Status "fixed here" means a commit on this branch plus a test that passes at `fb4abe2`. No issue is closed or
commented on by this work; the PR says `Fixes #133` and `Fixes #132` and `Refs` the rest.

### 6.1 Dojo issues

| Issue | Status | Evidence |
|:---|:---|:---|
| #133 `_parse_money("1.2M USD")` returned `None` | **Fixed here** (`36e856e`) | `tests/test_scoring_fixes_133_132.py::test_parse_money_reads_currency_words_with_suffixes` (7 cases) and `::test_parse_money_still_rejects_non_amounts`. Before/after [M]: `1.2M USD` None to 1200000.0; `USD 1.2M` None to 1200000.0; `5K dollars` None to 5000.0; `EUR 3B` None to 3000000000.0; `$1.2M`, `3 dollars`, `1,200,000 USD` unchanged |
| #132 carrier `cms_source_table` caps a perfect oracle at 0.9412 | **Reproduced on `origin/main` and fixed here** (`36e856e`) | `::test_perfect_carrier_extraction_scores_one`, `::test_perfect_carrier_extraction_has_full_field_micro_recall`, `::test_a_stated_wrong_cms_table_is_still_scored`. Before/after [M]: oracle `overall_score` 0.9412 (17 field scores) to 1.0 (16); a stated wrong table still scores 0.0. `freeze_goldens.py --check` exit 0, so the goldens do not exercise either change; `SCORE_CHANGELOG` has a 0.29.0 entry for `pipeline.extraction.overall` |
| #80 slim root `__init__` | **Done** (`5230b85`) | `tests/test_root_surface.py`; modules loaded 77 to 2, heavy deps `pandas`/`openpyxl` to none [M]. The commit message says 67 modules before; 77 was measured here (the count includes legacy alias entries) |
| #84 consumer-surface audit | **Done** (`f477ee0`, `16a3725`, `fb4abe2`) | `tests/test_consumer_closure.py`, `tests/test_audit_consumer_surface.py`. `audit_consumer_surface.py --check` **not run** (no consumer checkouts) |
| #78 dedupe `chained_composite` | **Done** (`0fde80b`) | `llm_dojo_scoring/scoring/tasks.py:485` is the only definition; `pipeline/sandbox_composite.py` deleted; CHANGELOG records the `RuntimeError` on a missing half |
| #79 prune legacy | **Partly done** (`0fde80b`) | Removed: `LEGACY_FULL_EXTRACTION_FIELD_TYPES`, `[jellyfish]` alias, `phoenix_sync`. Registry "legacy" metrics `run_aborted` / `stage_completed` stay: they are in mailroom's `SCORE_CONFIGS` **[P]** |
| #66 epic (retire deprecated packages) | **Open**; this PR delivers #78, #79 (part), #80, #84 | Commits above |
| #67 golden freeze | Delivered by `scripts/freeze_goldens.py`; `--check` exit 0 at `fb4abe2` [M]. Close-out is the owner's call | -- |
| #68 tiers | Not re-verified in this session | -- |
| #94, #95, #52 GT gaps (correspondence, merger, corporate) | **Still valid**; now visible and self-updating | Section 5. Closing needs labels, not code |
| #96 grammar hints for scored enums | **Not started**; its prerequisite (one registry, `d9d9e27`) is in | Roadmap |
| #74-#77 `mixed_source` moves | **Not moved**: consumers still call `legalbench_scoring` and `get_suite("court_opinion")` (confirmed by the dispatch keys in section 3 [M]) | Roadmap |
| #129 re-vendor prompts | Not re-verified in this session (plan [P]: looks done by PR #126) | -- |
| #120 audit row; mailroom #150-#156, #226-#229 | Not re-verified in this session. The closure shows `pipeline.archive`, `scoring.doc_scorers`, `scoring.extraction_scope` kept through the audit-row branches [M] | -- |

### 6.2 `docs/plans/BUG_SWEEP.md` items touched

| Item | Status |
|:---|:---|
| `audit_consumer_surface.py` pins developer paths, exits 2 | Fixed (`16a3725`); ticked in BUG_SWEEP |
| Repo-owned CI entry point | Partly: `scripts/ci.py` (section 2.1); clean-venv wheel build still open |
| Suite bloat | Profiled (section 7): runtime is not the problem; no tier changes beyond the smoke list |
| Insurance `claim_checklist` in the map with no GT | **Still open**: 0 / 1,100 rows, reported as `pending_annotation` [M]. Dropping it must move in step with llm-mailroom |
| Intents never seen in GT | **Still open**, now listed on the coverage page: `loss_report`, `other` (insurance) [M] |
| Correspondence audit gaps, #94 steps 2-5 | Open (labelling); `schemas.correspondence_gt_audit` held |
| CMS detection still sniffs `cms_source_table` | **Still open**: only the #132 symptom was fixed; explicit provenance is roadmap |

### 6.3 llm-mailroom and sandbox issues **[P], not re-verified in this session**

The repository could not be attached, so each row below is the plan's 2026-11-12 reading, unchanged. The plan's
Task 8 step 2 asked for each to be checked against mailroom `main`; that was **not done**.

| Issue | Plan's reading | Proposed disposition |
|:---|:---|:---|
| mailroom #192 taxonomy never wired into scoring | Fixed in code (`build_graph.py:20`, `run_pilot.py:76`, `run_hf_pilot.py:97` import `scoring_wiring`); issue open | Close |
| mailroom #195 yearless-date scoring | Dojo part landed in Dojo PR #135, included in mailroom pin `f95c318` | Close after confirming the loader part |
| mailroom #198 release chain | `pyproject` says 0.9.3; changelog part not checked | Verify with `release.py check`, then close |
| mailroom #187 "13 nodes" docs | Still valid (`README.md:11,103,127,276`) | Mailroom docs follow-up |
| mailroom #196 unpinned corpora | Partly (a live-or-loud warning exists) | Roadmap |
| mailroom #191, #193, #194, #197, #199-#201 | Linked PR #202 merged; issues open; not checked one by one | Verify each, then close or keep |
| mailroom #174 v10 schemas/loaders; #183 re-score insurance | Valid | `schemas.v10_rows` held; roadmap |
| mailroom: no lockfile; auto-bump red by design; posthoc `urgency="high"` outside the closed vocabulary | Valid; no issue yet | New issues |
| sandbox #216 corporate confidence prompt/schema mismatch | Partly: `corporate_records_specialist_condensed_v1.txt:23` still asks for `confidence` | Sandbox follow-up |
| sandbox #221 / Dojo #92 remote Dojo; #269 vendor audit | Valid | Roadmap |

## 7. Test-suite durations

Clean checkout of `fb4abe2`, `uv run --locked --extra dev pytest tests -q -rs --durations=25` **[M]**:
`3710 passed, 2 skipped in 22.42s`, exit 0. The two skips are
`test_release_tools.py:73` (needs release tags; the clone is shallow) and `test_release_tools.py:121` (GitHub CLI
unavailable). Collected: 3,712 tests in 100 files (`origin/main`: 3,625 in 102 files). The 25 slowest tests sum
to 6.62 s of 22.42 s; the slowest is 0.82 s. Runtime is not a bottleneck, which matches the earlier BUG_SWEEP
profile (3,688 tests, about 21 s).

| # | Seconds | Phase | Test |
|--:|--:|:---|:---|
| 1 | 0.82 | call | `test_release_tools.py::test_cli_publish_dry_run_json` |
| 2 | 0.79 | call | `test_maud_schema.py::test_every_rendered_line_round_trips_through_the_real_scorer[…]` |
| 3 | 0.40 | call | `test_prompts.py::test_llm_templates_omit_t0_t1_registry_ids` |
| 4 | 0.36 | call | `test_sandbox_schema_adherence.py::test_sibling_scan_stays_linear` |
| 5 | 0.34 | call | `test_consumer_closure.py::test_committed_json_covers_every_module_file_of_the_real_package` |
| 6 | 0.29 | call | `test_doc_scorer_departures.py::test_departures_are_current` |
| 7 | 0.28 | call | `test_update_awareness.py::test_cache_notices_are_bounded_and_expire` |
| 8 | 0.25 | call | `test_pr104_review_fixes.py::test_audit_star_import_binds_dispatch_aliases` |
| 9 | 0.23 | call | `test_archive_scoring.py::test_score_archive_block_rejects_contract_alias_for_merger` |
| 10 | 0.23 | call | `test_consumer_closure.py::test_committed_json_honours_the_hold_list_and_the_structural_modules` |
| 11 | 0.23 | call | `test_consumer_closure.py::test_every_real_hold_entry_names_a_module_of_the_real_package` |
| 12 | 0.22 | setup | `test_release_subtree_prefix.py::test_show_at_commit_reads_a_commit_that_predates_the_hub_import` |
| 13 | 0.21 | setup | `test_release_subtree_prefix.py::test_build_assets_builds_a_pre_import_commit_from_its_root` |
| 14 | 0.20 | setup | `test_audit_consumer_surface.py::test_submodule_alias_dispatch_calls_are_recorded[…]` |
| 15 | 0.20 | call | `test_update_awareness.py::test_concurrent_process_notice_claims_and_merge` |
| 16 | 0.20 | call | `test_sandbox_schema_adherence.py::test_many_open_braces_parse_in_linear_time` |
| 17 | 0.18 | call | `test_score_document_robustness.py::test_odd_field_values_never_raise_either_entry_point[…]` |
| 18 | 0.18 | call | `test_asr.py::test_transcriber_suites_return_wer_cer_and_have_no_honest_gap` |
| 19 | 0.16 | call | `test_update_awareness.py::test_strict_source_import_scoring_and_cli_do_not_network[…]` |
| 20 | 0.16 | call | `test_sandbox_schema_adherence.py::test_deeply_nested_text_is_unparseable_not_a_crash[…]` |
| 21 | 0.15 | call | `test_score_document_robustness.py::test_odd_field_values_never_raise_either_entry_point[…]` |
| 22 | 0.14 | call | `test_pr104_review_fixes.py::test_audit_pins_keyword_dispatch_literals` |
| 23 | 0.14 | call | `test_pr104_review_fixes.py::test_audit_pins_star_import_names` |
| 24 | 0.13 | call | `test_score_document_robustness.py::test_odd_field_values_never_raise_either_entry_point[…]` |
| 25 | 0.13 | call | `test_doc_classes.py::test_new_insurance_field_reaches_every_derived_table` |

Largest files by test count: `test_score_document.py` 476, `test_docstring_coverage.py` 196,
`test_field_scoring.py` 163, `test_correspondence_gt_audit.py` 122, `test_sandbox_schema_adherence.py` 111,
`test_update_awareness.py` 107, `test_doc_scorers_types.py` 98, `test_corporate_record_schema.py` 87.

## 8. Consumer verification

Quoted verbatim from the orchestrator **[S]**:

- local-mailroom-sandbox at commit c81a79a, venv per its CLAUDE.md. Dojo-facing tests (`tests/test_scoring_outputs_golden.py tests/test_eval.py tests/test_serving_parity.py tests/test_scoring_ownership.py tests/test_prompt_versions_dojo.py tests/test_prompt_catalog.py -n 0 --no-cov`): vendored snapshot 117 passed, 2 skipped; with DOJO_SRC = this branch, 117 passed, 2 skipped.
- Full sandbox suite: vendored snapshot 1 failed, 3137 passed, 29 skipped (pre-existing failure tests/test_job_trace_pack.py::test_pack_defaults_and_missing_source). With DOJO_SRC = a clean `git archive` export of this branch at 36e856e: 7 failed, 3131 passed, 29 skipped; the 6 extra failures (test_dependency_sources.py ×3, test_snapshots.py::test_fresh_process_imports_cache_without_installed_or_vendor, test_vendor.py ×2) all assert that the vendored snapshot (commit 00a2a7f…, "cached 0.28.1") is the one resolved, and fail only because DOJO_SRC overrides it; no failure concerns Dojo behavior. (Pointing DOJO_SRC at the live checkout instead gave 256 failures + 12 errors, all from the sandbox's snapshot hasher refusing the symlinks in the Dojo's uv `.venv` — environment, not a regression.)
- llm-mailroom: NOT verified in this session (repository could not be attached). Its pin-bound and Dojo-referencing tests remain to run.

Gaps in this section: the sandbox runs were at Dojo `36e856e`; the branch head is now `fb4abe2` (script and test
changes only), and the sandbox was not
re-run at `fb4abe2`. `git diff --stat 36e856e fb4abe2 -- llm_dojo_scoring` is empty [M]. The plan's expected llm-mailroom pin-bound failures (`test_dojo_source.py`,
`test_dojo_v012.py`, pin checks in `test_docs_truth.py`) are **not named from a run**.

## 9. Phase-2 roadmap

From the plan. Each needs consumer PRs or labels, so none belongs in this PR.

| # | Item | Depends on |
|:--|:---|:---|
| 1 | #74-#77: move LegalBench, ContractEval and the retired classes to `mixed_source` | Consumer PRs: mailroom still calls `legalbench_scoring` and `get_suite("court_opinion")` |
| 2 | Consolidate the metric registry, profiles and bundles onto `doc_classes` (the 161-metric registry is untouched here) | Registry in place (`d9d9e27`) |
| 3 | #96 grammar hints for scored enums | Registry (done) |
| 4 | v10: `schemas.v10_rows` loaders; mailroom #174, #183 | Dataset v10 |
| 5 | #94 / #95 / #52: GT labels for correspondence, merger and corporate; drop or label insurance `claim_checklist` | Labelling; llm-mailroom schema decision |
| 6 | Explicit-provenance CMS detection (replaces `cms_source_table` key-sniffing) | BUG_SWEEP item |
| 7 | One shared dataset pin across Dojo, mailroom and sandbox | Three repos |
| 8 | mailroom: `bump_dojo_scoring.py` refreshes `vendor/`; add a lockfile; posthoc `urgency="high"` | mailroom |
| 9 | sandbox: stop `test_vendor_drift.py` skipping in CI; pin lint tools; sandbox #216 prompt | sandbox |
| 10 | #92 / sandbox #221 remote Dojo; #269 vendor audit | sandbox |
| 11 | Scan `eval-environment` (never scanned) before the next removal round | Checkout |
| 12 | `ci.py`: clean-venv wheel build from `uv.lock` | BUG_SWEEP item |
| 13 | After merge: `/dojo-bump` in mailroom (with vendor refresh) and `/vendor-sync` in the sandbox, which can then drop `pandas` / `openpyxl` from its base deps | User-invoked, not part of this PR |
| 14 | Issue hygiene (close #192, #195, #198 after verification; #129, #67; flag mailroom #187) | Section 6.3 |

## 10. Findings outside this change

- `tests/test_audit_consumer_surface.py::test_default_checkout_locations_are_siblings_not_developer_paths` once
  failed when the Dojo was checked out under `/tmp`. It now checks each default path against
  `audit.REPO_ROOT.parent` and no longer depends on the checkout location.
- Core dependencies `pandas`, `openpyxl`, `matplotlib` have no import left in `llm_dojo_scoring` (`grep` finds
  none). They stay core for llm-mailroom's undeclared `pandas` import; see roadmap item 13.

## Reproduce

All commands run from the repository root unless noted. `<export>` is a scratch directory.

| Figure | Command |
|:---|:---|
| Package lines per subpackage | `git ls-tree -r origin/main --name-only llm_dojo_scoring \| grep '\.py$'`, then `git show origin/main:<path> \| wc -l` for each; the working tree with `wc -l`; summed per first path component |
| Modules loaded, `__all__` size, heavy deps | `python -c "import sys, llm_dojo_scoring as m; print(len([x for x in sys.modules if x.startswith('llm_dojo_scoring')]), len(m.__all__), [x for x in ('pandas','matplotlib','openpyxl') if x in sys.modules])"`, once with `PYTHONPATH=<export of origin/main>` (`git archive origin/main llm_dojo_scoring \| tar -x -C <export>`) and once on the branch |
| Skips before | export of `origin/main`; `uv run --locked --extra dev pytest tests -q -rs -p no:cacheprovider --deselect tests/test_release_tools.py` |
| Durations and test counts after | clean checkout of `fb4abe2`: `uv run --locked --extra dev pytest tests -q -rs --durations=25`; `... --collect-only -q` for per-file counts |
| #133 / #132 before and after | `parse_money` on the listed strings and `get_suite("insurance_claims_specialist").score(expected=row, predicted=row, doc_subclass="carrier")` on a synthetic 16-field carrier row (the row built in `tests/test_scoring_fixes_133_132.py`), against the `origin/main` export and the branch |
| Golden / GT page / lock | `uv run --locked python scripts/freeze_goldens.py --check` (exit 0); `uv run --locked python scripts/render_gt_coverage.py --check` (exit 0); `uv lock --check` (exit 0), all at `fb4abe2` |
| Consumer matrix, closure counts, hold list | read from `tests/fixtures/consumer_surface.json` and `docs/analysis/data/consumer_closure.json` with `python -c "import json; ..."`; the pre-deletion closure from `git show 8eda0f0:docs/analysis/data/consumer_closure.json` |
| GT status counts | tallied from the tables in `docs/schemas/GT_COVERAGE.md` |
| Diffstats | `git diff --shortstat origin/main...HEAD [-- llm_dojo_scoring \| tests]` |
