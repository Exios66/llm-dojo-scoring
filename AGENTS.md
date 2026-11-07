# AGENTS.md

`llm-dojo-scoring` (the Dojo) is the shared scoring engine of the Mailroom constellation:
one importable library, plus CLIs, that scores document classification and
field-type-aware extraction, quantifies uncertainty, explains failures and writes reports.
Python 3.11+. Every metric that `llm-mailroom`, `local-mailroom-sandbox` and
`eval-environment` report is computed here.

This is the long-form manual for every coding agent (Claude Code, Codex, Cursor, OpenCode)
and for humans. Read it by section, on demand.

## Start here (every agent, every task)

1. **Read `CLAUDE.md` first**, whatever tool you are. It is the short, maintained summary
   for all agents: purpose, constellation relationships, file map, commands, verification
   gates and the rules that prevent repeated mistakes. This manual expands on it.
2. **Follow the agent workflow** in `.claude/rules/` (Claude Code loads these files
   automatically; other tools must read them):
   - `.claude/rules/evidence-contract.md` — what counts as proof before you call anything
     done, fixed or passing, and how evidence (test output, ruff, golden diffs,
     screenshots) reaches the PR.
   - `.claude/rules/orchestration.md` — how work is delegated: the main session
     orchestrates on the top model tier and never spawns a subagent on that tier; scoped
     higher-level work goes to mid-tier subagents (Sonnet, effort high); simple tasks
     (run, fetch, collect, mechanical edits) go to the small tier (Haiku, effort high);
     every subagent change gets 1–3 adversarial review rounds sized to the change, then
     the orchestrator re-verifies.
   - `.claude/rules/pr-flow.md` — local gate → self-review → fresh-context pre-PR review
     → draft PR → bot review (CodeRabbit, CodeAnt). Nothing is pushed for review unvetted.
3. **Fill in `.github/pull_request_template.md`** for every PR: problem, change, evidence,
   what was not verified, review log, public API and consumer impact.

Tools without named model tiers: use your strongest model only for orchestration and final
verification, a mid-size model for implementation and review, and a small model for
mechanical work. The subagent briefs in `.claude/agents/` work as prompts in any tool.

## Contents

