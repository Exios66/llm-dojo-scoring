# MAUD schema — the machine-checkable question→answer contract

`llm_dojo_scoring/maud_schema.py` turns the 22 Hub MAUD questions into data so
the **prompt**, the **output grammar** and the **scorer** read one source. Answer
classes are never typed here: they are pulled from
[`maud.py`](MAUD_LABELS.md) (`MAUD_ANSWER_CLASSES`); this module only adds
meaning, location, grouping, and rendering. It imports from `maud.py`, never
changes it.

```python
from llm_dojo_scoring.maud_schema import (
    MAUD_QUESTIONS, maud_question, maud_questions, maud_json_schema,
    render_maud_question_block, parse_maud_clause, maud_answers_to_clauses,
    MergerAgreementExtraction, MAUD_CONSIDERATION_SUBCLASSES,
)

block  = render_maud_question_block("all_cash")      # every question + every answer, verbatim
schema = maud_json_schema("object")                  # vLLM guided_json (recommended)
parse_maud_clause("no-shop: yes.")                   # ('No-Shop', 'Yes')
```

## 1. Why this exists (SAND-042)

The frozen `merger_agreement_specialist` prompt demands
`'<Question>: <Hub valid_class>'` and "Answer is the Hub valid_class, not a
paraphrase" — but lists only the 22 **question names**, never the allowed answers
(`merger_agreement_specialist.production_prompts.md`, lines 35 and 41), and the
output grammar was a plain array of strings. A model cannot know that
`No-Shop` accepts `Strict liability` or that `Superior Offer Definition` expects
`Greater than 50% but not "all or substantially all"`. The block rendered here
lists every answer; the grammar makes anything else unemittable.

## 2. Design decisions

- **`answer_type`** is derived, not asserted: a question is `multi_label` iff some
  class equals another class of the same question plus `", <more>"` (the shape
  `maud.canonical_maud_class` handles component-wise). Result: 5 multi-label
  (`Accuracy of Target R&W Closing Condition`, `FTR Triggers`, `Limitations on FTR
  Exercise`, `MAE Definition`, `Tail Period & Acquisition Proposal Details`), 17
  single-choice. Even for multi-label questions the Hub answer is **one
  comma-joined catalog string**, so the model still picks exactly one listed string.
  **Keep the listed item order** (catalog order); the scorer's component path only
  rescues *other* orderings when each component is itself a class.
- **Two grammar shapes** — `maud_json_schema(shape=...)`:
  - `"object"` (**recommended**): `maud_answers: {<Question>: enum[valid_classes] | null}`,
    all 22 keys required. One decision per question, no question-name typing
    (the double-space name is a schema key), nulls for questions the text does not
    answer. Each class string appears once (~19 KB for the whole schema).
  - `"lines"`: `maud_clauses` is an array of `enum` strings `"<Question>: <class>"`
    (265 pairs, ~27 KB). `enum` rather than a regex `pattern`: same size (one
    alternative per pair) but no escaping of `( ) " / & '` or curly quotes and no
    way to hide a mistake in a metacharacter. JSON Schema cannot express "at most
    one line per question" (`uniqueItems` + `maxItems: 22` only bound it).
- **Scorer compatibility of `object`.** The scorer reads the extraction key
  `maud_clauses` only (`content_scoring.peel_non_extraction_fields`); a
  `{question: class}` mapping under `maud_clauses` parses, but under `maud_answers`
  it scores **0 presence**. Run `maud_answers_to_clauses(...)` to get lines.
  It drops `null`s and blanks. Passed straight to the scorer, a top-level
  `{question: null}` entry is unanswered, but a blank string or a record with
  `answer: null` is *present with an empty answer* and fails class validation.
- **Variable-class questions** (`Accuracy of Target R&W Closing Condition`,
  `Limitations on FTR Exercise`, `MAE Definition`, `Tail Period & Acquisition
  Proposal Details`) record the corpus *union* with `variable=True`; the block says so.
  When the GT record is known pass `row_classes={...}` to `maud_json_schema` to
  narrow the grammar to that row's own `valid_classes`.
- **Typo twins.** The Hub ships both `fundamental/Special` and `Fundermental/Special`
  R&W classes; the scorer folds them. `valid_classes` keeps both (GT-shaped answers
  stay representable); `prompt_classes` (used in prompts) drops the typo twin.
- **Chunk duty.** Merger documents are processed in about 8 chunks, so the block
  tells the model to answer a question only if its operative clause is visible in
  *this* text, else `null` (object) / omit (lines). `chunked=False` removes it.
