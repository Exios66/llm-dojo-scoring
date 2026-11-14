"""Review candidates: every audited unlabelled value, with a stable id and a priority.

A value found in the text is still not a label (owner rule), so every audited value
becomes a candidate; the verdict only sets its priority. The Dojo exports the
priority; the consumer owns the review queue.

``candidate_id`` is a sha256 over the document id, the field, the value in its field
type's normal form and the document-text hash, so re-running an audit gives the same
ids and two spellings of one value ("$1,250.00" and "1250 USD") are one candidate. A
list item is keyed by the item alone, so list order never changes ids.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, fields
from typing import Any, Iterable, Mapping

from ..scoring.field_scoring import _parse_date_parts
from .audit import SCHEMA_VERSION, UnlabelledValueAudit
from .verdicts import _ID_NOISE_RE, GROUNDED, NOT_FOUND, UNVERIFIABLE, _parse_amount

#: Review order by verdict: lower is reviewed first.
PRIORITY: dict[str, int] = {NOT_FOUND: 0, UNVERIFIABLE: 1, GROUNDED: 2}


def normalized_value(field_type: str, value: Any) -> str:
    """``value`` in its field type's normal form, as used in :func:`candidate_id`.

    Money is the parsed amount (two decimals, sign dropped), a date its stated
    ``year-month-day`` parts (``?`` for an unstated part), an identifier its
    casefolded text without whitespace, ``-``, ``/`` or ``.``; anything else (or a
    value its type cannot parse) is casefolded text with whitespace collapsed.
    """
    if field_type == "money":
        amount = _parse_amount(value)
        if amount is not None:
            return f"{amount:.2f}"
    elif field_type == "date":
        parts = _parse_date_parts(value)
        if parts is not None:
            return "-".join("?" if part is None else f"{part:02d}" for part in parts)
    elif field_type in ("id", "cms_doc_ref"):
        return _ID_NOISE_RE.sub("", str(value).casefold())
    return " ".join(str(value).casefold().split())


def candidate_id(doc_id: str, field: str, field_type: str, value: Any, doc_text_sha256: str | None) -> str:
    """Stable hex id of one value on one field of one document text."""
    key = json.dumps([doc_id, field, normalized_value(field_type, value), doc_text_sha256])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReviewCandidate:
    """One unlabelled value waiting for a person's or a trusted agent's verdict."""

    candidate_id: str
    run_id: str | None
    doc_id: str
    doc_class: str
    doc_subclass: str | None
    field: str
    field_type: str
    value: Any
    item_index: int | None
    verdict: str
    priority: int
    gt_status: str
    doc_text_sha256: str | None
    extractor: str | None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable record, with ``schema_version``."""
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewCandidate":
        """Rebuild a record from :meth:`as_dict` output; unknown keys are ignored."""
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})


def review_candidates(audits: Iterable[UnlabelledValueAudit]) -> list[ReviewCandidate]:
    """One candidate per distinct value, in review order.

    Order: verdict priority (``not_found``, then ``unverifiable``, then
    ``grounded``), then fields with more candidates first, then document, field and
    item. A value audited twice (a re-run, or a list repeating an item) is one
    candidate; the first audit wins. An audit without ``doc_id`` raises
    ``ValueError``: its id would collide across documents.
    """
    by_id: dict[str, ReviewCandidate] = {}
    for audit in audits:
        if not audit.doc_id:
            raise ValueError(f"audit of {audit.doc_class}.{audit.field} has no doc_id; a candidate needs one")
        if audit.verdict not in PRIORITY:
            raise ValueError(f"unknown grounding verdict {audit.verdict!r}")
        cid = candidate_id(audit.doc_id, audit.field, audit.field_type, audit.value, audit.doc_text_sha256)
        if cid in by_id:
            continue
        by_id[cid] = ReviewCandidate(
            candidate_id=cid, run_id=audit.run_id, doc_id=audit.doc_id, doc_class=audit.doc_class,
            doc_subclass=audit.doc_subclass, field=audit.field, field_type=audit.field_type,
            value=audit.value, item_index=audit.item_index, verdict=audit.verdict,
            priority=PRIORITY[audit.verdict], gt_status=audit.gt_status,
            doc_text_sha256=audit.doc_text_sha256, extractor=audit.extractor,
        )
    frequency = Counter((c.doc_class, c.field) for c in by_id.values())
    return sorted(by_id.values(), key=lambda c: (
        c.priority, -frequency[(c.doc_class, c.field)], c.doc_id, c.field,
        -1 if c.item_index is None else c.item_index,
    ))
