# CUAD contract schema — categories, families, questions

Reference for `llm_dojo_scoring.cuad_schema`, the single importable catalog
behind the `contract` document class (`ContractExtraction` /
`contracts_specialist`). It unifies the **41 Atticus clause categories**, the
**25 contract families + `other`**, the **11 scored fields**, tailored CUAD
questions, and a JSON Schema for guided decoding. See
[`EXTRACTION_SCHEMAS.md`](EXTRACTION_SCHEMAS.md) §1 for the field contract and
[`GT_METADATA.md`](GT_METADATA.md) for how `cuad_clause_labels` drive the
presence scorer.

**Documentation and prompt aids only.** Nothing here changes scoring:
`DEFAULT_FIELD_TYPES["contract"]` ≡ `CORPUS_EXTRACTION_FIELDS["contract"]` ≡
taxonomy fixture stays byte-identical, and the frozen `contracts_specialist`
prompt (sha256 `d91de396…`) is untouched. Import-time checks raise
`RuntimeError` if the catalog drifts from `corpus.CUAD_CLAUSE_CATEGORIES`,
`corpus.DOC_TYPE_SUBCLASSES["contract"]`, `corpus.CORPUS_SUBCLASS_SURFACES`,
or `DEFAULT_FIELD_TYPES["contract"]`.

```python
from llm_dojo_scoring.cuad_schema import (
    CUAD_CATEGORIES, CUAD_FAMILIES, CONTRACT_EXTRACTION_FIELDS,
    cuad_category, cuad_family, cuad_questions,
    cuad_json_schema, render_cuad_question_block,
)

cuad_category("ROFR/ROFO/ROFN").name          # 'Rofr/Rofo/Rofn'
cuad_family("License_Agreements").key         # 'license'
cuad_questions("supply")[:3]                  # salient categories first
render_cuad_question_block("license")         # prompt-ready text block
schema = cuad_json_schema()                   # vLLM guided-decoding schema
```

## Provenance

| Element | Source |
|---|---|
| Category names and set | `corpus.CUAD_CLAUSE_CATEGORIES` (asserted at import); tuple order is the CUAD / frozen-prompt order, not alphabetical |
| `description` / CUAD question | CUAD v1 `category_descriptions` ("Details" text) reproduced with ASCII quotes; the question template is CUAD's own wording |
| `prompt_question`, `group`, `answer_format` map, family definitions, salient sets, family hints | Curated by this package; not CUAD-official |
| Families, surfaces | `config.CONTRACT_SUBTYPES` + `corpus.CORPUS_SUBCLASS_SURFACES`, resolved through `normalize_subtype` |

`answer_format` is `span` where the answer is an extracted value (the eight
general-information categories and Warranty Duration) and `yes_no` where
presence of the clause is the answer. The scored `cuad_clauses` field and the
presence scorer treat all 41 identically (`'<Category>: <verbatim span>'`,
present only); `answer_format` is descriptive.

## Lookup helpers

| Helper | Behaviour |
|---|---|
| `cuad_category(name)` | Case / whitespace / punctuation-insensitive lookup incl. aliases (`ROFR/ROFO/ROFN`, `Noncompete`, `IP Ownership Assignment`, `MFN`, `Right of First Refusal`, `Perpetual License`, …). Unknown name raises `KeyError` |
| `canonical_cuad_category(value)` | Same lookup, returns the canonical name or `None` |
| `cuad_family(name)` | Key, label or folder surface via `normalize_subtype`; unknown/empty resolves to `other` |
| `salient_categories(family)` | Salient names in priority order (`()` for `None` / `other`) |
| `cuad_questions(family=None, style="cuad", salient_only=False)` | Ordered `[(category, question)]`; salient categories first, then the rest in CUAD order. `style="specialist"` gives the concise question |
| `render_cuad_question_block(family=None, style="specialist", categories=None)` | Prompt-ready text block; salient categories under their own heading, scored-field mappings tagged `[also <field>]` |
| `cuad_json_schema(include_trace=True)` | JSON Schema for guided decoding (below) |

## ContractExtraction fields (11 scored)

