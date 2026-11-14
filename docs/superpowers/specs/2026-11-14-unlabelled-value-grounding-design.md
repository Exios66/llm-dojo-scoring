# Unlabelled-value grounding, review candidates and label provenance — design

Status: draft for owner approval · Date: 2026-11-14 · Target: the `v0.30.0` staging branch

## 1. Intent

When an extraction model fills a field the ground truth (GT) does not label, the Dojo
today says nothing useful about that value. Since #139 (and its `pending_annotation`
follow-up) such a value is correctly **excluded** from field-micro P/R/F1 and from
`overall_score`, so it is neither rewarded nor punished. But it may be a hallucination,
or it may be a correct value the dataset simply has not labelled yet.

We want to:

1. **Measure** how often the model states values on unlabelled fields that the source
   document does not support: an *unlabelled-value hallucination rate*, tracked over
   time per run, document class and field.
2. **Route** each unsupported (or uncheckable) value to a reviewer as a candidate.
3. **Grow the dataset**: a value that a trusted reviewer confirms becomes a *valid label*
   with recorded provenance, exportable for the dataset's own ingestion process.
4. **Keep agent reviewers honest**: an adjudicating agent (the mailroom boss, or a tuned
   decision model such as JEV) may confirm labels only while its agreement with human
   spot-checks stays above a bar; the Dojo measures that agreement continuously.

All of this is a **separate calculation**. It must never change, obscure or be mixed
into the scoreable content measured by the traditional headline metrics.

## 2. Goals, non-goals, anti-goals

**Goals**

- A deterministic per-value verdict for every non-empty predicted value on an unlabelled
  field: `grounded`, `not_found` or `unverifiable`.
- Run-level rates, per class and per field, under their own metric ids, at a non-headline
  registry tier.
- A candidates export (one record per value needing review) and an ingest path for
  confirmations from a person, the boss or JEV.
- A per-reviewer agreement measurement against human spot-checks, and a trust gate that
  decides which agent confirmations count.
- A valid-labels export carrying provenance for every label.

**Non-goals (this project)**

- Any LLM call from the Dojo. The Dojo stays deterministic and network-free.
- Writing to Langfuse, Hugging Face or any hosted service. Exports are local files /
  return values; consumers move them.
- The llm-mailroom side: a "confirm this value" role for the boss / JEV, a review UI, or
  wiring this module into the pipeline. Separate follow-on project in llm-mailroom.
- The dataset side: ingesting valid labels into `mailroom-dataset`. Separate follow-on.
- Verifying extra items inside a *partially* labelled list field (`partial_gt` fields).
  v1 audits whole unlabelled fields only; see §9.

**Anti-goals (a failure even if it works)**

- Any change to `overall_score`, field-micro P/R/F1/F2, class headlines, `metric_id`
  selection, the existing `entity_list_audit` / `extraction_hallucination_rate`, or the
  golden baseline. `freeze_goldens.py --check` must pass unchanged.
- A model's own output entering the dataset as a label without a person's or a trusted
  agent's confirmation (circularity: later models would be scored against it).
- Calling a value "hallucinated" when it merely could not be checked (an inferred
  category, a reformatted value, or no document text).
- Losing track of which reviewer confirmed a label, so an agent later found unreliable
  could not have its labels found and withdrawn.

## 3. Constraints (from the repo)

- Dojo owns scoring logic; no LLM calls; core deps stay small (`CLAUDE.md`).
- Public surface changes need `docs/guides/PUBLIC_API.md`, `tests/test_public_api_doc.py`
  and, if consumers adopt it, `tests/fixtures/consumer_surface.json`. A new module stays
  **`hold`** in `docs/analysis/data/consumer_closure.json` until llm-mailroom imports it
  (precedent: `scoring.decision_lanes`, `ml.*`).
