"""CUAD contract schema catalog (``llm_dojo_scoring.cuad_schema``) — network-free.

Pins the 41-category / 25+1-family catalog to the corpus constants, the frozen
``contracts_specialist`` prompt and the taxonomy fixture, and checks that the
generated JSON Schema accepts GT-shaped extractions and rejects malformed ones.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from llm_dojo_scoring.config import CONTRACT_SUBTYPE_KEYS
from llm_dojo_scoring.corpus import (
    CORPUS_EXTRACTION_FIELDS,
    CORPUS_SUBCLASS_SURFACES,
    CUAD_CLAUSE_CATEGORIES,
    DOC_TYPE_SUBCLASSES,
)
from llm_dojo_scoring.cuad_schema import (
    CONTRACT_EXTRACTION_FIELDS,
    CONTRACT_FIELD_TYPES,
    CUAD_ANSWER_FORMATS,
    CUAD_CATEGORIES,
    CUAD_CATEGORY_NAMES,
    CUAD_FAMILIES,
    CUAD_FAMILY_KEYS,
    CUAD_GROUPS,
    CUAD_QUESTION_TEMPLATE,
    canonical_cuad_category,
    cuad_category,
    cuad_family,
    cuad_json_schema,
    cuad_questions,
    render_cuad_question_block,
    salient_categories,
)
from llm_dojo_scoring.equivalences import normalize_subtype
from llm_dojo_scoring.prompts import get_prompt
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES

_FIXTURE = Path(__file__).parent / "fixtures" / "taxonomy_field_types.json"


# ---------------------------------------------------------------------------
# Minimal JSON-Schema validator (the subset cuad_json_schema emits) — avoids
# adding a dependency; cross-checked against ``jsonschema`` when installed.
# ---------------------------------------------------------------------------

def _type_ok(value, name: str) -> bool:
    return {
        "string": isinstance(value, str),
        "null": value is None,
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }[name]


def _validate(value, schema, path="$") -> list[str]:
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_type_ok(value, t) for t in types):
            return [f"{path}: {value!r} is not of type {types}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match pattern")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{path}: too many items")
        for i, item in enumerate(value):
            errors += _validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required {req!r}")
        if schema.get("additionalProperties") is False:
            for extra in sorted(set(value) - set(props)):
                errors.append(f"{path}: unexpected key {extra!r}")
        for key, sub in props.items():
            if key in value:
                errors += _validate(value[key], sub, f"{path}.{key}")
    return errors


def _gt_shaped(**overrides) -> dict:
    """A GT-shaped ContractExtraction payload (11 scored keys + trace)."""
    out = {
        "reasoning": {"summary": "s", "entries": [
            {"field": "Governing Law", "evidence": "laws of the State of New York", "section_ref": "12.1"}]},
        "document_name": "License Agreement",
        "parties": ['Acme Technologies, Inc. ("Acme")', 'Beta LLC ("Beta")'],
        "effective_date": "2019-03-01",
        "term_length": "two (2) years",
        "governing_law": "governed by the laws of the State of New York",
        "contract_value": "$2,000,000",
        "renewal_terms": None,
        "cuad_family": "license",
        "merger_consideration": None,
        "cuad_clauses": [
            "License Grant: hereby grants a non-exclusive license",
            "Rofr/Rofo/Rofn: right of first refusal",
            "Unlimited/All-You-Can-Eat-License: enterprise-wide unlimited use",
        ],
        "maud_clauses": [],
        "confidence": 0.62,
    }
    out.update(overrides)
    return out


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def test_forty_one_unique_categories_match_corpus_constants():
    assert len(CUAD_CATEGORIES) == 41
    assert len(set(CUAD_CATEGORY_NAMES)) == 41
    assert set(CUAD_CATEGORY_NAMES) == set(CUAD_CLAUSE_CATEGORIES)


def test_category_names_and_order_match_frozen_prompt_list():
    text = get_prompt("contracts_specialist", family="production_prompts").text
    block = text.split("CUAD clause category names", 1)[1].split("\n", 1)[1].split("\n\n", 1)[0]
    prompt_names = tuple(n.strip() for n in block.rstrip(".").split(";"))
    assert prompt_names == CUAD_CATEGORY_NAMES


def test_category_metadata_is_well_formed():
    for cat in CUAD_CATEGORIES:
        assert cat.group in CUAD_GROUPS
        assert cat.answer_format in CUAD_ANSWER_FORMATS
        assert cat.description.strip() and cat.prompt_question.strip()
        assert cat.question == CUAD_QUESTION_TEMPLATE.format(name=cat.name, description=cat.description)
        assert cat.question.startswith(
            f'Highlight the parts (if any) of this contract related to "{cat.name}" '
            "that should be reviewed by a lawyer. Details: "
        )
        assert cat.field is None or cat.field in DEFAULT_FIELD_TYPES["contract"]
    assert {c.group for c in CUAD_CATEGORIES} == set(CUAD_GROUPS)


def test_span_categories_and_field_mapping():
    span = {c.name for c in CUAD_CATEGORIES if c.is_span}
    assert {"Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
            "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law",
            "Warranty Duration"} == span
    mapping = {c.name: c.field for c in CUAD_CATEGORIES if c.field}
    assert mapping == {
        "Document Name": "document_name",
        "Parties": "parties",
        "Agreement Date": "effective_date",
        "Effective Date": "effective_date",
        "Expiration Date": "term_length",
        "Renewal Term": "renewal_terms",
        "Notice Period To Terminate Renewal": "renewal_terms",
        "Governing Law": "governing_law",
    }


def test_known_cuad_descriptions_are_verbatim():
    assert cuad_category("Document Name").description == "The name of the contract"
    assert cuad_category("Expiration Date").description == "On what date will the contract's initial term expire?"
    assert cuad_category("Governing Law").description == (
        "Which state/country's law governs the interpretation of the contract?"
    )
    assert cuad_category("Competitive Restriction Exception").description.startswith(
        "This category includes the exceptions or carveouts to Non-Compete"
    )


@pytest.mark.parametrize("alias,canonical", [
    ("ROFR/ROFO/ROFN", "Rofr/Rofo/Rofn"),
    ("rofr rofo rofn", "Rofr/Rofo/Rofn"),
    ("ROFR", "Rofr/Rofo/Rofn"),
    ("Right of First Refusal", "Rofr/Rofo/Rofn"),
    ("Non-Compete", "Non-Compete"),
    ("Noncompete", "Non-Compete"),
    ("  non compete ", "Non-Compete"),
    ("IP Ownership Assignment", "Ip Ownership Assignment"),
    ("Joint IP Ownership", "Joint Ip Ownership"),
    ("Cap on Liability", "Cap On Liability"),
    ("termination for convenience", "Termination For Convenience"),
    ("MFN", "Most Favored Nation"),
    ("Change of Control", "Change Of Control"),
    ("Non-Solicit of Employees", "No-Solicit Of Employees"),
    ("All You Can Eat License", "Unlimited/All-You-Can-Eat-License"),
    ("Third-Party Beneficiary", "Third Party Beneficiary"),
    ("Notice Period", "Notice Period To Terminate Renewal"),
])
def test_category_alias_lookup(alias, canonical):
    assert cuad_category(alias).name == canonical
    assert canonical_cuad_category(alias) == canonical


def test_every_category_resolves_by_its_own_name_and_unknown_fails_closed():
    for name in CUAD_CATEGORY_NAMES:
        assert cuad_category(name).name == name
        assert cuad_category(name.upper()).name == name
    assert canonical_cuad_category("Not A Category") is None
    assert canonical_cuad_category(None) is None
    with pytest.raises(KeyError):
        cuad_category("Not A Category")
    with pytest.raises(KeyError):
        cuad_category(None)


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def test_families_match_corpus_subclass_catalog():
    assert len(CUAD_FAMILIES) == 26
    assert CUAD_FAMILY_KEYS[:-1] == tuple(CONTRACT_SUBTYPE_KEYS) == DOC_TYPE_SUBCLASSES["contract"]
    assert CUAD_FAMILY_KEYS[-1] == "other"
    surfaces = [s for f in CUAD_FAMILIES for s in f.surfaces]
    assert len(surfaces) == len(set(surfaces))
    assert set(surfaces) == set(CORPUS_SUBCLASS_SURFACES["contract"])
    for fam in CUAD_FAMILIES:
        for surface in fam.surfaces:
            assert normalize_subtype(surface) == fam.key


def test_family_salient_categories_are_valid_and_nonempty():
    valid = set(CUAD_CATEGORY_NAMES)
    for fam in CUAD_FAMILIES:
        assert set(fam.salient) <= valid
        assert len(fam.salient) == len(set(fam.salient))
        assert fam.definition.strip()
        if fam.key != "other":
            assert len(fam.salient) >= 8, fam.key
    assert cuad_family("other").salient == ()


def test_family_salient_cover_prompt_executive_brief():
    """Categories the frozen prompt's per-subtype brief names must be salient."""
    expected = {
        "license": {"License Grant", "Non-Transferable License", "Irrevocable Or Perpetual License",
                    "Ip Ownership Assignment"},
        "supply": {"Minimum Commitment", "Volume Restriction", "Price Restrictions"},
        "manufacturing": {"Minimum Commitment", "Volume Restriction", "Price Restrictions"},
        "non_compete_no_solicit": {"Non-Compete", "No-Solicit Of Customers", "No-Solicit Of Employees",
                                   "Non-Disparagement"},
        "affiliate": {"Affiliate License-Licensee", "Affiliate License-Licensor"},
        "franchise": {"Non-Compete", "Exclusivity", "Revenue/Profit Sharing", "Audit Rights",
                      "Minimum Commitment"},
        "joint_venture": {"Joint Ip Ownership", "Change Of Control", "Revenue/Profit Sharing"},
        "hosting": {"Price Restrictions", "Renewal Term"},
        "transportation": {"Insurance", "Cap On Liability"},
    }
    for key, cats in expected.items():
        assert cats <= set(cuad_family(key).salient), key


