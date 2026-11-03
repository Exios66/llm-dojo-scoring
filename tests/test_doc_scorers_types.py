"""Per-type scorer modules reproduce the sandbox goldens (plan D5, D6).

``score_tiers`` composes tier 0 with the type module's extras and headline; its output
must equal the sandbox's ``score_extraction_row`` payload without the adherence keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import load_script

from llm_dojo_scoring.scoring.doc_scorers import DOC_SCORERS, get_doc_scorer
from llm_dojo_scoring.scoring.doc_scorers.dispatch import score_tiers

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"
CASES = {c["case_id"]: c for c in json.loads((FIXTURES / "inputs.json").read_text())["cases"]}
GOLDENS = json.loads((FIXTURES / "goldens.json").read_text())["cases"]
to_jsonable = load_script("capture_sandbox_goldens").to_jsonable


def _without_adherence(golden: dict) -> dict:
    """The golden payload minus the keys ``assess_extraction_payload`` adds."""
    drop = set(golden["adherence"]) | {"extra_schema_key_count", "recovered_from_raw"}
    return {k: v for k, v in golden["payload"].items() if k not in drop}


def _cases_for(doc_type: str) -> list[str]:
    """Scorable case ids of one document type."""
    return sorted(
        k for k, c in CASES.items() if c["doc_type"] == doc_type and "error" not in GOLDENS[k]["payload"]
    )


def _run(case: dict) -> dict:
    """Score one case through the tiers."""
    return score_tiers(
        case["doc_type"],
        case["predicted"],
        case["expected"],
        doc_text=case.get("doc_text"),
        doc_subclass=case.get("doc_subclass"),
        expected_subclass=case.get("expected_subclass"),
    )


@pytest.mark.parametrize(
    "case_id", _cases_for("contract") + _cases_for("merger_agreement")
)
def test_type_parity_benchmark_types(case_id):
    """Contract and merger rows match the sandbox, CUAD/MAUD headline swap included."""
    assert to_jsonable(_run(CASES[case_id])) == _without_adherence(GOLDENS[case_id])


def test_benchmark_modules_registered():
    """Contract and merger have their own modules."""
    assert DOC_SCORERS["contract"].doc_type == "contract"
    assert DOC_SCORERS["merger_agreement"].doc_type == "merger_agreement"
    assert get_doc_scorer("contracts_specialist") is DOC_SCORERS["contract"]


def test_benchmark_labels_without_clause_keys_score_zero():
    """MAUD labels with no clause answers give the benchmark's 0.0, not a field-map fallback."""
    case_id = next(
        k
        for k in _cases_for("merger_agreement")
        if "maud_clause_labels" in (CASES[k]["expected"] or {})
        and "maud_clauses" not in (CASES[k]["predicted"] or {})
    )
    out = _run(CASES[case_id])
    assert out["overall_extraction_score"] == 0.0
    assert out["scoring_method"].endswith("+maud")
    assert "suite_overall_extraction_score" in out


def test_contract_subclass_normalises_cuad_surface():
    """Tier 2: a folder-style CUAD surface becomes its canonical family."""
    assert DOC_SCORERS["contract"].subclass("License_Agreements") == "license"