- Existing helpers to reuse, not re-implement, in `scoring/field_scoring.py`:
  `verify_list_items`, `_containment_tokens`, `_date_grounded_in_doc`,
  `get_verification_coverage()` (config `field_scoring.verification_token_coverage`,
  default 0.7) and `verification_enabled()`. GT helpers in `schemas/gt_metadata.py`:
  `parse_gt_fields`, `gt_presence_map`, `ABSENT_PRESENCE_STATUSES`, `is_empty_value`.
- Metric ids are registered in `metrics/registry.py` with a `MetricTier`
  (`HEADLINE=0, CORE=1, DEEP=2, LOG=3`) and listed in `docs/contracts/METRIC_IDS.md`.
- The CLIs were cut in the slim-down (only `dojo-version` remains): v1 ships a library
  API, not a new console script.
- `ScoreRecord(agent, metric, value, doc_id, run_id, metadata)` is the emitted unit;
  the new rates are emitted as ordinary `ScoreRecord`s with their own metric ids.

## 4. Approaches considered

| | Approach | Trade-off | Verdict |
|:--|:--|:--|:--|
| A | Extend the factuality audit inside `score_extraction` and add an "unlabelled" section to every scoring payload | No new wiring, but changes `ExtractionScoreResult` / suite payload shapes (cross-repo bump), grows the most sensitive function, and keeps headline separation only by convention | Rejected |
| **B** | **A separate module, run as its own pass after scoring** | Headline isolation is structural (not on the scoring path); existing payloads unchanged; consumers must call it explicitly; re-checks text scoring already saw (cheap) | **Chosen by the owner** |
| C | Build it in llm-mailroom next to the review tray | Metric definitions would live outside the Dojo; sandbox / evals would re-implement them | Rejected |

## 5. Decisions made with the owner

- **Uses:** all three — trend rate, review routing, dataset growth — plus helpful extras.
- **Validity rule:** a value is never a label because it was found in the text. Found
  text makes it a *candidate*. It becomes a **valid label** only when confirmed by a
  person, or by a trusted adjudicating agent (the boss) / tuned decision model (JEV)
  that rules with certainty. Only valid labels may go to the official dataset.
- **Trusting agents:** the Dojo keeps measuring each agent's agreement with human
  spot-checks; an agent's confirmations count only while that agreement stays above a
  bar.
- **Approach B.**

## 6. Design

### 6.1 Module layout

New subpackage `llm_dojo_scoring/grounding/` (structural separation from `scoring/`):

| Module | Owns |
|:--|:--|
| `grounding/audit.py` | per-value verdicts and run-level rates (piece 1) |
| `grounding/candidates.py` | candidate records, confirmations, provenance, valid-label export (piece 2) |
| `grounding/agreement.py` | reviewer agreement vs human spot-checks, the trust gate, spot-check sampling (piece 3) |

Nothing in `scoring/`, `metrics/emitter.py` or the suites imports `grounding/`. A test
asserts that (import-graph check), which is how the "never touches headlines" promise
is enforced by structure.

### 6.2 Piece 1 — what is "unlabelled", and the verdicts

For one document, given the **raw** GT row (Hub metadata or plain dict), the prediction,
the class field map and the document text:

A predicted field `k` with a non-empty value is **audited** when `k` is in the class field
map and the GT does not label it:

- `k` is absent from the parsed GT, **or** its `gt_presence` status is
  `pending_annotation`. (A field present with an empty value and no presence status is
  covered by §10 question 1; the proposed default leaves it out.)
- Not audited: fields labelled with a value (they are scored by the headline path);
  fields whose status is `not_applicable` / `schema_documented_absence` (labelled empty —
  a value there is already a headline false positive); CMS documented-absent
  `adjuster` / `denial_reasons` on CMS rows (same reason); `NEVER_SCORED_FIELDS`,
  annotation keys, off-schema keys (already headline FPs).

Each audited value gets one **verdict**:

| Verdict | Rule |
|:--|:--|
Verdict rule per registry field type (`schemas/doc_classes.py` has exactly `name`,
`free_text`, `date`, `label`, `money`, `id`, `entity_list`):

