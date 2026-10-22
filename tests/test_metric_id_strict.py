"""#17 remainder: strict metric_id resolver + docs/METRIC_IDS.md ↔ code parity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from llm_dojo_scoring.registry import get_registry
from llm_dojo_scoring.scorecard_honesty import (
    _CLASS_METRIC_IDS,
    _METRIC_ID_BY_NAME,
    UnknownMetricNameError,
    metric_id_for,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "METRIC_IDS.md"
# Headline aliases documented next to their registry name, not registry entries.
_DOCUMENTED_ALIASES = {"overall_score"}


def _section(title: str) -> str:
    """Extract a named level-two section from the metric ID documentation."""
    text = DOC.read_text(encoding="utf-8")
    start = text.index(f"## {title}")
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else None]


def _table_rows(section: str) -> list[list[str]]:
    """Parse Markdown table data cells while omitting the header and separators."""
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:]  # drop header


def _ticks(cell: str) -> list[str]:
    """Extract backtick-delimited identifiers from a documentation table cell."""
    return re.findall(r"`([^`]+)`", cell)


def test_docs_name_table_matches_code():
    """Require documented metric-name mappings to equal the canonical resolver table."""
    documented: dict[str, str] = {}
    for names, mid in _table_rows(_section("Canonical metric_ids")):
        (metric_id,) = _ticks(mid)
        for name in _ticks(names):
            documented[name] = metric_id
    assert documented == _METRIC_ID_BY_NAME


def test_docs_class_table_matches_code():
    """Keep documented class-specific allowed IDs equal to the code mapping."""
    documented = {
        _ticks(cls)[0]: tuple(_ticks(ids))
        for cls, ids in _table_rows(_section("Doc class → allowed metric_ids"))
    }
    assert documented == _CLASS_METRIC_IDS


def test_class_ids_are_canonical():
    """Allow only resolver-defined canonical IDs in document-class metric lists."""
    canonical = set(_METRIC_ID_BY_NAME.values())
    for doc_class, ids in _CLASS_METRIC_IDS.items():
        assert set(ids) <= canonical, doc_class


def test_mapped_names_exist_in_registry():
    """Require resolver names to be registered except for documented headline aliases."""
    names = {m.name for m in get_registry().filter()}
    assert set(_METRIC_ID_BY_NAME) - names <= _DOCUMENTED_ALIASES


@pytest.mark.parametrize("name", sorted(_METRIC_ID_BY_NAME))
def test_every_mapped_name_resolves(name):
    """Resolve registered aliases consistently even when a document class is supplied."""
    assert metric_id_for(name) == _METRIC_ID_BY_NAME[name]
    assert metric_id_for(name, doc_class="insurance_claim") == _METRIC_ID_BY_NAME[name]


@pytest.mark.parametrize(
    ("name", "doc_class"),
    [
        ("schema_valid", "insurance_claim"),  # registry metric, no comparison id
        ("maud_valid_class_rate", "merger_agreement"),  # used to fabricate maud.*
        ("made_up_metric", None),  # used to fabricate pipeline.*
    ],
)
@pytest.mark.parametrize("presence_mode", [False, True])
def test_unmapped_name_raises_instead_of_fabricating(name, doc_class, presence_mode):
    """Raise for unmapped names rather than synthesizing comparison metric IDs."""
    with pytest.raises(UnknownMetricNameError, match=name):
        metric_id_for(name, doc_class=doc_class, presence_mode=presence_mode)


def test_unknown_metric_error_is_a_key_error():
    """Preserve KeyError compatibility for unknown metric names."""
    with pytest.raises(KeyError):
        metric_id_for("made_up_metric")


@pytest.mark.parametrize("name", sorted(_METRIC_ID_BY_NAME))
def test_presence_mode_still_maps_to_cuad(name):
    """Resolve presence-mode metrics to the canonical CUAD clause-presence ID."""
    assert (
        metric_id_for(name, presence_mode=True)
        == "cuad.clause_presence.micro_f1"
    )
