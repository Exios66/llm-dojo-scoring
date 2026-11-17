"""Drop ground-truth labels the audits flag as untrusted, with ``pending_annotation`` semantics.

Correspondence and corporate-record rows carry auto-generated labels that a correct
extraction cannot match (Dojo #171, #164, #94):

- ``intent`` copied from the form subclass by a heuristic (``intent_source: heuristic``);
- ``subject_matter`` that is a fixed template (``"Correspondence concerning
  general_business."``, ``"bylaws of Acme (SEC EDGAR exhibit)."``);
- ``keywords`` that are filing or mailbox metadata, not document terms.

:func:`filter_untrusted_labels` removes those labels from one row's ground truth so the
field is *unlabelled*: not scored, and a value the model states is not a false positive
(the ``pending_annotation`` rule of :func:`.gt_metadata.scoring_gt_fields`). It reuses the
existing detectors (:mod:`.correspondence_gt_audit`, :func:`.corporate_record_schema.audit_gt_row`)
and invents no new rule. It is opt-in: nothing calls it by default, so scores only change for a
caller that passes a row through it. Pass the returned ground truth to ``suite.score`` /
``score_document`` as usual.

A label whose own provenance says it was adjudicated (``claude_refined``, ``manual``, a human
review) is never filtered, whatever the detectors think of its text.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .corporate_record_schema import audit_gt_row as _audit_corporate_row
from .correspondence_gt_audit import audit_correspondence_gt_row
from .gt_metadata import GT_PRESENCE_KEY, ABSENT_PRESENCE_STATUSES, gt_presence_map, is_empty_value, parse_gt_fields

__all__ = [
    "ADJUDICATED_LABEL_SOURCES",
    "FILTERED_DOC_TYPES",
    "count_untrusted_labels",
    "filter_untrusted_labels",
]

#: Label sources that mean a person or a refinement pass settled the value. A label from
#: one of these (matched case-insensitively, before any ``:`` detail) is never filtered.
ADJUDICATED_LABEL_SOURCES: frozenset[str] = frozenset(
    {"claude_refined", "manual", "human", "human_reviewed", "human_review", "adjudicated", "reviewed"}
)

#: The classes whose labels are filtered. Other classes are returned unchanged.
FILTERED_DOC_TYPES: tuple[str, ...] = ("correspondence", "corporate_record")

_PENDING_ANNOTATION = "pending_annotation"
_FIELDS = ("intent", "subject_matter", "keywords")

#: Detector code -> the field it flags, per class. Correspondence uses the narrower keyword rule
#: ``keywords_all_metadata`` (every keyword is metadata and at least one is strong), not
#: ``keywords_metadata`` (any one strong keyword): a real keyword list that happens to contain
#: one topic key or folder path keeps its label, and only the 5-slot templated shape is dropped.
_CORRESPONDENCE_CODES = {
    "subject_matter_templated": "subject_matter",
    "keywords_all_metadata": "keywords",
}
_CORPORATE_CODES = {
    "subject_matter_template": "subject_matter",
    "keywords_provenance_ids": "keywords",
}


def _is_adjudicated(parsed: Mapping[str, Any], field: str) -> bool:
    """Whether the row's provenance for *field* names an adjudicated source."""
    candidates: list[Any] = [parsed.get(f"{field}_source")]
    if field == "intent":
        candidates.append(parsed.get("intent_status"))
    provenance = parsed.get("provenance")
    if isinstance(provenance, Mapping):
        candidates.append(provenance.get(field))
    for source in candidates:
        token = str(source or "").strip().lower().split(":", 1)[0].strip()
        if token in ADJUDICATED_LABEL_SOURCES:
            return True
    return False


def _usable(parsed: Mapping[str, Any], presence: Mapping[str, str], field: str) -> bool:
    """The field carries a value that is not already absent, pending or not applicable."""
    if presence.get(field) in ABSENT_PRESENCE_STATUSES:
        return False
    return not is_empty_value(parsed.get(field))


def filter_untrusted_labels(
    doc_type: str,
    gt_fields: Mapping[str, Any] | str | None,
    *,
    subclass: Any = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Drop the untrusted ``intent`` / ``subject_matter`` / ``keywords`` labels of one row.

    *doc_type* is ``"correspondence"`` or ``"corporate_record"``; any other class, an empty
    row or ``None`` comes back unchanged with an empty report. *gt_fields* is the Hub ``gt_fields``
    (mapping, JSON or dict-literal string). *subclass* names the corporate subclass when the row
    carries no ``expected_subclass``.

    Flagged, when the field has a usable value and its provenance is not adjudicated:

    - ``intent`` when ``intent_source`` is ``heuristic`` (``intent_heuristic``);
    - ``subject_matter`` when the existing template detector fires
      (correspondence ``subject_matter_templated``, corporate ``subject_matter_template``);
    - ``keywords`` when the metadata detector fires (correspondence ``keywords_all_metadata``,
      corporate ``keywords_provenance_ids``).

    Returns ``(filtered_gt_fields, report)``. ``filtered_gt_fields`` is a new dict (inputs are
    not mutated; JSON-container values are parsed, annotation keys such as ``intent_source`` are
    kept) in which each flagged field's value is removed and, when the row has a ``gt_presence``
    map, marked ``pending_annotation``. A row without that map does not gain one. ``report`` maps
    each filtered field to its reason code. A label whose ``<field>_source``, ``provenance[field]``
    (or, for ``intent``, ``intent_status``) is in :data:`ADJUDICATED_LABEL_SOURCES` is never
    filtered. Malformed *gt_fields* raises ``TypeError`` or ``ValueError`` from
    :func:`.gt_metadata.parse_gt_fields`.
    """
    parsed = parse_gt_fields({} if gt_fields is None else gt_fields)
    if doc_type not in FILTERED_DOC_TYPES or not parsed:
        return parsed, {}
    presence = gt_presence_map(parsed)
    if doc_type == "correspondence":
        defects = audit_correspondence_gt_row(parsed)
        by_field = {_CORRESPONDENCE_CODES[c]: c for c in defects if c in _CORRESPONDENCE_CODES}
    else:
        sub = subclass if subclass is not None else parsed.get("expected_subclass")
        defects = _audit_corporate_row(sub, parsed)
        by_field = {_CORPORATE_CODES[c]: c for c in defects if c in _CORPORATE_CODES}
    if str(parsed.get("intent_source") or "").strip().lower() == "heuristic":
        by_field["intent"] = "intent_heuristic"
    report = {
        field: reason
        for field, reason in by_field.items()
        if field in _FIELDS and _usable(parsed, presence, field) and not _is_adjudicated(parsed, field)
    }
    if not report:
        return parsed, {}
    out = dict(parsed)
    for field in report:
        out.pop(field, None)
    if GT_PRESENCE_KEY in out:
        out[GT_PRESENCE_KEY] = {**presence, **{field: _PENDING_ANNOTATION for field in report}}
    return out, {field: report[field] for field in _FIELDS if field in report}


def count_untrusted_labels(reports: Iterable[Mapping[str, str]]) -> dict[str, int]:
    """Count filtered labels across rows: ``{"<field>:<reason>": n_rows}``.

    *reports* are the second items :func:`filter_untrusted_labels` returned; an empty report
    adds nothing. Keys are sorted, so the result is stable to print or diff.
    """
    counts: dict[str, int] = {}
    for report in reports:
        for field, reason in report.items():
            key = f"{field}:{reason}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
