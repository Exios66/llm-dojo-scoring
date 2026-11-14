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

Status (0.31.0): pieces 1 and 2 (verdicts and rates; review candidates, the
confirmation ledger and valid labels with provenance), the reviewer-trust settings,
agent agreement with human spot-checks, spot-check sampling and the trust gate: the whole
loop from audit to labels (piece 3 is split across four stacked PRs,
`docs/superpowers/plans/2026-11-14-unlabelled-value-grounding-piece-3.md`); see the design
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
- a timestamp `12.30.45`, an eight-digit number that is a valid `YYYYMMDD` from 1800 to 2099 (a SKU, or a
  claim or Bates number such as `18450317`, even after "Claim No."), a fraction in
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

## Review candidates (piece 2)

A value found in the text is still not a label. `grounding/candidates.py:review_candidates`
turns every audit record into a `ReviewCandidate`, whatever its verdict:

- **Id.** `candidate_id` is the sha256 of `[doc_id, field, normal form, doc_text_sha256]`
  (JSON-encoded). The normal form is the field type's own: the signed parsed amount with
  two decimals for money (the currency is not kept), `year-month-day` (`?` for an unstated part) for dates, the
  casefolded text without whitespace, `-`, `/` or `.` for identifiers, and casefolded
  text with whitespace collapsed for anything else or anything its type cannot parse.
  So re-running gives the same ids, `$1,250.00` and `1250 USD` are one candidate (as are
  `$1250` and `€1250`, and ids `1.2` and `12`: the forms are deliberately coarse), a
  credit `-1250` is another, and a list item keeps its id when the list is reordered.
  Known limitation: because the currency is not kept, a value that swaps only the
  currency of an already-audited amount on the same field is not a separate candidate. A value seen twice is one candidate
  (the first audit wins). An audit without `doc_id` raises `ValueError`.
- **Order.** `priority` is 0 for `not_found`, 1 for `unverifiable`, 2 for `grounded`;
  candidates come sorted by priority, then fields with more candidates first, then
  document, field and item. The Dojo exports the order; the consumer owns the queue.

## Confirmations and the ledger (piece 2)

A confirmation is one reviewer's verdict on one candidate (JSON, `schema_version: 1`):

| Field | Rule |
| --- | --- |
| `candidate_id` | must name a known candidate |
| `verdict` | `valid`, `hallucinated` or `unsure`. `valid` without a `corrected_value` needs a candidate value that is non-blank text or a finite number (a predicted `false` or object cannot become a label as it is) |
| `reviewer_kind` | `human` or `agent` |
| `reviewer_id` | non-blank. A human's starts with `human:` (`human:<opaque id>`) and an agent's never does (`boss@<prompt version>`, `jev-<version>`), so a record that labels an agent as a person (or the reverse) is rejected. A new agent version is a new reviewer |
| `confirmed_at` | Unix time (a finite number), at most a day ahead of ingest time (`now`, default the clock) |
| `certainty` | agents: required, in `[0, 1]`; humans: must be absent |
| `corrected_value` | optional; non-blank text or a finite number; becomes the label's value |
| `note` | optional text |

`ingest_confirmations(records, candidates)` validates records (mappings, for example from
`io.read_jsonl`, or `Confirmation` objects) into a `ConfirmationLedger`. A record that
fails a rule is kept in `ledger.rejects` as a `ConfirmationReject` with its position and
reason, never dropped. The ledger is append-only: `ledger.extend(records)` returns a new
ledger, nothing is edited or deleted, and a change of mind is a new confirmation. Only
each reviewer's **latest** confirmation per candidate counts (`ledger.latest()`; on equal
`confirmed_at` the one ingested later wins).

**Trust boundary.** The ledger checks that a record is well formed, not who wrote it:
`reviewer_kind` and `reviewer_id` are what the writer says. Whatever appends to the
ledger file (the review tray) must authenticate people and set `reviewer_kind: "human"`
only for them; anyone who can write the file can write a `human:` record.

## Valid labels (piece 2)

`derive_valid_labels(ledger, gate=None, *, certainty_floor=None, previous=())` is a pure
function of the ledger, recomputed every time. `certainty_floor` defaults to the
`grounding.certainty_floor` setting (0.9; see "Settings" below). Per candidate, on latest confirmations:

