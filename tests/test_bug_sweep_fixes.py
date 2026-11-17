"""Regressions for the docs/plans/BUG_SWEEP.md items fixed before 0.26.0."""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.pipeline.archive import (
    ARCHIVE_SCORING_METHOD,
    ARCHIVE_SCORING_METHOD_CMS,
    score_archive_block,
)
from llm_dojo_scoring.schemas.gt_metadata import is_empty_value
from llm_dojo_scoring.schemas.scored_enums import scored_enum_schema
from llm_dojo_scoring.scoring.field_scoring import (
    _cms_doc_signature,
    expected_cms_source_table,
    score_extraction,
)

_CMS = {
    "claim_type": "health",
    "claim_number": "887013387879564",
    "denial_reasons": "",
    "supporting_documents": '["provider NPI 5040521237"]',
}


def test_stray_table_key_on_a_non_health_row_is_not_cms():
    """A product-line GT other than health never switches on CMS rules."""
    assert expected_cms_source_table("insurance_claim", {"claim_type": "auto", "cms_source_table": "pde"}) is None
    assert expected_cms_source_table("insurance_claim", {"claim_type": "health", "cms_source_table": "pde"}) == "pde"
    assert expected_cms_source_table("insurance_claim", {"cms_source_table": "pde"}) == "pde"


def test_missing_adjuster_key_is_still_documented_absent_on_cms_rows():
    """A CMS GT that omits ``adjuster`` still scores a stated adjuster as wrong."""
    exp = {**_CMS, "cms_source_table": "carrier"}
    stated = score_extraction("insurance_claim", {}, {**exp, "adjuster": "JOHN D."}, exp)
    assert stated.field_scores["adjuster"] == 0.0
    silent = score_extraction("insurance_claim", {}, dict(exp), exp)
    assert "adjuster" not in silent.field_scores  # no free credit for omitted GT


@pytest.mark.parametrize(
    ("text", "ndc"),
    [
        ("NDC 0002-3227-30", "00002322730"),  # 4-4-2
        ("NDC 12345-678-90", "12345067890"),  # 5-3-2
        ("NDC 12345-6789-1", "12345678901"),  # 5-4-1
        ("NDC 00703-0510-02", "00703051002"),  # already 5-4-2
        ("NDC 00703051002", "00703051002"),
    ],
)
def test_ndc_segments_pad_to_5_4_2(text, ndc):
    """Each hyphenated segment is padded, not the whole number."""
    assert _cms_doc_signature(text) == ("ndc", ndc)


def test_cms_archive_block_names_its_rubric():
    """A CMS block says documented-absent fields joined the mean; others keep the default."""
    cms = score_archive_block("insurance_claim", dict(_CMS), dict(_CMS), expected_subclass="pde")
    assert cms["method"] == ARCHIVE_SCORING_METHOD_CMS
    assert cms["provenance"]["metric_id"] == "pipeline.extraction.overall"
    plain = score_archive_block("insurance_claim", dict(_CMS), dict(_CMS), expected_subclass="auto")
    assert plain["method"] == ARCHIVE_SCORING_METHOD


def test_numpy_subclass_array_is_per_row():
    """A NumPy subclass array is read per row, not stringified or truth-tested."""
    suite = get_suite("insurance_claims_specialist")
    rows = [dict(_CMS), dict(_CMS)]
    # Row 0 states an adjuster (wrong on a CMS row); row 1 names the wrong table
    # (wrong only if row 1 were CMS). Each per-row reading scores differently.
    preds = [{**_CMS, "cms_source_table": "pde", "adjuster": "JOHN D."},
             {**_CMS, "cms_source_table": "carrier"}]

    def score(subclass):
        """Batch extraction score and precision under one subclass reading."""
        out = suite.score(rows, preds, expected_subclass=subclass)
        return out["extraction"], out["extraction_precision"]

    array = score(np.array(["pde", "auto"]))
    assert array == score(["pde", "auto"])
    assert array != score(["auto", "auto"])  # row 0 must be CMS
    assert array != score(["pde", "pde"])  # row 1 must not be


def test_scalar_subclass_does_not_mark_every_batch_row_cms():
    """A scalar subclass on a batch is not broadcast into CMS mode."""
    suite = get_suite("insurance_claims_specialist")
    rows = [dict(_CMS), {**_CMS, "claim_type": "auto"}]
    preds = [dict(_CMS), {**_CMS, "claim_type": "auto", "adjuster": "JOHN D."}]
    scalar = suite.score(rows, preds, expected_subclass="pde")
    per_row = suite.score(rows, preds, expected_subclass=[None, None])
    assert scalar["extraction"] == per_row["extraction"]
    assert scalar["extraction_precision"] == per_row["extraction_precision"]


@pytest.mark.parametrize("value", ["nan", "NaN", " nan ", float("nan")])
def test_nan_is_empty(value):
    """Pandas ``nan`` cells are absent, never an expected value."""
    assert is_empty_value(value)
    assert not is_empty_value("nana")
    assert not math.isnan(0.0) and not is_empty_value(0.0)


@pytest.mark.parametrize("nullable", [True, False])
def test_enum_fragment_has_a_type(nullable):
    """Strict structured-output decoders need ``type`` beside ``enum``."""
    fragment = scored_enum_schema("insurance_claim", "claim_type", nullable=nullable)
    assert fragment["type"] == (["string", "null"] if nullable else "string")
    assert json.loads(json.dumps(fragment)) == fragment


