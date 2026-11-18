"""Regression tests for the 0.28.0 review follow-ups of issue #127."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.scoring import field_scoring as fs
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

RELATIVE_DATES = [
    "nine months after the date hereof",
    "twelve (12) months after the date of this Agreement",
    "180 days from the Effective Time",
    "six months following the date hereof",
]


@pytest.mark.parametrize("exp", RELATIVE_DATES)
def test_relative_outside_date_scores_as_populated_text(exp):
    """#127 item 1: a relative date is populated text, not a null expectation."""
    assert fs.score_date_field(exp, exp) == 1.0
    assert fs.score_date_field("", exp) == 0.0
    assert fs.score_date_field(exp.upper(), exp) == 1.0


def test_relative_outside_date_in_merger_extraction():
    """#127 item 1: identical relative outside_date is 1.0 and a missing one is 0.0 end to end."""
    exp = {"outside_date": "nine months after the date hereof"}
    types = DEFAULT_FIELD_TYPES["merger_agreement"]
    same = fs.score_extraction("merger_agreement", types, dict(exp), exp)
    missing = fs.score_extraction("merger_agreement", types, {}, exp)
    assert same.field_scores["outside_date"] == 1.0
    assert missing.field_scores["outside_date"] == 0.0


def test_relative_outside_date_wrong_value_is_not_a_match():
    """#127 item 1: a different relative period does not match."""
    exp = "nine months after the date hereof"
    assert fs.score_date_field("twelve months after the date hereof", exp) < 1.0


@pytest.mark.parametrize("label", ["_____ day of ________, 19____", "Effective Date:", "Effective Date"])
def test_blank_template_handling_unchanged(label):
    """#127 item 1: blank-template and bare-label ground truth keep their null semantics."""
    assert fs.score_date_field("", label) == 1.0
    assert fs.score_date_field(label, label) == 0.0


def test_corporate_not_applicable_excludes_every_entity_core_field():
    """#127 item 2: a spurious prediction on any not_applicable core field costs no precision."""
    import json

    from llm_dojo_scoring.schemas.corporate_record_schema import ENTITY_CORE_FIELDS
    from llm_dojo_scoring.scoring.suites import get_suite

    gt = {"intent": "entity_formation", "subject_matter": "Articles of Acme Inc.", "keywords": '["articles"]'}
    gt.update({f: "" for f in ENTITY_CORE_FIELDS})
    gt["gt_presence"] = json.dumps({f: "not_applicable" for f in ENTITY_CORE_FIELDS})
    pred = {"intent": "entity_formation", "subject_matter": "Articles of Acme Inc.", "keywords": ["articles"]}
    pred.update({f: ["Jane Doe"] if f == "signatories" else "spurious" for f in ENTITY_CORE_FIELDS})
    out = get_suite("corporate_records_specialist").score_document(
        gt, pred, doc_subclass="articles_of_incorporation"
    )
    assert out["extraction_precision"] == 1.0
    assert not set(ENTITY_CORE_FIELDS) & set(out["extraction"].field_scores)


def test_contract_parse_compat_keys_are_not_scored_on_the_direct_path():
    """#127 item 3: merger_consideration on a contract is accepted, never scored."""
    types = DEFAULT_FIELD_TYPES["contract"]
    gt = {"document_name": "MSA", "merger_consideration": "all_cash"}
    out = fs.score_extraction("contract", types, {"document_name": "MSA"}, gt)
    assert out.field_scores == {"document_name": 1.0}
    assert out.overall_score == 1.0
    # A stray prediction of the compat key is not scored either.
    out = fs.score_extraction("contract", types, gt, {"document_name": "MSA"})
    assert out.field_scores == {"document_name": 1.0}


def test_contract_parse_compat_keys_do_not_enter_field_micro():
    """#127 item 3: the field-micro counts ignore the compat keys on both sides."""
    from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics

    types = DEFAULT_FIELD_TYPES["contract"]
    gt = {"document_name": "MSA", "merger_consideration": "all_cash", "maud_clauses": ["x"]}
    for exp, pred in ((gt, {"document_name": "MSA"}), ({"document_name": "MSA"}, gt)):
        out = extraction_binary_metrics(exp, pred, field_types=types, doc_class="contract")
        assert out["extraction_precision"] == out["extraction_recall"] == 1.0, out


def test_merger_agreement_still_scores_merger_consideration():
    """#127 item 3: the exemption is contract-only; a merger agreement scores the key."""
    types = DEFAULT_FIELD_TYPES["merger_agreement"]
    out = fs.score_extraction(
        "merger_agreement", types, {}, {"merger_consideration": "all_cash"}
    )
    assert out.field_scores == {"merger_consideration": 0.0}


