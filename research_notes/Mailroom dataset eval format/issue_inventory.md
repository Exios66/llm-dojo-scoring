# Issue inventory — mailroom dataset & the four open PRs (as of 2026-10-17)

## CodeRabbit findings on the four PRs (reviews, inline comments, issue comments)

### Takeaway
Only 2 of 4 PRs have CodeRabbit reviews returned: sandbox #143 (1 review, 2 inline comments; one resolved in commit 649f71c, one still open) and EDA #22 (1 review, 2 inline comments, both open). Dojo #46 and eval-environment #99 have **NO review published yet** (reviews + inline comment arrays are empty); a full review was triggered via `@coderabbitai full review` on each, and on sandbox #143 a second request was blocked by the CodeRabbit free-tier rate limit ("Next included review available in 52 minutes").

### Cited Findings — PR #46 Exios66/llm-dojo-scoring
- `gh api repos/Exios66/llm-dojo-scoring/pulls/46/reviews` → `[]`; `pulls/46/comments` → `[]`; no inline findings published.
- Issue comments: CodeRabbit posted "review in progress" (ASSERTIVE profile, run `d9a185e8…`, reviewing commits 5431881…→e592ab09…, 23 files); user comment `@coderabbitai full review`; CodeRabbit reply "Full review triggered." — review had not landed at time of check.
- Status: review still PENDING. Any findings from it are unknown until it posts.

### Cited Findings — PR #99 LLM-Mailroom-Services/eval-environment
- `pulls/99/reviews` → `[]`; `pulls/99/comments` → `[]`; no findings published.
- Issue comments: only a Vercel deploy bot comment (preview `eval-environment-git-feat-corpo-fb0bd6-…vercel.app`, Ready) and CodeRabbit "review in progress" (CHILL profile; files `prompts/corporate_records_specialist_v7.md`, `prompts/mutations.json`; range bdba24ca…→b449a798…). `@coderabbitai full review` triggered ("Full review triggered.").
- Status: review still PENDING.

### Cited Findings — PR #143 Exios66/local-mailroom-sandbox (1 review + 2 inline comments)
- Review (id 5556959774, "Actionable comments posted: 2"), two inline comments:
  1. **`config/prompts/corporate_records_specialist_subclass_v2.txt` line 10 — "Restore the `subsidiary_list` rules for `subject_matter` and `keywords`"** (Minor, Functional Correctness): the `subsidiary_list` line gives extra keys `subsidiaries[]`/`subsidiary_jurisdictions[]` but never says `subject_matter` holds the subsidiary listing or that `keywords` hold the subsidiary names; a model could leave them null/empty and put names only in `subsidiaries[]`. Fix: add rules back (or document the change) **and update the SHA-256 + `chars` values in `eval_environment_lineage.json` in the same change**. **STILL OPEN** — verified: line 10 of the prompt file is unchanged (no `subject_matter`/`keywords` requirement), and the address-commit touched neither the prompt file nor `config/prompts/eval_environment_lineage.json`.
  2. **`config/prompts/eval_environment_lineage.json` ~lines 92–103 — "Update the generated prompt catalog and changelog for v7"** (Minor, Maintainability): add the frozen `corporate_records_specialist_v7` successor to `CHANGELOG.md` and regenerate `docs/prompts/` so its catalog + corporate-records page include v7; keep `corporate_records_specialist_v6` as sandbox default. **RESOLVED — "✅ Addressed in commit 649f71c"** (verified: commit 649f71c "fix: address review - regenerate prompt catalog, pin v7 gap, exact default-pin assertion, docs" changes CHANGELOG.md, config/prompts/README.md, docs/prompts/README.md, tests/test_eval_environment_lineage.py).
- Second `@coderabbitai full review` attempt was **rate-limited** ("You've used all free OSS reviews for now… Next included review available in 52 minutes"; issue comment updated 08:12:58Z) — further reviews of this PR are pending capacity.
- Review info: profile ASSERTIVE, config from repo `.coderabbit.yaml`, range ee9c595…→3ddd888…, 3 files processed.

