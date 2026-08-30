"""Field-scoring tests: scalar scorers, entity lists, factuality audit, and
composite score_extraction (ported behavior)."""

import pytest

from llm_dojo_scoring import field_scoring as fs


# ---------------------------------------------------------------------------
# Scalar scorers
# ---------------------------------------------------------------------------

def test_id_field():
    assert fs.score_id_field("ABC-123", "ABC-123") == 1.0
    assert fs.score_id_field("ABC-123", "ABC-124") == 0.0
    assert fs.score_id_field("", "") == 1.0


def test_money_field():
    assert fs.score_money_field("$250,001", "$250001") == 1.0
    assert fs.score_money_field("$250,001", "$250,000") == 0.0
    assert fs.score_money_field("2M", "$2,000,000") == 1.0
    assert fs.score_money_field("approx. two million", "$2,000,000") >= 0.0


def test_name_field():
    assert fs.score_name_field("Goosehead Insurance Agency, LLC", "Goosehead Insurance Agency LLC") == 1.0
    assert fs.score_name_field("FRANCHISE AGREEMENT", "Goosehead Insurance Agency, LLC Franchise Agreement") == 1.0
    assert fs.score_name_field("BETA", "SOVEREIGN STATE BANK OF OHIO") < 0.8


def test_free_text_field():
    assert fs.score_free_text_field("termination upon 90 days notice", "termination upon 90 days notice") == 1.0
    assert fs.score_free_text_field("", "something") == 0.0


def test_containment_field():
    assert fs.score_containment_field("the laws of the State of Delaware", "the laws of the State of Delaware") == 1.0
    assert fs.score_containment_field("", "the laws of the State of Delaware") == 0.0
    partial = fs.score_containment_field("the State of Delaware", "the laws of the State of Delaware")
    assert 0.0 < partial < 1.0


def test_date_field():
    assert fs.score_date_field("March 3, 2024", "03/03/2024") == 1.0
    assert fs.score_date_field("2024-03-03", "March 3, 2024") == 1.0
    assert fs.score_date_field("March 3, 2024", "March 1, 2024") == 0.67  # within 45 days
    assert fs.score_date_field("March 3, 2024", "2023-01-01") == 0.0
    # blank template expectation: null prediction is CORRECT
    assert fs.score_date_field("", "_____ day of ________, 19____") == 1.0
    assert fs.score_date_field("March 3, 2024", "_____ day of ________, 19____") == 0.0
    # containment: multi-date prediction containing the label's date
    assert fs.score_date_field("Executed March 1, 1996 and November 5, 1996", "November 5, 1996") == 1.0


# ---------------------------------------------------------------------------
# Entity lists
# ---------------------------------------------------------------------------

def test_entity_list_exact():
    score = fs.score_entity_list("name", ["Alpha Corp"], ["Alpha Corp"])
    assert score.f1 == 1.0
    assert score.score == 1.0


def test_entity_list_reorder_and_extra():
    score = fs.score_entity_list(
        "name",
        ["Beta LLC", "Alpha LLC", "Extra Corp"],
        ["Alpha LLC", "Beta LLC"],
    )
    assert score.matched == 2
    assert score.precision == pytest.approx(2 / 3)
    assert score.recall == 1.0


def test_entity_list_empty_sides():
    assert fs.score_entity_list("name", [], []).f1 == 1.0
    assert fs.score_entity_list("name", [], ["a"]).recall == 0.0


def test_entity_list_partial_gt_role_words():
    # partial-GT: role-word label matched by mere presence of a named party
    score = fs.score_entity_list("name", ["Shipper Co."], ["Shipper"], partial_gt=True)
    assert score.score == 1.0  # recall


def test_entity_list_to_dict():
    d = fs.score_entity_list("name", ["A"], ["A"]).to_dict()
    assert d["n_predicted"] == 1
    assert d["matched"] == 1


# ---------------------------------------------------------------------------
# Factuality audit
# ---------------------------------------------------------------------------

def test_audit_list_field_grounded_and_hallucinated():
    doc = "Alpha Corp and Beta LLC agree that the effective date is March 1 2024."
    audit = fs.audit_list_field("free_text", ["Alpha Corp and Beta LLC agree"],
                                ["Alpha Corp and Beta LLC agree"], doc)
    assert audit["verified_precision"] == 1.0
    assert audit["hallucination_rate"] == 0.0

    audit2 = fs.audit_list_field("free_text", ["Completely fabricated clause about unicorns"],
                                 [], doc)
    assert audit2["hallucination_rate"] == 1.0


def test_audit_scalar_field_date():
    doc = "Executed on 04-01-06."
    audit = fs.audit_scalar_field("date", "2006-04-01", "4/1/2006", doc)
    assert audit["true_items"] == 1


def test_verify_list_items():
    doc = "the parties shall terminate upon ninety days notice"
    flags = fs.verify_list_items(["ninety days notice"], doc)
    assert flags == [True]
    flags2 = fs.verify_list_items(["zebra hallucination"], doc)
    assert flags2 == [False]


def test_score_category_presence():
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": "shall not assign", "field": "cuad_clauses"},
        "Non-Existent": {"expected": False, "answer": "", "field": "cuad_clauses"},
    }
    field_types = {"cuad_clauses": "entity_list:free_text"}
    score, detail = fs.score_category_presence(
        {"cuad_clauses": ["Anti-Assignment: party shall not assign any rights"]},
        expectations, field_types,
    )
    assert score == 1.0
    assert detail["Non-Existent"]["expected"] is False


