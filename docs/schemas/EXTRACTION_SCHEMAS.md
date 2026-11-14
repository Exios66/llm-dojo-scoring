# Entity extraction schemas — mailroom-dataset (Dojo v0.28.1)

Pared live field maps for the **five primary document types** in
[`Lucius-Morningstar/mailroom-dataset`](https://huggingface.co/datasets/Lucius-Morningstar/mailroom-dataset)
(`ground_truth` config, Hub tag **v9.3** = commit `ccd040f6`, the revision `schemas/data/extraction_status.json`
is frozen from and llm-mailroom pins; the same **3,302** rows as v9.2, v9.1 and the v9 GT-closure pin `46a4d3c2`:
2,979 train / 323 test). Authority is the dojo live roster, not the
retired specialists.

**Where the field lists live.** One hand-edited table, `llm_dojo_scoring/schemas/doc_classes.py`
(`DOC_CLASSES`), holds each class's fields and scorer types; `DEFAULT_FIELD_TYPES`,
`CORPUS_EXTRACTION_FIELDS`, the rosters and the other field sets derive from it. Which of those
fields the dataset actually labels (and so scores today) is generated from the pinned dataset:
[`GT_COVERAGE.md`](GT_COVERAGE.md), `extraction_schemas.scoreable_fields(<class>)`.

| Pin | Value |
|---|---|
| Package | `llm-dojo-scoring` **v0.28.1** |
| Field maps | `schemas/doc_classes.py` (`DOC_CLASSES`) is the one hand-edited table. `scoring.suites.DEFAULT_FIELD_TYPES` (class → field → type) is derived from it, and for the five live classes it must equal the taxonomy fixture `tests/fixtures/taxonomy_field_types.json`. `schemas.corpus.CORPUS_EXTRACTION_FIELDS` is a projection of the same registry to field names only (class → tuple of names), not a type map |
| Taxonomy blob | llm-mailroom `src/config/taxonomy.yaml` blob SHA-1 `44e0ab59b6b705aed4c1939b5e85ed8499e38d0a` (the fixture's `authority_blob_sha1`) |
| Frozen prompts | `get_prompt(<agent>, family="production_prompts")` — eval-environment v1, frozen 2026-09-26T05:09:29+00:00 |
| Live classes | `contract` · `merger_agreement` · `corporate_record` · `correspondence` · `insurance_claim` |
| Not live | `unknown` (routing only) · `court_opinion` / `due_diligence` / `compliance_filing` (retired; zero corpus rows) |

Hub `gt_fields` is a **union dict**. Score only the class's own keys
([`GT_METADATA.md`](GT_METADATA.md)). `merger_agreement` is
`MergerAgreementExtraction`, never a CUAD `contract` alias.

```python
from llm_dojo_scoring import get_suite
from llm_dojo_scoring.schemas.corpus import suite_schema
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
| **total** | **3,302** | 100% | | **75 field slots** across the five maps (17 + 21 + 9 + 11 + 17) |

91 EX-10 contracts are triage-only (`cuad_clause_labels` =
`pending_annotation`) and stay **unscorable** until clause backfill.

## Scoring types

| Type | Match rule |
|---|---|
| `id` | Uppercase, strip punctuation/whitespace, exact |
| `date` | Canonical ISO date; containment + partial-credit fallbacks |
| `money` | Parse to float, ±$0.01; unparseable prose → fuzzy string |
| `name` | Jaro–Winkler + token-set; containment first |
| `label` | Closed vocabulary (`SCORED_ENUM_FIELDS`): aliases folded by `canonical_label` (`normalize_intent` for `intent`), then exact match — no partial credit, no embedding rescue. 0.28.0 retyped `cuad_family`, `merger_consideration`, merger `intent`, `communication_type`, `urgency`, `claim_type` and `coverage_determination` from `name` |
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

## 1. `contract` — `ContractExtraction` v2 (17 fields)

CUAD commercial contracts only. Category, family, question and JSON-Schema
catalog: [`CUAD_SCHEMA.md`](CUAD_SCHEMA.md) (`llm_dojo_scoring.schemas.cuad_schema`).
Sorter `doc_subclass` / `contract_subtype`
is situational context for `cuad_family`; verify against operative text.
Do **not** emit `intent` / `subject_matter` / `keywords` /
`effective_time`.

v2 (0.28.0, mailroom-dataset v10 plan A1) adds the entity fields from
`party_roles` to `territory` and drops the v1 parse-compat `merger_consideration` /
`maud_clauses` from the live map: a prediction may still carry them (they are not
extra keys) but they are never scored, so the contract headline can reach `full`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `document_name` | `name` | `null` | Title as stated; never from filename |
| `parties` | `entity_list:name` | `[]` | Full legal name + parenthetical alias when given |
| `party_roles` | `entity_list:free_text` | `[]` | `'<party>: <role>'`; role in `CONTRACT_PARTY_ROLES` (licensor, licensee, supplier, customer, …, other) |
| `signatories` | `entity_list:name` | `[]` | Persons who sign, as printed |
| `agreement_date` | `date` | `null` | "Dated as of" or signature date, ISO (CUAD Agreement Date) |
| `effective_date` | `date` | `null` | ISO `YYYY-MM-DD`; defined Effective Date beats signature date |
| `expiration_date` | `date` | `null` | End of the initial term when stated as a date (CUAD Expiration Date) |
| `term_length` | `free_text` | `null` | Duration of **the agreement**, not a sub-period |
| `renewal_terms` | `free_text` | `null` | Renewal / evergreen / rollover language |
| `termination_notice_period` | `free_text` | `null` | Notice to terminate or stop a renewal (CUAD Notice Period To Terminate Renewal) |
| `governing_law` | `name` | `null` | Governing-law sentence only; no forum/venue |
| `dispute_forum` | `name` | `null` | Courts or arbitral seat, separate from governing law |
| `contract_value` | `money` | `null` | Currency phrase as written (`"$2,000,000"`); do not compute |
| `payment_terms` | `free_text` | `null` | How and when consideration is paid |
| `territory` | `free_text` | `null` | Stated territory (promoted from the family hints) |
| `cuad_family` | `label` | `null` | Exactly one of 25 CUAD keys, or `other` |
| `cuad_clauses` | `entity_list:free_text` | `[]` | `'<Atticus category>: <verbatim span>'` — present only |

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
`unscorable`. The CUAD-derived fields the coverage page lists as scored count
through clause presence (`cuad.clause_presence.micro_f1`), not as separate
field scores; field-micro P/R/F1/F2 on a presence-only row are null.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`cuad.clause_presence.micro_f1`, `pipeline.extraction.field_micro_f1` /
`_f2` / `_precision` / `_recall`, `maud.question.micro_accuracy`.

**Frozen prompt:** `contracts_specialist` `sha256 d91de396…` (byte-identical
to sandbox `contracts_specialist_v33_simplified`).

---

## 2. `merger_agreement` — `MergerAgreementExtraction` v2 (21 fields)

Agreement and Plan of Merger (including amended/restated). **Not** the
CUAD extractor: never emit `cuad_family` or `cuad_clauses`. v2 (0.28.0,
mailroom-dataset v10 plan A2) adds the deal entities from `acquirer` to
`legal_counsel` and closes `merger_consideration` and `intent`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `document_name` | `name` | `null` | Title as stated |
| `parties` | `entity_list:name` | `[]` | Parent, Merger Sub, Target, other named entities |
| `acquirer` | `name` | `null` | The Parent, as printed |
| `target` | `name` | `null` | The Company, as printed |
| `merger_sub` | `entity_list:name` | `[]` | Merger subsidiary or subsidiaries |
| `signatories` | `entity_list:name` | `[]` | Persons signing for each party |
| `effective_date` | `date` | `null` | Calendar date only; **null when only an Effective Time exists** |
| `effective_time` | `free_text` | `null` | Clock / TZ / defined-term Effective Time |
| `governing_law` | `name` | `null` | Governing-law sentence; no forum/venue |
| `per_share_cash_amount` | `money` | `null` | Cash per Target share (promoted from the hint) |
| `exchange_ratio` | `free_text` | `null` | Parent shares per Target share (promoted from the hint) |
| `target_termination_fee` | `money` | `null` | Fee payable by the Target |
| `parent_termination_fee` | `money` | `null` | Reverse termination fee |
| `outside_date` | `date` | `null` | End / Outside Date; ISO, or as printed when relative |
| `financial_advisors` | `entity_list:name` | `[]` | From the brokers and fairness sections |
| `legal_counsel` | `entity_list:name` | `[]` | From the notice "with a copy to" lines |
| `merger_consideration` | `label` | `null` | One token: `all_cash` · `all_stock` · `mixed_cash_stock` · `mixed_cash_stock_election` · `other` |
| `maud_clauses` | `entity_list:free_text` | `[]` | `'<Question>: <Hub valid_class>'`; omit unanswered; never `"not specified"` |
| `intent` | `label` | `null` | `effect_merger` · `amend_merger` · `other` (`MERGER_INTENTS`; `plan_of_merger` folds to `effect_merger`) |
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
Per-question allowed answers, deal-point groups, the guided-decoding JSON Schema and the
subclass table: [`MAUD_SCHEMA.md`](MAUD_SCHEMA.md) (`llm_dojo_scoring.schemas.maud_schema`).
Ambiguous collapsed GT is `unscorable` on those keys, not a guessed match.

**GT extras:** `expected_subclass`, `maud_clause_labels`. MAUD-only rows
still score the content metric: their headline `metric_id` is
`maud.question.micro_accuracy`, and field-micro P/R/F1/F2 are null (no
extraction field is labelled).

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`maud.question.micro_accuracy`, `maud.clause_presence.rate`,
`pipeline.extraction.field_micro_f1` / `_f2` / `_precision` / `_recall`.

**Frozen prompt:** `merger_agreement_specialist` `sha256 00323258…`.

---

## 3. `corporate_record` — `CorporateRecordExtraction` (9 core fields + per-subclass entities)

> **Not one blanket schema.** The nine fields are a shared core; each subclass adds its own key entities and drops inapplicable core fields — see [`CORPORATE_RECORD_SCHEMA.md`](CORPORATE_RECORD_SCHEMA.md). Key-entity GT is currently unlabeled on all 450 rows and is excluded from scoring rather than scored as expected-empty.

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
| `intent` | `label` | `null` | `governance_rules` · `corporate_action_approval` · `entity_formation` · `authority_delegation` · `investor_rights` · `other`. Canonicalized via `normalize_intent`; exact match. |
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

Hub inventory has the 10 surfaces above except `certificate_of_formation`
(no Hub rows; any would fold into `articles_of_incorporation` for
`record_type`). It still gets its own explicit prompt line —
`+organizers[], registered_agent; omit authorized_capital entirely, even
when null` — because an LLC certificate has no capital-article share
schedule. Corpus GT currently covers that Hub subset.

**v0.19.1:** `subsidiary_list` keeps `filing_number` null unless an
official filing/document number is on **this** record.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`pipeline.extraction.field_micro_f1` / `_f2` / `_precision` / `_recall`. No CUAD/MAUD-grade external
benchmark.

**Prompt:** `corporate_records_specialist` `sha256 253559fc…`
(locally corrected + per-subclass entity schemas; upstream eval-environment re-freeze tracked in
[`TODOS.md`](../history/TODOS.md)).

---

## 4. `correspondence` — `CorrespondenceExtraction` (11 fields)

Letters, email, memos, notices, demands, meeting invites, press. Dollars
go in `demand_amount`, never insurance `claimed_amount`.

| Field | Type | Empty | Notes |
|---|---|---|---|
| `sender` | `name` | `null` | Name / title / entity as written; press = issuer or media contact |
| `recipient` | `name` | `null` | Named addressee; press/wire with none → `null` |
| `additional_recipients` | `entity_list` | `[]` | CC / copied parties |
| `communication_type` | `label` | `null` | 8 form tokens or `other` (see below); exact match since 0.28.0, so `demand` never matches `attorney_demand` |
| `communication_date` | `date` | `null` | Date **sent** (ISO); not a deadline, meeting, or invoice date |
| `demand_amount` | `money` | `null` | Exact dollars demanded; most non-demand mail is `null` |
| `action_items` | `entity_list` | `[]` | ≤3 concrete actions with deadlines if stated |
| `urgency` | `label` | never `null` | `routine` · `time-sensitive` · `urgent` · `critical`. Unspecified → `routine` |
| `intent` | `label` | `null` | `payment_demand` · `notice` · `analysis` · `request` · `update` · `meeting_invite` · `press_communication` · `other`. Canonicalized via `normalize_intent`; exact match. |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases from the text |

**`communication_type` vocabulary (8 + `other`):** `email`, `letter`, `memo`,
`notice`, `demand`, `attorney_demand`, `press_release`,
`meeting_request`, and `other` for a form outside the eight. Since 0.28.0
(mailroom-dataset v10) the gold is the row's subclass, `other` included, so
`other` is a scored token: emit it for an unregistered form, and `null` only
when the text gives no form at all. v8 `voicemail` is **not** in v9 GT and
normalizes to `other`.

**Content extras (scored, not schema keys).** Enron GT on all 1,000
rows: `content_topic` (11) —
`announcements`, `energy_market`, `finance_earnings`, `general_business`,
`hr_personnel`, `it_systems`, `legal_contracts`, `marketing_clients`,
`regulatory`, `scheduling`, `travel_logistics` — and `sentiment_label`
(`negative` 180 / `neutral` 566 / `positive` 254). Content-only rows
still score those metrics.

**Allowed `metric_id`:** extraction overall + field-micro F1/F2/precision/recall, plus
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
| `claim_number` | `id` | `null` | Exact printed claim id (CLAIM NO., FNOL; CMS rows: the 15-digit claim id) |
| `policy_number` | `id` | `null` | Exact printed policy number |
| `insurer` | `name` | `null` | Carrier as written |
| `insured_party` | `name` | `null` | Named insured / claimant |
| `claim_type` | `label` | `null` | Extract enum **orthogonal** to subclass (see below) |
| `date_of_loss` | `date` | `null` | Loss/event date (ISO) |
| `date_filed` | `date` | `null` | Filing date; not date of loss |
| `claimed_amount` | `money` | `null` | Amount as stated (CMS rows: the paid amount; `0.0` is a stated zero); do not compute |
| `adjuster` | `name` | `null` | Named adjuster only; CMS/GNOTHEIA/INSURBIAS often `null` (valid) |
| `damages_description` | `free_text` | `null` | Loss/damages as described |
| `coverage_determination` | `label` | `null` | `approved` · `denied` · `partial` · `pending` (`COVERAGE_DETERMINATIONS`); stated outcome words fold (`partially approved` → `partial`). Never infer from tone |
| `denial_reasons` | `entity_list:free_text` | `[]` | Stated grounds; `[]` when approved / pending / unstated |
| `supporting_documents` | `entity_list` | `[]` | Referenced docs; CMS provider/NPI lines belong here |
| `intent` | `label` | `null` | `claim_filing` · `coverage_determination` · `loss_report` · `claim_data_record` · `other`. Canonicalized via `normalize_intent`; exact match. |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 phrases from the text |
| `claim_checklist` | `entity_list:free_text` | `[]` | `'<Category>: <evidence>'` — present only |

**Subclass (6, sorter / Hub):** `carrier` · `inpatient` · `outpatient` ·
`pde` · `property` · `auto`.

**`claim_type` scored vocabulary (#93): product lines only**
(`corpus.INSURANCE_PRODUCT_LINES`): `auto` · `property` · `liability` · `health` ·
`life` · `workers_comp` · `other`. A CMS table token is **not** a `claim_type`. Product-line
`health` is **not** a subclass (`normalize_corpus_subclass(..., "health")`
→ `other`).

**CMS mapping (v0.26.0, #93).** `corpus.CMS_SOURCE_TABLES` is the single source
of truth: each source table (`carrier` · `inpatient` · `outpatient` · `pde`) maps
to `claim_type=health`, subclass = the table, and intent `claim_data_record`.
`claim_type` (the product line) and the source table are **orthogonal**:

- The SAND-042 fold is retired: on a CMS row `claim_type` is an exact `label`, so
  `pde` / `inpatient` / `outpatient` / `carrier` there scores 0 (GT is `health`).
- The source table is its own label field, `cms_source_table`. The published
  `gt_fields` never carry it (0 of 1,100 rows); the dojo derives it from
  `expected_subclass` for CMS rows when it assembles GT (`scoring_gt_fields(...,
  doc_type=, subclass=)`, suite scoring with `expected_subclass=`). For the frozen
  prompt, a table token on `claim_type` is still read as the `cms_source_table`
  prediction when that field is blank — it earns credit there only.
- CMS-aware fields (CMS rows only): `adjuster` and `denial_reasons` are
  documented-absent on all 600 rows, so an empty prediction scores 1.0 and a stated
  value 0.0; `supporting_documents` match by identifier (provider NPI, NDC, facility
  provider id exact; descriptors such as `HCPCS detail (N codes)` by type label).
- Non-CMS rows (INSURBIAS / BDR auto, GNOTHEIA property) are unchanged.

**Current split** (ground_truth config): 1,100 insurance rows — CMS 600
(`source_corpus == "cms_desynpuf"`, 150 per table) and non-CMS 500 (INSURBIAS auto
150, BDR auto 150, GNOTHEIA property 200). `claim_checklist` is in the live map but
no row populates it (the headline is `partial`); intents `loss_report` / `other`
are unused.

**`claim_checklist` categories:** Coverage Determination; Policy Limits;
Exclusions Cited; Deductible; Reservation Of Rights; Timely Notice; Proof
Of Loss; Subrogation; Independent Medical Exam; Amount Consistency.

**Class extras:** `determination_consistency` (`approved` ⇒ empty
reasons; `denied`/`partial` ⇒ nonempty; missing determination ⇒ 0.0),
`amount_exactness`. `schema_promotion_gate` (default 0.90) is emitted for
every live class, not only insurance (`SCHEMA_PROMOTION_GATES`). Published GT
is homogeneous (`coverage_determination=approved`, empty denials), so
consistency is degenerate on GT-shaped predictions.

**Allowed `metric_id`:** `pipeline.extraction.overall`,
`pipeline.extraction.field_micro_f1` / `_f2` / `_precision` / `_recall`.

**Frozen prompt:** `insurance_claims_specialist` `sha256 6c2776bc…`.

---

## Cross-class rules

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
   `pending_annotation` are never required events: the first two are blanked
   (labelled empty), a pending field is dropped (unlabelled). Passing the class-label
   string as GT fails closed (`gt_wrong_schema`). A schema field the GT does
   not label, or marks `pending_annotation`, is excluded from field-micro
   P/R/F1 on both sides (a value there is not a false positive); a value on a
   field labelled empty (`not_applicable`, `schema_documented_absence`), or an
   off-schema key, is. A CMS row's `adjuster` / `denial_reasons` stay labelled
   empty whatever their status (CMS documents them absent). A blank or literal `"nan"` `content_topic` /
   `sentiment_label` is not a label and emits no topic / sentiment score.
5. **Perfect-prediction replay** (both splits, 3,302 rows, 19,924
   extraction events): 0 FN / 0 FP / 0 spurious fills; 91 triage-only
   contracts stay `unscorable`.
6. **Prompt freeze vs live `production` family.** Eval stems are
   `family="production_prompts"`. Since v0.20.0 the five `production`
   specialists are re-vendored from live mailroom (`version: v1`,
   `source_key: frozen_v1`). Corporate records stays on mailroom's v6 freeze
   (`fe13501f…`), while `production_prompts` carries evaluation v7 (`253559fc…`);
   the other four specialist bodies match across families. The retired
   `contracts_specialist_v32` body is gone. Do not mix the
   `docclass` lineage into a comparison table without matching `prompt_id`.

## Scored-enum hints (#96)

Consumers must not hand-maintain the enum values they teach a specialist.
SAND-042 found a correspondence hint teaching `demand_payment`,
`schedule_meeting`, … — spellings outside the canonical hint vocabulary. The
insurance and corporate-record hints had the same defect. `normalize_intent`
still folds those two aliases to `payment_demand` / `meeting_invite` before
scoring, so their predictions are not necessarily marked wrong. The hint audit
flags them anyway, because the alias table is a safety net, not the contract.
The dojo generates the hints from
the scored vocabulary instead (`llm_dojo_scoring.schemas.scored_enums`):

| Class | Field | Source of the vocabulary |
|---|---|---|
| `corporate_record`, `correspondence`, `insurance_claim`, `merger_agreement` | `intent` | `INTENT_LABELS` (`MERGER_INTENTS` since 0.28.0) |
| `contract` | `cuad_family` | `DOC_TYPE_SUBCLASSES["contract"]` (0.28.0) |
| `merger_agreement` | `merger_consideration` | `MAUD_CONSIDERATION_TYPES` (0.28.0) |
| `correspondence` | `communication_type` | `DOC_TYPE_SUBCLASSES["correspondence"]` (0.28.0) |
| `correspondence` | `urgency` | `URGENCY_LEVELS` (0.28.0) |
| `insurance_claim` | `claim_type` | `INSURANCE_PRODUCT_LINES` (product lines only; CMS tables are `cms_source_table`) |
| `insurance_claim` | `cms_source_table` | `CMS_SOURCE_TABLES` |
| `insurance_claim` | `coverage_determination` | `COVERAGE_DETERMINATIONS` (0.28.0) |

Every `label` field of the five live classes has an entry, and the scorer folds a
value with `canonical_label(doc_type, field, value)` before the exact match.

```python
from llm_dojo_scoring import (
    enum_hint_violations, scored_enum_hint, scored_enum_schemas,
)

scored_enum_schemas("insurance_claim")   # {field: {"enum": [..., None], "description": ...}}
scored_enum_hint("correspondence", "intent")  # prompt line, every token verbatim
assert enum_hint_violations("correspondence", {"intent": MY_INTENTS}) == []
```

`enum_hint_violations` reports taught values that are not scored tokens,
scored tokens a consumer never teaches, and vendored enums the dojo does not
score. Alias spellings count as violations: `normalize_intent` folds them for
stored answers, but a hint teaches canonical tokens only. A contract test
fails if a `label`-typed field in `DEFAULT_FIELD_TYPES` has no hint.

## Schema registry: document type and subtype (v0.26.0)

`llm_dojo_scoring.schemas.extraction_schemas` gives every one of the five classes
a **document-type schema** plus a **schema per subtype**: 25 contract families,
5 MAUD consideration types, 11 corporate subclasses, 9 correspondence forms and
6 insurance subtypes (4 CMS tables, property, auto). That is 61 schemas.

```python
from llm_dojo_scoring import extraction_schema, iter_extraction_schemas, schema_coverage

pde = extraction_schema("insurance_claim", "pde")      # any corpus surface works too
pde.schema_id                    # "insurance_claim/pde@v9.3"
pde.scored_fields                # fields that count when the row labels them
pde.documented_absent_fields     # ("adjuster", "denial_reasons")
pde.pending_fields               # ("claim_checklist",)
pde.json_schema()                # strict, typed object for guided decoding
extraction_schema("contract", "License_Agreements").salient   # CUAD categories
```

Each field has a status read from the v9.3 `ground_truth` rows (Hub tag `v9.3` @
`ccd040f6`, the revision llm-mailroom pins; its per-field statuses equal those of
v9.2.1, which added the corporate relabel), frozen in
`llm_dojo_scoring/schemas/data/extraction_status.json` by
`scripts/build_extraction_status.py --from-hub`. The source revision is in the file and in
`extraction_status_source()`. The populated count behind every status is in the generated
[`GT_COVERAGE.md`](GT_COVERAGE.md).

| Status | Meaning | Example |
|---|---|---|
| `scored` | GT populates it on (nearly) every row | insurance `claim_number` |
| `partial` | GT labels it on some rows; scored where labelled | auto `adjuster` (50%) |
| `derived` | truth from a label source or the subtype | contract `parties` (CUAD), `cuad_family`, `cms_source_table` |
| `documented_absent` | an empty answer is right | CMS / property `adjuster` |
| `label_task` | scored by a label task, not extraction | correspondence `content_topic` |
| `pending_annotation` | in the live map, not labelled yet | correspondence `sender`, corporate entities, `claim_checklist` |
| `not_applicable` | GT marks it n/a for the class | merger `intent` |

What v9.3 labels, per class:

- **contract**: CUAD clause labels give the six metadata fields and
  `cuad_clauses` for 22 families. Most `consulting`, `ip` and `supply` rows are
  still `pending_annotation`. `contract_value` has no source.
- **merger_agreement**: `maud_clauses` (MAUD labels) and
  `merger_consideration` (the subtype). The other five fields are pending.
- **corporate_record**: `intent`, `subject_matter`, `keywords`, `record_type`
  (the subtype) and, since the v9.2.1 relabel, `entity_name` (the EDGAR
  registrant: 92% of rows; `scored` on seven subtypes, `partial` on articles,
  bylaws and rights instruments). `filing_number` is `not_applicable` except on
  articles and charter amendments; on `subsidiary_list`, `signatories` and
  `jurisdiction` are `not_applicable` too. Otherwise `effective_date`,
  `signatories`, `jurisdiction` and every per-subclass entity (for example
  indenture `trustee`) are unlabelled in every Hub revision and stay
  `pending_annotation` until they are annotated.
- **correspondence**: `intent`, `subject_matter`, `keywords` and
  `communication_type` (the subtype). Topic and sentiment are label tasks. The
  envelope fields are pending (#94).
- **insurance_claim**: 14 fields scored on every subtype. CMS tables add
  `cms_source_table` and identifier-aware `supporting_documents`, and document
  `adjuster` / `denial_reasons` as absent; property documents both as absent;
  auto labels them on some rows. `claim_checklist` is pending everywhere.

`Suite.score_document` (and `score(..., detailed=True)` on one document) adds a
`schema` block that is additive and changes no score. It holds the `schema_id`,
the fields this row can score, the scored fields it leaves unlabelled, and the
schema's pending fields. Pass `expected_subclass=` (or `doc_subclass=`) to get the
subtype schema. `registry_violations()` checks the registry against the taxonomy
and the live maps.

## Import surface

```python
from llm_dojo_scoring import get_suite, LIVE_DOC_TYPES
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES
from llm_dojo_scoring.schemas.corpus import CORPUS_EXTRACTION_FIELDS, suite_schema

assert tuple(LIVE_DOC_TYPES) == (
    "contract", "merger_agreement", "corporate_record",
    "correspondence", "insurance_claim",
)
for doc_type in LIVE_DOC_TYPES:
    assert set(DEFAULT_FIELD_TYPES[doc_type]) == set(CORPUS_EXTRACTION_FIELDS[doc_type])

out = get_suite("insurance_claims_specialist").score_document(expected, predicted)
```

Related: [`SCORING.md`](../guides/SCORING.md) · [`GT_METADATA.md`](GT_METADATA.md) ·
[`METRIC_IDS.md`](../contracts/METRIC_IDS.md) · [`MAUD_LABELS.md`](MAUD_LABELS.md) ·
[`PROMPTS.md`](../guides/PROMPTS.md) · [`SCORECARD_HONESTY.md`](../contracts/SCORECARD_HONESTY.md).
