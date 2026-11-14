# Unlabelled-value grounding — piece 1 (verdicts and rate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every value an extractor states on a field the ground truth does not label,
decide `grounded` / `not_found` / `unverifiable` against the source document, and report
an unlabelled-value hallucination rate per run, class and field. The headline scores
must not move.

**Architecture:** A new subpackage, `llm_dojo_scoring/grounding/`, run by the caller as
its own pass after scoring. Which fields count as "unlabelled" is decided by the
headline's own scoping function, `scoring_gt_fields`, so the two calculations are
disjoint by construction. The checks reuse the matchers in `scoring/field_scoring.py`.
Nothing in `scoring/`, `metrics/emitter.py` or the package root imports `grounding/`.

**Tech Stack:** Python 3.11, stdlib dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-14-unlabelled-value-grounding-design.md`
(§6.1, §6.2, §7 and §10 for this piece). Pieces 2 (candidates, ledger, provenance) and
3 (agreement, trust gate) get their own plans once this piece has landed.

## Global Constraints

- **Release:** this ships in **0.31.0**, as a follow-up to the v0.30.0 release. The
  branch is stacked on `origin/v0.30.0`, but it is **not merged into `v0.30.0`**. The
  changelog entries go under `## [Unreleased]`, in a block headed
  `<!-- 0.31.0: unlabelled-value grounding -->`. The work lands only after 0.30.0 has
  been cut, so `release.py cut 0.31.0` picks those entries up. Do not touch versions.
- The Dojo makes no LLM calls, opens no network connection, writes no files and stores
  no document text. Each record carries `doc_text_sha256` instead.
- Anti-goal: no change to `overall_score`, field-micro, class headlines, `metric_id`
  resolution, `entity_list_audit`, `extraction_hallucination_rate` or the golden
  baseline. `freeze_goldens.py --check` exits 0, unchanged.
- **What is audited** (owner decision, §10.1). A predicted field is audited only when:
  - it is in `doc_classes.field_types(doc_class)`;
  - its predicted value is not empty (`is_empty_value` is false);
  - its key is **missing** from `scoring_gt_fields(gt_row, field_types=…, doc_type=doc_class, subclass=doc_subclass)`.

  That missing key means the GT never had the key, or its presence status is
  `pending_annotation`. A blank GT value with no status is labelled empty and is
  **not** audited. On a CMS row (the scoped dict carries `cms_source_table`),
  `adjuster` and `denial_reasons` are labelled empty and **never** audited, whatever
  their status.
- Verdict values are exactly `"grounded"`, `"not_found"` and `"unverifiable"`.
  `gt_status` values are exactly `"absent"` and `"pending_annotation"`.
- **Metric ids** follow the registry's snake_case convention. These replace the spec's
  dotted placeholders:
  - `unlabelled_not_found_rate` (tier 1, `float[0,1]`);
  - `unlabelled_unverifiable_share` (tier 2, `float[0,1]`);
  - `unlabelled_audited_count` (tier 3, `count`).

  All three are `aggregation: none` (they are pooled at run level) and
  `applicable_agents: [SPECIALISTS]`. A rate is `None`, never `0.0`, when its
  denominator is 0.
- Coverage threshold: `get_verification_coverage()` (config
  `field_scoring.verification_token_coverage`, default 0.7). No new settings in this piece.
- Commits use the repository's local git identity, unsigned, with no Claude trailers.
- Gates (CLAUDE.md):
  - `uvx ruff@0.17.3 check llm_dojo_scoring tests scripts examples`;
  - `uv run --locked --extra dev pytest tests -q`;
  - `uv run --locked python scripts/freeze_goldens.py --check`;
  - `uv lock --check`;
  - `python scripts/release.py check`, quoting its WARN lines.

## Review Focus

1. **A value only reformatted from the text** (`"$1,250.00"` against "1250 dollars";
   `"AB-12/34"` against "ab 12 34") must be `grounded`, not `not_found`. Pinned in Task 1.
2. **A Hub row whose text columns are all `""` with no `gt_presence`.** This is what real
   Hub rows look like. It must audit nothing. Otherwise every field would be audited and
   the rate would be noise. Pinned in Task 2.
3. **`doc_text` that is `None`, `""` or only whitespace** makes every verdict
   `unverifiable` and the rate `None`, not 0.0 and not an error. Pinned in Tasks 1 and 3.
4. **A stringified list prediction** (`'["Acme", "Beta"]'`, as Hub-shaped predictions
   arrive) must be split into items, not audited as one string. Pinned in Task 2.
5. **An unknown `doc_class`** must raise the registry's `KeyError` with its message, and
   must not audit zero fields silently. Pinned in Task 2.

