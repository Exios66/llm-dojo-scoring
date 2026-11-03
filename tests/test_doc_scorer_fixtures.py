"""Golden inputs for the per-document-type scorers (unified audit row plan, D1).

``tests/fixtures/doc_scorers/inputs.json`` holds synthetic rows covering every corpus
document type and subclass; ``goldens.json`` holds what the sandbox's
``score_extraction_row`` / ``assess_extraction_payload`` returned for them before the
scoring code moved into the dojo. Every later doc-scorer test compares against these.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_dojo_scoring.schemas.corpus import (
    CORPUS_DOC_TYPES,
    CORPUS_SUBCLASS_SURFACES,
    DOC_TYPE_SUBCLASSES,
)

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"


def _cases() -> list[dict]:
    """The synthetic input rows."""
    return json.loads((FIXTURES / "inputs.json").read_text())["cases"]


def _subclass_values(cases: list[dict], doc_type: str) -> set[str]:
    """Every subclass key or surface the cases carry for ``doc_type``."""
    out: set[str] = set()
    for c in cases:
        if c["doc_type"] == doc_type:
            out.update(v for v in (c.get("doc_subclass"), c.get("expected_subclass")) if v)
    return out


def test_inputs_cover_every_type_and_subclass():
    """Inputs cover every type, subclass key, surface and required edge case."""
    cases = _cases()
    assert len({c["case_id"] for c in cases}) == len(cases)
    for doc_type in CORPUS_DOC_TYPES:
        seen = _subclass_values(cases, doc_type)
        assert set(DOC_TYPE_SUBCLASSES[doc_type]) <= seen, doc_type
        assert set(CORPUS_SUBCLASS_SURFACES.get(doc_type, ())) <= seen, doc_type
        assert any(c["doc_type"] == doc_type and c["expected"] is None for c in cases), doc_type

    def has(pred) -> bool:
        """Whether any case satisfies ``pred``."""
        return any(pred(c) for c in cases)

    exp = lambda c: c["expected"] or {}  # noqa: E731
    assert has(lambda c: c["doc_type"] == "merger_agreement" and "maud_clause_labels" in exp(c))
    assert has(lambda c: c["doc_type"] == "contract" and "cuad_clause_labels" in exp(c))
    assert has(lambda c: isinstance(c["predicted"], str))
    assert has(lambda c: c["predicted"] is None)
    assert has(lambda c: isinstance(c["predicted"], list))
    assert has(lambda c: isinstance(c["predicted"], dict) and c["predicted"].get("_parse_error"))
    assert has(
        lambda c: c["doc_type"] == "insurance_claim"
        and (c.get("expected_subclass") or c.get("doc_subclass")) in {"carrier", "inpatient", "outpatient", "pde"}
        and "cms_source_table" not in exp(c)
    )
    assert has(
        lambda c: c["doc_type"] == "corporate_record"
        and not c.get("doc_subclass")
        and not c.get("expected_subclass")
    )


def test_goldens_match_inputs():
    """Every input case has a golden captured on dojo 0.26.0."""
    goldens = json.loads((FIXTURES / "goldens.json").read_text())
    assert goldens["dojo_version"] == "0.26.0"
    assert goldens["sandbox_commit"]
    assert set(goldens["cases"]) == {c["case_id"] for c in _cases()}
    for case_id, golden in goldens["cases"].items():
        assert set(golden) == {"payload", "adherence", "model_fields", "typed_valid"}, case_id


@pytest.mark.parametrize("name", ["capture_sandbox_goldens"])
def test_capture_script_loads(name):
    """The capture script loads by path and exposes its entry points."""
    from conftest import load_script

    mod = load_script(name)
    assert callable(mod.capture)
    assert callable(mod.to_jsonable)
