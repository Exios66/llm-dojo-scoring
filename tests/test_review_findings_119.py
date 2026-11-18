"""Regressions for the minor findings of the 0.27.0 review (#119).

M1 (topic/sentiment with a missing label), M2 (``str``-Enum doc types), M4 (a JSON-text
``expected``), M5 (blank and off-catalogue subclasses) and M6 (``assess_extraction_payload``
and the doc type's case). All inputs are synthetic.
"""

from __future__ import annotations

import json
from enum import Enum

import pytest

from llm_dojo_scoring.pipeline.archive import score_archive_block
from llm_dojo_scoring.pipeline.sandbox_schema_adherence import assess_extraction_payload
from llm_dojo_scoring.schemas.corpus import DOC_TYPE_SUBCLASSES
from llm_dojo_scoring.scoring.doc_scorers import DOC_SCORERS, canonical_doc_type, get_doc_scorer
from llm_dojo_scoring.scoring.doc_scorers.dispatch import score_document


class _DocType(str, Enum):
    """A ``str``-Enum doc type, the way a typed caller passes one."""

    CONTRACT = "contract"
    CORRESPONDENCE = "correspondence"


# --- M1: topic / sentiment follow the registry's "gold present" rule -------------------


def test_m1_gold_topic_without_prediction_is_a_miss_and_prediction_only_is_skipped():
    """``content_topic_f1_macro`` is "computed when a gold label is present; skipped when empty".

    A gold label with no predicted label is therefore a miss (0.0, ``n_topic`` 1), and a
    predicted label with no gold is not scored at all. The suite does the same
    (``_labelled_label_pairs``), so the two paths agree.
    """
    gold_only = score_document("correspondence", {"sender": "a"}, {"sender": "a", "content_topic": "legal"})
    assert gold_only["content_topic_accuracy"] == 0.0 and gold_only["n_topic"] == 1
    pred_only = score_document("correspondence", {"sender": "a", "content_topic": "legal"}, {"sender": "a"})
    assert "content_topic_accuracy" not in pred_only and "n_topic" not in pred_only
    blank_gold = score_document(
        "correspondence", {"sender": "a", "content_topic": "legal"}, {"sender": "a", "content_topic": "nan"}
    )
    assert "content_topic_accuracy" not in blank_gold


# --- M2: str-Enum doc types ------------------------------------------------------------


def test_m2_str_enum_doc_type_resolves_like_its_value():
    """``DT.CONTRACT`` is ``contract``, not ``dt.contract``."""
    assert canonical_doc_type(_DocType.CONTRACT) == "contract"
    assert get_doc_scorer(_DocType.CORRESPONDENCE) is get_doc_scorer("correspondence")
    got = score_document(_DocType.CORRESPONDENCE, {"sender": "a"}, {"sender": "a"})
    want = score_document("correspondence", {"sender": "a"}, {"sender": "a"})
    assert got["scorer"] == want["scorer"]
    assert got["scorer"]["module"].endswith(".correspondence")
    assert got["doc_type"] == "correspondence"


# --- M3: a non-dict Mapping prediction is not a parse error (fixed in 0.27.1) ----------


def test_m3_mapping_proxy_prediction_is_not_a_parse_error():
    """Already covered in ``test_sandbox_schema_adherence``; pinned here through ``score_document``."""
    import types

    got = score_document("correspondence", types.MappingProxyType({"sender": "a"}), {"sender": "a"})
    assert got["parse_error"] is False


# --- M4: a JSON-text expected ----------------------------------------------------------

_EXPECTED = {"sender": "Acme", "subject": "Notice"}
_PREDICTED = {"sender": "Acme", "subject": "Notice"}


@pytest.mark.parametrize("wrap", [json.dumps, repr])
def test_m4_json_text_expected_is_the_object_it_holds(wrap):
    """A JSON (or Python-repr) object string is ground truth, in both entry points."""
    as_dict = score_document("correspondence", _PREDICTED, _EXPECTED)
    as_text = score_document("correspondence", _PREDICTED, wrap(_EXPECTED))
    assert as_dict["overall_extraction_score"] == 1.0
    assert as_text["overall_extraction_score"] == as_dict["overall_extraction_score"]
    assert as_text["extraction_precision"] == as_dict["extraction_precision"]
    block_dict = score_archive_block("correspondence", _PREDICTED, _EXPECTED)
    block_text = score_archive_block("correspondence", _PREDICTED, wrap(_EXPECTED))
    for key in ("overall_score", "status", "reason", "tp", "fp", "fn", "extraction_f1", "field_map_sha"):
        assert block_text[key] == block_dict[key], key


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", ["x"], 7])
def test_m4_unreadable_expected_is_no_ground_truth_in_both_entry_points(bad):
    """Anything that is not a mapping or an object string is unscorable ground truth, never a crash."""
    doc = score_document("correspondence", _PREDICTED, bad)
    assert doc["overall_extraction_score"] is None
    block = score_archive_block("correspondence", _PREDICTED, bad)
    assert block["status"] == "unscorable"
    assert block["reason"] == "gt_wrong_schema"
    assert block["overall_score"] is None


