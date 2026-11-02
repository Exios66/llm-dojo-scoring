<div align="center">

# 🧪 LLM Dojo Scoring Tests

**Test suites for the scoring engine package.**

</div>

---

## Running Tests

```bash
uv run --extra dev pytest tests/        # from the repository root
# or, after `pip install -e ".[dev]"`:
python -m pytest tests -q
```

> `tests/test_release_tools.py` runs `git log vX.Y.Z..HEAD`, so it needs tags and
> full history. In a shallow clone run `git fetch --unshallow --tags` first, or
> expect that one test to fail.

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
