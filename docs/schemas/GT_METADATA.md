# Hub GT metadata (`gt_fields`) handling

`Lucius-Morningstar/mailroom-dataset` stores per-document ground truth as a
**union field dict**: every live class's fields, the content differentiators,
annotation stats, and a stringified `gt_presence` map. Only a subset applies
to any one document, and many values are stringified JSON containers.

```json
{
  "adjuster": "", "claim_number": "", "cuad_clause_labels": "{}",
  "denial_reasons": "[]", "keywords": "[\"Bylaws\", \"stockholders\"]",
  "gt_presence": "{\"adjuster\": \"not_applicable\", \"intent\": \"populated\", ...}",
  "intent": "authority_delegation", "subject_matter": "Bylaws of ..."
}
```

`llm_dojo_scoring.schemas.gt_metadata` is the parser/normalizer every suite runs
before scoring (`ScoringSuite._score_extraction`). It guarantees:

1. **Stringified JSON is parsed.** `"[]"` / `"{}"` are empty; a stringified
   list compares as a list, so a correct model list is not scored as one
   giant string element.
2. **Absent fields are never required events.** `gt_presence` values
   `not_applicable`, `schema_documented_absence`, and `pending_annotation`
   (label backfill not yet run) are replaced with `""`
   (`ABSENT_PRESENCE_STATUSES`) — including stale non-empty values attached
   to a pending field — and no presence expectations are derived from a
   pending `cuad_clause_labels`. A model that correctly emits nothing for
   them is not penalized; filling one is still a spurious fill (FP), which is
   the honest signal.
3. **Only the document type's own label set is scored.** When the row carries
   `gt_presence` (the Hub contract), fields are scoped to that suite's
   extraction schema plus the content differentiators its extras can score.
   Another class's fields, and annotation stats (`token_estimate`,
   `intent_status`, `context_window_band`, `related_document_ids`, …), never
   reach extraction scoring. Plain field dicts from historical consumers keep
   their unmapped keys (`drop_unmapped=False` path).
4. **Presence labels drive the presence scorer.** `cuad_clause_labels`
   (`{category: [{start, text}, …]}`) is converted to
   `score_category_presence` expectations: a category with spans is
   `expected: True` with its clause text as the answer; empty categories are
   recorded but never scored. Presence-only rows keep extraction
   P/R/F1/F2 **null** instead of a misleading 0.0.

## Per-class GT label alignment

| Specialist (class) | Populated Hub GT labels | How they are scored |
|---|---|---|
| `contracts_specialist` (`contract`) | `cuad_clause_labels`, `maud_clause_labels` | CUAD category presence via derived expectations; MAUD per-question scorer. Triage-only rows (no populated label) stay **unscorable** |
| `merger_agreement_specialist` | `maud_clause_labels`, `intent`, `keywords`, `subject_matter` | MAUD per-question scorer + typed extraction (`MergerAgreementExtraction`, never the contract map) |
| `corporate_records_specialist` (`corporate_record`) | `intent`, `keywords`, `subject_matter` | Typed extraction |
| `correspondence_specialist` (`correspondence`) | `content_topic`, `sentiment_label`, `intent`, `keywords`, `subject_matter` | Enron content scorers (topic/sentiment) + typed extraction |
| `insurance_claims_specialist` (`insurance_claim`) | `claim_number`, `claim_type`, `claimed_amount`, `coverage_determination`, `damages_description`, `date_filed`, `date_of_loss`, `insured_party`, `insurer`, `intent`, `keywords`, `policy_number`, `subject_matter`, `supporting_documents`, `adjuster`, `denial_reasons` | Typed extraction; `adjuster` / `denial_reasons` are frequently `schema_documented_absence` (CMS rows / approved claims) |

Verified against the published corpus (2026-10-04): every `populated` key in
both splits (3,302 rows) is inside its class's field map or a handled content
/ presence key — there are no orphan GT labels.

## Correspondence GT audit (#94)

The SAND-042 RCA found correspondence scored on three of eleven live fields
(`intent`, `subject_matter`, `keywords`). It also *inferred*, without checking
the Hub rows, that `subject_matter` / `keywords` are templated
(`"Correspondence concerning general_business."`, folder and timestamp
tokens). `llm_dojo_scoring.schemas.correspondence_gt_audit` measures both:

```bash
python scripts/audit_correspondence_gt.py ground_truth.parquet   # or a JSONL export; --json for the raw report
```