| Field | Scoring type | Empty | Description |
|---|---|---|---|
| `document_name` | `name` | `null` | The contract's name as given (e.g. 'Web Hosting Agreement'); never invented from the file name. |
| `parties` | `entity_list:name` | `[]` | Distinct named contracting parties: full legal name plus parenthetical alias when the text gives one. |
| `effective_date` | `date` | `null` | Date the agreement takes effect as ISO YYYY-MM-DD; a defined Effective Date wins over the signature date. |
| `term_length` | `free_text` | `null` | Duration of the agreement itself (commencement through end / earlier termination), not a sub-period. |
| `governing_law` | `name` | `null` | Only the sentence naming the jurisdiction whose laws govern; no forum, venue or attorneys' fees. |
| `contract_value` | `money` | `null` | Monetary consideration as a plain currency phrase ('$2,000,000'); $0 is a stated amount; never computed. |
| `renewal_terms` | `free_text` | `null` | Renewal, extension or rollover language, including evergreen 'continues until terminated on N days notice'. |
| `cuad_family` | `name` | `null` | Exactly one CUAD family key (25 families) or 'other'; null only when not a CUAD commercial contract. |
| `merger_consideration` | `name` | `null` | Parse-compat only: always null on CUAD commercial contracts. |
| `cuad_clauses` | `entity_list:free_text` | `[]` | Present CUAD categories only, as '<Atticus category>: <short verbatim evidence span>'. |
| `maud_clauses` | `entity_list:free_text` | `[]` | Parse-compat only: always [] on CUAD commercial contracts. |

`reasoning` (object) and `confidence` (number) are emitted by the frozen prompt
but never scored; `cuad_json_schema(include_trace=False)` omits them.

## JSON Schema (guided decoding)

`cuad_json_schema()` returns a plain dict (`title: ContractExtraction`,
`additionalProperties: false`, every scored key required):

- nullable scalars are `["string", "null"]`; `effective_date` also carries
  `^\d{4}-\d{2}-\d{2}$`;
- `parties` / `cuad_clauses` are arrays defaulting to `[]`;
- `cuad_family` is an enum of the 25 families + `other` (or `null`);
- each `cuad_clauses` item must match `^(?:<41 exact Atticus names>): .+`;
- `merger_consideration` is pinned to `null` and `maud_clauses` to `[]`
  (parse-compat keys, always empty on CUAD rows);
- `reasoning` / `confidence` are included unless `include_trace=False`.

## The 41 categories

Groups: `basic_info`, `term_and_termination`, `restrictive_covenants`,
`ip_and_license`, `commercial_terms`, `liability_and_risk`, `other`.
Every full CUAD question is
`Highlight the parts (if any) of this contract related to "<Category>" that should be reviewed by a lawyer. Details: <description>`.