- **Parity is asserted at import**: `MergerAgreementExtraction.field_types` must equal
  `DEFAULT_FIELD_TYPES["merger_agreement"]` (and `CORPUS_EXTRACTION_FIELDS` order);
  drift raises `AssertionError` when the module is imported.
- **Deal-point groups and explanations are authored here** (HF is unreachable offline,
  so the Hub `category` string was not available). Audit them with
  `category_mismatches(maud_clause_labels)` against any real GT row.

## 3. The 10 scored fields (`MergerAgreementExtraction`)

| Field | Type | Empty | Notes |
|---|---|---|---|
| `document_name` | `name` | `null` | Agreement title as stated |
| `parties` | `entity_list:name` | `[]` | Parent, Merger Sub, Target |
| `effective_date` | `date` | `null` | `YYYY-MM-DD` only; null when just an Effective Time |
| `effective_time` | `free_text` | `null` | Clock / TZ / defined-term |
| `governing_law` | `name` | `null` | No forum/venue |
| `merger_consideration` | `name` | `null` | One of the five subclass tokens (section 5) |
| `maud_clauses` | `entity_list:free_text` | `[]` | `'<Question>: <Hub valid_class>'` |
| `intent` | `name` | `null` | Short label |
| `subject_matter` | `free_text` | `null` | One grounded sentence |
| `keywords` | `entity_list:name` | `[]` | ≤8 copied phrases |


## 4. Questions by deal point

Generated from `MAUD_QUESTIONS` (regenerate by reading the module; `tests/test_maud_schema.py` pins every string below to the catalog). *Type*: `single` = `single_choice`, `multi` = `multi_label` (a class is another class plus `, <more>`; still **one** comma-joined catalog string). **Uncertain** marks readings/groups inferred from the collapsed Hub class names.

### General Information (1)

#### 1. `Type of Consideration`

single · 4 answers

- **Asks:** What is the form of merger consideration paid to the Target's stockholders: all cash, all stock, a cash/stock mix, or a cash/stock mix with a stockholder election?
- **Usually found in:** Article II Effect on Capital Stock / 'Merger Consideration' (conversion of shares)

Tailored question:

```text
Type of Consideration: What is the form of merger consideration paid to the Target's stockholders: all cash, all stock, a cash/stock mix, or a cash/stock mix with a stockholder election?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - All Cash
  - All Stock
  - Mixed Cash/Stock
  - Mixed Cash/Stock: Election
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

### Conditions to Closing (3)

#### 2. `Absence of Litigation Closing Condition`

single · 5 answers · **uncertain**

- **Asks:** Does a closing condition require that no litigation be pending or threatened against the deal, and how broad is it: only government actions, or private suits too; pending only, threatened, or threatened in writing?
- **Usually found in:** Article VII/VI Conditions to Closing (No Injunction; No Litigation)
- **Uncertain:** The Hub classes mix two axes (who sues: governmental vs any; how: pending vs threatened vs threatened in writing). Reading is from the class names.

Tailored question:

```text
Absence of Litigation Closing Condition: Does a closing condition require that no litigation be pending or threatened against the deal, and how broad is it: only government actions, or private suits too; pending only, threatened, or threatened in writing?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Governmental litigation only
  - Non-Governmental & governmental litigation
  - Pending
  - Pending or threatened (without "writing" requirement)
  - Pending or threatened in writing
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 3. `Accuracy of Target R&W Closing Condition`

multi · 93 answers · variable class set (union shown) · **uncertain**

- **Asks:** How accurate must the Target's representations and warranties be at closing for the buyer to be obliged to close (the bring-down standard: all respects, all material respects, MAE standard, with de minimis exceptions), at what time they are measured (signing and closing, or closing only), and which R&Ws are treated as fundamental/specified (authority, capitalization, brokers, takeover statutes, ...)?
- **Usually found in:** Article VII/VI Conditions to Obligations of Parent and Merger Sub (Representations and Warranties); Target representations (Article III/IV) for the fundamental R&W list
- **Uncertain:** The Hub question collapses several MAUD sub-questions (bring-down standard, bring-down timing, list of fundamental R&Ws) into one key; its per-row class set is one of 7 variants and most classes are comma-joined lists.

<details><summary>Tailored question (93 allowed answers)</summary>

