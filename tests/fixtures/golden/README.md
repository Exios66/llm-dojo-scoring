# Golden scoring baseline (issue #67)

This fixture pins the current scoring output for **every task key** in
`llm_dojo_scoring.config.TASK_KINDS` (22 today) and **every live suite** from
`list_suites(live_only=True)` (21 today). It is a regression baseline, not a
claim that the numbers are ideal.

- `inputs.json` is hand-authored, deterministic, and small (2–4 rows per case).
- `scores.json` is generated and committed. Do not edit it by hand.
- `scripts/freeze_goldens.py` is the only writer.
- `tests/test_golden_scores.py` reads both files, recomputes in memory, and
  compares canonical JSON. It never rewrites the fixture.

## Coverage

Task cases include the `chained` guard (`score_task(..., "chained")` must raise
`ValueError`) plus `chained_summary(...)`, hierarchical `docclass` and
`pipeline` subclass cases, and one `ERROR:` prediction. Extraction suites
record both `score(...)` and the provenance-bearing `score_document(...)`.

`reporter`, `boss`, and `archivist` are emit-only. They are recorded as:

```json
{
  "computable": false,
  "kind": "reporter",
  "score_raises": "TypeError",
  "metric_names": ["..."]
}
```

Their `TypeError` refusal is asserted; no score is fabricated.

## Canonical form

`scripts/freeze_goldens.py` recursively canonicalizes values:

- dataclasses use `.to_dict()` (or their fields as a fallback);
- sets/frozensets and non-finite floats are rejected;
- `None` and `0.0` remain distinct;
- output is `json.dumps(sort_keys=True, indent=2, ensure_ascii=False,
  allow_nan=False)` plus one trailing LF.

Only `provenance.scorer_version` is masked, with `"<SCORER_VERSION>"`, so a
package version bump is not a scoring change. The test separately asserts the
unmasked value equals `SCORER_VERSION`.

## Defaults

The collector and tests clear `load_settings`' cache and require
`field_scoring.ambiguous_band == (0.5, 0.85)`. Freezing refuses to run when
`LLM_DOJO_SCORING_CONFIG` points at an existing file or when the cached band is
non-default.

## Check and regenerate

Check mode is the default and exits 1 with a unified diff on drift:

```bash
uv run --python 3.12 python scripts/freeze_goldens.py --check
```

After an intentional scoring change, rewrite and prove idempotence:

```bash
uv run --python 3.12 python scripts/freeze_goldens.py --write \
  --reason "Describe the intentional scoring change"
```

The script writes `scores.json`, re-collects immediately, and fails if the
second collection differs. The reason is printed for the review trail.

## Drift guard

Adding a `TASK_KINDS` key or a live suite without adding its case to
`inputs.json` fails `test_every_task_kind_has_a_golden_case` /
`test_every_live_suite_has_a_golden_entry`; missing cases are never skipped.
