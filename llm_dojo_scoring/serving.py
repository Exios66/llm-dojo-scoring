"""Local vs API serving comparison — TTFT, throughput, utilization, identity.

Comparable LLM-serving metrics computed from recorded timings and token
counts (vLLM / NVIDIA NIM / OpenAI streaming conventions). Identity
fields (model, quantization, GPU, provider) are registered, not scored
as quality.

Honesty
-------
* **TTFT** is ``None`` unless a first-token timestamp or explicit
  ``ttft_seconds`` is present. Do not infer TTFT from e2e / n_tokens.
* **GPU / KV-cache utilization** are local-only. API-key providers
  (OpenRouter, …) cannot supply them — the comparison records that gap.
* **Local cost** is ``None`` when the model slug has no OpenRouter price
  table entry (Ollama tags like ``qwen3:8b``). Do not fabricate electricity.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .bootstrap import bootstrap_ci, delta_significance
from .cost import estimate_cost

__all__ = [
    "LOCAL_PROVIDERS",
    "API_PROVIDERS",
    "SERVING_METRIC_NAMES",
    "IDENTITY_FIELDS",
    "ServingIdentity",
    "ServingObservation",
    "ServingRun",
    "classify_serving_kind",
    "normalize_serving_record",
    "score_serving_run",
    "aggregate_serving",
    "compare_serving",
    "split_local_api",
    "pair_comparable_runs",
    "CANONICAL_SERVING_KEYS",
]

LOCAL_PROVIDERS = frozenset(
    {
        "ollama",
        "vllm",
        "vllm-local",
        "modal-vllm",
        "llamacpp",
        "llama.cpp",
        "lmstudio",
        "lm-studio",
        "generic",
    }
)
API_PROVIDERS = frozenset(
    {
        "openrouter",
        "openai",
        "anthropic",
        "together",
        "groq",
        "fireworks",
        "deepseek",
        "mistral",
    }
)

# Registry names this module computes (T0/T1 serving surface).
SERVING_METRIC_NAMES: tuple[str, ...] = (
    "ttft_seconds",
    "tokens_per_second",
    "tpot_seconds",
    "e2e_latency_seconds",
    "ttft_p50",
    "ttft_p95",
    "e2e_p50",
    "e2e_p95",
    "output_tokens_per_second",
    "prompt_tokens_per_second",
    "requests_per_second",
    "docs_per_second",
    "gpu_utilization",
    "kv_cache_utilization",
    "gpu_memory_used_gb",
    "queue_time_seconds",
    "error_rate",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "cost_per_document",
)

IDENTITY_FIELDS: tuple[str, ...] = (
    "serving_kind",
    "provider",
    "model",
    "quantization",
    "dtype",
    "max_model_len",
    "gpu",
    "gpu_count",
    "tensor_parallel",
    "profile",
    "prompt_version",
    "task",
    "base_url_host",
)

#: Keys a comparable sandbox / experiment-log record should emit. Missing
#: timings stay ``None`` — they are never inferred from e2e / n_tokens.
CANONICAL_SERVING_KEYS: tuple[str, ...] = (
    "serving_kind",
    "provider",
    "profile",
    "model",
    "quantization",
    "dtype",
    "max_model_len",
    "gpu",
    "gpu_count",
    "tensor_parallel",
    "prompt_version",
    "task",
    "dataset_fingerprint",
    "base_url",
    "ttft_seconds",
    "t_start",
    "t_first_token",
    "t_end",
    "e2e_latency_seconds",
    "queue_time_seconds",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "gpu_utilization",
    "kv_cache_utilization",
    "gpu_memory_used_gb",
    "error",
    "n",
    "estimated_cost_usd",
    "scores",
    "requests",
)

_QUALITY_KEYS = (
    "extraction_f1",
    "f1_macro",
    "exact_match",
    "accuracy",
    "overall_extraction_score",
    "extraction_overall_score",
)


def _first(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
    if not mapping:
        return None
    for key in keys:
        if "." in key:
            cur: Any = mapping
            ok = True
            for part in key.split("."):
                if isinstance(cur, Mapping) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and cur not in (None, ""):
                return cur
            continue
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    num = _as_float(value)
    if num is None:
        return None
    return int(num)


def _as_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value).strip() or None


def _parse_ts(value: Any) -> float | None:
    """Unix seconds from a timestamp, ISO-8601 string, or numeric."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    num = _as_float(value)
    if num is not None:
        # Heuristic: ms since epoch
        if num > 1e12:
            return num / 1000.0
        return num
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _percentile(values: Sequence[float], p: float) -> float | None:
    """Linear interpolation percentile. ``p`` in ``[0, 1]``."""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return None
    xs.sort()
    if len(xs) == 1:
        return round(xs[0], 6)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    if lo == hi:
        return round(xs[lo], 6)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 6)