```text
Accuracy of Target R&W Closing Condition: How accurate must the Target's representations and warranties be at closing for the buyer to be obliged to close (the bring-down standard: all respects, all material respects, MAE standard, with de minimis exceptions), at what time they are measured (signing and closing, or closing only), and which R&Ws are treated as fundamental/specified (authority, capitalization, brokers, takeover statutes, ...)?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Accurate at another materiality standard (e.g., hybrid standard)
  - Accurate in all material respects
  - Accurate in all respects
  - Accurate in all respects with below-threshold carveout
  - Accurate in all respects with de minimis exception
  - All/The R&Ws accurate at MAE standard
  - All/The R&Ws accurate in all respects (repeating R&Ws)
  - At Closing Only
  - At Signing & At Closing
  - Authority, Approval, Enforceability
  - Authority, Approval, Enforceability, No MAE, Brokers' Fee
  - Authority, Approval, Enforceability, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor
  - Authority, Approval, Enforceability, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Authority, Approval, Enforceability, No MAE, Opinion of Financial Advisor, Other
  - Authority, Approval, Enforceability, Organization, Brokers' Fee
  - Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor, Other
  - Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Other
  - Capitalization-Other
  - Capitalization-Other, Approval, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, No MAE, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, No MAE, Brokers' Fee, Rights Agreement, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Opinion of Financial Advisor, No-Conflict
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Takeover Statutes
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Takeover Statutes, Rights Agreement
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, No-Conflict, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor, No-Conflict
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor, Tax
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, No MAE, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee, No-Conflict
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee, Takeover Statutes
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee, Takeover Statutes, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, No-Conflict
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Organization, Subsidiaries, No MAE, Takeover Statutes, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Subsidiaries, Brokers' Fee
  - Capitalization-Other, Authority, Approval, Enforceability, Subsidiaries, No MAE, Brokers' Fee, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Approval, Enforceability, Subsidiaries, No MAE, Brokers' Fee, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Enforceability, Subsidiaries, No MAE, Takeover Statutes, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Approval, Organization, Brokers' Fee, Takeover Statutes, Rights Agreement, Opinion of Financial Advisor
  - Capitalization-Other, Authority, Enforceability, Brokers' Fee
  - Capitalization-Other, Authority, Enforceability, Organization, Brokers' Fee, Takeover Statutes, Opinion of Financial Advisor, Other
  - Capitalization-Other, Authority, Enforceability, Organization, No MAE, Brokers' Fee, Opinion of Financial Advisor, No-Conflict
  - Capitalization-Other, Authority, Organization, No MAE, Brokers' Fee, Takeover Statutes, Rights Agreement
  - Capitalization-Other, No MAE
  - Capitalization-Other, No MAE, Other
  - Each R&W accurate at MAE standard
  - fundamental/Special R&Ws
  - General R&Ws
  - General R&Ws, Capitalization R&Ws
  - General R&Ws, Capitalization R&Ws, fundamental/Special R&Ws
  - General R&Ws, Capitalization R&Ws, Specified R&Ws only
  - General R&Ws, fundamental/Special R&Ws
  - General R&Ws, Specified R&Ws only
  - R&Ws accurate at another materiality standard (e.g., hybrid standard)
  - Specified R&Ws only
  - Tax
The allowed set varies by agreement: pick the listed answer that fits best; do not write anything that is not on the list.
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

</details>

#### 4. `Compliance with Covenant Closing Condition`

single · 3 answers · **uncertain**

- **Asks:** Which covenants must the Target have complied with for the buyer to be obliged to close: all covenants, each covenant, or a hybrid/other standard?
- **Usually found in:** Article VII/VI Conditions to Obligations of Parent and Merger Sub (Covenants)
- **Uncertain:** The Hub class names (All Covenants / Each Covenant / Hybrid/Other Standard) are terse; the precise MAUD sub-question wording is not available offline.

Tailored question:

```text
Compliance with Covenant Closing Condition: Which covenants must the Target have complied with for the buyer to be obliged to close: all covenants, each covenant, or a hybrid/other standard?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - All Covenants
  - Each Covenant
  - Hybrid/Other Standard
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

### Material Adverse Effect (1)

#### 5. `MAE Definition`

multi · 40 answers · variable class set (union shown) · **uncertain**

- **Asks:** How is 'Material Adverse Effect' defined: the forward-looking standard ('would'/'could' reasonably be expected to), the relational words used ('resulting from', 'arising from/out of', 'relating to', 'attributable to'), what the effect must be measured against (Target and subsidiaries 'taken as a whole'), which events are carved out (war or terrorism, natural disaster, announcement/pendency/consummation), and whether carveouts apply to all or only some MAE prongs?
- **Usually found in:** Definitions - 'Company Material Adverse Effect' / 'Material Adverse Effect'
- **Uncertain:** The Hub question collapses many MAUD MAE sub-questions into one key; its per-row class set is one of 5 variants (40 classes in the union).

