# Entity extraction schemas — mailroom-dataset (Dojo v0.20.0)

Pared live field maps for the **five primary document types** in
[`Lucius-Morningstar/mailroom-dataset`](https://huggingface.co/datasets/Lucius-Morningstar/mailroom-dataset)
(`ground_truth` config, v9 GT-closure pin `46a4d3c2`, **3,302** rows:
2,979 train / 323 test). Authority is the dojo live roster, not the
retired specialists.

| Pin | Value |
|---|---|
| Package | `llm-dojo-scoring` **v0.20.0** |
| Field maps | `DEFAULT_FIELD_TYPES` ≡ `CORPUS_EXTRACTION_FIELDS` ≡ taxonomy fixture `tests/fixtures/taxonomy_field_types.json` |
| Taxonomy blob | llm-mailroom `src/config/taxonomy.yaml` SHA-1 `ca297bd8e55e62b79ee452b02b65926b5032bdf1` |
| Frozen prompts | `get_prompt(<agent>, family="production_prompts")` — eval-environment v1, frozen 2026-09-26T05:09:29+00:00 |
| Live classes | `contract` · `merger_agreement` · `corporate_record` · `correspondence` · `insurance_claim` |
| Not live | `unknown` (routing only) · `court_opinion` / `due_diligence` / `compliance_filing` (retired; zero corpus rows) |

Hub `gt_fields` is a **union dict**. Score only the class's own keys
([`GT_METADATA.md`](GT_METADATA.md)). `merger_agreement` is
`MergerAgreementExtraction`, never a CUAD `contract` alias.

```python
from llm_dojo_scoring import get_suite
from llm_dojo_scoring.corpus import suite_schema
from llm_dojo_scoring.prompts import get_prompt

suite_schema("insurance_claim")
get_suite("merger_agreement_specialist").field_types
get_prompt("contracts_specialist", family="production_prompts").text
```

## Corpus composition (v9)

| `doc_type` | Rows | Share | Source | Schema / specialist |
|---|---:|---:|---|---|
| `contract` | 600 | 18.2% | CUAD v1 (509) + SEC EDGAR EX-10 (91) | `ContractExtraction` / `contracts_specialist` |
| `merger_agreement` | 152 | 4.6% | MAUD v1 | `MergerAgreementExtraction` / `merger_agreement_specialist` |
| `corporate_record` | 450 | 13.6% | SEC EDGAR S-1/8-K exhibits | `CorporateRecordExtraction` / `corporate_records_specialist` |
| `correspondence` | 1,000 | 30.3% | Enron (dedup pool) | `CorrespondenceExtraction` / `correspondence_specialist` |
| `insurance_claim` | 1,100 | 33.3% | CMS DE-SynPUF + GNOTHEIA + BDR + INSURBIAS | `InsuranceClaimExtraction` / `insurance_claims_specialist` |
| **total** | **3,302** | 100% | | **58 field slots** across the five maps |

91 EX-10 contracts are triage-only (`cuad_clause_labels` =
`pending_annotation`) and stay **unscorable** until clause backfill.

## Scoring types

| Type | Match rule |
|---|---|
| `id` | Uppercase, strip punctuation/whitespace, exact |
| `date` | Canonical ISO date; containment + partial-credit fallbacks |
| `money` | Parse to float, ±$0.01; unparseable prose → fuzzy string |
| `name` | Jaro–Winkler + token-set; containment first |
| `label` | Controlled vocabulary: canonicalized via `normalize_intent`, then exact match — no partial credit, no embedding rescue |
| `free_text` | SQuAD-style token F1 |
| `entity_list` | Hungarian bipartite match, then set P/R/F1 |
| `entity_list:name` | List items scored as `name` |
| `entity_list:free_text` | List items scored as `free_text` |

Untyped `entity_list` (correspondence `additional_recipients` /
`action_items`, insurance `supporting_documents`) uses name-style item
matching.

**Empty-field contract.** Unstated scalar → `null`; unstated list → `[]`.
Correct emptiness is credit **1.0** and is **not** folded into archive
`overall_score`. Spurious fill is an FP. Numeric **zero is a stated
amount**, not absence.

**Never scored:** `confidence`, `reasoning`, Hub annotation stats
(`token_estimate`, `intent_status`, …). Corporate-record v1 does not
emit `confidence`.

**Retired (do not emit):** `key_obligations`, `termination_clauses`,
`key_provisions`, `key_points`, `referenced_communications`.

---

## 1. `contract` — `ContractExtraction` (11 fields)

CUAD commercial contracts only. Sorter `doc_subclass` / `contract_subtype`
is situational context for `cuad_family`; verify against operative text.
Do **not** emit `intent` / `subject_matter` / `keywords` /
`effective_time`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `document_name` | `name` | `null` | Title as stated; never from filename |
| `parties` | `entity_list:name` | `[]` | Full legal name + parenthetical alias when given |
| `effective_date` | `date` | `null` | ISO `YYYY-MM-DD`; defined Effective Date beats signature date |
| `term_length` | `free_text` | `null` | Duration of **the agreement**, not a sub-period |
| `governing_law` | `name` | `null` | Governing-law sentence only; no forum/venue |
| `contract_value` | `money` | `null` | Currency phrase as written (`"$2,000,000"`); do not compute |
| `renewal_terms` | `free_text` | `null` | Renewal / evergreen / rollover language |
| `cuad_family` | `name` | `null` | Exactly one of 25 CUAD keys, or `other` |
| `merger_consideration` | `name` | `null` | **Always `null` on CUAD rows** (parse-compat) |
| `cuad_clauses` | `entity_list:free_text` | `[]` | `'<Atticus category>: <verbatim span>'` — present only |
| `maud_clauses` | `entity_list:free_text` | `[]` | **Always `[]` on CUAD rows** (parse-compat) |

**Subclass (sorter):** 25 CUAD families —
`affiliate`, `agency`, `collaboration`, `co_branding`, `consulting`,
`development`, `distributor`, `endorsement`, `franchise`, `hosting`,
`ip`, `joint_venture`, `license`, `maintenance`, `manufacturing`,
`marketing`, `non_compete_no_solicit`, `outsourcing`, `promotion`,
`reseller`, `service`, `sponsorship`, `strategic_alliance`, `supply`,
`transportation` — plus unknown bucket `other`. Folder surfaces
(`License_Agreements`, `Joint Venture _ Filing`, …) normalize through
`normalize_subtype`.

**`cuad_clauses` Atticus names (41; emit only those present):**
Document Name; Parties; Agreement Date; Effective Date; Expiration Date;
Renewal Term; Notice Period To Terminate Renewal; Governing Law; Most
Favored Nation; Competitive Restriction Exception; Non-Compete;
Exclusivity; No-Solicit Of Customers; No-Solicit Of Employees;
Non-Disparagement; Termination For Convenience; Rofr/Rofo/Rofn; Change
Of Control; Anti-Assignment; Revenue/Profit Sharing; Price Restrictions;
Minimum Commitment; Volume Restriction; Ip Ownership Assignment; Joint
Ip Ownership; License Grant; Non-Transferable License; Affiliate
License-Licensor; Affiliate License-Licensee;
Unlimited/All-You-Can-Eat-License; Irrevocable Or Perpetual License;
Source Code Escrow; Post-Termination Services; Audit Rights; Uncapped
Liability; Cap On Liability; Liquidated Damages; Warranty Duration;
Insurance; Covenant Not To Sue; Third Party Beneficiary.

**GT extras (not schema keys):** `expected_subclass`,
`cuad_clause_labels` → category-presence scorer. 91 EX-10 rows remain
`unscorable`.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1` /
`_f2`, `maud.question.micro_accuracy`.

**Frozen prompt:** `contracts_specialist` `sha256 d91de396…` (byte-identical
to sandbox `contracts_specialist_v33_simplified`).

---

## 2. `merger_agreement` — `MergerAgreementExtraction` (10 fields)

Agreement and Plan of Merger (including amended/restated). **Not** the
CUAD extractor: never emit `cuad_family` or `cuad_clauses`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `document_name` | `name` | `null` | Title as stated |
| `parties` | `entity_list:name` | `[]` | Parent, Merger Sub, Target, other named entities |
| `effective_date` | `date` | `null` | Calendar date only; **null when only an Effective Time exists** |
| `effective_time` | `free_text` | `null` | Clock / TZ / defined-term Effective Time |
| `governing_law` | `name` | `null` | Governing-law sentence; no forum/venue |
| `merger_consideration` | `name` | `null` | One token: `all_cash` · `all_stock` · `mixed_cash_stock` · `mixed_cash_stock_election` · `other` |
| `maud_clauses` | `entity_list:free_text` | `[]` | `'<Question>: <Hub valid_class>'`; omit unanswered; never `"not specified"` |
| `intent` | `name` | `null` | Short label (`effect_merger`, `amend_merger`, `plan_of_merger`, …) |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases copied from the text |

**Subclass = MAUD Type of Consideration** (same five tokens as
`merger_consideration`). `mixed_cash_stock` ↔
`mixed_cash_stock_election` are family-equivalent.

**22 MAUD question names (exact):**
Absence of Litigation Closing Condition; Accuracy of Target R&W Closing
Condition; Agreement provides for matching rights in connection with COR;
Agreement provides for matching rights in connection with FTR; Breach of
Meeting Covenant; Breach of No Shop; Compliance with Covenant Closing
Condition; FTR Triggers; Fiduciary exception to COR covenant;
Fiduciary exception:  Board determination (no-shop); General Antitrust
Efforts Standard; Intervening Event Definition; Knowledge Definition;
Limitations on FTR Exercise; MAE Definition; Negative interim operating
covenant; No-Shop; Ordinary course covenant; Specific Performance;
Superior Offer Definition; Tail Period & Acquisition Proposal Details;
Type of Consideration.

Answers must be the row's Hub `valid_classes` ([`MAUD_LABELS.md`](MAUD_LABELS.md)).
Ambiguous collapsed GT is `unscorable` on those keys, not a guessed match.

**GT extras:** `expected_subclass`, `maud_clause_labels`. MAUD-only rows
still score the content metric.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`maud.question.micro_accuracy`, `maud.clause_presence.rate`,
`pipeline.extraction.field_micro_f1` / `_f2`.

**Frozen prompt:** `merger_agreement_specialist` `sha256 00323258…`.

---

## 3. `corporate_record` — `CorporateRecordExtraction` (9 fields)

Governance instruments. Do **not** emit `document_name`, `parties`,
`cuad_*`, or SEC form types as `record_type`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `entity_name` | `name` | `null` | Legal name as written |
| `record_type` | `name` | `null` | **Extraction enum (5):** `articles_of_incorporation` · `bylaws` · `powers_of_attorney` · `rights_instrument` · `other` |
| `effective_date` | `date` | `null` | ISO when a calendar date is stated |
| `signatories` | `entity_list:name` | `[]` | Execution / approval names |
| `jurisdiction` | `name` | `null` | State/country of incorporation or governing jurisdiction |
| `filing_number` | `id` | `null` | Official file/document number **only**. Exhibit IDs and parent-agreement dockets do **not** qualify (v0.19.1 re-freeze) |
| `intent` | `label` | `null` | `governance_rules` · `corporate_action_approval` · `entity_formation` · `authority_delegation` · `investor_rights` · `other`. Canonicalized via `normalize_intent`; exact match. (`DEFAULT_FIELD_TYPES` still maps `intent` to `name` until the taxonomy fixture is re-pinned; `label` applies where the field-type map says so.) |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases from the text |

**Sorter subclass (11) vs extraction `record_type` (5).** Map, don't echo:

| `doc_subclass` | `record_type` |
|---|---|
| `bylaws` | `bylaws` |
| `articles_of_incorporation` · `certificate_of_formation` · `charter_amendment` | `articles_of_incorporation` |
| `powers_of_attorney` | `powers_of_attorney` |
| `rights_instrument` | `rights_instrument` |
| `subsidiary_list` · `indenture` · `board_resolution` · `officer_certificate` · `other` | `other` |

Hub inventory has the 10 surfaces above except
`certificate_of_formation` (scoring catalog keeps it as an LLC-formation
alias of `articles_of_incorporation`). Corpus GT currently covers that
Hub subset.

**v0.19.1:** `subsidiary_list` keeps `filing_number` null unless an
official filing/document number is on **this** record.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`pipeline.extraction.field_micro_f1` / `_f2`. No CUAD/MAUD-grade external
benchmark.

**Frozen prompt:** `corporate_records_specialist` `sha256 fe13501f…`
(locally corrected; upstream eval-environment re-freeze tracked in
[`TODOS.md`](TODOS.md)).

---

## 4. `correspondence` — `CorrespondenceExtraction` (11 fields)

Letters, email, memos, notices, demands, meeting invites, press. Dollars
go in `demand_amount`, never insurance `claimed_amount`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `sender` | `name` | `null` | Name / title / entity as written; press = issuer or media contact |
| `recipient` | `name` | `null` | Named addressee; press/wire with none → `null` |
| `additional_recipients` | `entity_list` | `[]` | CC / copied parties |
| `communication_type` | `name` | `null` | **8 tokens only** (see below). Unregistered form → `null`, **not** `other` (v0.19.1 re-freeze) |
| `communication_date` | `date` | `null` | Date **sent** (ISO); not a deadline, meeting, or invoice date |
| `demand_amount` | `money` | `null` | Exact dollars demanded; most non-demand mail is `null` |
| `action_items` | `entity_list` | `[]` | ≤3 concrete actions with deadlines if stated |
| `urgency` | `name` | never `null` | `routine` · `time-sensitive` · `urgent` · `critical`. Unspecified → `routine` |
| `intent` | `label` | `null` | `payment_demand` · `notice` · `analysis` · `request` · `update` · `meeting_invite` · `press_communication` · `other`. Canonicalized via `normalize_intent`; exact match. (`DEFAULT_FIELD_TYPES` still maps `intent` to `name` until the taxonomy fixture is re-pinned; `label` applies where the field-type map says so.) |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases from the text |

**`communication_type` vocabulary (8):** `email`, `letter`, `memo`,
`notice`, `demand`, `attorney_demand`, `press_release`,
`meeting_request`. Sorter subclass catalog adds an `other` bucket; the
extractor must emit `null` there. v8 `voicemail` is **not** in v9 GT and
normalizes to `other` for classification only.

**Content extras (scored, not schema keys).** Enron GT on all 1,000
rows: `content_topic` (11) —
`announcements`, `energy_market`, `finance_earnings`, `general_business`,
`hr_personnel`, `it_systems`, `legal_contracts`, `marketing_clients`,
`regulatory`, `scheduling`, `travel_logistics` — and `sentiment_label`
(`negative` 180 / `neutral` 566 / `positive` 254). Content-only rows
still score those metrics.

**Allowed `metric_id`:** extraction overall + field-micro F1/F2, plus
`pipeline.enron.topic_accuracy` / `topic_f1_macro` /
`sentiment_accuracy` / `sentiment_f1_macro`.

**Frozen prompt:** `correspondence_specialist` `sha256 2b0b81ff…`
(locally corrected `communication_type` fallback).

---

## 5. `insurance_claim` — `InsuranceClaimExtraction` (17 fields)

FNOL, adjuster reports, coverage/denial letters, CMS/DE-SynPUF tables,
EOBs. Dollars go in `claimed_amount`, never correspondence
`demand_amount`. An insurance **policy** sold to the insured is a
`contract`; if this specialist is reading one, still fill only claim
fields the text states.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `claim_number` | `id` | `null` | Exact printed id (CLAIM NO., FNOL, CLM_ID, CMS Notice ID) |
| `policy_number` | `id` | `null` | Exact printed policy number |
| `insurer` | `name` | `null` | Carrier as written |
| `insured_party` | `name` | `null` | Named insured / claimant |
| `claim_type` | `name` | `null` | Extract enum **orthogonal** to subclass (see below) |
| `date_of_loss` | `date` | `null` | Loss/event date (ISO) |
| `date_filed` | `date` | `null` | Filing date; not date of loss |
| `claimed_amount` | `money` | `null` | Amount as stated; CMS MSN = Medicare paid total; do not compute |
| `adjuster` | `name` | `null` | Named adjuster only; CMS/GNOTHEIA/INSURBIAS often `null` (valid) |
| `damages_description` | `free_text` | `null` | Loss/damages as described |
| `coverage_determination` | `name` | `null` | As written: `approved` · `denied` · `partial` · `pending`. Never infer from tone |
| `denial_reasons` | `entity_list:free_text` | `[]` | Stated grounds; `[]` when approved / pending / unstated |
| `supporting_documents` | `entity_list` | `[]` | Referenced docs; CMS provider/NPI lines belong here |
| `intent` | `label` | `null` | `claim_filing` · `coverage_determination` · `loss_report` · `claim_data_record` · `other`. Canonicalized via `normalize_intent`; exact match. (`DEFAULT_FIELD_TYPES` still maps `intent` to `name` until the taxonomy fixture is re-pinned; `label` applies where the field-type map says so.) |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases from the text |
| `claim_checklist` | `entity_list:free_text` | `[]` | `'<Category>: <evidence>'` — present only |

**Subclass (6, sorter / Hub):** `carrier` · `inpatient` · `outpatient` ·
`pde` · `property` · `auto`.

**`claim_type` extract enum (11):** those six, plus legacy FNOL lines
`liability` · `health` · `life` · `workers_comp` · `other`. Product-line
`health` is **not** a subclass (`normalize_corpus_subclass(..., "health")`
→ `other`).

**`claim_checklist` categories:** Coverage Determination; Policy Limits;
Exclusions Cited; Deductible; Reservation Of Rights; Timely Notice; Proof
Of Loss; Subrogation; Independent Medical Exam; Amount Consistency.

**Class extras:** `determination_consistency` (`approved` ⇒ empty
reasons; `denied`/`partial` ⇒ nonempty; missing determination ⇒ 0.0),
`amount_exactness`, `schema_promotion_gate` (default 0.90). Published GT
is homogeneous (`coverage_determination=approved`, empty denials), so
consistency is degenerate on GT-shaped predictions.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`pipeline.extraction.field_micro_f1` / `_f2`.

**Frozen prompt:** `insurance_claims_specialist` `sha256 6c2776bc…`.

---

## Cross-class rules (v0.20.0)

1. **One schema per document.** Fill only that class's keys. Foreign keys
   (`claim_number` on a letter, `sender` on a claim) are out of schema.
2. **Semantic trio** (`intent`, `subject_matter`, `keywords`) is live on
   merger, corporate record, correspondence, and insurance — **not** on
   CUAD `contract`.
3. **Sorter handoff is context, not a JSON field.** Never echo
   `doc_subclass` / `contract_subtype` as its own key; map it onto
   `cuad_family` / `merger_consideration` / `record_type` /
   `communication_type` / `claim_type` after reading the text.
4. **Hub union GT.** `parse_gt_fields` + `scoring_gt_fields(..., drop_unmapped=True)`
   before scoring. `not_applicable` / `schema_documented_absence` /
   `pending_annotation` are never required events. Passing the class-label
   string as GT fails closed (`gt_wrong_schema`).
5. **Perfect-prediction replay** (both splits, 3,302 rows, 19,924
   extraction events): 0 FN / 0 FP / 0 spurious fills; 91 triage-only
   contracts stay `unscorable`.
6. **Prompt freeze vs live `production` family.** Eval stems are
   `family="production_prompts"`. Since v0.20.0 the five `production`
   specialists are re-vendored from live mailroom and **equal**
   `production_prompts` v1 (`version: v1`, `source_key: frozen_v1`); the
   retired `contracts_specialist_v32` body is gone. Do not mix the
   `docclass` lineage into a comparison table without matching `prompt_id`.

## Import surface

```python
from llm_dojo_scoring import get_suite, LIVE_DOC_TYPES
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES
from llm_dojo_scoring.corpus import CORPUS_EXTRACTION_FIELDS, suite_schema

assert tuple(LIVE_DOC_TYPES) == (
    "contract", "merger_agreement", "corporate_record",
    "correspondence", "insurance_claim",
)
for doc_type in LIVE_DOC_TYPES:
    assert set(DEFAULT_FIELD_TYPES[doc_type]) == set(CORPUS_EXTRACTION_FIELDS[doc_type])

out = get_suite("insurance_claims_specialist").score_document(expected, predicted)
```

Related: [`SCORING.md`](SCORING.md) · [`GT_METADATA.md`](GT_METADATA.md) ·
[`METRIC_IDS.md`](METRIC_IDS.md) · [`MAUD_LABELS.md`](MAUD_LABELS.md) ·
[`PROMPTS.md`](PROMPTS.md) · [`SCORECARD_HONESTY.md`](SCORECARD_HONESTY.md).
