# Unlabelled-value grounding — piece 1 (verdicts and rate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every value an extractor states on a field the ground truth does not label,
decide `grounded` / `not_found` / `unverifiable` against the source document, and report
an unlabelled-value hallucination rate per run, class and field. The headline scores
must not move.

**Architecture:** A new subpackage, `llm_dojo_scoring/grounding/`, that callers run as
their own pass after scoring. It has four single-purpose modules:

| Module | Job |
|:--|:--|
| `verdicts` | checks one value against the document text |
| `selection` | decides which fields are unlabelled |
| `audit` | turns each unlabelled value into a record |
| `summary` | turns records into rates and `ScoreRecord`s |

`selection` uses the headline's own scoping function, `scoring_gt_fields`, so the
headline and this pass can never count the same value. Nothing on the scoring path
imports `grounding/`.

**Tech Stack:** Python 3.11, stdlib dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-14-unlabelled-value-grounding-design.md`.
This plan implements §6.2 and §7. The layout and names are fixed by §11, and the order
of work across repos by §12. Pieces 2 and 3 get their own plans after this piece lands.

**Tracker:** the master tracker issue on `Exios66/llm-dojo-scoring` (linked from the
spec's §12 once opened).

## Global Constraints

- **Release:** ships in **0.31.0**, after v0.30.0 is cut (spec §12, step 1).
  - The branch is stacked on `origin/v0.30.0` and is never merged into it.
  - Changelog entries go under `## [Unreleased]` → `### Added`, in a block that opens
    with `<!-- 0.31.0: unlabelled-value grounding -->`.
  - Do not touch versions.
- **Layout and names:** exactly as in spec §11. Each subpackage `__init__.py` holds a
  one-line docstring and nothing else. New code imports from subpackage paths
  (`from ..schemas.gt_metadata import …`).
- **No side effects:** the Dojo makes no LLM calls, opens no network connection, writes
  no files and stores no document text. Records carry `doc_text_sha256` instead.
- **Anti-goal:** none of these may change:
  - `overall_score`, field-micro, class headlines and `metric_id` resolution;
  - `entity_list_audit` and `extraction_hallucination_rate`;
  - the golden baseline (`freeze_goldens.py --check` must exit 0).
- **Audited set** (owner decision, spec §10.1). A predicted field is audited only when
  all of these hold:
  - it is in `doc_classes.field_types(doc_class)`;
  - its predicted value is not empty (`is_empty_value` is false);
  - its key is missing from `scoring_gt_fields(gt_row, field_types=…, doc_type=doc_class, subclass=doc_subclass)`.

  A blank GT value with no presence status is not audited. On a CMS row (the scoped dict
  carries `cms_source_table`), `adjuster` and `denial_reasons` are never audited.
- **Fixed string values:**
  - verdicts: `"grounded"`, `"not_found"`, `"unverifiable"`;
  - `gt_status`: `"absent"`, `"pending_annotation"`;
  - every record carries `"schema_version": 1` in its `as_dict()`.
- **Metric ids** (spec §11):
  - `grounding_not_found_rate`: tier 1, `float[0,1]`, `aggregation: none`;
  - `grounding_unverifiable_rate`: tier 2, `float[0,1]`, `aggregation: none`;
  - `grounding_n_audited`: tier 3, `count`, `aggregation: sum`.

  All three have `applicable_agents: [SPECIALISTS]`. A rate whose denominator is 0 is
  `None`, never `0.0`.
- **Coverage threshold:** `get_verification_coverage()` (default 0.7). This piece adds no
  new settings.
- **Commits** use the repository's local git identity, unsigned, with no Claude trailers.
- **Gates:**
  - `uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples`
  - `uv run --locked --extra dev pytest tests -q`
  - `uv run --locked python scripts/freeze_goldens.py --check`
  - `uv lock --check`
  - `python scripts/release.py check` (quote its WARN lines)

## Review Focus

1. **A value reformatted from the text must be `grounded`, not `not_found`.** Examples:
   `"$1,250.00"` against "1250 dollars", and `"AB-12/34"` against "ab 12 34". Pinned in
   Task 1.
2. **A real Hub row** (every text column `""`, no `gt_presence`) must audit nothing.
   Otherwise every field is audited and the rate is noise. Pinned in Task 2.
3. **Missing document text** (`None`, `""` or whitespace) gives `unverifiable` and a
   `None` rate. It must not give 0.0 and must not raise. Pinned in Tasks 1 and 3.