<details><summary>Tailored question (40 allowed answers)</summary>

```text
MAE Definition: How is 'Material Adverse Effect' defined: the forward-looking standard ('would'/'could' reasonably be expected to), the relational words used ('resulting from', 'arising from/out of', 'relating to', 'attributable to'), what the effect must be measured against (Target and subsidiaries 'taken as a whole'), which events are carved out (war or terrorism, natural disaster, announcement/pendency/consummation), and whether carveouts apply to all or only some MAE prongs?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - "Arising from/out of"
  - "Arising from/out of", "Relating to"
  - "Arising from/out of", Other
  - "Attributable to"
  - "Could" (reasonably) be expected to
  - "Relating to"
  - "Resulting from"
  - "Resulting from", "Arising from/out of"
  - "Resulting from", "Arising from/out of", "Attributable to"
  - "Resulting from", "Arising from/out of", "Relating to"
  - "Resulting from", "Arising from/out of", "Relating to", "Attributable to"
  - "Resulting from", "Arising from/out of", "Relating to", "Attributable to", Relational language varies among carveouts
  - "Resulting from", "Arising from/out of", "Relating to", Other
  - "Resulting from", "Arising from/out of", "Relating to", Relational language varies among carveouts
  - "Resulting from", "Arising from/out of", Relational language varies among carveouts
  - "Resulting from", "Attributable to"
  - "Resulting from", "Relating to"
  - "Resulting from", Other
  - "Would"
  - "Would" (reasonably) be expected to
  - ability to consummate transaction
  - All MAE carveouts
  - announcement
  - announcement, consummation
  - announcement, pendency
  - announcement, pendency, consummation
  - Applies to Target and subsidiaries "taken as a whole"
  - business and operation of Target
  - business and operation of Target, ability to consummate transaction
  - Natural disaster
  - Natural disaster, "act of God"
  - No
  - Other forward-looking standard
  - Some MAE carveouts
  - War or terrorism
  - War or terrorism, Natural disaster
  - War or terrorism, Natural disaster, "act of God"
  - War or terrorism, Natural disaster, "act of God", force majeure
  - War or terrorism, Natural disaster, force majeure
  - Yes
The allowed set varies by agreement: pick the listed answer that fits best; do not write anything that is not on the list.
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

</details>

### Knowledge (1)

#### 6. `Knowledge Definition`

single · 6 answers

- **Asks:** How is 'Knowledge' of the Target defined: actual knowledge only, constructive knowledge, knowledge based on a named role/people, or after reasonable investigation or inquiry?
- **Usually found in:** Definitions - 'Knowledge' (Article I or Section 9.x / 'Certain Definitions')

Tailored question:

```text
Knowledge Definition: How is 'Knowledge' of the Target defined: actual knowledge only, constructive knowledge, knowledge based on a named role/people, or after reasonable investigation or inquiry?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Actual knowledge
  - Based on investigation or inquiry
  - Based on role
  - Constructive knowledge
  - No
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

### Operating and Efforts Covenant (3)

#### 7. `General Antitrust Efforts Standard`

single · 3 answers

- **Asks:** What efforts standard must the parties use to obtain antitrust / regulatory clearance: reasonable best efforts, commercially reasonable efforts, or a flat (absolute) standard?
- **Usually found in:** Efforts / Regulatory Approvals covenant (Article VI/V, 'Filings; Other Actions')

Tailored question:

```text
General Antitrust Efforts Standard: What efforts standard must the parties use to obtain antitrust / regulatory clearance: reasonable best efforts, commercially reasonable efforts, or a flat (absolute) standard?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Commercially reasonable efforts
  - Flat standard
  - Reasonable best efforts
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 8. `Negative interim operating covenant`

single · 6 answers · **uncertain**

- **Asks:** Does the Target have negative interim operating covenants (things it may not do between signing and closing without consent), do they apply to all or only specified actions, and what is the consent standard (flat consent, or not unreasonably withheld, conditioned or delayed)?
- **Usually found in:** Conduct of Business Pending the Merger (Article V/VI), 'Negative covenants' list
- **Uncertain:** Hub classes merge existence, scope, and consent-standard readings.

Tailored question:

```text
Negative interim operating covenant: Does the Target have negative interim operating covenants (things it may not do between signing and closing without consent), do they apply to all or only specified actions, and what is the consent standard (flat consent, or not unreasonably withheld, conditioned or delayed)?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Applies only to specified negative covenants
  - Applies to all negative covenants
  - Consent may not be unreasonably withheld, conditioned or delayed
  - Flat consent
  - No
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 9. `Ordinary course covenant`

