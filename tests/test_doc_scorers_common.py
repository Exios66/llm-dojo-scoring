"""Tier 0 of the per-document-type scorers: ``score_common`` (plan D3).

Tier 0 is everything the sandbox's ``score_extraction_row`` did before adherence and
the MAUD/CUAD headline swap. Parity is checked against the sandbox goldens with the
adherence keys and the benchmark keys taken out (those belong to D2 and D5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import load_script

from llm_dojo_scoring.scoring.doc_scorers.common import score_common
from llm_dojo_scoring.scoring.extraction_scope import scope_extraction_pair

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"
CASES = {c["case_id"]: c for c in json.loads((FIXTURES / "inputs.json").read_text())["cases"]}
GOLDENS = json.loads((FIXTURES / "goldens.json").read_text())["cases"]
to_jsonable = load_script("capture_sandbox_goldens").to_jsonable

_BENCHMARK_PREFIXES = ("maud_", "cuad_")


def _tier0_golden(golden: dict) -> dict:
    """The golden payload without adherence keys and without the benchmark headline."""
    payload = golden["payload"]
    adherence_keys = set(golden["adherence"]) | {"extra_schema_key_count", "recovered_from_raw"}
    out = {
        k: v
        for k, v in payload.items()
        if k not in adherence_keys
        and not k.startswith(_BENCHMARK_PREFIXES)
        and k != "suite_overall_extraction_score"
    }
    if "suite_overall_extraction_score" in payload:
        out["overall_extraction_score"] = payload["suite_overall_extraction_score"]
        out["scoring_method"] = payload["scoring_method"].rsplit("+", 1)[0]
    return out


SCORABLE = sorted(k for k, g in GOLDENS.items() if "error" not in g["payload"])


@pytest.mark.parametrize("case_id", SCORABLE)
def test_common_matches_golden_tier0_keys(case_id):
    """Every scorable case reproduces the sandbox's tier-0 payload exactly."""
    case = CASES[case_id]
    got = score_common(
        case["doc_type"],
        case["predicted"],
        case["expected"],
        doc_text=case.get("doc_text"),
        doc_subclass=case.get("doc_subclass"),
        expected_subclass=case.get("expected_subclass"),
    )
    assert to_jsonable(got) == _tier0_golden(GOLDENS[case_id])


def test_scope_drops_empty_lists_and_foreign_keys():
    """A correspondence row's empty insurance placeholder is not a miss."""
    pred, exp = scope_extraction_pair(
        "correspondence",
        {"sender": "A"},
        {"sender": "A", "denial_reasons": [], "claim_number": None},
    )
    assert exp == {"sender": "A"} and pred == {"sender": "A"}


def test_detailed_override_selects_suite_path():
    """``detailed=True`` forces the detailed suite path even without a subclass."""
    case = CASES[next(k for k in SCORABLE if CASES[k]["doc_type"] == "contract" and CASES[k]["expected"])]
    plain = score_common(case["doc_type"], case["predicted"], case["expected"], detailed=False)
    detailed = score_common(case["doc_type"], case["predicted"], case["expected"], detailed=True)
    assert plain["overall_extraction_score"] == detailed["overall_extraction_score"]
