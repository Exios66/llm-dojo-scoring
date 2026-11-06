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


# ---- review follow-ups on #114 ------------------------------------------------


def test_required_samples_tiny_risk_hits_the_cap_without_overflow():
    """``risk=1e-308`` would overflow ``math.ceil``; past the cap it is ``None``."""
    from llm_dojo_scoring.analysis.calibration import required_samples

    assert required_samples(0, risk=1e-308) is None
    assert required_samples(0, risk=0.01) == 299


def test_auroc_accepts_numpy_scalars():
    """numpy float32 / int64 scores are real numbers and are ranked."""
    import numpy as np

    from llm_dojo_scoring.analysis.calibration import auroc

    labels = [True, False, True, False]
    plain = auroc([0.9, 0.1, 0.8, 0.2], labels)
    assert auroc([np.float32(v) for v in (0.9, 0.1, 0.8, 0.2)], labels) == plain == 1.0
    assert auroc([np.int64(v) for v in (9, 1, 8, 2)], labels) == 1.0


def test_spearman_keeps_large_integers_distinct():
    """Integers above 2**53 stay distinct when ranked."""
    from llm_dojo_scoring.analysis.calibration import spearman

    big = 2**53
    assert spearman([big, big + 1, big + 2, big + 3], [1, 2, 3, 4]) == 1.0


def test_rescore_file_refuses_a_hard_link_to_the_items(tmp_path):
    """A hard link to the items file is the same file: refuse before truncating it."""
    import os

    from llm_dojo_scoring.scoring.rescore import RescoreError, rescore_file

    items = tmp_path / "items.jsonl"
    items.write_text("{}\n")
    link = tmp_path / "alias.jsonl"
    os.link(items, link)
    with pytest.raises(RescoreError, match="must differ"):
        rescore_file(items, out_path=link)
    assert items.read_text() == "{}\n"


def test_rescore_file_replaces_the_output_without_touching_a_linked_inode(tmp_path, monkeypatch):
    """The output is renamed into place, so a hard link made after the check survives."""
    import os

    from llm_dojo_scoring.scoring import rescore

    items = tmp_path / "items.jsonl"
    items.write_text("{}\n")
    out = tmp_path / "out.jsonl"
    real = rescore.rescore_records

    def link_then_score(*args, **kwargs):
        os.link(items, out)  # the race: the target becomes the items after the check
        return real(*args, **kwargs)

    monkeypatch.setattr(rescore, "rescore_records", link_then_score)
    rescore.rescore_file(items, out_path=out)
    assert items.read_text() == "{}\n"
    assert not out.samefile(items)


def test_rank_correlations_take_integers_beyond_float_range():
    """Huge integers neither overflow the NaN check nor merge when ranked."""
    from llm_dojo_scoring.analysis.calibration import auroc, spearman

    huge = 10**400
    assert spearman([huge, huge + 1, huge + 2], [1, 2, 3]) == 1.0
    assert auroc([huge + 1, huge], [True, False]) == 1.0