| Situation | Outcome |
| --- | --- |
| Any human said `valid` or `hallucinated` | **Humans decide.** All `valid` with the same value (text equal after casefolding and collapsing whitespace; `$1,250.00` and `1250` differ) → label, `validity_basis: "human"`. All `hallucinated` → `rejected`. Otherwise → conflict `humans_disagree` |
| Only `unsure` from everyone | pending `only_unsure` (a human `unsure` never validates or blocks) |
| No human verdict; agents say only `hallucinated` | pending `agent_hallucinated` |
| Agents disagree (`valid` and `hallucinated`, or different values, compared as for humans) | conflict `agents_disagree`, for a person to settle |
| Agents say `valid`; at least one was trusted by the gate as of its `confirmed_at`, with `certainty ≥ certainty_floor` | label, `validity_basis: "trusted_agent"`, `gate_snapshot_id` of the earliest such agent |
| Agents say `valid` with enough certainty, none trusted | pending `agent_untrusted` |
| Agents say `valid`, none with enough certainty | pending `below_certainty_floor` |

Without a gate no agent is trusted, so only human-confirmed labels come out. A gate is any
object with `trusted_snapshot_id(ledger, reviewer_id, at) -> str | None` (`TrustGate`,
see "Trust gate" below). Given no `certainty_floor`, `derive_valid_labels` uses the
gate's `certainty_floor` when it has one, else the setting. A later human `hallucinated`
removes a label agents made; labels of a `previous` export that are not derived now (same
candidate and same value) are returned as `withdrawn`, so a later correction to another
value withdraws the old one.

`ValidLabel` (JSON, `schema_version: 1`): `doc_id`, `doc_class`, `field`, `item_index`,
`value`, `source_candidate_id`, `extractor`, `doc_text_sha256`, `confirmed_by` (every
latest confirmation: `reviewer_kind`, `reviewer_id`, `verdict`, `certainty`,
`confirmed_at`), `validity_basis` and `gate_snapshot_id`. `LabelDerivation` holds
`labels`, `rejected`, `conflicts` and `pending` (candidate id → reason) and `withdrawn`.

`io.write_jsonl(items, path, append=False)` and `io.read_jsonl(path)` move every record
type to and from local JSONL files. A replace is atomic and keeps an existing file's
permissions; an append first closes a torn last line; an unserialisable record or NaN
raises before anything is written; a bad line on read (not JSON, not an object, or a `NaN` or `Infinity`) raises, naming the line. There is
no locking: one writer per file at a time. Nothing is written to a hosted store.

| Id | Tier | Value |
| --- | --- | --- |
| `grounding_n_candidates` | 3 | candidates exported |
| `grounding_n_valid_labels` | 3 | valid labels; `metadata.by_basis` splits `human` / `trusted_agent` |
| `grounding_n_label_conflicts` | 3 | conflicts; `metadata.by_reason` |

`labels.label_score_records(candidates, derivation, *, agent, run_id=None)` emits them
for the run.

```python
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import review_candidates
from llm_dojo_scoring.grounding.labels import derive_valid_labels
from llm_dojo_scoring.grounding.ledger import ingest_confirmations

doc_text = "Claim AB-12/34 filed March 3, 2024 by Acme Holdings for 1250 dollars."
audits = audit_unlabelled_values(
    {"claim_number": "AB-12/34"},
    {"claimed_amount": "$1,250.00", "adjuster": "Robin Example"},
    doc_class="insurance_claim", doc_text=doc_text, doc_id="doc-1", run_id="run-1")
candidates = review_candidates(audits)          # adjuster (not_found) first
for c in candidates:
    print(c.field, c.verdict, c.priority, c.candidate_id[:12])
amount, adjuster = candidates[1], candidates[0]
ledger = ingest_confirmations([
    {"candidate_id": amount.candidate_id, "verdict": "valid", "reviewer_kind": "human",
     "reviewer_id": "human:r1", "confirmed_at": 1767225600},
    {"candidate_id": adjuster.candidate_id, "verdict": "valid", "reviewer_kind": "agent",
     "reviewer_id": "boss@v3", "certainty": 0.97, "confirmed_at": 1767225600},
    {"candidate_id": "unknown", "verdict": "valid", "reviewer_kind": "human",
     "reviewer_id": "human:r1", "confirmed_at": 1767225600},
], candidates)
print([r.reason for r in ledger.rejects])
result = derive_valid_labels(ledger)            # no gate: no agent is trusted
print([(l.field, l.value, l.validity_basis) for l in result.labels])
print(result.pending)
```

Output (run on this release; the last id shortened):

```
adjuster not_found 0 c61ae340aca8
claimed_amount grounded 2 157461380899
["unknown candidate_id 'unknown'"]
[('claimed_amount', '$1,250.00', 'human')]
{'c61ae340aca866de…': 'agent_untrusted'}
```