| # | Category | Group | Format | Feeds field | CUAD description (Details) | Specialist question |
|--:|---|---|---|---|---|---|
| 1 | `Document Name` | basic_info | span | `document_name` | The name of the contract | What is the contract's own title (e.g. 'Web Hosting Agreement')? |
| 2 | `Parties` | basic_info | span | `parties` | The two or more parties who signed the contract | Who are the contracting parties (full legal name plus defined alias)? |
| 3 | `Agreement Date` | basic_info | span | `effective_date` | The date of the contract | What is the date the contract was made or signed? |
| 4 | `Effective Date` | basic_info | span | `effective_date` | The date when the contract is effective | On what date does the contract take effect (a defined Effective Date wins over the signature date)? |
| 5 | `Expiration Date` | term_and_termination | span | `term_length` | On what date will the contract's initial term expire? | When does the initial term expire, or how long does the agreement last? |
| 6 | `Renewal Term` | term_and_termination | span | `renewal_terms` | What is the renewal term after the initial term expires? This includes automatic extensions and unilateral extensions with prior notice. | What is the renewal or extension term after the initial term (including evergreen rollover)? |
| 7 | `Notice Period To Terminate Renewal` | term_and_termination | span | `renewal_terms` | What is the notice period required to terminate renewal? | How much notice must be given to stop the contract renewing? |
| 8 | `Governing Law` | basic_info | span | `governing_law` | Which state/country's law governs the interpretation of the contract? | Which state or country's law governs the contract? |
| 9 | `Most Favored Nation` | commercial_terms | yes_no | — | Is there a clause that if a third party gets better terms on the licensing or sale of technology/goods/services described in the contract, the buyer of such technology/goods/services under the contract shall be entitled to those better terms? | Does the buyer or licensee get any better terms a third party is later given? |
| 10 | `Competitive Restriction Exception` | restrictive_covenants | yes_no | — | This category includes the exceptions or carveouts to Non-Compete, Exclusivity and No-Solicit of Customers above. | Are there exceptions or carve-outs to the non-compete, exclusivity or customer no-solicit restrictions? |
| 11 | `Non-Compete` | restrictive_covenants | yes_no | — | Is there a restriction on the ability of a party to compete with the counterparty or operate in a certain geography or business or technology sector? | Is a party restricted from competing with the other, or from operating in a geography, business or technology sector? |
| 12 | `Exclusivity` | restrictive_covenants | yes_no | — | Is there an exclusive dealing commitment with the counterparty? This includes a commitment to procure all "requirements" from one party of certain technology, goods, or services or a prohibition on licensing or selling technology, goods or services to third parties, or a prohibition on collaborating or working with other parties), whether during the contract or after the contract ends (or both). | Is there an exclusive-dealing, requirements or no-third-party-sales commitment, during or after the term? |
| 13 | `No-Solicit Of Customers` | restrictive_covenants | yes_no | — | Is a party restricted from contracting or soliciting customers or partners of the counterparty, whether during the contract or after the contract ends (or both)? | Is a party barred from soliciting or contracting with the other's customers or partners? |
| 14 | `No-Solicit Of Employees` | restrictive_covenants | yes_no | — | Is there a restriction on a party's soliciting or hiring employees and/or contractors from the counterparty, whether during the contract or after the contract ends (or both)? | Is a party barred from soliciting or hiring the other's employees or contractors? |
| 15 | `Non-Disparagement` | restrictive_covenants | yes_no | — | Is there a requirement on a party not to disparage the counterparty? | Must a party refrain from disparaging the other party? |
| 16 | `Termination For Convenience` | term_and_termination | yes_no | — | Can a party terminate this contract without cause (solely by giving a notice and allowing a waiting period to expire)? | Can a party terminate without cause on notice and a waiting period? |
| 17 | `Rofr/Rofo/Rofn` | restrictive_covenants | yes_no | — | Is there a clause granting one party a right of first refusal, right of first offer or right of first negotiation to purchase, license, market, or distribute equity interest, technology, assets, products or services? | Does a party hold a right of first refusal, first offer or first negotiation? |
| 18 | `Change Of Control` | other | yes_no | — | Does one party have the right to terminate or is consent or notice required of the counterparty if such party undergoes a change of control, such as a merger, stock sale, transfer of all or substantially all of its assets or business, or assignment by operation of law? | Is there a termination right, consent or notice requirement if a party undergoes a change of control? |
| 19 | `Anti-Assignment` | other | yes_no | — | Is consent or notice required of a party if the contract is assigned to a third party? | Is consent or notice required before the contract is assigned to a third party? |
| 20 | `Revenue/Profit Sharing` | commercial_terms | yes_no | — | Is one party required to share revenue or profit with the counterparty for any technology, goods, or services? | Must a party share revenue or profit (royalty, commission, split) with the other? |
| 21 | `Price Restrictions` | commercial_terms | yes_no | — | Is there a restriction on the ability of a party to raise or reduce prices of technology, goods, or services provided? | Is a party restricted from raising or reducing prices? |
| 22 | `Minimum Commitment` | commercial_terms | yes_no | — | Is there a minimum order size or minimum amount or units per-time period that one party must buy from the counterparty under the contract? | Is there a minimum order size or minimum purchase amount per period? |
| 23 | `Volume Restriction` | commercial_terms | yes_no | — | Is there a fee increase or consent requirement, etc. if one party's use of the product/services exceeds certain threshold? | Is there a fee increase or consent requirement if usage exceeds a threshold? |
| 24 | `Ip Ownership Assignment` | ip_and_license | yes_no | — | Does intellectual property created by one party become the property of the counterparty, either per the terms of the contract or upon the occurrence of certain events? | Does IP created by one party become the other party's property? |
| 25 | `Joint Ip Ownership` | ip_and_license | yes_no | — | Is there any clause providing for joint or shared ownership of intellectual property between the parties to the contract? | Is any IP jointly or co-owned by the parties? |
| 26 | `License Grant` | ip_and_license | yes_no | — | Does the contract contain a license granted by one party to its counterparty? | Does one party grant the other a license? |
| 27 | `Non-Transferable License` | ip_and_license | yes_no | — | Does the contract limit the ability of a party to transfer the license being granted to a third party? | Is the licensee barred from transferring or sublicensing the license to a third party? |
| 28 | `Affiliate License-Licensor` | ip_and_license | yes_no | — | Does the contract contain a license grant by affiliates of the licensor or that includes intellectual property of affiliates of the licensor? | Does the license come from, or cover IP of, the licensor's affiliates? |
| 29 | `Affiliate License-Licensee` | ip_and_license | yes_no | — | Does the contract contain a license grant to a licensee (incl. sublicensor) and the affiliates of such licensee/sublicensor? | Does the license extend to the licensee's (or sublicensor's) affiliates? |
| 30 | `Unlimited/All-You-Can-Eat-License` | ip_and_license | yes_no | — | Is there a clause granting one party an "enterprise," "all you can eat" or unlimited usage license? | Is there an enterprise, 'all you can eat' or unlimited-usage license? |
| 31 | `Irrevocable Or Perpetual License` | ip_and_license | yes_no | — | Does the contract contain a license grant that is irrevocable or perpetual? | Is any license irrevocable or perpetual? |
| 32 | `Source Code Escrow` | ip_and_license | yes_no | — | Is one party required to deposit its source code into escrow with a third party, which can be released to the counterparty upon the occurrence of certain events (bankruptcy, insolvency, etc.)? | Must source code be placed in escrow for release on bankruptcy or similar events? |
| 33 | `Post-Termination Services` | term_and_termination | yes_no | — | Is a party subject to obligations after the termination or expiration of a contract, including any post-termination transition, payment, transfer of IP, wind-down, last-buy, or similar obligations? | Are there obligations after termination or expiration (transition, wind-down, last-buy, payment, IP transfer)? |
| 34 | `Audit Rights` | commercial_terms | yes_no | — | Does a party have the right to audit the books, records, or physical locations of the counterparty to ensure compliance with the contract? | Can a party audit the other's books, records or premises? |
| 35 | `Uncapped Liability` | liability_and_risk | yes_no | — | Is a party's liability uncapped upon the breach of its obligation in the contract? This also includes uncap liability for a particular type of breach such as IP infringement or breach of confidentiality obligation. | Is any liability uncapped (in general or for a breach type such as IP infringement or confidentiality)? |
| 36 | `Cap On Liability` | liability_and_risk | yes_no | — | Does the contract include a cap on liability upon the breach of a party's obligation? This includes time limitation for the counterparty to bring claims or maximum amount for recovery. | Is liability capped, or is there a time limit or maximum amount for claims? |
| 37 | `Liquidated Damages` | liability_and_risk | yes_no | — | Does the contract contain a clause that would award either party liquidated damages for breach or a fee upon the termination of a contract (termination fee)? | Are liquidated damages or a termination fee payable? |
| 38 | `Warranty Duration` | liability_and_risk | span | — | What is the duration of any warranty against defects or errors in technology, products, or services provided under the contract? | How long does the warranty against defects or errors last? |
| 39 | `Insurance` | liability_and_risk | yes_no | — | Is there a requirement for insurance that must be maintained by one party for the benefit of the counterparty? | Must a party maintain insurance for the other's benefit? |
| 40 | `Covenant Not To Sue` | restrictive_covenants | yes_no | — | Is a party restricted from contesting the validity of the counterparty's ownership of intellectual property or otherwise bringing a claim against the counterparty for matters unrelated to the contract? | Is a party barred from challenging the other's IP ownership or suing it on unrelated matters? |
| 41 | `Third Party Beneficiary` | other | yes_no | — | Is there a non-contracting party who is a beneficiary to some or all of the clauses in the contract and therefore can enforce its rights against a contracting party? | Can a non-party beneficiary enforce any of the contract's clauses? |