| Field type | `grounded` when | otherwise |
|:--|:--|:--|
| `name`, `free_text` | token containment ≥ `verification_token_coverage` (`_containment_tokens`) | `not_found` |
| `date` | `_date_grounded_in_doc` | `not_found` |
| `money` | the parsed amount (digits and decimal point, currency symbols and words dropped) equals an amount parsed from the document | `not_found` if parsing succeeds on the value; `unverifiable` if the value does not parse as an amount |
| `id` | the value, with case, whitespace and `-`/`/`/`.` separators removed, is a substring of the document text normalised the same way | `not_found` |
| `entity_list` | handled per item (see "Lists" below) | |
| `label` | never — a closed-vocabulary / inferred value (`intent`, `claim_type`, `cuad_family`, …) is not a literal in the text | always `unverifiable` |

Also `unverifiable`, whatever the type: no document text; or a value with no comparable
tokens after normalisation. A field missing from the registry map is not audited.

**Lists.** An `entity_list` value is split into items (the same split as
`verify_list_items`) and **each item is audited, and becomes a candidate, on its own**,
with its own verdict. The field-level rate counts items, not lists.

Per-value record (plain dict / frozen dataclass, JSON-serialisable):

```
{ run_id, doc_id, doc_class, doc_subclass, field, field_type, value,
  item_index (lists only, else null), verdict, coverage, gt_status ("absent"|"pending_annotation"),
  doc_text_sha256, extractor (model/agent id if given), audited_at }
```

`doc_text_sha256` lets a reviewer and the dataset prove which source the verdict was
made against without the Dojo storing document text.

**Run-level rates** (aggregate over audited values; a value with no audit is not a
denominator):

| Metric id | Value | Tier |
|:--|:--|:--|
| `grounding.unlabelled.not_found_rate` | `not_found / (grounded + not_found)` — the hallucination rate; `unverifiable` excluded from the denominator | CORE (1) |
| `grounding.unlabelled.unverifiable_share` | `unverifiable / all audited` — how much the rate cannot see | DEEP (2) |
| `grounding.unlabelled.n_audited` | count | LOG (3) |

Each is also reported per `doc_class` and per `field` (metadata on the `ScoreRecord`,
same metric id). Null, never 0.0, when the denominator is 0. The name deliberately
differs from the existing `extraction_hallucination_rate` (which mixes labelled and
unlabelled fields) so dashboards cannot confuse them.

Public entry points (piece 1):

```python
audit_unlabelled_values(gt_row, predicted, *, doc_class, doc_text, doc_subclass=None,
                        field_types=None, run_id=None, doc_id=None, extractor=None)
    -> list[UnlabelledValueAudit]
summarize_unlabelled_audits(audits) -> UnlabelledAuditSummary   # rates, per class, per field
unlabelled_score_records(summary, *, agent, run_id) -> list[ScoreRecord]
```

### 6.3 Piece 2 — candidates, confirmations, provenance, valid labels

**Candidate:** every audited value with verdict `not_found` or `unverifiable` is a
review candidate. `grounded` values are candidates too, flagged lower priority — a
grounded value is still not a label until confirmed (owner rule). A deterministic
`candidate_id = sha256(doc_id | field | normalised value | doc_text_sha256)` makes
candidates idempotent across re-runs. "Normalised" is the type's own normaliser from
the verdict table (casefold + whitespace collapse for text, ISO date, parsed amount,
separator-stripped id); for list items it is the item, not the whole list, so order
does not change ids. A `corrected_value` never re-keys a candidate.

Priority (for the review queue the consumer builds): `not_found` > `unverifiable` >
`grounded`; ties by field frequency. The Dojo exports priority; it does not own a queue.

**Confirmation** (ingested from llm-mailroom or a human tool; JSONL or list of dicts):

```
{ candidate_id, verdict: "valid" | "hallucinated" | "unsure",
  corrected_value (optional), reviewer_kind: "human" | "agent",
  reviewer_id ("human:<opaque id>" | "boss@<prompt version>" | "jev-1.13.0"),
  certainty (agents: required, 0..1; humans: omitted), confirmed_at, note }
```

