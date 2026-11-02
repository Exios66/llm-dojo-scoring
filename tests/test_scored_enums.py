"""Scored-enum grammar hints (issue #96): consumers cannot drift from the scorer."""

from __future__ import annotations

import json

import pytest

import llm_dojo_scoring as dojo
from llm_dojo_scoring.schemas.intents import INTENT_LABELS
from llm_dojo_scoring.schemas.scored_enums import (
    SCORED_ENUM_FIELDS,
    enum_hint_violations,
    scored_enum_hint,
    scored_enum_schema,
    scored_enum_schemas,
    scored_vocabulary,
)
from llm_dojo_scoring.scoring.field_scoring import score_extraction
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

#: The drifted correspondence hint SAND-042 found in a consumer prompt.
SAND042_DRIFTED_INTENTS = (
    "demand_payment",
    "request_information",
    "threaten_litigation",
    "acknowledge",
    "schedule_meeting",
)


def _enum_cases():
    """Every (doc_type, field) pair the dojo publishes a hint for."""
    return [(doc_type, field) for doc_type, fields in SCORED_ENUM_FIELDS.items() for field in fields]


def test_every_label_field_in_the_scored_field_map_has_a_hint():
    """A ``label``-typed field without a generated hint is a drift hazard."""
    missing = [
        f"{doc_type}.{field}"
        for doc_type, fields in DEFAULT_FIELD_TYPES.items()
        for field, field_type in fields.items()
        if field_type == "label" and field not in SCORED_ENUM_FIELDS.get(doc_type, {})
    ]
    assert not missing, f"label fields without a scored-enum hint: {missing}"


def test_intent_hints_are_the_intent_vocabulary_verbatim():
    """The intent hint is :data:`INTENT_LABELS`, order included."""
    for doc_type, labels in INTENT_LABELS.items():
        assert scored_vocabulary(doc_type, "intent") == labels


@pytest.mark.parametrize(("doc_type", "field"), _enum_cases())
def test_every_scored_token_earns_full_credit(doc_type, field):
    """A hint must only teach tokens the scorer actually credits as correct."""
    field_types = {field: DEFAULT_FIELD_TYPES[doc_type].get(field, "label")}
    for token in scored_vocabulary(doc_type, field):
        result = score_extraction(doc_type, field_types, {field: token}, {field: token})
        assert result.field_scores[field] == 1.0, f"{doc_type}.{field}={token!r}"


@pytest.mark.parametrize(("doc_type", "field"), _enum_cases())
def test_schema_fragment_matches_the_vocabulary(doc_type, field):
    """The JSON Schema enum is the vocabulary plus ``null`` and serializes cleanly."""
    fragment = scored_enum_schema(doc_type, field)
    assert fragment["enum"] == [*scored_vocabulary(doc_type, field), None]
    assert fragment["description"]
    assert json.loads(json.dumps(fragment)) == fragment
    strict = scored_enum_schema(doc_type, field, nullable=False)
    assert None not in strict["enum"]


@pytest.mark.parametrize(("doc_type", "field"), _enum_cases())
def test_hint_names_every_token_verbatim(doc_type, field):
    """The prompt line quotes every scored token and admits null."""
    hint = scored_enum_hint(doc_type, field)
    assert hint.startswith(f"{field}: one of ")
    for token in scored_vocabulary(doc_type, field):
        assert f'"{token}"' in hint
    assert "or null" in hint


def test_scored_enum_schemas_cover_each_class():
    """Per-class schemas list every enum field; a class without enums is empty."""
    assert set(scored_enum_schemas("insurance_claim")) == {"intent", "claim_type", "cms_source_table"}
    assert set(scored_enum_schemas("correspondence")) == {"intent"}
    assert scored_enum_schemas("contract") == {}


def test_matching_vendored_hints_have_no_violations():
    """A consumer that vendors the dojo's lists verbatim is clean."""
    for doc_type, fields in SCORED_ENUM_FIELDS.items():
        vendored = {field: list(vocab) + [None] for field, (vocab, _) in fields.items()}
        assert enum_hint_violations(doc_type, vendored) == []


def test_sand042_drifted_intent_hint_is_reported():
    """The exact SAND-042 drift (taught labels the scorer marks wrong) is caught."""
    problems = enum_hint_violations("correspondence", {"intent": SAND042_DRIFTED_INTENTS})
    assert any("teaches unscored values" in p and "demand_payment" in p for p in problems)
    assert any("never teaches scored values" in p and "payment_demand" in p for p in problems)


