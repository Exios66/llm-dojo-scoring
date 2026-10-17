# Corporate-record entity schema — one contract per subclass

`corporate_record` is not one document shape. The flat nine-field `CorporateRecordExtraction` is a shared **core**; each sorter `doc_subclass` adds its own **key entities** and drops core fields that do not apply to it. The data lives in `llm_dojo_scoring.corporate_record_schema`; the specialist prompt section is generated from it (a test asserts they match).

```python
from llm_dojo_scoring import (
    corporate_record_subclass_schema, corporate_record_field_types,
    corporate_record_json_schema, render_corporate_record_block,
    audit_corporate_record_labels)

corporate_record_subclass_schema('indenture').entities   # trustee, guarantors, ...
corporate_record_field_types('indenture', gt)            # core + labeled entities
suite.score_document(gt, pred, doc_subclass='indenture')
```

## Why

Audited against `mailroom-dataset` **v9.2** (tag `v9.2`, data `d49f60a4…`; the v9 cache gives identical entity/label findings — v9.2 only re-labels `annotation_method`, which is now `heuristic` on all 450 rows). The published GT (450 `corporate_record` rows) labels **none** of `entity_name`, `record_type`, `effective_date`, `signatories`, `jurisdiction`, `filing_number` on any row. Only `intent` / `subject_matter` / `keywords` are populated, and those are provenance boilerplate (`subject_matter` = `<subclass> of <Company> (CIK …) (SEC EDGAR exhibit)` on 411 rows; `keywords` carry exhibit numbers, form types, accession numbers and CIKs on 412; `intent` is a 1:1 function of subclass, 450/450 `heuristic`/`auto_labeled`). Scoring that GT as "expected empty" rewarded models for **not** extracting entities: a fully correct extraction scored precision 0.375.

The 39 legacy S-1 rows have prose labels but a coarse `expected_subclass`: 14 rows carry a subclass that disagrees with their own `subject_matter` (e.g. "Bylaws of …" under `articles_of_incorporation` ×8 / `powers_of_attorney` ×2, organizational minutes, registration-rights agreements and specimen certificates under `articles_of_incorporation`). The per-subclass schema is only as reliable as `expected_subclass`; the audit reports these as `subclass_content_conflict:<subclass>`.

## Scoring rule — unlabeled vs. absent

A key-entity field that is blank in GT is **expected empty** only if `gt_presence` says `schema_documented_absence` / `not_applicable`. A blank with no such statement is **unlabeled**: it is dropped from both expected and predicted (reported as `unlabeled_fields` on the score payload), so neither a filled nor an empty prediction is scored. Once the dataset labels a field (`populated`, or a documented absence), it is scored normally and a spurious fill is an FP again. Extension entities are scored only when labeled; stray keys from another subclass never count as spurious fill. Pass `doc_subclass=` (scalar, or a list for batches) to `score` / `score_document`.

## Subclasses

`record_type` stays the 5-token Hub enum; `doc_subclass` is the authority for which schema applies. `intent` is the value the published GT pins for the subclass.

| Subclass | `record_type` | `intent` (pinned) | Not applicable (core) | Key entities (extension fields) |
|---|---|---|---|---|
| `bylaws` | `bylaws` | `governance_rules` | `filing_number` | `certifying_officer`, `last_amended_date` |
| `articles_of_incorporation` | `articles_of_incorporation` | `entity_formation` | — | `incorporators`, `registered_agent`*, `authorized_capital` |
| `certificate_of_formation` | `articles_of_incorporation` | `entity_formation` | — | `organizers`, `registered_agent`* |
| `charter_amendment` | `articles_of_incorporation` | `entity_formation` | — | `amended_provisions`*, `approval_date`, `prior_entity_name` |
| `powers_of_attorney` | `powers_of_attorney` | `authority_delegation` | `filing_number` | `principal`*, `attorneys_in_fact`*, `authority_scope`, `expiration_date` |
| `subsidiary_list` | `other` | `other` | `signatories`, `jurisdiction`, `filing_number` | `subsidiaries`*, `subsidiary_jurisdictions` |
| `rights_instrument` | `rights_instrument` | `investor_rights` | `filing_number` | `instrument_kind`*, `holder`, `rights_agent`, `securities_covered`, `exercise_price` |
| `indenture` | `other` | `investor_rights` | `filing_number` | `trustee`*, `guarantors`, `securities_series`*, `principal_amount`, `maturity_date` |
| `board_resolution` | `other` | `corporate_action_approval` | `filing_number` | `acting_body`*, `action_approved`*, `resolutions` |
| `officer_certificate` | `other` | `governance_rules` | `filing_number` | `certifying_officer`*, `officer_title`*, `certified_matter`*, `addressee` |
| `other` | `other` | `other` | — | — |

