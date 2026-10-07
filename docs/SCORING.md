# Scoring

- Live extraction schemas (five mailroom-dataset classes): [`EXTRACTION_SCHEMAS.md`](EXTRACTION_SCHEMAS.md)
- Archive / unified scoring block: [`ARCHIVE_SCORING.md`](ARCHIVE_SCORING.md)
- MAUD GT, format vs extraction, completion and cost: [`SCORECARD_HONESTY.md`](SCORECARD_HONESTY.md)
- Metric identity: [`METRIC_IDS.md`](METRIC_IDS.md)
- Controlled `intent` labels (`label` field type): `llm_dojo_scoring/intents.py`

## Field types

| Type | Match rule |
|---|---|
| `id` / `date` / `money` | Exact after normalization (see [`EXTRACTION_SCHEMAS.md`](EXTRACTION_SCHEMAS.md)) |
| `name` | Jaro–Winkler + token-set; containment first |
| `free_text` | SQuAD-style token F1 |
| `entity_list[:type]` | Hungarian bipartite match, then set P/R/F1 |
| `label` | Controlled vocabulary. Both sides are canonicalized with `intents.normalize_intent` (aliases fold to the class's own vocabulary; another class's token canonicalizes to empty), then compared exactly: 1.0 or 0.0, never partial credit, no embedding rescue. |

`score_extraction` canonicalizes `intent` only when the field-type map says
`intent: label`. A map that says `intent: name` (historical archives)
keeps the old fuzzy behaviour, so rescoring old runs is unchanged. A
null ground truth with a predicted `"other"` is a spurious fill, not a match.