single · 7 answers

- **Asks:** Must the Target conduct its business in the ordinary course between signing and closing, and with what standard: a flat covenant, commercially reasonable efforts, reasonable best efforts, or buyer consent not to be unreasonably withheld?
- **Usually found in:** Conduct of Business Pending the Merger (Article V/VI), 'Ordinary Course'

Tailored question:

```text
Ordinary course covenant: Must the Target conduct its business in the ordinary course between signing and closing, and with what standard: a flat covenant, commercially reasonable efforts, reasonable best efforts, or buyer consent not to be unreasonably withheld?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Commercially reasonable efforts
  - Consent may not be unreasonably withheld, conditioned or delayed
  - Flat consent
  - Flat covenant (no efforts standard)
  - No
  - Reasonable best efforts
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

### Deal Protection and Related Provisions (12)

#### 10. `Agreement provides for matching rights in connection with COR`

single · 11 answers

- **Asks:** If the Target board wants to change its recommendation (COR = change of recommendation) because of a competing proposal or intervening event, does the buyer get a matching right, and how long is the match period?
- **Usually found in:** No Solicitation / Change of Recommendation covenant (Article VI/V)

Tailored question:

```text
Agreement provides for matching rights in connection with COR: If the Target board wants to change its recommendation (COR = change of recommendation) because of a competing proposal or intervening event, does the buyer get a matching right, and how long is the match period?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - 2 business days or less
  - 3 business days
  - 3 calendar days
  - 3 days
  - 4 business days
  - 4 calendar days
  - 5 business days
  - > 5 business days
  - Continuous matching right
  - Greater than 5 business days
  - None
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 11. `Agreement provides for matching rights in connection with FTR`

single · 12 answers

- **Asks:** If the Target wants to terminate to accept a superior offer (FTR = fiduciary termination right), does the buyer get a matching right, and how long is the match period?
- **Usually found in:** No Solicitation / Superior Proposal termination covenant (Article VI/V); Termination article (Article VIII/IX), termination for a Superior Proposal

Tailored question:

```text
Agreement provides for matching rights in connection with FTR: If the Target wants to terminate to accept a superior offer (FTR = fiduciary termination right), does the buyer get a matching right, and how long is the match period?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - 2 business days or less
  - 3 business days
  - 3 calendar days
  - 3 days
  - 4 business days
  - 4 calendar days
  - 5 business days
  - 5 calendar days
  - >5 business days
  - Continuous matching right
  - Greater than 5 business days
  - None
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 12. `Breach of Meeting Covenant`

single · 2 answers · **uncertain**

- **Asks:** Does the Target's breach of its covenant to hold the stockholder meeting trigger the termination fee (or the buyer's termination right)?
- **Usually found in:** Termination article, termination fee triggers (Article VIII/IX); Stockholders Meeting / Proxy covenant
- **Uncertain:** Exact trigger semantics (fee vs termination right) are inferred from the MAUD deal-point name; class set is only Yes/No.

Tailored question:

```text
Breach of Meeting Covenant: Does the Target's breach of its covenant to hold the stockholder meeting trigger the termination fee (or the buyer's termination right)?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - No
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 13. `Breach of No Shop`

single · 2 answers · **uncertain**

- **Asks:** Does the Target's breach of the no-shop (no-solicitation) covenant trigger the termination fee (or the buyer's termination right)?
- **Usually found in:** Termination article, termination fee triggers (Article VIII/IX); No Solicitation covenant (Article VI/V)
- **Uncertain:** Exact trigger semantics are inferred from the deal-point name; Yes/No only. Group could alternatively be read as Remedies.

Tailored question:

```text
Breach of No Shop: Does the Target's breach of the no-shop (no-solicitation) covenant trigger the termination fee (or the buyer's termination right)?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - No
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 14. `FTR Triggers`

multi · 2 answers

- **Asks:** On what events may the Target exercise its fiduciary termination right: a Superior Offer only, or also an Intervening Event?
- **Usually found in:** No Solicitation / Change of Recommendation covenant; Termination article

Tailored question:

```text
FTR Triggers: On what events may the Target exercise its fiduciary termination right: a Superior Offer only, or also an Intervening Event?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Superior Offer
  - Superior Offer, Intervening Event
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 15. `Fiduciary exception to COR covenant`

single · 12 answers · **uncertain**

- **Asks:** What standard of fiduciary duty must the Target board meet to be allowed to change its recommendation (COR): e.g. failure would be 'inconsistent with', a 'breach' or 'violation' of, or 'reasonably likely' to breach, its fiduciary duties?
- **Usually found in:** Change of Recommendation covenant within No Solicitation (Article VI/V)
- **Uncertain:** Classes also include Yes/No/None, so some rows record mere existence of the exception.

