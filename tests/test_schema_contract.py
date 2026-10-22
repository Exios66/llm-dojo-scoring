"""Empty-field contract guard (SAND-042 insurance schema-valid RCA)."""

from __future__ import annotations

import pytest

pydantic = pytest.importorskip("pydantic")
from pydantic import BaseModel, Field  # noqa: E402

from llm_dojo_scoring.schema_contract import (  # noqa: E402
    contract_empty_payload,
    contract_empty_value,
    contract_violations,
)
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES  # noqa: E402


class _BrokenInsurance(BaseModel):
    """The SAND-042 shape: five scalars non-nullable."""

    claim_number: str | None = None
    policy_number: str | None = None
    insurer: str = ""
    insured_party: str = ""
    claim_type: str = ""
    date_of_loss: str | None = None
    date_filed: str | None = None
    claimed_amount: float | None = None
    adjuster: str | None = None
    damages_description: str = ""
    coverage_determination: str = ""
    denial_reasons: list[str] = Field(default_factory=list)
    supporting_documents: list[str] = Field(default_factory=list)
    intent: str | None = None
    subject_matter: str | None = None
    keywords: list[str] = Field(default_factory=list)
    claim_checklist: list[str] = Field(default_factory=list)


def test_detects_sand042_insurance_nullability_bug():
    """Identify the five nonnullable insurance scalars that violate empty-field contracts."""
    assert contract_violations("insurance_claim", _BrokenInsurance) == [
        "insurer",
        "insured_party",
        "claim_type",
        "damages_description",
        "coverage_determination",
    ]


def test_money_probe_catches_currency_phrase():
    """Accept repaired nullability but flag a currency string in a numeric amount field."""
    class Fixed(_BrokenInsurance):
        """Repair the insurance scalar nullability while preserving the numeric amount type."""
        insurer: str | None = None
        insured_party: str | None = None
        claim_type: str | None = None
        damages_description: str | None = None
        coverage_determination: str | None = None

    assert contract_violations("insurance_claim", Fixed) == []
    assert contract_violations(
        "insurance_claim", Fixed, fields={"claimed_amount": "$18,530.00"}
    ) == ["claimed_amount"]


@pytest.mark.parametrize("doc_type", sorted(DEFAULT_FIELD_TYPES))
def test_empty_payload_covers_field_map(doc_type):
    """Populate every scored field and use empty lists for entity-list fields."""
    payload = contract_empty_payload(doc_type)
    assert set(payload) == set(DEFAULT_FIELD_TYPES[doc_type])
    for field, ftype in DEFAULT_FIELD_TYPES[doc_type].items():
        if ftype.startswith("entity_list"):
            assert payload[field] == []


def test_urgency_never_null():
    """Use routine urgency as the correspondence empty-value sentinel."""
    assert contract_empty_value("correspondence", "urgency") == "routine"


def test_unknown_doc_type_raises():
    """Reject document classes without a supported schema contract."""
    with pytest.raises(KeyError):
        contract_violations("court_opinion", _BrokenInsurance)


class _RequiredNullable(BaseModel):
    """Two required-but-nullable fields: each one-field probe omits the other."""

    insurer: str | None
    insured_party: str | None


def test_missing_other_required_field_is_not_blamed_on_probe():
    """Ignore unrelated missing required fields when probing a nullable field."""
    assert contract_violations("insurance_claim", _RequiredNullable) == []


class _RequiredNonNullable(BaseModel):
    """Model a required nonnullable insurer beside a required nullable insured party."""
    insurer: str
    insured_party: str | None


def test_required_non_nullable_still_flagged():
    """Report a required nonnullable field even when another required field is absent."""
    assert contract_violations("insurance_claim", _RequiredNonNullable) == ["insurer"]