### Cited Findings — PR #22 Exios66/Mailroom-Corpus-EDA (1 review + 2 inline comments)
- Review (id 5556979315, "Actionable comments posted: 2"), both on `src/mailroom_eda/v9_build.py` (Minor, Data Integrity, Quick win; no ✅ addressed markers — both open):
  1. **~Lines 180–182 — "Do not retain a confirmed ticker as a company-name suffix"**: if `filer` = `"First Majestic Silver Corp (AG) (CIK 0001308648)"`, `_clean_filer` removes the CIK but retains `(AG)` because `AG` is in `_NOT_TICKERS`; AG is also First Majestic's real ticker, so the backfill puts that ticker in all three generated fields. Fix: distinguish legal-form suffixes from ticker suffixes; add collision case to cleaner tests (links to sec.gov EDGAR filing for CIK 0001308648).
  2. **Line 184 — "Restrict state-suffix removal to state codes"**: `_STATE_TAIL` accepts any two uppercase letters, so `filer` ending `/UK/` has the country code stripped, losing part of the filer name (while the parenthetical `(UK)` form is preserved). Fix: match only recognized state codes; test a non-state suffix.
- Walkthrough/pre-merge checks: Merge Risk 🔵 Low; **1 failed pre-merge check — Docstring Coverage 20% (threshold 80%)** across 10 functions in 2 files; title/description/out-of-scope checks passed. Release-note summary: corporate backfills generate subject_matter/keywords from subclass phrases + cleaned filer names, fill empty `entity_name`, initialize missing/non-dict `gt_fields`.
- Range reviewed: 5fccfa13…→37f7542e… (37f7542 = current branch HEAD). Verified at HEAD: `_NOT_TICKERS` still contains `"AG"` (line 181) and `_STATE_TAIL` is still `r"\s*/[A-Z]{2}/\s*$"` (line 184) — both findings still valid.

### Inferences
- Dojo #46 and eval-environment #99 reviews are the biggest unknowns; the reviewer should re-poll their review/inline-comment APIs before finalizing a fix list (or trigger again if the review never landed).
- The EDA commit 37f7542 ("address review - robust filer cleaning…") predates the published CodeRabbit review; the published findings are against the same HEAD, so nothing on EDA has been addressed yet.
- Sandbox #143: after the open finding #1 is fixed, the prompt bytes (and thus the sha256 + `chars` in `config/prompts/eval_environment_lineage.json` and the eval-environment `corporate_records_specialist_v7` bytes) must change in lockstep across sandbox ↔ eval-environment ↔ dojo catalog — a cross-repo ripple.

## Known limits documented in llm-dojo-scoring docs

### Takeaway
`docs/CORPORATE_RECORD_SCHEMA.md` §"Known limits of the repaired labels" records 4 standing limits (entity_name from EDGAR filer metadata ~25% inexact; DOC-85c7b49cdac19586 deliberately left on the subclass conflict; all 450 intents remain heuristic; extension entities unscored until the dataset labels them). The broader corpus-wide defect landscape (why the repair exists) is in the same file's "Why" section; cross-repo pending work lives in `docs/TODOS.md`.

### Cited Findings
- **`docs/CORPORATE_RECORD_SCHEMA.md` "Known limits of the repaired labels"**:
  1. `entity_name` comes from EDGAR filer metadata in the template subject_matter, **not from document text**; ~25% differ from the in-document name (mostly `CO`/`Company` style) — treat as the registrant, not a verbatim string.
  2. `DOC-85c7b49cdac19586` (organizational minutes approving bylaws) matches two subclass cues and is **deliberately not auto-reassigned**; probably `board_resolution`. (This is the "left unfixed" cue-conflict row.)
  3. **All 450 intents remain `intent_source: heuristic`**; the relabel never overrides an adjudicated intent, `record_type`, or a populated `filing_number`.
  4. Extension entities are scored only once the dataset labels them (`gt_presence` `populated` / `schema_documented_absence`); `pending_annotation` and unstated blanks are unlabeled.
