# llm-dojo-pipeline (skeleton — not released)

This is the dedicated scoring package for the full Mailroom pipeline. It is tracked
in #83, and its parent issue is #66. It lives on the long-lived branch
`feat/66-pipeline-scoring-package` and **must not merge to `main`** until the plan
is complete.

## Scope

| Family | Task keys | Contract |
| --- | --- | --- |
| `classification` | `subtype` / `doc_class` / `multiclass` | exact match + CI, macro accuracy, per-class, confusion |
| `hierarchical` | `docclass` / `maud_docclass` | doc_type accuracy + macro P/R/F1/F2, subclass accuracy |
| `maud` | `maud_question` / `maud_extraction` | exact match + CI, per-class, macro |
| `correspondence` | `enron_topic` / `enron_sentiment` | accuracy, macro-F1, per-class |
| `transcription` | `transcription` / `wer` / `cer` (PDF transcriber, image transcriber/OCR) | WER, CER, word/character accuracy |

## Layers

- `contracts`: declares the metric contract for each family. A result that is missing a
  required key is reported in `contract_gaps`. `strict=True` raises an error instead.
- `families.score_family`: delegates to `llm_dojo_scoring.score_task`, so numbers are
  identical to the core.
- `events.ScoreEvent`: a sink-neutral record. The trace target, data type and comment
  are typed fields here, where the core keeps them in loose metadata.
- `sinks`: the `TraceSink` protocol plus these adapters:
  - `LocalManifestTraceSink`
  - `LangfuseTraceSink`, which keeps score-name parity with the dojo alias table that
    The-Mailroom visualizer reads
  - `FanoutSink`
  - `PhoenixTraceSink` and `OTelTraceSink`, which are planned and raise
    `NotImplementedError` for now
- `pipeline.PipelineScorer`: maps graph nodes to families, scores a node, and emits
  the result to any set of sinks.

## Install (once released, tag prefix `pipeline-v`)

```
llm-dojo-pipeline @ git+https://github.com/Exios66/llm-dojo-scoring.git@pipeline-v0.1.0#subdirectory=packages/llm-dojo-pipeline
```

Tags are namespaced so that `update_awareness` and the mailroom `bump-dojo-scoring`
workflow never mistake a pipeline release for a core `vX.Y.Z` release.