def test_explicit_field_types_still_score_a_compat_key_for_historical_rescoring():
    """#127 item 3: like retired prompt keys, an explicit field_types entry opts back in."""
    types = {**DEFAULT_FIELD_TYPES["contract"], "merger_consideration": "label"}
    out = fs.score_extraction("contract", types, {}, {"merger_consideration": "all_cash"})
    assert out.field_scores.get("merger_consideration") == 0.0


@pytest.mark.parametrize("value", ["partly approved", "Partly Denied", "partially approved", "partially denied"])
def test_partly_forms_fold_to_partial_coverage(value):
    """#127 item 4: "partly approved/denied" fold to ``partial`` like "partially ..." do."""
    from llm_dojo_scoring.schemas.scored_enums import canonical_label

    assert canonical_label("insurance_claim", "coverage_determination", value) == "partial"


def test_long_pivots_skip_rows_without_category_or_question():
    """#127 item 5: a row with no category / question never creates an empty document."""
    from llm_dojo_scoring.schemas.v10_rows import cuad_labels_from_long, maud_labels_from_long

    assert cuad_labels_from_long([{"document_id": "d1"}]) == {}
    assert cuad_labels_from_long([{"document_id": "d1", "category": ""}]) == {}
    assert maud_labels_from_long([{"document_id": "d1"}]) == {}
    assert maud_labels_from_long([{"document_id": "d1", "question": None}]) == {}
    # A valid row beside an invalid one keeps only the valid label.
    assert cuad_labels_from_long(
        [{"document_id": "d1"}, {"document_id": "d1", "category": "Parties", "start": 1, "text": "A"}]
    ) == {"d1": {"Parties": [{"start": 1, "text": "A"}]}}


def test_party_roles_guided_schema_anchors_the_role():
    """#127 item 6: each party_roles item must read '<party>: <role>' with a known role."""
    import re

    from llm_dojo_scoring.schemas.cuad_schema import CONTRACT_PARTY_ROLES, cuad_json_schema

    items = cuad_json_schema()["properties"]["party_roles"]["items"]
    assert items["minLength"] == 1 and "pattern" in items
    pattern = re.compile(items["pattern"])
    for role in CONTRACT_PARTY_ROLES:
        assert pattern.search(f"Acme Corp.: {role}"), role
    assert pattern.search("Acme: Inc.: licensor")  # a colon inside the party name
    for bad in ("Acme Corp.", "Acme Corp.: ", "Acme Corp.: vendor", "Acme Corp.: licensor and more",
                ": licensor", "Acme Corp.: Licensor"):
        assert not pattern.search(bad), bad


def test_factuality_audit_compares_labels_through_alias_folding():
    """#127 item 7: the audit matches a label alias the label scorer already accepts."""
    out = fs.score_extraction(
        "insurance_claim",
        {"coverage_determination": "label"},
        {"coverage_determination": "covered"},
        {"coverage_determination": "approved"},
        doc_text="The claim was approved.",
    )
    assert out.field_scores["coverage_determination"] == 1.0
    audit = out.entity_list_audit["coverage_determination"]
    assert audit["matched_gt"] == 1 and audit["hallucinated"] == 0


def test_factuality_audit_still_flags_a_wrong_label():
    """#127 item 7: a label that folds onto a different token stays hallucinated."""
    out = fs.score_extraction(
        "insurance_claim",
        {"coverage_determination": "label"},
        {"coverage_determination": "denied"},
        {"coverage_determination": "approved"},
        doc_text="The claim was approved.",
    )
    audit = out.entity_list_audit["coverage_determination"]
    assert audit["matched_gt"] == 0


def _cms_rows():
    """A synthetic CMS carrier row in its legacy (v9) and typed (v10) shapes."""
    presence = {
        "claim_number": "populated", "claim_type": "populated",
        "adjuster": "schema_documented_absence", "denial_reasons": "schema_documented_absence",
    }
    legacy = {
        "claim_number": "887013387879564", "claim_type": "health",
        "adjuster": "", "denial_reasons": "",
        "gt_presence": dict(presence), "expected_subclass": "carrier",
    }
    typed = {
        "document_id": "DOC-0123456789abcdef", "filename": "c.pdf", "subclass": "carrier",
        "source_subclass": "carrier", "content_sha256": "a", "source_content_sha256": "a",
        "claim_number": "887013387879564", "claim_type": "health",
        "adjuster": None, "denial_reasons": [],
        "presence": dict(presence), "evidence": {}, "provenance": {},
    }
    return legacy, typed


