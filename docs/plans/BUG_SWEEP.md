# Bug sweep: open defects and gaps (after #103 / #105 / #106)

Tracking list for the follow-up sweep. Each item says where it is, why it
matters, and how it was found. Tick items off, or move them to issues, as they
are fixed. Scoring changes land here first (CLAUDE.md); a change that moves
scores needs a CHANGELOG comparability note and a `score_changelog` entry.

## Scoring correctness

- [ ] **#94 correspondence GT relabel.**
  - Measured on the Hub `ground_truth` config: 904 of 1,000 rows have templated
    `subject_matter`, and 860 of 1,000 have keywords that are all metadata.
  - Steps 2–5 of #94 are open: a deterministic relabel proposal, a human-review
    export, GT for the 8 unpopulated fields or an explicit decision to drop them,
    and `GT_METADATA.md` results.
- [ ] **Correspondence audit known gaps.**
  - 44 templated rows are still not counted as all-metadata. The unmatched values are:
    - underscore-style mailbox ids (`bill_williams_iii`, `chris_stokley`);
    - first-name mailboxes (`jean`);
    - custom Enron folders (`power`, `tw_commercial_group`, `bankrupt`, …).
  - See `schemas/correspondence_gt_audit.py`.
- [ ] **Insurance `claim_checklist`:** it is in the live field map, but no Hub row
  populates it, so the insurance headline is always `partial`. Either add GT or drop
  the field from the map in step with llm-mailroom.
- [x] **`"nan"` string values:** they appear in 350 non-CMS insurance rows (topic and
  sentiment keys). Verify `scoring_gt_fields` / `is_empty_value` treat `"nan"` as
  empty for every class that maps those keys.
  Fixed: `is_empty_value` treats `nan` / float NaN as empty.
- [ ] **Intents never seen in GT:** `loss_report` and `other` (insurance) never occur in
  the Hub data. Decide whether hints should still teach them.
- [x] **PR #106 adversarial review:** confirmed findings 1–3, 5 and 6 are fixed in
  #106 (`fcca394`).
- [ ] **CMS detection still sniffs the key.** A plain-dict GT that carries
  `cms_source_table` puts a non-CMS row into CMS mode (#106 review, finding 4).
  Replace key-sniffing with an explicit flag set where GT is scoped.
  Narrowed, not closed: a row whose GT names a product line other than
  `health` is never CMS, and the token must be a known CMS table. A `health` or
  `claim_type`-less plain dict that carries the key is still treated as CMS
  until detection reads explicit provenance.
- [x] **Scalar `expected_subclass` with a list `expected`.** In batch scoring this
  marks every row as CMS. Numpy or pandas subclass arrays silently miss detection,
  and `rescore` reads only the `expected_subclass` key (#106 review).
  Fixed: a scalar is not broadcast for CMS derivation in a batch; arrays are read per row; rescore also reads `doc_subclass`.
- [x] **Archive method label is wrong for CMS blocks.** The `method` label
  `unweighted_mean_of_nonempty_expected_fields` no longer describes them, because
  documented-absent fields join the mean (`n_fields_scored` 14 → 17).
  Fixed: `ARCHIVE_SCORING_METHOD_CMS`, same `metric_id`.
- [x] **CMS branch skipped when `adjuster` is missing.** If the expected dict has no
  `adjuster` key, the CMS branch is skipped, while field-micro metrics still count a
  stated adjuster as a false positive.
  Fixed: a stated value on an omitted documented-absent key scores 0; silence on it is not scored.
- [x] **NDC padding.** `zfill(11)` mis-normalizes the 5-3-2 / 5-4-1 forms of a
  10-digit NDC, causing false negatives in `_cms_doc_signature`.
  Fixed: hyphenated segments pad to 5-4-2.

## Reporting / honesty

- [x] **Unescaped Markdown in grid output:** specialist names are interpolated without
  escaping into the grid table and the headline-scope footnotes (`analysis/grid.py`).
  A name containing `|`, `**` or a newline breaks the report.
  Fixed: `_cell` escapes free text.
- [x] **Exports:** `headline_scope` / `intent_split` are not exported from the package root.
  Decide whether they are part of the public surface.
  Decided: public in `metrics.scorecard_honesty` (its `__all__`), like `aggregate_quality_honest`; not root exports.
- [x] **Scored-enum fragments have no `"type"`.** Strict structured-output decoders may
  require one. See `schemas/scored_enums.py`.
  Fixed: `type` is `["string", "null"]` or `"string"`.

## Portability / CI (no GitHub Actions dependency)

- [ ] **Suite fails off the dev machine.** The CI investigation was interrupted
  before it reported. Known breakers:
  - plain system Python lacks `structlog`, so `import llm_dojo_scoring` fails outside `uv`;
  - ~~`test_release_tools` fails in shallow clones without tags~~ (fixed: the notes test
    skips when the release tags are missing);
  - `scripts/audit_consumer_surface.py` pins developer checkout paths and exits 2 when
    they are missing.
- [ ] **Repo-owned CI entry point.** Build one (e.g. `scripts/ci.py`) that:
  - builds the wheel into a clean venv from `uv.lock`;
  - runs a fast smoke/contract tier and an offline-by-default full tier;
  - emits a machine-readable summary;
  - runs locally, in a container, or from a pre-push hook.
- [ ] **Suite bloat.** Profile it (`--durations`, tests per file) and demote pinning-only
  tests (doc-table lockstep, docstring coverage) out of the smoke tier.

## Process notes

- [ ] **`intent_split` commit label.** The `intent_split` non-finite fix shipped inside
  the #95 commit `4ef6882`, not the #94 commit. It is noted in `3a07966`; no action
  needed beyond awareness.
- [ ] **Commit `3a07966` never had a second-round adversarial review.** This is the
  #94 hardening commit on #105.