4. **A stringified list prediction** (`'["Acme", "Beta"]'`) is split into items. It must
   not be audited as one string. Pinned in Task 2.
5. **An unknown `doc_class`** raises the registry's `KeyError`. It must not quietly audit
   nothing. Pinned in Task 2.

---

### Task 1: `grounding/verdicts.py` — one value against the document

**Files:**
- Create: `llm_dojo_scoring/grounding/__init__.py`. Its whole content is the docstring
  `"""Unlabelled-value grounding: verdicts, rates, review candidates and label provenance."""`.
- Create: `llm_dojo_scoring/grounding/verdicts.py`
- Create: `tests/grounding/conftest.py`, with a fixture `doc_text` returning
  `"Invoice AB-12/34 dated March 3, 2024 from Acme Holdings for 1250 dollars."`
- Test: `tests/grounding/test_grounding_verdicts.py`

**Interfaces:**
- Consumes, from `..scoring.field_scoring`:
  - `_containment_tokens(text) -> set[str]`
  - `_parse_date_parts(text) -> _DateParts | None`
  - `_date_grounded_in_doc(pred_date, doc_text) -> bool`
  - `_parse_money(text) -> float | None`
  - `get_verification_coverage() -> float`
- Produces:
  - `GROUNDED`, `NOT_FOUND`, `UNVERIFIABLE`: `str` constants.
  - `VERDICTS: tuple[str, ...]`: the three verdicts, in that order.
  - `value_verdict(field_type: str, value: Any, doc_text: str | None) -> tuple[str, float | None]`:
    - returns `(verdict, coverage)`;
    - `coverage` is the token share for `name` and `free_text`, and `None` otherwise;
    - accepts the scalar types `name`, `free_text`, `date`, `money`, `id`, `label` and
      `cms_doc_ref`;
    - any other type uses the `name` rule.
  - The per-type rules live in a module-level dispatch dict, `_RULES: dict[str, Callable[[Any, str], tuple[str, float | None]]]`,
    so a new type is a single new entry (spec §11, extension points).

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize(("ftype", "value", "expected"), [
    ("name", "Acme Holdings", "grounded"),
    ("name", "Globex Corporation", "not_found"),
    ("free_text", "invoice from Acme", "grounded"),
    ("date", "2024-03-03", "grounded"),
    ("date", "2024-03-04", "not_found"),
    ("money", "$1,250.00", "grounded"),
    ("money", "$9,999", "not_found"),
    ("money", "about a thousand", "unverifiable"),
    ("id", "ab 12 34", "grounded"),
    ("id", "AB-99", "not_found"),
    ("cms_doc_ref", "AB1234", "grounded"),
    ("label", "invoice", "unverifiable"),
    ("name", "!!!", "unverifiable"),
])
def test_value_verdict_by_field_type(doc_text, ftype, value, expected):
    assert value_verdict(ftype, value, doc_text)[0] == expected

@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_document_text_is_unverifiable(missing):
    assert value_verdict("name", "Acme", missing) == ("unverifiable", None)

def test_name_coverage_is_reported(doc_text):
    assert value_verdict("name", "Acme Globex", doc_text) == ("not_found", pytest.approx(0.5))

def test_verdicts_constant_lists_every_outcome():
    assert VERDICTS == ("grounded", "not_found", "unverifiable")
```

- [ ] **Step 2: Run the tests and watch them fail.**
  `uv run --extra dev pytest tests/grounding/test_grounding_verdicts.py -q`
  Expected: an `ImportError` on `llm_dojo_scoring.grounding.verdicts`.
- [ ] **Step 3: Implement the rules.**
  - **`name` / `free_text`:** take the share of the value's `_containment_tokens` that
    appear in the document's tokens. `grounded` when the share is at least
    `get_verification_coverage()`, else `not_found`. If the value has no tokens:
    `unverifiable`.
  - **`date`:** `_parse_date_parts`, then `_date_grounded_in_doc`. If the value does not
    parse, use the `name` rule.
  - **`money`:**
    - Parse the value with `_parse_money`. If that fails: `unverifiable`.
    - Find the document's amounts with `_MONEY_RE = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?(?:\s*[KMB]\b)?")`,
      parsing each match with `_parse_money`.
    - `grounded` when any document amount is within 0.005 of the value.
  - **`id` / `cms_doc_ref`:** casefold, then strip whitespace and `-`, `/`, `.` from
    both the value and the document. `grounded` when the value is a substring of the
    document.
  - **`label`:** always `unverifiable`.
  - **Document text that is missing or blank:** `("unverifiable", None)`, before any rule
    runs.
