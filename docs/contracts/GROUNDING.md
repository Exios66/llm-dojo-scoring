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
each read by the same parser (a test checks a broad list of forms: whatever the parser reads as a
full date is found in a document, bar the one listed below); a weekday prefix ("Sunday, March 3, 2024") is
ignored:

| Form | Examples |
| --- | --- |
| ISO and year-first numeric | `2024-03-03`, `2024/03/03`, `2024.03.03`, `2024-03-03T10:30:00Z`, `2024-Mar-03`, compact `20240303` and `18990303` (compact years run 1800 to 2099 too) |
| numeric with a year last | `3/24/2006`, `04-01-06`, `13.04.2024`, `03.04.24`, `3.4.24`, a dotted range `12.31.99-12.31.99` |
| month-first prose | `March 3, 2024`, `Mar. 3rd, 2024`, `March 3 2024`, `March the 3rd, 2024`, `may 3, 2024`, `March 3rd of 2024`, `March, 3 2024`, `March 3d, 2024` |
| day-first prose | `3 March 2024`, `3rd of March, 2024`, `03-Mar-2024`, `3rd-March-2024`, `3/Mar/2024`, `the 3rd day of March, 2024` (also OCR splits such as `18t h day of`, and "the month of": `3rd day of the month of March, 2024`) |
| glued day, month, year | `03MAR2024`, `03Mar24`, `3MAR24` |
| two-digit-year prose | `31 Dec 23`, `3 Mar 24`, `Mar 3, 24`, `March 3rd, '24` |
| spelled-out days and years | `this third day of March, 2024`, `the Thirty-first day of December, 2024`, `twenty-first of June 2024`, `first of March 2024`, `May twenty-fourth, 2024`, `March third, 2024`, `3rd day of March, two thousand twenty-four`, `3rd day of March, in the year of our Lord 2024`, and a legal `this 3d day of March` |
| a day written twice | `the 3rd (third) day of March, 2024`, `first (1st) of March 2024` |
| year-first prose | `2024 March 3`, `2024, March 3rd` |
| month and year | `March 2024`, `March of 2024`, `Mar-2024`, `2024-03`, `03/2024`, `3/2024` |
| month and day, no year | `March 3`, `3rd of March`, `twenty-first of June` |
| day ranges | `March 3-5, 2024`, `3-5 March 2024`, `March 3 to 5, 2024`, `March 3 through 5, 2024`, `March 3rd through 5th, 2024`, `March 30-April 2, 2024`, and year-less `March 1 to June 30` |

Digits written full-width or in another script (`２０２４-０３-０３`) are folded to ASCII (NFKC
and a decimal map) on the document and on the value, as are no-break and other Unicode spaces.

Ordinal words run from `first` to `thirty-first` (hyphen or space). They count only as a whole
day: `thirty-second`, `forty-first` and `fifty-third` name no day (a bare `second` or `third`
after a tens word is not read either, however much whitespace separates the two words). A day written twice, `3rd (third)`, is that day; when the
two disagree (`3rd (fourth)`) the day is not read, and the month and year still are. Spelled-out
years are `two thousand [and] ...` and `nineteen ...` / `eighteen ...`.
Document years run from 1800 to 2099 in every form (so `1/1000` is a fraction, not a date).

Rules that decide what is a date:

- A date states what it writes and nothing more. A year-less document date ("signed on
  March 3") never grounds a value that states a year, and a month and year never grounds a
  day. A full document date does ground a partial value that agrees ("March 3", "2024-03").
- Every start position is tried. A number in front of a month ("Item 4 March 15, 2024",
  "Page 3 March 15, 2024") is read as its own year-less "4 March" and the full date after it is
  read as well; a wrong year-less extra grounds no year.
- A day range states both its ends and nothing between: `March 3-5, 2024` grounds March 3
  and March 5, 2024, not March 4. A value that is itself a range ("March 3-5, 2024") is
  read as its first day, so it is grounded when the document states that day.
- An ambiguous numeric date is month-first: `03/04/2024` is March 4, so it grounds
  `2024-03-04`, not `2024-04-03`. A first or second number above 12 is the day. A
  two-digit year uses the fixed pivot (00 to 68 is 2000 to 2068, 69 to 99 is 1969 to 1999).
  The clock is never read.
- A complete date (day, month and a four-digit year, or numeric with a two-digit year after
  dashes or slashes) may be followed by punctuation, `_`, `@` or a letter, and may follow
  punctuation or whitespace (not a letter, a digit, or a digit and a dot), so ranges (`01/01/2024-12/31/2024`,
  `March 1, 2024/March 1, 2025`, `2024-03-01/2024-03-10`) and file names (`contract_3-1-2024.pdf`) read,
  and both ends of a range are read. It may not touch a digit (`2024-03-0001` is an identifier)
  or start right after a letter (`HO3-12-2020` and `A1-12-2020` are part and policy numbers, not
  March 12, 2020). The other forms (month and year, month and day, compact, dotted
  two-digit year, two-digit-year prose, glued `03MAR2024`) must stand alone: a span inside a longer
  alphanumeric, hyphenated, slashed or dotted run is not a date (`INV-2024-0301`, `415-505-2024`), nor is
  one after `#`, `@`, a currency sign or `+`. Numbers must be in calendar range.
- "May" and "March" are months in a partial date (month and year, month and day) only when
  capitalised: "you may 5 times" is not May 5. With a day and a year ("may 3, 2024") any
  case reads. A decimal or thousands group after a day (`March 3,000`, `March 3.50`) is an
  amount. A month-first two-digit year needs a comma or an apostrophe (`Mar 3, 24`, `March 3rd, '24`);
  a two-digit year after a day-first month ("3 Mar 24") must not start a longer number
  (`4 March 15, 2024` is March 15, 2024).
- A dotted span (`3.4.24`, `13.04.2024`) is a date, except right after "v", "version", "ver",
  "release", "build" or "rev" (`Version: 1.2.34`, `Release notes 1.2.34`, `see build 1.2.34-1.2.35`
  are versions) or after Section, Sec., Clause, Article, Art., Paragraph, Para., Rule, Item, Part,
  Schedule, Exhibit, the section sign or the paragraph sign (`Section 3.1.20`, `§ 5.2.14` are section
  numbers), each with an optional colon or spaces. A dotted two-digit-year date
  must stand alone, except that both ends of a range `3.4.24-3.5.24` read.
- A numeric month and year alone (`03/2024`, `3/2024`, `03-2024`, `2024-03`) is a reference number
  after Case, No., Number, `#`, Ordinance, Resolution, Policy, Claim, Docket, Ref, RFC, Pub. L., ext.,
  Room, Invoice, Inv. or a section word. A full date after those words still reads
  (`Policy dated 03/12/2020`).
- A year-less range (`March 1 to June 30`, `March 3-5`) states both its ends without a year; like
  every year-less date it grounds no value that states a year. It uses the partial-date guards.
- Every gap inside a date is bounded (30 whitespace characters), so scanning is linear:
  The scan grows linearly with the text: a test checks that 200 KB of hostile text takes
  under 8 times as long as its first quarter (quadratic backtracking would be 16 times).

Not read, so the value is `not_found` (fix in the scanner if you hit one): ISO basic with a
time (`20240303T1030`; with a colon it reads), compact dates inside a longer run (`INV20240303`),
`3-2024` (unpadded month with a dash), lowercase "may" or "march" in a partial date, month names
in other languages, cardinal day words ("twenty-one of June"), `March 3 and 5, 2024` (only
`March 3` reads), a dotted two-digit-year date that touches `-`, `/` or `@` (outside a range), an
impossible ordinal (`thirty-second`), `Q1 2024`, fiscal years and ISO week dates, and
`March 3 24` (a month-first two-digit year with neither a comma nor an apostrophe; the value reader
does read it, the one asymmetry, pinned in a test). "The month of March 2024" reads as "March 2024".

Lookalikes that do read as a date (trade-offs for reading everything above):

- a dotted version with small parts that has no version or section word before it (`1.2.34`,
  `10.12.15`), and one written as a range (`1.2.34-1.2.35`);
- a timestamp `12.30.45`, an eight-digit number that is a valid `YYYYMMDD` (a SKU), a fraction in
  the 1800 to 2099 range (`1/2000` is January 2000);
- a month name followed by a number: `Dec 25 units`, `12 March Road`, a capitalised "May" or "March"
  next to a number ("Theresa May 5"), `March 3, 24 hours` (March 3, 2024), `4 March 15 people`
  (March 4, 2015);
- a complete date inside an invoice number (`INV-2024-03-01`) and a month-and-year number after a
  word that is not in the id list above.

The headline factuality audit (`audit_scalar_field`) uses the same matcher, so these verdicts and its
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
