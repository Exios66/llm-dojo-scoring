#!/usr/bin/env python3
"""Render ``docs/schemas/GT_COVERAGE.md`` from the frozen ground-truth status.

Reads only ``llm_dojo_scoring/schemas/data/extraction_status.json`` (network-free)
and writes, per live class, one row per extraction-schema field: its type,
status, populated rows out of the class's rows, and share, plus the closed
vocabulary values the ground truth never uses.

Usage::

    uv run python scripts/render_gt_coverage.py --write   # regenerate the page
    uv run python scripts/render_gt_coverage.py --check   # exit 1 + diff when it is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from difflib import unified_diff
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_dojo_scoring.schemas import extraction_schemas as _schemas  # noqa: E402
from llm_dojo_scoring.schemas.corpus import cms_source_table as _cms_source_table  # noqa: E402

STATUS_PATH = REPO_ROOT / "llm_dojo_scoring/schemas/data/extraction_status.json"
DOC_PATH = REPO_ROOT / "docs/schemas/GT_COVERAGE.md"
_REGEN = "scripts/build_extraction_status.py --from-hub --commit <40-hex> --revision <tag>"


#: Shown under a class table with fields whose truth is read from a label container.
_CONTAINER_NOTE = (
    "Fields whose truth comes from {sources} show source-container coverage: the count is "
    "the rows whose label container is populated, not the rows that answer that field's own "
    "category."
)


def _n(value: int) -> str:
    """An integer with thousands separators."""
    return f"{value:,}"


def _populated(status: Mapping[str, Any], doc_type: str, spec: Any) -> int:
    """Rows of ``doc_type`` whose ground truth labels the field, summed over its subtypes.

    ``cms_source_table`` is derived on the CMS tables only, so it counts just those
    subtypes.  A CUAD/MAUD-derived field counts rows whose label *container* is populated
    (see :data:`_CONTAINER_NOTE`), not rows that answer its own category.
    """
    by_subtype = status.get("doc_types", {}).get(doc_type, {})
    parts = by_subtype.values()
    if spec.source == "subtype":
        if spec.name == "cms_source_table":
            parts = [p for sub, p in by_subtype.items() if _cms_source_table(doc_type, sub)]
        return sum(int(part["rows"]) for part in parts)
    if spec.source == "other class":
        return 0
    key = spec.name if spec.source == "gt_fields" else spec.source
    return sum(int(part["fields"].get(key, {}).get("populated", 0)) for part in parts)


def _class_section(status: Mapping[str, Any], doc_type: str) -> list[str]:
    """The heading, summary line and field table of one class."""
    schema = _schemas.extraction_schema(doc_type)
    lines = [f"## {doc_type}", ""]
    if not schema.rows:
        return [*lines, "This revision has no ground-truth rows for this class.", ""]
    scored = len(schema.scored_fields)
    lines += [
        f"{_n(schema.rows)} rows; scored now: {scored} of {len(schema.fields)} fields.",
        "",
        "| Field | Field type | Status | Populated / class rows | Share | Truth from | Note |",
        "|:---|:---|:---|---:|---:|:---|:---|",
    ]
    for name, spec in schema.fields.items():
        populated = _populated(status, doc_type, spec)
        share = f"{100 * populated / schema.rows:.1f}%"
        lines.append(
            f"| `{name}` | {spec.field_type} | {spec.status} | {_n(populated)} / {_n(schema.rows)} "
            f"| {share} | {spec.source} | {spec.note} |"
        )
    containers = sorted({s.source for s in schema.fields.values() if s.source in _schemas._LABEL_SOURCES})
    if containers:
        sources = " and ".join(f"`{name}`" for name in containers)
        lines += ["", _CONTAINER_NOTE.format(sources=sources)]
    return [*lines, ""]


def _never_seen(status: Mapping[str, Any]) -> list[str]:
    """The ``Never seen in ground truth`` section: vocabulary values with no GT row."""
    gaps: list[str] = []
    not_applicable: list[str] = []
    outside: list[str] = []
    for doc_type, fields in sorted(status.get("vocabulary", {}).items()):
        schema = _schemas.extraction_schema(doc_type)
        for field, entry in sorted(fields.items()):
            zero = sorted(v for v, n in entry["values"].items() if n == 0)
            spec = schema.fields.get(field)
            if spec is not None and spec.status == "not_applicable":
                not_applicable.append(f"- `{doc_type}.{field}` ({len(entry['values'])} values)")
            elif zero and entry["rows_with_value"] == 0:
                gaps.append(f"- `{doc_type}.{field}`: no row labels this field; all {len(zero)} values unused")
            elif zero:
                gaps.append(f"- `{doc_type}.{field}`: " + ", ".join(f"`{v}`" for v in zero))
            for raw, count in entry.get("outside_vocabulary", {}).items():
                outside.append(f"- `{doc_type}.{field}`: `{raw}` on {_n(count)} rows")
    lines = [
        "## Never seen in ground truth",
        "",
        "Closed-vocabulary values the scorer accepts but no ground-truth row uses. A model can be "
        "asked for them and cannot be scored on them until labels exist.",
        "",
        *(gaps or ["- none"]),
        "",
        "Fields the ground truth marks not applicable to the class (not label gaps):",
        "",
        *(not_applicable or ["- none"]),
        "",
        "Ground-truth values outside the scored vocabulary:",
        "",
        *(outside or ["- none"]),
        "",
    ]
    return lines


def render(status: Mapping[str, Any]) -> str:
    """The coverage page for ``status`` (the parsed ``extraction_status.json``)."""
    with mock.patch.object(_schemas, "_status_data", lambda: status):
        _schemas._cached.cache_clear()
        try:
            lines = [
                "<!-- Generated by scripts/render_gt_coverage.py. Do not edit by hand. -->",
                "",
                "# Ground-truth coverage",
                "",
                "This page is generated from `llm_dojo_scoring/schemas/data/extraction_status.json`. "
                "Regenerate it with `uv run python scripts/render_gt_coverage.py --write`.",
                "",
                f"- Dataset: `{status['dataset']}` (config `{status['config']}`)",
                f"- Revision: `{status['revision']}`",
                f"- Commit: `{status['commit']}`",
                f"- Rows: {_n(int(status['rows']))}",
                "",
                "Every field the dataset populates is scored; there are no label-quality tiers. "
                "Statuses are defined in `llm_dojo_scoring/schemas/extraction_schemas.py`.",
                "",
            ]
            for doc_type in _schemas.MAILROOM_DOC_TYPES:
                lines += _class_section(status, doc_type)
            lines += _never_seen(status)
        finally:
            _schemas._cached.cache_clear()
    lines += [
        "## How to update when labels grow",
        "",
        "```bash",
        f"uv run --extra dev --with pyarrow python {_REGEN}",
        "uv run python scripts/render_gt_coverage.py --write",
        "```",
        "",
        "No code edit is needed for a field to become scored: its status follows the populated "
        "share in the rebuilt status file. Check that `scripts/freeze_goldens.py --check` still "
        "passes, and add a `CHANGELOG.md` entry.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the page")
    mode.add_argument("--check", action="store_true", help="exit 1 with a diff when the page is stale")
    args = parser.parse_args(argv)
    text = render(json.loads(STATUS_PATH.read_text(encoding="utf-8")))
    if args.write:
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {DOC_PATH}")
        return 0
    current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
    if current == text:
        print(f"{DOC_PATH} is current")
        return 0
    diff = unified_diff(
        current.splitlines(keepends=True), text.splitlines(keepends=True), "committed", "rendered"
    )
    sys.stderr.writelines(diff)
    print(f"\n{DOC_PATH} is stale; run scripts/render_gt_coverage.py --write", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
