#!/usr/bin/env python3
"""Audit corporate_record ground-truth labels against the per-subclass schemas.

Usage::

    python scripts/audit_corporate_record_labels.py PATH [PATH ...] [--json]

Each PATH is a mailroom-dataset ``ground_truth`` parquet (or a ``.bin`` HF
cache copy) or a JSONL file with ``expected`` / ``expected_subclass`` /
``gt_fields``. Prints defect counts per subclass (see
``llm_dojo_scoring.corporate_record_schema.audit_gt_row``). Parquet needs
``pyarrow``. Exit status is 1 when any defect is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_dojo_scoring.corporate_record_schema import audit_gt_rows


def _rows(path: Path):
    """Yield nonblank JSONL records, or the three audit columns from parquet.

    Non-``.jsonl`` paths require ``pyarrow``. File and parsing errors propagate.
    """
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return
    import pyarrow.parquet as pq  # optional dependency

    yield from pq.read_table(path, columns=["expected", "expected_subclass", "gt_fields"]).to_pylist()


def main(argv: list[str] | None = None) -> int:
    """Print a label audit; return 1 for any defect and 0 otherwise.

    ``argv`` excludes the program name; ``None`` uses command-line arguments.
    Argument errors exit through argparse; file-reading and parsing errors
    propagate, while GT parse errors within a row are counted as ``gt_unparseable``.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)
    rows = [row for path in args.paths for row in _rows(path)]
    report = audit_gt_rows(rows)
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
