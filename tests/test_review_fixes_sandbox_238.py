"""Regressions for the review findings raised on the sandbox's v0.26.0 vendor bump (#238)."""

from __future__ import annotations

import json
import math

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.analysis import calibration
from llm_dojo_scoring.analysis.grid import _cell
from llm_dojo_scoring.metrics.emitter import _emit_provenance
from llm_dojo_scoring.metrics.scorecard_honesty import ProvenanceExportError
from llm_dojo_scoring.scoring.rescore import RescoreError, rescore_file, rescore_records

PROV = {
    "dataset_revision": "r1",
    "prompt_id": "p1",
    "serving_kind": "modal",
    "model_id": "m1",
}


def test_required_samples_tiny_risk_returns_none_instead_of_dividing_by_zero():
    """``1 - 1e-17`` rounds to 1.0; log1p keeps the denominator nonzero."""
    assert calibration.required_samples(0, risk=1e-17) is None


def test_required_samples_zero_errors_respects_the_cap():
    """Zero errors needing more than the cap of accepts is ``None``, as documented."""
    assert calibration.required_samples(0, risk=1e-7) is None
    assert calibration.required_samples(0, risk=0.01) == 299


def test_wilson_lower_is_unrounded():
    """The target decision uses the exact bound, not ``wilson_ci``'s rounded ``lo``."""
    exact = calibration._wilson_lower(0.95, 400, 1.96)
    rounded = calibration.wilson_ci(0.95, 400, z=1.96)["lo"]
    assert exact != rounded and abs(exact - rounded) < 1e-4
    # A target between the exact and the rounded bound must not be met.
    target = (exact + rounded) / 2
    assert (exact >= target) != (rounded >= target)


def test_auroc_ignores_nan_scores():
    """NaN has no order; it is dropped rather than ranked arbitrarily."""
    with_nan = calibration.auroc([0.1, math.nan, 0.9, 0.5], [False, True, True, False])
    assert with_nan == calibration.auroc([0.1, 0.9, 0.5], [False, True, False])


def test_spearman_drops_nan_pairs():
    """A NaN on either axis removes that pair; too few pairs left is ``None``."""
    assert calibration.spearman([1, math.nan, 3, 4], [1, 2, 3, 4]) == calibration.spearman(
        [1, 3, 4], [1, 3, 4]
    )
    assert calibration.spearman([1, math.nan, 3], [1, 2, 3]) is None


@pytest.mark.parametrize("units", ["USD", "usd", "Usd"])
def test_usd_units_require_cost_basis_in_any_case(units):
    """The registry spells some cost units ``usd``; the basis check must still fire."""
    with pytest.raises(ProvenanceExportError, match="cost_basis"):
        _emit_provenance("reviewer_cost_per_accepted_usd", units, PROV, require=True)


def test_markdown_cell_escapes_html():
    """Untrusted names cannot inject raw HTML into the Markdown report."""
    assert _cell("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"


def test_rescore_records_skips_non_mapping_rows():
    """A ``None`` or list row is recorded as a skip instead of aborting the batch."""
    out = rescore_records([None, ["x"]])
    assert [s["index"] for s in out["skipped"]] == [0, 1]
    assert all("not an object" in s["reason"] for s in out["skipped"])


def test_rescore_file_refuses_to_overwrite_its_input(tmp_path):
    """``--out`` equal to ``--items`` would destroy the raw predictions."""
    items = tmp_path / "items.jsonl"
    original = json.dumps({"item_id": "a"}) + "\n"
    items.write_text(original, encoding="utf-8")
    with pytest.raises(RescoreError, match="must differ"):
        rescore_file(items, out_path=items)
    assert items.read_text(encoding="utf-8") == original


def test_batch_score_carries_headline_scope():
    """``ScoringSuite.score`` passes the class and field scores to the honest aggregate."""
    suite = get_suite("corporate_record")
    fields = list(suite.field_types)[:3]
    expected = {name: "Acme Corp" for name in fields}
    result = suite.score([expected, expected], [expected, {}])
    assert "headline_scope" in result
