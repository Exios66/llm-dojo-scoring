# Specialist grid reports (local → Modal GPU)

`llm_dojo_scoring.grid` builds a scorecard for multi-experiment studies in
the **L4 Specialist Grid** shape: one row per specialist with the class
metric, `ok / n`, p50 latency, and GPU cost **per ok document**; a pooled
serving-efficiency table; and a cost table separating **busy-window** GPU
time from the **metered** provider session.

```python
from llm_dojo_scoring import GridDocument, GridExperiment, build_grid_report

documents = [
    GridDocument(
        experiment="Experiment 3",
        specialist="Contracts",
        metric_id="cuad.clause_presence.micro_f1",
        score=0.612,
        ok=True,
        latency_seconds=96.1,
        gpu_seconds=310.0,
        completion_tokens=12000,
    ),
    # one row per scored document, per cell
]

experiments = [
    GridExperiment(
        name="Experiment 3",
        posture="2×L4 C32 n=50",
        gpus=2,
        gpu_type="L4",
        gpu_hourly_usd=0.80,
        client_concurrency=32,
        wall_seconds=1840.0,      # busy run window for the cells
        metered_usd=1.09,          # whole Modal session from the billing report
        billed_usd=0.00,
        documents_per_class=50,
        status="5 of 5 cells",
        serving_kind="modal",      # local | modal | api — never remapped
    ),
]

md = build_grid_report(
    documents=documents,
    experiments=experiments,
    title="L4 Specialist Grid (Experiments 1–4): Results and Cost Summary",
    setup="Qwen/Qwen3-8B-AWQ on vLLM v0.29.0, NVIDIA L4 at $0.80/GPU-hr; "
          "mailroom-dataset @ ed7576b6, seed 42.",
    findings=["2×L4 at C32 raises throughput +99% at +0.4% cost per document."],
    provenance={"dataset_revision": "ed7576b6", "draw_seed": "42",
                "serving_kind": "modal", "cost_basis": "busy_window"},
    figures={"Throughput": "figures/1x-vs-2xL4-throughput.png"},
    appendix_url="SAND-37-MASTER-APPENDIX.md",
)
```

`grid_scorecard(...)` returns the same content as JSON-friendly dicts when a
machine-readable artifact is wanted.

## Aggregations

| Block | Function | Columns |
|---|---|---|
| Quality / cost by specialist | `specialist_grid_rows` | score (+ coverage when present), `ok / n`, p50 latency, busy GPU `$` / ok doc |
| Pooled serving efficiency | `serving_efficiency_rows` | error rate, documents/min, tokens/s/GPU, GPU `$`/doc |
| Session cost | `session_cost_rows` | busy-window GPU, metered session, busy share, metered/doc, billed |

## Honesty rules

- `serving_kind` stays `local` / `modal` / `api`; `modal-vllm` normalizes to
  `modal`, never to `local`.
- Busy-window numbers are labeled `cost_basis="busy_window"`; metered numbers
  are `billed_incl_cold`. Missing inputs render `n/a` — a metered per-document
  figure is never estimated.
- One row must carry one `metric_id`; mixing CUAD micro-F1 with MAUD accuracy
  raises instead of averaging two scales (#17).
- `ok` comes from the per-document records; errors are read from explicit
  `error` / `error_class` fields (the `summarize_run_completion` contract).

## Compact layout

`build_grid_report(compact=True)` (default) renders one specialist row and
joins the per-experiment cells with `·`, matching the L4 tables.
`compact=False` emits one row per experiment × specialist.
