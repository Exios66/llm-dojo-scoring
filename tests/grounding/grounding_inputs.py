"""Synthetic grounding inputs: one source document and Hub-shaped GT rows (no real data)."""

from __future__ import annotations

import json
from typing import Any

#: One synthetic source document; every grounding test reads only this text.
DOC_TEXT = "Invoice AB-12/34 dated March 3, 2024 from Acme Holdings for 1250 dollars."

#: The blank text columns every Hub ``ground_truth`` row carries (copied from
#: ``tests/behavior/test_class_headline_contract.py``; test modules never import each other).
_TEXT_COLUMNS = (
    "adjuster", "claim_number", "claim_type", "claimed_amount", "clause_count",
    "content_topic", "coverage_determination", "damages_description",
    "date_filed", "date_of_loss", "insured_party", "insurer", "intent",
    "intent_confidence", "intent_source", "intent_status", "keywords",
    "label_evidence", "maud_label_count", "policy_number", "sentiment_evidence",
    "sentiment_label", "sentiment_score", "subject_matter", "topic_evidence",
)


def hub_row(**labels: Any) -> str:
    """One synthetic ``gt_fields`` value shaped like a Hub ``ground_truth`` row."""
    row: dict[str, Any] = {name: "" for name in _TEXT_COLUMNS}
    row.update(
        cuad_clause_labels="{}",
        maud_clause_labels="{}",
        denial_reasons="[]",
        supporting_documents="[]",
        related_document_ids="[]",
        relationships="[]",
    )
    for name, value in labels.items():
        row[name] = value if isinstance(value, str) else json.dumps(value)
    return json.dumps(row)


def with_presence(gt_fields: str, field: str, status: str) -> str:
    """The same Hub row with ``field`` blanked and ``gt_presence`` giving it ``status``."""
    row = json.loads(gt_fields)
    row[field] = ""
    row["gt_presence"] = json.dumps({field: status})
    return json.dumps(row)