| Code | Meaning |
| --- | --- |
| `subject_matter_templated` | a `Correspondence concerning <topic>.` frame, or an embedded snake_case topic key |
| `keywords_metadata` | at least one keyword is *strong* metadata: a topic key, a date **and** time stamp, a path with a folder segment, or an underscore-prefixed folder (`_sent_mail`). *Weak* tokens (communication type such as `email` / `press release`, plain folder names, mailbox ids like `delainey-d` / `williams-w3`, bare dates, bare clock times, email addresses) never fire alone, because genuine content keywords look like them |
| `keywords_all_metadata` | every keyword is strong or weak, and at least one is strong (the templated 5-slot shape `[topic, communication type, mailbox id, folder, ISO timestamp]`) |
| `intent_missing` | no usable `intent` GT (population fact; does not fail the script) |
| `gt_unparseable` | `gt_fields` could not be parsed |

The report also gives `field_population` (rows with GT per live field),
`populated_field_counts` and `unscored_fields`. Exit status: `0` clean, `1`
when a templated, metadata or unparseable defect is found, `2` when the audit
could not run (unreadable or malformed file, a row that is not an object, or
no correspondence rows; the reason goes to stderr).

`is_metadata_keyword(value)` answers "could be metadata" (strong or weak);
`metadata_keyword_kind(value)` returns `"strong"`, `"weak"` or `None`.

Known gaps: mailbox ids with underscores or digits in the owner part
(`bill_williams_iii`) and user-specific folder names (`power`, `tw_commercial_group`)
are not recognised, so `keywords_all_metadata` slightly under-counts templated
rows. Mailbox-shaped content words (`plan-b`, `vitamin-c`) are weak, so they
cannot fire the audit alone.

Status: the detectors are in place. On the 1,000 Hub correspondence rows they
flag 904 `subject_matter_templated`, 904 `keywords_metadata` and 860
`keywords_all_metadata`; none of the 96 non-templated rows fires
`keywords_metadata`. The relabel proposal and human-review export (#94 steps 2–3) wait on
those numbers. Until the GT is relabelled:

- the correspondence headline is reported with `headline_scope: "partial"`
  (see [`SCORECARD_HONESTY.md`](../contracts/SCORECARD_HONESTY.md));
- `aggregate_quality_honest(..., doc_class=...)` adds `intent_split`
  (intent mean, hit / miss counts, mean of the other fields), so the
  intent-driven bimodality is visible.

A relabel changes correspondence scores, which is a comparability break that
must be recorded in the CHANGELOG and `metrics.score_changelog`.

## Public API

```python
from llm_dojo_scoring import (
    parse_gt_fields,          # JSON string / repr / dict -> dict (nested JSON parsed)
    scoring_gt_fields,        # scope to a suite's field map + extras
    get_suite,                # suite lookup for per-class field maps
    gt_presence_map,          # the parsed gt_presence status map
    derive_presence_from_gt,  # CUAD labels -> score_category_presence expectations
    is_empty_value,           # None / blank / "null" / "[]" / "{}" / empty collections
    parse_json_container,
)

fields = parse_gt_fields(row["gt_fields"])
out = get_suite("insurance_claims_specialist").score_document(fields, predicted)
```

The dataset's `expected` column is the **doc-class label** (`"contract"`,
`"insurance_claim"`, …), not the field dict. Passing it as GT fails closed
with `gt_wrong_schema` instead of crashing.

## Evidence (replay over the full published corpus, 3,302 rows)

A perfect prediction built from the normalized GT scored through the suites,
over **both splits** (`ground_truth` test 323 + train 2,979):

| Split | Rows | Extraction events | FN | FP | Spurious | F1 < 1.0 | Presence < 1.0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| test | 323 | 2,009 | 0 | 0 | 0 | 0 | 0 |
| train | 2,979 | 17,915 | 0 | 0 | 0 | 0 | 0 |
| **total** | **3,302** | **19,924** | **0** | **0** | **0** | **0** | **0** |

- 91 triage-only contract rows (6 test + 85 train) are correctly
  `unscorable` — never a fabricated 0.0. All 91 carry
  `cuad_clause_labels: "{}"` with `gt_presence` status `pending_annotation`
  (the label backfill has not run); they become scorable automatically once
  the backfill populates the labels.
- Placeholder GT values are handled: populated `N/A` dates are empty, and
  CUAD spans with no alphanumeric content (`[*]`, `[●]`, `____`, `.`) are
  omitted from presence expectations instead of counting against a model that
  cannot quote them.

Offline fixtures mirroring these rows live in `tests/test_gt_metadata.py`.
