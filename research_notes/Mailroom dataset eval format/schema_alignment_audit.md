# Extraction-schema alignment audit — corporate-record (and other record-type) schemas across llm-dojo-scoring, eval-environment, local-mailroom-sandbox, Mailroom-Corpus-EDA

Repo/branch snapshots audited (read-only; 2026-10-17):

- `llm-dojo-scoring` @ `feat/corporate-record-subclass-schemas`, HEAD `e592ab0` (branch adds `corporate_record_schema.py` + unlabeled scoring)
- `eval-environment` @ `STAGING` HEAD `4ffe258` (prompts frozen at v1) — with cross-checks of sibling branch `feat/corporate-records-v7` HEAD `b449a79` (carries v6/v7 + sorter_v4)
- `local-mailroom-sandbox` @ `feat/corporate-records-subclass-v2` HEAD `649f71c`
- `Mailroom-Corpus-EDA` @ `feat/grounded-corporate-backfill` HEAD `37f7542`

All paths below are relative to those worktrees. Byte/wild-card equality claims ("==") were verified by direct diff or sha256 comparison, not by reading docs. Inferences (not read directly from code) live in the Inferences subsections.

---

## Where the per-subclass entity schema is defined, and whether the subclass → entity-field maps agree

### Takeaway

The one true per-subclass schema lives in the dojo (`llm_dojo_scoring/corporate_record_schema.py`, guarded at import against `corpus.DOC_TYPE_SUBCLASSES`). The eval-environment v7 prompt, the sandbox `corporate_records_specialist_subclass_v2` stem, and the dojo-rendered prompt block are byte-identical (sha256 `b40963bb…`, 5,333 chars, verified), so the 10 frozen/snowflake subclass lines agree everywhere that has taken v7. Every other copy is stale: sandbox's own taxonomy still carries the retired `key_provisions` and lacks the semantic trio, the vendored dojo snapshot (v0.22.0) predates the whole feature, STAGING never received v7, and the default sandbox pin still serves v6 (old executive-brief doctrine with different intent pins).

### Cited Findings

**Dojo — canonical schema data**

- `llm-dojo-scoring / llm_dojo_scoring/corporate_record_schema.py:134` — `SUBCLASS_SCHEMAS` defines **11 keys**: `bylaws`, `articles_of_incorporation`, `certificate_of_formation`, `charter_amendment`, `powers_of_attorney`, `subsidiary_list`, `rights_instrument`, `indenture`, `board_resolution`, `officer_certificate`, `other`, each with `record_type` (5-token enum, lines 81–87), pinned `intent`, `core_applicable`, and `RecordEntity` extension fields (dataclass at :90–98).
- `llm-dojo-scoring / llm_dojo_scoring/corporate_record_schema.py:299-309` — import-time drift guards: subclass set must equal `corpus.DOC_TYPE_SUBCLASSES["corporate_record"]`; every `record_type` must be in the enum; entity keys must not shadow the 9 core fields.
- `llm-dojo-scoring / llm_dojo_scoring/corpus.py:87-99` — `DOC_TYPE_SUBCLASSES["corporate_record"]` = the same 11 keys (10 surfaces + `certificate_of_formation`). `corpus.py:189-201` (`CORPUS_SUBCLASS_SURFACES`) carries the **published-GT** vocabulary: 10 keys, **no `certificate_of_formation`** — Hub inventory has no rows for it.
- `llm-dojo-scoring / llm_dojo_scoring/corporate_record_schema.py:66-78` — the shared core is the flat 9-field `CorporateRecordExtraction` (`entity_name, record_type, effective_date, signatories, jurisdiction, filing_number, intent, subject_matter, keywords`; `DEFAULT_FIELD_TYPES["corporate_record"]` identical in `suites.py:95-105`), from which `ENTITY_CORE_FIELDS` = the six entity-bearing core fields.
- Record-type map (subclass → Hub token): `charter_amendment` and `certificate_of_formation` → `articles_of_incorporation`; `subsidiary_list`, `indenture`, `board_resolution`, `officer_certificate`, `other` → `other` (`corporate_record_schema.py:134-297`; mirrored in `docs/EXTRACTION_SCHEMAS.md:209-222`).
- Pinned intents: bylaws=`governance_rules`; articles/certificate_of_formation/charter_amendment=`entity_formation`; powers_of_attorney=`authority_delegation`; subsidiary_list=`other`; rights_instrument and indenture=`investor_rights`; board_resolution=`corporate_action_approval`; officer_certificate=`governance_rules`; other=`other` (`corporate_record_schema.py:137-295`). `intent_review` flags `charter_amendment`, `indenture`, `officer_certificate` as debatable (kept for score comparability; `docs/CORPORATE_RECORD_SCHEMA.md:48`).
- Docs table (`llm-dojo-scoring / docs/CORPORATE_RECORD_SCHEMA.md:30-44`) reproduces the same 11 rows incl. entities and not-applicable cores — no drift between module and doc.

**eval-environment (v7, on `feat/corporate-records-v7`) — identical to dojo/sandbox**

- `eval-environment @feat/corporate-records-v7 / prompts/corporate_records_specialist_v7.md` (lines 5–15 of file) — 10 subclass lines: same subclass→`record_type`,→`intent`; same `+entity keys` with `[]` list markers; same `null <inapplicable core>` list per line. `certificate_of_formation` is folded into a prose note ("= articles_of_incorporation with organizers instead of incorporators") exactly as the dojo's `render_prompt_section` does (`corporate_record_schema.py:513-520`).
- Byte equality verified: the v7 mutation body in `eval-environment @feat / prompts/mutations.json` computes sha256 `b40963bb3c53…` / 5,333 chars == `local-mailroom-sandbox / config/prompts/corporate_records_specialist_subclass_v2.txt` == the dojo template `llm_dojo_scoring/prompts/templates/corporate_records_specialist.production_prompts.md` (template differs only by a 2-line provenance comment). dojo `catalog.yaml:536-549` records that sha/source_key `corporate_records_specialist_v7`.
- Live diff verified: dojo `render_prompt_section()` output reproduces the sandbox prompt's per-subclass block **exactly** (unified diff shows zero differences among the 10 subclass lines).
- STAGING disagrees by omission: `eval-environment @STAGING / prompts/manifest.json` has lineage_id `mailroom-dataset-v1`, `frozen_version 1`, and only `corporate_records_specialist_v1`; `prompts/mutations.json` on STAGING contains corporate mutations only up to **v5**. v6 (commit `3f9bd55`) and v7 (commit `b449a79`) exist **only on `feat/corporate-records-v7`**.
- Old doctrine inside STAGING (`prompts/corporate_records_specialist_v1.md` = the v1 executive brief): `officer_certificate → intent corporate_action_approval`, `charter_amendment → "corporate_action_approval or entity_formation as stated"`. Those conflict with the dojo pins (`officer_certificate=governance_rules`, charter=entity_formation). Only relevant while a pre-v7 prompt is live.

