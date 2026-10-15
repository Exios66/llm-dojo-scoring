"""MAUD answer-class catalogs — never guess on merger-agreement labels.

Dataset authority: ``Lucius-Morningstar/mailroom-dataset`` config
``ground_truth``; the offline union mirror is
``tests/fixtures/maud_valid_classes.json`` (152 merger rows, scanned
2026-10-04). These tests pin:

* every one of the 22 Hub questions has a fully populated class catalog, per
  document type (``merger_agreement`` and ``contract``);
* the GT record's own ``valid_classes`` is preserved by ``parse_maud_labels``
  and is the authority for validity / normalization;
* unknown questions fail closed instead of "any non-empty text is valid";
* typo / case / quote variants of one class compare equal;
* the corpus union and the fixture agree.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.content_scoring import (
    is_valid_maud_answer,
    normalize_maud_answer,
    parse_maud_labels,
    score_maud_extraction,
)
from llm_dojo_scoring.corpus import MAUD_QUESTION_KEYS
from llm_dojo_scoring.maud import (
    MAUD_ANSWER_CLASSES,
    MAUD_CATALOG_ROWS,
    MAUD_QUESTION_KEYS_BY_DOC_TYPE,
    MAUD_VARIABLE_CLASS_QUESTIONS,
    canonical_maud_class,
    is_maud_class,
    maud_class_index,
    maud_question_catalog,
)

FIXTURE = Path(__file__).parent / "fixtures" / "maud_valid_classes.json"

_RW_QUESTION = "Accuracy of Target R&W Closing Condition"


def test_catalog_fixture_matches_module():
    data = json.loads(FIXTURE.read_text())
    assert data["rows"]["total"] == MAUD_CATALOG_ROWS == 152
    assert set(data["questions"]) == set(MAUD_QUESTION_KEYS)
    for question, entry in data["questions"].items():
        assert tuple(entry["classes"]) == MAUD_ANSWER_CLASSES[question]


def test_every_maud_question_has_a_populated_class_catalog():
    assert len(MAUD_ANSWER_CLASSES) == len(MAUD_QUESTION_KEYS) == 22
    for question in MAUD_QUESTION_KEYS:
        assert MAUD_ANSWER_CLASSES[question], question
    for doc_type in ("merger_agreement", "contract"):
        catalog = maud_question_catalog(doc_type)
        assert set(catalog) == set(MAUD_QUESTION_KEYS)
        assert all(catalog[q] for q in catalog)
    assert set(maud_question_catalog("merger_agreement_specialist")) == set(
        MAUD_QUESTION_KEYS
    )
    assert set(maud_question_catalog("contracts_specialist")) == set(MAUD_QUESTION_KEYS)
    assert set(MAUD_QUESTION_KEYS_BY_DOC_TYPE["merger_agreement"]) == set(
        MAUD_QUESTION_KEYS
    )
    with pytest.raises(KeyError):
        maud_question_catalog("insurance_claim")


def test_variable_class_questions_are_flagged():
    assert set(MAUD_VARIABLE_CLASS_QUESTIONS) == {
        "Accuracy of Target R&W Closing Condition",
        "Limitations on FTR Exercise",
        "MAE Definition",
        "Tail Period & Acquisition Proposal Details",
    }
    data = json.loads(FIXTURE.read_text())
    for question in MAUD_VARIABLE_CLASS_QUESTIONS:
        assert data["questions"][question]["distinct_class_sets"] > 1


def test_parse_maud_labels_preserves_valid_classes():
    labels = parse_maud_labels(
        {
            "No-Shop": {
                "answer": "Strict liability",
                "category": "Deal Protection and Related Provisions",
                "excerpt_chars": 120,
                "label_idx": 3,
                "valid_classes": [
                    "No",
                    "Reasonable standard",
                    "Strict liability",
                    "Yes",
                ],
            }
        }
    )
    rec = labels["No-Shop"]
    assert rec["answer"] == "Strict liability"
    assert rec["valid_classes"] == [
        "No",
        "Reasonable standard",
        "Strict liability",
        "Yes",
    ]


def test_record_valid_classes_are_the_authority_not_the_union():
    # Row-level surface: this row recognizes only Yes/No.
    row_classes = ["Yes", "No"]
    assert is_valid_maud_answer("No-Shop", "Strict liability", row_classes) is False
    assert is_valid_maud_answer("No-Shop", "Yes", row_classes) is True
    # Without the row surface, the union knows Strict liability (still valid).
    assert is_valid_maud_answer("No-Shop", "Strict liability") is True


def test_unknown_question_without_catalog_fails_closed():
    assert is_valid_maud_answer("Some Novel Question", "whatever") is False
    assert is_valid_maud_answer("Some Novel Question", "x", ["x"]) is True


def test_typo_case_and_quote_variants_compare_equal():
    a = "General R&Ws, Capitalization R&Ws, Fundermental/Special R&Ws"
    b = "general r&ws, capitalization r&ws, fundamental/special r&ws"
    assert canonical_maud_class(_RW_QUESTION, a) == canonical_maud_class(
        _RW_QUESTION, b
    )
    assert is_maud_class(_RW_QUESTION, b) is True


def test_component_wise_validity_for_combined_classes():
    assert is_valid_maud_answer("No-Shop", "Yes") is True
    assert is_valid_maud_answer("No-Shop", "yes, no") is True
    assert is_valid_maud_answer("No-Shop", "yes, maybe") is False


def test_yes_no_aliases_only_where_the_surface_has_yes_no():
    assert normalize_maud_answer("No-Shop", "YES") == "yes"
    assert normalize_maud_answer("No-Shop", "true") == "yes"
    # Specific Performance has no Yes/No surface.
    assert is_valid_maud_answer("Specific Performance", "true") is False


def test_perfect_maud_prediction_is_not_penalized_and_paraphrase_is_invalid():
    expected = {
        "Type of Consideration": {
            "answer": "All Cash",
            "category": "General Information",
            "valid_classes": [
                "All Cash",
                "All Stock",
                "Mixed Cash/Stock",
                "Mixed Cash/Stock: Election",
            ],
        },
        "No-Shop": {
            "answer": "Strict liability",
            "category": "Deal Protection and Related Provisions",
            "valid_classes": [
                "No",
                "Reasonable standard",
                "Strict liability",
                "Yes",
            ],
        },
        "Knowledge Definition": {
            "answer": "Actual knowledge",
            "category": "Knowledge",
            "valid_classes": [
                "Actual knowledge",
                "Based on investigation or inquiry",
                "Based on role",
                "Constructive knowledge",
                "No",
                "Yes",
            ],
        },
    }
    perfect = {
        "Type of Consideration": {"answer": "all cash"},
        "No-Shop": {"answer": "strict liability"},
        "Knowledge Definition": {"answer": "Actual knowledge"},
    }
    out = score_maud_extraction(expected, perfect)
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_clause_presence"] == 1.0
    assert out["maud_valid_class_rate"] == 1.0

    paraphrased = dict(perfect)
    paraphrased["No-Shop"] = {"answer": "the company must be very liable"}
    bad = score_maud_extraction(expected, paraphrased)
    assert bad["maud_valid_class_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert bad["per_question"]["No-Shop"]["valid_class_rate"] == 0.0


def test_merger_suite_perfect_maud_row_scores_1():
    suite = get_suite("merger_agreement")
    labels = {
        "Type of Consideration": {
            "answer": "All Stock",
            "category": "General Information",
            "valid_classes": [
                "All Cash",
                "All Stock",
                "Mixed Cash/Stock",
                "Mixed Cash/Stock: Election",
            ],
        },
        "MAE Definition": {
            "answer": "All MAE carveouts",
            "category": "Material Adverse Effect",
            "valid_classes": ["All MAE carveouts", "Some MAE carveouts", "No", "Yes"],
        },
    }
    out = suite.score_document(
        {"maud_clause_labels": labels}, {"maud_clause_labels": labels}
    )
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_clause_presence"] == 1.0
    assert out["maud_valid_class_rate"] == 1.0


@pytest.mark.parametrize("value", [None, "", " \t\n", "...", ", ,"])
def test_empty_or_punctuation_only_answers_are_invalid(value):
    assert not is_maud_class("No-Shop", value)
    assert not is_valid_maud_answer("No-Shop", value)
    assert normalize_maud_answer("No-Shop", value) == ""


@pytest.mark.parametrize(
    "alias, canonical, opposite",
    [("Y", "yes", "No"), ("true", "yes", "No"), ("1", "yes", "No"),
     ("N", "no", "Yes"), ("false", "no", "Yes"), ("0", "no", "Yes")],
)
def test_alias_requires_its_corresponding_row_class(alias, canonical, opposite):
    assert is_valid_maud_answer("No-Shop", alias, [canonical])
    assert normalize_maud_answer("No-Shop", alias, [canonical]) == canonical
    assert not is_valid_maud_answer("No-Shop", alias, [opposite])
    assert normalize_maud_answer("No-Shop", alias, [opposite]) == alias.lower()


def test_class_index_canonicalizes_and_deduplicates_without_mutating_input():
    classes = ["", "...", "  ‘FUNDERMENTAL’  R&Ws ", "'fundamental' R&Ws"]
    original = classes.copy()
    assert maud_class_index(_RW_QUESTION, classes) == {
        "fundamental r ws": "'fundamental' R&Ws",
    }
    assert classes == original
    assert maud_class_index("Unknown question") == {}


@pytest.mark.parametrize("classes", [None, [], ()])
def test_empty_row_catalog_uses_union(classes):
    assert is_valid_maud_answer("No-Shop", "Strict liability", classes)
    assert not is_valid_maud_answer("Unknown question", "Yes", classes)


@pytest.mark.parametrize(
    "value, classes, canonical, valid",
    [
        # A class containing commas must match as a whole, without requiring
        # its fragments to be separate classes.
        ("KNOWN, but consequences unknown, at signing",
         ["Known, but consequences unknown, at signing"],
         "known but consequences unknown at signing", True),
        (" YES , no ", ["Yes", "No"], "yes, no", True),
        ("Yes, maybe", ["Yes", "No"], "yes maybe", False),
        ("true, No", ["Yes", "No"], "true no", False),
        ('“ENTITLED TO” specific performance',
         ['"entitled to" specific performance'], "entitled to specific performance", True),
        ("UNLISTED answer!", ["Yes", "No"], "unlisted answer", False),
    ],
)
def test_class_matching_boundaries(value, classes, canonical, valid):
    assert canonical_maud_class("Custom question", value, classes) == canonical
    assert is_maud_class("Custom question", value, classes) is valid


@pytest.mark.parametrize("doc_type", [
    " CONTRACT ", "Contracts_Specialist", " MERGER_AGREEMENT ",
    "Merger_Agreement_Specialist",
])
def test_catalog_aliases_return_independent_dicts(doc_type):
    catalog = maud_question_catalog(doc_type)
    assert catalog == MAUD_ANSWER_CLASSES
    catalog.pop("No-Shop")
    assert "No-Shop" in maud_question_catalog(doc_type)


@pytest.mark.parametrize("doc_type", [None, "", "merger", "contracts", "unknown"])
def test_invalid_document_types_fail_closed(doc_type):
    with pytest.raises(KeyError, match="unknown MAUD document type"):
        maud_question_catalog(doc_type)


@pytest.mark.parametrize("container", ["mapping", "json", "records", "tuple"])
def test_parser_preserves_classes_across_supported_record_formats(container):
    record = {"answer": [None, "", "Yes"], "valid_classes": [None, "", "Yes", "No"]}
    if container in ("mapping", "json"):
        payload = {"no shop": record}
        if container == "json":
            payload = json.dumps(payload)
    else:
        payload = [{"question": "no shop", **record}]
        if container == "tuple":
            payload = tuple(payload)
    original = deepcopy(payload)
    assert parse_maud_labels(payload) == {
        "No-Shop": {"answer": "Yes", "category": "", "valid_classes": ["Yes", "No"]},
    }
    assert payload == original


@pytest.mark.parametrize("classes, expected", [
    ("Strict liability", ["Strict liability"]),
    (("Yes", 1, None, ""), ["Yes", "1"]),
    ([], None), (None, None), ([None, ""], None),
])
def test_parser_filters_class_entries_and_keeps_scalar_class_whole(classes, expected):
    result = parse_maud_labels({"No-Shop": {"answer": "Yes", "valid_classes": classes}})
    assert result["No-Shop"].get("valid_classes") == expected
    if expected is None:
        assert "valid_classes" not in result["No-Shop"]


@pytest.mark.parametrize("second_answer", ["YES", "No"])
def test_repeated_keys_union_classes_in_first_seen_order(second_answer):
    records = [
        {"question": "No-Shop", "answer": "Yes", "valid_classes": ["Yes", "No"]},
        {"key": "no shop", "answer": second_answer,
         "valid_classes": ["No", "Strict liability", "Strict liability"]},
        {"question": "No-Shop", "answer": "Yes"},
    ]
    original = deepcopy(records)
    result = parse_maud_labels(records)["No-Shop"]
    assert result["valid_classes"] == ["Yes", "No", "Strict liability"]
    assert result["answer"] == ("Yes" if second_answer == "YES" else ["Yes", "No"])
    assert records == original


def test_scoring_uses_each_rows_catalog_without_leaking_between_documents():
    expected = [
        {"No-Shop": {"answer": "Yes", "valid_classes": ["Yes", "No"]}},
        {"No-Shop": {"answer": "Strict liability", "valid_classes": ["Strict liability"]}},
    ]
    predicted = [{"No-Shop": {"answer": "Strict liability"}}] * 2
    out = score_maud_extraction(expected, predicted)
    assert out["maud_valid_class_rate"] == 0.5
    assert out["maud_question_accuracy"] == 0.5
    assert out["per_question"]["No-Shop"]["valid_class_rate"] == 0.5
    assert [doc["accuracy"] for doc in out["per_document"]] == [0.0, 1.0]


@pytest.mark.parametrize("suite_name", ["contract", "merger_agreement", "contracts_specialist"])
def test_prediction_cannot_override_expected_catalog(suite_name):
    expected = {"maud_clause_labels": {
        "No-Shop": {"answer": "Yes", "valid_classes": ["Yes", "No"]},
    }}
    predicted = {"maud_clause_labels": {
        "No-Shop": {"answer": "Strict liability", "valid_classes": ["Strict liability"]},
    }}
    out = get_suite(suite_name).score_document(expected, predicted)
    assert out["maud_valid_class_rate"] == 0.0
    assert out["maud_question_accuracy"] == 0.0
    assert out["maud_clause_presence"] == 1.0


def test_scoring_normalizes_against_custom_gt_catalog():
    expected = {"Custom question": {"answer": "Yes", "valid_classes": ["Yes"]}}
    out = score_maud_extraction(expected, {"Custom question": "true"})
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_valid_class_rate"] == 1.0


def test_validity_denominator_excludes_missing_ambiguous_and_extra_questions():
    expected = {
        "No-Shop": {"answer": "Yes", "valid_classes": ["Yes", "No"]},
        "Knowledge Definition": {"answer": "Actual knowledge"},
        "MAE Definition": {"answer": "Yes"},
        _RW_QUESTION: {"answer": ["Yes", "No"], "valid_classes": ["Yes", "No"]},
    }
    predicted = {
        "No-Shop": "true", "Knowledge Definition": "invented class",
        _RW_QUESTION: "invented class", "Extra question": "invented class",
    }
    out = score_maud_extraction(expected, predicted)
    assert out["n_questions"] == 3
    assert out["n_present"] == 2
    assert out["n_ambiguous"] == 1
    assert out["maud_valid_class_rate"] == 0.5
    assert out["maud_question_accuracy"] == pytest.approx(1 / 3, abs=1e-4)
    assert out["maud_clause_presence"] == pytest.approx(2 / 3, abs=1e-4)
    assert out["per_question"][_RW_QUESTION]["valid_class_rate"] is None
    assert "Extra question" not in out["per_question"]


@pytest.mark.parametrize("prediction, expected_rate", [({}, None), ({"No-Shop": ""}, 0.0)])
def test_no_prediction_differs_from_present_but_empty_answer(prediction, expected_rate):
    out = score_maud_extraction({"No-Shop": {"answer": "Yes"}}, prediction)
    assert out["maud_valid_class_rate"] == expected_rate
    assert out["maud_question_accuracy"] == 0.0


def test_identical_unknown_answers_do_not_imply_class_validity():
    labels = {"Custom question": {"answer": "Unlisted answer"}}
    out = score_maud_extraction(labels, labels)
    assert out["maud_question_accuracy"] == 1.0
    assert out["maud_valid_class_rate"] == 0.0
