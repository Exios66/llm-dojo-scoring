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
confirmation ledger and valid labels with provenance) and the reviewer-trust settings.
Agent agreement, the trust gate and spot-check sampling follow in stacked PRs
(`docs/superpowers/plans/2026-11-14-unlabelled-value-grounding-piece-3.md`); see the design
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

| Field type | `grounded` when | Otherwise |
| --- | --- | --- |
| `name`, `free_text` (and unknown types) | at least `field_scoring.verification_token_coverage` (default 0.7) of the value's content tokens appear in the document | `not_found`; `unverifiable` when the value has no content tokens |
| `date` | the document states the same date in any format (partial dates agree on every stated part) | `not_found`; text that is not a date uses the token rule |
| `money` | the document states the same amount (within half a cent, sign ignored) as money: with a currency symbol or word (spaces between it and the number on the same line are fine: `$ 500`, `500  dollars`), a scale (`5M`, upper case and attached, or `thousand`/`million`/`billion`), a thousands separator or two decimals. Bare integers in the text (a day, a year, a phone digit group) never count | `not_found`; `unverifiable` when the value is not an amount |
| `id`, `cms_doc_ref` | after casefolding and removing whitespace, `-`, `/` and `.`, the value equals one alphanumeric part of the text or up to six adjacent parts (`CLM 0001` matches `CLM-0001`; `12345` matches `INV-12345` and `No.12345`); a part is never split (`12` does not match inside `2012`) | `not_found`; `unverifiable` when shorter than three characters |
| `label` | never: a closed-vocabulary label is inferred, not quoted | always `unverifiable` |

Missing or blank document text makes every verdict `unverifiable`. Names, text and dates
reuse the factuality audit's matchers (`scoring/field_scoring.py`); amounts reuse its
money parser; the money and identifier boundary rules are this module's own. Per-document
work is cached (the last eight documents per cache), so auditing many values of one
document scans it once.

Known limitation: dates use the shared date matcher, which does not read ordinal
suffixes, so `2024-03-03` against "March 3rd, 2024" is `not_found`. Fixing that matcher
would change headline scores, so it is out of scope here. A new field type
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
| `verdict` | `valid`, `hallucinated` or `unsure` |
| `reviewer_kind` | `human` or `agent` |
| `reviewer_id` | non-blank. A human's starts with `human:` (`human:<opaque id>`) and an agent's never does (`boss@<prompt version>`, `jev-<version>`), so an agent cannot pass as a person. A new agent version is a new reviewer |
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
object with `trusted_snapshot_id(ledger, reviewer_id, at) -> str | None` (`TrustGate`
in piece 3). A later human `hallucinated` removes a label agents made; labels of a
`previous` export that are not derived now are returned as `withdrawn`.

`ValidLabel` (JSON, `schema_version: 1`): `doc_id`, `doc_class`, `field`, `item_index`,
`value`, `source_candidate_id`, `extractor`, `doc_text_sha256`, `confirmed_by` (every
latest confirmation: `reviewer_kind`, `reviewer_id`, `verdict`, `certainty`,
`confirmed_at`), `validity_basis` and `gate_snapshot_id`. `LabelDerivation` holds
`labels`, `rejected`, `conflicts` and `pending` (candidate id → reason) and `withdrawn`.

`io.write_jsonl(items, path, append=False)` and `io.read_jsonl(path)` move every record
type to and from local JSONL files. A replace is atomic and keeps an existing file's
permissions; an append first closes a torn last line; an unserialisable record or NaN
raises before anything is written; a bad line on read raises, naming the line. There is
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

## Settings

`config.GroundingSettings`, the `grounding` section of `Settings`, holds the tunable
thresholds. Only `grounding/` reads it, so no value here can move a headline score.

| Key | Default | Meaning |
| --- | --- | --- |
| `trust_bar` | 0.95 | Wilson lower bound an agent's `valid` precision must reach to be trusted |
| `trust_min_n` | 50 | paired human checks needed before an agent can be trusted |
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
