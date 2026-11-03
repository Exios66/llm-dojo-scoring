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

`release.py check` exits non-zero only on **errors**: `pyproject` and `__init__` versions
disagree, `pyproject` is behind the newest tag, README release pins or
`tests/test_consumer_compat.py` disagree with `pyproject`, or `CHANGELOG.md` sections are
non-semver, duplicated or out of order. A tag with no `CHANGELOG.md` section, a stamped
section with no local tag, and lightweight or oddly worded tags are only **warnings**
(`WARN` lines, exit 0). A green check therefore does not prove every tag and changelog entry
match: read the `WARN` lines and report them. In a shallow clone fetch tags first:
`git fetch --unshallow --tags`.

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
2. **local-mailroom-sandbox** — its `/vendor-sync` skill. Set `ref` and `sha` for
   `llm-dojo-scoring` in `_VENDOR_PINS` (`src/mailroom_sandbox/cli.py`) to the tag and its
   peeled commit. Then refresh `vendor/llm-dojo-scoring`:
   - in the monorepo, import the merged Dojo revision into `../../packages/llm-dojo-scoring`
     first (its `HEAD` must equal the pinned SHA), then
     `python scripts/sync_vendor.py llm-dojo-scoring`;
   - standalone, `sandbox fetch-deps` (SHA-checked, but it refreshes **both** pins, so
     confirm only `vendor/llm-dojo-scoring` changed).
   Update `vendor/README.md` and `vendor/llm-dojo-scoring/VENDOR.md`. Its drift test
   compares against the sibling `../llm-dojo-scoring` at the pinned commit, so fetch that
   commit there too.

## 4. Report

State which steps are done, which remain, and which repo each belongs to. If the change
touched anything importable by the consumers (public names in `__init__.py`,
`field_scoring`, `ScoreRecord`), say so explicitly.
