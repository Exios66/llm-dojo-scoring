# Subagent orchestration

These rules govern how the main session delegates work. They apply to every task in
this repository. `AGENTS.md` points other agent tools here.

## Roles and model selection

Use the current session's provider and model for delegated work by default, including
implementation and review. Role names describe responsibilities, not model tiers.
User model choices override repository defaults. **Do not use Sonnet 4.6.**

Discover the live model catalog before selecting a model explicitly. Do not downgrade to
an older model because a role used to name a cheaper tier, or because another provider
fails. Stay with the current approved provider/model unless the user selects another.
The project agent briefs inherit the session model; use high reasoning effort for
implementation and review when the provider supports it.

| Role | Who | Use for |
|:---|:---|:---|
| Orchestrator | The main session | Plans the work, writes briefs, owns final verification, talks to the user. |
| `implementer` | `.claude/agents/implementer.md` | Features, bug fixes, refactors and investigations. |
| `runner` | `.claude/agents/runner.md` | Commands, data collection and mechanical work. |
| `adversarial-reviewer` | `.claude/agents/adversarial-reviewer.md` | Read-only attempts to break the change. |
| `pre-pr-reviewer` | `.claude/agents/pre-pr-reviewer.md` | Fresh-context review before pushing a PR. |

**Hard rules**

1. Model selection follows the user's current instructions, then the session default;
   project roles never force a provider or an older model. Check the selected model
   before dispatch, including when using a built-in agent rather than a project brief.
2. Match the brief to the work. If a runner task requires implementation judgement,
   re-brief it as implementer work; do not retry the same mechanical brief.
3. Do not delegate trivial lookups you can answer with one read or search. Each subagent
   starts cold and re-reads context, so delegation has a cost.
4. Run independent subagents in parallel and dependent ones in sequence.
5. Subagents never push, open PRs, comment on GitHub, publish, or write to hosted services.
   Those actions stay with the orchestrator.
6. Subagents that change files commit locally, one concern per commit with a message that
   says what and why (read-only reviewers commit nothing). Never rewrite pushed history;
   leave folding to the orchestrator, which squash-merges a feature or fix PR as one
   coherent commit; branch-sync and release PRs keep a merge commit
   (`.claude/rules/pr-flow.md` step 7).

## Writing a brief

A subagent sees only its brief, not this conversation. Scope and prepare every brief
for the circumstances. The `pre-pr-reviewer` is the exception: its brief is fixed by
`.claude/rules/pr-flow.md` step 3 and gets none of the context below. Every other brief
includes:

- **Goal:** the user's original request, quoted, plus the slice this subagent owns.
- **Context it cannot discover cheaply:** files and functions involved, decisions already
  made, constraints from `CLAUDE.md` that apply, what was already tried.
- **Boundaries:** files it may change, files it must not touch, commands it must not run.
- **Done means:** the acceptance check and the evidence it must return
  (see `.claude/rules/evidence-contract.md`).
- **Return format:** what changed (paths), commands run with exit codes and the key output
  lines, what it could not verify, open questions.

## Adversarial review (required)

Every change produced by subagents gets at least **one** adversarial review round before
the orchestrator verifies it, and at most **three**. Size the rounds to the work:

| Rounds | When |
|:---|:---|
| 1 | Up to about 100 changed lines in one area, including docs-only, test-only or mechanical changes of that size. |
| 2 | About 100 to 500 changed lines, several modules, or any behavior change. |
| 3 | More than about 500 lines; or a public API, cross-repo contract, scoring or metric change, release, migration, security- or secrets-sensitive change. |

Commit the subagent's work locally first (local commits need no request), so the count
and every review see the whole change; then count lines with `git diff --stat <base>...HEAD`,
after `git fetch origin <base>`. Size and risk both count: a large
docs-only change is not tier 1. When in doubt, pick the higher tier.

Each round is a **new** `adversarial-reviewer` instance (never resume a reviewer with
`SendMessage`), and each round has its own lens:

1. **Does it solve the problem?** Compare the result with the original request. Re-run
   the claimed evidence. Look for requirements that were skipped or quietly narrowed.
2. **What breaks?** Edge cases, error paths, regressions in callers, cross-repo
   contracts, config and docs that the change made stale.
3. **Try to break it.** Hostile inputs, concurrency, partial failure, the claims in the
   PR description and docs, anything that looks too easy.

Between rounds, send BLOCKING and MAJOR findings back to an `implementer` (or fix them
yourself if trivial), commit, then start the next round on the updated diff. After the
last round of the tier (round 1 for a one-round change), every BLOCKING finding is either
fixed and verified by you, or you stop and report it to the user as unresolved; do not
start a fourth round, and do not leave it for the pre-PR review to find.
Record every round (lens, findings, what was fixed) for the PR's "Review log".

## Orchestrator verification (required)

Subagent reports are claims, not evidence. Before you tell the user anything is done:

- read the full diff yourself;
- re-run the verification gates from `CLAUDE.md` on the final state of the branch
  (delegating the run to a `runner` is fine; reading its raw output is not optional);
- check each item of `.claude/rules/evidence-contract.md` against what you hold.

Then, if the user asked for a pull request, follow `.claude/rules/pr-flow.md` to open it.
