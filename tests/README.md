<div align="center">

# 🧪 LLM Dojo Scoring Tests

**Test suites for the scoring engine package.**

</div>

---

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
# inside the Digital-Mailroom monorepo: uv run pytest packages/llm-dojo-scoring/tests
```

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