def test_family_hints_do_not_touch_scored_field_map():
    for fam in CUAD_FAMILIES:
        for hint in fam.family_fields:
            assert hint.informs is None or hint.informs in DEFAULT_FIELD_TYPES["contract"]
            assert hint.name not in DEFAULT_FIELD_TYPES["contract"]
    names = {h.name for h in cuad_family("license").family_fields}
    assert {"royalty_rate", "territory", "licensed_product"} <= names


def test_cuad_family_lookup_normalizes_surfaces_and_unknowns():
    assert cuad_family("License_Agreements").key == "license"
    assert cuad_family("Joint Venture _ Filing").key == "joint_venture"
    assert cuad_family("Non_Compete_Non_Solicit").key == "non_compete_no_solicit"
    assert cuad_family("License Agreement").key == "license"
    assert cuad_family("supply") is cuad_family(cuad_family("supply"))
    assert cuad_family(None).key == "other"
    assert cuad_family("employment contract").key == "other"
    assert cuad_family("other").key == "other"


# ---------------------------------------------------------------------------
# Field map parity
# ---------------------------------------------------------------------------

def test_field_descriptor_matches_default_field_types_and_fixture():
    assert CONTRACT_FIELD_TYPES == DEFAULT_FIELD_TYPES["contract"]
    assert len(CONTRACT_EXTRACTION_FIELDS) == 11
    assert tuple(f.name for f in CONTRACT_EXTRACTION_FIELDS) == CORPUS_EXTRACTION_FIELDS["contract"]
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert CONTRACT_FIELD_TYPES == fixture["doc_classes"]["contract"]["field_types"]