---

### Task 1: Per-type value verdicts

**Files:**
- Create: `llm_dojo_scoring/grounding/__init__.py` (docstring only, no imports)
- Create: `llm_dojo_scoring/grounding/verdicts.py`
- Test: `tests/test_grounding_verdicts.py`

**Interfaces:**
- Consumes, from `llm_dojo_scoring.scoring.field_scoring`:
  - `_containment_tokens(text) -> set[str]`;
  - `_parse_date_parts(text) -> _DateParts | None`, which also parses partial dates;
  - `_date_grounded_in_doc(pred_date, doc_text) -> bool`;
  - `_parse_money(text) -> float | None`, which strips symbols, commas and currency
    words, and expands K/M/B;
  - `get_verification_coverage() -> float`.
- Produces:
  - `GROUNDED, NOT_FOUND, UNVERIFIABLE`: the three verdict strings.
  - `value_verdict(field_type: str, value: Any, doc_text: str | None) -> tuple[str, float | None]`
    returns `(verdict, coverage)`. `coverage` is the token share for `name` and
    `free_text`, and `None` for the other types. `field_type` is a scalar type:
    `name`, `free_text`, `date`, `money`, `id`, `label` or `cms_doc_ref`.
    Any other type is treated as `name`.

- [ ] **Step 1: Write the failing tests.** Use synthetic text only. `DOC = "Invoice AB-12/34 dated March 3, 2024 from Acme Holdings for 1250 dollars."`

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
    ("label", "invoice", "unverifiable"),
    ("name", "!!!", "unverifiable"),          # no comparable tokens
])
def test_value_verdict_by_type(ftype, value, expected):
    assert value_verdict(ftype, value, DOC)[0] == expected

@pytest.mark.parametrize("doc", [None, "", "   "])
def test_no_document_text_is_unverifiable(doc):
    assert value_verdict("name", "Acme", doc) == ("unverifiable", None)

def test_name_coverage_is_reported():
    verdict, coverage = value_verdict("name", "Acme Globex", DOC)
    assert verdict == "not_found" and coverage == pytest.approx(0.5)
