"""Deterministic repair of ``corporate_record`` ground-truth rows.

Fixes only what can be derived from the row itself, never invented:

* ``entity_name`` — the company already named in the template ``subject_matter``
  (``"<subclass> of <Company>  (TICKER)  (CIK 0000000000) (SEC EDGAR exhibit)."``),
  with ticker/CIK stripped; marked ``populated``;
* template ``subject_matter`` → one grounded sentence naming the record and company;
* ``keywords`` — provenance strings (exhibit number, form type, accession, CIK)
  removed; the record phrase and company name kept;
* ``expected_subclass`` — re-assigned when prose ``subject_matter`` unambiguously
  names a different record shape (``subclass_content_conflict``);
* ``record_type`` — the subclass's mapped Hub token (``populated``);
* ``intent`` — set to the subclass pin and ``intent_source`` kept honest
  (``heuristic``/``auto_labeled`` stays: nothing here is human-adjudicated);
* ``gt_presence`` — extended with the subclass's entity fields:
  ``populated`` / ``not_applicable``; every other entity field is **left
  unlabeled** (absent from the map) for real annotation.

:func:`relabel_row` returns a new row plus a change list; it never mutates input.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .corporate_record_schema import (
    ENTITY_CORE_FIELDS,
    _ID_KEYWORD,
    _CIK_KEYWORD,
        _TEMPLATE_MARK,
    _subject_conflicts,
    subclass_schema,
)
from .gt_metadata import gt_presence_map, parse_gt_fields

__all__ = ["relabel_row", "relabel_rows", "company_from_template"]

_TEMPLATE_RE = re.compile(r"^\s*\S+ of (?P<company>.+?)\s*\(CIK\s*\d+\)\s*\(SEC EDGAR exhibit\)", re.S)
_TICKER_RE = re.compile(r"\s*\((?:[A-Z][A-Z0-9.\-]{0,5})\)\s*$")

_PHRASE = {
    "bylaws": "Bylaws",
    "articles_of_incorporation": "Articles of incorporation",
    "certificate_of_formation": "Certificate of formation",
    "charter_amendment": "Charter amendment",
    "powers_of_attorney": "Power of attorney",
    "subsidiary_list": "List of subsidiaries",
    "rights_instrument": "Rights instrument",
    "indenture": "Indenture",
    "board_resolution": "Board resolution",
    "officer_certificate": "Officer certificate",
    "other": "Corporate record",
}


def company_from_template(subject_matter: str) -> str | None:
    """Company named in a template ``subject_matter``; ``None`` when not a template."""
    m = _TEMPLATE_RE.match(subject_matter or "")
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group("company")).strip()
    while True:
        stripped = _TICKER_RE.sub("", name).strip()
        if stripped == name:
            break
        name = stripped
    return name or None


def relabel_row(row: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return ``(new_row, changes)`` for one Hub ground-truth row."""
    new = dict(row)
    changes: list[str] = []
    if row.get("expected") != "corporate_record":
        return new, changes
    gt = parse_gt_fields(row.get("gt_fields") or {})
    presence = dict(gt_presence_map(gt))
    sub = subclass_schema(row.get("expected_subclass")).subclass

    # 1. subclass conflicts (prose subject_matter only)
    conflicts = _subject_conflicts(sub, str(gt.get("subject_matter") or ""))
    if len(conflicts) == 1:
        changes.append(f"expected_subclass:{sub}->{conflicts[0]}")
        sub = conflicts[0]
        new["expected_subclass"] = sub
    schema = subclass_schema(sub)

    # 2. entity_name + subject_matter + keywords from the template
    subject = str(gt.get("subject_matter") or "")
    company = company_from_template(subject)
    if company:
        gt["entity_name"] = company
        presence["entity_name"] = "populated"
        gt["subject_matter"] = f"{_PHRASE[schema.subclass]} of {company}."
        changes += ["entity_name", "subject_matter"]
    kws = gt.get("keywords")
    if isinstance(kws, list):
        own = sub.replace("_", " ")
        kept = [
            k for k in kws
            if not (_ID_KEYWORD.match(str(k).strip()) or _CIK_KEYWORD.search(str(k)))
            and str(k).strip().lower().replace("_", " ") != own
        ]
        if company:
            kept = [_PHRASE[schema.subclass], *kept]
            if company not in kept:
                kept.append(company)
        if kept != kws:
            gt["keywords"] = kept
            changes.append("keywords")

    # record_type is a documented function of the (adjudicated) subclass.
    gt["record_type"] = schema.record_type
    presence["record_type"] = "populated"
    changes.append("record_type")

    # 3. intent pin + presence for inapplicable entity fields
    if gt.get("intent") != schema.intent:
        changes.append(f"intent:{gt.get('intent')}->{schema.intent}")
        gt["intent"] = schema.intent
    for f in ENTITY_CORE_FIELDS:
        if f not in schema.core_applicable:
            presence[f] = "not_applicable"
    out = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in gt.items()}
    out["gt_presence"] = json.dumps(presence, sort_keys=True)
    new["gt_fields"] = json.dumps(out, sort_keys=True)
    return new, changes


def relabel_rows(rows):
    """Relabel every row; yields ``(new_row, changes)``."""
    for row in rows:
        yield relabel_row(row)