def test_score_category_presence_defaults_field_to_cuad_clauses():
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": "shall not assign"},
    }
    score, detail = fs.score_category_presence(
        {"cuad_clauses": ["shall not assign any rights"]},
        expectations,
        {"cuad_clauses": "entity_list:free_text"},
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["field"] == "cuad_clauses"


def test_disaggregate_clause_spans():
    merged = [
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER PARTY, "
        "ASSIGN THIS AGREEMENT; the Company shall not solicit or hire any employee; "
        "Distributor shall not sell products outside the Territory."
    ]
    spans = fs.disaggregate_clause_spans(merged)
    assert len(spans) == 3
    assert "ASSIGN THIS AGREEMENT" in spans[0]
    assert "solicit or hire any employee" in spans[1]
    assert "outside the Territory" in spans[2]


def test_disaggregate_clause_spans_single_passes_through():
    assert fs.disaggregate_clause_spans(["a single standalone clause"]) == [
        "a single standalone clause"
    ]
    assert fs.disaggregate_clause_spans([]) == []
    assert fs.disaggregate_clause_spans(None) == []


def test_score_category_presence_disaggregated():
    """Issue #21 fix #1/#3: 4 clauses merged into ONE item no longer dilutes
    the match — after disaggregation the labeled clause is contained at 1.0."""
    anti_assignment = (
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER "
        "PARTY, ASSIGN THIS AGREEMENT"
    )
    merged = ";\n".join([
        anti_assignment,
        "the Company shall not solicit or hire any employee of the Distributor",
        "during the Term, Distributor shall not sell products outside the Territory",
        "this Agreement may be terminated by either party upon ninety (90) days written notice",
    ])
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": anti_assignment, "field": "cuad_clauses"},
    }
    field_types = {"cuad_clauses": "entity_list:free_text"}
    score, detail = fs.score_category_presence(
        {"cuad_clauses": [merged]}, expectations, field_types,
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["matched"] is True


def test_score_category_presence_routed_entries():
    """Issue #21 fix #2/#3: a reasoning-trace entry tagged with the canonical
    category name routes its evidence straight to the category evaluator even
    when the checklist item does not cover the label."""
    anti_assignment = (
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER "
        "PARTY, ASSIGN THIS AGREEMENT"
    )
    predicted = {
        "cuad_clauses": ["an unrelated exclusivity provision"],
        "reasoning": {
            "entries": [
                {"field": "Anti-Assignment", "evidence": anti_assignment,
                 "section_ref": "7.1"},
            ]
        },
    }
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": anti_assignment, "field": "cuad_clauses"},
    }
    score, detail = fs.score_category_presence(
        predicted, expectations, {"cuad_clauses": "entity_list:free_text"},
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["matched"] is True



# ---------------------------------------------------------------------------
# Composite score_extraction
# ---------------------------------------------------------------------------

FIELD_TYPES = {
    "document_name": "name",
    "parties": "entity_list:name",
    "effective_date": "date",
    "contract_value": "money",
    "governing_law": "containment",
    "key_obligations": "entity_list:free_text",
}


def test_score_extraction_null_date_rule():
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "A", "effective_date": None},
        {"document_name": "A", "effective_date": "_____ day of ________, 19____"},
    )
    assert result.field_scores["effective_date"] == 1.0
    assert result.overall_score == 1.0


def test_score_extraction_overall_and_ambiguity():
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "Franchise Agreement", "effective_date": "2024-03-01"},
        {"document_name": "Franchise Agreement", "effective_date": "2024-02-15"},
    )
    # name exact (1.0), date within 45 days (0.67) -> ambiguous band
    assert result.field_scores["document_name"] == 1.0
    assert result.field_scores["effective_date"] == 0.67
    assert result.overall_score == pytest.approx(0.835)
    assert result.ambiguous_fields == ["effective_date"]
    assert result.needs_judge_review is True


def test_score_extraction_missing_field_zero():
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "A"},
        {"document_name": "A", "contract_value": "$100,000"},
    )
    assert result.field_scores["contract_value"] == 0.0


def test_score_extraction_entity_list_scores_and_audit():
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"parties": ["Acme LLC"], "key_obligations": ["deliver quarterly reports"]},
        {"parties": ["Acme LLC"]},
        doc_text="Acme LLC shall deliver quarterly reports.",
    )
    assert "parties" in result.entity_list_scores
    assert result.entity_list_scores["parties"].score == 1.0
    assert "key_obligations" in result.entity_list_audit
    assert result.entity_list_audit["key_obligations"]["true_items"] == 1


def test_score_extraction_to_dict_serializable():
    result = fs.score_extraction("contract", FIELD_TYPES,
                                 {"parties": ["Acme"]}, {"parties": ["Acme"]})
    d = result.to_dict()
    assert d["overall_score"] == 1.0
    assert d["entity_list_scores"]["parties"]["f1"] == 1.0


def test_get_field_types_from_taxonomy():
    taxonomy = {"doc_classes": [{"key": "contract", "field_types": {"a": "date"}}]}
    assert fs.get_field_types("contract", taxonomy) == {"a": "date"}
    assert fs.get_field_types("contract") == {}


def test_heuristic_field_type():
    assert fs._heuristic_field_type("effective_date", "x") == "date"
    assert fs._heuristic_field_type("contract_value", "x") == "money"
    assert fs._heuristic_field_type("docket_number", "x") == "id"
    assert fs._heuristic_field_type("note", ["x"]) == "entity_list"