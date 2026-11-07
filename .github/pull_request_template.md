## Problem

<!-- The request, issue or task this PR answers. Link it. Quote the original ask if it came from a person. -->

## Change

<!-- What changed and why this approach. One concern per PR. -->

## Evidence

<!--
Proof that the change solves the problem above, taken on the final commit.
See .claude/rules/evidence-contract.md. Quote real output; trim with … ; long output in <details>.
-->

Commit: `<short sha>`

- **Tests:** `uv run --locked --extra dev pytest tests -q` → [summary line]
- **Lint:** `uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples` → [result]
- **Type check:** not configured in this repo
- **Golden scores:** `uv run --locked python scripts/freeze_goldens.py --check` → [exit 0, or the intended diff and the `--write --reason`]
- **Dependencies (dependency changes):** `uv lock --check` → [exit 0, or "not applicable"]
- **Regression test (bug fixes):** [test name] fails before, passes after
- **Score before / after (scoring changes):** [table, or "not applicable"]
- **Release chain (version / changelog work):** `python scripts/release.py check` → [result + WARN lines]
- **Visual (README / docs assets, report output):** [before / after screenshots, or "not applicable"]

<details><summary>Raw output</summary>

```text
```

</details>

## Not verified

<!-- What you could not check and why (shallow-clone skips, gh-dependent tests, consumer checkouts you did not have). "Nothing" is a claim too. -->

## Review log

<!-- Adversarial rounds (count, lens, findings, fixes) and the fresh pre-PR review verdict. See .claude/rules/orchestration.md. -->

- Adversarial review: [N] round(s) — [summary]
- Pre-PR review (fresh context): [READY / fixes applied]

## Public API and consumer impact

<!-- Names added, changed or removed (see docs/guides/PUBLIC_API.md). Does llm-mailroom's pin or the sandbox vendor snapshot need a bump? "None" and why. -->

## Checklist

- [ ] Evidence above was taken on the final commit
- [ ] Every behavior change has a test; no test was disabled, deleted or loosened
- [ ] Environment skips (shallow-clone release test, `gh`-dependent publish test) are named under "Not verified"
- [ ] Golden baseline unchanged, or rewritten with `--reason` for an intended score change
- [ ] Legacy flat import paths still work for any moved module
- [ ] `CHANGELOG.md` `[Unreleased]`, README and `docs/guides/` updated where behavior changed
- [ ] Versions and `uv.lock` not hand-edited
