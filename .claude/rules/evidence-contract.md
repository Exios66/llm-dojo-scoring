# Evidence contract

**Nothing is "done", "fixed", "passing" or "working" until you hold evidence for it.**
This applies to the orchestrator, to every subagent report, to commit messages and to
PR descriptions. A claim without evidence is a guess; label it as one or drop it.

The Dojo defines what "correct" means for the whole constellation, so a wrong number here
becomes a wrong number in `llm-mailroom`, the sandbox and every report built on them.

## Rules

1. **Evidence is output, not prose.** Quote the command, its exit code and the lines that
   prove the claim (the pytest summary line, the ruff result, the golden diff). "Should
   work", "looks right" and "I believe" are not evidence.
2. **Evidence comes from the final state.** Commit the last edit (local commits need no
   request; pushing does), then re-run the gates on a clean tree (`git status --short`
   prints nothing). Name that commit (`git rev-parse --short HEAD`). Output from before a
   later change is stale.
3. **Prove the original problem is solved, not just that nothing broke.** For a bug, show
   a test that fails before the fix and passes after (red, then green). For a scoring
   change, show the scores before and after on concrete inputs.
4. **Say what you did not verify, and why.** Skipped tests (the shallow-clone release test,
   the `gh`-dependent publish test), optional extras you did not install, consumers you
   could not check. Never present one test file as the full suite.
5. **Re-verify subagent evidence.** The orchestrator re-runs at least the verification
   gates itself (or reads a `runner`'s raw output) before repeating any subagent claim.
6. **Never fabricate or "tidy" output.** Trimming is fine (mark it `…`); editing numbers,
   dropping failures or merging runs is not.

## What each kind of claim needs

| Claim | Evidence |
|:---|:---|
| Tests pass | `uv run --locked --extra dev pytest tests -q` summary line (`N passed, M skipped …`), exit code, commit. Name the skips. |
| Lint clean | `uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples` → `All checks passed!` (the version CI pins). The rule set is correctness-only (see `pyproject.toml`); do not claim more than it checks. |
| Type-checked | **No type checker is configured.** Say "not configured"; never claim "type-safe". |
| Bug fixed | The new or changed regression test, its failing output on the old code, its passing output on the new code. |
| Golden scores unchanged | `uv run --locked python scripts/freeze_goldens.py --check` → exit 0. This covers the frozen golden cases only: when scoring code changed, also name the affected metrics and whether the golden inputs exercise them; otherwise say "not covered by goldens". |
| Scoring intentionally changed | The `--check` diff before rewriting, `uv run python scripts/freeze_goldens.py --write --reason "…"`, a before/after table for the affected metrics, a `CHANGELOG.md` entry, and the consumer impact. |
| Public API unchanged / changed | `tests/test_consumer_compat.py` and `tests/test_public_api_doc.py` pass, and `git diff origin/<base>...HEAD -- llm_dojo_scoring/__init__.py tests/fixtures/consumer_surface.json docs/guides/PUBLIC_API.md` shows the surface change (empty for "unchanged"); for a change, `docs/guides/PUBLIC_API.md` updated and `scripts/audit_consumer_surface.py --check` run (it needs the consumer checkouts; exit 2 means one is missing, say so). |
| Legacy import paths still work | When a module moved, a test imports the old flat path (`llm_dojo_scoring.<old_name>`) and its previously exported names (`from llm_dojo_scoring.<old_name> import …`), and passes. |
| Release chain consistent | `python scripts/release.py check` → exit 0, plus every `WARN` line quoted (warnings do not fail the check). |
| Dependency change | `pyproject.toml` diff, `uv lock` re-run (never a hand-edited `uv.lock`), `uv lock --check` → exit 0, suite green with `uv sync --frozen`. |
| Docs are true | Every command you added was run (paste the result) or is marked unverified; every path, name and version you mention exists. |
| Visual change (README SVGs, `docs/assets/`, `visualize.py` / grid report output) | Before and after screenshots (Playwright, `deviceScaleFactor: 2`) of the rendered asset or report. |
| Cross-repo impact | Whether `llm-mailroom` (pin) and the sandbox (vendor snapshot) need a bump, and which public names changed. "None" is a claim too: say why. |

## Where evidence goes

- **Text** (test summaries, ruff, golden check, command output) goes in the PR description
  under "Evidence", inside `<details>` blocks for anything longer than ten lines. Use the
  template in `.github/pull_request_template.md`. Before pasting, remove tokens, keys,
  bearer headers, local paths and any real document text; if output cannot be shared
  safely, use synthetic input or list the item under "Not verified".
- **Screenshots and recordings:** save them under `.evidence/` (git-ignored); never commit
  binaries to the feature branch. They stay there until a PR was requested and has passed
  the pre-PR review (`.claude/rules/pr-flow.md` step 4). Then push them to the orphan
  branch `pr-evidence`, under `<feature-branch>/` (the literal branch name), and embed them
  with
  `![what it shows](https://github.com/Exios66/llm-dojo-scoring/blob/pr-evidence/<feature-branch>/<file>.png?raw=true)`,
  percent-encoding characters such as `#` (`%23`) and `%` (`%25`) in the URL.
  That branch is never merged; pushing evidence files there is allowed (the one exception to
  "push the designated branch only"). If it does not exist yet, create it on first use from a
  separate worktree: `tmp=$(mktemp -d) && git worktree add --detach "$tmp" && git -C "$tmp" switch --orphan pr-evidence`,
  then copy the files to `"$tmp/<feature-branch>/"`, `git -C "$tmp" add . && git -C "$tmp" commit -m "evidence: <feature-branch>"`
  and `git -C "$tmp" push -u origin pr-evidence`, then `git worktree remove "$tmp"`. If the
  branch already exists: `tmp=$(mktemp -d) && git fetch origin pr-evidence && git worktree add "$tmp" pr-evidence`,
  copy, commit, `git -C "$tmp" push origin pr-evidence` and `git worktree remove "$tmp"`. If the push is
  refused (cloud sessions are often limited to one branch), send the files to the user
  and list each file and what it shows under "Visual evidence" in the PR, marked
  "attached by hand". Never describe a screenshot you did not take.
- **Keep captures free of real documents.** This repo and its `pr-evidence` branch are
  public. Capture synthetic or sample data only, never real or client documents, names,
  tokens or local paths. If a surface cannot be shown that way, redact it and check the
  final image, or leave it out and say so under "Not verified". This covers files attached
  by hand too.
- **Final report to the user:** the same evidence, short. Lead with what was verified and
  what was not.