- **Corpus diagnosis (same file, "Why")**: published GT (450 `corporate_record` rows) labels none of `entity_name`/`record_type`/`effective_date`/`signatories`/`jurisdiction`/`filing_number` on any row; only intent/subject_matter/keywords populated, as provenance boilerplate (`subject_matter` = `<subclass> of <Company> (CIK …) (SEC EDGAR exhibit)` on 411 rows; keywords carry exhibit/form/accession/CIK ids on 412; intent is a 1:1 function of subclass, 450/450 heuristic). A correct extraction scored precision 0.375 under the old scoring. The 39 legacy S-1 rows have 14 subclass/content conflicts (e.g., "Bylaws of …" under `articles_of_incorporation` ×8 / `powers_of_attorney` ×2, plus minutes, registration-rights agreements, specimen certificates).
- **Relabel scope (same file, "Dataset labels — repair tooling")**: on v9.2 it populates `entity_name` (411 rows) and `record_type` (450); replaces 411 template subject_matter; strips provenance ids from 422 keywords; re-assigns 12 conflicting expected_subclass (+ re-pin intent); marks inapplicable fields `not_applicable`. **Everything else stays unlabeled and needs real annotation; 2 conflicts are ambiguous and stay flagged; intent remains heuristic.** Schema table flags intents for review on `charter_amendment`, `indenture`, `officer_certificate` (`SubclassSchema.intent_review`), kept for score comparability.
- **Remaining dataset work (same file, "Dataset labels — what has to change", outside this repo)**: (1) label each subclass's core+extension entities with `gt_presence` populated/schema_documented_absence; (2) replace template subject_matter, drop provenance ids from keywords; (3) fix the 14 subclass/content conflicts (or add subclasses for minutes / registration-rights / specimen certificates), re-adjudicate flagged intents, record non-heuristic `intent_source`; (4) re-pin the taxonomy fixture.
- **Prompt divergence caveat (same file, "Specialist prompt")**: `corporate_records_specialist` sha256 `b40963bb…` diverges from the vendored mailroom `frozen_v1` bytes; the same change must land in llm-mailroom and eval-environment before the next `sync_production_prompts.py --check`.
- **`docs/TODOS.md` (Connected-repo TODOs) — still-open checkboxes**: eval-environment: `[ ]` regenerate `web/data/snapshot.json` (`scripts/export_site_snapshot.py`) where llm-mailroom is importable; sandbox: `[ ]` mirror corrected bytes into `config/prompts/{correspondence,corporate_records}_specialist_simplified.txt`, `[ ]` refresh `config/prompts/eval_environment_lineage.json` for both rows to `correspondence_specialist_v7` / `corporate_records_specialist_v6` keys, `[ ]` `scripts/sync_specialist_prompts.py --check` + prompt/lineage tests green with stems byte-identical to the lock.

### Gaps
- The relabel/scripts do not hard-code any `DOC-…` row IDs (grep found none); the DOC-2e10b60058bb3b36 leftover-template fix is structural (every template subject_matter row is rewritten), verified via the module contract (template regex → grounded sentence) rather than a per-ID assertion. No test pins that specific DOC id.

## Test failures outside the dojo repo

### Takeaway
Confirmed by cheap targeted runs: Mailroom-Corpus-EDA has 4 failing tests (3 in `test_eval_contract.py`, 1 in `test_fixtures.py`), all rooted in `eval_contract` expecting merger agreements to route to `contracts_specialist` while the live taxonomy has `merger_agreement_specialist`; the 4 pre-existing eval-environment `tests/test_prompts.py` failures cited in PR #46 reproduce on the local STAGING checkout (2 × KeyError 'sorter' lineage gaps + 2 × ModuleNotFoundError 'llm'); local-mailroom-sandbox has exactly 2 sibling-checkout test failures, both caused by the adjacent eval-environment checkout sitting on branch `STAGING` (head 4ffe258) which lacks the SAND-042 / frozen-specialist mutation keys (`_v4` claims, `correspondence_specialist_v7`, `corporate_records_specialist_v6`/`_v7`).

