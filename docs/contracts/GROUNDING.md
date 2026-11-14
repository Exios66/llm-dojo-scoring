# Unlabelled-value grounding

When an extractor fills a field the ground truth (GT) does not label, the headline
scores ignore that value: since 0.29.0 field-micro excludes unlabelled fields from both
sides, so the value is neither rewarded nor punished. The value may still be a
hallucination, or a correct value the dataset has not labelled yet.

`llm_dojo_scoring.grounding` checks each such value against the source document and
reports how often the document does not support it. It is a **separate pass**: callers
run it after scoring, and nothing on the scoring path imports it
(`tests/grounding/test_grounding_isolation.py` proves both). It never changes
`overall_score`, field-micro, class headlines, `extraction_hallucination_rate` or the
golden baseline. It is deterministic, network-free, makes no LLM calls, writes no files
and never stores document text.

Status: piece 1 of 3 (0.31.0). Review candidates, the confirmation ledger, label
provenance and the agent trust gate follow; see the design
(`docs/superpowers/specs/2026-11-14-unlabelled-value-grounding-design.md`) and tracker
Exios66/llm-dojo-scoring#146. Consumers: none yet (`hold` in
`docs/analysis/data/consumer_closure.json`); llm-mailroom wiring follows the release.

## What is audited

A predicted field is audited when **all** hold:

