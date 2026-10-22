# Connected-repo TODOs

Follow-ups for repos that mirror the frozen specialist prompts or import the
dojo prompt catalog. The dojo side of the v0.19.1 `production_prompts` lineage
is complete; the items below are **not** done in this repo.

## `LLM-Mailroom-Services/eval-environment` — freeze the two corrected records (#29)

Done on eval-environment branch `claude/cool-wozniak-o044u4` (`3f9bd55`, not yet
merged). The `_v1` records stay immutable and remain the default; the
corrections landed through `apply_mutation` as the next free mutation keys,
because `_v2`… were already taken by GEPA mutations:

- [x] `correspondence_specialist_v7` (parent `_v6`) — sha256 `2b0b81ff…`
- [x] `corporate_records_specialist_v6` (parent `_v5`) — sha256 `fe13501f…`
- [ ] Regenerate `web/data/snapshot.json` (`scripts/export_site_snapshot.py`)
      where llm-mailroom is importable; it embeds `prompts/mutations.json`.

## `Exios66/local-mailroom-sandbox` — mirror the corrected stems

Landed on sandbox `main` via
[local-mailroom-sandbox#146](https://github.com/Exios66/local-mailroom-sandbox/pull/146).

- [x] `config/prompts/correspondence_specialist_simplified.txt` is the
      corrected stem (`2b0b81ff…`).
- [x] `config/prompts/corporate_records_specialist_simplified.txt` stays the
      v6 experiment stem (`fe13501f…`). The v7 bytes (`253559fc…`, 5,462
      chars) are the canonical `corporate_records_specialist_subclass_v2`
      stem, and #146 moved the corporate default pin from v6 to v7.
- [x] Lineage lock and specialist sync checks were part of the #146
      verification (1338 passed; two pre-existing mailroom-ml sibling
      failures only).

## Upstream blockers (tracked outside this repo)

- [x] eval-environment canonical prompt fix — `corporate_records_specialist_v7`
      at the pinned lineage commit `22d217ab` is sha `253559fc…` (explicit
      `certificate_of_formation` line, `omit authorized_capital`, and
      `subsidiary_list` guidance). The interim `ec3bccc2…` draft is
      superseded. Merging that branch to eval-environment `main` is still
      open:
      [eval-environment#104](https://github.com/LLM-Mailroom-Services/eval-environment/pull/104),
      tracked on dojo #29.
- [ ] llm-mailroom re-vendor — bump the vendored llm-dojo-scoring snapshot
      (still v0.22.0: no `corporate_record_schema.py`, no unlabeled
      alignment, "39 corporate_record rows" suite docstring). Keep the
      corporate `production` freeze at v6 (`fe13501f…`) until mailroom
      promotes evaluation v7 (`253559fc…`). Until the scoring snapshot moves,
      a prompt bump alone leaves v0.22.0 scoring semantics in place.
      Tracked on dojo #51.

## Dataset annotation (outside this repo)

- [ ] Human labels for the entity fields the relabel cannot derive
      (`jurisdiction`, `signatories`, `effective_date`, `filing_number`,
      subclass entities), the two ambiguous subclass conflicts, and the
      450 heuristic intents. The relabel JSONL is a proposal, not ground
      truth. Tracked on dojo #52.

## Downstream importers of `llm-dojo-scoring`

- [x] Switch consumers that need the frozen eval-environment v1 specialist
      text to `get_prompt(<agent>, family="production_prompts")` instead of
      vendoring their own copy. (Done by llm-mailroom Task 2: specialists load
      the frozen v1 bytes; the dojo `production` family follows that freeze.
      Corporate production remains v6 until mailroom promotes evaluation v7.)
- [x] Pin `llm-dojo-scoring @ v0.19.1` when adopting the corrected records. (Mailroom pin moves to v0.20.0 after this release.)

## Dojo reference pins (v0.19.1)

| Agent | `family` | `sha256` (prefix) |
|---|---|---|
| `contracts_specialist` | `production_prompts` | `d91de396…` |
| `corporate_records_specialist` | `production_prompts` | `253559fc…` (= eval-environment `_v7`) |
| `correspondence_specialist` | `production_prompts` | `2b0b81ff…` (= eval-environment `_v7`) |
| `insurance_claims_specialist` | `production_prompts` | `6c2776bc…` |
| `merger_agreement_specialist` | `production_prompts` | `00323258…` |