### Cited Findings — Mailroom-Corpus-EDA (branch `feat/grounded-corporate-backfill`, HEAD 37f7542)
- `uv run pytest tests/test_fixtures.py tests/test_eval_contract.py -q` → **4 failed**:
  - `tests/test_fixtures.py::test_specialist_routing_present`
  - `tests/test_eval_contract.py::test_expected_specialist_registry_mapping`
  - `tests/test_eval_contract.py::test_expected_specialist_matches_live_taxonomy_yaml` — `AssertionError: merger_agreement: assert 'merger_agreement_specialist' == 'contracts_specialist'`
  - `tests/test_eval_contract.py::test_row_level_invariants_over_fixture_rows` — `assert 'merger_agreement_specialist' in ('contracts_specialist', 'corporate_records_specialist', 'correspondence_specialist', 'insurance_claims_specialist')` (i.e., `ec.SPECIALISTS` omits `merger_agreement_specialist`)
- Root cause: `src/mailroom_eda/eval_contract.py` constants are stale vs. the live `taxonomy.yaml` / specialist registry, which now maps merger_agreement → `merger_agreement_specialist`. These are the "known pre-existing failures: test_eval_contract ×3, test_fixtures" declared in PR #22's body.

### Cited Findings — eval-environment local checkout (branch `STAGING`, head 4ffe258)
- `uv run pytest` cannot even build the project here: `Failed to generate package metadata for mailroom==0.7.1 @ editable+../llm-mailroom … 'llm-dojo-scoring' references a workspace in tool.uv.sources but is not a workspace member` (sibling-layout issue). Using the committed `.venv/bin/python -m pytest tests/test_prompts.py` instead → **4 failed, 16 passed**, matching PR #46's "eval-environment `tests/test_prompts.py` ×4":
  - `test_resolve_all_layers` — `KeyError: "unknown prompt version 'sorter'"` (known versions go `sorter_v1/v2/v3` + `sorter_reviewer_v1`; no bare `sorter`), from `src/evals/prompts/lineage.py:97`
  - `test_all_versions_layer_priority` — same `KeyError: 'sorter'` at `tests/test_prompts.py:308`
  - `test_injection_and_restore` — `ModuleNotFoundError: No module named 'llm'` at `src/evals/prompts/registry.py:93`
  - `test_injection_reaches_the_merger_agent` — same `ModuleNotFoundError: 'llm'`
- Notably, the STAGING lineage's known-key list tops out at `corporate_records_specialist_v5` and `correspondence_specialist_v6` — the STAGING branch predates both the correspondence/corporate v1-refreeze (`_v6`/`_v7`) and the `_v7` mutation under review.

