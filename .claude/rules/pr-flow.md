# Pull request flow

Bot reviewers (CodeRabbit, CodeAnt) should spend their attention on real bugs, not on
mistakes we could have caught ourselves. So **nothing is pushed for review until it has
been vetted locally and by a fresh-context reviewer.** Run these steps in order. Steps 4
and 5 (pushing, opening and updating a PR) happen only when the user asked for a pull
request; otherwise stop after step 3 and report the result with its evidence. A local
commit needs no request; leave changes you did not make (the user's own edits) out of
your commits and out of the gate, and say they exist in the report.

`<base>` below is the branch the PR targets (`main` unless the user names another), fetched
fresh: `git fetch origin <base>`.

## 1. Local gate (before any push)

On the final state of the branch, run the gates that match the change (see "Verification
gates" in `CLAUDE.md` and `.claude/rules/evidence-contract.md`) and keep the raw output.
At minimum:

```bash
git status --short                                         # prints nothing: commit your changes first
git fetch origin <base>
git diff origin/<base>...HEAD --stat                       # the diff is the size you expect
uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples   # the CI lint gate
uv run --locked --extra dev pytest tests -q                # full suite, under a minute
uv run --locked python scripts/freeze_goldens.py --check   # scores unchanged (or intentionally rewritten)
uv lock --check                                            # uv.lock agrees with pyproject.toml
```

Add `python scripts/release.py check` for version or changelog work. A red gate stops the
flow; fix it first.

## 2. Self-review checklist

Read your own diff top to bottom before handing it to a reviewer:

- No debug prints, commented-out code, stray TODOs, local paths, secrets or `.env` values.
- No unrelated changes (formatting churn, drive-by renames). One concern per PR.
- Every behavior change has a test; every bug fix has a regression test.
- Moved or renamed modules still import through their legacy flat path (`_layout.py`).
- Public names in `__init__.py` and `docs/guides/PUBLIC_API.md` agree.
- `CHANGELOG.md` (`[Unreleased]`), README, `docs/guides/`, `docs/contracts/` and docstrings
  match the new behavior. Counts, versions and paths named in prose are still true.
- Cross-repo effects are noted (see "Constellation" in `CLAUDE.md`).

## 3. Fresh-context pre-PR review (required)

Dispatch a **new** `pre-pr-reviewer` subagent for every PR, and a new one again after
any non-trivial fix. Never reuse a reviewer that saw the implementation (no `SendMessage`
to an earlier reviewer, no fork): its context is the thing we are trying to avoid.

Give it only:

- the user's original request, quoted;
- the base ref and branch name (`origin/<base>...HEAD`);
- the draft PR description with its evidence section, but without its review log
  (screenshots stay in `.evidence/` at this point; give it the local paths);
- the gate commands you ran and their exit codes.

Do **not** give it the implementer's reasoning or the adversarial-review history; it must
judge the diff as a stranger would. Fix every BLOCKING and MAJOR finding, then re-run the
local gate. If the fixes were more than trivial, dispatch another fresh `pre-pr-reviewer`
(at most two passes; then escalate to the user).

## 4. Push and open a draft PR (only when the user asked for a PR)

- Push the designated branch only (`git push -u origin <branch>`): the feature branch the
  user named or the session was started on. Never force-push, delete tags or amend release
  commits.
- Only now, after the pre-PR review and the privacy check in
  `.claude/rules/evidence-contract.md`, push screenshots from `.evidence/` to the
  `pr-evidence` branch and embed them.
- Open the PR **as a draft**, filled in from `.github/pull_request_template.md`: problem,
  change, evidence, what was not verified, review log, cross-repo impact.
- Mark it ready only when every evidence item is present and CI (`ci/circleci: test`) is
  green on the pushed commit.

## 5. Handling bot and human review

- Treat each comment as a claim to verify, not an order. Reproduce it against the code.
- **Valid:** fix it with a test where possible, then before each push re-run the local
  gate (step 1) on the new commit and update the PR's "Commit:" line and evidence to it.
  Push, and reply with what changed and the evidence.
- **Not valid:** reply with the file and line or the output that shows why. Do not
  "fix" correct code to quiet a bot.
- **Out of scope:** say so and propose a follow-up issue; do not grow the PR.
- After CI goes red, reproduce the failure locally first, then fix it. Never skip,
  disable or loosen a test, and never rewrite a golden baseline, to get green.

## 6. Close the loop

When a bot finds a careless mistake that steps 1 to 3 should have caught, add one line
to "Lessons from bot reviews" in `.claude/agents/pre-pr-reviewer.md` in the same PR, so
the next fresh reviewer checks for it.
