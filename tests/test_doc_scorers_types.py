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
from llm_dojo_scoring.scoring.doc_scorers.correspondence import CONTENT_KEYS
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


_FIELD_MAP_TYPES = ("corporate_record", "correspondence", "insurance_claim")


#: Extras each field-map type reports beside the sandbox payload (0.27.0).
_TYPE_EXTRA_KEYS = {
    "corporate_record": set(),
    "correspondence": set(CONTENT_KEYS),
    "insurance_claim": {"determination_consistency", "amount_exactness"},
}


@pytest.mark.parametrize("case_id", [k for t in _FIELD_MAP_TYPES for k in _cases_for(t)])
def test_type_parity_field_map_types(case_id):
    """Corporate, correspondence and insurance rows keep every sandbox key and value.

    The only additions are the type's own extras, which never touch the headline.
    """
    got = to_jsonable(_run(CASES[case_id]))
    golden = _without_adherence(GOLDENS[case_id])
    assert {k: got[k] for k in golden} == golden
    assert set(got) - set(golden) <= _TYPE_EXTRA_KEYS[CASES[case_id]["doc_type"]]


@pytest.mark.parametrize("doc_type", _FIELD_MAP_TYPES)
def test_field_map_modules_registered(doc_type):
    """Every corpus type with a field map has its own module; none sets a headline."""
    scorer = DOC_SCORERS[doc_type]
    assert scorer.doc_type == doc_type
    assert scorer.headline({"overall_extraction_score": 0.5}, {}) == (None, None)
    assert scorer.extras({}, {}, subclass=None, doc_text=None) == {}


def test_corporate_record_always_detailed():
    """Corporate records take the detailed, per-record-type suite path."""
    assert DOC_SCORERS["corporate_record"].detailed is True


@pytest.mark.parametrize("doc_type", _FIELD_MAP_TYPES + ("contract", "merger_agreement"))
def test_unknown_subclass_surface_normalises(doc_type):
    """Tier 2: an uncatalogued subclass surface becomes the type's catch-all, never raises."""
    scorer = DOC_SCORERS[doc_type]
    out = scorer.subclass("Totally Unknown Surface!!")
    assert out in (*scorer.subclasses, "other")
    assert scorer.subclass(None) is None  # no subclass known: tier 0 keeps the sandbox rule


@pytest.mark.parametrize("surface, table", [("carrier", "carrier"), (" PDE ", "pde"), ("auto", None), (None, None)])
def test_insurance_derives_cms_source_table(surface, table):
    """Tier 2: CMS rows derive ``cms_source_table`` from the subclass; others get none."""
    derived = DOC_SCORERS["insurance_claim"].derived_fields(surface)
    assert derived == ({"cms_source_table": table} if table else {})


def test_cms_row_without_table_scores_derived_table():
    """A CMS row whose ground truth lacks the table still scores; the table is derived, not missed."""
    without = CASES["insurance_claim__carrier__partial__no_cms_source_table"]
    out = _run(without)
    assert out["scoring_method"] == "suite"
    assert "cms_source_table" not in (out.get("unlabeled_fields") or [])
    assert DOC_SCORERS["insurance_claim"].derived_fields(without["doc_subclass"]) == {"cms_source_table": "carrier"}
