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
  source schema, whatever their status).

The selection rule lives only in `grounding/selection.py:unlabelled_fields`. A list field
(`entity_list…`) is audited item by item; each item gets its own record and verdict.

## Verdicts

| Field type | `grounded` when | Otherwise |
| --- | --- | --- |
| `name`, `free_text` (and unknown types) | at least `field_scoring.verification_token_coverage` (default 0.7) of the value's content tokens appear in the document | `not_found`; `unverifiable` when the value has no content tokens |
| `date` | the document states the same date in any format (partial dates agree on every stated part) | `not_found`; text that is not a date uses the token rule |
| `money` | the document states the same amount (within half a cent) whatever its symbols, separators, currency words or K/M/B suffix | `not_found`; `unverifiable` when the value is not an amount |
| `id`, `cms_doc_ref` | the value is a substring of the document after casefolding and removing whitespace, `-`, `/` and `.` | `not_found` |
| `label` | never: a closed-vocabulary label is inferred, not quoted | always `unverifiable` |

Missing or blank document text makes every verdict `unverifiable`. The matchers are the
factuality audit's own (`scoring/field_scoring.py`), so a value grounded here is grounded
there. A new field type is one entry in `grounding/verdicts.py:_RULES`.

## Metrics

| Id | Tier | Value | Denominator |
| --- | --- | --- | --- |
| `grounding_not_found_rate` | 1 | `not_found / (grounded + not_found)` | checkable values; `unverifiable` excluded |
| `grounding_unverifiable_rate` | 2 | `unverifiable / n_audited` | all audited values |
| `grounding_n_audited` | 3 | audited values (list items counted singly) | — |

A rate with a zero denominator is `None`, never `0.0`. `grounding_score_records` emits
each metric for the run (`metadata.scope: "run"`), then per class (`"class"`,
`doc_class`), then per field (`"field"`, `doc_class`, `field`); every record carries
`metadata.denominator`.

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
for r in grounding_score_records(summary, agent="insurance_claims_specialist", run_id="run-1")[:3]:
    print(r.metric, r.value, r.metadata)
```

Output (run on this release):

```
claimed_amount grounded absent
adjuster not_found absent
coverage_determination unverifiable absent
{'grounded': 1, 'not_found': 1, 'unverifiable': 1, 'n_audited': 3, 'not_found_rate': 0.5, 'unverifiable_rate': 0.3333333333333333}
grounding_not_found_rate 0.5 {'scope': 'run', 'denominator': 2}
grounding_unverifiable_rate 0.3333333333333333 {'scope': 'run', 'denominator': 3}
grounding_n_audited 3 {'scope': 'run', 'denominator': 3}
```

## Modules

| Module | Owns |
| --- | --- |
| `grounding/verdicts.py` | `value_verdict`, `VERDICTS`: one value against the document |
| `grounding/selection.py` | `unlabelled_fields`, `UNLABELLED_STATUSES`: the audited set |
| `grounding/audit.py` | `UnlabelledValueAudit`, `audit_unlabelled_values` |
| `grounding/summary.py` | `GroundingCounts`, `GroundingSummary`, `summarize_grounding`, `grounding_score_records`, `METRIC_IDS` |