**local-mailroom-sandbox**

- `config/prompts/corporate_records_specialist_subclass_v2.txt:5-15` — per-subclass block identical to dojo (verified `==`). Lines 30–40 carry the nine registered core fields with `record_type` 5-token enum (line 33) and `intent` 6-label enum (line 38) — enums match dojo `RECORD_TYPES` and `intents.py:15-21`.
- **Drift:** `local-mailroom-sandbox / config/mailroom.taxonomy.base.yaml:196-201` — corporate `field_types` still list the **retired** `key_provisions: entity_list:free_text` and **lack** `intent` / `subject_matter` / `keywords`. The sandbox's own eval key-sets (`src/mailroom_sandbox/eval/schema_adherence.py:104-114` and `src/mailroom_sandbox/eval/extraction_scope.py:58-67`) hold the clean 9-key core. Differs from: sandbox eval lists, vendor llm-mailroom taxonomy (`vendor/llm-mailroom/src/config/taxonomy.yaml:381-396`, clean 9 keys + semantic trio), dojo live map. Whichever side feeds `configure_from_taxonomy()` at runtime is authoritative; the base taxonomy is not. (I did not trace a runtime reader of `mailroom.taxonomy.base.yaml` field_types — gap below.)
- **Drift:** the sandbox runtime scoreboard is the vendored dojo `v0.22.0` (`vendor/llm-dojo-scoring/VENDOR.md`, pin `a2862cec`, 2026-10-16): `vendor/llm-dojo-scoring/src/llm_dojo_scoring/` has **no `corporate_record_schema.py`**, and diffing `suites.py` vs the feature branch shows the entire per-subclass machinery missing — no `required_ftypes` core-only format gate, no `align_unlabeled` block, format layer required keys = the scoring `ftypes` (v0.22.0 line `required_keys=list(ftypes.keys())`), and the suite docstring still says "39 corporate_record rows … record-type subclasses" instead of "450 rows in 10 subclasses with per-subclass entity schemas" (branch `suites.py:398-403`).
- The vendored llm-mailroom frozen prompt lock has not taken v7 either: `vendor/llm-mailroom/src/llm/frozen_v1/lineage.json:19-20` still pins corporate sha `fe13501f…` (v6 bytes, 5,865 chars). This matches the propagation todo in `docs/CORPORATE_RECORD_SCHEMA.md:65` ("the same change must land in llm-mailroom and eval-environment … before the next `sync_production_prompts.py --check`").

**Mailroom-Corpus-EDA**

- No per-subclass entity schema exists here at all (never claimed to). Its vocabulary surfaces are `EXPECTED_SUBCLASS_BY_CLASS["corporate_record"]` — 10 subclasses, no `certificate_of_formation` (`src/mailroom_eda/v9_build.py:90-94`) — plus the subclass→intent and subclass→phrase maps at :150-177 (see KQ4). The class carries **no extraction field map** beyond the purpose trio (`CLASS_GT_KEYS["corporate_record"]`, :106-120) and `eval_contract.py` `GT_HINTS`-style purpose keys (`:390-400`, `corporate_record: ()` extra keys).

**Drift register for KQ1** (repo / file:line / differs / authoritative)

1. `eval-environment @STAGING / prompts/manifest.json (versions)` + `prompts/mutations.json` — v6/v7 absent (STAGING mutations carry corporate only v1…v5); executive-brief v1 is the frozen default — **feature branch `feat/corporate-records-v7` is authoritative** (dojo catalog synced from its tip `b449a79`).
2. `local-mailroom-sandbox / config/mailroom.taxonomy.base.yaml:196-201` — retired `key_provisions`, missing semantic trio — **sandbox eval lists + vendor taxonomy + dojo live map are authoritative**; base yaml is the stale side.
3. `local-mailroom-sandbox / vendor/llm-dojo-scoring/src/llm_dojo_scoring/` (v0.22.0 snapshot) — no subclass schema, no unlabeled alignment, v8-era suite docstring — **the dojo feature branch is authoritative**; vendor is stale by one release cycle by design.
4. `local-mailroom-sandbox / vendor/llm-mailroom/src/llm/frozen_v1/lineage.json:19-20` — corporate prompt still v6 bytes — **v7 (b40963bb) authoritative**.
5. `llm-dojo-scoring / llm_dojo_scoring/prompts/catalog.yaml:548` — the v7 row's `notes` string says "sandbox stem corporate_records_specialist_simplified" (that is v6's stem; v7's is `corporate_records_specialist_subclass_v2` per lineage JSON) — stale prose note only; the sha/`source_key` fields are correct. **lineage JSON is authoritative.**
6. Classification-boundary drift inside the corporate doctrine (dojo record types vs sorter): `eval-environment @feat / prompts/sorter_v4.md` maps "Certificate of Designation (preferred-stock series)" → `officer_certificate`, while the dojo `rights_instrument` entity `instrument_kind` description includes "preferred stock / designations" (`corporate_record_schema.py:230-233`) and the sandbox prompt line 33 lists "preferred certificates, specimen stock" under `rights_instrument`. **Sorter_v4 is authoritative for `doc_subclass`** (it decides the record shape; the specialist then maps subclass→token). The rights instrument's description should not be read as a competing classification rule for Certificate-of-Designation documents, but this seam is undocumented.
7. `llm-dojo-scoring / llm_dojo_scoring/suites.py:218-226` (`LEGACY_FULL_EXTRACTION_FIELD_TYPES` corporate = entity keys + `key_provisions`, no semantic trio) — legacy-only map for historical rescoring, correctly excluded from live scoring (`suites.py:186-187` doc); not a live drift.

### Inferences

