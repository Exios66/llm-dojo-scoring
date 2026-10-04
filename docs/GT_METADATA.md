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

`llm_dojo_scoring.gt_metadata` is the parser/normalizer every suite runs
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
