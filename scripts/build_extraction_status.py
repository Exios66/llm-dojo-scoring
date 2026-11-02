#!/usr/bin/env python3
"""Freeze per-field GT status for every (document type, subtype) of the corpus.

Reads the ``ground_truth`` parquet of ``Lucius-Morningstar/mailroom-dataset``
and writes ``llm_dojo_scoring/schemas/data/extraction_status.json``: for each of
the five mailroom classes and each canonical subtype, the row count and, per
field, how many rows carry it as ``populated``, ``schema_documented_absence``,
``not_applicable`` or ``pending_annotation`` (``gt_presence``), plus label-source
coverage for the CUAD / MAUD derived fields. The extraction-schema registry
(:mod:`llm_dojo_scoring.schemas.extraction_schemas`) classifies fields from it.

Usage (pyarrow is not a Dojo dependency)::

    uv run --extra dev --with pyarrow python scripts/build_extraction_status.py \\
        --parquet-dir path/to/parquet/ground_truth --revision v9.2.1 \\
        --commit 0a2f829248525cf434ed49e38c3ac43b05090ba6

``--check`` rebuilds in memory and exits 1 when the tracked file differs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from llm_dojo_scoring.schemas.corpus import normalize_corpus_subclass
from llm_dojo_scoring.schemas.gt_metadata import (
    ANNOTATION_KEYS,
    gt_presence_map,
    is_empty_value,
    parse_gt_fields,
)

OUT_PATH = Path(__file__).resolve().parents[1] / "llm_dojo_scoring/schemas/data/extraction_status.json"
DATASET = "Lucius-Morningstar/mailroom-dataset"
FIVE = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")
#: Label sources the derived fields read; their coverage is recorded per subtype.
LABEL_SOURCES = ("cuad_clause_labels", "maud_clause_labels")


def _rows(parquet_dir: Path) -> list[dict[str, Any]]:
    """Train + test rows of the ground_truth config."""
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = []
    for split in ("train", "test"):
        path = parquet_dir / split / f"{split}-00000-of-00001.parquet"
        table = pq.read_table(path, columns=["expected", "expected_subclass", "gt_fields"])
        rows.extend(table.to_pylist())
    return rows


def build(rows: list[dict[str, Any]], revision: str, commit: str) -> dict[str, Any]:
    """The status document for ``rows``."""
    counts: Counter[tuple[str, str]] = Counter()
    surfaces: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    status: dict[tuple[str, str], dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        doc_type = row["expected"]
        if doc_type not in FIVE:
            continue
        subtype = normalize_corpus_subclass(doc_type, row["expected_subclass"])
        key = (doc_type, subtype)
        counts[key] += 1
        surfaces[key][str(row["expected_subclass"] or "")] += 1
        fields = parse_gt_fields(row["gt_fields"] or "{}")
        presence = gt_presence_map(fields)
        for name in sorted(set(fields) | set(presence)):
            if name in ANNOTATION_KEYS and name not in LABEL_SOURCES:
                continue
            state = presence.get(name)
            if state is None:
                state = "populated" if not is_empty_value(fields.get(name)) else "missing"
            status[key][name][state] += 1
    out: dict[str, Any] = {
        "dataset": DATASET,
        "config": "ground_truth",
        "revision": revision,
        "commit": commit,
        "rows": sum(counts.values()),
        "doc_types": {},
    }
    from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

    for doc_type in FIVE:
        live_fields = set(DEFAULT_FIELD_TYPES[doc_type])
        subtypes = {}
        for (dt, subtype), n in sorted(counts.items()):
            if dt != doc_type:
                continue
            fields = {
                name: dict(sorted(c.items()))
                for name, c in sorted(status[(dt, subtype)].items())
                # A field marked not_applicable everywhere is usually another
                # class's key carried in the union schema; it is kept only when
                # this class's live field map declares it (GT says "n/a" there).
                if set(c) != {"not_applicable"} or name in live_fields
            }
            subtypes[subtype] = {
                "rows": n,
                "surfaces": dict(sorted(surfaces[(dt, subtype)].items())),
                "fields": fields,
            }
        out["doc_types"][doc_type] = subtypes
    return out


def render(doc: dict[str, Any]) -> str:
    """Stable JSON text."""
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Hub tag, e.g. v9.2")
    parser.add_argument("--commit", required=True, help="Hub commit the tag points at")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(build(_rows(args.parquet_dir), args.revision, args.commit))
    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != text:
            print(f"{OUT_PATH} is stale; rebuild without --check", file=sys.stderr)
            return 1
        print(f"{OUT_PATH} is current")
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
