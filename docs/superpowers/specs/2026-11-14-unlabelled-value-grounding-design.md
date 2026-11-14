# Unlabelled-value grounding, review candidates and label provenance — design

Status: approved 2026-11-14 · Release: 0.31.0 (after v0.30.0) · Date: 2026-11-14 · Target: the `v0.30.0` staging branch

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

New subpackage `llm_dojo_scoring/grounding/`, structurally separate from `scoring/`.
One responsibility per module; §11 is the binding layout and naming table.

Nothing in `scoring/`, `metrics/emitter.py`, the suites or the package root imports
`grounding/`. A subprocess test asserts that, which is how the "never touches headlines"
promise is enforced by structure rather than by convention.

### 6.2 Piece 1 — what is "unlabelled", and the verdicts

For one document, given the **raw** GT row (Hub metadata or plain dict), the prediction,
the class field map and the document text:

A predicted field `k` with a non-empty value is **audited** when `k` is in the class field
map and the GT does not label it:

- `k` is absent from the parsed GT, **or** its `gt_presence` status is
  `pending_annotation`. A field present with an empty value and no presence status is
  labelled empty and **not** audited (owner decision, §10).
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
| `grounding_not_found_rate` | `not_found / (grounded + not_found)` — the hallucination rate; `unverifiable` excluded from the denominator | CORE (1) |
| `grounding_unverifiable_rate` | `unverifiable / all audited` — how much the rate cannot see | DEEP (2) |
| `grounding_n_audited` | count | LOG (3) |

Each is also reported per `doc_class` and per `field` (metadata on the `ScoreRecord`,
same metric id). Null, never 0.0, when the denominator is 0. The name deliberately
differs from the existing `extraction_hallucination_rate` (which mixes labelled and
unlabelled fields) so dashboards cannot confuse them.

Public entry points (piece 1):

```python
audit_unlabelled_values(gt_row, predicted, *, doc_class, doc_text, doc_subclass=None,
                        run_id=None, doc_id=None, extractor=None)
    -> list[UnlabelledValueAudit]
summarize_grounding(audits) -> GroundingSummary   # rates, per class, per field
grounding_score_records(summary, *, agent, run_id) -> list[ScoreRecord]
```

As built, the field types always come from the class registry, plus the headline's
`CMS_ROW_FIELD_TYPES` on a CMS row, exactly as scoring uses them. A `field_types=`
override was dropped so the audit can never type a field differently from the
headline. `docs/contracts/GROUNDING.md` is the contract.

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
mind is a new confirmation. `derive_valid_labels(...)` is a pure function of the whole ledger
plus the gate history, re-derived every time, so a withdrawal is simply the absence of a
label on the next derivation (and is listed in a `withdrawn` section by comparing with a
previous export, if one is passed).

**Valid label** rule, per candidate:

- Only each reviewer's **latest** confirmation counts.
- If any human's latest verdict exists, humans decide: valid when every human with a
  latest verdict says `valid` (or `valid` with the same `corrected_value`); every human
  `hallucinated` → rejected; a disagreement between humans → not valid, reported as a
  conflict.
  A human `unsure` neither validates nor blocks.
