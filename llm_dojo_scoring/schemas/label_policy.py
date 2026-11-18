"""What the Dojo scores against: Hub GT without its stale labels, plus the reviewed overlays.

Three label sources reach a score:

1. **Hub ground truth** (``Lucius-Morningstar/mailroom-dataset``). Some of its labels are
   not truth (#164, #171, #94):

   * ``intent`` whose ``intent_source`` is ``heuristic`` (any class). It copies the
     form subclass (``notice`` → ``notice``, ``demand`` → ``payment_demand``) instead
     of naming what the sender wants.
   * ``corporate_record``: ``subject_matter`` in the SEC EDGAR provenance template
     (``"bylaws of <Company> (CIK …) (SEC EDGAR exhibit)…"``), and ``keywords``
     that carry provenance ids (exhibit number, form type, accession, CIK).
   * ``correspondence``: ``subject_matter`` in the ``"Correspondence concerning
     <topic>"`` frame or embedding a topic key, and ``keywords`` with a strong
     metadata token (topic key, timestamp, mail folder path).

   :func:`stale_hub_labels` names them and :func:`drop_stale_hub_labels` removes them.
   :func:`~llm_dojo_scoring.scoring.extraction_scope.scope_extraction_pair` calls it
   before every doc-scorer run and drops the same keys from the prediction, so such a
   field is not a scoring event in either direction. A correct free-text answer is no
   longer a miss against a template.

2. **Interim labels** (schema ``mailroom-interim-labels/v1``). The sandbox builds them
   (``data/labels/interim``) from gate-accepted, grounded extractions; llm-mailroom
   loads the same files (``observability/interim_gt.py``). Each label has a
   ``status``:

   * ``gap_fill`` / ``derived`` — truth. Applied only where the Hub has no label.
   * ``correction`` — truth. Applied only while the Hub value still equals the
     ``hub_value`` it corrects (two blanks are equal: a CUAD contract correction
     fixes the clause-span label while the Hub field is blank). A Hub revision that
     publishes another value wins.
   * ``disputed``, or any label with ``use_as_truth`` false — never applied.

3. **Near-gold labels** (the sandbox's ``data/labels/gold-overlay``; ``basis``
   ``near_gold:*``). Two agreeing passes or an Opus review. Opt-in. They fill only
   fields that neither the Hub nor an interim label covers.

Rules shared by both overlays (:func:`apply_label_overlays`):

* A record binds to the exact text it was read from (``doc_sha256``, the first 16 hex
  of the text's sha256) and to its ``doc_class``. On a mismatch nothing applies.
* A value on a scored enum field must be in the scorer's vocabulary
  (:data:`~.scored_enums.SCORED_ENUM_FIELDS`, and :data:`~.corporate_record_schema.RECORD_TYPES`
  for ``record_type``). A raw subclass such as ``board_resolution`` cannot be gold for
  ``record_type`` because no extraction can emit it.
* A CMS row's ``claim_type`` is ``health`` (llm-mailroom #280). Any other value is
  rejected.
* A null truth label is a documented absence: the field's ``gt_presence`` becomes
  ``schema_documented_absence``. The corporate suite scores that as expected-empty.
  Other classes do not score empty expectations.
* Every applied field is named in :attr:`OverlayMerge.sources`
  (``interim:<status>`` or ``near_gold:<how>``), so a score that used them is never
  read as a Hub-GT score.

Before this module the sandbox and llm-mailroom each applied their own rules. They
disagreed on corrections, null labels and closed vocabularies. Both now call this one
policy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .gt_metadata import GT_PRESENCE_KEY, gt_presence_map, is_empty_value, parse_json_container

__all__ = [
    "INTERIM_LABEL_SCHEMA",
    "INTERIM_TRUTH_STATUSES",
    "NEAR_GOLD_BASIS_PREFIX",
    "OverlayMerge",
    "apply_label_overlays",
    "doc_sha",
    "drop_stale_hub_labels",
    "hub_labels_field",
    "stale_hub_labels",
]

INTERIM_LABEL_SCHEMA = "mailroom-interim-labels/v1"
INTERIM_TRUTH_STATUSES: frozenset[str] = frozenset({"gap_fill", "derived", "correction"})
NEAR_GOLD_BASIS_PREFIX = "near_gold:"

_PENDING = "pending_annotation"
_ABSENT = "schema_documented_absence"
_POPULATED = "populated"
#: Presence codes that mean the Hub row has decided the field (a value, an absence, or
#: out of schema). ``pending_annotation`` is not one: the label was never made.
_DECIDED = frozenset({_POPULATED, _ABSENT, "not_applicable"})
_CMS_TABLES = frozenset({"carrier", "inpatient", "outpatient", "pde"})


def doc_sha(doc_text: str | None) -> str:
    """The short hash that binds an overlay label to its document text (builder's format)."""
    return hashlib.sha256((doc_text or "").encode("utf-8")).hexdigest()[:16]


def _fields(expected: Mapping[str, Any] | str | None) -> dict[str, Any]:
    """A mutable copy of the GT map (a JSON string is parsed; anything else is ``{}``)."""
    if expected is None:
        return {}
    if isinstance(expected, str):
        parsed = parse_json_container(expected)
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return dict(expected)


def _class(doc_class: Any) -> str:
    """The class key, lower-cased (an Enum gives its ``.value``)."""
    return str(getattr(doc_class, "value", doc_class) or "").strip().lower()


def stale_hub_labels(doc_class: Any, expected: Mapping[str, Any] | str | None) -> dict[str, str]:
    """``{field: reason}`` for the Hub labels on this row that are not truth.

    Reasons: ``intent_heuristic``, ``subject_matter_template`` / ``keywords_provenance_ids``
    (corporate records, #164) and ``subject_matter_templated`` / ``keywords_metadata``
    (correspondence, #94). Only fields that carry a value are reported. Unparseable GT
    yields ``{}``. This function never raises on a row's content.
    """
    fields = _fields(expected)
    presence = gt_presence_map(fields)
    cls = _class(doc_class)

    def labelled(name: str) -> bool:
        """The Hub row carries a value for *name* that its presence map does not void."""
        return presence.get(name) not in {"not_applicable", _ABSENT, _PENDING} and not is_empty_value(
            fields.get(name)
        )

    out: dict[str, str] = {}
    if labelled("intent") and str(fields.get("intent_source") or "").strip().lower() == "heuristic":
        out["intent"] = "intent_heuristic"
    if cls == "corporate_record":
        from .corporate_record_schema import _CIK_KEYWORD, _ID_KEYWORD, _TEMPLATE_MARK, _keywords

        if labelled("subject_matter") and _TEMPLATE_MARK in str(fields.get("subject_matter")):
            out["subject_matter"] = "subject_matter_template"
        if labelled("keywords") and any(
            _ID_KEYWORD.match(k.strip()) or _CIK_KEYWORD.search(k) for k in _keywords(fields)
        ):
            out["keywords"] = "keywords_provenance_ids"
    elif cls == "correspondence":
        from .correspondence_gt_audit import _keyword_list, is_templated_subject_matter, metadata_keyword_kind

        try:
            if labelled("subject_matter") and is_templated_subject_matter(fields.get("subject_matter")):
                out["subject_matter"] = "subject_matter_templated"
            if labelled("keywords") and any(
                metadata_keyword_kind(k) == "strong" for k in _keyword_list(fields.get("keywords"))
            ):
                out["keywords"] = "keywords_metadata"
        except (TypeError, ValueError):
            pass  # an unreadable value is the scorer's problem, not a stale-label verdict
    return out


def _write_presence(fields: dict[str, Any], original: Any, presence: Mapping[str, str]) -> None:
    """Store *presence* in the same form (JSON string or mapping) the row used."""
    fields[GT_PRESENCE_KEY] = (
        json.dumps(dict(presence), sort_keys=True) if isinstance(original, str) else dict(presence)
    )


def drop_stale_hub_labels(
    doc_class: Any, expected: Mapping[str, Any] | str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    """``(fields, dropped)``: the GT without its stale labels, and ``{field: reason}``.

    A dropped field's key is removed. If the row has a ``gt_presence`` map, the field's
    code becomes ``pending_annotation`` (unlabelled), so a later overlay may fill it.
    The input is never mutated.
    """
    fields = _fields(expected)
    dropped = stale_hub_labels(doc_class, fields)
    if not dropped:
        return fields, {}
    for name in dropped:
        fields.pop(name, None)
    if GT_PRESENCE_KEY in fields:
        presence = gt_presence_map(fields)
        presence.update(dict.fromkeys(dropped, _PENDING))
        _write_presence(fields, fields[GT_PRESENCE_KEY], presence)
    return fields, dropped


def hub_labels_field(fields: Mapping[str, Any], name: str) -> bool:
    """Whether *fields* already label *name*: a decided presence code, or a value.

    ``pending_annotation`` is unlabelled even with a stored value (as in
    :func:`~.corporate_record_schema.unlabeled_fields`).
    """
    status = gt_presence_map(fields).get(name)
    if status == _PENDING:
        return False
    if status in _DECIDED:
        return True
    return not is_empty_value(fields.get(name))


def _vocabulary(doc_class: str, name: str) -> tuple[str, ...] | None:
    """The scored vocabulary of an enum field, or ``None`` for a free field."""
    if doc_class == "corporate_record" and name == "record_type":
        from .corporate_record_schema import RECORD_TYPES

        return RECORD_TYPES
    from .scored_enums import SCORED_ENUM_FIELDS

    entry = (SCORED_ENUM_FIELDS.get(doc_class) or {}).get(name)
    return entry[0] if entry else None


def _canon(value: Any) -> str:
    """A comparison key: ``""`` for absence, folded whitespace and case for text."""
    if is_empty_value(value):
        return ""
    value = parse_json_container(value)
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _cms_row(fields: Mapping[str, Any], subclass: str) -> bool:
    """Whether the row is a CMS / DE-SynPUF claim (by subclass or ``cms_source_table``)."""
    return subclass in _CMS_TABLES or str(fields.get("cms_source_table") or "").strip().lower() in _CMS_TABLES


@dataclass
class OverlayMerge:
    """The result of :func:`apply_label_overlays`.

    ``fields`` is the expected-field map to score against. ``sources`` names every field
    an overlay supplied (``interim:<status>`` / ``near_gold:<how>``). ``report`` lists
    ``stale`` (Hub label dropped → reason), ``applied`` (field → source), ``superseded``
    (the Hub or an earlier overlay already labels it), ``rejected`` (``field: why``) and
    ``disputed`` (never truth).
    """

    fields: dict[str, Any]
    sources: dict[str, str] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)


def _bound(record: Mapping[str, Any], cls: str, text_sha: str, report: dict[str, Any], tag: str) -> bool:
    """Whether *record* was labelled on this text and class; a mismatch is reported."""
    if record.get("doc_sha256") != text_sha:
        report["rejected"].append(f"{tag}:*: document text differs from the labelled text")
        return False
    rec_cls = _class(record.get("doc_class"))
    if rec_cls and cls and rec_cls != cls:
        report["rejected"].append(f"{tag}:*: overlay class {rec_cls} is not {cls}")
        return False
    return True


def _admissible(cls: str, sub: str, fields: Mapping[str, Any], name: str, value: Any) -> str | None:
    """Why *value* cannot be gold for *name*, or ``None``."""
    if is_empty_value(value):
        return None
    if name == "claim_type" and cls == "insurance_claim" and _cms_row(fields, sub):
        if str(value).strip().lower() != "health":
            return "a CMS row's claim_type is health"
    vocab = _vocabulary(cls, name)
    if vocab is not None:
        if not isinstance(value, str) or value.strip().lower() not in vocab:
            return f"{value!r} is not in the scored {name} vocabulary"
    return None


def apply_label_overlays(
    expected: Mapping[str, Any] | str | None,
    *,
    doc_class: Any,
    doc_text: str | None,
    interim: Mapping[str, Any] | None = None,
    near_gold: Mapping[str, Any] | None = None,
    doc_subclass: Any = None,
) -> OverlayMerge:
    """Hub GT minus its stale labels, plus one document's overlay records.

    *interim* and *near_gold* are one record each (``{"doc_id", "doc_class",
    "doc_sha256", "labels": {field: {...}}}``) or ``None``. Interim labels apply first,
    then near-gold labels fill what is still unlabelled. See the module docstring for the
    rules. The inputs are never mutated.
    """
    cls = _class(doc_class)
    sub = str(doc_subclass or "").strip().lower()
    fields, stale = drop_stale_hub_labels(cls, expected)
    original_presence = fields.get(GT_PRESENCE_KEY)
    presence = gt_presence_map(fields)
    report: dict[str, Any] = {"stale": stale, "applied": {}, "superseded": [], "rejected": [], "disputed": []}
    sources: dict[str, str] = {}
    text_sha = doc_sha(doc_text)

    def put(name: str, value: Any, source: str) -> None:
        """Apply one overlay value and record where it came from."""
        fields[name] = value
        presence[name] = _ABSENT if is_empty_value(value) else _POPULATED
        sources[name] = source
        report["applied"][name] = source

    if interim and _bound(interim, cls, text_sha, report, "interim"):
        for name, lab in sorted((interim.get("labels") or {}).items()):
            status = str(lab.get("status") or "")
            if status not in INTERIM_TRUTH_STATUSES or not lab.get("use_as_truth"):
                report["disputed"].append(name)
                continue
            if status == "correction":
                # Two empties match: a CUAD contract correction fixes the clause-span label
                # while the Hub field itself is blank (``hub_value: null``).
                if _canon(fields.get(name)) != _canon(lab.get("hub_value")):
                    report["superseded"].append(name)
                    continue
            elif hub_labels_field({**fields, GT_PRESENCE_KEY: presence}, name):
                report["superseded"].append(name)
                continue
            why = _admissible(cls, sub, fields, name, lab.get("value"))
            if why:
                report["rejected"].append(f"{name}: {why}")
                continue
            put(name, lab.get("value"), f"interim:{status}")

    if near_gold and _bound(near_gold, cls, text_sha, report, "near_gold"):
        for name, lab in sorted((near_gold.get("labels") or {}).items()):
            basis = str(lab.get("basis") or "")
            if not basis.startswith(NEAR_GOLD_BASIS_PREFIX):
                report["rejected"].append(f"{name}: basis {basis!r} is not near_gold")
                continue
            if hub_labels_field({**fields, GT_PRESENCE_KEY: presence}, name):
                report["superseded"].append(name)
                continue
            why = _admissible(cls, sub, fields, name, lab.get("value"))
            if why:
                report["rejected"].append(f"{name}: {why}")
                continue
            put(name, lab.get("value"), basis)

    if sources and (original_presence is not None or presence):
        _write_presence(fields, original_presence, presence)
    return OverlayMerge(fields=fields, sources=sources, report=report)