`Agreement Date` and `Effective Date` both feed `effective_date`: a defined
Effective Date beats a signature date. `Notice Period To Terminate Renewal`
feeds `renewal_terms` (evergreen / notice language). `contract_value` and
`cuad_family` have no Atticus category.

## The 25 families + `other`

`cuad_family` is the sorter's `doc_subclass` after verification against the
operative text. Salient categories are a *prior* (characteristically present
for the family, in priority order), not presence labels; they order
`cuad_questions(family)` and the prompt block. They extend the frozen
prompt's per-subtype brief (a test pins the brief's named categories as a
subset). `family_fields` are optional entity hints for prompts and docs: never
scored, never emitted, never added to the field map.

| Key | Label | CUAD folder surfaces | Definition |
|---|---|---|---|
| `affiliate` | Affiliate Agreement | `Affiliate_Agreements` | Affiliate or referral-program agreement: a publisher or partner promotes the counterparty's products for a commission or referral fee. |
| `agency` | Agency Agreement | `Agency Agreements` | Agency agreement: one party (agent) represents or sells for the other (principal), usually for a commission. |
| `collaboration` | Collaboration / Cooperation Agreement | `Collaboration` | Collaboration or cooperation agreement: parties pool R&D or other effort toward a shared program. |
| `co_branding` | Co-Branding Agreement | `Co_Branding` | Co-branding agreement: parties combine marks or properties on jointly branded products, sites or campaigns. |
| `consulting` | Consulting Agreement | `Consulting Agreements` | Consulting or advisory services agreement: a consultant provides expertise for fees. |
| `development` | Development Agreement | `Development` | Development agreement: one party builds a product, software or deliverable, often against milestones. |
| `distributor` | Distributor Agreement | `Distributor` | Distributor agreement: a distributor buys and resells the supplier's goods in a territory. |
| `endorsement` | Endorsement Agreement | `Endorsement` | Endorsement agreement (or rider): a person or entity lends name, likeness or reputation to promote a product. |
| `franchise` | Franchise Agreement | `Franchise` | Franchise agreement: a franchisor grants the right to operate under its system and marks in exchange for fees. |
| `hosting` | Hosting Agreement | `Hosting` | Hosting agreement: a provider hosts web sites, applications or data for a customer. |
| `ip` | IP Agreement | `IP` | Intellectual-property agreement: assignment, transfer or licensing of patents, marks, copyrights or software. |
| `joint_venture` | Joint Venture Agreement | `Joint Venture`, `Joint Venture _ Filing` | Joint-venture agreement: parties form or operate a shared venture or project and divide contributions and returns. |
| `license` | License Agreement | `License_Agreements` | License agreement: one party licenses technology, content or IP to another, typically for royalties. |
| `maintenance` | Maintenance Agreement | `Maintenance` | Maintenance or support agreement: a provider keeps software, equipment or systems operating. |
| `manufacturing` | Manufacturing Agreement | `Manufacturing` | Manufacturing agreement: one party makes goods to specification for another, often with supply commitments. |
| `marketing` | Marketing Agreement | `Marketing` | Marketing agreement: a party markets, promotes or co-promotes products or services. |
| `non_compete_no_solicit` | Non-Compete / No-Solicit / Non-Disparagement Agreement | `Non_Compete_Non_Solicit` | Restrictive-covenant agreement: non-compete, non-solicit and non-disparagement undertakings. |
| `outsourcing` | Outsourcing Agreement | `Outsourcing` | Outsourcing agreement: a provider takes over a business process or function for a customer. |
| `promotion` | Promotion Agreement | `Promotion` | Promotion agreement: promotional services, campaigns or co-promotion of a product. |
| `reseller` | Reseller Agreement | `Reseller` | Reseller agreement: a reseller or value-added reseller buys or licenses products to resell to customers. |
| `service` | Service Agreement | `Service` | Service agreement: general professional, support or operational services for fees. |
| `sponsorship` | Sponsorship Agreement | `Sponsorship` | Sponsorship agreement: a sponsor funds an event, team or content in exchange for promotional benefits. |
| `strategic_alliance` | Strategic Alliance Agreement | `Strategic Alliance` | Strategic-alliance agreement: parties partner on a commercial initiative without forming a separate entity. |
| `supply` | Supply Agreement | `Supply` | Supply agreement: a supplier sells goods or materials to a buyer on stated quantities and prices. |
| `transportation` | Transportation Agreement | `Transportation` | Transportation agreement: carriage, logistics or freight services. |
| `other` | Other / unlisted | — | Commercial contract that fits none of the 25 listed families; extract every present category from the text and never invent a family from the filename. |

