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


@pytest.mark.parametrize("depth", [129, 30_000])
@pytest.mark.parametrize("style", ["json", "repr", "wrapped_json", "wrapped_repr", "array"])
def test_nesting_guard_is_deterministic_across_parse_paths(depth, style):
    """Excess nesting is rejected before Python-dependent decoder limits matter."""
    nested = "[" * depth + "1" + "]" * depth
    quote = "'" if "repr" in style else '"'
    text = "{" + quote + "junk" + quote + ": " + nested + "}"
    if style.startswith("wrapped"):
        text = "Here: " + text + " done"
    elif style == "array":
        text = "[" * depth + '{"sender": "Acme"}' + "]" * depth
    payload, meta = coerce_predicted_payload(text)
    assert payload is None
    assert meta["parse_error"] is True


@pytest.mark.parametrize("nested", [
    '{"a": ' * 129 + "1" + "}" * 129,
    '{"a": ' + "[" * 129 + "1" + "]" * 129 + "}",
], ids=["objects", "arrays"])
def test_guarded_candidates_are_not_redecoded_as_shallow_children(nested, monkeypatch):
    """Skip the whole deep region and recover a sibling without decoding its children."""
    from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence

    original = adherence.json.JSONDecoder.raw_decode
    calls = []

    def record_decode(self, text, *args, **kwargs):
        """Count decoder attempts to detect child-candidate retry regressions."""
        calls.append(len(text))
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(adherence.json.JSONDecoder, "raw_decode", record_decode)
    payload, meta = coerce_predicted_payload("x " + nested + ' then {"sender": "Acme"}')
    assert payload == {"sender": "Acme"}
    assert meta["prose_wrapper"] is True
    assert len(calls) <= 3


def test_normal_nested_arrays_and_quoted_braces_remain_payloads():
    """Normal dictionaries, nested arrays and quoted brackets remain supported."""
    payload = {"sender": "Acme", "items": [{"text": '{}[] and escaped \"quote\"'}], "deep": [[1]]}
    for text in (json.dumps(payload), repr(payload), "Here: " + json.dumps(payload) + " done"):
        assert coerce_predicted_payload(text)[0] == payload


@pytest.mark.parametrize("text", [
    'x {"bad": "' + '{"a": ' * 129 + '1' + '}' * 129,
    'Here: ' + '[' * 129 + '{"sender": "Acme"}' + ']' * 129 + ' done',
    "Here's " + '[' * 129 + '{"sender": "Acme"}' + ']' * 129,
], ids=["inside-quoted-junk", "wrapped-deep-array", "apostrophe-wrapper"])
def test_fallback_cannot_bypass_nesting_guard(text):
    """Every recovered candidate passes the same explicit nesting guard."""
    payload, meta = coerce_predicted_payload(text)
    assert payload is None
    assert meta["parse_error"] is True


@pytest.mark.parametrize("style", ["json", "repr", "wrapped_json", "wrapped_repr"])
def test_nesting_limit_boundary_and_quoted_brackets_are_accepted(style):
    """The supported depth boundary and bracket strings remain parseable."""
    nested = "[" * 127 + "1" + "]" * 127
    quote = "'" if "repr" in style else '"'
    text = "{" + quote + "items" + quote + ": " + nested + "}"
    if style.startswith("wrapped"):
        text = "Here's " + text + " done"
    payload, meta = coerce_predicted_payload(text)
    assert isinstance(payload["items"], list)
    assert meta["parse_error"] is False
    assert coerce_predicted_payload(json.dumps({"text": "{" * 200 + "[" * 200}))[0] == {"text": "{" * 200 + "[" * 200}


@pytest.mark.parametrize("fragment", ['{"', '{"a": "'])
def test_malformed_quote_candidates_reuse_scanned_regions(fragment, monkeypatch):
    """Alternate quote contexts share cached ends instead of rescanning each suffix."""
    from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence

    original = adherence._object_ends
    scanned = 0

    def count_scan(text, start):
        """Count a conservative upper bound on characters scanned by each call."""
        nonlocal scanned
        scanned += len(text) - start
        return original(text, start)

    monkeypatch.setattr(adherence, "_object_ends", count_scan)
    text = 'x {"bad": "' + fragment * 2_000
    assert coerce_predicted_payload(text)[0] is None
    assert scanned <= 3 * len(text)
    assert coerce_predicted_payload(text + ' then {"sender": "Acme"}')[0] == {"sender": "Acme"}


def test_shallow_repr_after_unrelated_deep_array_is_recovered():
    """A rejected deep region must not suppress an independent Python-repr payload."""
    text = "junk " + "[" * 129 + "1" + "]" * 129 + " then {'sender': 'Acme'}"
    payload, meta = coerce_predicted_payload(text)
    assert payload == {"sender": "Acme"}
    assert meta["prose_wrapper"] is True


def test_deep_repr_cannot_recover_json_from_a_quoted_value():
    """Reject the entire deep repr, including JSON text stored inside its strings."""
    text = "{'junk': " + "[" * 129 + "1" + "]" * 129 + ", 'raw': '{\"sender\": \"Acme\"}'}"
    payload, meta = coerce_predicted_payload(text)
    assert payload is None
    assert meta["parse_error"] is True


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("count", [80, 2_000])
@pytest.mark.parametrize("tail", ["", "z" * 4_000], ids=["no-tail", "long-tail"])
def test_escaped_quote_recovery_reads_a_linear_number_of_characters(quote, count, tail, monkeypatch):
    """Count real indexing work when malformed candidates change quote contexts."""
    from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence

    reads = 0
    original = adherence._object_ends

    class CountedText(str):
        """Instrument character access without relying on machine timing."""

        def __getitem__(self, index):
            """Count individual indexed reads."""
            nonlocal reads
            if isinstance(index, int):
                reads += 1
            return super().__getitem__(index)

        def __iter__(self):
            """Expose iteration through the same read counter."""
            for index in range(len(self)):
                yield self[index]

    def count_scan(text, start):
        """Instrument the index builder without changing payload parsing."""
        return original(CountedText(text), start)

    monkeypatch.setattr(adherence, "_object_ends", count_scan)
    text = 'x {"bad": "' + ("[\\" + quote) * count + tail
    assert coerce_predicted_payload(text)[0] is None
    assert reads <= 3 * len(text)
    reads = 0
    sibling_text = text + ' then {"sender": "Acme"}'
    assert coerce_predicted_payload(sibling_text)[0] == {"sender": "Acme"}
    assert reads <= 3 * len(sibling_text)


@pytest.mark.parametrize("count", [100, 2_000])
def test_completed_escaped_array_candidates_do_not_decode_overlapping_suffixes(count, monkeypatch):
    """Arrays enforce depth but never consume decoder input intended for dicts."""
    from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence

    decoded = 0
    original = adherence.json.JSONDecoder.raw_decode

    def count_decode(self, text, *args, **kwargs):
        """Count decoder input volume, including copies of overlapping suffixes."""
        nonlocal decoded
        decoded += len(text)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(adherence.json.JSONDecoder, "raw_decode", count_decode)
    text = 'x {"bad": "' + ('[\\"' * count) + '" ]'
    assert coerce_predicted_payload(text)[0] is None
    assert decoded <= 3 * len(text)
    decoded = 0
    sibling_text = text + ' then {"sender": "Acme"}'
    assert coerce_predicted_payload(sibling_text)[0] == {"sender": "Acme"}
    assert decoded <= 3 * len(sibling_text)