- [ ] **Step 4: Run the tests and watch them pass.** Same command as Step 2.
- [ ] **Step 5: Commit.**
  `feat(grounding): per-type value verdicts against the source document`

### Task 2: `grounding/selection.py` and `grounding/audit.py` — which values, and their records

**Files:**
- Create: `llm_dojo_scoring/grounding/selection.py`
- Create: `llm_dojo_scoring/grounding/audit.py`
- Modify: `tests/grounding/conftest.py`
  - Add a `hub_row(**labels) -> str` helper and a `with_presence(gt_fields, field, status) -> str`
    helper.
  - Copy their bodies from `tests/behavior/test_class_headline_contract.py:49-62` and
    `:205-210`. Copy them; do not import across test modules.
- Test: `tests/grounding/test_grounding_selection.py`
- Test: `tests/grounding/test_grounding_audit.py`

**Interfaces:**
- Consumes:
  - `value_verdict`, `UNVERIFIABLE` (Task 1)
  - from `..schemas.gt_metadata`: `scoring_gt_fields`, `gt_presence_map`,
    `parse_gt_fields`, `is_empty_value`, `parse_json_container`, `CMS_SOURCE_TABLE_KEY`
  - from `..schemas.doc_classes`: `field_types`
  - from `..schemas.corpus`: `CMS_DOCUMENTED_ABSENT_FIELDS`
  - from `..scoring.field_scoring`: `is_entity_list`
- Produces, in `selection.py`:
  - `UNLABELLED_STATUSES: tuple[str, ...] = ("absent", "pending_annotation")`
  - `unlabelled_fields(gt_row, predicted: Mapping[str, Any], *, doc_class: str, doc_subclass: str | None = None) -> dict[str, str]`
    maps each audited field to its `gt_status`. Fields come in
    `field_types(doc_class)` order.
- Produces, in `audit.py`:
  - `@dataclass(frozen=True) class UnlabelledValueAudit` with these fields:
    - `run_id: str | None`
    - `doc_id: str | None`
    - `doc_class: str`
    - `doc_subclass: str | None`
    - `field: str`
    - `field_type: str`
    - `value: Any`
    - `item_index: int | None`
    - `verdict: str`
    - `coverage: float | None`
    - `gt_status: str`
    - `doc_text_sha256: str | None`
    - `extractor: str | None`
    - `audited_at: float`

    It also has `as_dict() -> dict` (which includes `"schema_version": 1`) and the
    classmethod `from_dict(data) -> UnlabelledValueAudit`.
  - `audit_unlabelled_values(gt_row, predicted: Mapping[str, Any], *, doc_class: str, doc_text: str | None, doc_subclass: str | None = None, run_id: str | None = None, doc_id: str | None = None, extractor: str | None = None) -> list[UnlabelledValueAudit]`:
    - A list field (`is_entity_list`) gives one record per non-empty item, with
      `item_index` set. The items are parsed with `parse_json_container`, and the item
      type is the suffix after `entity_list:` (`name` if there is none).
    - A scalar gives one record with `item_index=None`.
    - `doc_text_sha256` is `hashlib.sha256(doc_text.encode("utf-8")).hexdigest()`, or
      `None` when there is no document text.

- [ ] **Step 1: Write the failing tests.**
  - In `test_grounding_selection.py`:
    - `test_real_hub_row_with_blank_columns_selects_nothing`: `hub_row()` with a
      prediction that fills several fields gives `{}`.
    - `test_pending_annotation_is_selected_as_pending`
    - `test_key_missing_from_gt_is_selected_as_absent`: the GT is a plain dict.
    - `test_labelled_empty_statuses_are_not_selected`: `not_applicable` and
      `schema_documented_absence`.
    - `test_labelled_value_is_not_selected`
    - `test_cms_documented_absent_fields_never_selected`, parametrized over `adjuster`
      and `denial_reasons`:
      - a CMS `insurance_claim` row with the field pending gives `{}`;
      - a non-CMS insurance row gives `{field: "pending_annotation"}`.
    - `test_empty_predictions_and_off_schema_keys_not_selected`: `""`, `None`, `[]` and
      `"[]"`.
    - `test_unknown_doc_class_raises_key_error`
  - In `test_grounding_audit.py`:
    - `test_stringified_list_audited_item_by_item`:
      `parties='["Acme Holdings", "Globex"]'` gives two records, with `item_index` 0
      and 1 and verdicts `grounded` and `not_found`.
    - `test_scalar_record_carries_status_and_verdict`
    - `test_record_carries_hash_not_text`: `doc_text_sha256` matches, and the document
      text appears nowhere in `json.dumps(record.as_dict())`.
    - `test_record_round_trips_through_dict`: `from_dict(as_dict())` equals the
      original, and `as_dict()["schema_version"] == 1`.
