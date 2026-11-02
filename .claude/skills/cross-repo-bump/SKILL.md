---
name: cross-repo-bump
description: Walk a Dojo release or a public-API change through the coordinated bump across llm-dojo-scoring, llm-mailroom and local-mailroom-sandbox, checking the release chain and consumer compatibility first. Use when the user asks to cut or prepare a Dojo release, or when a change alters public names or ScoreRecord shapes.
disable-model-invocation: true
---

# cross-repo-bump

The Dojo is consumed by `llm-mailroom` (a git pin) and `local-mailroom-sandbox` (a tracked
vendor snapshot). A release here is therefore a three-repo event, in this order. Do only
the Dojo steps from this checkout and report the downstream steps as remaining work
unless the user asks to do them.

## 1. Dojo: prove the chain is consistent (read-only)

```bash
python scripts/release.py status
python scripts/release.py check
uv run --extra dev pytest tests/test_consumer_compat.py -q
```

`release.py check` errors when `pyproject` is behind the newest tag, or when the version,
`CHANGELOG.md`, README release pins and `tests/test_consumer_compat.py` disagree. In a
shallow clone fetch tags first: `git fetch --unshallow --tags`.

## 2. Dojo: plan the release (dry run)

```bash
python scripts/release.py cut X.Y.Z
```

`cut` is a dry run unless `--apply`. Show the plan to the user and **do not pass
`--apply`, `publish`, or `edit` without their explicit go-ahead**. Never force-push,
delete tags or amend release commits.

## 3. Downstream, after the release is merged and published

1. **llm-mailroom** — `PYTHONPATH=src python src/scripts/bump_dojo_scoring.py --check`,
   then `--apply --tag vX.Y.Z` (its `/dojo-bump` skill). Verify the suite against the
   exact pinned revision, not a local editable install.
2. **local-mailroom-sandbox** — update `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py`
   (tag plus commit SHA), then `sandbox fetch-deps` (its `/vendor-sync` skill). Its
   vendor drift tests compare against sibling checkouts, so refresh those too.

## 4. Report

State which steps are done, which remain, and which repo each belongs to. If the change
touched anything importable by the consumers (public names in `__init__.py`,
`field_scoring`, `ScoreRecord`), say so explicitly.
