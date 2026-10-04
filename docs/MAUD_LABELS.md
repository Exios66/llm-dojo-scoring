# MAUD answer-class catalogs — never guess merger-agreement labels

Merger-agreement rows in the Hub `ground_truth` config carry
`maud_clause_labels`: for each of the 22 MAUD questions, the expected answer
plus the `valid_classes` catalog the annotators recognized **on that row**.
Scoring must interpret model output against those labels — never against
"any non-empty text".

## Source of truth

- Dataset: `Lucius-Morningstar/mailroom-dataset`, config `ground_truth`,
  pinned revision `bc9eab280044befb51e19dda3071d290a8677f42` (2026-09-27).
- 152 merger rows: **17 test + 135 train**. Every record carries
  `valid_classes`; **0 observed answers fall outside their row's catalog**
  (asserted by `scripts/verify_gt_penalties.py`).
- Four questions legitimately vary their class set by row — *Accuracy of
  Target R&W Closing Condition*, *MAE Definition*, *Limitations on FTR
  Exercise*, *Tail Period & Acquisition Proposal Details*. The record's own
  classes win; the union is only the fallback.
- Offline mirror: `tests/fixtures/maud_valid_classes.json` (per-question
  union classes, answered rows, distinct-set counts).
- Generated module: `llm_dojo_scoring/maud.py`.

## Per-document-type dict

`maud_question_catalog(doc_type)` returns a **fully populated**
`{question: (classes...)}` dict for every doc type that carries MAUD:

| `doc_type` | accepted aliases | questions |
| --- | --- | --- |
| `merger_agreement` | `merger_agreement_specialist` | all 22 |
| `contract` | `contracts_specialist` | all 22 |

Any other doc type raises `KeyError` — fail closed, never return a silently
empty catalog. The Hub routes merger rows through the contracts specialist,
so both doc types expose the same 22-question surface.

## Scoring API

- `parse_maud_labels` preserves each record's `valid_classes`; repeated Hub
  keys union their class surfaces instead of last-wins.
- `is_valid_maud_answer(question, value, valid_classes=None)` uses the
  record's own classes when given, otherwise the corpus union; unknown
  questions fail closed (`False`).
- `normalize_maud_answer(...)` canonicalizes case, smart quotes, the
  `fundermental` → `fundamental` typo, Yes/No aliases (only where the
  question's surface actually carries Yes/No), and comma-separated class
  components.
- `score_maud_extraction` reports `maud_question_accuracy`,
  `maud_question_macro_accuracy`, `maud_clause_presence`,
  `maud_valid_class_rate`, and `maud_category_accuracy`. A prediction using
  text outside the row's classes counts as invalid (the valid-class rate
  drops) rather than scoring as a near match.

## Reproduce / verify (portable)

From the repo root — no absolute paths, no machine-specific venv:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,catalog]"

# 1) committed catalog matches regeneration from the pinned revision
python scripts/gen_maud_catalog.py --check

# 2) perfect-prediction replay, both splits: zero FN/FP/spurious,
#    MAUD parity 1.0 on all 152 merger rows, zero class mismatches
python scripts/verify_gt_penalties.py
```

Offline mode: download the parquet tree once and pass `--parquet-dir` (see
each script's docstring for the expected layout and the snapshot command).

Regenerating after a dataset revision bump:

```bash
python scripts/gen_maud_catalog.py --write --revision <sha> --generated <YYYY-MM-DD>
python -m pytest -q
```

The same checks run as tests: `tests/test_maud_catalog.py` pins catalog
completeness, per-doc-type dicts, fixture consistency, canonicalization,
component-wise validity, and fail-closed behavior.