```

- [ ] **Step 2: Run them and see them fail.** `uv run --extra dev pytest tests/test_grounding_verdicts.py -q`. Expected: an ImportError on `llm_dojo_scoring.grounding.verdicts`.
- [ ] **Step 3: Implement `value_verdict` in `grounding/verdicts.py`.**
  - **`money`:** parse the value with `_parse_money`, and each number-like token in the
    document (regex `[$€£]?\d[\d,]*(?:\.\d+)?(?:\s*[KMB]\b)?`) the same way. The
    amounts are equal when they differ by at most 0.005. A value that `_parse_money`
    cannot parse is `unverifiable`.
  - **`id`:** casefold, then strip whitespace and `-`, `/` and `.` from both sides. A
    substring match means `grounded`.
  - **`date`:** `_parse_date_parts`, then `_date_grounded_in_doc`. A value that does not
    parse falls back to the `name` rule.
  - **`label`:** always `unverifiable`.
  - **`cms_doc_ref`:** use the `id` rule.
- [ ] **Step 4: Run them and see them pass** with the same command.
- [ ] **Step 5: Commit.** `feat(grounding): per-type value verdicts against the source document`

### Task 2: Choosing unlabelled values and per-value audit records

**Files:**
- Create: `llm_dojo_scoring/grounding/audit.py`
- Test: `tests/test_grounding_audit.py`

**Interfaces:**
- Consumes:
  - `value_verdict` (Task 1);
  - `scoring_gt_fields`, `is_empty_value` and `parse_json_container`, from `schemas.gt_metadata`;
  - `field_types` from `schemas.doc_classes`;
  - `is_entity_list` from `scoring.field_scoring`.
- Produces:
  - `@dataclass(frozen=True) class UnlabelledValueAudit`. Its fields:
    - `run_id: str | None`, `doc_id: str | None`;
    - `doc_class: str`, `doc_subclass: str | None`;
    - `field: str`, `field_type: str`;
    - `value: Any`, `item_index: int | None`;
    - `verdict: str`, `coverage: float | None`;
    - `gt_status: str`, `doc_text_sha256: str | None`;
    - `extractor: str | None`, `audited_at: float`.

    It also has `as_dict() -> dict`, which is JSON-serialisable.
  - `audit_unlabelled_values(gt_row, predicted: Mapping[str, Any], *, doc_class: str, doc_text: str | None, doc_subclass: str | None = None, run_id: str | None = None, doc_id: str | None = None, extractor: str | None = None) -> list[UnlabelledValueAudit]`.
    The records come in `field_types(doc_class)` order. A list field yields one record
    per non-empty item, with `item_index` set. A scalar has `item_index=None`.
    `doc_text_sha256` is the hex sha256 of `doc_text` encoded as UTF-8, or `None` when
    there is no text.
  - For a list field, the element type is the suffix after `entity_list:`, defaulting
    to `name`.

- [ ] **Step 1: Write the failing tests.** Build GT with `hub_row(...)` and
  `_with_presence(...)` from `tests/behavior/test_class_headline_contract.py`. Import
  them from that module, or move them to `tests/conftest.py` if an import across test
  files fails under the rootdir. Name each test after the behaviour it pins:
  - `test_hub_row_with_blank_columns_audits_nothing`: an all-blank `hub_row()` and a
    prediction filling several fields returns `[]` (Review Focus 2, owner decision §10.1).
  - `test_pending_annotation_field_is_audited`: `gt_status == "pending_annotation"`, and
    the verdict comes from the text.
  - `test_absent_key_is_audited_as_absent`: the GT is a plain dict without the key, so
    `gt_status == "absent"`.
  - `test_not_applicable_and_documented_absence_are_not_audited`: both statuses give `[]`.
  - `test_labelled_field_is_not_audited`: the GT has a value for the field, so no record.
  - `test_cms_adjuster_never_audited`: `doc_class="insurance_claim"` with a CMS subclass,
    and `adjuster` pending, gives no record. A non-CMS insurance row with `adjuster`
    pending gives one record.
  - `test_list_items_audited_one_by_one`: `parties='["Acme Holdings", "Globex"]'`
    (stringified, Review Focus 4) gives two records with `item_index` 0 and 1 and
    verdicts `grounded` and `not_found`.
  - `test_empty_prediction_and_off_schema_keys_skipped`: `""`, `None` and `[]`
    predictions, and keys outside the class map, give no record.
  - `test_unknown_doc_class_raises`: `pytest.raises(KeyError)` (Review Focus 5).
  - `test_records_carry_hash_not_text`: `doc_text_sha256` equals
    `hashlib.sha256(DOC.encode()).hexdigest()`, and `DOC` appears in no value of
    `as_dict()`.
- [ ] **Step 2: Run them and see them fail.** `uv run --extra dev pytest tests/test_grounding_audit.py -q`. Expected: an ImportError.
- [ ] **Step 3: Implement `audit_unlabelled_values`.**
  - Call `scoring_gt_fields(gt_row, field_types=types, doc_type=doc_class, subclass=doc_subclass)` once.
  - Read `gt_status` from the parsed `gt_presence`: `"pending_annotation"` when that is
    the field's status, else `"absent"`.
  - The CMS exclusion holds when the scoped dict has a non-empty `cms_source_table`.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit.** `feat(grounding): select unlabelled values with the headline's own scoping and audit them`

### Task 3: Run summary, ScoreRecords and registry entries

**Files:**
- Modify: `llm_dojo_scoring/grounding/audit.py`
- Modify: `llm_dojo_scoring/metrics/registry.py`, adding the three entries next to
  `extraction_hallucination_rate`. Each has `source: "grounding.audit.summarize_unlabelled_audits"`,
  and its `notes` say it is distinct from `extraction_hallucination_rate` and covers
  unlabelled fields only.
- Test: `tests/test_grounding_audit.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AuditCounts`, with `grounded: int`,
    `not_found: int` and `unverifiable: int`. Its properties:
    - `audited` is the sum of the three counts;
    - `not_found_rate` is `not_found / (grounded + not_found)`, or `None`;
    - `unverifiable_share` is `unverifiable / audited`, or `None`.
  - `@dataclass(frozen=True) class UnlabelledAuditSummary`, with
    `overall: AuditCounts`, `by_class: dict[str, AuditCounts]` and
    `by_field: dict[tuple[str, str], AuditCounts]`. `by_field` is keyed by
    `(doc_class, field)`. Its `as_dict()` renders those keys as `"doc_class.field"`.
  - `summarize_unlabelled_audits(audits: Iterable[UnlabelledValueAudit]) -> UnlabelledAuditSummary`.
  - `unlabelled_score_records(summary, *, agent: str, run_id: str | None = None) -> list[ScoreRecord]`:
    - one record per metric id for the overall counts, with `metadata={"scope": "run"}`;
    - then the same for each class, with `{"scope": "class", "doc_class": …}`;
    - then for each field, with `{"scope": "field", "doc_class": …, "field": …}`;
    - every record's metadata also carries `"denominator"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_rate_excludes_unverifiable`: the counts 3 grounded, 1 not_found and 4
    unverifiable give a rate of `0.25`, a share of `0.5` and `audited == 8`.
  - `test_rates_are_none_without_denominator`: `summarize_unlabelled_audits([])`, and a
    summary of only unverifiable records, give a rate of `None` (Review Focus 3).
  - `test_score_records_use_registered_ids`: every `record.metric` is in
    `get_registry().names()` and has the tier from Global Constraints.
  - `test_breakdowns_by_class_and_field`: two classes and three fields add up to the
    overall counts.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the summary, the records and the three registry entries.**