def test_alias_spellings_are_not_accepted_as_a_vocabulary():
    """Scorer alias folding is a safety net, not a licence to teach aliases."""
    vendored = list(scored_vocabulary("correspondence", "intent"))
    vendored[vendored.index("meeting_invite")] = "schedule_meeting"
    problems = enum_hint_violations("correspondence", {"intent": vendored})
    assert problems and "schedule_meeting" in problems[0]


def test_unknown_vendored_field_is_reported():
    """A consumer enum the dojo does not score is named, not silently passed."""
    problems = enum_hint_violations("correspondence", {"tone": ["formal"]})
    assert "correspondence.tone: not a scored enum field" in problems
    # The scored fields the consumer omitted are reported too.
    assert "correspondence.intent: scored enum field missing from vendored hints" in problems


def test_unknown_class_or_field_raises_with_the_known_names():
    """Lookups fail loudly instead of returning an empty vocabulary."""
    with pytest.raises(KeyError, match="no scored enum fields"):
        scored_vocabulary("contract", "intent")
    with pytest.raises(KeyError, match="not a scored enum"):
        scored_vocabulary("correspondence", "urgency")


def test_helpers_are_exported_from_the_package_root():
    """Consumers import the hint helpers from ``llm_dojo_scoring`` directly."""
    for name in (
        "SCORED_ENUM_FIELDS",
        "enum_hint_violations",
        "scored_enum_hint",
        "scored_enum_schema",
        "scored_enum_schemas",
        "scored_vocabulary",
    ):
        assert hasattr(dojo, name), name
        assert name in dojo.__all__, name


def test_bare_string_vendored_value_is_one_value():
    """A bare string is a one-element list, not iterated into characters."""
    problems = enum_hint_violations("correspondence", {"intent": "payment_demand"})
    assert not any("unscored values" in p for p in problems)
    assert any("never teaches scored values" in p for p in problems)
    bad = enum_hint_violations("correspondence", {"intent": "demand_payment"})
    assert any("teaches unscored values ['demand_payment']" in p for p in bad)


def test_claim_type_teaches_product_lines_only():
    """#93: CMS table tokens are cms_source_table values, never claim_type hints."""
    claim_types = scored_vocabulary("insurance_claim", "claim_type")
    tables = scored_vocabulary("insurance_claim", "cms_source_table")
    assert "health" in claim_types
    assert not set(claim_types) & set(tables)
    problems = enum_hint_violations("insurance_claim", {"claim_type": [*claim_types, "pde"]})
    assert "insurance_claim.claim_type: teaches unscored values ['pde']" in problems
    # Fields this partial hint set omits are reported separately (#104 review).
    assert all(
        p.endswith("scored enum field missing from vendored hints")
        for p in problems
        if not p.startswith("insurance_claim.claim_type:")
    )


def test_scored_enum_fields_outer_mapping_is_read_only():
    """Assigning to the outer mapping raises and leaves the vocabulary unchanged."""
    before = scored_vocabulary("correspondence", "intent")
    with pytest.raises(TypeError):
        SCORED_ENUM_FIELDS["correspondence"] = {}  # type: ignore[index]
    assert scored_vocabulary("correspondence", "intent") == before


def test_scored_enum_fields_inner_mapping_is_read_only():
    """Assigning to an inner field mapping raises and leaves every caller's vocabulary unchanged."""
    before = scored_vocabulary("correspondence", "intent")
    with pytest.raises(TypeError):
        SCORED_ENUM_FIELDS["correspondence"]["intent"] = ((), "x")  # type: ignore[index]
    with pytest.raises(TypeError):
        SCORED_ENUM_FIELDS["insurance_claim"]["claim_type"] = ((), "x")  # type: ignore[index]
    assert scored_vocabulary("correspondence", "intent") == before
    assert enum_hint_violations("correspondence", {"intent": list(before)}) == []


def test_non_iterable_vendored_value_is_reported_not_raised():
    """An int vendored value is one reported problem, and the remaining fields are still checked."""
    problems = enum_hint_violations(
        "insurance_claim",
        {"claim_type": 5, "cms_source_table": ["carrier"]},
    )
    assert "insurance_claim.claim_type: vendored value is not a list of values" in problems
    assert any("cms_source_table" in p and "never teaches scored values" in p for p in problems)


def test_uppercase_spelling_is_reported_as_unscored():
    """Matching is case-sensitive: a hint teaching 'AUTO' is reported, not folded to 'auto'."""
    vendored = list(scored_vocabulary("insurance_claim", "claim_type"))
    vendored[vendored.index("auto")] = "AUTO"
    problems = enum_hint_violations("insurance_claim", {"claim_type": vendored})
    assert "insurance_claim.claim_type: teaches unscored values ['AUTO']" in problems
    assert "insurance_claim.claim_type: never teaches scored values ['auto']" in problems
