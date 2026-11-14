"""Which predicted fields are unlabelled, and so audited by the grounding pass.

The one place the rule lives. It reuses the headline's own GT scoping
(:func:`llm_dojo_scoring.schemas.gt_metadata.scoring_gt_fields`): a field is
unlabelled exactly when that scoping leaves it out, so a value is judged either by
the headline (labelled, including labelled empty) or here (unlabelled), never both.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..schemas.corpus import CMS_DOCUMENTED_ABSENT_FIELDS
from ..schemas.doc_classes import field_types
from ..schemas.gt_metadata import (
    CMS_SOURCE_TABLE_KEY,
    gt_presence_map,
    is_empty_value,
    parse_gt_fields,
    scoring_gt_fields,
)
from ..scoring.field_scoring import expected_cms_source_table

ABSENT = "absent"
PENDING_ANNOTATION = "pending_annotation"

#: Why a field is unlabelled: the GT has no such key, or its label backfill has not run.
UNLABELLED_STATUSES: tuple[str, ...] = (ABSENT, PENDING_ANNOTATION)


def unlabelled_fields(
    gt_row: Any,
    predicted: Mapping[str, Any],
    *,
    doc_class: str,
    doc_subclass: str | None = None,
) -> dict[str, str]:
    """``{field: gt_status}`` for each non-empty prediction on an unlabelled field.

    A field qualifies when it is in the class registry, its prediction is not empty,
    and :func:`scoring_gt_fields` drops it (missing key or ``pending_annotation``).
    A blank GT value with no status is labelled empty and never qualifies, and a CMS
    insurance row's ``adjuster`` / ``denial_reasons`` are labelled empty by the CMS
    source schema, whatever their status. Fields come in registry order.

    A row is a CMS row by the headline's own test
    (:func:`~llm_dojo_scoring.scoring.field_scoring.expected_cms_source_table`): a
    ``cms_source_table`` carried by the GT or derived from ``doc_subclass``, and no
    ``claim_type`` other than ``health``.

    ``gt_row`` is a Hub ``gt_fields`` value (JSON string or mapping) or a plain field
    dict; unparseable GT raises like :func:`scoring_gt_fields`. ``predicted`` must be a
    mapping (``TypeError`` otherwise). An unknown ``doc_class`` raises ``KeyError``.
    """
    if not isinstance(predicted, Mapping):
        raise TypeError(f"predicted must be a mapping of field -> value, got {type(predicted).__name__}")
    types = field_types(doc_class)
    scoped = scoring_gt_fields(gt_row, field_types=types, extra_keys=(CMS_SOURCE_TABLE_KEY,),
                               doc_type=doc_class, subclass=doc_subclass)
    presence = gt_presence_map(parse_gt_fields(gt_row))
    is_cms_row = expected_cms_source_table(doc_class, scoped) is not None
    out: dict[str, str] = {}
    for name in types:
        if name in scoped or is_empty_value(predicted.get(name)):
            continue
        if is_cms_row and name in CMS_DOCUMENTED_ABSENT_FIELDS:
            continue
        out[name] = PENDING_ANNOTATION if presence.get(name) == PENDING_ANNOTATION else ABSENT
    return out