Validation: unknown `candidate_id`, missing `reviewer_id`, or an agent confirmation
without `certainty` is rejected with a reason (never silently dropped).

**The ledger is append-only.** Confirmations are never edited or deleted; a change of
mind is a new confirmation. `valid_labels(...)` is a pure function of the whole ledger
plus the gate history, re-derived every time, so a withdrawal is simply the absence of a
label on the next derivation (and is listed in a `withdrawn` section by comparing with a
previous export, if one is passed).

**Valid label** rule, per candidate:

- Only each reviewer's **latest** confirmation counts.
- If any human's latest verdict exists, humans decide: valid when every human with a
  latest verdict says `valid` (or `valid` with the same `corrected_value`); a human
  `hallucinated` or a disagreement between humans → not valid, reported as a conflict.
  A human `unsure` neither validates nor blocks.
- With no human verdict: valid only when at least one agent says `valid`, that agent was
  **trusted as of its `confirmed_at`** (piece 3) with `certainty ≥` the certainty floor,
  and no other agent's latest verdict is `hallucinated`. Agents disagreeing → pending,
  routed to a human.
- A later human `hallucinated` on a value that was valid on agent grounds removes it on
  the next derivation and counts as a human/agent disagreement for that agent.
- `corrected_value` becomes the label value, with the same provenance.

**Valid-label export** — one record per label, carrying full provenance:

```
{ doc_id, field, value, source_candidate_id, extractor, doc_text_sha256,
  confirmed_by: [{reviewer_kind, reviewer_id, verdict, certainty, confirmed_at}],
  validity_basis: "human" | "trusted_agent", gate_snapshot_id }
```

`gate_snapshot_id` names the agreement snapshot that made an agent trusted, so labels
an agent approved can be found and withdrawn later if its agreement falls.

Public entry points (piece 2):

```python
candidates_from_audits(audits) -> list[ReviewCandidate]
ingest_confirmations(records, candidates) -> ConfirmationLedger   # validated, with rejects
valid_labels(ledger, gate) -> list[ValidLabel]
export_jsonl(items, path)  # helpers for candidates / valid labels (local file only)
```

### 6.4 Piece 3 — agent agreement and the trust gate

- **Spot-check sampling:** `select_spot_checks(ledger, *, rate, seed)` picks a
  deterministic random sample (seeded by `candidate_id`) of each agent's confirmations
  to send to humans. Default rate 10% per agent, minimum 20 per agent per window;
  configurable.
- **Agreement:** for every candidate confirmed by both an agent and a human, agreement =
  same verdict (`valid`/`hallucinated`; `unsure` from either side excluded). Report per
  `reviewer_id`: n, agreement rate, Wilson 95% lower bound, per-field breakdown, and
  Cohen's κ where both classes occur.
