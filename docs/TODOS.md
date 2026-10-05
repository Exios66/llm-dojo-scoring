# Connected-repo TODOs

Follow-ups for repos that mirror the frozen specialist prompts or import the
dojo prompt catalog. The dojo side of the v0.19.1 `production_prompts` lineage
is complete; the items below are **not** done in this repo.

## `LLM-Mailroom-Services/eval-environment` — re-freeze the two corrected v1 records

The dojo's `correspondence_specialist_v1` and `corporate_records_specialist_v1`
bytes carry a local re-freeze (2026-10-05) that the upstream mirror does not
have yet. AGENTS.md rule 9 makes the frozen lineage immutable, so land the
correction through the sanctioned path (`evals.prompts.mutations.apply_mutation`
or a scripted re-promote — never a hand edit).

- [ ] `scripts/promote_sandbox_specialist.py` / `evals.prompts.mutations.apply_mutation`:
      re-cut `correspondence_specialist` with the `other`-bucket fallback
      aligned to the registered 8-token vocabulary (`communication_type: null`,
      no `other` token) and the null-first field spec.
- [ ] Same path for `corporate_records_specialist`: `filing_number` null unless
      an official filing/document number is stated; parent-agreement exhibit
      IDs do not qualify.
- [ ] Update `src/evals/prompts/frozen_v1.py`, `prompts/<key>.md`, and
      `prompts/manifest.json` sha256/chars together; update the
      `PRE_EXISTING_SANDBOX_SHA256` guard pins in `tests/test_prompts.py` in
      the same commit.
- [ ] `uv run pytest tests/test_prompts.py -q` and
      `uv run python scripts/freeze_prompts.py --check`.

## `Exios66/local-mailroom-sandbox` — mirror the corrected stems

- [ ] Mirror the corrected bytes into
      `config/prompts/correspondence_specialist_simplified.txt` and
      `config/prompts/corporate_records_specialist_simplified.txt`.
- [ ] Refresh `config/prompts/eval_environment_lineage.json` sha256/chars for
      both rows after the eval-environment re-cut (keep the original
      `frozen_at`; record the re-freeze stamp).
- [ ] `scripts/sync_specialist_prompts.py --check` and the sandbox prompt /
      lineage tests must pass with the stems byte-identical to the lock.

## Downstream importers of `llm-dojo-scoring`

- [ ] Switch consumers that need the frozen eval-environment v1 specialist
      text to `get_prompt(<agent>, family="production_prompts")` instead of
      vendoring their own copy.
- [ ] Pin `llm-dojo-scoring @ v0.19.1` when adopting the corrected records.

## Dojo reference pins (v0.19.1)

| Agent | `family` | `sha256` (prefix) |
|---|---|---|
| `contracts_specialist` | `production_prompts` | `d91de396…` |
| `corporate_records_specialist` | `production_prompts` | `fe13501f…` (locally corrected) |
| `correspondence_specialist` | `production_prompts` | `2b0b81ff…` (locally corrected) |
| `insurance_claims_specialist` | `production_prompts` | `6c2776bc…` |
| `merger_agreement_specialist` | `production_prompts` | `00323258…` |