- [Commands](#commands)
- [Package layout](#package-layout)
- [Scoring rules that must not drift](#scoring-rules-that-must-not-drift)
- [Public API and consumers](#public-api-and-consumers)
- [Golden baseline](#golden-baseline)
- [Releases](#releases)
- [Testing quirks](#testing-quirks)
- [Source ownership and the constellation](#source-ownership-and-the-constellation)
- [Documentation layout](#documentation-layout)

## Commands

```bash
uv sync --frozen --extra dev                     # install from the lock (what CI does)
uv run --extra dev pytest tests -q               # full suite (~2,500 tests, network-free, under a minute)
uv run --extra dev pytest tests/test_cli.py -q   # one file
uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples   # lint gate (CI pins 0.17.3)
uv run python scripts/freeze_goldens.py --check  # golden score baseline (exit 1 + unified diff on drift)
uv run python scripts/freeze_goldens.py --write --reason "…"   # ONLY for an intended score change
uv run python scripts/audit_consumer_surface.py --check   # consumer import surface (needs consumer checkouts; exit 2 if missing)
python scripts/release.py status                 # read-only: version / changelog / pin chain
python scripts/release.py check                  # read-only: errors exit 1; WARN lines exit 0
python scripts/release.py cut X.Y.Z              # dry run; --apply writes (needs the user's go-ahead)
dojo-analyze / dojo-export / dojo-rescore / dojo-sync / dojo-version   # CLIs (see README "CLI reference")
```

- Plain `pip install -e ".[dev]"` then `pytest` also works. Extras: `embeddings`
  (sentence-transformers / OpenAI embedding rescue), `tracing` (Langfuse / Phoenix sync),
  `catalog`, `all`. The default suite needs none of them.
- No type checker is configured. Ruff runs a correctness-only rule set
  (`E9, F63, F7, F82, B006, B018, PLE` in `pyproject.toml`); F401/F841 are excluded on
  purpose because the package re-exports names. Widen the set only together with a cleanup.
- Settings: one `Settings` object (`llm_dojo_scoring/config.py`); `configure(...)`,
  `configure_from_taxonomy(...)`, or `LLM_DOJO_SCORING_CONFIG=<yaml>` for a process-wide
  override.

## Package layout

Modules are grouped into subpackages; only entry points sit at the root. The full table is
`llm_dojo_scoring/README.md`.

| Subpackage | Owns |
|:---|:---|
| `scoring/` | Deterministic scorers: `field_scoring` (field types), `classification`, `tasks` (`score_task`), `suites` (one per pipeline agent — the API consumers call), `extraction_metrics`, `content_scoring`, `claims_consistency`, `legalbench_scoring`, `asr`, `reviewer`, `rescore` |
| `schemas/` | What dataset rows mean: `corpus`, `gt_metadata`, `intents`, `equivalences`, CUAD / MAUD / corporate-record schemas, `schema_contract` |
| `pipeline/` | The llm-mailroom pipeline contract (`mailroom`), intake clerk, pilot labels, verdicts, `archive` (audit-row hash, byte-identical to llm-mailroom's), sandbox rubrics |
| `metrics/` | `registry` (every score name → tier T0–T3), `profiles`, `bundles`, `emitter` (`ScoreRecord`, JSONL / Langfuse routing), `scorecard_honesty`, `score_changelog` |
| `analysis/` | `bootstrap`, `calibration`, `diagnostics`, `error_analysis`, `failure_modes`, `report`, `visualize`, `grid`, `serving`, `cost` |
| `integrations/` | `langfuse_sync`, `phoenix_sync`, `update_awareness` (`dojo-version`) |
| `prompts/` | Importable prompt catalog and the frozen eval-environment lineage |

**Legacy flat paths.** Until v0.26.0 every module sat directly under `llm_dojo_scoring`.
`_layout.py:install_legacy_aliases()` keeps `import llm_dojo_scoring.field_scoring` (and
`mock.patch("llm_dojo_scoring.field_scoring._get_embedding")`) working, and each old path is
the **same module object** as its new path. When you move or rename a module, add it to
`LEGACY_MODULES` and test the old path. New code imports from the subpackage path.

## Scoring rules that must not drift

Detail: `docs/guides/SCORING.md`, `docs/contracts/`.

- Field types: `id` (normalize, exact), `date` (parse to ISO, exact), `money` (strip
  symbols, within one cent), `name` (containment, Jaro-Winkler + token-set ratio),
  `free_text` (SQuAD token F1), `label` (exact on a controlled vocabulary, no partial
  credit), `entity_list` (Hungarian bipartite matching → precision / recall / F1).
- Embedding similarity is a **second signal** only below
  `field_scoring.embedding_rescue_below`; it never overrides a confident string score and
  never rescues a blank prediction or expectation.
- Metric identity is fixed: names and tiers come from `metrics/registry.py` and
  `docs/contracts/METRIC_IDS.md`. Renaming a metric is a consumer-breaking change.
- Scorecards fail closed (`metrics/scorecard_honesty.py`): no ground truth, no score.
- `jellyfish` is a core dependency; without it name matching silently degrades to
  `difflib`. Do not move it back to an extra.

## Public API and consumers

- `docs/guides/PUBLIC_API.md` is the supported surface. It is written by hand and mirrors
  `tests/fixtures/consumer_surface.json`, a static AST scan of the consumer repositories
  made by `scripts/audit_consumer_surface.py`. `tests/test_public_api_doc.py` fails when a
  name in the fixture is missing from the page.
- To change the surface: regenerate the fixture (`--write`, with the consumer checkouts
  available as siblings), update the page, keep the old name working with a deprecation
  note in `CHANGELOG.md`, and run `tests/test_consumer_compat.py`.
- Anything not on that page may be renamed in a minor release after a deprecation notice.
- A change to the public surface is a three-repo event. Use the `/cross-repo-bump` skill
  (Claude Code) or follow `.claude/skills/cross-repo-bump/SKILL.md` by hand.

## Golden baseline

`tests/fixtures/golden/inputs.json` is hand-authored; `scores.json` is generated from it
by `scripts/freeze_goldens.py` and covers every key in `config.TASK_KINDS` and every live
suite. CI runs `--check`. A diff means a score moved:

- unintended → it is a bug; fix the code, never the baseline;
- intended → show the diff in the PR, rewrite with `--write --reason "…"`, add a
  `CHANGELOG.md` entry, and name the consumer impact.

## Releases

- Do not hand-edit the version. It lives in `pyproject.toml`, `llm_dojo_scoring/__init__.py`,
  `CHANGELOG.md`, README release pins and `tests/test_consumer_compat.py`. Move them together
  with `python scripts/release.py cut X.Y.Z` (dry run unless `--apply`).
- `release.py check` exits non-zero only on errors (version disagreement, `pyproject` behind
  the newest tag, pin or changelog order problems). Missing changelog sections for tags and
  odd tags are `WARN` lines with exit 0 — quote them; a green check does not prove every tag
  matches.
- `cut --apply`, `publish`, `edit` and `assets` need the user's explicit go-ahead. Never
  force-push, delete or move tags, or amend release commits.
- After a release: `llm-mailroom` bumps its pin (`src/scripts/bump_dojo_scoring.py`, its
  `/dojo-bump` skill), the sandbox refreshes its vendor snapshot (`/vendor-sync`). Full
  steps: `docs/guides/RELEASES.md` and `.claude/skills/cross-repo-bump/SKILL.md`.

## Testing quirks

- The suite is network-free. `test_cli_publish_dry_run_json` calls `git ls-remote` / `gh`
  and skips itself without `gh`.
- `tests/test_release_tools.py` needs tags and full history: in a shallow clone,
  `test_notes_render_contains_changelog_and_commit` is skipped. `git fetch --unshallow --tags`
  lets it run.
- Load repo scripts in tests with `tests/conftest.py:load_script(name)`, never
  `from scripts import ...` (a co-installed `llm-mailroom` shadows the `scripts` package).
- `uv.lock` is generated: edit `pyproject.toml`, run `uv lock`. A hook blocks direct edits.

## Source ownership and the constellation

This standalone repository is the authoritative source for all scoring logic. Develop,
test and merge here first; Digital-Mailroom then imports the exact merged revision into
`packages/llm-dojo-scoring` and refreshes the sandbox vendor snapshot. Never port a fix
*from* a consumer or a `vendor/` tree back into this repo, and never accept hub-to-feeder
development pushes.

| Repo | How it consumes the Dojo | What a change here obliges |
|:---|:---|:---|
| llm-mailroom | git pin (40-hex SHA) in `pyproject.toml` + fallback snapshot `vendor/llm-dojo-scoring/`; daily `bump-dojo-scoring.yml` opens bump PRs | a release or interim SHA, then its `bump_dojo_scoring.py`; it verifies against the real pinned revision |
| local-mailroom-sandbox | tracked snapshot under `vendor/llm-dojo-scoring`, pinned in `_VENDOR_PINS` | its `/vendor-sync` after the release is merged |
| eval-environment | imports suites and the frozen v1 prompt lineage | keep `prompts/` lineage stable; note changes in the PR |
| mailroom-ml | reads the Dojo taxonomy | never redefine taxonomy there |
| Digital-Mailroom | imports merged `main` | merge here first |

Cross-repo bugs go to `LLM-Mailroom-Services/mailroom-issues`; hub work is tracked in
Digital-Mailroom `governance/TASKS.md`.

## Documentation layout

- `README.md` — public contract, install, quickstart, CLI reference.
- `llm_dojo_scoring/README.md` — package layout and the module table.
- `docs/guides/` — `SCORING.md`, `PUBLIC_API.md`, `RELEASES.md`, `MIGRATION.md`,
  `ADDING_A_DOCUMENT_TYPE.md`, `COMPARABILITY.md`, `GRID_REPORTS.md`, `PROMPTS.md`,
  `UPDATE_AWARENESS.md`.
- `docs/contracts/` — metric ids, scorecard honesty, archive / reviewer / sandbox scoring.
- `docs/schemas/` — extraction, CUAD, MAUD, corporate-record and GT metadata schemas.
- `docs/history/`, `docs/plans/` — past transfers, TODOs and plans; not current contracts.
- `CHANGELOG.md` — every user-visible change under `[Unreleased]` until `release.py cut`.