### Cited Findings — local-mailroom-sandbox (branch `feat/corporate-records-subclass-v2`, HEAD 649f71c)
- `uv run pytest tests/test_eval_environment_lineage.py` → **1 failed, 19 passed**: `test_sibling_eval_environment_matches_when_present` — `verify_sibling_catalog` returns errors including `'corporate_records_specialist: superseded corporate_records_specialist_v1 sha256=484e64dd… != sibling manifest sha256=fe13501f…'` (it expects `_v6` bytes `fe13501f…` as v1's superseder) and `'corporate_records_specialist: sibling mutations.json missing corporate_records_specialist_v7'`; 5 error items total spanning corporate + correspondence specialists. This is the failure declared in PR #143's body.
- `uv run pytest tests/test_prompt_versions_dojo.py` → **1 failed, 53 passed**: `test_lineage_matches_the_sibling_eval_environment_checkout` — `KeyError: 'insurance_claims_specialist_v4'` when iterating the sibling `prompts/mutations.json`; the STAGING checkout also lacks the SAND-042 frozen `insurance_claims_specialist_v4`/`merger_agreement_specialist_v4` keys. This is the **second** sibling-checkout failure (matches the task's count of 2).
- Fix path: either the eval-environment checkout must move to a branch holding `_v4`/`_v6`/`_v7` (e.g., the PR #99 head, commit b449a798), or `verify_sibling_catalog` must tolerate STAGING; the sandbox failures are environment-relative, not code defects in the sandbox PR itself.

### Gaps
- Did not run the other eval-environment/sandbox/EDA suites (per constraints); other latent failures outside these files were not surveyed.
- CI logs on GitHub Actions for these PRs were not retrieved; the numbers above are the local-checkout repro.

## HF branch audit — what is still unrepaired

### Takeaway
The doc-ID-level defects found in the Hub-branch audit were fixed structurally by the row-agnostic relabel (template row DOC-2e10b60058bb3b36 is covered because every template `subject_matter` row is rewritten; paren ids, double periods, ticker lists, `(SEC EDGAR exhibit: …)` variant, `EX-3.1(A)` ids were all fixed in idempotency follow-ups per PR #46), and the rebuilt branch is now actually pushed (head `0a2f829…`). The unrepaired remainder is exactly what "Known limits" declares: the DOC-85c7b49cdac19586 cue-conflict row (kept deliberately), all 450 intents still `heuristic`, unlabeled entity/jurisdiction/filing fields still needing real annotation, and entity_name sourced from EDGAR metadata (~25% inexact).

### Cited Findings
- `corporate_record_relabel.py` docstring/contract: repairs on the row itself — entity_name from the company already named in the template; template subject_matter → one grounded sentence; provenance keyword strings removed (exhibit, form type, accession, CIK); `relabel_row` is pure ("returns a new row plus a change list; it never mutates input"); trailing `(TICK)`/`(TICK, TICK-PA)` and EDGAR `/UT/` state suffixes handled by `_TICKER_RE`/`_STATE_RE` with `_NOT_TICKERS` guard. No DOC-per-ID logic anywhere in the repo (grep zero hits, including tests).
- PR #46 body, "Adversarial review" section: relabel idempotency/regression fixes landed for stated `record_type`/`intent`/`filing_number` overwrite, `(UK)` mangling, ticker lists, `/UT/`, double period, `(SEC EDGAR exhibit: …)` variant, `EX-3.1(A)` ids; "Hub-branch audit: 450 corporate rows only, non-corporate byte-identical, enums valid; defects above (leftover template row, paren ids, double periods, ticker lists) are fixed in the relabel and the rebuilt files verify".
- Still-open per docs/CORPORATE_RECORD_SCHEMA.md §Known limits: DOC-85c7b49cdac19586 deliberately left; 450/450 intents heuristic; entity_name ~25% divergent from in-document name; extension entities unscorable until dataset annotation.

### Inferences
- Nothing in the branch audit remains unrepaired at the row level beyond the deliberately-kept conflict row and the annotation-dependent items; an implementer "repairing the audit" means: (a) human review of the 2 ambiguous conflicts + the 12/14 auto-reassigned subclass fixes, (b) real annotation of unlabeled entity fields, (c) intent adjudication — all dataset-side work, not code.

## Open TODOs / decisions recorded in the four PR descriptions

### Takeaway
Every PR body explicitly lists pending adversarial review + CodeRabbit full review; the sandbox PR carries two documentation TODOs (README table, CHANGELOG), the EDA PR admits the branch is behind unmerged main work, the dojo PR carries the merge-order dependencies, Hub-review-before-promote decision, and an urgent token-rotation caveat; several "not yet pushed / not landed" statements are now resolved.

### Cited Findings — verbatim-worthy items per PR body
**Dojo #46 (`Exios66/llm-dojo-scoring`, head e592ab09 → advanced past the reviewed 5431881):**
- `"Draft: work in progress — adversarial review and full audits still pending (see Plan)."` plan step 7: `"Review/audit — adversarial review subagents over dojo, siblings and Hub branch; then @coderabbitai full review."`
- Merge notes: `"eval_environment_lineage.json re-synced to eval-environment b449a79 (41 versions) — depends on the eval-environment PR landing (branch based on claude/cool-wozniak-o044u4, which holds _v6)."`, and `"llm-mailroom picks the prompt up only when its dojo pin moves."`
- Hub decision: repaired rows on branch `corporate-labels-v9.2.1`; **"not merged to main, v9.2 pin unchanged"**; follow-up: `"Review Hub branch before promoting to main / bumping the pin (v9.1 experiments unaffected)."`
- Security caveat: `"An HF token was pasted in chat during this work — rotate it."`
- Now-resolved claim: `"rebuilt branch not yet pushed (needs HF write token; v1 of the branch remains)"` — superseded by the later push (see HF section below).
- Pre-existing failures declared: eval-environment `tests/test_prompts.py` ×4; sandbox `test_sibling_eval_environment_matches_when_present`; EDA `test_eval_contract` ×3, `test_fixtures` (all reproduced above).

**eval-environment #99 (`feat/corporate-records-v7`, stacked on `claude/cool-wozniak-o044u4` which holds `_v6`):**
- `"Pending: adversarial review, CodeRabbit full review."`
- Also (from TODOS.md context rather than the PR body): snapshot.json regeneration remains open for eval-environment.

**sandbox #143 (`feat/corporate-records-subclass-v2`):**
- `"Pending: docs (config/prompts/README table, CHANGELOG), adversarial review, CodeRabbit full review."` — docs TODO partially done by 649f71c (CHANGELOG.md +5, config/prompts/README.md, docs/prompts/README.md); the SUBCLASS-v2 README table entry appears done, but re-verify docs/prompts/catalog includes v7 (CodeRabbit's ✅ addressed marker covers this finding).
- `"Depends on: eval-environment draft PR (_v7) and Exios66/llm-dojo-scoring#46."`
- Declared known failure: `test_sibling_eval_environment_matches_when_present` (reproduced).
- Unresolved CodeRabbit finding #1 (subsidiary_list rules + lineage sha/chars update) — see review section.

**EDA #22 (`feat/grounded-corporate-backfill`):**
- `"Pending: adversarial review, CodeRabbit full review."` — the review has since posted (2 open findings).
- `"Known pre-existing failures: test_eval_contract ×3, test_fixtures."`
- Body claim `"New tests/test_corporate_backfill.py passes."` is consistent with the local run (that file was not among the failing tests). Caveat from the reviewer's merge-risk note: the ticker/country-code label defects are "bounded, mergeable with owner awareness and follow-up".
- Note: EDA HEAD (37f7542) still sits on top of main at 5fccfa1; no rebase/merge of latest main noted.

### Inferences
- Merge order matters: eval-environment #99 must land (its branch carries `_v6` + `_v7`) before sandbox #143's lineage keys and the dojo catalog/lineage sync resolve cleanly; the sandbox and dojo PRs both name that dependency, and both local sibling tests fail only because the STAGING checkout lags.

## HF branch corporate-labels-v9.2.1 pushed?

### Takeaway
Yes — verified via the HF API: branch `corporate-labels-v9.2.1` exists on `Lucius-Morningstar/mailroom-dataset` with head `0a2f829248525cf434ed49e38c3ac43b05090ba6` ("v9.2.1: corporate_record label repair… Deterministic repair via llm_dojo_scoring.corporate_record_relabel. Label-only over v9.2…"), pushed 2026-10-17T08:14:45Z as the second commit on the branch, superseding `2258a6275f6b8c2ca6a566b638b7036d77dcab33` (07:51:54Z, cited in the PR body). PR #46's "rebuilt branch not yet pushed" is therefore RESOLVED.

### Cited Findings
- `GET https://huggingface.co/api/datasets/Lucius-Morningstar/mailroom-dataset/refs` → branches: `corporate-labels-v9.2.1` → `0a2f829248525cf434ed49e38c3ac43b05090ba6`; `main` → `670e8bc6…`. Tags: `v9.1` (bc9eab28…), `v9.2` (1eb5b42c…) — the v9.2 pin is untouched, as the PR promises.
- Commit history of the branch: `0a2f829…` (2026-10-17T08:14:45Z, "v9.2.1: corporate_record label repair (entity_name/record_type, grounded subject_matter, provenance-free keywords, 12 subclass fixes)") on top of `2258a627…` (07:51:54Z, same title) on top of main's `670e8bc6…` (v9.2 relations & provenance revision, 2026-10-06).
- The 0a2f829 commit message claims "row set, identity and content unchanged; see README section 'v9.2.1'".

### Gaps
- Did not diff the branch payload row-by-row (would require downloading the parquet); "enums valid / non-corporate byte-identical" rests on the PR body's audit claim plus the relabel's design, not an independent re-verification here.
- Whether the HF token flagged for rotation was actually rotated could not be checked read-only.
