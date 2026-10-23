"""Hand-computed controls for the sandbox's canonical chained rubric."""
import pytest
from llm_dojo_scoring.sandbox_composite import chained_composite


@pytest.mark.parametrize("sorter, extract, expected", [(1., 1., 1.), (1., 0., .25), (0., 1., .75), (0., 0., 0.), (1., .5, .625)])
def test_chained_weighted_policy(sorter, extract, expected):
    """Preserve the exact fixed quarter/three-quarter compatibility policy."""
    assert chained_composite(sorter, extract) == expected


@pytest.mark.parametrize("sorter, extract", [(None, 1.), (1., None), (None, None)])
def test_chained_missing_half_refuses_a_zero_sentinel(sorter, extract):
    """Missing support cannot produce a comparable composite score."""
    with pytest.raises(RuntimeError, match="chained eval: composite score cannot be derived"):
        chained_composite(sorter, extract)
