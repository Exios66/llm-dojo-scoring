"""Check one extracted value against the source document text.

A verdict says whether the document supports a value, not whether the value is right:

* ``grounded`` — the document states it (in any format the field type allows);
* ``not_found`` — the value is checkable and the document does not state it;
* ``unverifiable`` — it cannot be checked: no document text, a closed-vocabulary
  ``label`` (inferred, never a literal in the text), or a value with nothing to compare.

Each field type has one rule in :data:`_RULES`; a new type is one new entry. The
matchers are the factuality audit's own (:mod:`llm_dojo_scoring.scoring.field_scoring`),
so a value grounded here is grounded there. Deterministic and network-free.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..scoring.field_scoring import (
    _containment_tokens,
    _date_grounded_in_doc,
    _parse_date_parts,
    _parse_money,
    get_verification_coverage,
)

GROUNDED = "grounded"
NOT_FOUND = "not_found"
UNVERIFIABLE = "unverifiable"

#: Every verdict, in report order.
VERDICTS: tuple[str, ...] = (GROUNDED, NOT_FOUND, UNVERIFIABLE)

#: A rule maps (value, non-blank document text) to (verdict, token coverage or None).
Rule = Callable[[Any, str], "tuple[str, float | None]"]

#: Number-like spans in document text, parsed with ``_parse_money`` for the money rule.
_MONEY_RE = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?(?:\s*[KMB]\b)?")

#: Characters ignored when comparing identifiers ("AB-12/34" == "ab 12 34").
_ID_NOISE_RE = re.compile(r"[\s\-/.]+")

#: Two amounts within half a cent are the same amount.
_MONEY_TOLERANCE = 0.005


def _token_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """Share of the value's content tokens found in the document."""
    value_tokens = _containment_tokens(str(value))
    if not value_tokens:
        return UNVERIFIABLE, None
    coverage = len(value_tokens & _containment_tokens(doc_text)) / len(value_tokens)
    verdict = GROUNDED if coverage >= get_verification_coverage() else NOT_FOUND
    return verdict, coverage


def _date_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """A date the document states in any format; unparseable text falls back to tokens."""
    parts = _parse_date_parts(value)
    if parts is None:
        return _token_rule(value, doc_text)
    return (GROUNDED if _date_grounded_in_doc(parts, doc_text) else NOT_FOUND), None


def _money_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """The same amount anywhere in the document, whatever its symbols or separators."""
    amount = _parse_money(value)
    if amount is None:
        return UNVERIFIABLE, None
    for match in _MONEY_RE.finditer(doc_text):
        found = _parse_money(match.group(0))
        if found is not None and abs(found - amount) <= _MONEY_TOLERANCE:
            return GROUNDED, None
    return NOT_FOUND, None


def _id_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """The identifier as a substring, ignoring case, whitespace and ``-`` ``/`` ``.``."""
    needle = _ID_NOISE_RE.sub("", str(value).casefold())
    if not needle:
        return UNVERIFIABLE, None
    haystack = _ID_NOISE_RE.sub("", doc_text.casefold())
    return (GROUNDED if needle in haystack else NOT_FOUND), None


def _label_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """A closed-vocabulary label is inferred, so the text can neither confirm nor refute it."""
    return UNVERIFIABLE, None


_RULES: dict[str, Rule] = {
    "name": _token_rule,
    "free_text": _token_rule,
    "date": _date_rule,
    "money": _money_rule,
    "id": _id_rule,
    "cms_doc_ref": _id_rule,
    "label": _label_rule,
}


def value_verdict(field_type: str, value: Any, doc_text: str | None) -> tuple[str, float | None]:
    """Verdict for one scalar value of ``field_type`` against ``doc_text``.

    Returns ``(verdict, coverage)``: ``coverage`` is the token share for the token
    rule (``name``, ``free_text``, unparseable dates and unknown types), else ``None``.
    Missing or blank document text is always ``("unverifiable", None)``.
    """
    if doc_text is None or not str(doc_text).strip():
        return UNVERIFIABLE, None
    rule = _RULES.get(field_type, _token_rule)
    return rule(value, str(doc_text))
