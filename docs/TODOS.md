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

- [ ] Mirror the corrected bytes into
      `config/prompts/correspondence_specialist_simplified.txt` and
      `config/prompts/corporate_records_specialist_simplified.txt`.
- [ ] Refresh `config/prompts/eval_environment_lineage.json` for both rows to
      the eval-environment mutation keys `correspondence_specialist_v7` /
      `corporate_records_specialist_v6` (keep the superseded v1 digest and
      `frozen_at` recoverable).
- [ ] `scripts/sync_specialist_prompts.py --check` and the sandbox prompt /
      lineage tests must pass with the stems byte-identical to the lock.

## Downstream importers of `llm-dojo-scoring`

- [x] Switch consumers that need the frozen eval-environment v1 specialist
      text to `get_prompt(<agent>, family="production_prompts")` instead of
      vendoring their own copy. (Done by llm-mailroom Task 2: specialists load
      the frozen v1 bytes; the dojo `production` family now equals them.)
- [x] Pin `llm-dojo-scoring @ v0.19.1` when adopting the corrected records. (Mailroom pin moves to v0.20.0 after this release.)

## Dojo reference pins (v0.19.1)

| Agent | `family` | `sha256` (prefix) |
|---|---|---|
| `contracts_specialist` | `production_prompts` | `d91de396…` |
| `corporate_records_specialist` | `production_prompts` | `fe13501f…` (= eval-environment `_v6`) |
| `correspondence_specialist` | `production_prompts` | `2b0b81ff…` (= eval-environment `_v7`) |
| `insurance_claims_specialist` | `production_prompts` | `6c2776bc…` |
| `merger_agreement_specialist` | `production_prompts` | `00323258…` |
