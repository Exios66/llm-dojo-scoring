"""Shared synthetic inputs for the grounding tests (no real documents)."""

from __future__ import annotations

import pytest

#: One synthetic source document; every grounding test reads only this text.
DOC_TEXT = "Invoice AB-12/34 dated March 3, 2024 from Acme Holdings for 1250 dollars."


@pytest.fixture
def doc_text() -> str:
    """The synthetic source document."""
    return DOC_TEXT