### Salient categories and entity hints per family

**`affiliate`** — Affiliate Agreement

- Salient: Affiliate License-Licensee, Affiliate License-Licensor, License Grant, Non-Transferable License, Revenue/Profit Sharing, Termination For Convenience, Exclusivity, Anti-Assignment, Governing Law, Renewal Term
- Hints: `commission_rate` (→ `contract_value`) — Commission or referral fee rate; `program_territory` — Territory or channels the affiliate may promote in

**`agency`** — Agency Agreement

- Salient: Termination For Convenience, Governing Law, Notice Period To Terminate Renewal, Exclusivity, Non-Compete, Revenue/Profit Sharing, Anti-Assignment, Renewal Term, Expiration Date
- Hints: `principal_and_agent` — Which party is principal and which is agent; `commission_rate` (→ `contract_value`) — Commission rate or schedule; `territory` — Territory the agent covers

**`collaboration`** — Collaboration / Cooperation Agreement

- Salient: Joint Ip Ownership, Ip Ownership Assignment, License Grant, Exclusivity, Revenue/Profit Sharing, Termination For Convenience, Expiration Date, Governing Law, Non-Compete, Change Of Control
- Hints: `collaboration_scope` — Program or field of collaboration; `cost_sharing` (→ `contract_value`) — How costs and revenue are split