Tailored question:

```text
Fiduciary exception to COR covenant: What standard of fiduciary duty must the Target board meet to be allowed to change its recommendation (COR): e.g. failure would be 'inconsistent with', a 'breach' or 'violation' of, or 'reasonably likely' to breach, its fiduciary duties?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - "Breach" of fiduciary duties
  - "Inconsistent" with fiduciary duties
  - "Reasonably likely/expected breach" of fiduciary duties
  - "Reasonably likely/expected to be inconsistent" with fiduciary duties
  - "Reasonably likely/expected violation" of fiduciary duties
  - "Required to comply" with fiduciary duties
  - "Violation" of fiduciary duties
  - More likely than not violate fiduciary duties
  - No
  - None
  - Other specified standard
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 16. `Fiduciary exception:  Board determination (no-shop)`

single · 11 answers

- **Asks:** What determination must the Target board make before it may talk to or furnish information to an unsolicited bidder despite the no-shop (the fiduciary exception to the no-solicitation covenant)? NOTE the question name has two spaces after the first colon.
- **Usually found in:** No Solicitation covenant, exceptions for unsolicited proposals (Article VI/V)

Tailored question:

```text
Fiduciary exception:  Board determination (no-shop): What determination must the Target board make before it may talk to or furnish information to an unsolicited bidder despite the no-shop (the fiduciary exception to the no-solicitation covenant)? NOTE the question name has two spaces after the first colon.
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - "Breach" of fiduciary duties
  - "Inconsistent" with fiduciary duties
  - "Reasonably likely/expected breach" of fiduciary duties
  - "Reasonably likely/expected to be inconsistent" with fiduciary duties
  - "Reasonably likely/expected violation" of fiduciary duties
  - "Required to comply" with fiduciary duties
  - "Violation" of fiduciary duties
  - Acquisition Proposal only
  - None
  - Other specified standard
  - Superior Offer, or Acquisition Proposal reasonably likely/expected to result in a Superior Offer
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 17. `Intervening Event Definition`

single · 8 answers · **uncertain**

- **Asks:** How does the definition of 'Intervening Event' treat events known (or reasonably foreseeable) at signing: must it arise after signing, may it be known but with unknown consequences, and so on?
- **Usually found in:** Definitions - 'Intervening Event' (Article I or the Change of Recommendation covenant)
- **Uncertain:** Classes also include Yes/No (existence of a definition); mixing of the two is inferred.

Tailored question:

```text
Intervening Event Definition: How does the definition of 'Intervening Event' treat events known (or reasonably foreseeable) at signing: must it arise after signing, may it be known but with unknown consequences, and so on?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - Known, but consequences unknown or not reasonably foreseeable, at signing
  - Known, but consequences unknown, at signing
  - May occur or arise prior to signing
  - Must occur or arise after signing
  - No
  - Not known and not reasonably foreseeable at signing
  - Not known at signing
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 18. `Limitations on FTR Exercise`

multi · 10 answers · variable class set (union shown) · **uncertain**

- **Asks:** What limits the Target's right to terminate for a superior offer: e.g. it may not do so if it breached the no-shop (any, material, or resulting in the Superior Offer) or breached other provisions of the agreement?
- **Usually found in:** Termination for a Superior Proposal (Article VIII/IX); No Solicitation covenant
- **Uncertain:** Multi-label: answers combine a no-shop-breach class with an 'other provisions' class in one comma-joined string.

Tailored question:

```text
Limitations on FTR Exercise: What limits the Target's right to terminate for a superior offer: e.g. it may not do so if it breached the no-shop (any, material, or resulting in the Superior Offer) or breached other provisions of the agreement?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - (Material) breach of other provisions of agreement
  - Any breach of no-shop
  - Any breach of no-shop, (Material) breach of other provisions of agreement
  - Breach of no-shop resulting in a Superior Offer
  - Breach of no-shop resulting in a Superior Offer, (Material) breach of other provisions of agreement
  - Material breach of no-shop
  - Material breach of no-shop resulting in a Superior Offer
  - Material breach of no-shop resulting in a Superior Offer, (Material) breach of other provisions of agreement
  - Material breach of no-shop, (Material) breach of other provisions of agreement
  - Other
The allowed set varies by agreement: pick the listed answer that fits best; do not write anything that is not on the list.
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 19. `No-Shop`

single · 4 answers · **uncertain**

