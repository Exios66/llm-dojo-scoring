"""Local vs API serving comparison (v0.12.0). Network-free."""

from __future__ import annotations

import pytest

from llm_dojo_scoring import (
    compare_serving,
    get_suite,
    score_serving_run,
    split_local_api,
)
from llm_dojo_scoring.pruning import dashboard_metrics, headline_metrics
from llm_dojo_scoring.registry import MetricTier, expand_agent_families, load_registry
from llm_dojo_scoring.serving import (
    CANONICAL_SERVING_KEYS,
    classify_serving_kind,
    pair_comparable_runs,
)


def test_ttft_from_timestamps():
    run = score_serving_run(
        {
            "provider": "ollama",
            "model": "qwen3:8b",
            "quantization": "q4_k_m",
            "t_start": 1_700_000_000.0,
            "t_first_token": 1_700_000_000.4,
            "t_end": 1_700_000_002.4,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
    )
    assert run["ttft_seconds"] == pytest.approx(0.4)
    assert run["e2e_latency_seconds"] == pytest.approx(2.4)
    assert run["tpot_seconds"] == pytest.approx((2.4 - 0.4) / 49)
    assert run["tokens_per_second"] == pytest.approx(50 / 2.4)
    assert run["output_tokens_per_second"] == pytest.approx(50 / 2.0)
    assert run["prompt_tokens_per_second"] == pytest.approx(100 / 0.4)
    assert run["identity"]["serving_kind"] == "local"
    assert run["identity"]["quantization"] == "q4_k_m"
    assert run["identity"]["model"] == "qwen3:8b"


def test_ttft_none_when_missing_not_inferred_from_e2e():
    run = score_serving_run(
        {
            "provider": "ollama",
            "model": "qwen3:8b",
            "e2e_latency_seconds": 3.0,
            "completion_tokens": 60,
        }
    )
    assert run["ttft_seconds"] is None
    assert run["tpot_seconds"] is None
    assert run["output_tokens_per_second"] is None
    assert run["tokens_per_second"] == pytest.approx(20.0)
    assert any("ttft" in g for g in run["honest_gaps"])


def test_explicit_ttft_seconds_used():
    run = score_serving_run(
        {
            "provider": "vllm",
            "ttft_seconds": 0.12,
            "e2e_latency_seconds": 1.12,
            "completion_tokens": 21,
        }
    )
    assert run["ttft_seconds"] == pytest.approx(0.12)
    assert run["tpot_seconds"] == pytest.approx(1.0 / 20)


def test_gpu_utilization_percent_normalized_and_stripped_on_api():
    local = score_serving_run(
        {
            "provider": "vllm",
            "gpu_utilization": 85,
            "kv_cache_utilization": 0.4,
            "gpu_memory_used_mb": 2048,
        }
    )
    assert local["gpu_utilization"] == pytest.approx(0.85)
    assert local["kv_cache_utilization"] == pytest.approx(0.4)
    assert local["gpu_memory_used_gb"] == pytest.approx(2.0)

    api = score_serving_run(
        {
            "provider": "openrouter",
            "model": "qwen/qwen3-8b",
            "gpu_utilization": 0.9,
            "kv_cache_utilization": 0.5,
            "gpu_memory_used_gb": 8.0,
            "e2e_latency_seconds": 1.0,
        }
    )
    assert api["gpu_utilization"] is None
    assert api["kv_cache_utilization"] is None
    assert api["gpu_memory_used_gb"] is None
    assert any("gpu_utilization" in g for g in api["honest_gaps"])


def test_local_ollama_cost_is_none():
    run = score_serving_run(
        {
            "provider": "ollama",
            "model": "qwen3:8b",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "e2e_latency_seconds": 2.0,
        }
    )
    assert run["estimated_cost_usd"] is None
    assert any("estimated_cost_usd" in g for g in run["honest_gaps"])


def test_compare_serving_deltas_and_identity():
    local = {
        "provider": "ollama",
        "model": "qwen3:8b",
        "quantization": "q4_k_m",
        "gpu": "RTX 4090",
        "ttft_seconds": 0.5,
        "e2e_latency_seconds": 2.5,
        "completion_tokens": 100,
        "gpu_utilization": 0.7,
        "scores": {"extraction_f1": 0.80},
    }
    api = {
        "provider": "openrouter",
        "model": "qwen/qwen3-8b",
        "ttft_seconds": 0.2,
        "e2e_latency_seconds": 1.0,
        "completion_tokens": 100,
        "scores": {"extraction_f1": 0.82},
    }
    out = compare_serving(local, api)
    assert out["metrics"]["ttft_seconds"]["local"] == pytest.approx(0.5)
    assert out["metrics"]["ttft_seconds"]["api"] == pytest.approx(0.2)
    assert out["metrics"]["ttft_seconds"]["delta_local_minus_api"] == pytest.approx(0.3)
    assert out["metrics"]["ttft_seconds"]["ratio_local_over_api"] == pytest.approx(2.5)
    assert out["metrics"]["gpu_utilization"]["local"] == pytest.approx(0.7)
    assert out["metrics"]["gpu_utilization"]["api"] is None
    assert out["metrics"]["gpu_utilization"]["delta_local_minus_api"] is None
    assert out["quality"]["metric"] == "extraction_f1"
    assert out["quality"]["delta_local_minus_api"] == pytest.approx(-0.02)
    assert out["local"]["identity"]["quantization"] == "q4_k_m"
    assert out["local"]["identity"]["gpu"] == "RTX 4090"
    assert out["api"]["identity"]["serving_kind"] == "api"
    assert out["ttft_delta"] is None  # n=1 per side — unmeasurable, not 0.0


def test_split_and_pair_comparable_runs():
    records = [
        {
            "provider": "ollama",
            "task": "sorter",
            "prompt_version": "sorter_v14",
            "dataset_fingerprint": "abc",
            "ttft_seconds": 0.4,
        },
        {
            "provider": "openrouter",
            "task": "sorter",
            "prompt_version": "sorter_v14",
            "dataset_fingerprint": "abc",
            "ttft_seconds": 0.2,
        },
        {"provider": "mystery", "task": "sorter"},
    ]
    local, api, unknown = split_local_api(records)
    assert len(local) == 1 and len(api) == 1 and len(unknown) == 1
    pairs = pair_comparable_runs(records)
    assert len(pairs) == 1
    assert classify_serving_kind(pairs[0][0]) == "local"
    assert classify_serving_kind(pairs[0][1]) == "api"


def test_get_suite_local_vs_api_routes_to_compare():
    suite = get_suite("local_vs_api")
    assert suite.kind == "serving"
    assert suite.computable is True
    assert suite.profile.ground_truth is False
    assert "ttft_seconds" in suite.headline_names()
    assert "tokens_per_second" in suite.headline_names()
    assert suite.honest_gap and "TTFT" in suite.honest_gap
    local = {"provider": "vllm-local", "ttft_seconds": 0.3, "e2e_latency_seconds": 1.3}
    api = {"provider": "openrouter", "ttft_seconds": 0.1, "e2e_latency_seconds": 0.8}
    out = suite.score(local, api)
    assert out["metrics"]["ttft_seconds"]["delta_local_minus_api"] == pytest.approx(0.2)


def test_serving_metrics_do_not_apply_to_sorter():
    reg = load_registry()
    assert not reg.get("ttft_seconds").applies_to("sorter")
    assert not reg.get("gpu_utilization").applies_to("sorter")
    assert reg.get("ttft_seconds").applies_to("local_vs_api")
    assert headline_metrics("sorter") == ["accuracy", "f1_macro"]
    assert "ttft_seconds" not in dashboard_metrics("sorter")
    assert "ttft_seconds" in headline_metrics("local_vs_api")
    assert "tokens_per_second" in headline_metrics("local_vs_api")


def test_serving_t0_t1_have_citation_and_ground_truth_none():
    reg = load_registry()
    for name in (
        "ttft_seconds",
        "tokens_per_second",
        "tpot_seconds",
        "e2e_latency_seconds",
        "gpu_utilization",
        "kv_cache_utilization",
        "docs_per_second",
    ):
        m = reg.get(name)
        assert m.tier <= MetricTier.CORE, name
        assert m.citation.strip(), name
        assert m.inclusion.strip(), name
        assert m.ground_truth == "none", name
        assert m.source.startswith("serving."), name


def test_identity_tags_are_t3():
    reg = load_registry()
    for name in (
        "serving_kind",
        "quantization",
        "gpu_name",
        "max_model_len",
        "model",
        "provider",
        "dtype",
    ):
        assert reg.get(name).tier is MetricTier.LOG, name
        assert reg.get(name).applies_to("local_vs_api")


def test_expand_serving_family():
    assert "local_vs_api" in expand_agent_families(["SERVING"])


def test_canonical_keys_document_ttft_and_quantization():
    assert "ttft_seconds" in CANONICAL_SERVING_KEYS
    assert "quantization" in CANONICAL_SERVING_KEYS
    assert "gpu_utilization" in CANONICAL_SERVING_KEYS


def test_multi_request_percentiles():
    run = score_serving_run(
        {
            "provider": "vllm",
            "requests": [
                {"ttft_seconds": 0.1, "e2e_latency_seconds": 1.0, "completion_tokens": 10},
                {"ttft_seconds": 0.2, "e2e_latency_seconds": 2.0, "completion_tokens": 20},
                {"ttft_seconds": 0.3, "e2e_latency_seconds": 3.0, "completion_tokens": 30},
            ],
        }
    )
    assert run["n_requests"] == 3
    assert run["ttft_seconds"] == pytest.approx(0.2)
    assert run["ttft_p50"] == pytest.approx(0.2)
    assert run["error_rate"] == 0.0


def test_kind_field_is_not_used_for_serving_kind():
    """Bare ``kind`` is too ambiguous (doc class, task kind, …)."""
    assert classify_serving_kind({"kind": "local", "provider": "mystery"}) == "unknown"
    assert classify_serving_kind({"serving_kind": "local"}) == "local"
    assert classify_serving_kind({"serving": {"kind": "api"}}) == "api"
