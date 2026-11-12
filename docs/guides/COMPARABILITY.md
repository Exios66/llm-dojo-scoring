# Comparability across scorer releases

A card built from two runs is comparable only when the documents, prompts,
models, metric identity, and **scorer release** agree. The first four were
already enforced; the scorer release is the v0.26.0 addition (#97).

## The guard

`compare_serving` now reads each leg's own `provenance.scorer_version` (or a
top-level `scorer_version`) and reports:

| Status | Meaning | Quality delta |
| --- | --- | --- |
| `scorer_version_mismatch` | Both legs name different releases | suppressed (`None`) |
| `scorer_version_missing` | One leg names a release, the other does not | suppressed |
| `scorer_version_mixed` | One leg pools runs from different releases | suppressed |
| `scorer_version_unverified` | Both legs are unstamped, or a leg pools stamped and unstamped runs | reported with a flag |

`pair_comparable_runs` also includes the release in its pairing key, so a
local run and an API run from different releases are never paired silently.

The mismatch payload carries `left_scorer_version`, `right_scorer_version`,
and `score_changes` — the ledger entries between the two releases. A reader can
see whether a delta is a model effect or a scorer fix without opening the
CHANGELOG.


## Release ledger

`llm_dojo_scoring.metrics.score_changelog.SCORE_CHANGELOG` is the machine
ledger. `score_changes_between("0.24.0", "0.26.0")` returns every release in
the interval; `score_changes_for_metric("cuad.clause_presence.micro_f1", ...)`
narrows to one metric. Add an entry only when a deterministic scorer change can
move a number on unchanged predictions.

| Release | What moved | Re-score required |
| --- | --- | --- |
| 0.22.0 | MAUD fold/reducer and six MAUD truth defects | yes |
| 0.25.0 | Merger subclass `other` unannotated | yes |
| 0.26.0 | CUAD parties/effective-date truth; insurance `cms_source_table` orthogonal | yes |

The table is intentionally short. A refactor that leaves predictions and scores
identical does not need an entry; a release that moves a number does.

## Reading a historical card

1. Check `scorer_version` on both legs. If they differ, do not compare the
   quality delta.
2. Read `score_changes` or the ledger for the interval.
3. For a quality record (extraction, label tasks, reviewer), re-score the
   older run's stored predictions with the current suite (`get_suite(...).score`) before comparing.
4. A serving card cannot be re-scored, because timings and hardware counters are not reproducible. Compare its
   timing and cost metrics as recorded, and treat its quality delta across a
   release mismatch as incomparable.
5. If re-scoring is impossible (the run store lost predictions or GT), label
   the card with the supported bound and the unverified release; never present
   the delta as a model effect.
