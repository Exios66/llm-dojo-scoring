<div align="center">

# 📚 LLM Dojo Scoring Documentation

**Documentation for the scoring engine package.**

</div>

---

## Purpose

Documentation for the llm-dojo-scoring package, covering:
- Scoring methodology
- Field-type-aware scoring
- Entity list scoring
- Archive scoring block (`ARCHIVE_SCORING.md`)
- Scorecard honesty: MAUD GT, format vs extraction, completion/cost, confidence/reasoning knobs (`SCORECARD_HONESTY.md`)
- Hub ground-truth metadata: `gt_fields` parsing, `gt_presence`, per-class label scoping (`GT_METADATA.md`)
- MAUD answer-class catalogs: no-guess validity/scoring on merger agreements (`MAUD_LABELS.md`)
- Importable prompt catalog + frozen eval-environment v1 lineage (`PROMPTS.md`)
- Connected-repo TODOs for prompt mirrors, re-freeze scripts, and downstream imports (`TODOS.md`)
- Metric identity by doc class (`METRIC_IDS.md`)
- Specialist grid reports for local → Modal GPU studies (`GRID_REPORTS.md`)
- Issue-by-issue alignment status (`ISSUE_ALIGNMENT.md`)
- Regression diagnostics
- Factuality audit

## Related Files

- `README.md` — Package overview
- `llm_dojo_scoring/` — Source code
- `examples/` — Usage examples
