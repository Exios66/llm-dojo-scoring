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


# --- 0.27.2: review findings on the 0.27.1 snapshot (local-mailroom-sandbox#245) ---


def test_any_mapping_is_a_dict_payload():
    """score_document accepts any Mapping, so adherence must not call it a parse error."""
    import types
    from collections import UserDict

    for wrapped in (types.MappingProxyType({"sender": "Acme"}), UserDict({"sender": "Acme"})):
        payload, meta = coerce_predicted_payload(wrapped)
        assert payload == {"sender": "Acme"} and type(payload) is dict
        assert meta["parse_error"] is False and meta["parse_failure_reason"] is None


def test_flagged_parse_error_mapping_still_recovers_raw():
    """A flagged parse error arriving as a non-dict Mapping still recovers ``_raw``."""
    import types

    payload, meta = coerce_predicted_payload(
        types.MappingProxyType({"_parse_error": True, "_raw": '{"sender": "Acme"}'})
    )
    assert payload == {"sender": "Acme"}
    assert meta["parse_error"] is True and meta["recovered_from_raw"] is True


@pytest.mark.parametrize("text", ["[" * 200_000, "{" * 200_000, "note: " + '{"a": ' * 200_000])
def test_deeply_nested_text_is_unparseable_not_a_crash(text):
    """Nesting past the decoder's stack is an unparseable payload, not a RecursionError."""
    payload, meta = coerce_predicted_payload(text)
    assert payload is None
    assert meta["parse_error"] is True and meta["parse_failure_reason"] == "unparseable"


@pytest.mark.parametrize(
    "text",
    ["Here you go: {'sender': 'Acme'} thanks", 'Here you go: {"sender": "Acme"} thanks'],
)
def test_prose_wrapped_object_sets_prose_wrapper(text):
    """Both wrapped forms (JSON and Python repr) are prose-wrapped payloads."""
    payload, meta = coerce_predicted_payload(text)
    assert payload == {"sender": "Acme"}
    assert meta["prose_wrapper"] is True and meta["parse_error"] is False


@pytest.mark.parametrize(
    "text, expected",
    [
        ('Use {braces} first, then { "sender": "Acme" } done', {"sender": "Acme"}),
        ("Empty {} then {x} end", {}),
        ('{{{{ junk then {"sender": "Acme"} and {more', {"sender": "Acme"}),
    ],
)
def test_fallback_still_finds_an_object_after_stray_braces(text, expected):
    """The candidate-start fallback still finds an object after braces in the prose."""
    payload, meta = coerce_predicted_payload(text)
    assert payload == expected
    assert meta["prose_wrapper"] is True


def test_many_open_braces_parse_in_linear_time():
    """Brace-heavy junk text fails fast (the old greedy regex and fallback were quadratic)."""
    import time

    started = time.perf_counter()
    for text in ("{" * 200_000, "note: " + '{"a": ' * 200_000, "x {" * 100_000):
        assert coerce_predicted_payload(text)[0] is None
    assert time.perf_counter() - started < 5.0


@pytest.mark.parametrize(
    "text",
    [
        # 50k levels: past the C decoder's recursion limit (it decodes ~5k fine)
        'see ' + '{"a": ' * 50_000 + "1" + "}" * 50_000 + ' then {"sender": "Acme"} done',
        'see ' + '{"s": "}{", "a": ' * 50_000 + "1" + "}" * 50_000 + ' and {"sender": "Acme"}',
    ],
)
def test_sibling_object_after_a_too_deep_object_is_found(text):
    """A RecursionError skips only the deep object; a later sibling object still parses."""
    payload, meta = coerce_predicted_payload(text)
    assert payload == {"sender": "Acme"}
    assert meta["prose_wrapper"] is True and meta["parse_error"] is False


def test_sibling_scan_stays_linear():
    """Many deep-then-closed objects in a row are each skipped in one pass."""
    import time

    deep = '{"a": ' * 30_000 + "1" + "}" * 30_000
    text = "x " + " ".join([deep] * 20) + ' {"sender": "Acme"}'
    started = time.perf_counter()
    assert coerce_predicted_payload(text)[0] == {"sender": "Acme"}
    assert time.perf_counter() - started < 5.0