**`co_branding`** — Co-Branding Agreement

- Salient: License Grant, Non-Transferable License, Ip Ownership Assignment, Exclusivity, Revenue/Profit Sharing, Non-Compete, Termination For Convenience, Governing Law, Audit Rights
- Hints: `co_branded_product` — Product, site or program carrying both brands; `licensed_marks` — Trademarks licensed to each party

**`consulting`** — Consulting Agreement

- Salient: Termination For Convenience, Cap On Liability, Ip Ownership Assignment, Non-Compete, No-Solicit Of Employees, Insurance, Expiration Date, Governing Law, Post-Termination Services
- Hints: `fee_structure` (→ `contract_value`) — Hourly rate, retainer or fixed fee; `services_scope` — Description of the consulting services

**`development`** — Development Agreement

- Salient: Ip Ownership Assignment, Joint Ip Ownership, License Grant, Source Code Escrow, Warranty Duration, Termination For Convenience, Post-Termination Services, Expiration Date, Cap On Liability, Governing Law
- Hints: `deliverables` — Product or software to be developed; `milestone_fees` (→ `contract_value`) — Milestone or acceptance payments

**`distributor`** — Distributor Agreement

- Salient: License Grant, Exclusivity, Minimum Commitment, Anti-Assignment, Non-Compete, Price Restrictions, Termination For Convenience, Rofr/Rofo/Rofn, Competitive Restriction Exception, Volume Restriction, Governing Law, Renewal Term
- Hints: `territory` — Distribution territory; `distributed_products` — Products the distributor may sell; `minimum_purchase` (→ `contract_value`) — Minimum purchase or quota

**`endorsement`** — Endorsement Agreement

- Salient: License Grant, Non-Transferable License, Exclusivity, Non-Disparagement, Ip Ownership Assignment, Expiration Date, Termination For Convenience, Non-Compete, Governing Law
- Hints: `endorser` — Person or entity giving the endorsement; `endorsement_fee` (→ `contract_value`) — Endorsement fee or compensation

**`franchise`** — Franchise Agreement

