# CLAUDE.md — llm-dojo-scoring

The Dojo is the **scoring engine** of the Mailroom constellation: the one place that
defines what "correct" means. A library plus one CLI (`dojo-version`) that scores classification and field-type-aware
extraction, quantifies uncertainty and reports failures. Python 3.11+. **Every change here
is a cross-package event**: a wrong number here becomes a wrong number everywhere.

`AGENTS.md` is the long-form manual (module ownership, public API, scoring rules, releases).
`README.md` is the public contract; `docs/guides/` holds scoring detail. Read on demand.

**Always loaded with this file** (`.claude/rules/`), and binding on every task:

- `orchestration.md` — Opus orchestrates; Sonnet and Haiku subagents do the work; 1–3
  adversarial review rounds; orchestrator re-verifies.
- `evidence-contract.md` — what counts as proof before anything is called done.
- `pr-flow.md` — local gate → fresh-context pre-PR review → draft PR → bot review.

## Constellation: who depends on what

| Repo | Relationship to this repo |
|:---|:---|
| `Exios66/llm-mailroom` | **Consumer.** Pins a Dojo commit (40-hex SHA) in its `pyproject.toml` and keeps a fallback `vendor/llm-dojo-scoring/` snapshot of the same commit. Bumps through its `src/scripts/bump_dojo_scoring.py` and a daily `bump-dojo-scoring.yml` workflow. Owns the taxonomy the Dojo is configured from. |
| `Exios66/local-mailroom-sandbox` | **Consumer.** Scores sandbox runs with a tracked snapshot under its `vendor/llm-dojo-scoring`, pinned in its `_VENDOR_PINS`; refreshed by its `/vendor-sync`. |
| `LLM-Mailroom-Services/eval-environment` | **Consumer.** Per-node evals; its frozen v1 prompt lineage is mirrored in `llm_dojo_scoring/prompts/`. |
| `LLM-Mailroom-Services/mailroom-ml` | Consumes the Dojo taxonomy; never redefines it. |
| `LLM-Mailroom-Services/Digital-Mailroom` | **Integration hub.** Imports our merged `main` into `packages/llm-dojo-scoring` and refreshes vendor snapshots. Never develop here from the hub. |
| `Lucius-Morningstar/mailroom-dataset` (HF) | The ground truth the scorers read (`schemas/gt_metadata.py`, `schemas/corpus.py`). |

The surface consumers rely on is listed in `docs/guides/PUBLIC_API.md` (written by hand; it mirrors
`tests/fixtures/consumer_surface.json`, and `tests/test_public_api_doc.py` checks that every consumed name is documented). Changing anything on it needs the
`/cross-repo-bump` walk.

## File map

| Path | What lives there |
|:---|:---|
| `llm_dojo_scoring/__init__.py` | public API re-exports — consumers import from here |
| `llm_dojo_scoring/_layout.py` | legacy flat import paths → subpackage modules (keep them working) |
| `llm_dojo_scoring/scoring/` | deterministic scorers: `field_scoring`, `classification`, `tasks`, `suites` (per-agent API), … |
| `llm_dojo_scoring/schemas/` | `doc_classes.py` (the one class/field registry), corpus, GT metadata, CUAD/MAUD, equivalences |
| `llm_dojo_scoring/pipeline/` | llm-mailroom pipeline and sandbox scoring contracts, archive audit row |
| `llm_dojo_scoring/metrics/` | metric registry and tiers, bundles, profiles, emitter, scorecard honesty |
| `llm_dojo_scoring/analysis/` | bootstrap, calibration, diagnostics, failure modes, serving, cost |
| `llm_dojo_scoring/integrations/` | `dojo-version` release awareness |
| `llm_dojo_scoring/prompts/` | importable prompt catalog and frozen lineage |
| `llm_dojo_scoring/config.py` | `Settings` (`LLM_DOJO_SCORING_CONFIG`) |
| `tests/` | ~3,500 tests, network-free but one release test; `tests/fixtures/golden/` is the golden score baseline |
| `scripts/` | `release.py`, `freeze_goldens.py`, `audit_consumer_surface.py`, `consumer_closure.py`, `build_extraction_status.py`, `render_gt_coverage.py`, GT audits |
| `docs/guides/`, `docs/contracts/`, `docs/schemas/` | scoring guides, metric ids and contracts, schema docs |

Full module table: `llm_dojo_scoring/README.md`.

## Commands

