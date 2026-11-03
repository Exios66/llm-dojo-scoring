"""The per-document-type scorer registry (plan D4)."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.schemas.corpus import (
    CORPUS_ABSENT_DOC_TYPES,
    CORPUS_DOC_TYPES,
    DOC_TYPE_SUBCLASSES,
    NATIVE_DOC_TYPES,
)
from llm_dojo_scoring.scoring.doc_scorers import DOC_SCORERS, DocScorer, get_doc_scorer
from llm_dojo_scoring.scoring.suites import SPECIALIST_DOC_TYPES


@pytest.mark.parametrize("doc_type", NATIVE_DOC_TYPES)
def test_every_native_type_resolves(doc_type):
    """Each native type gets its own scorer, or ``generic`` until it has a module."""
    scorer = get_doc_scorer(doc_type)
    assert isinstance(scorer, DocScorer)
    if doc_type in DOC_SCORERS:
        assert scorer.doc_type == doc_type
    else:
        assert scorer.doc_type == "generic"
    if doc_type in CORPUS_ABSENT_DOC_TYPES:
        assert scorer.doc_type == "generic"


@pytest.mark.parametrize("doc_type", ["", "memo_pad", None])
def test_unknown_type_is_generic(doc_type):
    """Unknown, empty or missing types never fall through."""
    assert get_doc_scorer(doc_type).doc_type == "generic"


@pytest.mark.parametrize("agent, doc_type", sorted(SPECIALIST_DOC_TYPES.items()))
def test_aliases_resolve(agent, doc_type):
    """Specialist agent names and odd casing resolve like the doc type itself."""
    assert get_doc_scorer(agent) is get_doc_scorer(doc_type)
    assert get_doc_scorer(f"  {doc_type.upper()} ") is get_doc_scorer(doc_type)


def test_registry_doc_types_match_subclass_table():
    """Every registered type declares exactly its catalogue subclasses."""
    for doc_type, scorer in DOC_SCORERS.items():
        assert scorer.doc_type == doc_type
        assert scorer.subclasses == DOC_TYPE_SUBCLASSES.get(doc_type, ())


def test_generic_defaults():
    """``generic`` adds nothing on top of tier 0."""
    generic = get_doc_scorer("generic")
    assert generic.subclasses == ()
    assert generic.subclass("anything") is None
    assert generic.extras({"a": 1}, {"a": 1}, subclass=None, doc_text=None) == {}
    assert generic.headline({"overall_extraction_score": 0.5}, {}) == (None, None)


def test_registered_types_are_corpus_types():
    """Only corpus types get modules in 0.27.0; the rest are ``generic``."""
    assert set(DOC_SCORERS) <= set(CORPUS_DOC_TYPES)