- Salient: Non-Compete, Exclusivity, Revenue/Profit Sharing, Audit Rights, Minimum Commitment, Renewal Term, Cap On Liability, License Grant, Termination For Convenience, Anti-Assignment, Post-Termination Services, Insurance, No-Solicit Of Employees, Rofr/Rofo/Rofn, Governing Law
- Hints: `territory` — Franchised territory; `franchise_fees` (→ `contract_value`) — Initial franchise fee and royalty rate; `franchised_system` — Brand or business system franchised

**`hosting`** — Hosting Agreement

- Salient: Price Restrictions, Renewal Term, Expiration Date, Warranty Duration, Cap On Liability, Uncapped Liability, Insurance, Audit Rights, Post-Termination Services, Termination For Convenience, Volume Restriction, Source Code Escrow, Governing Law
- Hints: `hosted_service` — Site, application or data being hosted; `service_levels` — Uptime or service-level commitments; `hosting_fees` (→ `contract_value`) — Recurring hosting fees

**`ip`** — IP Agreement

- Salient: Ip Ownership Assignment, License Grant, Joint Ip Ownership, Source Code Escrow, Non-Transferable License, Irrevocable Or Perpetual License, Covenant Not To Sue, Anti-Assignment, Warranty Duration, Governing Law
- Hints: `ip_assets` — Patents, marks, copyrights or software covered; `consideration` (→ `contract_value`) — Purchase price or royalty for the IP

**`joint_venture`** — Joint Venture Agreement

- Salient: Joint Ip Ownership, Governing Law, Change Of Control, Revenue/Profit Sharing, Non-Compete, Exclusivity, Rofr/Rofo/Rofn, Anti-Assignment, Termination For Convenience, Ip Ownership Assignment, Expiration Date, Competitive Restriction Exception
- Hints: `venture_entity` — Name of the joint venture entity or project; `capital_contributions` (→ `contract_value`) — Each party's contribution; `ownership_split` — Ownership or profit-split percentages

**`license`** — License Agreement

- Salient: License Grant, Non-Transferable License, Irrevocable Or Perpetual License, Ip Ownership Assignment, Affiliate License-Licensor, Affiliate License-Licensee, Source Code Escrow, Unlimited/All-You-Can-Eat-License, Revenue/Profit Sharing, Exclusivity, Covenant Not To Sue, Audit Rights, Anti-Assignment, Termination For Convenience, Joint Ip Ownership, Most Favored Nation
- Hints: `royalty_rate` (→ `contract_value`) — Royalty rate or license fee; `territory` — Licensed territory; `licensed_product` — Licensed technology, content or product; `license_scope` — Exclusive / non-exclusive, field of use, sublicensing

**`maintenance`** — Maintenance Agreement

- Salient: Warranty Duration, Post-Termination Services, Expiration Date, Renewal Term, Price Restrictions, Cap On Liability, Termination For Convenience, Source Code Escrow, Insurance, Notice Period To Terminate Renewal
- Hints: `supported_product` — Software or equipment under maintenance; `support_fees` (→ `contract_value`) — Annual or recurring maintenance fee

**`manufacturing`** — Manufacturing Agreement

- Salient: Minimum Commitment, Volume Restriction, Price Restrictions, Warranty Duration, Exclusivity, Insurance, Ip Ownership Assignment, License Grant, Most Favored Nation, Termination For Convenience, Audit Rights, Uncapped Liability
- Hints: `manufactured_product` — Goods to be manufactured; `minimum_volume` — Minimum or forecast volumes; `unit_price` (→ `contract_value`) — Unit price or pricing formula

**`marketing`** — Marketing Agreement

- Salient: Exclusivity, Non-Compete, Revenue/Profit Sharing, License Grant, Termination For Convenience, Expiration Date, Renewal Term, Ip Ownership Assignment, Minimum Commitment, Competitive Restriction Exception, Governing Law
- Hints: `marketed_product` — Product or service being marketed; `marketing_fees` (→ `contract_value`) — Fees or commission for marketing services

**`non_compete_no_solicit`** — Non-Compete / No-Solicit / Non-Disparagement Agreement

- Salient: Non-Compete, No-Solicit Of Customers, No-Solicit Of Employees, Non-Disparagement, Competitive Restriction Exception, Expiration Date, Governing Law, Covenant Not To Sue, Liquidated Damages, Exclusivity
- Hints: `restricted_period` (→ `term_length`) — Duration of the restrictive covenants; `restricted_territory` — Geography the restriction covers; `restricted_business` — Business or activity restricted

