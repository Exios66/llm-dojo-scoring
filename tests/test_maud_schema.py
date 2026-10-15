"""MAUD entity schema: question→answer contract is data, and the scorer agrees.

Pins ``llm_dojo_scoring.maud_schema`` against the live catalog
(``maud.py``), the offline Hub mirror (``fixtures/maud_valid_classes.json``),
the field map (``DEFAULT_FIELD_TYPES``) and — via the real merger suite — the
scorer's own parsing, so the prompt, the grammar and the scorer cannot drift.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.config import MAUD_CONSIDERATION_TYPES
from llm_dojo_scoring.content_scoring import (
    parse_maud_labels,
    score_maud_extraction,
)
from llm_dojo_scoring.corpus import (
    CORPUS_EXTRACTION_FIELDS,
    DOC_TYPE_SUBCLASSES,
    MAUD_CLAUSE_CATEGORIES,
    MAUD_QUESTION_KEYS,
    subclass_equivalent,
)
from llm_dojo_scoring.maud import (
    MAUD_ANSWER_CLASSES,
    MAUD_VARIABLE_CLASS_QUESTIONS,
    maud_question_catalog,
)
from llm_dojo_scoring.maud_schema import (
    MAUD_CONSIDERATION_SUBCLASSES,
    MAUD_QUESTIONS,
    MAUD_TYPE_OF_CONSIDERATION_TO_TOKEN,
    MaudQuestion,
    MergerAgreementExtraction,
    category_mismatches,
    consideration_subclass,
    maud_answers_to_clauses,
    maud_clause_line,
    maud_clauses_to_answers,
    maud_json_schema,
    maud_json_schema_text,
    maud_question,
    maud_questions,
    parse_maud_clause,
    render_maud_question_block,
    scorer_ambiguous_classes,
    scorer_fold_collisions,
)
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES
from llm_dojo_scoring.tasks import normalize_maud_consideration

FIXTURE = Path(__file__).parent / "fixtures" / "maud_valid_classes.json"
FIDUCIARY = "Fiduciary exception:  Board determination (no-shop)"


# --- tiny JSON-Schema validator (no new deps) --------------------------------


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "string":
        return isinstance(value, str)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    raise AssertionError(f"validator does not support type {name}")


def valid(schema: dict[str, Any], value: Any) -> bool:
    import re

    if "enum" in schema and value not in schema["enum"]:
        return False
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            return False
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        return False
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        return False
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        return False
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if any(k not in value for k in schema.get("required", ())):
            return False
        if schema.get("additionalProperties") is False and set(value) - set(props):
            return False
        if any(not valid(props[k], v) for k, v in value.items() if k in props):
            return False
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return False
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            return False
        if "items" in schema and any(not valid(schema["items"], v) for v in value):
            return False
    return True


# --- fixtures ----------------------------------------------------------------


def _gt_labels(pick: int = 0) -> dict[str, dict[str, Any]]:
    """GT-shaped ``maud_clause_labels``: one answer per question + its catalog."""
    return {
        q.name: {
            "answer": q.valid_classes[min(pick, len(q.valid_classes) - 1)],
            "category": q.group,
            "excerpt_chars": 100,
            "label_idx": i,
            "valid_classes": list(q.valid_classes),
        }
        for i, q in enumerate(MAUD_QUESTIONS)
    }


def _doc_fields() -> dict[str, Any]:
    return {
        "document_name": "Agreement and Plan of Merger",
        "parties": ["Acme Parent Inc.", "Acme Merger Sub Inc.", "Target Corp."],
        "effective_date": "2024-01-02",
        "effective_time": "The Effective Time",
        "governing_law": "State of Delaware",
        "merger_consideration": "all_cash",
        "intent": "effect_merger",
        "subject_matter": "Parent acquires Target for cash by merger.",
        "keywords": ["merger", "Effective Time"],
    }


# --- questions vs. catalog ---------------------------------------------------


def test_22_questions_match_hub_keys_in_order():
    assert len(MAUD_QUESTIONS) == 22
    assert tuple(q.name for q in MAUD_QUESTIONS) == tuple(MAUD_QUESTION_KEYS)
    assert all(isinstance(q, MaudQuestion) for q in MAUD_QUESTIONS)


def test_records_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        MAUD_QUESTIONS[0].name = "x"  # type: ignore[misc]


def test_valid_classes_are_exactly_the_catalog_never_invented():
    catalog = maud_question_catalog("merger_agreement")
    for q in MAUD_QUESTIONS:
        assert set(q.valid_classes) <= set(MAUD_ANSWER_CLASSES[q.name])
        assert q.valid_classes == catalog[q.name]
        assert q.valid_classes, q.name


def test_variable_flag_matches_catalog_module():
    assert {q.name for q in MAUD_QUESTIONS if q.variable} == set(MAUD_VARIABLE_CLASS_QUESTIONS)
    assert len(MAUD_VARIABLE_CLASS_QUESTIONS) == 4


def test_every_gt_class_in_fixture_is_representable():
    data = json.loads(FIXTURE.read_text())
    assert set(data["questions"]) == {q.name for q in MAUD_QUESTIONS}
    for name, entry in data["questions"].items():
        q = maud_question(name)
        for cls in entry["classes"]:
            assert cls in q.valid_classes
            assert q.class_for(cls) == cls or q.class_for(cls) in q.valid_classes
            assert parse_maud_clause(f"{name}: {cls}") is not None, (name, cls)
            assert maud_clause_line(name, cls).startswith(name + ": ")


def test_answer_type_is_derived_from_composite_classes():
    multi = {q.name for q in MAUD_QUESTIONS if q.answer_type == "multi_label"}
    assert multi == {
        "Accuracy of Target R&W Closing Condition",
        "FTR Triggers",
        "Limitations on FTR Exercise",
        "MAE Definition",
        "Tail Period & Acquisition Proposal Details",
    }
    for q in MAUD_QUESTIONS:
        assert (q.answer_type == "multi_label") == bool(q.composite_classes)
        assert q.answer_type in ("single_choice", "multi_label")


def test_groups_are_maud_taxonomy_and_cover_all_seven():
    assert {q.group for q in MAUD_QUESTIONS} == set(MAUD_CLAUSE_CATEGORIES)
    assert maud_question("MAE Definition").group == "Material Adverse Effect"
    assert maud_question("Type of Consideration").group == "General Information"


def test_every_question_has_explanation_sections_and_verbatim_options():
    for q in MAUD_QUESTIONS:
        assert q.explanation and q.sections, q.name
        assert q.uncertain == bool(q.note)
        assert q.question.startswith(q.name + ":")
        for cls in q.prompt_classes:
            assert f"  - {cls}\n" in q.question + "\n", (q.name, cls)
    assert any(q.uncertain for q in MAUD_QUESTIONS)


def test_prompt_classes_drop_only_scorer_typo_twins():
    rw = maud_question("Accuracy of Target R&W Closing Condition")
    assert len(rw.valid_classes) - len(rw.prompt_classes) == 2
    assert not any("Fundermental" in c for c in rw.prompt_classes)
    for q in MAUD_QUESTIONS:
        if q is not rw:
            assert q.prompt_classes == q.valid_classes


def test_lookup_is_case_space_and_smart_quote_insensitive():
    assert maud_question(" no-shop ").name == "No-Shop"
    assert maud_question("fiduciary exception: board determination (no-shop)").name == FIDUCIARY
    assert maud_question(FIDUCIARY.upper()).name == FIDUCIARY
    assert maud_question("TAIL PERIOD &  ACQUISITION proposal details").name.startswith("Tail")
    with pytest.raises(KeyError):
        maud_question("Not A Question")


def test_maud_questions_ordering_and_subclass_priority():
    assert [q.name for q in maud_questions()] == list(MAUD_QUESTION_KEYS)
    for sub in MAUD_CONSIDERATION_SUBCLASSES:
        ordered = maud_questions(sub.token)
        assert sorted(q.name for q in ordered) == sorted(MAUD_QUESTION_KEYS)
        assert tuple(q.name for q in ordered[: len(sub.priority_questions)]) == sub.priority_questions
    assert maud_questions("Mixed Cash/Stock: Election")[0].name == "Type of Consideration"
    with pytest.raises(ValueError):
        maud_questions("bogus_subclass")


# --- consideration subclasses --------------------------------------------------


def test_subclass_tokens_match_corpus_and_config():
    tokens = tuple(s.token for s in MAUD_CONSIDERATION_SUBCLASSES)
    assert tokens == tuple(MAUD_CONSIDERATION_TYPES) == DOC_TYPE_SUBCLASSES["merger_agreement"]
    assert len(tokens) == 5
    assert all(s.definition and s.label for s in MAUD_CONSIDERATION_SUBCLASSES)


def test_type_of_consideration_classes_map_to_tokens_per_the_scorer():
    classes = MAUD_ANSWER_CLASSES["Type of Consideration"]
    assert set(MAUD_TYPE_OF_CONSIDERATION_TO_TOKEN) == set(classes)
    for cls, token in MAUD_TYPE_OF_CONSIDERATION_TO_TOKEN.items():
        assert normalize_maud_consideration(cls) == token
        assert consideration_subclass(cls).token == token
    by_token = {s.token: s for s in MAUD_CONSIDERATION_SUBCLASSES}
    assert by_token["other"].maud_class is None  # the Hub has no 'Other' class
    assert {t for t, s in by_token.items() if s.maud_class} == set(tokens_without_other())


def tokens_without_other() -> list[str]:
    return [t for t in MAUD_CONSIDERATION_TYPES if t != "other"]


def test_family_equivalence_matches_scorer():
    by_token = {s.token: s for s in MAUD_CONSIDERATION_SUBCLASSES}
    assert by_token["mixed_cash_stock"].equivalent_to == ("mixed_cash_stock_election",)
    assert by_token["mixed_cash_stock_election"].equivalent_to == ("mixed_cash_stock",)
    for a in by_token:
        for b in by_token:
            expected = a == b or b in by_token[a].equivalent_to
            assert subclass_equivalent("merger_agreement", a, b) is expected


def test_entity_hints_are_documentation_only():
    live = dict(DEFAULT_FIELD_TYPES["merger_agreement"])
    hint_names = set()
    for sub in MAUD_CONSIDERATION_SUBCLASSES:
        assert sub.entity_hints
        for hint in sub.entity_hints:
            assert hint.scored is False
            hint_names.add(hint.name)
    assert hint_names.isdisjoint(live)
    assert dict(get_suite("merger_agreement").field_types) == live  # untouched


def test_unknown_subclass_fails_closed():
    with pytest.raises(ValueError):
        consideration_subclass("stock-ish")


# --- entity schema -------------------------------------------------------------


def test_extraction_schema_has_parity_with_scored_field_map():
    assert MergerAgreementExtraction.field_types == DEFAULT_FIELD_TYPES["merger_agreement"]
    assert tuple(f.name for f in MergerAgreementExtraction.fields) == CORPUS_EXTRACTION_FIELDS["merger_agreement"]
    assert dict(get_suite("merger_agreement").field_types) == MergerAgreementExtraction.field_types
    assert len(MergerAgreementExtraction.fields) == 10
    for f in MergerAgreementExtraction.fields:
        assert f.description
        assert f.empty == ([] if f.type.startswith("entity_list") else None)
    assert MergerAgreementExtraction.empty_prediction()["parties"] == []
    assert MergerAgreementExtraction.empty_prediction()["effective_date"] is None


# --- clause lines: render -> parse -> score ------------------------------------


ALL_PAIRS = [(q.name, cls) for q in MAUD_QUESTIONS for cls in q.valid_classes]


def test_pair_count_is_the_catalog_size():
    assert len(ALL_PAIRS) == sum(len(v) for v in MAUD_ANSWER_CLASSES.values()) == 265


@pytest.mark.parametrize("name", [q.name for q in MAUD_QUESTIONS])
def test_every_rendered_line_round_trips_through_the_real_scorer(name):
    q = maud_question(name)
    labels = {name: {"answer": "", "valid_classes": list(q.valid_classes)}}
    for cls in q.valid_classes:
        line = maud_clause_line(name, cls)
        canonical = q.class_for(cls)  # == cls except for the Fundermental typo twins
        assert parse_maud_clause(line) == (name, canonical)
        # the scorer's own parser agrees on question and (verbatim) answer
        parsed = parse_maud_labels([line])
        assert list(parsed) == [name]
        assert parsed[name]["answer"] == canonical
        gt = {name: {**labels[name], "answer": cls}}
        out = score_maud_extraction(gt, [line])
        assert out["maud_question_accuracy"] == 1.0, line
        assert out["maud_clause_presence"] == 1.0, line
        assert out["maud_valid_class_rate"] == 1.0, line


def test_perfect_prediction_built_from_schema_gets_full_credit_via_merger_suite():
    suite = get_suite("merger_agreement")
    labels = _gt_labels()
    expected = {**_doc_fields(), "maud_clause_labels": labels}
    lines = [maud_clause_line(n, rec["answer"]) for n, rec in labels.items()]
    assert len(lines) == 22
    for predicted_maud in (lines, maud_clauses_to_answers(lines)):
        predicted = {**_doc_fields(), "maud_clauses": predicted_maud}
        out = suite.score_document(expected, predicted)
        assert out["maud_question_accuracy"] == 1.0
        assert out["maud_clause_presence"] == 1.0
        assert out["maud_valid_class_rate"] == 1.0
        assert out["n_questions"] == 22 and out["n_ambiguous"] == 0
        assert all(v == 1.0 for v in out["extraction"].field_scores.values())


@pytest.mark.parametrize("pick", [1, 2, 5])
def test_other_gt_answers_also_round_trip_via_object_shape(pick):
    labels = _gt_labels(pick)
    answers = {n: rec["answer"] for n, rec in labels.items()}
    clauses = maud_answers_to_clauses(answers, strict=True)
    out = get_suite("merger_agreement").score_document(
        {**_doc_fields(), "maud_clause_labels": labels},
        {**_doc_fields(), "maud_clauses": clauses},
    )
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_valid_class_rate"] == 1.0


def test_null_answers_are_dropped_before_the_scorer():
    answers = {"No-Shop": "Yes", "Knowledge Definition": None, "MAE Definition": ""}
    assert maud_answers_to_clauses(answers) == ["No-Shop: Yes"]
    assert maud_clauses_to_answers(["No-Shop: Yes", "free text, no colon"]) == {"No-Shop": "Yes"}


def test_answers_to_clauses_strict_and_passthrough():
    assert maud_answers_to_clauses({"No-Shop": "maybe"}) == ["No-Shop: maybe"]
    with pytest.raises(ValueError):
        maud_answers_to_clauses({"No-Shop": "maybe"}, strict=True)
    with pytest.raises(ValueError):
        maud_answers_to_clauses({"Bogus": "Yes"}, strict=True)


@pytest.mark.parametrize(
    "line, expected",
    [
        ("No-Shop: Yes", ("No-Shop", "Yes")),
        ("  - no-shop: yes.", ("No-Shop", "Yes")),
        ('"No-Shop: Strict liability"', ("No-Shop", "Strict liability")),
        ("1. Knowledge Definition: actual knowledge", ("Knowledge Definition", "Actual knowledge")),
        (f"{FIDUCIARY}: Acquisition Proposal only", (FIDUCIARY, "Acquisition Proposal only")),
        ("Fiduciary exception: Board determination (no-shop): None", (FIDUCIARY, "None")),
        ('MAE Definition: "Would"', ("MAE Definition", '"Would"')),
        ("MAE Definition: “Would”", ("MAE Definition", '"Would"')),
        ("Type of Consideration: Mixed Cash/Stock: Election", ("Type of Consideration", "Mixed Cash/Stock: Election")),
        ("Type of Consideration: mixed_cash_stock_election", ("Type of Consideration", "Mixed Cash/Stock: Election")),
        ("Type of Consideration: all_cash", ("Type of Consideration", "All Cash")),
        ("Agreement provides for matching rights in connection with FTR: >5 business days",
         ("Agreement provides for matching rights in connection with FTR", ">5 business days")),
        ("Agreement provides for matching rights in connection with COR: > 5 business days",
         ("Agreement provides for matching rights in connection with COR", "> 5 business days")),
    ],
)
def test_parse_maud_clause_accepts(line, expected):
    assert parse_maud_clause(line) == expected


@pytest.mark.parametrize(
    "line",
    ["", "No-Shop", "No-Shop: maybe", "Bogus: Yes", "per-share cash $10.00",
     "Exchange ratio: 0.5 shares", "Type of Consideration: Other", "Specific Performance: Yes"],
)
def test_parse_maud_clause_rejects_off_vocabulary(line):
    assert parse_maud_clause(line) is None


def test_double_space_name_is_what_the_scorer_needs():
    """Documented drift hazard: the scorer matches the exact double-space prefix."""
    good = f"{FIDUCIARY}: Acquisition Proposal only"
    assert list(parse_maud_labels([good])) == [FIDUCIARY]
    assert maud_clause_line("fiduciary exception: board determination (no-shop)", "None").startswith(
        FIDUCIARY + ":"
    )


def test_scorer_fold_collisions_are_reported_not_hidden():
    collisions = scorer_fold_collisions()
    # The genuine '5' vs '> 5 business days' collision is fixed in maud._fold;
    # only intended equivalences ('> 5' ≡ 'Greater than 5', typo twins) remain.
    for groups in collisions.values():
        for group in groups:
            assert "5 business days" not in group
    cor = collisions["Agreement provides for matching rights in connection with COR"]
    assert ("> 5 business days", "Greater than 5 business days") in cor
    assert set(collisions) <= set(MAUD_QUESTION_KEYS)


def test_scorer_ambiguous_classes_are_catalog_classes():
    flagged = scorer_ambiguous_classes()
    for name, classes in flagged.items():
        assert set(classes) <= set(maud_question(name).valid_classes)
        assert all(" / " in c or " | " in c or " ; " in c for c in classes)


def test_category_mismatches_audit():
    ok = {q.name: {"category": q.group} for q in MAUD_QUESTIONS}
    assert category_mismatches(ok) == []
    bad = {"No-Shop": {"category": "Remedies"}, "Unknown": {"category": "x"}}
    assert category_mismatches(bad) == [("No-Shop", "Deal Protection and Related Provisions", "Remedies")]


# --- prompt block ----------------------------------------------------------------


@pytest.mark.parametrize("shape", ["object", "lines"])
@pytest.mark.parametrize("subclass", [None, "all_cash", "mixed_cash_stock_election", "other"])
def test_block_lists_every_allowed_answer_verbatim(shape, subclass):
    block = render_maud_question_block(subclass, shape=shape)
    assert "[22/22]" in block
    for q in MAUD_QUESTIONS:
        assert q.name in block
        for cls in q.prompt_classes:
            assert f"\n  - {cls}\n" in block + "\n", (q.name, cls)
    assert "Chunk duty" in block and "THIS text" in block
    assert "TWO spaces" in block
    if shape == "object":
        assert "maud_answers" in block and "null" in block
    else:
        assert "maud_clauses" in block and "<Question>: <Answer>" in block
    assert block.count("varies by agreement") == len(MAUD_VARIABLE_CLASS_QUESTIONS)


def test_block_options_and_priority():
    block = render_maud_question_block("all_stock", questions=["Knowledge Definition", "No-Shop"])
    assert "[1/2] Knowledge Definition" in block and "[priority for all_stock deals]" in block
    assert "MAE Definition" not in block
    assert "Chunk duty" not in render_maud_question_block(chunked=False)
    with pytest.raises(ValueError):
        render_maud_question_block(shape="array")  # type: ignore[arg-type]


# --- JSON schema -----------------------------------------------------------------


def _object_prediction(labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "reasoning": {"summary": "s", "entries": [{"field": "parties", "evidence": "e", "section_ref": None}]},
        **_doc_fields(),
        "maud_answers": {n: rec["answer"] for n, rec in labels.items()},
        "confidence": 0.7,
    }


def _lines_prediction(labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pred = _object_prediction(labels)
    del pred["maud_answers"]
    pred["maud_clauses"] = [maud_clause_line(n, rec["answer"]) for n, rec in labels.items()]
    return pred


def test_schema_accepts_gt_shaped_predictions_both_shapes():
    obj_schema = maud_json_schema("object")
    lines_schema = maud_json_schema("lines")
    for pick in (0, 3):
        labels = _gt_labels(pick)
        assert valid(obj_schema, _object_prediction(labels))
        assert valid(lines_schema, _lines_prediction(labels))
    # every single (question, class) pair is accepted in both shapes
    for name, cls in ALL_PAIRS:
        assert valid(obj_schema["properties"]["maud_answers"]["properties"][name], cls)
        assert valid(lines_schema["properties"]["maud_clauses"]["items"], f"{name}: {cls}")
    # unanswered questions
    empty = _object_prediction(_gt_labels())
    empty["maud_answers"] = {q.name: None for q in MAUD_QUESTIONS}
    assert valid(obj_schema, empty)
    none_lines = _lines_prediction(_gt_labels())
    none_lines["maud_clauses"] = []
    assert valid(lines_schema, none_lines)


def test_schema_rejects_off_vocabulary_answers_and_names():
    obj_schema = maud_json_schema("object")
    lines_schema = maud_json_schema("lines")
    labels = _gt_labels()

    paraphrase = _object_prediction(labels)
    paraphrase["maud_answers"]["No-Shop"] = "the company must be very liable"
    assert not valid(obj_schema, paraphrase)

    wrong_question_class = _object_prediction(labels)
    wrong_question_class["maud_answers"]["Specific Performance"] = "Yes"
    assert not valid(obj_schema, wrong_question_class)

    typo_key = _object_prediction(labels)
    typo_key["maud_answers"]["Fiduciary exception: Board determination (no-shop)"] = typo_key["maud_answers"].pop(FIDUCIARY)
    assert not valid(obj_schema, typo_key)

    missing_key = _object_prediction(labels)
    del missing_key["maud_answers"]["No-Shop"]
    assert not valid(obj_schema, missing_key)

    extra = _object_prediction(labels)
    extra["cuad_clauses"] = []
    assert not valid(obj_schema, extra)

    bad_token = _object_prediction(labels)
    bad_token["merger_consideration"] = "All Cash"
    assert not valid(obj_schema, bad_token)

    bad_date = _object_prediction(labels)
    bad_date["effective_date"] = "January 2, 2024"
    assert not valid(obj_schema, bad_date)

    bad_lines = _lines_prediction(labels)
    bad_lines["maud_clauses"][0] = "No-Shop: maybe"
    assert not valid(lines_schema, bad_lines)
    single_space = _lines_prediction(labels)
    single_space["maud_clauses"] = ["Fiduciary exception: Board determination (no-shop): None"]
    assert not valid(lines_schema, single_space)
    dup = _lines_prediction(labels)
    dup["maud_clauses"] = [dup["maud_clauses"][0]] * 2
    assert not valid(lines_schema, dup)
    free_text = _lines_prediction(labels)
    free_text["maud_clauses"] = ["exchange ratio 0.5"]
    assert not valid(lines_schema, free_text)


def test_schema_shapes_keys_and_size():
    obj = maud_json_schema("object")
    lines = maud_json_schema("lines")
    assert "maud_answers" in obj["properties"] and "maud_clauses" not in obj["properties"]
    assert "maud_clauses" in lines["properties"] and "maud_answers" not in lines["properties"]
    assert list(obj["properties"]) == obj["required"]
    assert set(f.name for f in MergerAgreementExtraction.fields) - {"maud_clauses"} <= set(obj["properties"])
    assert len(lines["properties"]["maud_clauses"]["items"]["enum"]) == 265
    assert len(set(lines["properties"]["maud_clauses"]["items"]["enum"])) == 265
    assert len(obj["properties"]["maud_answers"]["required"]) == 22
    # sane grammar size
    assert len(maud_json_schema_text("object")) < 30_000
    assert len(maud_json_schema_text("lines")) < 40_000
    json.loads(maud_json_schema_text("object"))
    # maud-only sub-schema and trace-free variant
    sub = maud_json_schema("object", full=False)
    assert set(sub["properties"]) == set(MAUD_QUESTION_KEYS)
    slim = maud_json_schema("lines", include_trace=False)
    assert "reasoning" not in slim["properties"] and "confidence" not in slim["properties"]
    with pytest.raises(ValueError):
        maud_json_schema("array")  # type: ignore[arg-type]


def test_schema_row_classes_and_question_subset_narrow_the_grammar():
    name = "MAE Definition"
    narrow = maud_json_schema("object", full=False, questions=[name, "No-Shop"], row_classes={name: ["Yes", "No"]})
    assert set(narrow["properties"]) == {name, "No-Shop"}
    assert narrow["properties"][name]["enum"] == ["Yes", "No", None]
    with pytest.raises(ValueError):
        maud_json_schema("object", row_classes={"No-Shop": ["Sometimes"]})
    lines = maud_json_schema("lines", full=False, questions=["Specific Performance"])
    assert lines["items"]["enum"] == [
        'Specific Performance: "entitled to seek" specific performance',
        'Specific Performance: "entitled to" specific performance',
    ]


def test_schema_agrees_with_jsonschema_library_when_installed():
    jsonschema = pytest.importorskip("jsonschema")
    labels = _gt_labels()
    for shape, build in (("object", _object_prediction), ("lines", _lines_prediction)):
        schema = maud_json_schema(shape)
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        assert validator.is_valid(build(labels))
    bad = _object_prediction(labels)
    bad["maud_answers"]["No-Shop"] = "nope"
    assert not jsonschema.Draft202012Validator(maud_json_schema("object")).is_valid(bad)
