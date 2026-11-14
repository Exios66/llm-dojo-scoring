"""Per-value audit records for unlabelled extracted values.

:func:`audit_unlabelled_values` takes one document's GT row, prediction and source
text, picks the unlabelled values (:mod:`.selection`), and checks each against the
text (:mod:`.verdicts`). A list field is audited item by item. Records carry a
sha256 of the document text, never the text itself.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

from ..schemas.doc_classes import field_types
from ..schemas.gt_metadata import is_empty_value, parse_json_container
from ..scoring.field_scoring import CMS_ROW_FIELD_TYPES, LIST_PREFIX, is_entity_list
from .selection import is_cms_row, unlabelled_fields
from .verdicts import value_verdict

#: Version of the record shape written by ``as_dict``; bump it on any shape change.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class UnlabelledValueAudit:
    """The grounding verdict for one value (or one list item) on an unlabelled field."""

    run_id: str | None
    doc_id: str | None
    doc_class: str
    doc_subclass: str | None
    field: str
    field_type: str
    value: Any
    item_index: int | None
    verdict: str
    coverage: float | None
    gt_status: str
    doc_text_sha256: str | None
    extractor: str | None
    audited_at: float

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnlabelledValueAudit":
        """Rebuild a record from :meth:`as_dict` output; unknown keys are ignored."""
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})


def _text_sha256(doc_text: str | None) -> str | None:
    """Hex sha256 of the UTF-8 document text, or ``None`` without text."""
    if doc_text is None:
        return None
    return hashlib.sha256(str(doc_text).encode("utf-8")).hexdigest()


def _items(value: Any) -> list[Any]:
    """A list prediction as its items (stringified JSON lists are parsed)."""
    parsed = parse_json_container(value)
    return parsed if isinstance(parsed, list) else [parsed]


def _item_value(item: Any) -> Any:
    """The checkable text of one list item: a mapping's or list's string values joined.

    ``{"name": "Bob Co"}`` is checked as ``"Bob Co"`` (keys are not document text); a
    scalar item is returned unchanged.
    """
    if isinstance(item, Mapping):
        parts = item.values()
    elif isinstance(item, (list, tuple)):
        parts = item
    else:
        return item
    return " ".join(str(part) for part in parts if not is_empty_value(part)
                    and not isinstance(part, (Mapping, list, tuple)))


def _element_type(field_type: str) -> str:
    """The item type of an ``entity_list`` field (``name`` when unspecified)."""
    prefix = LIST_PREFIX + ":"
    return field_type[len(prefix):] if field_type.startswith(prefix) else "name"


def audit_unlabelled_values(
    gt_row: Any,
    predicted: Mapping[str, Any],
    *,
    doc_class: str,
    doc_text: str | None,
    doc_subclass: str | None = None,
    run_id: str | None = None,
    doc_id: str | None = None,
    extractor: str | None = None,
) -> list[UnlabelledValueAudit]:
    """Grounding records for every unlabelled value in one document's prediction.

    Records come in registry field order; a list field gives one record per
    non-empty item (``item_index`` set; a mapping or list item is checked by its string
    values), a scalar one record (``item_index=None``). ``predicted`` must be a mapping
    (``TypeError``) and an unknown ``doc_class`` raises ``KeyError``. On a CMS row the
    headline's ``CMS_ROW_FIELD_TYPES`` apply (``supporting_documents`` items are
    ``cms_doc_ref``), as in scoring.
    """
    types = dict(field_types(doc_class))
    if is_cms_row(gt_row, doc_class=doc_class, doc_subclass=doc_subclass):
        types.update({k: v for k, v in CMS_ROW_FIELD_TYPES.items() if k in types})
    selected = unlabelled_fields(gt_row, predicted, doc_class=doc_class, doc_subclass=doc_subclass)
    digest = _text_sha256(doc_text)
    now = time.time()
    records: list[UnlabelledValueAudit] = []

    def record(name: str, ftype: str, value: Any, index: int | None) -> None:
        """Check one value and append its record."""
        verdict, coverage = value_verdict(ftype, value, doc_text)
        records.append(UnlabelledValueAudit(
            run_id=run_id, doc_id=doc_id, doc_class=doc_class, doc_subclass=doc_subclass,
            field=name, field_type=ftype, value=value, item_index=index, verdict=verdict,
            coverage=coverage, gt_status=selected[name], doc_text_sha256=digest,
            extractor=extractor, audited_at=now,
        ))

    for name in selected:
        ftype = types[name]
        if is_entity_list(ftype):
            element = _element_type(ftype)
            for index, item in enumerate(_items(predicted[name])):
                if not is_empty_value(item):
                    record(name, element, _item_value(item), index)
        else:
            record(name, ftype, predicted[name], None)
    return records