- **Asks:** Does the agreement prohibit the Target from soliciting competing offers (a no-shop), and is the Target's responsibility for its representatives' breaches judged on a reasonable standard or strict liability?
- **Usually found in:** No Solicitation / Acquisition Proposals covenant (Article VI/V)
- **Uncertain:** Yes/No existence is merged with the Reasonable standard / Strict liability reading of responsibility for representatives; inferred from class names.

Tailored question:

```text
No-Shop: Does the agreement prohibit the Target from soliciting competing offers (a no-shop), and is the Target's responsibility for its representatives' breaches judged on a reasonable standard or strict liability?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - No
  - Reasonable standard
  - Strict liability
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 20. `Superior Offer Definition`

single · 6 answers

- **Asks:** What portion of the Target's equity or assets must a competing proposal cover to count as a Superior Offer/Proposal: 50%, more than 50% but not 'all or substantially all', less than 50%, or 'all or substantially all'?
- **Usually found in:** Definitions - 'Superior Proposal' / 'Superior Offer'

Tailored question:

```text
Superior Offer Definition: What portion of the Target's equity or assets must a competing proposal cover to count as a Superior Offer/Proposal: 50%, more than 50% but not 'all or substantially all', less than 50%, or 'all or substantially all'?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - "All or substantially all"
  - 50%
  - Greater than 50% but not "all or substantially all"
  - Less than 50%
  - No
  - Yes
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

#### 21. `Tail Period & Acquisition Proposal Details`

multi · 14 answers · variable class set (union shown) · **uncertain**

- **Asks:** For the Target termination fee 'tail': how long after termination does a competing deal still trigger the fee (6, 9, 12 months or longer), and which triggers require the Acquisition Proposal to have been publicly disclosed (breach, no-vote/failure to obtain approval, outside date)?
- **Usually found in:** Termination Fee / Effect of Termination (Article VIII/IX), tail provision
- **Uncertain:** The Hub question collapses tail length and 'publicly disclosed' sub-questions (per-row class set is one of 2 variants).

Tailored question:

```text
Tail Period & Acquisition Proposal Details: For the Target termination fee 'tail': how long after termination does a competing deal still trigger the fee (6, 9, 12 months or longer), and which triggers require the Acquisition Proposal to have been publicly disclosed (breach, no-vote/failure to obtain approval, outside date)?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - 12 months or longer
  - No
  - Other
  - within 12 months
  - within 6 months
  - within 9 months
  - Yes
  - “Publicly disclosed” requirement applies to Acquisition Proposal + Breach Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + Breach Trigger, “Publicly disclosed” requirement applies to Acquisition Proposal + No-Vote / MTC Failure Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + Breach Trigger, “Publicly disclosed” requirement applies to Acquisition Proposal + No-Vote / MTC Failure Trigger, “Publicly disclosed” requirement applies to Acquisition Proposal + Outside Date Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + Breach Trigger, “Publicly disclosed” requirement applies to Acquisition Proposal + Outside Date Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + No-Vote / MTC Failure Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + No-Vote / MTC Failure Trigger, “Publicly disclosed” requirement applies to Acquisition Proposal + Outside Date Trigger
  - “Publicly disclosed” requirement applies to Acquisition Proposal + Outside Date Trigger
The allowed set varies by agreement: pick the listed answer that fits best; do not write anything that is not on the list.
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

### Remedies (1)

#### 22. `Specific Performance`

single · 2 answers

- **Asks:** Do the parties get specific performance of the agreement, and is the right phrased as 'entitled to' specific performance or only 'entitled to seek' it?
- **Usually found in:** Specific Performance (Article IX/X, miscellaneous / remedies)

Tailored question:

```text
Specific Performance: Do the parties get specific performance of the agreement, and is the right phrased as 'entitled to' specific performance or only 'entitled to seek' it?
Answer with EXACTLY ONE of the following, copied verbatim (including quotes, commas and capitalization):
  - "entitled to seek" specific performance
  - "entitled to" specific performance
