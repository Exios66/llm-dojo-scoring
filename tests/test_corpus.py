"""Corpus alignment — suites match docclass-merged schemas/subclasses/fields.

Pinned to Lucius-Morningstar/docclass-merged ground_truth (1,210 rows).
Network-free: catalogs are in-repo constants derived from that publish.
"""

from __future__ import annotations

from llm_dojo_scoring.config import DOC_CLASS_KEYS
from llm_dojo_scoring.corpus import (
    CORPUS_ABSENT_DOC_TYPES,
    CORPUS_DIFFERENTIATORS,
    CORPUS_DOC_TYPES,
    CORPUS_EXTRACTION_FIELDS,
    CORPUS_SUBCLASS_SURFACES,
    CUAD_CLAUSE_CATEGORIES,
    DOC_TYPE_SUBCLASSES,
    INSURANCE_CLAIM_TYPES,
    MAUD_QUESTION_KEYS,
    NATIVE_DOC_TYPES,
    normalize_corpus_subclass,
    subclass_equivalent,
    suite_schema,
)
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite, suite_for_doc_type


def test_native_doc_types_match_config_and_corpus_union():
    assert set(NATIVE_DOC_TYPES) == set(DOC_CLASS_KEYS)
    assert "insurance_claim" in DOC_CLASS_KEYS
    assert set(CORPUS_DOC_TYPES).isdisjoint(CORPUS_ABSENT_DOC_TYPES)
    assert set(CORPUS_DOC_TYPES) | set(CORPUS_ABSENT_DOC_TYPES) == set(NATIVE_DOC_TYPES)


def test_every_corpus_subclass_surface_normalizes():
    for doc_type, surfaces in CORPUS_SUBCLASS_SURFACES.items():
        allowed = set(DOC_TYPE_SUBCLASSES[doc_type])
        for surface in surfaces:
            key = normalize_corpus_subclass(doc_type, surface)
            assert key in allowed, f"{doc_type}: {surface!r} -> {key!r} not in {sorted(allowed)}"


def test_cuad_folder_labels_normalize_to_canonical_families():
    assert normalize_corpus_subclass("contract", "License_Agreements") == "license"
    assert normalize_corpus_subclass("contract", "Joint Venture _ Filing") == "joint_venture"
    assert normalize_corpus_subclass("contract", "Non_Compete_Non_Solicit") == "non_compete_no_solicit"
    assert normalize_corpus_subclass("contract", "Affiliate_Agreements") == "affiliate"
    assert subclass_equivalent("contract", "Reseller", "distributor")


def test_maud_consideration_and_insurance_source_table_are_distinct():
    assert normalize_corpus_subclass("merger_agreement", "All Cash") == "all_cash"
    assert normalize_corpus_subclass("merger_agreement", "mixed_cash_stock_election") == (
        "mixed_cash_stock_election"
    )
    assert subclass_equivalent("merger_agreement", "mixed_cash_stock", "mixed_cash_stock_election")
    for src in ("carrier", "inpatient", "outpatient", "pde"):
        assert normalize_corpus_subclass("insurance_claim", src) == src
    # product-line claim_type is NOT a subclass
    assert normalize_corpus_subclass("insurance_claim", "health") == "other"
    assert "health" in INSURANCE_CLAIM_TYPES


def test_correspondence_and_corporate_record_subclasses():
    assert normalize_corpus_subclass("correspondence", "attorney_demand") == "attorney_demand"
    assert normalize_corpus_subclass("correspondence", "press_release") == "press_release"
    assert normalize_corpus_subclass("corporate_record", "articles_of_incorporation") == (
        "articles_of_incorporation"
    )
    assert normalize_corpus_subclass("corporate_record", "rights_instrument") == "rights_instrument"


def test_specialist_suite_fields_match_corpus_extraction_schema():
    for doc_type, fields in CORPUS_EXTRACTION_FIELDS.items():
        suite = suite_for_doc_type(doc_type)
        assert suite.doc_type == doc_type
        mapped = DEFAULT_FIELD_TYPES[doc_type]
        assert set(mapped) == set(fields), f"{doc_type}: {sorted(set(mapped) ^ set(fields))}"
        assert set(suite.field_types) == set(fields)
    assert "document_name" in DEFAULT_FIELD_TYPES["contract"]
    assert "document_name" in DEFAULT_FIELD_TYPES["merger_agreement"]


