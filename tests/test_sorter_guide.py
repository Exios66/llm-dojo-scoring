"""Sorter subclass guide: keys a sorter may emit, their corpus meaning, unannotated labels."""

from __future__ import annotations

import llm_dojo_scoring as dojo
from llm_dojo_scoring.schemas.corpus import CORPUS_SUBCLASS_SURFACES, DOC_TYPE_SUBCLASSES
from llm_dojo_scoring.schemas.sorter_guide import (
    CORRESPONDENCE_SUBCLASS_PRECEDENCE,
    SORTER_SUBCLASS_GUIDE,
    format_sorter_subclass_guide,
    sorter_subclass_keys,
    subclass_scorable,
)
from llm_dojo_scoring.scoring.tasks import score_task

LIVE = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")


def test_every_emittable_key_has_a_meaning():
    """Every emittable key has a meaning."""
    for kind in LIVE:
        keys = sorter_subclass_keys(kind)
        assert keys
        assert set(keys) == set(SORTER_SUBCLASS_GUIDE[kind]), kind


def test_every_ground_truth_label_is_emittable():
    """Every ground truth label is emittable."""
    for kind in ("corporate_record", "correspondence", "insurance_claim", "merger_agreement"):
        assert set(CORPUS_SUBCLASS_SURFACES[kind]) <= set(sorter_subclass_keys(kind)), kind


def test_certificate_of_formation_is_scoring_only():
    """Certificate of formation is scoring only."""
    assert "certificate_of_formation" in DOC_TYPE_SUBCLASSES["corporate_record"]
    assert "certificate_of_formation" not in sorter_subclass_keys("corporate_record")
    assert "certificate of formation" in SORTER_SUBCLASS_GUIDE["corporate_record"]["articles_of_incorporation"]


def test_correspondence_keys_follow_the_corpus_precedence():
    """Correspondence keys follow the corpus precedence."""
    assert sorter_subclass_keys("correspondence") == CORRESPONDENCE_SUBCLASS_PRECEDENCE
    assert CORRESPONDENCE_SUBCLASS_PRECEDENCE[-1] == "email"


def test_insurance_adds_the_fnol_lines():
    """Insurance adds the fnol lines."""
    keys = sorter_subclass_keys("insurance_claim")
    assert keys[:6] == DOC_TYPE_SUBCLASSES["insurance_claim"]
    assert {"liability", "health", "life", "workers_comp", "other"} <= set(keys)


def test_v14_confusions_are_named_in_the_guide():
    """V14 confusions are named in the guide."""
    guide = SORTER_SUBCLASS_GUIDE
    assert "PHYSICIAN/SUPPLIER" in guide["insurance_claim"]["carrier"]
    assert "OUTPATIENT SERVICES" in guide["insurance_claim"]["outpatient"]
    assert "Certificate of Designation" in guide["corporate_record"]["officer_certificate"]
    assert "never rights_instrument" in guide["corporate_record"]["officer_certificate"]
    assert "Amendment" in guide["corporate_record"]["charter_amendment"]
    assert "bylaws adopted by the board" in guide["corporate_record"]["board_resolution"]
    assert "employment" in guide["contract"]["consulting"]
    assert "note purchase" in guide["contract"]["supply"]


def test_rendered_block_has_one_line_per_key():
    """Rendered block has one line per key."""
    block = format_sorter_subclass_guide("corporate_record")
    lines = block.splitlines()
    assert lines[0].startswith("- corporate_record (")
    assert len(lines) == 1 + len(sorter_subclass_keys("corporate_record"))
    assert format_sorter_subclass_guide("unknown") == ""
    assert format_sorter_subclass_guide("due_diligence") == ""


def test_merger_other_is_not_a_label():
    """Merger other is not a label."""
    assert not subclass_scorable("merger_agreement", "other")
    assert subclass_scorable("merger_agreement", "all_cash")
    assert subclass_scorable("contract", "other")
    assert not subclass_scorable("contract", "")
    assert not subclass_scorable("contract", None)


def test_docclass_skips_unannotated_merger_subclass():
    """Docclass skips unannotated merger subclass."""
    result = score_task(
        "docclass",
        ["merger_agreement", "merger_agreement", "contract"],
        ["merger_agreement", "merger_agreement", "contract"],
        expected_subclass=["other", "all_cash", "License_Agreements"],
        predicted_subclass=["all_cash", "all_cash", "license"],
    )
    assert result["n_subclass_scored"] == 2
    assert result["n_subclass_unannotated"] == 1
    assert result["subclass_accuracy"] == 1.0
    assert result["exact_match"] == 1.0
    assert "other" not in result["per_subclass"]


def test_docclass_unannotated_row_still_scores_the_class():
    """Docclass unannotated row still scores the class."""
    result = score_task(
        "docclass",
        ["merger_agreement"],
        ["contract"],
        expected_subclass=["other"],
        predicted_subclass=["license"],
    )
    assert result["doc_type_accuracy"] == 0.0
    assert result["exact_match"] == 0.0
    assert result["n_subclass_scored"] == 0


def test_public_exports():
    """Public exports."""
    assert dojo.sorter_subclass_keys is sorter_subclass_keys
    assert dojo.subclass_scorable is subclass_scorable
    assert dojo.UNANNOTATED_SUBCLASSES == {"merger_agreement": ("other",)}