- The per-subclass map is single-sourced in the dojo and all *current* per-line copies (v7/sandbox stem/dojo template) are generated or pinned from it — the "schema regime" is one data structure plus two byte-locks. Any per-subtype regime extension (new subclass or new entity) is a code change in exactly one file plus prompt re-freezing, not a search.
- The alignment is prompt-freeze-gated: the dojo test `tests/test_corporate_record_schema.py:171-179` asserts `render_prompt_section() in get_prompt(...).text` for both `production` and `production_prompts` families and that the text never exceeds 5,865 chars — so prompt and scorer cannot drift silently *within the dojo*, but every out-of-repo copy still does until re-frozen.

### Gaps

- I did not trace which code path actually reads `local-mailroom-sandbox/config/mailroom.taxonomy.base.yaml` `field_types` at runtime (overlay/components loading not walked end-to-end); the drift classification (stale vs load-bearing) is unconfirmed there.
- The exact working-tree state of `prompts/corporate_records_specialist_v7.md` on the `feat` branch was read via `git show` (not a checkout), fine, but STAGING's future merge plan (whether v7 lands before the feat branch refreeze) is outside these repos.

---

## How each specialist prompt describes per-subclass entities / JSON schema / inapplicable core keys / unlabeled fields — vs the dojo module and the dataset's `gt_presence` semantics

### Takeaway

v7/subclass_v2 and the dojo module state and JSON Schema are consistent with each other line-for-line including the "null = emit null/[]" rule for inapplicable core keys. `gt_presence` semantics agree on the four published codes (populated / not_applicable / schema_documented_absence / pending_annotation), and the dojo adds a fifth *unstated-blank ⇒ unlabeled* regime that exists only in the scorer (drop from both sides), never in the dataset — the published v9/v9.1 build actually **cannot express** per-field corporate entity presence because its `gt_presence` key set is a fixed union of purpose keys that excludes every entity field.

### Cited Findings

**Prompt description (subclass_v2 = v7; all line refs are to `local-mailroom-sandbox / config/prompts/corporate_records_specialist_subclass_v2.txt`)**

- Per-subclass key entities: one compact line each (`:6-14`): "+extra keys ([] = list)" — e.g. indenture `+trustee, guarantors[], securities_series, principal_amount, maturity_date`; and "null = emit null/[]" for inapplicable core (`:5`, e.g. bylaws `null filing_number`; subsidiary_list `null signatories, jurisdiction, filing_number`). Matches `SUBCLASS_SCHEMAS` core_applicable/entities exactly (diff-verified).
- Scope discipline: "Fill only CorporateRecordExtraction keys and your subclass's +keys … never another subclass's" (`:17`) — matches dojo `align_unlabeled`'s cross-subclass stray-key semantics (`corporate_record_schema.py:427-432`).
- Entity-name rule: "entity_name is always the owning company (registrant/issuer/parent), never a counterparty or signer" (`:5`) — matches `docs/CORPORATE_RECORD_SCHEMA.md:46`.
- Inapplicable-core handling: "Unstated scalar … → null. Unstated list (signatories, keywords) → []. filing_number is null when the record has no official file/document number" (`:20-22`); the dojo's per-subclass JSON Schema makes inapplicable core keys stay `required` but only vacuous (`corporate_record_schema.py:474-483`), and the format layer counts a key as present even when null (`scorecard_honesty.py:448-455`, presence-only). No conflict.

**`gt_presence` semantics, both sides of the fence**

- Dojo dictionary of the four codes: `llm-dojo-scoring / llm_dojo_scoring/gt_metadata.py:12-25` — `populated`, `not_applicable` ("class never carries this field"), `schema_documented_absence` ("legitimately has none"), `pending_annotation` ("label backfill has not run yet; stale values must never score"); all absences treated as empty for scoring (:64-66 `ABSENT_PRESENCE_STATUSES`, applied as `""` in `scoring_gt_fields` :230-231).
- Corporate-specific refinement: `corporate_record_schema.py:334-338` — only `schema_documented_absence`/`not_applicable` make a blank "expected empty"; `pending_annotation` and any unstated blank are **unlabeled** (`unlabeled_fields`, :382-406) — dropped from both sides by `align_unlabeled` (:409-440) so "a correct extraction [is] not scored as a spurious fill." Difference from the generic class treatment is intentional for corporate (where the whole published GT is blank+undocumented).
- Dataset-side vocabulary: `Mailroom-Corpus-EDA / src/mailroom_eda/gt_presence.py:44-50` — the same four published codes, plus the rule that `genuine_gap` "must never ship" (:32-38, :196). The codes match the dojo's reader.
- **Key-set drift (structural):** `gt_presence.py:56-77` — `FIELD_KEYS_BY_CLASS["corporate_record"] = ("intent","subject_matter","keywords")`; `ALL_GT_FIELDS` is the union over classes; `row_gt_presence` writes exactly that key set; `v9_1_revision.py:264` `verify_presence_codes` **asserts `set(presence) == set(ALL_GT_FIELDS)`** on every published row. Therefore a published corporate row's `gt_presence` cannot carry `entity_name`/`record_type`/subclass entities at all — which is exactly why the published v9.2 has zero key-entity labels (`docs/CORPORATE_RECORD_SCHEMA.md:18`: published GT labels none of the six entity keys on any of the 450 rows; only intent/subject_matter/keywords populated, as template boilerplate on 411/412 rows).
- Dojo relabel, by contrast, **extends** `gt_presence` with subclass entity entries — "gt_presence — extended with the subclass's entity fields: populated / not_applicable; every other entity field is left unlabeled (absent from the map)" (`corporate_record_relabel.py:16-18`; written at :140-148: inapplicable entity-core fields get `not_applicable`, everything else stays absent). If such rows were pushed back through the EDA revision pipeline, `verify_presence_codes` (`v9_1_revision.py:264-266`) would fail them outright — the two regimes disagree on the gt_presence key convention.

**Drift register for KQ2**