- [ ] **Step 4: Run** `uv run --extra dev pytest tests/test_grounding_audit.py tests/test_registry.py tests/test_metric_id_strict.py -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat(grounding): unlabelled-value rates as non-headline ScoreRecords`

### Task 4: Prove the isolation, record the hold, write the docs

**Files:**
- Test: `tests/test_grounding_isolation.py`
- Modify: `scripts/consumer_closure.py`. Add to `HOLD`:
  `"grounding": "unlabelled-value grounding, review candidates and label provenance (0.31.0); mailroom wiring is a follow-on"`.
- Modify: `docs/analysis/data/consumer_closure.json`, regenerated, never hand-edited.
- Modify: `llm_dojo_scoring/README.md`, adding a `grounding/` row to the module table.
- Create: `docs/guides/GROUNDING.md`. It covers:
  - what is audited, and why that set cannot overlap the headline;
  - the three verdicts and their per-type rules;
  - the three metric ids, and how they differ from `extraction_hallucination_rate`;
  - a short usage example that you run and whose output you paste.
- Modify: `CHANGELOG.md`, under `## [Unreleased]` → `### Added`, inside the 0.31.0
  comment block from Global Constraints.
- Modify: the design doc. In §6.2, replace the dotted metric names with the snake_case
  ids. In §3 and §8, replace "documented in `PUBLIC_API.md`" with "`docs/guides/GROUNDING.md`
  and the module README; `PUBLIC_API.md` is updated when a consumer imports it".

**Interfaces:** none new.

- [ ] **Step 1: Write the isolation tests.**
  - `test_scoring_path_never_imports_grounding`: in a fresh
    `subprocess.run([sys.executable, "-c", …])`, import `llm_dojo_scoring`,
    `llm_dojo_scoring.scoring.suites`, `llm_dojo_scoring.scoring.field_scoring` and
    `llm_dojo_scoring.metrics.emitter`. Then assert that no key in `sys.modules` starts
    with `llm_dojo_scoring.grounding`.
  - `test_auditing_leaves_extraction_scores_unchanged`: score one `hub_row` with a
    pending field through `get_suite` / `score_extraction`, as the existing headline
    tests do. Run `audit_unlabelled_values` on the same inputs. Score again, and assert
    that both `to_dict()` results are equal.
- [ ] **Step 2: Run them.** `uv run --extra dev pytest tests/test_grounding_isolation.py -q`.
  Expected: both pass, since Tasks 1 to 3 import nothing from `grounding` on the scoring
  path. If the first test fails, an import leaked in: remove it. Do not weaken the test.
- [ ] **Step 3: Add the `HOLD` entry and regenerate the closure JSON.**
  - Run `uv run python scripts/consumer_closure.py --mailroom ../llm-mailroom --sandbox ../exios66/local-mailroom-sandbox --extra-ref origin/claude/howdy-n8vcc1 --extra-ref origin/stack/01-audit-storage --extra-ref origin/stack/02-diagnostics-workbench --extra-ref origin/stack/03-audit-live-row --write`.
  - Then run the same command with `--check`. Expected: exit 0.
  - If a ref is missing (exit 2), stop and report it. Do not drop the ref.
- [ ] **Step 4: Write the guide, the README row, the CHANGELOG entry and the spec
  corrections.** Run the guide's example and paste its real output.
- [ ] **Step 5: Run the full local gate** from Global Constraints on a clean tree. Expected:
  - ruff prints `All checks passed!`;
  - the suite's summary line shows no failures, and the skips are named;
  - `freeze_goldens.py --check` exits 0;
  - `uv lock --check` exits 0;
  - `release.py check` exits 0, with its WARN lines quoted.
- [ ] **Step 6: Commit.** `docs(grounding): isolation tests, closure hold, guide and 0.31.0 changelog`

## After the tasks (orchestrator)

1. Count the diff with `git diff --stat origin/v0.30.0...HEAD`.
2. Run three adversarial rounds, one per lens; this is a new-metric change. Fix every
   BLOCKING or MAJOR finding between rounds.
3. Re-run the gates yourself.
4. Run a fresh `pre-pr-reviewer`, following `.claude/rules/pr-flow.md` step 3.
5. Push only the session branch, and only when the user asks.