- **Trust gate:** see §10 question 2 for what the bar is measured on. An agent is
  trusted when, over its rolling window (default last 200 paired checks, ordered by the
  human's `confirmed_at`), `n ≥ min_n` (default 50) **and** the Wilson lower bound ≥
  `bar` (default 0.95). Untrusted agents' confirmations stay pending (never valid) until
  a human confirms. A new agent version (different `reviewer_id`) starts untrusted.
- **Trust over time:** trust is evaluated **as of each confirmation's `confirmed_at`**,
  never retroactively. `TrustGate.history(ledger)` replays the ledger in time order and
  returns serialisable `GateSnapshot`s (id = hash of reviewer id, window bounds and
  numbers); `valid_labels(ledger, gate)` looks up the snapshot in force when each agent
  confirmation was made. The Dojo stores nothing: the caller keeps the ledger (JSONL),
  and every snapshot can be recomputed from it.
- **Regression guard (extra):** when a gate snapshot drops an agent below the bar, the
  snapshot lists every valid label whose `validity_basis` was that agent since its last
  passing snapshot, for re-review.
- Agreement metrics are emitted as `grounding.reviewer.valid_precision` and
  `grounding.reviewer.valid_precision_lower_bound` (CORE, the gated numbers) and
  `grounding.reviewer.agreement` (DEEP, overall), with `reviewer_id` in metadata.

Public entry points (piece 3):

```python
select_spot_checks(ledger, *, rate=0.10, min_per_agent=20, seed=0) -> list[str]  # candidate_ids
reviewer_agreement(ledger, *, window=200) -> dict[str, ReviewerAgreement]
TrustGate(bar=0.95, min_n=50, certainty_floor=0.9).history(ledger) -> list[GateSnapshot]
```

### 6.5 Extras (helpful, small)

- Per-field hallucination leaderboard in the summary ("`sender`: 30% not found").
- Confirmed-label regression set: `valid_labels` can be fed back as plain expected
  dicts so a later model is checked on values a person already confirmed — but scored
  through the normal suites as a **separate** run, never merged into the official GT.

## 7. Testing

- Unit tests per piece with synthetic Hub-shaped rows (reuse `hub_row` from
  `tests/behavior/test_class_headline_contract.py`), synthetic document text only.
- **Isolation test:** importing `llm_dojo_scoring.scoring`, the suites and the emitter
  does not import `llm_dojo_scoring.grounding` (checked via `sys.modules` in a fresh
  subprocess); and running the full audit on the golden fixtures leaves
  `freeze_goldens.py --check` unchanged.
- Verdict table tests: grounded / not_found / unverifiable for scalar, date, list,
  closed-vocabulary, missing doc text, pending vs absent vs blank GT, CMS exclusions.
- Ledger tests: rejects, human-beats-agent, human-human conflict, corrected values,
  idempotent `candidate_id`.
- Gate tests: Wilson bound math, below-`min_n`, version change resets trust, the
  regression-guard listing.
- Gates: ruff, full suite, goldens `--check`, `test_public_api_doc.py` (new names
  documented), `consumer_closure.py --check` (new modules recorded as `hold`).

## 8. Delivery

Three stacked PRs onto `v0.30.0`, in order: piece 1 → piece 2 → piece 3. Each follows
`.claude/rules/pr-flow.md` (score/metric work: three adversarial rounds, fresh pre-PR
review, draft PR). No public names on the consumer surface change; new names are added
under `grounding` and documented in `PUBLIC_API.md`. Follow-on (not this project):
llm-mailroom wiring + boss/JEV confirm role + review UI; dataset ingestion.

## 9. Left to the builder

- Exact dataclass names and module-private helpers.
- How the closed-vocabulary field set is derived from `schemas/doc_classes.py` (with a
  minimal override list if needed).
- Whether per-class / per-field breakdowns are separate records or metadata (prefer
  metadata on one metric id, matching existing registry practice).
- Default thresholds are proposals (§6.4) and live in `Settings` so they can be tuned
  without code changes.
- `partial_gt` list fields (extra items beyond an incomplete GT list) are out of v1;
  record them as a follow-up.
- The amount and id parsers' exact edge cases (they must be deterministic and tested).

## 10. Open questions for the owner

Builder check (fresh reader) raised six points. Four were settled in the text above
(trust as of `confirmed_at`, per-item list candidates, the append-only ledger and its
conflict rules, the per-type verdict table). Two are the owner's:

1. **A field present in the GT with an empty value and no presence status.** Since
   #139 the headline path treats it as *labelled empty*, so a value there is already a
   false positive. Proposed default: **do not audit it** (it is labelled, the headline
   already judges it, and the two calculations stay disjoint). The alternative also
   sends it for review as a possible missing label, at the cost of one value counting in
   both places.
2. **What the trust bar measures.** Only an agent's `valid` verdict creates a label, but
   plain agreement also rewards easy `hallucinated` calls. Proposed default: **gate on
   the precision of the agent's `valid` verdicts** (of the values it called valid, the
   share humans also called valid), and *report* overall agreement and κ alongside it.