- [ ] **Step 2: Run the tests and watch them fail.**
  `uv run --extra dev pytest tests/grounding -q`
- [ ] **Step 3: Implement `unlabelled_fields`.**
  - Call `scoring_gt_fields` once, with `field_types=field_types(doc_class)`.
  - Read the raw presence status with `gt_presence_map(parse_gt_fields(gt_row))`.
  - Apply the CMS exclusion when the scoped dict has a non-empty `CMS_SOURCE_TABLE_KEY`.
- [ ] **Step 4: Implement `audit_unlabelled_values`.** Build on `unlabelled_fields` and
  `value_verdict`. Do not reimplement the selection rule.
- [ ] **Step 5: Run the tests and watch them pass.**
- [ ] **Step 6: Commit.**
  `feat(grounding): select unlabelled values with the headline's own scoping and audit them`

### Task 3: `grounding/summary.py` — rates, breakdowns, ScoreRecords, registry

**Files:**
- Create: `llm_dojo_scoring/grounding/summary.py`
- Modify: `llm_dojo_scoring/metrics/registry.py`. Add the three entries right after
  `extraction_hallucination_rate`:
  - `source: "grounding.summary.summarize_grounding"`;
  - `ground_truth: required`;
  - `notes:` "unlabelled fields only; distinct from extraction_hallucination_rate, which
    mixes labelled and unlabelled values".
- Test: `tests/grounding/test_grounding_summary.py`

**Interfaces:**
- Consumes:
  - `UnlabelledValueAudit` (Task 2)
  - `ScoreRecord` from `..metrics.emitter`
- Produces:
  - `@dataclass(frozen=True) class GroundingCounts(grounded: int = 0, not_found: int = 0, unverifiable: int = 0)`,
    with these properties:
    - `n_audited`: the sum of the three counts;
    - `not_found_rate`: `not_found / (grounded + not_found)`, or `None` when that is 0;
    - `unverifiable_rate`: `unverifiable / n_audited`, or `None` when that is 0.
  - `@dataclass(frozen=True) class GroundingSummary` with these fields:
    - `overall: GroundingCounts`
    - `by_class: dict[str, GroundingCounts]`
    - `by_field: dict[tuple[str, str], GroundingCounts]`, keyed by
      `(doc_class, field)`

    Its `as_dict()` writes the field keys as `"doc_class.field"` and includes
    `"schema_version": 1`.
  - `summarize_grounding(audits: Iterable[UnlabelledValueAudit]) -> GroundingSummary`
  - `grounding_score_records(summary: GroundingSummary, *, agent: str, run_id: str | None = None) -> list[ScoreRecord]`:
    - The order is: the three metrics for the whole run (`metadata={"scope": "run"}`),
      then each class (`{"scope": "class", "doc_class": …}`), then each field
      (`{"scope": "field", "doc_class": …, "field": …}`).
    - Every record's `metadata` also has `"denominator"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_not_found_rate_excludes_unverifiable`: counts of 3 grounded, 1 not_found and
    4 unverifiable give a rate of 0.25, an unverifiable rate of 0.5 and an
    `n_audited` of 8.
  - `test_rates_are_none_without_a_denominator`: an empty list, and a list where every
    value is unverifiable, give a `not_found_rate` of `None` (Review Focus 3).
  - `test_breakdowns_add_up_to_the_overall_counts`: two classes and three fields.
  - `test_score_records_use_registered_ids_and_tiers`: each `record.metric` is in
    `get_registry().names()`, and its tier matches Global Constraints.
- [ ] **Step 2: Run the tests and watch them fail.**
- [ ] **Step 3: Implement the summary, the records and the registry entries.**
- [ ] **Step 4: Run the tests and watch them pass.**
  `uv run --extra dev pytest tests/grounding tests/test_registry.py tests/test_metric_id_strict.py -q`