## Agent agreement (piece 3)

`grounding/agreement.py` measures how often people confirm what each agent
(`reviewer_id`) said. `paired_checks(ledger, *, as_of=None)` pairs, per candidate, each
agent's blind verdict with people's, when that verdict is decisive:

- the agent's side is its **blind** verdict: its latest confirmation from before people
  first decided the candidate (earlier in the ledger and no later in time). A revision
  after people decided never rewrites the pair, so an agent shown the human verdict
  cannot erase its miss, and a backdated record that arrived after the human one does
  not count. When that latest blind confirmation is `unsure`, the agent took no
  position and is not paired, even if it said `valid` earlier;
- people's side is their latest confirmations; `unsure` from either side is left out
  (a person whose latest word is `unsure` no longer counts);
- people must agree with each other (same verdict and, for `valid`, the same value),
  or the candidate has no human truth and is not paired;
- `human_verdict` is people's verdict on the value the agent vouched for: an agent
  `valid` on a value people corrected to something else counts as `hallucinated`;
- with `as_of`, only confirmations made at or before it count; a pair is dated by the
  latest deciding human confirmation.

Known limitation: the ledger records when a confirmation was made (`confirmed_at`), not
when it arrived. `as_of` therefore reconstructs the past from today's ledger: a person's
record appended later but dated earlier is counted at every `as_of` after its date. If it
disagrees with the person who decided first, the candidate loses its human truth, and the
pair drops out of the history (and so out of the trust gate's snapshots, which are
recomputed, not stored). Pinning history to arrival needs an arrival time on each record,
a schema change tracked on Exios66/llm-dojo-scoring#146.

`reviewer_agreement(ledger, *, window=None, as_of=None)` returns a `ReviewerAgreement`
per agent over its latest `window` pairs (default `grounding.trust_window`), ordered by
the human's time (ties by candidate id), with `overall` and `by_field`
(`"doc_class.field"`) `AgreementCounts`:

| Id | Tier | Value |
| --- | --- | --- |
| `grounding_reviewer_valid_precision` | 1 | of the agent's `valid` verdicts, the share people also call valid with the same value |
| `grounding_reviewer_valid_precision_lower_95` | 1 | Wilson 95% lower bound of that share, **unrounded** (`wilson_ci`'s four-decimal rounding could lift 0.94998 to a 0.95 bar): the number the trust gate compares with `trust_bar`. Its denominator, and the count `trust_min_n` applies to, is `n_agent_valid` |
| `grounding_reviewer_agreement` | 2 | share of pairs with the same verdict |
| `grounding_reviewer_kappa` | 2 | Cohen's κ, with people's side read as their verdict on the value the agent vouched for (a corrected value counts as `hallucinated`); `None` unless both sides used both verdicts |
| `grounding_reviewer_n_checked` | 3 | pairs in the window |

A rate with a zero denominator is `None`. `agreement_score_records(agreements, *,
run_id=None)` emits the five metrics per reviewer, with `agent` set to the `reviewer_id`
(the reviewer version is what is scored) and `metadata.reviewer_id`, `metadata.window`
and `metadata.denominator`; the metrics apply to `ALL` agents for that reason.
`Emitter.get_scorecard(reviewer_id, run_id)` then gives one reviewer's numbers: under a
shared agent name it would aggregate by metric id alone and show only the last
reviewer's precision.

### Spot-check sampling

`select_spot_checks(ledger, *, rate=None, min_per_agent=None, seed=0) -> list[str]`
returns the candidate ids to send to people, in candidate-id order:

- per agent, the eligible candidates are those whose latest confirmation by that agent
  is `valid` or `hallucinated` and that no person has decided yet (a latest `unsure`
  is not a decision);
- each gets a fixed draw in `[0, 1)` from `sha256([seed, reviewer_id, candidate_id])`
  (the first 64 bits of the JSON list's digest), and a draw below `rate` is sampled; that
  part of the sample does not change as the ledger grows or between runs;
- when the agent's paired checks in its latest `trust_window` plus its drawn candidates
  are fewer than `min_per_agent`, its lowest remaining draws top it up (all its eligible
  candidates if there are fewer). Checks people already made count, so calling again
  after they answered does not add another 20. The floor is capped at `trust_window`,
  the most paired checks that can count toward it. The top-up can change as candidates
  arrive, so a caller keeps its own record of what it sent;
- a candidate sampled for several agents is listed once.

`rate` and `min_per_agent` default to `grounding.spot_check_rate` (0.10) and
`grounding.spot_check_min_per_agent` (20) and are validated like them (`ValueError`);
`seed` must be a whole number. Precision counts every paired check, including ones a
person made without being asked, not only sampled ones.

## Trust gate

`grounding/trust.py`. `TrustGate(bar=None, min_n=None, window=None, certainty_floor=None)`
takes its defaults from the `grounding` settings and validates them together
(`ValueError` on a bad value). An agent (`reviewer_id`) is **trusted** at time `t` when,
over its latest `window` pairs known at `t` (`reviewer_agreement(..., as_of=t)`):

- it said `valid` at least `min_n` times (`n_agent_valid ≥ min_n`), and
- the unrounded Wilson lower bound of its valid precision is at least `bar`.

With the defaults a perfect record passes only from 73 checked `valid` verdicts: the
bound of `n/n` is `1 / (1 + 1.96²/n)`, 0.9287 at 50 and 0.9500 at 73.

Trust is judged **as of each agent confirmation's `confirmed_at`**, never
retroactively. `TrustGate.history(ledger)` replays the ledger at each distinct time a
person confirmed something (the only times a pair can appear or change) and returns a
`GateSnapshot` whenever an agent's numbers change, ordered by `effective_at`. A
snapshot is in force from its `effective_at` (inclusive) until that agent's next one.

| Rule | Effect |
| --- | --- |
| New `reviewer_id` (a new boss prompt version, a new JEV release) | no pairs, no snapshot: untrusted |
| `human:` reviewer id | never gated (`trusted_snapshot_id` is `None`) |
| People later withdraw every pair (latest word `unsure`, or they disagree) | an empty, untrusted snapshot |
| Same evidence under the same thresholds | the same `snapshot_id` |

`GateSnapshot` (JSON, `schema_version: 1`): `snapshot_id`, `reviewer_id`,
`effective_at`, `trusted`, `bar`, `min_n`, `window`, `window_start`, `window_end`,
`n_checked`, `n_agent_valid`, `n_valid_confirmed`, `valid_precision`,
`valid_precision_lower_95`. `snapshot_id` is the sha256 of the reviewer id, the
thresholds, the window bounds, the counts and `trusted`.

- `trusted_snapshot_id(ledger, reviewer_id, at)` is the `TrustLookup` that
  `derive_valid_labels` calls: the id of the snapshot in force at `at` if it is trusted,
  else `None`. `snapshot_at(ledger, reviewer_id, at)` returns the snapshot itself.
- **Regression guard:** `regressions(ledger, labels)` returns a `Regression` for each
  untrusted snapshot that follows a trusted one: `failed` (that snapshot), `passing`
  (the ids of the passing run before it) and `labels` (the `trusted_agent` labels whose
  `gate_snapshot_id` is in that run), for a person to re-review. Those labels are not
  withdrawn automatically: they were trusted when made, and a human `hallucinated`
  removes one.

Trust is looked up by the agent confirmation's own `confirmed_at`, with human evidence
at exactly that time included. The ledger accepts past times, so an agent record that
arrives late but is dated inside a passing run counts as trusted; the regression guard
still lists it if that run later ends, and a consumer that needs arrival-time trust
should stamp `confirmed_at` on ingest.

The whole loop, from extraction to labels (synthetic data; low thresholds so 30 checks
suffice):

```python
from llm_dojo_scoring.grounding.agreement import reviewer_agreement, select_spot_checks
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import review_candidates
from llm_dojo_scoring.grounding.labels import derive_valid_labels
from llm_dojo_scoring.grounding.ledger import ingest_confirmations
from llm_dojo_scoring.grounding.trust import TrustGate

doc_text = "Claim AB-12/34 filed March 3, 2024 by Acme Holdings for 1250 dollars."
audits = []
for i in range(40):
    audits += audit_unlabelled_values({}, {"adjuster": f"Robin Example {i}"}, doc_class="insurance_claim",
                                      doc_text=doc_text, doc_id=f"doc-{i}")
candidates = review_candidates(audits)
ids = [c.candidate_id for c in candidates]

def record(cid, kind, reviewer, at, **extra):
    """A ``valid`` confirmation."""
    return {"candidate_id": cid, "verdict": "valid", "reviewer_kind": kind,
            "reviewer_id": reviewer, "confirmed_at": at, **extra}

boss = [record(cid, "agent", "boss@v3", 1767225600, certainty=0.97) for cid in ids[:30]]
ledger = ingest_confirmations(boss, candidates)
sample = select_spot_checks(ledger, rate=1.0)    # send every one to people this time
people = [record(cid, "human", "human:r1", 1767229200) for cid in sample]
later = [record(cid, "agent", "boss@v3", 1767232800, certainty=0.97) for cid in ids[30:]]
ledger = ledger.extend(people + later)

gate = TrustGate(bar=0.85, min_n=25)             # defaults: 0.95 and 50
counts = reviewer_agreement(ledger)["boss@v3"].overall
print(counts.n_agent_valid, round(counts.valid_precision_lower_95, 4))
print([(s.effective_at, s.trusted) for s in gate.history(ledger)])
result = derive_valid_labels(ledger, gate)
print(sorted({l.validity_basis for l in result.labels}), len(result.labels), result.pending)
```

Output (run on this release):

```
30 0.8865
[(1767229200.0, True)]
['human', 'trusted_agent'] 40 {}
```

The boss's first 30 values became `human` labels; its later 10, made after the gate
trusted it, became `trusted_agent` labels with no one checking them.

The Dojo stores nothing: the caller keeps the ledger, and every snapshot can be
recomputed from it. `history` is cached per ledger object (ledgers are immutable) and
recomputes only the candidates a person touched at each step; a test checks it against
the plain replay of `reviewer_agreement` as of every time.

## Settings

`config.GroundingSettings`, the `grounding` section of `Settings`, holds the tunable
thresholds. Only `grounding/` reads it, so no value here can move a headline score.

| Key | Default | Meaning |
| --- | --- | --- |
| `trust_bar` | 0.95 | Wilson lower bound an agent's `valid` precision must reach to be trusted |
| `trust_min_n` | 50 | `valid` verdicts with a human check (`n_agent_valid`) an agent needs before it can be trusted |
| `trust_window` | 200 | most recent paired checks the gate looks at (at least `trust_min_n`) |
| `certainty_floor` | 0.9 | least certainty an agent's `valid` needs to count |
| `spot_check_rate` | 0.10 | share of each agent's confirmations sampled for people |
| `spot_check_min_per_agent` | 20 | least sample per agent |

Set them in the YAML config (`LLM_DOJO_SCORING_CONFIG`) or the taxonomy passed to
`configure_from_taxonomy`, under a `grounding:` block, or with
`configure(grounding__trust_bar=0.97)` (or `configure(grounding=GroundingSettings(...))`).
Values must be finite numbers: rates in `[0, 1]`, counts whole numbers of at least 0
(`trust_min_n` at least 1, so no agent is trusted on zero checks), and
`trust_window ≥ trust_min_n` (overrides passed together are checked together). Every
path coerces alike: `trust_min_n: 40.0` (YAML), `grounding__trust_min_n=40.0` and
`grounding=GroundingSettings(trust_min_n=40.0)` all give `40`. A block that is not a
mapping (`false`, `0`, `""` and `[]` included) is an error; `grounding: null` and
`grounding: {}` change nothing. A bad
grounding value raises `ValueError` before anything in that config file or taxonomy is
applied, so every settings section keeps its old values; unknown keys in the block are
ignored. Updates change `get_settings().grounding` in place.

## Modules

| Module | Owns |
| --- | --- |
| `grounding/verdicts.py` | `value_verdict`, `VERDICTS`: one value against the document |
| `grounding/selection.py` | `unlabelled_fields`, `UNLABELLED_STATUSES`: the audited set |
| `grounding/audit.py` | `UnlabelledValueAudit`, `audit_unlabelled_values` |
| `grounding/summary.py` | `GroundingCounts`, `GroundingSummary`, `summarize_grounding`, `grounding_score_records`, `METRIC_IDS` |
| `grounding/candidates.py` | `ReviewCandidate`, `candidate_id`, `normalized_value`, `review_candidates`, `PRIORITY` |
| `grounding/ledger.py` | `Confirmation`, `ConfirmationReject`, `ConfirmationLedger`, `ingest_confirmations` |
| `grounding/labels.py` | `ValidLabel`, `LabelDerivation`, `derive_valid_labels`, `label_score_records`, `TrustLookup` |
| `grounding/io.py` | `read_jsonl`, `write_jsonl` |
| `grounding/agreement.py` | `PairedCheck`, `paired_checks`, `AgreementCounts`, `ReviewerAgreement`, `reviewer_agreement`, `agreement_score_records`, `select_spot_checks` |
| `grounding/trust.py` | `TrustGate`, `GateSnapshot`, `Regression` |
