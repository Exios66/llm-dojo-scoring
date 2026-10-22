#!/usr/bin/env python3
"""Audit corporate_record ground-truth labels against the per-subclass schemas.

Usage::

    python scripts/audit_corporate_record_labels.py PATH [PATH ...] [--json] [--review-queue OUTPUT.jsonl]

Each PATH is a mailroom-dataset ``ground_truth`` parquet (or a ``.bin`` HF
cache copy) or a JSONL file with ``expected`` / ``expected_subclass`` /
``gt_fields``. Prints defect counts per subclass (see
``llm_dojo_scoring.corporate_record_schema.audit_gt_row``). Parquet needs
``pyarrow``. Exit status is 1 when any defect is found.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from llm_dojo_scoring.corporate_record_schema import audit_gt_row, audit_gt_rows


def _rows(path: Path, *, include_context: bool = False):
    """Yield JSONL records or parquet rows, projecting audit columns by default.

    Review queues retain all parquet columns for source context. Non-``.jsonl``
    paths require ``pyarrow``. File and parsing errors propagate.
    """
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return
    import pyarrow.parquet as pq  # optional dependency

    columns = None if include_context else ["expected", "expected_subclass", "gt_fields"]
    yield from pq.read_table(path, columns=columns).to_pylist()


def _json_safe(value):
    """Return ``value`` with non-finite floats replaced by their string form.

    Keeps queue lines strict JSON while preserving the original evidence.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _review_rows(rows):
    """Yield defective corporate rows and audit evidence without suggesting labels."""
    for row in rows:
        if row.get("expected") != "corporate_record":
            continue
        raw_gt = row.get("gt_fields")
        try:
            defects = audit_gt_row(row.get("expected_subclass"), {} if raw_gt is None else raw_gt)
        except (TypeError, ValueError):
            defects = ["gt_unparseable"]
        if defects:
            yield {
                "row": dict(row),
                "defects": defects,
                "annotation_fields": [
                    code.split(":", 1)[1]
                    for code in defects if code.startswith("entity_unlabeled:")
                ],
            }


def main(argv: list[str] | None = None) -> int:
    """Print a label audit; return 1 for any defect and 0 otherwise.

    ``argv`` excludes the program name; ``None`` uses command-line arguments.
    Argument errors exit through argparse; file-reading and parsing errors
    propagate, while GT parse errors within a row are counted as ``gt_unparseable``.
    An optional review queue preserves defective rows for human annotation;
    its output must not already exist and never replaces an input file.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    ap.add_argument("--review-queue", type=Path, help="write a new JSONL queue for human review")
    args = ap.parse_args(argv)
    if args.review_queue and args.review_queue.resolve() in {path.resolve() for path in args.paths}:
        ap.error("--review-queue must not replace an input file")
    rows = [
        row for path in args.paths
        for row in _rows(path, include_context=args.review_queue is not None)
    ]
    report = audit_gt_rows(rows)
    if args.review_queue:
        with args.review_queue.open("x", encoding="utf-8") as queue:
            for entry in _review_rows(rows):
                queue.write(json.dumps(_json_safe(entry), ensure_ascii=False, default=str, allow_nan=False) + "\n")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"corporate_record rows audited: {report['n_rows']}")

        def fmt(counts: dict[str, int]) -> str:
            """Summarize defects, grouping conflicts and unlabeled entity fields."""
            ent = {k.split(":", 1)[1]: v for k, v in counts.items() if k.startswith("entity_unlabeled:")}
            rest = {
                k: v for k, v in counts.items()
                if k != "rows" and not k.startswith(("entity_unlabeled:", "subclass_content_conflict:"))
            }
            parts = [f"{k}={v}" for k, v in sorted(rest.items())]
            conflict = sum(v for k, v in counts.items() if k.startswith("subclass_content_conflict:"))
            if conflict:
                parts.append(f"subclass_content_conflict={conflict}")
            if ent:
                parts.append(f"unlabeled entity fields={len(ent)} ({', '.join(sorted(ent))})")
            return "; ".join(parts) or "clean"

        for sub, counts in sorted(report["by_subclass"].items()):
            print(f"  {sub} ({counts['rows']} rows): {fmt(counts)}")
        print("totals:", fmt(report["totals"]))
    return 1 if any(k != "rows" for k in report["totals"]) else 0


if __name__ == "__main__":
    sys.exit(main())
