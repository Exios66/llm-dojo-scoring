<div align="center">

# 🧪 LLM Dojo Scoring Tests

**Test suites for the scoring engine package.**

</div>

---

## Running Tests

```bash
uv run --locked --extra dev pytest tests -q -rs     # the full suite, from the repository root
uv run --locked --extra dev python scripts/ci.py --tier full    # every CI gate, in CI's order
uv run --locked --extra dev python scripts/ci.py --tier smoke   # ruff + the contract tests, seconds
```

> `tests/test_release_tools.py::test_notes_render_contains_changelog_and_commit` runs
> `git log vX.Y.Z..HEAD`, so it needs tags and full history; in a shallow clone it is
> skipped (`git fetch --unshallow --tags` lets it run). `test_cli_publish_dry_run_json`
> skips when the GitHub CLI or the network is unavailable.

## Test Structure

Tests cover:
- Field-type scoring
- Entity list scoring
- Regression diagnostics
- Factuality audit
- Intake normalization

## Related Files

- `llm_dojo_scoring/` — Source code
- `examples/` — Usage examples
- `docs/` — Documentation