`*` = expected on a well-formed instance. Entity types, where-to-look hints and notes: `SUBCLASS_SCHEMAS[...]`.

`entity_name` is always the company the record belongs to (registrant / issuer / parent) — never a counterparty, trustee or signer. Principals, trustees and agents have their own fields.

Pinned intents the schema flags for review (`SubclassSchema.intent_review`): `charter_amendment`, `indenture`, `officer_certificate`. They are kept so existing scores stay comparable.

## Dataset labels — repair tooling

`python scripts/relabel_corporate_record_gt.py OUT.jsonl <ground_truth parquet…>` (module `corporate_record_relabel`) writes a repaired **proposal** — it never publishes. On v9.2 it: populates `entity_name` (411 rows, from the company already named in the template) and `record_type` (450, from the subclass map); replaces 411 template `subject_matter`; strips provenance IDs from 422 `keywords`; re-assigns 12 conflicting `expected_subclass` (+ re-pins their `intent`); marks inapplicable fields `not_applicable`. Everything else stays *unlabeled* (jurisdiction, signatories, dates, filing numbers, subclass entities) and needs real annotation; 2 conflicts are ambiguous and stay flagged; `intent` remains `heuristic`. Review the JSONL, then push to the Hub.

## Dataset labels — what has to change

`python scripts/audit_corporate_record_labels.py <ground_truth parquet…>` reports, per subclass: unlabeled entity fields, `subject_matter_template`, `keywords_provenance_ids`, `intent_mismatch`, `intent_heuristic`, `subclass_content_conflict:*`, `entity_wrong_subclass:*`. To close the gap in the dataset (outside this repo):

1. Label each subclass's core + extension entities in `gt_fields`, setting `gt_presence` to `populated` or `schema_documented_absence` for every entity field of the subclass (`not_applicable` for the rest).
2. Replace template `subject_matter` with one grounded sentence; drop exhibit/form/accession/CIK strings from `keywords`.
3. Fix the 14 subclass/content conflicts (or add subclasses for minutes, registration-rights agreements and specimen certificates); re-adjudicate the flagged intents; record `intent_source` other than `heuristic`.
4. Re-pin the taxonomy fixture only when core fields change; extension entities do not touch `DEFAULT_FIELD_TYPES`.

## Specialist prompt

`corporate_records_specialist` (`production` and `production_prompts`, identical text, `sha256 b40963bb…`) now carries one generated line per subclass (`record_type, intent; +extra keys; null …`) in place of the old executive brief, plus the `entity_name` rule — 5,333 chars, 532 *shorter* than frozen v1 (5,865). This diverges from the vendored mailroom `frozen_v1` bytes; the same change must land in llm-mailroom and eval-environment (`prompts/corporate_records_specialist_v1.md`) before the next `sync_production_prompts.py --check`. The legacy `docclass` stem is unchanged (retired `key_provisions` lineage).

## Known limits of the repaired labels

- `entity_name` comes from the EDGAR filer metadata in the template `subject_matter`, not from document text; ~25% differ from the in-document name (mostly `CO`/`Company` style). Treat it as the registrant, not a verbatim string.
- `DOC-85c7b49cdac19586` (organizational minutes approving bylaws) matches two subclass cues and is deliberately not auto-reassigned; it is probably `board_resolution`.
- All 450 intents remain `intent_source: heuristic`; the relabel never overrides an adjudicated intent, `record_type`, or a populated `filing_number`.
- Extension entities are scored only once the dataset labels them (`gt_presence` `populated` / `schema_documented_absence`); `pending_annotation` and unstated blanks are unlabeled.