1. Dojo expectation (`corporate_record_schema.py:394` + `corporate_record_relabel.py:140-148`): corporate `gt_presence` may include subclass-specific entity keys with tied statuses — vs dataset builder law `Mailroom-Corpus-EDA / src/mailroom_eda/gt_presence.py:76-77,:199-203` + assertion at `src/mailroom_eda/v9_1_revision.py:264` — **the dataset's uniform key-set is authoritative for v9.x published rows; the dojo regime only becomes operative once the dataset (post-v9.3?) adopts the extended key set.** The dojo itself is the SSOT of the *desired* regime per `docs/CORPORATE_RECORD_SCHEMA.md:58` ("set gt_presence to populated or schema_documented_absence for every entity field of the subclass").
2. Historical (v1/v6) intent conflicts noted in KQ1 finding 5 above are a prompt-vs-schema drift; **v7 + dojo module are authoritative**; `intent_review` documented in the module is kept for score comparability, not because it is final.
3. Sorter-to-specialist subclass semantics: `sorter_v4` (feat branch) explicitly forbids `certificate_of_formation` ("formation filings also use [articles_of_incorporation], not certificate_of_formation") — consistent with the dojo fold; **no drift** on this axis.

### Inferences

- Under the published data today, `gt_presence` presence statuses never "gate" corporate entities since the keys aren't there; the dojo's `_labeled` fallback (`corporate_record_schema.py:350-356`: no status ⇒ label iff value non-empty) means a dataset that *fills a value but writes no status* is still treated as labeled — that is exactly the `backfill_purpose_gt` shape (see KQ4), so the two regimes interlock by fallback rather than by contract.
- The suite docstring "The published merge covers 450 corporate_record rows in 10 record-shape subclasses" (branch `suites.py:398-403`) vs v9_build's 411 corporate draw rows + 39 v8-routed rows = 450; both counts are internally consistent (39 legacy S-1 rows at `docs/CORPORATE_RECORD_SCHEMA.md:20`).

### Gaps

- The corporate draw JSONL sidecars (`data/v9/draws/*.jsonl`) are not committed in the EDA checkout (`data/` is empty there) — the *actual producer* of the published template `subject_matter ("<subclass> of <Company> (TICKER) (CIK …) (SEC EDGAR exhibit).")` that the dojo relabel parses is not in any audited working tree. The current branch's `backfill_purpose_gt` writes **grounded** phrases (no CIK/EDGAR suffix), so the on-disk code no longer reproduces the published 411-row template — either the template was produced by an older EDA revision not in the branch history I read, or by an external draw-preparation step.

---

## Scoring treatment: labeled extension entities, `pending_annotation`, unlabeled fields, format-check required keys; remaining expected/predicted asymmetries

### Takeaway

On the feature branch, corporate scoring is now asymmetric-removed correctly: unlabeled (blank+undocumented, pending, or not-applicable-without-value) fields are deleted from **both** sides, predicted keys from any subclass the dataset does not label are never spurious-fill FPs, and the format gate requires only the registered core. The score-feed extension `scored_field_types()` exists but isn't what scoring actually uses (the suite unions *all* subclass entities into the live map instead). Three real asymmetries remain: (1) the archive-side scorer (`archive.py`) has no corporate alignment at all, (2) entity keys are keyed by name only, so a populated cross-subclass entity value is scored (and only flagged by audit), and (3) the micro-FP side still charges unmatched list items and per-field spurious fills in ways the labels (once they exist) must be constructed to expect.

### Cited Findings

- Soft scoring path: `llm-dojo-scoring / llm_dojo_scoring/field_scoring.py:1330-1375` — iterates **expected** fields only; empty expected skipped (correctly-empty credit handled by the micro layer); per-field typed scorer by `field_types`; `intent` canonicalized via `normalize_intent` (:1345-1348); retired/annotation keys never scored (:54-68 `NEVER_SCORED_FIELDS`, `RETIRED_PROMPT_KEYS`).
- Asymmetry the branch fixes — micro layer: `extraction_metrics.py:119-147` — empty GT + filled prediction ⇒ `n_spurious_fill` ⇒ **FP** (with `penalize_spurious_empty=True` default); predicted extra keys **not in expected** ⇒ FP (:141-147). On the published blank-GT the branch inserts `align_unlabeled` before both (`suites.py:920-945`, per-row on batch `:931-941`, single-doc `:941-945`), dropping unlabeled fields from expected and predicted and carrying `unlabeled_fields` into the payload (`suites.py:1279-1283, 1315-1318` test-visible).
- Labeled extension entities: `corporate_record_schema.py:359-374` (`scored_field_types(sub, gt)` adds an entity to the map only if `populated`/`schema_documented_absence` or a non-empty value; `pending_annotation` / `not_applicable` never). `:350-356` `_labeled`. Test `tests/test_corporate_record_schema.py:190-204` exercises labeled scored both ways (hit=1.0, wrong<0.5, missing ⇒ recall<1.0); `:207-213` asserts `pending_annotation` behaves as unlabeled.
- **Actually wired scoring type map:** `suites.py:758-768` — for `corporate_record` the suite unions *all* `all_entity_field_types()` over `DEFAULT_FIELD_TYPES` core into `ftypes` (so any labeled entity anywhere in GT can score by name), while `required_ftypes` stays the passed/default map and the format layer gets `required_keys=list(required_ftypes)` (`suites.py:963-968`; v0.22.0 had `required_keys=list(ftypes.keys())` — the scoring map and the required-key set were the same thing — see vendor diff) — "entities are scored when labeled but never required." `scored_field_types()` is exported (`__init__.py:260-262`) and used only by tests/scripts, not the suite path.
- Format layer semantics: `scorecard_honesty.py:416-455` — `schema_valid` = share of required keys **present on the parsed prediction** (a `null` value counts as present; parse failure ⇒ 0). Test `tests/test_corporate_record_schema.py:216+` asserts the JSON Schema accepts prompt-compliant nulls for inapplicable core. So for corporate the format check is schema presence of the 9 core keys only — decision documented at `suites.py:758-760`.
- `pending_annotation` globally: `gt_metadata.py:64-66, 230-231` — any field whose status is in `ABSENT_PRESENCE_STATUSES` (incl. pending) is scoped to `""` so it is never an expected event; per-class evidence: 91 EX-10 contract rows with `cuad_clause_labels: pending_annotation` are unscorable until backfill (`docs/EXTRACTION_SCHEMAS.md:43-44`; `gt_metadata.py:20`, `:289-301` for CUAD presence).
- Unlabeled semantics on the **predicted** side: `corporate_record_schema.py:422-440` — stray keys = every subclass's entity keys not labeled by the row's presence map; deleted from predicted so "emitting subclass entities never counts as spurious fill."

**Drift register for KQ3**