```bash
uv run --locked --extra dev pytest tests -q      # full suite (under a minute; one release test uses the network)
uv run --extra dev pytest tests/test_field_scoring.py -q   # one file
uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples   # lint gate, same version as CI
uv run --locked python scripts/freeze_goldens.py --check   # golden scores unchanged (exit 1 + diff on drift)
python scripts/release.py status                 # read-only: version / changelog / pin chain
python scripts/release.py check                  # read-only: verify the chain is consistent
```

- Plain `pytest` also works after `pip install -e ".[dev]"`. Optional extras
  (`embeddings`, `tracing`, `catalog`) are only needed for the code paths that name them.
- Ruff is not in the `dev` extra (keeps `uv.lock` untouched): use `uvx ruff …`. The
  PostToolUse hook runs `ruff` from PATH and is a no-op without it.
- Shallow clone with no tags (typical in cloud sessions):
  `tests/test_release_tools.py::test_notes_render_contains_changelog_and_commit` is skipped;
  `git fetch --unshallow --tags` lets it run.

## Verification gates

Run the ones that match the change, on the final state, and keep the output for the PR
(`.claude/rules/evidence-contract.md`). CI (`.circleci/config.yml`, job `test`) runs ruff,
the full suite and the golden check; `release-chain` runs `release.py check` on `main`.

| Change touches | Run |
|:---|:---|
| Anything | ruff, the full suite, `freeze_goldens.py --check` |
| A score, metric, normalization or suite | + before/after scores on fixtures; if intended, `freeze_goldens.py --write --reason "…"` and a `CHANGELOG.md` entry |
| Public names, `field_scoring`, suite results, `ScoreRecord` shapes | + `tests/test_consumer_compat.py`, `tests/test_public_api_doc.py`, `scripts/audit_consumer_surface.py --check` |
| A moved or renamed module | + a test that imports the old flat path |
| Dependencies | + `uv lock`, `uv lock --check` (exit 0), then `uv sync --frozen --extra dev` and the suite |
| Versions / changelog | + `python scripts/release.py check` (quote its `WARN` lines) |

**No type checker is configured.** Ruff's rule set is correctness-only (`pyproject.toml`).
Report exactly that; never claim "type-safe" or "fully linted".

## Rules that prevent repeated mistakes

- **Dojo owns scoring logic.** Scoring changes land here first. Never port a fix *from*
  `llm-mailroom` or the sandbox's `vendor/` back into this repo.
- **Do not hand-edit versions.** The version lives in `pyproject.toml`,
  `llm_dojo_scoring/__init__.py`, `CHANGELOG.md`, README release pins and
  `tests/test_consumer_compat.py`. Move them together with
  `python scripts/release.py cut X.Y.Z` (dry run unless `--apply`). Never force-push,
  delete tags, or amend release commits.
- **Never rewrite the golden baseline to get green.** `freeze_goldens.py --write` is only
  for an intended score change, with `--reason`, and the user should know.
- **Package layout:** modules are nested in subpackages. Legacy flat paths are kept alive
  by `_layout.install_legacy_aliases()`. When moving or renaming a module, keep the alias
  working — consumers import (and monkeypatch) the old paths.
- **`uv.lock` is generated.** Change dependencies in `pyproject.toml`, then run `uv lock`.
  A hook blocks direct edits.
- **Tests load repo scripts by path** via `tests/conftest.py:load_script(name)`, not
  `from scripts import ...` — a co-installed `llm-mailroom` shadows `scripts`.
- Core deps are deliberately small. `jellyfish` is core (name matching silently degrades
  to `difflib` without it); do not move it back to an extra.
- Embedding similarity only rescues an ambiguous string score and never a blank
  prediction or expectation (`llm_dojo_scoring/scoring/field_scoring.py:_with_embedding_rescue`).
- Secrets: `.env` is git-ignored; only `.env.example` is tracked. Never print or commit
  Langfuse keys. Never write to hosted services (Langfuse, Hugging Face) unless the user asks.

## Subagents and skills

- Project subagents (`.claude/agents/`): `implementer` (Sonnet), `runner` (Haiku),
  `adversarial-reviewer` (Sonnet), `pre-pr-reviewer` (Sonnet). How and when to use them:
  `.claude/rules/orchestration.md`.
- `/cross-repo-bump` (`.claude/skills/cross-repo-bump/`) — walk a release or a public-API
  change through Dojo, then llm-mailroom, then the sandbox vendor snapshot. User-invoked
  only; every mutating release step still needs the user's explicit go-ahead.

## Before you finish

Follow `.claude/rules/pr-flow.md`. If you touched anything importable by the other repos
(public names in `__init__.py`, `field_scoring`, suite results, `ScoreRecord` shapes), say
so in the PR and the summary: `llm-mailroom` and the sandbox vendor snapshot will need a
coordinated bump.