def test_specialist_suites_bind_corpus_subclasses_and_differentiators():
    for doc_type in CORPUS_DOC_TYPES:
        suite = get_suite(doc_type)
        assert suite.in_corpus is True
        assert suite.doc_type == doc_type
        assert tuple(suite.subclasses) == DOC_TYPE_SUBCLASSES[doc_type]
        assert tuple(suite.differentiators) == CORPUS_DIFFERENTIATORS[doc_type]


def test_merger_agreement_rebinds_maud_not_cuad():
    merger = get_suite("merger_agreement")
    contract = get_suite("contracts_specialist")
    assert merger.name == "contracts_specialist"
    assert merger.doc_type == "merger_agreement"
    assert contract.doc_type == "contract"
    assert "all_cash" in merger.subclasses
    assert "license" in contract.subclasses
    assert "all_cash" not in contract.subclasses
    assert "maud_clause_labels" in merger.differentiators
    assert "cuad_clause_labels" in contract.differentiators
    assert merger.honest_gap and "MAUD" in merger.honest_gap


def test_absent_corpus_types_are_honest():
    for doc_type in CORPUS_ABSENT_DOC_TYPES:
        schema = suite_schema(doc_type)
        assert schema["in_corpus"] is False
        assert schema["honest_gap"] and "zero rows" in schema["honest_gap"]
        suite = get_suite(doc_type)
        assert suite.in_corpus is False
        assert suite.subclasses == ()


def test_insurance_gt_fields_are_on_the_suite():
    suite = get_suite("insurance_claim")
    for field in (
        "claim_number", "policy_number", "insurer", "insured_party",
        "claim_type", "date_of_loss", "date_filed", "claimed_amount",
        "damages_description", "coverage_determination", "supporting_documents",
        "adjuster", "denial_reasons",
    ):
        assert field in suite.field_types
    assert suite.field_types["claimed_amount"] == "money"
    assert suite.field_types["date_of_loss"] == "date"
    assert suite.subclasses == ("carrier", "inpatient", "outpatient", "pde")


def test_contract_suite_has_cuad_clause_surface_and_document_name():
    suite = get_suite("contract")
    assert "document_name" in suite.field_types
    assert "extraction_category_presence" in suite.metric_names()
    assert "Parties" in CUAD_CLAUSE_CATEGORIES
    assert "Type of Consideration" in MAUD_QUESTION_KEYS
    assert len(CUAD_CLAUSE_CATEGORIES) == 41


def test_sorter_in_corpus_and_normalizes_across_types():
    sorter = get_suite("sorter")
    assert sorter.in_corpus is True
    assert sorter.task_key == "docclass"
    assert sorter.doc_type is None
    # Without a parent class the sorter must not apply CUAD prefixes.
    assert sorter.normalize_subclass("License_Agreements") == "other"
    assert sorter.normalize_subclass("License_Agreements", doc_type="contract") == "license"
    assert sorter.normalize_subclass("carrier", doc_type="insurance_claim") == "carrier"
    assert sorter.normalize_subclass("all_cash", doc_type="merger_agreement") == "all_cash"
    assert normalize_corpus_subclass("contract", "License_Agreements") == "license"


def test_correspondence_topics_and_cuad_maud_catalogs_are_complete():
    from llm_dojo_scoring.corpus import CORRESPONDENCE_TOPICS, MAUD_CLAUSE_CATEGORIES

    assert len(CORRESPONDENCE_TOPICS) == 11
    assert set(CORRESPONDENCE_TOPICS) == {
        "announcements",
        "energy_market",
        "finance_earnings",
        "general_business",
        "hr_personnel",
        "it_systems",
        "legal_contracts",
        "marketing_clients",
        "regulatory",
        "scheduling",
        "travel_logistics",
    }
    assert len(MAUD_CLAUSE_CATEGORIES) == 7
    assert len(MAUD_QUESTION_KEYS) == 22


def test_suite_schema_export():
    schema = suite_schema("insurance_claim")
    assert schema["in_corpus"] is True
    assert schema["subclasses"] == list(DOC_TYPE_SUBCLASSES["insurance_claim"])
    assert "claim_number" in schema["extraction_fields"]
