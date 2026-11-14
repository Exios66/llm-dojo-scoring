"""Check one extracted value against the source document text.

A verdict says whether the document supports a value, not whether the value is right:

* ``grounded`` — the document states it (in any format the field type allows);
* ``not_found`` — the value is checkable and the document does not state it;
* ``unverifiable`` — it cannot be checked: no document text, a closed-vocabulary
  ``label`` (inferred, never a literal in the text), or a value with nothing to compare.

Each field type has one rule in :data:`_RULES`; a new type is one new entry. Names,
text and dates reuse the factuality audit's matchers
(:mod:`llm_dojo_scoring.scoring.field_scoring`); amounts reuse its money parser but
only count document numbers that read as money; identifiers match whole runs of the
text. Per-document work (tokens, amounts, identifier runs) is cached, so auditing many
values of one document scans it once. Deterministic and network-free.
"""

from __future__ import annotations

import re
from functools import lru_cache
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

#: Scale words spelled out ("$1.2 million") become the K/M/B suffix ``_parse_money`` reads.
_SCALE_WORDS = (("thousand", "K"), ("million", "M"), ("billion", "B"))
_SCALE_WORD_RE = re.compile(r"\s*\b(" + "|".join(w for w, _ in _SCALE_WORDS) + r")\b", re.IGNORECASE)

#: An amount in document text: optional currency marker, digits, optional scale and
#: currency word. A marker may stand apart from the number by spaces on the same line
#: ("$ 500", "USD  500", "500  dollars"), never across a line break. Only spans with a
#: money signal count (see :func:`_document_amounts`), so a day, a year or a phone digit
#: group never grounds an amount.
_AMOUNT_RE = re.compile(
    r"(?P<lead>(?:[$€£]|\b(?:USD|EUR|US\$))[ \t\u00a0]*)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>(?-i:[KMB])\b|\s?(?:thousand|million|billion)\b)?"
    r"(?P<tail>[ \t\u00a0]*(?:USD|EUR|dollars?|euros?)\b)?",
    re.IGNORECASE,
)

#: Alphanumeric parts of document text; an identifier is one or more adjacent parts.
_ID_PART_RE = re.compile(r"[A-Za-z0-9]+")

#: Characters ignored when comparing identifiers ("AB-12/34" == "ab 12 34").
_ID_NOISE_RE = re.compile(r"[\s\-/.]+")

#: An identifier spans at most this many adjacent parts ("AB 12 34", "INV-2024-0001").
_ID_MAX_PARTS = 6

#: Shorter normalised identifiers match too much text by chance: ``unverifiable``.
_ID_MIN_CHARS = 3

#: Two amounts within half a cent are the same amount.
_MONEY_TOLERANCE = 0.005


def _spell_scale(text: str) -> str:
    """``"1.2 million"`` -> ``"1.2M"`` so the K/M/B parser reads spelled-out scales."""
    return _SCALE_WORD_RE.sub(lambda m: dict(_SCALE_WORDS)[m.group(1).lower()], text)


def _parse_amount(value: Any) -> float | None:
    """A money value as a non-negative float, or ``None`` when it is not an amount."""
    if isinstance(value, bool):
        return None
    amount = _parse_money(value if isinstance(value, (int, float)) else _spell_scale(str(value)))
    return None if amount is None else abs(amount)


@lru_cache(maxsize=8)
def _document_tokens(doc_text: str) -> frozenset[str]:
    """Content tokens of one document (cached: every value of a document reuses them)."""
    return frozenset(_containment_tokens(doc_text))


@lru_cache(maxsize=8)
def _document_amounts(doc_text: str) -> tuple[float, ...]:
    """Amounts the document states with a money signal.

    A span counts when it has a currency symbol or word, a scale (K/M/B or spelled
    out), a thousands separator, or exactly two decimals; bare integers ("15",
    "2023", "555") never do.
    """
    amounts: list[float] = []
    for match in _AMOUNT_RE.finditer(doc_text):
        number = match.group("num")
        signal = (match.group("lead") or match.group("scale") or match.group("tail")
                  or "," in number or re.search(r"\.\d{2}$", number))
        if not signal:
            continue
        lead = " ".join((match.group("lead") or "").split())
        found = _parse_amount((lead + " " if lead else "") + number + (match.group("scale") or ""))
        if found is not None:
            amounts.append(found)
    return tuple(amounts)


@lru_cache(maxsize=8)
def _document_id_parts(doc_text: str) -> tuple[str, ...]:
    """Casefolded alphanumeric parts of one document, in order."""
    return tuple(part.casefold() for part in _ID_PART_RE.findall(doc_text))


def _token_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """Share of the value's content tokens found in the document."""
    value_tokens = _containment_tokens(str(value))
    if not value_tokens:
        return UNVERIFIABLE, None
    coverage = len(value_tokens & _document_tokens(doc_text)) / len(value_tokens)
    verdict = GROUNDED if coverage >= get_verification_coverage() else NOT_FOUND
    return verdict, coverage


def _date_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """A date the document states in any format; unparseable text falls back to tokens."""
    parts = _parse_date_parts(value)
    if parts is None:
        return _token_rule(value, doc_text)
    return (GROUNDED if _date_grounded_in_doc(parts, doc_text) else NOT_FOUND), None


def _money_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """The same amount stated as money anywhere in the document, whatever its format."""
    amount = _parse_amount(value)
    if amount is None:
        return UNVERIFIABLE, None
    if any(abs(found - amount) <= _MONEY_TOLERANCE for found in _document_amounts(doc_text)):
        return GROUNDED, None
    return NOT_FOUND, None


def _id_rule(value: Any, doc_text: str) -> tuple[str, float | None]:
    """The identifier as one or more whole adjacent alphanumeric parts of the text.

    Case and separators are ignored: ``"AB-12/34"`` matches ``"ab 12 34"`` and
    ``"AB1234"``, and ``"12345"`` matches the number part of ``"INV-12345"`` or
    ``"No.12345"``. A part is never split, so ``"12"`` never matches inside ``"2012"``.
    Identifiers shorter than three characters are ``unverifiable``.
    """
    needle = _ID_NOISE_RE.sub("", str(value).casefold())
    if len(needle) < _ID_MIN_CHARS:
        return UNVERIFIABLE, None
    parts = _document_id_parts(doc_text)
    for start, first in enumerate(parts):
        if not needle.startswith(first):
            continue
        joined = ""
        for part in parts[start:start + _ID_MAX_PARTS]:
            joined += part
            if joined == needle:
                return GROUNDED, None
            if not needle.startswith(joined):
                break
    return NOT_FOUND, None


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
