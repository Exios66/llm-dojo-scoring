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
