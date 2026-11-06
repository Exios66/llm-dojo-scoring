"""Bound the recorded departures from the frozen per-document-type goldens.

``tests/fixtures/doc_scorers/departures.json`` holds the scores a release changed on
purpose (``scripts/record_doc_scorer_departures.py``); the parity tests apply it over
the captured goldens. These tests keep it from becoming a way to absorb any change:
it must be current, and it may only move what the 0.28.0 v2 schemas move.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import doc_scorer_departures, load_script

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"
CASES = {c["case_id"]: c for c in json.loads((FIXTURES / "inputs.json").read_text())["cases"]}
DEPARTURES = doc_scorer_departures()

#: Classes whose live field map changed in 0.28.0 (corporate_record did not).
_V2_CLASSES = {"contract", "merger_agreement", "correspondence", "insurance_claim"}
#: Fields whose scores may move: the ``label`` retypes and the contract parse-compat keys.
_MOVABLE_FIELDS = {
    "contract": {"cuad_family", "merger_consideration", "maud_clauses"},
    "merger_agreement": {"merger_consideration", "intent"},
    "correspondence": {"communication_type", "urgency"},
    "insurance_claim": {"claim_type", "coverage_determination"},
}
_PRF = {"extraction_precision", "extraction_recall", "extraction_f1", "extraction_f2"}
_PAYLOAD_KEYS = {"overall_extraction_score", "suite_overall_extraction_score", "fields"} | _PRF
_BLOCK_KEYS = {"field_map_sha", "field_scores", "overall_score", "schema_valid", "tp", "fp", "fn"} | _PRF


def test_departures_are_current():
    """The overlay equals what the recorder computes from this checkout."""
    assert load_script("record_doc_scorer_departures").main(["--check"]) == 0


def test_departures_touch_only_v2_classes_and_keys():
    """Only v2 classes move, and only scores, counts, field maps and schema_valid."""
    for case_id, moved in DEPARTURES["payload"].items():
        assert CASES[case_id]["doc_type"] in _V2_CLASSES, case_id
        assert set(moved) <= _PAYLOAD_KEYS, (case_id, set(moved) - _PAYLOAD_KEYS)
    for case_id, variants in DEPARTURES["archive_block"].items():
        assert CASES[case_id]["doc_type"] in _V2_CLASSES, case_id
        for moved in variants.values():
            assert set(moved) <= _BLOCK_KEYS, (case_id, set(moved) - _BLOCK_KEYS)


def test_field_score_moves_are_label_or_parse_compat_fields():
    """A moved block field score is a retyped label (or a contract parse-compat key)."""
    before = json.loads((FIXTURES / "archive_block_before.json").read_text())["cases"]
    for case_id, variants in DEPARTURES["archive_block"].items():
        doc_type = CASES[case_id]["doc_type"]
        for moved in variants.values():
            if "field_scores" not in moved:
                continue
            old, new = before[case_id]["field_scores"], moved["field_scores"]
            changed = {f for f in set(old) | set(new) if old.get(f) != new.get(f)}
            assert changed <= _MOVABLE_FIELDS[doc_type], (case_id, changed)


def test_every_v2_block_records_its_new_field_map():
    """Every scorable v2-class block moves ``field_map_sha``; corporate blocks never do."""
    before = json.loads((FIXTURES / "archive_block_before.json").read_text())["cases"]
    for case_id, block in before.items():
        if "error" in block:
            continue
        moved = DEPARTURES["archive_block"].get(case_id, {})
        if CASES[case_id]["doc_type"] in _V2_CLASSES:
            assert {"plain", "with_subclass"} <= set(moved), case_id
            assert all("field_map_sha" in v for v in moved.values()), case_id
        else:
            assert not moved, case_id