| Condition | Why |
| --- | --- |
| The field is in the class registry (`schemas.doc_classes.field_types`) | Off-schema keys are already headline false positives |
| The prediction is not empty (`schemas.gt_metadata.is_empty_value`) | Nothing to check |
| `scoring_gt_fields` (the headline's own GT scoping) drops the field | The headline does not judge it |

`scoring_gt_fields` drops a field when the GT has no such key (`gt_status: "absent"`) or
its `gt_presence` status is `pending_annotation` (`gt_status: "pending_annotation"`).
So these are **never** audited, because the headline already judges them:

- a field labelled with a value;
- a field labelled empty: `not_applicable`, `schema_documented_absence`, or a blank GT
  value with no presence status (owner decision, 2026-11-14);
- `adjuster` and `denial_reasons` on a CMS insurance row (labelled empty by the CMS
  source schema, whatever their status). A row is CMS by the headline's own test,
  `scoring.field_scoring.expected_cms_source_table`: a `cms_source_table` the GT carries
  or that `doc_subclass` implies, and no `claim_type` other than `health`.

`predicted` must be a mapping of field to value (`TypeError` otherwise); GT that
`scoring_gt_fields` cannot parse raises its error.

The selection rule lives only in `grounding/selection.py:unlabelled_fields`. A list field
(`entity_list…`) is audited item by item; each item gets its own record and verdict. A
mapping or list item is checked by its string values (`{"name": "Bob Co"}` as `Bob Co`).

## Verdicts

Each value is checked by its field type as the headline types it: the class registry's
type, with `scoring.field_scoring.CMS_ROW_FIELD_TYPES` on a CMS row (so
`supporting_documents` items there are `cms_doc_ref`, not names). A list field is
checked item by item with its item type.

| Field type | `grounded` when | Otherwise |
| --- | --- | --- |
| `name`, `free_text` (and unknown types) | at least `field_scoring.verification_token_coverage` (default 0.7) of the value's content tokens appear in the document | `not_found`; `unverifiable` when the value has no content tokens |
| `date` | the document writes the same date in any common form (see "Dates" below); partial dates agree on every stated part | `not_found`; text that is not a date uses the token rule |
| `money` | the document states the same amount (within half a cent, sign ignored) as money: with a currency symbol or word (spaces between it and the number on the same line are fine: `$ 500`, `500  dollars`), a scale (`5M`, upper case and attached, or `thousand`/`million`/`billion`), a thousands separator or two decimals. Bare integers in the text (a day, a year, a phone digit group) never count | `not_found`; `unverifiable` when the value is not an amount |
| `id`, `cms_doc_ref` | after casefolding and removing whitespace, `-`, `/` and `.`, the value equals one alphanumeric part of the text or up to six adjacent parts (`CLM 0001` matches `CLM-0001`; `12345` matches `INV-12345` and `No.12345`); a part is never split (`12` does not match inside `2012`) | `not_found`; `unverifiable` when shorter than three characters |
| `label` | never: a closed-vocabulary label is inferred, not quoted | always `unverifiable` |

Missing or blank document text makes every verdict `unverifiable`. Names, text and dates
reuse the factuality audit's matchers (`scoring/field_scoring.py`); amounts reuse its
money parser; the money and identifier boundary rules are this module's own. Per-document
work is cached (the last eight documents per cache), so auditing many values of one
document scans it once.

### Dates

A date value is read with `field_scoring._parse_date_parts`, the reader the headline date
scorer uses, and is `grounded` when some date the document writes agrees with every
component the value states (year, month, day). The document is scanned for these forms,
each read by the same parser; a weekday prefix ("Sunday, March 3, 2024") is ignored:

| Form | Examples |
| --- | --- |
| ISO and year-first numeric | `2024-03-03`, `2024/03/03`, `2024.03.03`, `2024-03-03T10:30:00Z` |
| numeric with a year last | `3/24/2006`, `04-01-06`, `13.04.2024`, `03.04.24` |
| month-first prose | `March 3, 2024`, `Mar. 3rd, 2024`, `March 3 2024`, `March the 3rd, 2024` |
| day-first prose | `3 March 2024`, `3rd of March, 2024`, `the 3rd day of March, 2024`, `03-Mar-2024` |
| month and year | `March 2024`, `Mar. 2024`, `2024-03`, `03/2024` |
| month and day, no year | `March 3`, `3rd of March` |

Rules that keep a date-shaped string from becoming a date:

- A date states what it writes and nothing more. A year-less document date ("signed on
  March 3") never grounds a value that states a year, and a month-and-year never
  grounds a day. A full document date does ground a partial value that agrees ("March 3",
  "2024-03").
- An ambiguous numeric date is month-first: `03/04/2024` is March 4, so it grounds
  `2024-03-04`, not `2024-04-03`. A first or second number above 12 is the day. A
  two-digit year uses the fixed pivot (00 to 68 is 2000 to 2068, 69 to 99 is 1969 to 1999).
  The clock is never read.
- A span inside a longer alphanumeric, hyphenated, slashed or dotted run is not a date
  (`INV-2024-0301`, `2024-03-0001`, `415-505-2024`, `1.2.34`), nor is one after `#`, `@`,
  a currency sign or `+`. Numbers must be in calendar range.
- "May" is a month only when capitalised ("you may 5 times" is not May 5). A decimal or
  thousands group after a day (`March 3,000`, `March 3.50`) is an amount.
- Numeric month-and-year needs a zero-padded month (`03/2024`, not `3/2024`), so `1/2000`
  stays a fraction. Dots between numbers need a four-digit year, or two-digit day, month
  and year.

Not read, so the value is `not_found` (fix in the scanner if you hit one): day ranges
(`March 3-5, 2024`), an ISO interval joined by a slash (`2024-03-03/2024-03-10`; joined
by an en dash it reads), compact `20240303`, year-first prose (`2024 March 3`), a lowercase
"may", month names in other languages, spelled-out days ("third of March"), "the month of
March 2024", and quarters or fiscal years. Lookalikes that do read as a date: a version
written with two-digit parts (`10.12.15`), a padded month-year reference number
(`INV 03/2024`) and a month name followed by a number ("Dec 25 units"). The headline
factuality audit (`audit_scalar_field`) uses the same matcher, so these verdicts and its
`verified_in_doc`, `hallucination_rate` and `verified_precision` read a document's dates
identically (tracked on Exios66/llm-dojo-scoring#146 and #147). A new field type
is one entry in `grounding/verdicts.py:_RULES`.

## Metrics

| Id | Tier | Value | Denominator |
| --- | --- | --- | --- |
| `grounding_not_found_rate` | 1 | `not_found / (grounded + not_found)` | checkable values; `unverifiable` excluded |
| `grounding_unverifiable_rate` | 2 | `unverifiable / n_audited` | all audited values |
| `grounding_n_audited` | 3 | audited values (list items counted singly) | — |

A rate with a zero denominator is `None`, never `0.0`. `grounding_score_records` emits
one record per metric, for the run: `metadata` holds `scope: "run"`, the run's
`denominator`, and `by_class` and `by_field` (keys `"doc_class.field"`), each mapping a
slice to its `value` and `denominator`. Slices are not separate records because
`Emitter.get_scorecard` aggregates by metric id alone: it would sum `grounding_n_audited`
over run, class and field, and show the last slice's rate as the run's.

`extraction_hallucination_rate` is a different number: a mailroom alias over **all**
reported values (labelled or not) that match neither GT nor the document. Do not put the
two on one chart axis.

## Record contract

`UnlabelledValueAudit.as_dict()` (JSON, `schema_version: 1`; `from_dict` reads it back):

| Field | Meaning |
| --- | --- |
| `run_id`, `doc_id` | Caller ids |
| `doc_class`, `doc_subclass` | Registry class and subclass |
| `field`, `field_type` | Field, and the type checked (a list's item type) |
| `value`, `item_index` | The value; the item's position for list fields, else `null` |
| `verdict`, `coverage` | `grounded` / `not_found` / `unverifiable`; token share for the token rule, else `null` |
| `gt_status` | `absent` or `pending_annotation` |
| `doc_text_sha256` | sha256 of the UTF-8 document text (`null` without text); the text is never stored |
| `extractor` | Model or agent id, when given |
| `audited_at` | Unix time of the audit |

`GroundingSummary.as_dict()` carries `schema_version: 1`, `overall`, `by_class` and
`by_field` (keys `"doc_class.field"`).

## Usage

```python
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.summary import grounding_score_records, summarize_grounding

doc_text = "Claim AB-12/34 filed March 3, 2024 by Acme Holdings for 1250 dollars."
gt_row = {"claim_number": "AB-12/34", "insurer": "Acme Holdings"}  # no adjuster, no amount
predicted = {
    "claim_number": "AB-12/34",            # labelled: scored by the headline, not audited
    "insurer": "Acme Holdings",            # labelled: not audited
    "claimed_amount": "$1,250.00",         # unlabelled, stated in the text
    "adjuster": "Robin Example",           # unlabelled, not in the text
    "coverage_determination": "approved",  # unlabelled label: cannot be checked
}
audits = audit_unlabelled_values(gt_row, predicted, doc_class="insurance_claim",
                                 doc_text=doc_text, doc_id="doc-1", run_id="run-1")
for a in audits:
    print(a.field, a.verdict, a.gt_status)
summary = summarize_grounding(audits)
print(summary.overall.as_dict())
for r in grounding_score_records(summary, agent="insurance_claims_specialist", run_id="run-1"):
    print(r.metric, r.value, r.metadata["denominator"], r.metadata["by_field"]["insurance_claim.adjuster"])
```

Output (run on this release):

```
claimed_amount grounded absent
adjuster not_found absent
coverage_determination unverifiable absent
{'grounded': 1, 'not_found': 1, 'unverifiable': 1, 'n_audited': 3, 'not_found_rate': 0.5, 'unverifiable_rate': 0.3333333333333333}
grounding_not_found_rate 0.5 2 {'value': 1.0, 'denominator': 1}
grounding_unverifiable_rate 0.3333333333333333 3 {'value': 0.0, 'denominator': 1}
grounding_n_audited 3 3 {'value': 1, 'denominator': 1}
```

## Modules

| Module | Owns |
| --- | --- |
| `grounding/verdicts.py` | `value_verdict`, `VERDICTS`: one value against the document |
| `grounding/selection.py` | `unlabelled_fields`, `UNLABELLED_STATUSES`: the audited set |
| `grounding/audit.py` | `UnlabelledValueAudit`, `audit_unlabelled_values` |
| `grounding/summary.py` | `GroundingCounts`, `GroundingSummary`, `summarize_grounding`, `grounding_score_records`, `METRIC_IDS` |
