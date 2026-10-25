"""DMR-111: complete serving costs and producer-owned sorter token identity."""

import pytest

from llm_dojo_scoring.pilot_labels import normalize_sorter_token
from llm_dojo_scoring.serving import aggregate_serving


@pytest.mark.parametrize("costs,expected_total,expected_per_doc", [
    ([(1.25, 2), (None, 8)], None, None),
    ([(None, 2), (1.25, 8)], None, None),
    ([(0.0, 2), (None, 8)], None, None),
    ([(1.25, 2), (3.75, 8)], 5.0, 0.5),
    ([(0.0, 2), (0.0, 8)], 0.0, 0.0),
    ([(None, 2), (None, 8)], None, None),
    ([], None, None),
])
def test_serving_total_requires_every_run_cost(costs, expected_total, expected_per_doc):
    """Partial costs cannot price all ten documents; complete five-dollar cost can."""
    runs = [{"estimated_cost_usd": cost, "n": n, "cost_basis": "busy_window"}
            for cost, n in costs]
    result = aggregate_serving(runs)
    assert result["estimated_cost_usd"] == expected_total
    assert result["cost_per_document"] == expected_per_doc


@pytest.mark.parametrize("token", ["auto", "property", "liability", "health", "life", "workers_comp"])
def test_sorter_preserves_exact_producer_fnol_tokens(token):
    """The producer accepts these labels even when its corpus catalog is narrower."""
    catalog = {"auto", "property", "liability", "health", "life", "workers_comp", "other"}
    assert normalize_sorter_token("insurance_claim", token, catalog) == token


def test_sorter_preserves_contract_precedence_and_scoped_fallbacks():
    """Exact producer identity must not override CUAD normalization or unknown policy."""
    assert normalize_sorter_token("contract", "other", {"other", "license"}, contract_token="license") == "license"
    assert normalize_sorter_token("contract", "license", {"license"}) == "license"
    assert normalize_sorter_token("corporate_record", "BYLAWS", {"other", "bylaws"}) == "bylaws"
    assert normalize_sorter_token("corporate_record", "alien", {"other", "bylaws"}) == "other"
    assert normalize_sorter_token("correspondence", "alien", {"email"}) is None
    assert normalize_sorter_token("insurance_claim", " liability ", {"liability", "other"}) == "liability"
    assert normalize_sorter_token("insurance_claim", None, {"other"}) is None
    assert normalize_sorter_token("insurance_claim", "", {"other"}) is None
    assert normalize_sorter_token("insurance_claim", "liability", set()) is None


@pytest.mark.parametrize("known_cost", [1.25, 0.0])
@pytest.mark.parametrize("unknown_first", [False, True])
def test_comparison_cost_card_keeps_incomplete_priced_pool_unknown(known_cost, unknown_first):
    """Partial tokens cannot restore an unknown pooled cost or its cost basis."""
    from llm_dojo_scoring.serving import compare_serving

    runs = [
        {"provider": "openrouter", "model": "qwen/qwen3.7-flash", "n": 2,
         "prompt_tokens": 1000, "completion_tokens": 100,
         "estimated_cost_usd": known_cost, "cost_basis": "busy_window"},
        {"provider": "openrouter", "model": "qwen/qwen3.7-flash", "n": 8},
    ]
    if unknown_first:
        runs.reverse()
    comparison = compare_serving([], runs)
    assert comparison["api"]["n_docs"] == 10
    for block in (comparison["api"], comparison["cost"]["api"],
                  comparison["scorecard"]["cost"]["api"]):
        assert block["estimated_cost_usd"] is None
        assert block["cost_per_document"] is None
        assert block.get("cost_basis") is None


@pytest.mark.parametrize("record,expected,basis", [
    ({}, "token_estimate", "token_price_estimate"),
    ({"estimated_cost_usd": None}, None, None),
    ({"estimated_cost_usd": None, "cost_per_document": 0.25}, None, None),
    ({"estimated_cost_usd": 0.0, "cost_basis": "busy_window"}, 0.0, "busy_window"),
    ({"estimated_cost_usd": 0.25, "cost_basis": "busy_window"}, 0.25, "busy_window"),
])
def test_cost_card_respects_explicit_cost_and_retains_legacy_token_fallback(record, expected, basis):
    """Only a missing cost key permits legacy token pricing; known zero is a cost."""
    from llm_dojo_scoring.cost import estimate_cost
    from llm_dojo_scoring.serving import serving_cost_card

    aggregate = {"identity": {"model": "qwen/qwen3.7-flash", "provider": "openrouter"},
                 "prompt_tokens": 1000, "completion_tokens": 100, "n_docs": 10,
                 **record}
    if expected == "token_estimate":
        expected = estimate_cost(1000, 100, "qwen/qwen3.7-flash")
        assert expected is not None and expected > 0
    result = serving_cost_card(aggregate)
    assert result["estimated_cost_usd"] == expected
    assert result["cost_per_document"] == (None if expected is None else round(expected / 10, 8))
    assert result["cost_basis"] == basis


def test_comparison_prices_each_complete_token_run_before_pooling():
    """Complete priced token runs still produce the full total and document rate."""
    from llm_dojo_scoring.cost import estimate_cost
    from llm_dojo_scoring.serving import compare_serving

    runs = [{"provider": "openrouter", "model": "qwen/qwen3.7-flash", "n": n,
             "prompt_tokens": prompt, "completion_tokens": completion}
            for n, prompt, completion in [(2, 1000, 100), (8, 3000, 300)]]
    expected = sum(estimate_cost(run["prompt_tokens"], run["completion_tokens"], run["model"])
                   for run in runs)
    comparison = compare_serving([], runs)
    for block in (comparison["api"], comparison["cost"]["api"]):
        assert block["estimated_cost_usd"] == expected
        assert block["cost_per_document"] == round(expected / 10, 8)
        assert block["cost_basis"] == "token_price_estimate"


@pytest.mark.parametrize("costs,bases,expected_basis", [
    ([1.0, None], ["busy_window", "busy_window"], None),
    ([0.0, 0.0], ["busy_window", "busy_window"], "busy_window"),
    ([1.0, 2.0], ["busy_window", "busy_window"], "busy_window"),
    ([1.0, 2.0], ["busy_window", "billed_incl_cold"], None),
    ([1.0, 2.0], ["busy_window", None], None),
])
def test_pooled_cost_basis_requires_complete_uniform_labeled_costs(costs, bases, expected_basis):
    """A pooled basis describes every known run total and cannot label partial costs."""
    runs = [{"estimated_cost_usd": cost, "cost_basis": basis, "n": 1}
            for cost, basis in zip(costs, bases)]
    assert aggregate_serving(runs).get("cost_basis") == expected_basis