def _mean(values: Sequence[float | None]) -> float | None:
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return None
    return round(sum(xs) / len(xs), 6)


def _host(url: Any) -> str | None:
    text = _as_str(url)
    if not text:
        return None
    if "://" not in text:
        return text.split("/")[0].split(":")[0] or None
    return urlparse(text).hostname


def _frac(value: Any) -> float | None:
    """Normalize 0–1 or 0–100 utilization to ``[0, 1]``."""
    num = _as_float(value)
    if num is None:
        return None
    if num > 1.0:
        num = num / 100.0
    if num < 0:
        return None
    return round(min(num, 1.0), 6)


def classify_serving_kind(
    record: Mapping[str, Any] | None,
    *,
    provider: str | None = None,
) -> str:
    """``local`` | ``api`` | ``unknown`` from explicit field or provider family."""
    raw = _first(record or {}, "serving_kind", "serving.kind")
    if raw:
        token = str(raw).strip().lower()
        if token in {"local", "offline", "self-hosted", "on-prem"}:
            return "local"
        if token in {"api", "cloud", "hosted", "openrouter"}:
            return "api"
    prov = (provider or _as_str(_first(record or {}, "provider", "profile")) or "").lower()
    if prov in LOCAL_PROVIDERS or prov.startswith("ollama") or prov.startswith("vllm"):
        return "local"
    if prov in API_PROVIDERS or prov.startswith("openrouter"):
        return "api"
    profile = (_as_str(_first(record or {}, "profile")) or "").lower()
    if profile in LOCAL_PROVIDERS or profile.startswith("ollama") or profile in {
        "vllm-local",
        "modal-vllm",
        "llamacpp",
        "lmstudio",
    }:
        return "local"
    if profile in API_PROVIDERS or profile == "openrouter":
        return "api"
    return "unknown"


@dataclass(frozen=True)
class ServingIdentity:
    """Model / quantization / hardware identity for one serving run."""

    serving_kind: str = "unknown"
    provider: str | None = None
    model: str | None = None
    quantization: str | None = None
    dtype: str | None = None
    max_model_len: int | None = None
    gpu: str | None = None
    gpu_count: int | None = None
    tensor_parallel: int | None = None
    profile: str | None = None
    prompt_version: str | None = None
    task: str | None = None
    base_url_host: str | None = None
    dataset_fingerprint: str | None = None
    experiment_name: str | None = None
    n: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class ServingObservation:
    """One request's recorded timings / tokens / utilization."""

    ttft_seconds: float | None = None
    e2e_latency_seconds: float | None = None
    tpot_seconds: float | None = None
    queue_time_seconds: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    gpu_utilization: float | None = None
    kv_cache_utilization: float | None = None
    gpu_memory_used_gb: float | None = None
    error: bool = False


@dataclass
class ServingRun:
    identity: ServingIdentity
    observations: list[ServingObservation] = field(default_factory=list)
    scores: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    honest_gaps: list[str] = field(default_factory=list)


