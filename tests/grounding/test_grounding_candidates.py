"""Review candidates: stable ids, normal forms and review order."""

from __future__ import annotations

import pytest
from grounding_inputs import DOC_TEXT, sample_candidates

from llm_dojo_scoring.grounding.audit import audit_unlabelled_values
from llm_dojo_scoring.grounding.candidates import (
    ReviewCandidate,
    candidate_id,
    normalized_value,
    review_candidates,
)


def _audit(predicted, doc_id="d1", doc_text=DOC_TEXT):
    """Audit one synthetic insurance-claim prediction."""
    return audit_unlabelled_values({}, predicted, doc_class="insurance_claim", doc_text=doc_text,
                                   doc_id=doc_id)


@pytest.mark.parametrize(("field_type", "value", "expected"), [
    ("money", "$1,250.00", "1250.00"),
    ("money", "1250 USD", "1250.00"),
    ("money", "-1.2 million", "1200000.00"),
    ("date", "March 3, 2024", "2024-03-03"),
    ("date", "2024-03-03", "2024-03-03"),
    ("date", "August 2014", "2014-08-?"),
    ("id", "AB-12/34", "ab1234"),
    ("cms_doc_ref", "ab 12.34", "ab1234"),
    ("name", "  Acme   HOLDINGS ", "acme holdings"),
    ("money", "n/a", "n/a"),
])
def test_normalized_value(field_type, value, expected):
    """Each field type has its own normal form; unparseable values fall back to text."""
    assert normalized_value(field_type, value) == expected


def test_ids_are_stable_and_spelling_blind():
    """Re-running gives the same id; two spellings of one amount share it."""
    first = review_candidates(_audit({"claimed_amount": "$1,250.00"}))
    again = review_candidates(_audit({"claimed_amount": "1250 USD"}))
    assert first[0].candidate_id == again[0].candidate_id
    assert first[0].candidate_id == candidate_id("d1", "claimed_amount", "money", "1,250",
                                                 first[0].doc_text_sha256)


def test_ids_depend_on_document_field_and_text():
    """Another document, field or document text gives another id."""
    base = candidate_id("d1", "insurer", "name", "Acme", "h1")
    assert len({base, candidate_id("d2", "insurer", "name", "Acme", "h1"),
                candidate_id("d1", "insured_party", "name", "Acme", "h1"),
                candidate_id("d1", "insurer", "name", "Acme", "h2")}) == 4


def test_list_items_keyed_by_item_not_position():
    """Reordering a list keeps each item's id, and a repeated item is one candidate."""
    one = review_candidates(_audit({"keywords": ["Acme Holdings", "Globex"]}))
    two = review_candidates(_audit({"keywords": ["Globex", "Acme Holdings", "Globex"]}))
    assert {c.candidate_id for c in one} == {c.candidate_id for c in two}
    assert len(two) == 2


def test_review_order_and_priority():
    """not_found first, then unverifiable, then grounded."""
    ordered = list(sample_candidates().values())
    assert [(c.field, c.verdict, c.priority) for c in ordered] == [
        ("adjuster", "not_found", 0),
        ("coverage_determination", "unverifiable", 1),
        ("claimed_amount", "grounded", 2),
    ]


def test_more_frequent_fields_first_within_a_priority():
    """Within one verdict, a field with more candidates is reviewed first."""
    audits = _audit({"adjuster": "Robin Example"}) + _audit({"keywords": ["Globex", "Initech"]})
    assert [c.field for c in review_candidates(audits)] == ["keywords", "keywords", "adjuster"]


def test_doc_id_required():
    """An audit without doc_id cannot become a candidate."""
    with pytest.raises(ValueError, match="doc_id"):
        review_candidates(_audit({"adjuster": "Robin Example"}, doc_id=None))


def test_round_trip():
    """as_dict carries schema_version and from_dict reads it back."""
    candidate = sample_candidates()["adjuster"]
    data = candidate.as_dict()
    assert data["schema_version"] == 1
    assert ReviewCandidate.from_dict(data) == candidate