def test_field_empty_values_follow_empty_field_contract():
    for f in CONTRACT_EXTRACTION_FIELDS:
        assert f.description.strip()
        assert f.is_list == f.scoring_type.startswith("entity_list")
        assert f.empty_value == ([] if f.is_list else None)
    a, b = CONTRACT_EXTRACTION_FIELDS[1].empty_value, CONTRACT_EXTRACTION_FIELDS[1].empty_value
    assert a == b == [] and a is not b


def test_default_field_types_untouched_by_import():
    assert list(DEFAULT_FIELD_TYPES["contract"]) == list(CORPUS_EXTRACTION_FIELDS["contract"])


# ---------------------------------------------------------------------------
# Questions and prompt block
# ---------------------------------------------------------------------------

def test_questions_without_family_follow_cuad_order():
    qs = cuad_questions()
    assert [c for c, _ in qs] == list(CUAD_CATEGORY_NAMES)
    assert all(q.startswith("Highlight the parts (if any)") for _, q in qs)
    spec = cuad_questions(style="specialist")
    assert [c for c, _ in spec] == list(CUAD_CATEGORY_NAMES)
    assert all(not q.startswith("Highlight") for _, q in spec)
    with pytest.raises(ValueError):
        cuad_questions(style="nope")


@pytest.mark.parametrize("family", CUAD_FAMILY_KEYS)
def test_questions_put_salient_categories_first(family):
    qs = cuad_questions(family)
    names = [c for c, _ in qs]
    salient = list(salient_categories(family))
    assert len(names) == 41 and set(names) == set(CUAD_CATEGORY_NAMES)
    assert names[: len(salient)] == salient
    rest = [n for n in CUAD_CATEGORY_NAMES if n not in set(salient)]
    assert names[len(salient):] == rest
    assert [c for c, _ in cuad_questions(family, salient_only=True)] == salient


def test_license_family_leads_with_license_grant():
    names = [c for c, _ in cuad_questions("License_Agreements")]
    assert names[0] == "License Grant"
    assert names.index("Non-Transferable License") < names.index("Document Name")


def test_render_question_block():
    plain = render_cuad_question_block()
    assert "Salient" not in plain and "Contract family" not in plain
    for name in CUAD_CATEGORY_NAMES:
        assert f"- {name}" in plain
    lic = render_cuad_question_block("license")
    assert "Contract family: license" in lic
    assert lic.index("- License Grant") < lic.index("Other categories:") < lic.index("- Document Name")
    assert "- Governing Law [also governing_law]:" in lic
    full = render_cuad_question_block("supply", style="cuad")
    assert 'related to "Minimum Commitment"' in full
    subset = render_cuad_question_block("supply", categories=["ROFR/ROFO/ROFN", "Insurance"])
    assert subset.count("\n- ") == 2 and "Rofr/Rofo/Rofn" in subset
    with pytest.raises(KeyError):
        render_cuad_question_block(categories=["bogus"])


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------

