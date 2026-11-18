"""The ``DocScorer`` protocol and a base class for per-document-type scorers.

Tier 1 (``extras`` and ``headline``) and tier 2 (``subclass``) live in one module per
document type. Each module defines a ``TypeScorer`` instance and the registry in
``doc_scorers/__init__.py`` collects them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ...config import SUBTYPE_UNKNOWN
from ...schemas.corpus import normalize_corpus_subclass
from ...schemas.gt_metadata import is_empty_value

#: Types whose own normaliser has a first-class unknown bucket (CUAD's "Other / unlisted"),
#: so ``other`` is a valid subclass for them even though the catalogue tuple omits it.
_UNKNOWN_BUCKET_TYPES = frozenset({"contract"})


def clean_subclass(*values: Any) -> str | None:
    """The first subclass value that says something, as stripped text; else ``None``.

    ``None``, blank text, NaN and the literal absence tokens (``"nan"``, ``"none"``,
    ``"null"``, ``"n/a"``) are not a subclass, and one of them does not shadow a later value.
    """
    for value in values:
        if is_empty_value(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


@runtime_checkable
class DocScorer(Protocol):
    """What the dispatcher needs from a document type's scorer."""

    doc_type: str
    subclasses: tuple[str, ...]
    #: Tier-0 suite path: ``True`` forces the detailed path, ``None`` keeps the default rule.
    detailed: bool | None

    def subclass(self, raw: Any) -> str | None:
        """Tier 2: the canonical subclass key for a raw value, or ``None``."""

    def extras(
        self,
        predicted: Mapping[str, Any],
        raw_expected: Mapping[str, Any],
        *,
        subclass: str | None,
        doc_text: str | None,
    ) -> dict[str, Any]:
        """Tier 1: type-specific scores added to the payload."""

    def headline(self, common: Mapping[str, Any], extras: Mapping[str, Any]) -> tuple[float | None, str | None]:
        """Tier 1: ``(score, metric_name)`` replacing the headline, or ``(None, None)``."""


@dataclass(frozen=True)
class TypeScorer:
    """Default per-type scorer: subclass normalisation, no extras, no headline swap."""

    doc_type: str
    subclasses: tuple[str, ...] = ()
    detailed: bool | None = None

    def subclass(self, raw: Any) -> str | None:
        """Normalise ``raw`` through the corpus catalogue.

        ``None`` for types without a catalogue, for a blank value (NaN, ``"nan"``, ``""``) and
        for a value outside the catalogue where the type has no ``other`` bucket (so an
        insurance ``health`` is no subclass rather than an ``other`` the catalogue never lists).
        """
        text = clean_subclass(raw)
        if not self.subclasses or text is None:
            return None
        key = normalize_corpus_subclass(self.doc_type, text)
        if key in self.subclasses or (key == SUBTYPE_UNKNOWN and self.doc_type in _UNKNOWN_BUCKET_TYPES):
            return key
        return None

    def extras(
        self,
        predicted: Mapping[str, Any],
        raw_expected: Mapping[str, Any],
        *,
        subclass: str | None,
        doc_text: str | None,
    ) -> dict[str, Any]:
        """No type-specific extras."""
        return {}

    def headline(self, common: Mapping[str, Any], extras: Mapping[str, Any]) -> tuple[float | None, str | None]:
        """No headline swap."""
        return None, None

    def derived_fields(self, raw_subclass: Any) -> dict[str, str]:
        """Expected fields derived from a row's subclass (ground truth never carries them); none by default."""
        return {}