def test_m4_coerce_expected_payload():
    """The shared reader: mappings pass, object text parses, the rest is ``None``."""
    from llm_dojo_scoring.pipeline.sandbox_schema_adherence import coerce_expected_payload

    assert coerce_expected_payload({"a": 1}) == {"a": 1}
    assert coerce_expected_payload(None) is None
    assert coerce_expected_payload('{"a": 1}') == {"a": 1}
    assert coerce_expected_payload(b'{"a": 1}') == {"a": 1}
    assert coerce_expected_payload("prose with {braces} around it") is None
    assert coerce_expected_payload("[1]") is None


# --- M5: blank and off-catalogue subclasses --------------------------------------------


@pytest.mark.parametrize("doc_type", sorted(DOC_SCORERS))
@pytest.mark.parametrize("blank", [float("nan"), "nan", "None", "null", "n/a", " "])
def test_m5_blank_subclass_is_no_subclass(doc_type, blank):
    """NaN and the literal absence tokens are not a subclass: no ``other``, no tier 2."""
    assert get_doc_scorer(doc_type).subclass(blank) is None


@pytest.mark.parametrize("doc_type", sorted(DOC_SCORERS))
def test_m5_subclass_is_always_in_the_catalogue_or_the_unknown_bucket(doc_type):
    """An off-catalogue value maps to ``other`` only where ``other`` is a real bucket of the type."""
    scorer = get_doc_scorer(doc_type)
    got = scorer.subclass("health")
    catalogue = set(DOC_TYPE_SUBCLASSES[doc_type])
    if "other" in catalogue or doc_type == "contract":
        assert got == "other"
    else:
        assert got is None


def test_m5_insurance_off_catalogue_subclass_is_not_other():
    """``insurance_claim`` has no ``other`` bucket, so ``health`` is no subclass at all."""
    assert "other" not in DOC_TYPE_SUBCLASSES["insurance_claim"]
    assert get_doc_scorer("insurance_claim").subclass("health") is None
    assert get_doc_scorer("insurance_claim").subclass("Carrier") == "carrier"


@pytest.mark.parametrize("blank", [float("nan"), "nan", "", None])
def test_m5_blank_subclass_is_not_recorded_as_a_tier_2_run(blank):
    """A blank subclass leaves ``tiers_run`` at common + type and does not shadow the other subclass."""
    got = score_document("insurance_claim", {"claim_type": "x"}, {"claim_type": "x"}, doc_subclass=blank)
    assert got["scorer"]["subclass"] is None
    assert got["scorer"]["tiers_run"] == ["common", "type"]
    # A real expected subclass is not masked by a blank doc_subclass.
    both = score_document(
        "insurance_claim", {"claim_type": "x"}, {"claim_type": "x"}, doc_subclass=blank, expected_subclass="carrier"
    )
    assert both["scorer"]["subclass"] == "carrier"
    assert both["scorer"]["tiers_run"] == ["common", "type", "subclass"]


def test_m5_off_catalogue_subclass_is_not_recorded_as_a_tier_2_run_for_insurance():
    """``health`` resolves to no subclass, so tier 2 did not run."""
    got = score_document("insurance_claim", {"claim_type": "x"}, {"claim_type": "x"}, doc_subclass="health")
    assert got["scorer"]["subclass"] is None
    assert "subclass" not in got["scorer"]["tiers_run"]


# --- M6: assess_extraction_payload canonicalises the doc type --------------------------


@pytest.mark.parametrize("spelling", ["Contract", " CONTRACT ", _DocType.CONTRACT])
def test_m6_assess_extraction_payload_reads_the_doc_type_case_insensitively(spelling):
    """A payload with a foreign key reports it whatever the doc type's case or type."""
    payload = {"parties": "Acme", "not_a_contract_field": 1}
    want = assess_extraction_payload(payload, "contract")
    assert want["extra_schema_keys"] == ["not_a_contract_field"]
    assert assess_extraction_payload(payload, spelling) == want