- [ ] **Step 5: Commit.**
  `feat(grounding): unlabelled-value rates as non-headline ScoreRecords`

### Task 4: Isolation proof, closure hold, contract, docs

**Files:**
- Test: `tests/grounding/test_grounding_isolation.py`
- Modify: `scripts/consumer_closure.py`. Add this to `HOLD`:
  `"grounding": "unlabelled-value grounding (0.31.0); mailroom wiring follows, see the tracker issue"`
- Modify: `docs/analysis/data/consumer_closure.json`. Regenerate it with the script;
  never edit it by hand.
- Create: `docs/contracts/GROUNDING.md`. Mirror the section order of
  `docs/contracts/REVIEWER_SCORING.md`:
  - purpose;
  - what is audited, and why it cannot overlap the headline;
  - the verdict table by field type;
  - the metric ids, and how they differ from `extraction_hallucination_rate`;
  - the record schema (`schema_version` 1);
  - a usage example that you run and whose real output you paste;
  - a short "Pieces 2 and 3" stub that points to the spec.
- Modify: `llm_dojo_scoring/README.md`. Add a `grounding/` row to the module table.
- Modify: `AGENTS.md`. Add a "Package layout" row for `grounding/`, and list
  `GROUNDING.md` under "Documentation layout".
- Modify: `CHANGELOG.md`. Add the entry inside the 0.31.0 block from Global Constraints.

**Interfaces:** none new.

- [ ] **Step 1: Write the tests.**
  - `test_scoring_path_never_imports_grounding`:
    - In `subprocess.run([sys.executable, "-c", …], check=True)`, import
      `llm_dojo_scoring`, `llm_dojo_scoring.scoring.suites`,
      `llm_dojo_scoring.scoring.field_scoring` and `llm_dojo_scoring.metrics.emitter`.
    - Then print every `sys.modules` key that starts with `llm_dojo_scoring.grounding`,
      and assert the output is empty.
  - `test_auditing_leaves_extraction_scores_unchanged`:
    - Score a `hub_row` that has a pending field, with `score_extraction` /
      `get_suite`, the same way `tests/behavior/test_class_headline_contract.py`
      does.
    - Run `audit_unlabelled_values` on the same inputs.
    - Score again, and assert both `to_dict()` results are equal.
- [ ] **Step 2: Run the tests.** `uv run --extra dev pytest tests/grounding -q`.
  Both should pass. If the first fails, an import leaked into the scoring path: remove
  the import, and do not weaken the test.
- [ ] **Step 3: Add the `HOLD` entry and regenerate the closure data.**
  - Run `uv run python scripts/consumer_closure.py --mailroom ../llm-mailroom --sandbox ../exios66/local-mailroom-sandbox --extra-ref origin/claude/howdy-n8vcc1 --extra-ref origin/stack/01-audit-storage --extra-ref origin/stack/02-diagnostics-workbench --extra-ref origin/stack/03-audit-live-row --extra-ref origin/claude/vibrant-sagan-fltg8i --extra-ref origin/claude/vibrant-sagan-fltg8i-scoring-fixes --write`.
    The extra refs cover the open mailroom PRs #222, #226, #227, #229, #230 and #231.
  - Then run the same command with `--check`. It should exit 0.
  - If it exits 2 because a ref is missing, fetch that ref in `../llm-mailroom`. If it
    still fails, stop and report. Never drop a ref to get green.
- [ ] **Step 4: Write the contract, the README row, the AGENTS rows and the changelog
  entry.** Run the contract's usage example and paste its real output.
- [ ] **Step 5: Run the full local gate on a clean tree.** Expect:
  - ruff prints `All checks passed!`;
  - the pytest summary has no failures, and its skips are named;
  - the golden check exits 0;
  - `uv lock --check` exits 0;
  - `release.py check` exits 0, with its WARN lines quoted.
- [ ] **Step 6: Commit.**
  `docs(grounding): isolation tests, closure hold, contract and 0.31.0 changelog`

## After the tasks (orchestrator)

1. Run `git diff --stat origin/v0.30.0...HEAD`.
2. Run three adversarial rounds: lenses 1, 2 and 3, because this adds new metrics. Fix
   every BLOCKING and MAJOR finding between rounds.
3. Re-run the gates yourself.
4. Run a fresh `pre-pr-reviewer` (`.claude/rules/pr-flow.md` step 3).
5. Tick piece 1 on the tracker issue. Push only the session branch. Open a draft PR only
   when the user asks for one.
