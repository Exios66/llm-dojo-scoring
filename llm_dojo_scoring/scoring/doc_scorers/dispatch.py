"""Compose the scoring tiers for one document.

``score_tiers`` runs tier 0 (``score_common``), then the type module's tier 1/2
extras and headline. The headline swap keeps the field-map score as
``suite_overall_extraction_score`` and marks ``scoring_method`` with ``+<benchmark>``
(``+maud``, ``+cuad``).
"""

from __future__ import annotations

from typing import Any, Mapping

from ..extraction_scope import scope_extraction_pair
from . import get_doc_scorer
from .common import score_common


def score_tiers(
    doc_type: str,
    predicted: Mapping[str, Any] | None,
    expected: Mapping[str, Any] | None,
    *,
    doc_text: str | None = None,
    doc_subclass: str | None = None,
    expected_subclass: str | None = None,
) -> dict[str, Any]:
    """Tier 0 plus the type's extras and headline for one document (no adherence)."""
    scorer = get_doc_scorer(doc_type)
    payload = score_common(
        doc_type,
        predicted,
        expected,
        doc_text=doc_text,
        doc_subclass=doc_subclass,
        expected_subclass=expected_subclass,
        detailed=scorer.detailed,
    )
    raw_expected = expected or {}
    scoped_predicted, _ = scope_extraction_pair(doc_type, predicted or {}, raw_expected)
    sub = scorer.subclass(doc_subclass or expected_subclass)
    extras = scorer.extras(scoped_predicted, raw_expected, subclass=sub, doc_text=doc_text)
    payload.update(extras)
    score, metric = scorer.headline(payload, extras)
    if metric is not None:
        payload["suite_overall_extraction_score"] = payload["overall_extraction_score"]
        payload["overall_extraction_score"] = score
        payload["scoring_method"] = f"{payload['scoring_method']}+{metric.split('_', 1)[0]}"
    return payload
