# CLAUDE.md — llm-dojo-scoring

The Dojo is the **scoring engine** of the Mailroom constellation. It is a library
plus CLI (`dojo-analyze`, `dojo-export`, `dojo-sync`, `dojo-version`) consumed by
two sibling repos: `llm-mailroom` (git-SHA pin) and `local-mailroom-sandbox`
(tracked snapshot under its `vendor/`). A change here is a cross-package event.

Read `README.md` for the public contract and `docs/guides/` for scoring detail.

## Commands

```bash
uv run --extra dev pytest tests -q          # full suite (network-free)
uv run --extra dev pytest tests/test_cli.py -q   # one file
uvx ruff check llm_dojo_scoring tests scripts examples   # correctness gate; same as CI
python scripts/release.py status            # read-only: version / changelog / pin chain
python scripts/release.py check             # read-only: verify the chain is consistent
```

In a shallow clone with no tags (typical for cloud sessions),
`tests/test_release_tools.py::test_notes_render_contains_changelog_and_commit`
is skipped; `git fetch --unshallow --tags` lets it run. Everything should pass
(about 2500 tests, under a minute).

Ruff is not in the `dev` extra (keeping `uv.lock` untouched): use `uvx ruff ...` or
`pip install ruff`. The editing hook uses `ruff` from PATH and is a no-op without it.

Plain `pytest` also works once `pip install -e ".[dev]"` has been run. Optional
extras (`embeddings`, `tracing`, `catalog`) are only needed for the code paths
that name them; the default suite does not need them.

## Rules that prevent repeated mistakes

- **Dojo owns scoring logic.** Scoring changes land here first. Never port a fix
  *from* `llm-mailroom` or the sandbox's `vendor/` back into this repo.
- **Do not hand-edit versions.** The version lives in `pyproject.toml`,
  `llm_dojo_scoring/__init__.py`, `CHANGELOG.md`, README release pins and
  `tests/test_consumer_compat.py`. Move them together with
  `python scripts/release.py cut X.Y.Z` (dry-run unless `--apply`). Never
  force-push, delete tags, or amend release commits.
- **Package layout:** modules are nested in subpackages (`analysis/`, `scoring/`,
  `metrics/`, `pipeline/`, `integrations/`, `schemas/`). Legacy flat import paths
  are kept alive by `_layout.install_legacy_aliases()`. When moving or renaming a
  module, keep the alias working — consumers import the old paths.
- **`uv.lock` is generated.** Change dependencies in `pyproject.toml`, then run
  `uv lock`; do not edit the lock by hand. A hook blocks direct edits.
- **Tests load repo scripts by path** via `tests/conftest.py:load_script(name)`,
  not `from scripts import ...` — a co-installed `llm-mailroom` shadows `scripts`.
  Use `load_script` for any new script test.
- Core deps are deliberately small. `jellyfish` is core (name matching silently
  degrades to `difflib` without it); do not move it back to an extra.
- Secrets: `.env` is git-ignored; only `.env.example` is tracked. Never print or
  commit Langfuse keys.

## Skills

- `/cross-repo-bump` (`.claude/skills/cross-repo-bump/`) — walk a release or a public-API
  change through Dojo, then llm-mailroom, then the sandbox vendor snapshot. User-invoked
  only; every mutating release step still needs your explicit go-ahead.

## Before you finish

Run the full suite and `ruff check`. If you touched anything importable by the
other repos (public names in `__init__.py`, `field_scoring`, `ScoreRecord`
shapes), say so in the summary: `llm-mailroom` and the sandbox vendor snapshot
will need a coordinated bump.
