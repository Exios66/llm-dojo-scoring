# Dojo releases (agent guide)

`scripts/release.py` is the in-house governor for cutting, noting, asset-building,
publishing, and editing llm-dojo-scoring GitHub releases. Prefer it over ad-hoc
`git tag` / `gh release` commands so the changelog ↔ tag ↔ package identity chain
stays honest and every release ships wheel + checksum + manifest assets (#92 B).

## Agent contract

- Mutating commands are **dry-run unless `--apply`**.
- Add `--json` for a stable plan/result object (`action`, `errors`, `next`, …).
- Exit `0` = success / clean dry-run; `1` = structural refusal; `2` = usage.
- Never force-push, never delete tags, never amend commits.
- Publish an already-merged cut with `--commit <merge-sha>` so the tag points at
  the immutable release commit even if the worktree has moved on.

## Commands

```bash
python scripts/release.py status --json
python scripts/release.py check --json

# Prepare a new version from [Unreleased] (writes only with --apply)
python scripts/release.py cut 0.26.0 --json
python scripts/release.py cut 0.26.0 --apply

# Render notes (CHANGELOG + merged PRs + key commits)
python scripts/release.py notes 0.25.0 --out /tmp/notes.md --json

# Build wheel/sdist + SHA256SUMS + release-manifest.json
python scripts/release.py assets 0.25.0 --commit <sha> --apply --json

# Tag + push + GitHub Release (+ assets). Dry-run first.
python scripts/release.py publish 0.25.0 --commit <sha> --json
python scripts/release.py publish 0.25.0 --commit <sha> --apply --push

# Edit an existing GitHub release title/notes/latest flag
python scripts/release.py edit 0.25.0 --title "Dojo v0.25.0: ..." --apply
```

## Cut surface

`cut` stamps `[Unreleased]` → `## [X.Y.Z] - DATE` and bumps:

| File | Field |
| --- | --- |
| `CHANGELOG.md` | dated section |
| `pyproject.toml` | `project.version` |
| `llm_dojo_scoring/__init__.py` | `__version__` |
| `README.md` | badge + install pins |
| `tests/test_consumer_compat.py` | release identity assert |

It warns (does not rewrite) when `tests/test_update_awareness.py` still mentions
the previous version — review those fixtures before merge.

## Publish surface

`publish` for an already-stamped version:

1. Verifies the target commit’s `pyproject` / `__init__` match `X.Y.Z` and that a
   CHANGELOG section exists.
2. Creates an annotated tag `vX.Y.Z` (`llm-dojo-scoring vX.Y.Z`) on `--commit`.
3. Pushes the tag when `--push` is set.
4. Builds wheel + sdist + `SHA256SUMS` + `release-manifest.json` unless `--no-assets`.
5. Creates the GitHub Release from the generated notes and uploads the assets.

## Identity checks

`check` fails when:

- `pyproject` and `__init__` disagree
- a local `v*` tag has no CHANGELOG section
- README release pins or the consumer-compat pin drift from `pyproject`
- CHANGELOG version sections are not strictly descending
- `pyproject` is behind the newest local version tag

Stamped-but-untagged sections are warnings (normal prep state).

## Template

`.github/RELEASE_TEMPLATE.md` is the only release-body layout. Edit the template,
never hand-type a published body. Regenerate with `notes` / `publish` / `edit`.
