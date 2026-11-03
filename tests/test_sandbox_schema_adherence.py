"""``assess_extraction_payload`` moved from the sandbox into the dojo (plan D2).

Parity is checked against ``tests/fixtures/doc_scorers/goldens.json``. Mailroom's
pydantic models are never imported: ``GoldenSchemaLookup`` replays, per case, the
model field names and validation verdict the capture script recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_dojo_scoring.pipeline.sandbox_schema_adherence import (
    assess_extraction_payload,
    coerce_predicted_payload,
)

FIXTURES = Path(__file__).parent / "fixtures" / "doc_scorers"
CASES = {c["case_id"]: c for c in json.loads((FIXTURES / "inputs.json").read_text())["cases"]}
GOLDENS = json.loads((FIXTURES / "goldens.json").read_text())["cases"]


class GoldenSchemaLookup:
    """A ``schema_lookup`` that replays one case's recorded mailroom model facts."""

    def __init__(self, golden: dict):
        """Keep the recorded ``model_fields`` and ``typed_valid`` for the case."""
        self.fields = golden["model_fields"]
        self.typed_valid = golden["typed_valid"]

    def __call__(self, doc_type: str):
        """Return a stand-in model class, or ``None`` when no model was recorded."""
        if self.fields is None:
            return None
        verdict = self.typed_valid

        class _Model:
            """Stand-in pydantic model."""

            model_fields = {name: None for name in self.fields}

            @staticmethod
            def model_validate(payload):
                """Replay the recorded verdict."""
                if verdict is False:
                    raise ValueError("recorded invalid")
                return payload

        return _Model


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_adherence_matches_goldens(case_id):
    """Every case reproduces the sandbox's adherence result exactly."""
    case, golden = CASES[case_id], GOLDENS[case_id]
    sub = case.get("doc_subclass") or case.get("expected_subclass")
    got = assess_extraction_payload(
        case["predicted"], case["doc_type"], sub, schema_lookup=GoldenSchemaLookup(golden)
    )
    assert got == golden["adherence"]


@pytest.mark.parametrize(
    "predicted",
    ["Here is the extraction: none", None, ["a", "b"], '{"parties": ["A"]}', 42, b"\xff\xfe", ""],
)
def test_adherence_without_lookup_never_raises(predicted):
    """Bad payloads come back as data, never as an exception."""
    out = assess_extraction_payload(predicted, "contract")
    assert set(out) >= {"parse_error", "schema_valid", "schema_adherence", "parse_failure_reason"}
    assert out["schema_adherence"] in (0.0, 1.0)


def test_coerce_reads_python_repr_and_wrapped_json():
    """Job rows store a Python repr; raw LLM text can wrap JSON in prose."""
    assert coerce_predicted_payload("{'a': 1}")[0] == {"a": 1}
    payload, meta = coerce_predicted_payload('Sure! {"a": 1} hope that helps')
    assert payload == {"a": 1} and meta["prose_wrapper"] is True