def test_v10_cms_row_keeps_the_documented_absent_fields_empty_credit():
    """#127 item 8: a typed CMS row scores its null adjuster / empty denial_reasons like the legacy row."""
    from llm_dojo_scoring.schemas.gt_metadata import scoring_gt_fields
    from llm_dojo_scoring.schemas.v10_rows import gt_from_v10_row

    legacy, typed = _cms_rows()
    types = DEFAULT_FIELD_TYPES["insurance_claim"]
    pred = {"claim_number": "887013387879564", "claim_type": "health", "cms_source_table": "carrier"}
    results = []
    for raw in (legacy, gt_from_v10_row(typed)):
        expected = scoring_gt_fields(raw, field_types=types, doc_type="insurance_claim", subclass="carrier")
        results.append(fs.score_extraction("insurance_claim", types, pred, expected))
    legacy_result, v10_result = results
    assert legacy_result.field_scores["adjuster"] == 1.0  # the legacy row gives the credit
    assert v10_result.field_scores == legacy_result.field_scores
    assert v10_result.overall_score == legacy_result.overall_score


def test_v10_non_cms_row_does_not_gain_documented_absent_keys():
    """#127 item 8: only CMS rows get the empty adjuster; an auto row's null stays absent."""
    from llm_dojo_scoring.schemas.v10_rows import gt_from_v10_row

    _, typed = _cms_rows()
    auto = {**typed, "subclass": "auto", "source_subclass": "auto", "claim_type": "auto"}
    out = gt_from_v10_row(auto)
    assert "adjuster" not in out and "denial_reasons" not in out
    assert gt_from_v10_row(typed)["adjuster"] == ""


def test_converted_cms_row_scores_as_cms_without_a_subclass_keyword():
    """#127 item 9: the converted row's own expected_subclass marks it a CMS row."""
    from llm_dojo_scoring.scoring.suites import get_suite
    from llm_dojo_scoring.schemas.v10_rows import gt_from_v10_row

    legacy, typed = _cms_rows()
    suite = get_suite("insurance_claims_specialist")
    pred = {"claim_number": "887013387879564", "claim_type": "health", "cms_source_table": "carrier",
            "adjuster": "JOHN D."}
    from_row = suite.score_document(gt_from_v10_row(typed), pred)
    with_kw = suite.score_document(gt_from_v10_row(typed), pred, expected_subclass="carrier")
    # A stated adjuster is a false positive on a CMS row; only a derived CMS table sees it.
    assert with_kw["extraction"].field_scores["adjuster"] == 0.0
    assert from_row["extraction"].field_scores == with_kw["extraction"].field_scores
    assert from_row["extraction_precision"] == with_kw["extraction_precision"]


def test_explicit_subclass_keyword_beats_the_rows_own_subclass():
    """#127 item 9: a caller's subclass keyword stays authoritative."""
    from llm_dojo_scoring.scoring.suites import get_suite
    from llm_dojo_scoring.schemas.v10_rows import gt_from_v10_row

    _, typed = _cms_rows()
    suite = get_suite("insurance_claims_specialist")
    pred = {"claim_number": "887013387879564", "claim_type": "health", "adjuster": "JOHN D."}
    out = suite.score_document(gt_from_v10_row(typed), pred, expected_subclass="auto")
    assert "cms_source_table" not in out["extraction"].field_scores


class _StrictContractModel:
    """A producer model that lists only v2 keys and forbids extras (pydantic ``extra='forbid'``)."""

    model_fields = {"document_name": None, "cuad_family": None}

    @classmethod
    def model_validate(cls, payload):
        """Reject any key the model does not declare."""
        extra = set(payload) - set(cls.model_fields)
        if extra:
            raise ValueError(f"extra keys: {sorted(extra)}")
        return cls


@pytest.mark.parametrize("agent", ["contract", "contract_specialist", "contracts_specialist"])
def test_parse_compat_keys_survive_a_lookup_for_the_agent_alias(agent):
    """#127 item 10: the producer-model branch keeps the compat keys for an agent name too."""
    from llm_dojo_scoring.pipeline.sandbox_schema_adherence import schema_keys_for

    keys = schema_keys_for(agent, schema_lookup=lambda _name: _StrictContractModel)
    assert {"merger_consideration", "maud_clauses"} <= keys


@pytest.mark.parametrize("agent", ["contract", "contracts_specialist"])
def test_strict_producer_model_does_not_reject_parse_compat_keys(agent):
    """#127 item 10: a forbid-extras contract model still validates a payload with v1 compat keys."""
    from llm_dojo_scoring.pipeline.sandbox_schema_adherence import assess_extraction_payload

    payload = {"document_name": "MSA", "cuad_family": "license", "merger_consideration": None, "maud_clauses": []}
    out = assess_extraction_payload(payload, agent, schema_lookup=lambda _n: _StrictContractModel)
    assert out["extra_schema_keys"] == []
    assert out["schema_valid"] is True and out["schema_adherence"] == 1.0
    # A genuinely unknown key is still rejected.
    bad = assess_extraction_payload({**payload, "bogus": 1}, agent, schema_lookup=lambda _n: _StrictContractModel)
    assert bad["extra_schema_keys"] == ["bogus"] and bad["schema_valid"] is False