If the operative clause is not visible in this text, give no answer (omit it / null) -- never write 'not specified'.
```

## 5. Consideration subclasses

| Token | Hub `Type of Consideration` class | Definition | Family-equivalent to | Priority questions (frozen prompt) | Optional entity hints (**not scored**) |
|---|---|---|---|---|---|
| `all_cash` | `All Cash` | Every Target share converts into a fixed cash amount only. | - | Type of Consideration; Absence of Litigation Closing Condition; MAE Definition; No-Shop; Ordinary course covenant | `per_share_cash_amount`; `cvr` |
| `all_stock` | `All Stock` | Every Target share converts into Parent stock at an exchange ratio; no cash except for fractional shares. | - | Type of Consideration; Knowledge Definition; Accuracy of Target R&W Closing Condition | `exchange_ratio`; `cash_in_lieu_of_fractional_shares` |
| `mixed_cash_stock` | `Mixed Cash/Stock` | Each Target share converts into a fixed combination of cash and Parent stock. | `mixed_cash_stock_election` | Type of Consideration; FTR Triggers; Compliance with Covenant Closing Condition | `per_share_cash_amount`; `exchange_ratio` |
| `mixed_cash_stock_election` | `Mixed Cash/Stock: Election` | Mixed cash and stock where each holder may elect the form, subject to proration. | `mixed_cash_stock` | Type of Consideration; Limitations on FTR Exercise; Superior Offer Definition; Tail Period & Acquisition Proposal Details | `election_mechanics`; `proration`; `per_share_cash_amount`; `exchange_ratio` |
| `other` | *(none; Hub has no Other class)* | Non-standard or unstated consideration; do not force a cash/stock token when the agreement is silent or ambiguous. | - | - | `consideration_description`; `cvr` |

`Type of Consideration` → token is the scorer's own `normalize_maud_consideration`
(verified in `tests/test_maud_schema.py`); `mixed_cash_stock` ↔
`mixed_cash_stock_election` are family-equivalent for the **subclass** dimension only —
`maud_question_accuracy` still scores the two `Type of Consideration` classes as
different answers. The entity hints are documentation: the tests assert none of them
enter the scored field map.

## 6. Scorer vs. prompt: observed inconsistencies

Found while building the round-trip tests (`tests/test_maud_schema.py`). Items
marked **fixed** were corrected in the scorer in the same change (SAND-042 RCA)
and are pinned by `tests/test_maud_catalog.py`.

1. **Answers are never shown to the model.** See section 1. (Prompt-side; the
   rendered block fixes it for stems built from `render_maud_question_block`.)
2. **Fixed — double-space question name.** A model that normalizes
   `"Fiduciary exception:  Board determination (no-shop)"` to one space used to be
   split at the first colon (unknown question `Fiduciary exception`). Span prefixes
   are now whitespace-tolerant.
3. **Free-text lines inside `maud_clauses`.** The frozen prompt's per-subclass brief asks
   for "exchange ratio / stock consideration language", "per-share cash and stock mix"
   and "election mechanics" *in `maud_clauses`*. Those lines are not
   `'<Question>: <class>'`; they become unknown extra questions (ignored by the MAUD
   extras) but depress the `maud_clauses` field's token-F1.
4. **`maud_category_accuracy` is structurally 0.** Span predictions carry
   `category=""`, and the prompt format cannot carry a category. Not a model error.
5. **Fixed — null mapping entries.** A top-level `{question: null}` is now
   unanswered rather than present-but-invalid; see section 2 for the shapes that
   still count as present.
6. **Fixed — newline-joined strings** in `maud_clauses` are split into one span per
   line.
7. **Fixed — `> 5 business days` ≡ `5 business days`.** `maud._fold` now spells
   comparators out (`>` → `greater than`, `>=`/`≥` → `at least`, …) before stripping
   punctuation, so the two classes stay distinct; `scorer_fold_collisions()` reports
   only intended equivalences.
8. **Fixed — a legitimate class made GT unscorable.** `detect_maud_gt_ambiguity` no
   longer splits a value that is itself a catalog class, so the 4
   `Tail Period & Acquisition Proposal Details` classes containing
   `No-Vote / MTC Failure Trigger` score normally.
9. **`Type of Consideration` degrades unknown text to `other`**
   (`tasks.normalize_maud_consideration`), and accepts `none`/`cash`/`stock` aliases as
   valid, unlike the other 21 questions.

## 7. Verification

```bash
python -m pytest tests/test_maud_schema.py -q
```

The tests pin: 22 questions == `MAUD_QUESTION_KEYS`; `valid_classes` == catalog; every
fixture class representable; every one of the 265 `<Question>: <class>` lines
round-trips through `parse_maud_labels`/`score_maud_extraction`; a perfect
schema-built prediction scores 1.0 on the merger suite (lines and object shape); the
JSON Schema accepts GT-shaped predictions and rejects paraphrases, wrong question
names, single-space fiduciary names, extra keys, and bad tokens.

See also: [`MAUD_LABELS.md`](MAUD_LABELS.md) (catalog provenance),
[`EXTRACTION_SCHEMAS.md`](EXTRACTION_SCHEMAS.md#2-merger_agreement--mergeragreementextraction-10-fields).