1. `llm-dojo-scoring / llm_dojo_scoring/archive.py:359-396` (`score_archive_block`) — takes no `doc_subclass`, no `align_unlabeled`; `_filter_to_live_map` keeps only `ftypes`; `schema_valid` over `list(ftypes.keys())` (:394-403). An archive-path corporate scoring therefore still treats blank entity-core fields as expected-empty (spurious-fill FPs) and requires **whatever ftypes the caller passes** (caller decides). **suites.py's corporate path is authoritative for extraction scoring; archive.py is the audit-log formatter and must gain the same alignment or route through the suite.**
2. `corporate_record_schema.py:341-347, 359-374` vs `suites.py:761-768` — two different extension maps are used (per-subclass w/ GT gate vs all-subclasses union). They can disagree only when GT labels a foreign-subclass entity key: under the union map the row is scored like it belongs to that key's own scorer and expected-side keeps it; audit then flags `entity_wrong_subclass:<key>` (`corporate_record_schema.py:594-598`). **The union choice is current behavior; `scored_field_types()` is the stricter proposed regime.** This is the known open asymmetry between expected and predicted side: expected keeps labeled-by-anyone entity keys, align drops predicted strays only when *unlabeled*.
3. `field_scoring.py:1377-1394` — factuality audit (`entity_list_audit`) runs for every populated predicted field in `ftypes` **including fields the GT does not label** (comment says so explicitly); that audit is additive/diagnostic, not FP-producing — but on corporate it means every predicted subclass entity gets verified against doc text even while excluded from P/R — a low-risk asymmetry, deliberate per comment.
4. `extraction_metrics.py:137-139` — for scored `entity_list` fields, `unmatched_predicted` items also add FP on labeled expected lists (correct under labeled GT; inert on today's unlabeled corporate rows except `keywords` — which IS labeled everywhere, and the relabel/EDA both strip provenance IDs so list spuriousness is a live metric).
5. Historical/installed surface: v0.22.0 vendor (same diff as KQ1 drift 3) — format layer required keys = scoring map (v0.22.0 `suites.py` joined with DEFAULT core so effectively 9 keys; but no `unlabeled_fields` payload and no per-subclass precision fix). Everything above is the branch's fix; the sandbox still scores on v0.22.0 semantics.

### Inferences

- The one remaining *designed* gap — expected-side keys keyed by name across subclasses — mirrors the dataset reality that `gt_fields` is one flat union dict (`gt_metadata.py:5-10`), so subclass scoping of expected labels can only come from annotation discipline (the relabel's `not_applicable` marks), not from code.
- Once the dataset labels entities, the branch numbers line up: TP≥1.0 exact, FN<1.0, spurious fills become FP again (`extraction_metrics.py:119-139`), which is the per-subtype regime the docs ask for (`CORPORATE_RECORD_SCHEMA.md:24`).

### Gaps

- The sandbox-side `score_extraction_row` never passes `expected_subclass`/`doc_subclass` into `suite.score` (`local-mailroom-sandbox / src/mailroom_sandbox/eval/scoring.py:106-146` calls `suite.score(expected, predicted, doc_text=doc_text)`; `runners.py:520-526` likewise) — so even after the vendor bump, the alignment would run with `subclass=None` ⇒ normalized to the `other` schema. Whether `runners`/`metrics` have another doc_subclass path was not traced fully (no other call sites found). Wiring this kwarg is required for the sandbox to get the branch semantics.
- Did not fully read `scorecard_honesty.assess_extraction_gt` interplay with corporate blank rows beyond the suites comments; treat status/reason framing as verified only in test snippets.

---

## How Mailroom-Corpus-EDA produces corporate labels (v9_build backfill) and whether its output satisfies the dojo relabel's assumptions

### Takeaway

The EDA backfill (`backfill_purpose_gt`) is a non-overwriting, zero-LLM fill of the *purpose trio* plus `entity_name` from EDGAR filer metadata: subclass→intent template, grounded `subject_matter` phrase, cleaned keywords, entity name — matching the dojo relabel's assumptions on every field it writes (same intent pins, same phrase map, compatible name cleaning), but it does not touch `record_type`, does not set `gt_presence` for anything it writes, and its write-only-when-empty contract plus the uniform `gt_presence` key-set law keep the six entity-core fields unlabeled in the published data — which is exactly the regime the dojo branch then handles honestly. The published 411-row template subject_matter that the dojo relabel repairs is *not* produced by the current branch code, so the two pipelines cannot currently reproduce each other byte-for-byte.

### Cited Findings

- `Mailroom-Corpus-EDA / src/mailroom_eda/v9_build.py:207-266` — `backfill_purpose_gt(rows)`: corporate intent 0% on the 39 v8 rows; fills `intent = CORP_SUBCLASS_INTENT[subclass]` with `intent_source="heuristic"`, `intent_confidence="0.9"`, `intent_status="auto_labeled"` for empty intent; `subject_matter = "{phrase} of {company}."` (or `"{phrase} of the registrant."` with no company); `keywords = json [phrase, company]` provenance-free; `entity_name = _clean_filer(metadata.filer)`. Only EMPTY fields are written (:216-218 docstring, tests `tests/test_corporate_backfill.py:41-45`).
- `v9_build.py:152-163` — `CORP_SUBCLASS_INTENT` is field-for-field identical to the dojo's pinned intents (`corporate_record_schema.py:137-295`) including `other→other` and subsidiary/indenture tokens. `v9_build.py:167-177` `CORP_SUBCLASS_PHRASE` is identical to dojo `corporate_record_relabel.py:50-62` `_PHRASE` (incl. the "Corporate record" fallback for residual subclasses; EDA's dict omits `other` and `certificate_of_formation` — it has no such rows and falls back to "Corporate record" generically at the call site :236).
- Filer cleaning `v9_build.py:187-204` (`_clean_filer`) — drops `(CIK n)` anywhere, trailing tickers, `/ST/` tails; keeps country/entity-form tokens like `(UK)` (`_NOT_TICKERS` list at :180-182 is **identical** to the dojo's `corporate_record_relabel.py:46-48`). Tests pin "Pfizer (UK)", "Berkshire Hathaway Inc (BRK-A, BRK-B) (CIK 1)", "SOURCE ENERGY CORP /UT/" (`tests/test_corporate_backfill.py:47-53`). The dojo's `company_from_template` (`corporate_record_relabel.py:65-79`) cleans the same set of artifacts, but reads them off the *template subject_matter* rather than `metadata.filer`. Difference: input surface, not algorithm.
- **Entity-name difference in behavior:** relabel writes `presence["entity_name"]="populated"` and rewrites subject_matter (`corporate_record_relabel.py:104-108`); EDA writes only `gt_fields["entity_name"]` with no presence entry (`v9_build.py:247-248`) — under the dojo `_labeled` fallback a non-empty value is still treated labeled, but there is no explicit "populated" marker (drift vs relabel's output convention; relabel would add it on rescore).
- **`record_type` — never written by EDA** (no occurrence in v9_build.py); the dojo relabel fills it from the subclass map when blank/invalid or after subclass reassignment (`corporate_record_relabel.py:126-134`). So EDA-produced rows would arrive at the relabel/audit with `record_type` blank and unpinned — consistent, but nothing pre-labels it.
- **`intent_status` divergence:** EDA sets `intent_status="auto_labeled"` (`v9_build.py:233`); the dojo audit only reads `intent_source` (`heuristic`) for `intent_heuristic` (`corporate_record_schema.py:590-591`), and its relabel keeps an adjudicated intent untouched when `intent_source` is neither blank nor heuristic (`corporate_record_relabel.py:136-139`). "auto_labeled" in the status is not read by the dojo — no conflict, just vocabulary duplication (also mirrored in `eval_contract.INTENT_SOURCE_METHOD`, `Mailroom-Corpus-EDA / src/mailroom_eda/eval_contract.py:93-108`).
- Draw/conformance laws EDA enforces that shape what reaches the dojo: expected/subclass vocab validation (`v9_build.py:537-560`, incl. `"gt_fields"` required to be a dict and metadata keys must not look like labels); 27-key conformance (`conform_rows`, :628-663 — for corporate, intent/subject_matter/keywords must be non-empty on every row); v9.1 `gt_presence` write (see KQ2), and v9.1 `verify_zero_drift` (`v9_1_revision.py:252-282`) forbids any non-targeted byte change, i.e. GT entity backfills must go through a new deliberate revision, they cannot ride along.
- The dojo's own repaired-label report states the published-data facts this all hangs off: `docs/CORPORATE_RECORD_SCHEMA.md:52` — on v9.2, relabel populates `entity_name` (411 rows from template) and `record_type` (450), replaces 411 template subject_matters, strips provenance IDs from 422 keywords, re-assigns 12 conflicting `expected_subclass`, marks inapplicable `not_applicable`; everything else stays unlabeled; 2 conflicts ambiguous; `intent` remains `heuristic`. Known limits at `:67-72` (entity_name from filer metadata, ~25% differ from in-document name; DOC-85c7b49… deliberately not auto-reassigned).

**Drift register for KQ4**

1. `Mailroom-Corpus-EDA / src/mailroom_eda/v9_build.py:239-243` (grounded `{phrase} of {company}.`) vs published template (`"<subclass> of <Company> (TICKER) (CIK …) (SEC EDGAR exhibit)."` per dojo docs) — **the EDA branch's new grounded form matches the dojo relabel's *output* spec** (dojo relabel writes the same grounded phrase, relabel.py:107), so the branch side is the authoritative direction; the published v9.2 data still needs the relabel pass or a v9.3 re-build.
2. `v9_build.py:247-248` writes entity_name without `gt_presence populated` vs `corporate_record_relabel.py:106` — file the dojo side as authoritative for a fully labeled dataset (per docs instruction, `CORPORATE_RECORD_SCHEMA.md:58`), EDA side acceptable under the fallback.
3. `v9_build.py:90-94` 10-subclass surface vs `corpus.py:87-99` 11-key scoring catalog — `certificate_of_formation` exists only in the dojo as an alias; **dojo authoritative (kept as LLC-formation alias), EDA/document surfaces 10 keys**, consistent with sorter_v4's "not certificate_of_formation" doctrine.
4. Expected-subclass conflict handling differs: EDA conformance does not cross-check prose subject_matter vs `expected_subclass` (no `subclass_content_conflict` equivalent anywhere in v9_build/v9_1/v9_2); the dojo audit/relabel owns that check (`corporate_record_schema.py:556-563, 592-593`; relabel :92-98). **Dojo authoritative for conflict repair** (12 auto-reassignments on v9.2, `CORPORATE_RECORD_SCHEMA.md:52`).

### Inferences

- If the EDA branch's grounded-backfill shape is published, the dojo's `company_from_template` regex and the template-rewrite branch of relabel become mostly no-ops for *new* rows (nothing synthetic to repair); the relabel retains its role for the published 411 template rows and for conflict reassignment.
- The relabel doc's claim "intent_source kept honest (heuristic/auto_labeled stays)" matches EDA's emission (`heuristic` source + `auto_labeled` status) — the two repos agree that none of this is human-adjudicated.

### Gaps

- The producer of the published template subject_matter (`(TICKER) (CIK …) (SEC EDGAR exhibit)` string) is not in the audited EDA branch code (see KQ2 gap); I could not verify whether a v9.3 plan already swaps in the grounded phrases en masse.
- Whether `metadata.filer` exists on all 411 published corporate rows (EDA `_row` fixture shows it does on draws) was not verified against Hub data from this machine.

---

## What is pinned in the sandbox lineage JSON (the _v6/_v7 key pinning) and how a schema bump propagates

### Takeaway

The sandbox `eval_environment_lineage.json` is a sha256 lock over prompt *bytes*, not over schema semantics: the default corporate row is re-frozen **v6** (`sha fe13501f…`, 5,865 chars — old executive brief), while v7 (`sha b40963bb…`, 5,333 chars, stem `corporate_records_specialist_subclass_v2`) sits as a `frozen_successors` entry (:92-104, frozen 2026-10-17, parent v6, origin "dojo corporate_record_schema"). Default runs get v6; v7 is opt-in, and a test pins exactly that asymmetry. A v8 bump would ripple through the pinned surfaces below in a fixed order and leave a stale default until an explicit re-freeze of the `specialists` row.

### Cited Findings

- `local-mailroom-sandbox / config/prompts/eval_environment_lineage.json:16-32` — `specialists.corporate_records_specialist`: `eval_environment_key: corporate_records_specialist_v6`, `sandbox_stem: corporate_records_specialist_simplified`, sha fe13501f…, refrozen 2026-10-16 with a `superseded` block retaining the original v1 identity (`484e64dd…`, 5,801 chars, frozen 2026-09-26).
- `:92-104` — `frozen_successors` appends corporate v7 → sandbox_stem `corporate_records_specialist_subclass_v2`, sha b40963bb…, 5,333 chars, `frozen_at 2026-10-17`, `source_path prompts/mutations.json`, note "one compact line per doc_subclass …; entity_name = owning company; 532 chars shorter than v6."
- `src/mailroom_sandbox/eval_environment_lineage.py:8-18` — documented law: successors are byte-pinned the same way, do not move the default, a run opts in by pinning the successor stem (:95-101 `default_prompt_variant` reads only the `specialists` row).
- `tests/test_eval_environment_lineage.py:112-150` — SAND42_SUCCESSORS requires the successor triplet `(agent, key, parent)`; asserts `default_prompt_variant(agent) != stem` ("Freezing a successor does not move the default v1 pin") and that the default pin is exactly the `specialists` row key (:146-150); a sibling-checkout consistency check exists (:97-100) via `verify_sibling_catalog` → drift refusal tests for stem bytes (:151+).
- Selection mechanics: `src/mailroom_sandbox/prompt_versions.py:1-13, 38-45` — `prompt_version` = the eval-environment key, sha256-stamped, `prompt_version`/`prompt_sha256` are serving-group identity so v6 and v7 runs **never pool**; no selection ⇒ existing `*_simplified` stem default. Lineage API is delegated to the dojo's `llm_dojo_scoring.prompts` (:44-60).
- Dojo mirror of the same lineage: `llm-dojo-scoring / llm_dojo_scoring/prompts/eval_environment_lineage.json` — synced at `2026-10-17T08:00:00Z`, `source_commit b449a79…` (the feat-branch tip), full `text` bodies inlined. So the dojo's prompt catalog legally cites v7 exactly when the feat branch tip is the authority; STAGING is behind it.
- Re-freeze precedent for the *default* row: the `_v6`→default move is described in the JSON notes (:7, "Re-freeze (dojo #29/#30): the corporate_records and correspondence stems carry the corrected text … each row's `superseded` block keeps the original v1 key") — i.e. moving vN into the `specialists` row is a deliberate freeze event, not an automatic consequence of freezing a successor.
- Scoring-code version channel: `local-mailroom-sandbox / vendor/llm-dojo-scoring/VENDOR.md` — sandbox ships a snapshot of the dojo (tag v0.22.0) re-vendored from the monorepo workspace; llm-mailroom pins `llm-dojo-scoring @ git+…@v0.22.0` for release installs (`/Users/morningstar/Desktop/Cold_Storage/llm-mailroom/pyproject.toml:42`, workspace-resolved in dev `:115`); eval-env resolves the dojo only transitively through mailroom's pin (`/Users/morningstar/Desktop/Cold_Storage/eval-environment/pyproject.toml:15-21, 42-43`).

**How a v8/new-dataset-format bump would ripple (order matters):**

1. Prompt mutation: new `corporate_records_specialist_v8` (parent v7) in `eval-environment / prompts/mutations.json` (+ `.md` mirror) — the eval-env key string itself is the currency (`prompts/mutations.json` on feat branch currently holds v7 with `net_chars`/`sha256`).
2. Sandbox stem: new `config/prompts/corporate_records_specialist_subclass_v3.txt` (or equivalent) + `eval_environment_lineage.json` `frozen_successors` row (sha256/chars/parent) — byte drift is refused (`tests/test_eval_environment_lineage.py:151+`), and `SAND42_SUCCESSORS` map (`:112-121`) must gain the row or the succesor-set equality test fails.
3. Prompt catalog regeneration on the sandbox (the commit `649f71c` did exactly this for v7: "regenerate prompt catalog, pin v7 gap, exact default-pin assertion, docs") and a `prompt_version` pin selection to run it.
4. Dojo: `llm_dojo_scoring/prompts/templates/<agent>.production_prompts.md` + `catalog.yaml` row + `llm_dojo_scoring/prompts/eval_environment_lineage.json` resync; `scripts/sync_production_prompts.py --check` gates only the `production` family (mailroom bytes), `production_prompts` is the eval-env mirror family.
5. Semantics: if the bump changes core field keys or presence semantics, `DEFAULT_FIELD_TYPES`/`corporate_record_schema` (`docs/CORPORATE_RECORD_SCHEMA.md:61`: "Re-pin the taxonomy fixture only when core fields change; extension entities do not touch DEFAULT_FIELD_TYPES"), then `configure_from_taxonomy()` consumers (`eval-environment / src/evals/dojo_wiring.py:37-84`) re-wire at process start.
6. Installer pins: sandbox vendor snapshot re-vendor (VENDOR.md), llm-mailroom `pyproject.toml:42` git-tag bump, eval-env transitive pick-up. **Until steps 5–6 happen, the sandbox and eval-env runtime keep v0.22.0 semantics regardless of any prompt bump.**
7. Default row move (v6→v8 as the `specialists` row, v1-style re-freeze event) is a *separate* decision — otherwise default runs stay on the frozen executor-brief line forever.
8. Dataset format bumps (gt_presence key extension — see KQ2/KQ4) additionally touch the EDA pipeline: `gt_presence.FIELD_KEYS_BY_CLASS` + `ALL_GT_FIELDS` + `v9_1_revision.verify_presence_codes`, and the dojo `gt_metadata.ANNOTATION_KEYS` never blocks a new gt key as long as scoring maps are updated.

### Inferences

- The pin design is deliberately "byte-frozen, opt-in successor": a schema bump cannot silently change running evaluations — results remain group-identified by `prompt_version`/`prompt_sha256`. The cost is that the default line lags the schema regime until an explicit re-freeze (currently at v6 vs the v7-class schema).
- The freeze chain has one path per repo but two prompt families (dojo `production` = mailroom bytes; `production_prompts` = eval-env bytes). v7 froze the latter only (`catalog.yaml:536-549`), consistent with the doc's note that the production family lags (`CORPORATE_RECORD_SCHEMA.md:65`).

### Gaps

- sandbox `tests/test_prompt_versions.py` / `test_prompt_versions_dojo.py` details not walked (dojo-side API contract for `prompt_roles`/`prompt_chain` unverified).
- Whether the `sorter` prompts participate in the lineage JSON: they do not (the JSON covers only the five specialists; `VENDOR_MIRROR_STEMS` at `eval_environment_lineage.py:39-45` adds only production-mirrored specialist stems) — so a v8 that changes the sorter subclass catalog (e.g. adds `certificate_of_formation`) rides on `sorter_v4` in eval-env and is not sha-locked by the sandbox lineage today.

---

## Record-type dispatch: per-record-type schema handling vs blanket application, and where dispatch happens

### Takeaway

Dispatch to a specialist is strictly doc_class → agent (1:1) everywhere; doc_subclass never selects a different prompt or field map except inside `corporate_record`, where the single corporate specialist prompt carries the per-subclass entity lines generated from the one dojo data module. Contracts, insurance, merger and correspondence remain blanket one-schema-per-class (subclass dims act only on *classification* scoring, MAUD/CUAD extras, and insurance claim_type content folding). The subclass doctrine is theirs alone: the sorter emits it (v4), the corporate specialist consumes it, the judge/arbiter/judge-classification prompts ignore it beyond "judge only the registered schema".

### Cited Findings

- Doc_class→specialist 1:1 maps (authoritative table): `llm-dojo-scoring / llm_dojo_scoring/suites.py:56-69` (`SPECIALIST_DOC_TYPES`: contracts→contract, corporate_records_specialist→corporate_record, etc.); `eval-environment / src/evals/tasks/corporate_records.py:8-13` — `specialist_task(name="corporate_records", doc_class="corporate_record", agent_role="corporate_records_specialist", default_subset="class:corporate_record")` (same pattern for other five files); `local-mailroom-sandbox / config/mailroom.taxonomy.base.yaml:187-190` — `key: corporate_record / specialist: corporate_records_specialist`; identical in `vendor/llm-mailroom/src/config/taxonomy.yaml:381-385`.
- Subclass emission is sorter-owned: `eval-environment @feat / prompts/sorter_v4.md` — "CORPORATE RECORD SUBCLASS (only when doc_type is corporate_record): set doc_subclass to EXACTLY ONE key from the corporate_record catalog supplied with the document" with per-key definitions incl. "formation filings … also use this key [articles_of_incorporation], not certificate_of_formation", board_resolution covering board-adopted bylaw amendments, Certificate of Designation → officer_certificate, TITLE WINS doctrine. STAGING's `sorter_v1.md` leaves subclass generic as well: "When the chosen class has a subclass catalog, emit doc_subclass as one key from that class's catalog" (`prompts/sorter_v1.md:71` production doctrine).
- Sandbox local sorter has no subclass doctrine: `config/prompts/sorter_local_v0.txt` emits `doc_subclass: second-level subclass or null` with no corporate catalog (`sorter_reviewer_local_v0.txt` likewise); in sandbox evals the GT subclass is injected into the pipeline state (`src/mailroom_sandbox/eval/agents.py:230, 248`), so the subclass acts as prompt context, never as routing dispatch.
- Contract subclass dimension: classification-only — `contract_subtype` from the CUAD 25 families with equivalence classes (`llm-dojo-scoring / llm_dojo_scoring/config.py:104-113` SUBTYPE_EQUIVALENCES rubric; `config.py:115-118` DOC_SUBCLASS_EQUIVALENCES merger only) and per-family grid slicing `PER_SUBTYPE` (`config.py:63-70`); the extraction field map itself is one 11-key `ContractExtraction` live map (`suites.py:82-94`), fields identical for every family (no family-conditional fields anywhere in `field_scoring.get_field_types`, `field_scoring.py:1224-1247`).
- Insurance: content-folding only — `canonical_claim_type` folds CMS table tokens onto `health` when GT is `health` (`field_scoring.py:76-92`); subclass informs claim_type token + column priority only through prompt prose (the frozen v1 insurer's per-layout brief, STAGING `src/evals/prompts/frozen_v1.py`). Merger: consideration tokens are GT (`expected_subclass` enum in `corpus.py:190-195`); the fork to per-field MAUD answering is prompt-side — the merger v4 fixture "per-chunk answering duty" is built from `llm_dojo_scoring.maud_schema` (sandbox lineage JSON `:88-91`), still a single doc_class map.

- Correspondence: fully blanket — 10-key live map `suites.py:227-237`, subclass enum is 8 published tokens (`corpus.py:203-212`), no per-subclass fields; the DMR-071 adjudication records the v8-era `voicemail` labeler key was removed to match the v9 GT pin (`corpus.py:190-212` comment).
- Judge/arbiter remain registry-scoped and subclass-blind: "Judge only fields registered in the supplied extraction schema" (`eval-environment STAGING / prompts/judge_v1.md` rules :1-3; arbiter fields_to_fix "registered schema field names"), with shared field names across classes explicitly not conflicts (`boss_v1`: "Shared field names … are not a conflict").
- Cross-class shared keys handled by the scorer's union-safety: `gt_metadata.py:70-91` — `expected_subclass` (and all annotation stats) are `ANNOTATION_KEYS`, "scored by the classifier, never as a field"; each row's `gt_fields` is one union dict but `scoring_gt_fields` scopes to the doc_class map (:199-234).

### Inferences

- If a per-subtype regime is extended beyond corporate (the stated goal), the natural pattern to copy is corporate's: data-defined `SUBCLASS_SCHEMAS`-style record + generated prompt lines + byte-locked prompt freeze + suite-side union map with unlabeled alignment + format-gate on core only. The infrastructure (`doc_subclass` kwarg, `align_unlabeled` batch path, `unlabeled_fields` payload) is already type-generic in the branch's suites.py.
- Insurance is the next most structured candidate (claim subclasses already parametrize prompt prose); its extraction map is currently entirely flat.

### Gaps

- Did not audit `llm-mailroom` repo (name exists at Cold_Storage/llm-mailroom — production pipeline) beyond the sandbox vendored copy; production-side subclass handoff (`docclass_mode`, `build_graph.py`) was not traced, so the production runtime's subclass flow is asserted from vendor copy only.
- eval-environment `src/evals/runner.py:67` reads `prediction.get("doc_subclass")` on the classification axis; whether extraction-scoring wiring there passes subclass into scores was not followed further.