def test_json_schema_shape():
    schema = cuad_json_schema()
    props = schema["properties"]
    assert schema["additionalProperties"] is False
    assert set(CONTRACT_FIELD_TYPES) <= set(props) and set(props) - set(CONTRACT_FIELD_TYPES) == {
        "reasoning", "confidence"}
    assert set(schema["required"]) == set(props)
    for name in ("document_name", "term_length", "governing_law", "contract_value", "renewal_terms"):
        assert props[name]["type"] == ["string", "null"]
    assert props["parties"]["default"] == [] and props["cuad_clauses"]["default"] == []
    assert props["cuad_family"]["enum"] == [*CUAD_FAMILY_KEYS, None]
    assert len(props["cuad_family"]["enum"]) == 27
    pattern = props["cuad_clauses"]["items"]["pattern"]
    assert pattern.startswith("^(?:") and pattern.endswith("): .+")
    assert all(n in pattern for n in CUAD_CATEGORY_NAMES)
    json.dumps(schema)  # serializable for guided decoding


def test_json_schema_scored_only_variant():
    schema = cuad_json_schema(include_trace=False)
    assert list(schema["properties"]) == list(CORPUS_EXTRACTION_FIELDS["contract"])
    assert schema["required"] == list(CORPUS_EXTRACTION_FIELDS["contract"])


def test_json_schema_accepts_gt_shaped_examples():
    schema = cuad_json_schema()
    scored = cuad_json_schema(include_trace=False)
    empty = _gt_shaped(
        document_name=None, parties=[], effective_date=None, term_length=None,
        governing_law=None, contract_value=None, cuad_family=None, cuad_clauses=[],
    )
    for example in (_gt_shaped(), empty, _gt_shaped(cuad_family="other", contract_value="$0")):
        assert _validate(example, schema) == []
        scored_only = {k: v for k, v in example.items() if k in scored["properties"]}
        assert _validate(scored_only, scored) == []
    every_category = _gt_shaped(cuad_clauses=[f"{n}: some verbatim span" for n in CUAD_CATEGORY_NAMES])
    assert _validate(every_category, schema) == []


@pytest.mark.parametrize("bad", [
    {"effective_date": "March 1, 2019"},
    {"cuad_family": "employment"},
    {"cuad_clauses": ["Made Up Category: text"]},
    {"cuad_clauses": ["License Grant:"]},
    {"cuad_clauses": ["License Grant grants a license"]},
    {"cuad_clauses": ["license grant: wrong case"]},
    {"parties": "Acme"},
    {"parties": [None]},
    {"merger_consideration": "all_cash"},
    {"maud_clauses": ["MAE Definition: Yes"]},
    {"confidence": 1.5},
    {"unknown_key": 1},
])
def test_json_schema_rejects_malformed(bad):
    assert _validate(_gt_shaped(**bad), cuad_json_schema()) != []


def test_json_schema_rejects_missing_required():
    payload = _gt_shaped()
    del payload["cuad_clauses"]
    assert any("cuad_clauses" in e for e in _validate(payload, cuad_json_schema()))


def test_json_schema_agrees_with_jsonschema_when_installed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = cuad_json_schema()
    validator = jsonschema.Draft7Validator(schema)
    jsonschema.Draft7Validator.check_schema(schema)
    assert list(validator.iter_errors(_gt_shaped())) == []
    for bad in ({"effective_date": "March 1, 2019"}, {"cuad_clauses": ["Made Up Category: x"]},
                {"cuad_family": "employment"}, {"merger_consideration": "all_cash"}):
        payload = _gt_shaped(**bad)
        assert (not validator.is_valid(payload)) == bool(_validate(payload, schema))


def test_reference_doc_covers_every_category_and_family():
    doc = (Path(__file__).parent.parent / "docs" / "CUAD_SCHEMA.md").read_text(encoding="utf-8")
    for cat in CUAD_CATEGORIES:
        assert f"`{cat.name}`" in doc and cat.description.replace("|", "\\|") in doc
    for fam in CUAD_FAMILIES:
        assert f"`{fam.key}`" in doc


def test_cuad_family_unknown_normalized_subtype_falls_back_to_other(monkeypatch):
    # configure_from_taxonomy() can register a custom subtype that
    # normalize_subtype returns verbatim; it has no CUAD family.
    import llm_dojo_scoring.cuad_schema as cs

    monkeypatch.setattr(cs, "normalize_subtype", lambda _name: "custom")
    assert cs.cuad_family("custom contract").key == "other"