**`outsourcing`** — Outsourcing Agreement

- Salient: Audit Rights, Cap On Liability, Uncapped Liability, Termination For Convenience, Post-Termination Services, Change Of Control, Insurance, Minimum Commitment, Volume Restriction, Price Restrictions, Expiration Date, No-Solicit Of Employees, Liquidated Damages, Ip Ownership Assignment
- Hints: `outsourced_function` — Business process or function outsourced; `service_levels` — Service levels and credits; `service_fees` (→ `contract_value`) — Base fee or charges

**`promotion`** — Promotion Agreement

- Salient: Exclusivity, Revenue/Profit Sharing, Expiration Date, Renewal Term, License Grant, Non-Disparagement, Termination For Convenience, Minimum Commitment, Non-Compete, Ip Ownership Assignment
- Hints: `promoted_product` — Product or service being promoted; `promotion_fees` (→ `contract_value`) — Fees or compensation for promotion

**`reseller`** — Reseller Agreement

- Salient: License Grant, Minimum Commitment, Anti-Assignment, Price Restrictions, Exclusivity, Non-Transferable License, Most Favored Nation, Termination For Convenience, Volume Restriction, Rofr/Rofo/Rofn, Competitive Restriction Exception, Audit Rights, Warranty Duration
- Hints: `territory` — Reseller territory; `resold_products` — Products the reseller may resell; `reseller_discount` (→ `contract_value`) — Discount off list price

**`service`** — Service Agreement

- Salient: Termination For Convenience, Warranty Duration, Cap On Liability, Expiration Date, Renewal Term, Insurance, Ip Ownership Assignment, Post-Termination Services, Uncapped Liability, Audit Rights, Governing Law, No-Solicit Of Employees, Price Restrictions
- Hints: `services_scope` — Description of the services; `service_fees` (→ `contract_value`) — Service fees or rate card

**`sponsorship`** — Sponsorship Agreement

- Salient: Exclusivity, License Grant, Non-Transferable License, Revenue/Profit Sharing, Rofr/Rofo/Rofn, Termination For Convenience, Expiration Date, Renewal Term, Competitive Restriction Exception, Non-Disparagement, Ip Ownership Assignment, Minimum Commitment
- Hints: `sponsored_property` — Event, team or content sponsored; `sponsorship_fee` (→ `contract_value`) — Sponsorship fee; `sponsor_benefits` — Rights and benefits the sponsor receives

**`strategic_alliance`** — Strategic Alliance Agreement

- Salient: Joint Ip Ownership, Exclusivity, Change Of Control, Non-Compete, Revenue/Profit Sharing, Rofr/Rofo/Rofn, Competitive Restriction Exception, License Grant, Ip Ownership Assignment, Termination For Convenience, Governing Law, No-Solicit Of Customers, No-Solicit Of Employees, Anti-Assignment
- Hints: `alliance_scope` — Field or initiative of the alliance; `revenue_split` — How revenue or profit is divided

**`supply`** — Supply Agreement

- Salient: Minimum Commitment, Volume Restriction, Price Restrictions, Governing Law, Warranty Duration, Exclusivity, Most Favored Nation, Insurance, Termination For Convenience, Uncapped Liability, Cap On Liability, Expiration Date, Renewal Term, Audit Rights
- Hints: `supplied_goods` — Goods or materials supplied; `minimum_quantity` — Minimum or forecast quantities; `unit_price` (→ `contract_value`) — Unit price or pricing formula

**`transportation`** — Transportation Agreement

- Salient: Insurance, Cap On Liability, Uncapped Liability, Price Restrictions, Volume Restriction, Minimum Commitment, Termination For Convenience, Expiration Date, Exclusivity, Audit Rights, Liquidated Damages, Anti-Assignment, Governing Law
- Hints: `route_or_lane` — Routes, lanes or territory served; `freight_rates` (→ `contract_value`) — Freight rates or fees

**`other`** — Other / unlisted

- Salient: none (extract every present category)
