#!/usr/bin/env python3
"""Audit correspondence ground truth for templated and metadata-derived labels (#94).

Usage::

    python scripts/audit_correspondence_gt.py PATH [PATH ...] [--json]

Each PATH is a mailroom-dataset ``ground_truth`` parquet (or a ``.bin`` HF
cache copy) or a JSONL file with ``expected`` / ``gt_fields``. Prints defect
counts and the scored population per live field (see
``llm_dojo_scoring.schemas.correspondence_gt_audit``). Parquet needs
``pyarrow``. Exit status is 1 when a templated or metadata defect is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_dojo_scoring.schemas.correspondence_gt_audit import audit_correspondence_gt

#: Defects that mean the GT itself needs relabelling (``intent_missing`` is a
#: population fact, reported but not a failure).
FAILING_CODES = ("subject_matter_templated", "keywords_metadata", "gt_unparseable")


def _rows(path: Path):
    """Yield JSONL records or parquet rows projected to the audit columns."""
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return
    import pyarrow.parquet as pq  # optional dependency

    yield from pq.read_table(path, columns=["expected", "gt_fields"]).to_pylist()


def main(argv: list[str] | None = None) -> int:
    """Print the audit; return 1 when any failing defect is found, else 0."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)
    report = audit_correspondence_gt(row for path in args.paths for row in _rows(path))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        n = report["n_rows"]
        print(f"correspondence rows audited: {n}")
        for code, count in sorted(report["totals"].items()):
            print(f"  {code}: {count}/{n}")
        print("field population (rows with GT):")
        for field, count in report["field_population"].items():
            print(f"  {field}: {count}/{n}")
        hist = ", ".join(f"{k} fields={v}" for k, v in report["populated_field_counts"].items())
        print(f"populated live fields per row: {hist or 'n/a'}")
        if report["unscored_fields"]:
            print("never scored: " + ", ".join(report["unscored_fields"]))
    return 1 if any(report["totals"].get(code) for code in FAILING_CODES) else 0


if __name__ == "__main__":
    sys.exit(main())