- With no human verdict: valid only when at least one agent says `valid`, that agent was
  **trusted as of its `confirmed_at`** (piece 3) with `certainty ≥` the certainty floor,
  and no other agent's latest verdict is `hallucinated`. Agents disagreeing → a
  conflict (`agents_disagree`), routed to a human.
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
review_candidates(audits) -> list[ReviewCandidate]
ingest_confirmations(records, candidates) -> ConfirmationLedger   # validated, with rejects
derive_valid_labels(ledger, gate) -> list[ValidLabel]
write_jsonl(items, path) / read_jsonl(path)  # grounding/io.py, local files only
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
- **Trust gate:** the bar is measured on the **precision of the agent's `valid`
  verdicts** (owner decision, §10). An agent is
  trusted when, over its rolling window (default last 200 paired checks, ordered by the
  human's `confirmed_at`), `n ≥ min_n` (default 50) **and** the Wilson lower bound ≥
  `bar` (default 0.95). Untrusted agents' confirmations stay pending (never valid) until
  a human confirms. A new agent version (different `reviewer_id`) starts untrusted.
- **Trust over time:** trust is evaluated **as of each confirmation's `confirmed_at`**,
  never retroactively. `TrustGate.history(ledger)` replays the ledger in time order and
  returns serialisable `GateSnapshot`s (id = hash of reviewer id, window bounds and
  numbers); `derive_valid_labels(ledger, gate)` looks up the snapshot in force when each agent
  confirmation was made. The Dojo stores nothing: the caller keeps the ledger (JSONL),
  and every snapshot can be recomputed from it.
- **Regression guard (extra):** when a gate snapshot drops an agent below the bar, the
  snapshot lists every valid label whose `validity_basis` was that agent since its last
  passing snapshot, for re-review.
- Agreement metrics are emitted as `grounding_reviewer_valid_precision` and
  `grounding_reviewer_valid_precision_lower_95` (tier 1, the gated numbers),
  `grounding_reviewer_agreement` and `grounding_reviewer_kappa` (tier 2) and
  `grounding_reviewer_n_checked` (tier 3), with `reviewer_id` in metadata.

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

See §12 for the full order across the constellation. In the Dojo: three stacked PRs
(piece 1 → piece 2 → piece 3), each following `.claude/rules/pr-flow.md` (new-metric
work: three adversarial rounds, a fresh pre-PR review, a draft PR), released together as
**0.31.0** after 0.30.0 is cut. The new modules stay `hold` in `consumer_closure` and
are documented in `docs/contracts/GROUNDING.md` and the package README; they join
`docs/guides/PUBLIC_API.md` and `tests/fixtures/consumer_surface.json` in the
cross-repo bump that first imports them from llm-mailroom.

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

## 10. Owner decisions on the builder check

A fresh reader raised six points. Four were settled in the text above: trust is judged as
of `confirmed_at`, list items are separate candidates, the ledger is append-only with
the conflict rules in §6.3, and each field type has its own verdict rule. The owner
decided the other two on 2026-11-14:

1. **A field present in the GT with an empty value and no presence status is not
   audited.** Since #139 the headline treats it as labelled empty and already counts a
   value there as a false positive. The grounding pass covers only absent and
   `pending_annotation` fields, so no value is counted in both calculations.
2. **The trust bar is measured on the precision of the agent's `valid` verdicts**: of the
   values it called valid, the share humans also called valid, by Wilson lower bound.
   Overall agreement and κ are reported next to it but do not gate trust.

## 11. Code organization and naming (binding)

House conventions this follows: subpackage `__init__.py` holds only a one-line
docstring (no re-exports); consumers map their own stores to input dataclasses, as
`scoring.reviewer.ReviewRecord` does; metric ids are snake_case with a family prefix
(`reviewer_*`, `extraction_*`, `legalbench_*`), counts are `<family>_n_<thing>` and
one-sided bounds end `_lower_95` / `_upper_95`; contracts live in `docs/contracts/`;
statistics reuse `analysis.bootstrap.wilson_ci`; settings live in `config.Settings`.

| Path | Piece | Owns | Public names |
|:--|:--|:--|:--|
| `grounding/__init__.py` | 1 | docstring only | — |
| `grounding/verdicts.py` | 1 | per-type check of one value against document text | `GROUNDED`, `NOT_FOUND`, `UNVERIFIABLE`, `VERDICTS`, `value_verdict` |
| `grounding/selection.py` | 1 | which predicted fields are unlabelled (the one place the rule lives; reuses `scoring_gt_fields`) | `UNLABELLED_STATUSES`, `unlabelled_fields` |
| `grounding/audit.py` | 1 | per-value audit records | `UnlabelledValueAudit`, `audit_unlabelled_values` |
| `grounding/summary.py` | 1 | counts, rates, breakdowns, `ScoreRecord`s | `GroundingCounts`, `GroundingSummary`, `summarize_grounding`, `grounding_score_records` |
| `grounding/io.py` | 2 | local JSONL read/write for every grounding record type | `read_jsonl`, `write_jsonl` |
| `grounding/candidates.py` | 2 | review candidates, stable ids, priority | `ReviewCandidate`, `candidate_id`, `review_candidates` |
| `grounding/ledger.py` | 2 | confirmations, validation, the append-only ledger | `Confirmation`, `ConfirmationReject`, `ConfirmationLedger`, `ingest_confirmations` |
| `grounding/labels.py` | 2 | valid-label derivation, conflicts, withdrawals | `ValidLabel`, `LabelDerivation`, `derive_valid_labels` |
| `grounding/agreement.py` | 3 | paired human/agent checks, precision of `valid`, κ, spot-check sampling | `ReviewerAgreement`, `reviewer_agreement`, `select_spot_checks` |
| `grounding/trust.py` | 3 | the trust gate and its time-ordered snapshots, regression guard | `TrustGate`, `GateSnapshot` |
| `config.py` (`GroundingSettings`, key `grounding`) | 3 | `trust_bar=0.95`, `trust_min_n=50`, `trust_window=200`, `certainty_floor=0.9`, `spot_check_rate=0.10`, `spot_check_min_per_agent=20` | — |
| `tests/grounding/test_grounding_<module>.py` + `tests/grounding/conftest.py` | all | one test file per module; shared synthetic documents and Hub rows | — |
| `docs/contracts/GROUNDING.md` | all | the contract: audited set, verdicts, metric ids, ledger and trust rules | — |

Extension points, so later work is additive:

- A new field type adds one row to the dispatch table in `verdicts.py` and one test row.
- A new reviewer kind (e.g. a second decision model) needs no code: `reviewer_id` is
  free text and every agent is gated by the same `TrustGate`.
- A new export format adds a writer next to `io.py`; record types expose `as_dict()` /
  `from_dict()` and never change shape without a `schema_version` bump (every record
  carries `schema_version: 1`).

**Metric ids** (registry, `aggregation` and units as listed):

| Id | Tier | Units | Piece |
|:--|:--|:--|:--|
| `grounding_not_found_rate` | 1 | float[0,1] | 1 |
| `grounding_unverifiable_rate` | 2 | float[0,1] | 1 |
| `grounding_n_audited` | 3 | count | 1 |
| `grounding_n_candidates` | 3 | count | 2 |
| `grounding_n_valid_labels` | 3 | count | 2 |
| `grounding_n_label_conflicts` | 3 | count | 2 |
| `grounding_reviewer_valid_precision` | 1 | float[0,1] | 3 |
| `grounding_reviewer_valid_precision_lower_95` | 1 | float[0,1] | 3 |
| `grounding_reviewer_agreement` | 2 | float[0,1] | 3 |
| `grounding_reviewer_kappa` | 2 | float[-1,1] | 3 |
| `grounding_reviewer_n_checked` | 3 | count | 3 |

## 12. Constellation sequencing

Tracked in Exios66/llm-dojo-scoring#146.

The mailroom side cannot start until both release lines are clear. Order:

1. **Dojo 0.30.0** — land the open stack onto `v0.30.0` (#140, #142, #143, #144; #145 is
   the release PR), cut 0.30.0.
2. **llm-mailroom catches up to 0.30.0** — #230 (pin at the trimmed Dojo stack) then
   #231 (scoring fixes, stacked on #230), re-pinned to the 0.30.0 release commit;
   the audit stack #226 → #227 → #229 (storage, diagnostics workbench, live audit row);
   #222 (GT label workbook). #228 is a consolidation draft and #204 / #160 are held: not
   prerequisites.
3. **Dojo 0.31.0** — grounding pieces 1, 2, 3 (this design). Can be built in parallel
   with step 2; lands after step 1.
4. **llm-mailroom wiring** (separate design, after steps 2 and 3), building on what the
   open PRs add:
   - pin bump to 0.31.0 with `/dojo-bump`, plus the `/cross-repo-bump` walk (grounding
     enters `PUBLIC_API.md` and `consumer_surface.json`; `consumer_closure` hold → keep);
   - run the grounding pass in `src/graph/scoring_nodes.py` (#229) after extraction
     scoring, behind a taxonomy flag, off by default;
   - emit the rates through `src/audit/sinks/` (#229) and register the names in
     `SCORE_CONFIGS`; persist audits and candidates in the audit storage (#226);
   - human review: candidates exported to the GT label workbook (#222) and shown as a
     queue in the diagnostics workbench (#227); confirmations read back into the ledger;
   - boss and JEV "confirm this value" roles (a Langfuse-managed prompt registered in
     `prompt_templates()`; JEV adapter emitting `certainty`);
   - follow-ups: The-Mailroom schema mirror if spans change; sandbox vendor refresh.
5. **mailroom-dataset ingestion** of exported valid labels, human-run, separate repo.