def _identity_from(record: Mapping[str, Any]) -> ServingIdentity:
    serving = record.get("serving") if isinstance(record.get("serving"), Mapping) else {}
    vllm = record.get("vllm") if isinstance(record.get("vllm"), Mapping) else {}
    merged: dict[str, Any] = {}
    merged.update(serving or {})
    merged.update(vllm or {})
    merged.update(dict(record))
    provider = _as_str(_first(merged, "provider", "DEFAULT_PROVIDER"))
    kind = classify_serving_kind(record, provider=provider)
    n = _as_int(_first(merged, "n", "n_rows", "n_docs"))
    return ServingIdentity(
        serving_kind=kind,
        provider=provider,
        model=_as_str(_first(merged, "model", "model_slug", "llm_model")),
        quantization=_as_str(
            _first(merged, "quantization", "quant", "serving.quantization", "vllm.quantization")
        ),
        dtype=_as_str(_first(merged, "dtype", "serving.dtype")),
        max_model_len=_as_int(
            _first(merged, "max_model_len", "max_model_length", "context_length")
        ),
        gpu=_as_str(_first(merged, "gpu", "gpu_name", "serving.gpu")),
        gpu_count=_as_int(_first(merged, "gpu_count", "tensor_parallel_size")),
        tensor_parallel=_as_int(_first(merged, "tensor_parallel", "tp", "tensor_parallel_size")),
        profile=_as_str(_first(merged, "profile", "SANDBOX_PROFILE")),
        prompt_version=_as_str(_first(merged, "prompt_version", "prompt")),
        task=_as_str(_first(merged, "task", "eval_task")),
        base_url_host=_host(_first(merged, "base_url", "VLLM_BASE_URL", "OLLAMA_BASE_URL")),
        dataset_fingerprint=_as_str(_first(merged, "dataset_fingerprint", "fingerprint")),
        experiment_name=_as_str(_first(merged, "experiment_name", "name", "run_id")),
        n=n,
    )


def _observation_from(row: Mapping[str, Any]) -> ServingObservation:
    tokens = row.get("tokens") if isinstance(row.get("tokens"), Mapping) else {}
    usage = row.get("usage") if isinstance(row.get("usage"), Mapping) else {}
    timings = row.get("timings") if isinstance(row.get("timings"), Mapping) else {}
    merged: dict[str, Any] = {}
    for part in (timings, tokens, usage, row):
        if isinstance(part, Mapping):
            merged.update(part)

    start = _parse_ts(
        _first(merged, "t_start", "start_ts", "request_start", "started_at")
    )
    first = _parse_ts(
        _first(merged, "t_first_token", "first_token_ts", "first_token_at")
    )
    end = _parse_ts(_first(merged, "t_end", "end_ts", "finished_at", "completed_at"))

    ttft = _as_float(
        _first(merged, "ttft_seconds", "ttft", "time_to_first_token")
    )
    if ttft is None and start is not None and first is not None:
        ttft = first - start
        if ttft < 0:
            ttft = None

    e2e = _as_float(
        _first(
            merged,
            "e2e_latency_seconds",
            "latency_seconds",
            "duration_seconds",
            "run_duration_seconds",
            "elapsed_seconds",
            "latency",
        )
    )
    if e2e is None and start is not None and end is not None:
        e2e = end - start
        if e2e < 0:
            e2e = None

    prompt_tok = _as_int(
        _first(merged, "prompt_tokens", "input_tokens", "prompt_token_count")
    )
    completion_tok = _as_int(
        _first(merged, "completion_tokens", "output_tokens", "completion_token_count")
    )
    total_tok = _as_int(_first(merged, "total_tokens"))
    if total_tok is None and prompt_tok is not None and completion_tok is not None:
        total_tok = prompt_tok + completion_tok

    tpot = _as_float(
        _first(merged, "tpot_seconds", "tpot", "time_per_output_token", "itl_seconds")
    )
    if tpot is None and ttft is not None and e2e is not None and completion_tok is not None:
        denom = completion_tok - 1
        if denom > 0 and e2e >= ttft:
            tpot = (e2e - ttft) / denom

    mem = _as_float(
        _first(merged, "gpu_memory_used_gb", "gpu_memory_gb", "mem_used_gb")
    )
    mem_mb = _as_float(_first(merged, "gpu_memory_used_mb"))
    if mem is None and mem_mb is not None:
        mem = mem_mb / 1024.0

    err = _first(merged, "error", "failed", "is_error")
    error = bool(err) if err not in (None, "", 0, "0") else False

    return ServingObservation(
        ttft_seconds=round(ttft, 6) if ttft is not None else None,
        e2e_latency_seconds=round(e2e, 6) if e2e is not None else None,
        tpot_seconds=round(tpot, 6) if tpot is not None else None,
        queue_time_seconds=_as_float(
            _first(merged, "queue_time_seconds", "queue_time", "waiting_time")
        ),
        prompt_tokens=prompt_tok,
        completion_tokens=completion_tok,
        total_tokens=total_tok,
        gpu_utilization=_frac(
            _first(merged, "gpu_utilization", "gpu_util", "nvidia.utilization")
        ),
        kv_cache_utilization=_frac(
            _first(merged, "kv_cache_utilization", "cache_usage", "prefix_cache_hit_rate")
        ),
        gpu_memory_used_gb=round(mem, 6) if mem is not None else None,
        error=error,
    )


def _request_rows(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("requests", "observations", "generations", "timings", "per_call"):
        val = record.get(key)
        if isinstance(val, list) and val and isinstance(val[0], Mapping):
            return list(val)
    return [record]


def normalize_serving_record(record: Mapping[str, Any] | ServingRun) -> ServingRun:
    """Normalize a sandbox / experiment-log / raw serving dict into a run."""
    if isinstance(record, ServingRun):
        return record
    identity = _identity_from(record)
    observations = [_observation_from(row) for row in _request_rows(record)]
    scores = record.get("scores") if isinstance(record.get("scores"), Mapping) else {}
    cost = _as_float(
        _first(record, "estimated_cost_usd", "cost_usd", "cost", "scores.estimated_cost_usd")
    )
    if cost is None:
        prompt = sum(o.prompt_tokens or 0 for o in observations) or None
        completion = sum(o.completion_tokens or 0 for o in observations) or None
        if prompt or completion:
            cost = estimate_cost(prompt, completion, identity.model)
    gaps: list[str] = []
    if not any(o.ttft_seconds is not None for o in observations):
        gaps.append("ttft_seconds missing — not inferred from e2e/n_tokens")
    if identity.serving_kind == "api":
        # API-key providers cannot supply GPU / KV / VRAM — drop even if
        # a caller accidentally copied local hardware fields onto the record.
        observations = [
            replace(
                o,
                gpu_utilization=None,
                kv_cache_utilization=None,
                gpu_memory_used_gb=None,
            )
            for o in observations
        ]
        gaps.append("gpu_utilization unavailable on API-key providers")
        gaps.append("kv_cache_utilization unavailable on API-key providers")
    if cost is None and identity.serving_kind == "local":
        gaps.append("estimated_cost_usd unknown for local model slug (no price table)")
    return ServingRun(
        identity=identity,
        observations=observations,
        scores=dict(scores or {}),
        estimated_cost_usd=cost,
        honest_gaps=gaps,
    )


def _derived(obs: ServingObservation) -> dict[str, float | None]:
    e2e = obs.e2e_latency_seconds
    ttft = obs.ttft_seconds
    prompt = obs.prompt_tokens
    completion = obs.completion_tokens
    tokens_per_sec = None
    if e2e and e2e > 0 and completion:
        tokens_per_sec = completion / e2e
    output_tps = None
    decode = None
    if ttft is not None and e2e is not None and e2e > ttft:
        decode = e2e - ttft
    if decode and decode > 0 and completion:
        output_tps = completion / decode
    prompt_tps = None
    if ttft and ttft > 0 and prompt:
        prompt_tps = prompt / ttft
    return {
        "tokens_per_second": round(tokens_per_sec, 6) if tokens_per_sec is not None else None,
        "output_tokens_per_second": round(output_tps, 6) if output_tps is not None else None,
        "prompt_tokens_per_second": round(prompt_tps, 6) if prompt_tps is not None else None,
    }


def score_serving_run(run: Mapping[str, Any] | ServingRun) -> dict[str, Any]:
    """Aggregate serving metrics for one local or API run."""
    return aggregate_serving([run])


def aggregate_serving(
    runs: Iterable[Mapping[str, Any] | ServingRun],
) -> dict[str, Any]:
    """Mean + p50/p95 over every observation in ``runs``."""
    normalized = [normalize_serving_record(r) for r in runs]
    obs: list[ServingObservation] = []
    for run in normalized:
        obs.extend(run.observations)
    ttfts = [o.ttft_seconds for o in obs]
    e2es = [o.e2e_latency_seconds for o in obs]
    tpots = [o.tpot_seconds for o in obs]
    queues = [o.queue_time_seconds for o in obs]
    derived = [_derived(o) for o in obs]
    n_req = len(obs)
    n_err = sum(1 for o in obs if o.error)
    prompt_sum = sum(o.prompt_tokens or 0 for o in obs)
    completion_sum = sum(o.completion_tokens or 0 for o in obs)
    total_sum = sum(
        (o.total_tokens if o.total_tokens is not None else (o.prompt_tokens or 0) + (o.completion_tokens or 0))
        for o in obs
    )
    wall = _mean(e2es)
    rps = None
    if wall and wall > 0 and n_req:
        # requests / mean e2e approximates sequential throughput; when n
        # observations share one wall clock, prefer sum(e2e) as the window.
        window = sum(v for v in e2es if v is not None)
        if window and window > 0:
            rps = round(n_req / window, 6)
    docs = None
    n_docs = sum(r.identity.n or 0 for r in normalized) or n_req
    if wall and wall > 0 and n_docs:
        window = sum(v for v in e2es if v is not None) or (wall * n_req)
        if window > 0:
            docs = round(n_docs / window, 6)

    costs = [r.estimated_cost_usd for r in normalized]
    cost = _mean(costs)
    cost_per = None
    if cost is not None and n_docs:
        cost_per = round(cost / n_docs, 8) if len(normalized) == 1 else round(
            sum(c for c in costs if c is not None) / n_docs, 8
        )

    identities = [r.identity.as_dict() for r in normalized]
    gaps: list[str] = []
    for run in normalized:
        for gap in run.honest_gaps:
            if gap not in gaps:
                gaps.append(gap)

    quality: dict[str, Any] = {}
    for key in _QUALITY_KEYS:
        vals = []
        for run in normalized:
            v = run.scores.get(key)
            num = _as_float(v)
            if num is not None:
                vals.append(num)
        if vals:
            quality[key] = _mean(vals)

    return {
        "n_requests": n_req,
        "n_runs": len(normalized),
        "n_docs": n_docs,
        "identity": identities[0] if len(identities) == 1 else identities,
        "ttft_seconds": _mean(ttfts),
        "ttft_p50": _percentile([v for v in ttfts if v is not None], 0.50),
        "ttft_p95": _percentile([v for v in ttfts if v is not None], 0.95),
        "tpot_seconds": _mean(tpots),
        "e2e_latency_seconds": _mean(e2es),
        "e2e_p50": _percentile([v for v in e2es if v is not None], 0.50),
        "e2e_p95": _percentile([v for v in e2es if v is not None], 0.95),
        "queue_time_seconds": _mean(queues),
        "tokens_per_second": _mean([d["tokens_per_second"] for d in derived]),
        "output_tokens_per_second": _mean([d["output_tokens_per_second"] for d in derived]),
        "prompt_tokens_per_second": _mean([d["prompt_tokens_per_second"] for d in derived]),
        "requests_per_second": rps,
        "docs_per_second": docs,
        "gpu_utilization": _mean([o.gpu_utilization for o in obs]),
        "kv_cache_utilization": _mean([o.kv_cache_utilization for o in obs]),
        "gpu_memory_used_gb": _mean([o.gpu_memory_used_gb for o in obs]),
        "error_rate": round(n_err / n_req, 6) if n_req else None,
        "prompt_tokens": prompt_sum or None,
        "completion_tokens": completion_sum or None,
        "total_tokens": total_sum or None,
        "estimated_cost_usd": cost,
        "cost_per_document": cost_per,
        "ttft_ci": bootstrap_ci([v for v in ttfts if v is not None]),
        "e2e_ci": bootstrap_ci([v for v in e2es if v is not None]),
        "quality": quality,
        "honest_gaps": gaps,
    }


def _delta_map(local: Mapping[str, Any], api: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SERVING_METRIC_NAMES:
        a = _as_float(local.get(key))
        b = _as_float(api.get(key))
        if a is None and b is None:
            continue
        delta = None if a is None or b is None else round(a - b, 6)
        ratio = None
        if a is not None and b is not None and b != 0:
            ratio = round(a / b, 6)
        out[key] = {"local": a, "api": b, "delta_local_minus_api": delta, "ratio_local_over_api": ratio}
    return out


def compare_serving(
    local: Mapping[str, Any] | ServingRun | Sequence[Any],
    api: Mapping[str, Any] | ServingRun | Sequence[Any],
    *,
    quality_metric: str | None = None,
) -> dict[str, Any]:
    """Compare a local serving run (or list) against an API-key run.

    ``delta_local_minus_api`` is signed: negative TTFT means local is faster.
    GPU/KV metrics stay ``None`` on the API side rather than being zero-filled.
    """
    local_runs: Sequence[Any] = (
        local if isinstance(local, Sequence) and not isinstance(local, (str, bytes, Mapping, ServingRun))
        else [local]
    )
    api_runs: Sequence[Any] = (
        api if isinstance(api, Sequence) and not isinstance(api, (str, bytes, Mapping, ServingRun))
        else [api]
    )
    left = aggregate_serving(local_runs)
    right = aggregate_serving(api_runs)

    quality_key = quality_metric
    if quality_key is None:
        shared = set(left.get("quality") or {}) & set(right.get("quality") or {})
        for cand in _QUALITY_KEYS:
            if cand in shared:
                quality_key = cand
                break

    quality_block: dict[str, Any] | None = None
    if quality_key:
        lv = (left.get("quality") or {}).get(quality_key)
        rv = (right.get("quality") or {}).get(quality_key)
        quality_block = {
            "metric": quality_key,
            "local": lv,
            "api": rv,
            "delta_local_minus_api": None if lv is None or rv is None else round(lv - rv, 6),
        }

    local_ttft = [
        o.ttft_seconds
        for r in (normalize_serving_record(x) for x in local_runs)
        for o in r.observations
        if o.ttft_seconds is not None
    ]
    api_ttft = [
        o.ttft_seconds
        for r in (normalize_serving_record(x) for x in api_runs)
        for o in r.observations
        if o.ttft_seconds is not None
    ]
    local_e2e = [
        o.e2e_latency_seconds
        for r in (normalize_serving_record(x) for x in local_runs)
        for o in r.observations
        if o.e2e_latency_seconds is not None
    ]
    api_e2e = [
        o.e2e_latency_seconds
        for r in (normalize_serving_record(x) for x in api_runs)
        for o in r.observations
        if o.e2e_latency_seconds is not None
    ]

    gaps = list(left.get("honest_gaps") or [])
    for gap in right.get("honest_gaps") or []:
        if gap not in gaps:
            gaps.append(gap)

    return {
        "local": left,
        "api": right,
        "metrics": _delta_map(left, right),
        "quality": quality_block,
        "ttft_delta": delta_significance(api_ttft, local_ttft),
        "e2e_delta": delta_significance(api_e2e, local_e2e),
        "honest_gaps": gaps,
    }


def split_local_api(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Partition experiment-log records into local, api, and unknown."""
    local: list[Mapping[str, Any]] = []
    api: list[Mapping[str, Any]] = []
    unknown: list[Mapping[str, Any]] = []
    for rec in records:
        kind = classify_serving_kind(rec)
        if kind == "local":
            local.append(rec)
        elif kind == "api":
            api.append(rec)
        else:
            unknown.append(rec)
    return local, api, unknown


def pair_comparable_runs(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Pair local/api records that share task + prompt + dataset fingerprint."""
    local, api, _ = split_local_api(records)

    def _key(rec: Mapping[str, Any]) -> tuple[Any, ...]:
        ident = _identity_from(rec)
        return (ident.task, ident.prompt_version, ident.dataset_fingerprint)

    api_by: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for rec in api:
        api_by.setdefault(_key(rec), []).append(rec)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for rec in local:
        bucket = api_by.get(_key(rec)) or []
        if bucket:
            pairs.append((rec, bucket.pop(0)))
    return pairs
