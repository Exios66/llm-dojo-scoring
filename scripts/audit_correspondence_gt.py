#!/usr/bin/env python3
"""Audit correspondence ground truth for templated and metadata-derived labels (#94).

Usage::

    python scripts/audit_correspondence_gt.py PATH [PATH ...] [--json]

Each PATH is a mailroom-dataset ``ground_truth`` parquet (or a ``.bin`` HF
cache copy) or a JSONL file with ``expected`` / ``gt_fields``. Prints defect
counts and the scored population per live field (see
``llm_dojo_scoring.schemas.correspondence_gt_audit``). Parquet needs
``pyarrow``. JSONL may carry a UTF-8 BOM.

Exit status:

- ``0`` — rows were audited and no templated / metadata / unparseable defect found;
- ``1`` — a templated or metadata defect was found;
- ``2`` — the audit could not run: an unreadable or malformed input file, a row
  that is not a JSON object, or no correspondence rows to audit (a message goes
  to stderr).
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


class InputError(Exception):
    """An input file could not be read, parsed or understood (exit status 2)."""


def _rows(path: Path):
    """Yield JSONL records or parquet rows projected to the audit columns."""
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8-sig") as fh:
            for number, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise InputError(f"{path}:{number}: invalid JSON: {exc}") from exc
                if not isinstance(row, dict):
                    raise InputError(
                        f"{path}:{number}: expected a JSON object, got {type(row).__name__}"
                    )
                yield row
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq  # optional dependency
    except ImportError as exc:
        raise InputError(f"{path}: reading parquet needs pyarrow ({exc})") from exc
    try:
        table = pq.read_table(path, columns=["expected", "gt_fields"])
    except (pa.ArrowException, KeyError) as exc:
        raise InputError(f"{path}: cannot read parquet: {type(exc).__name__}: {exc}") from exc
    yield from table.to_pylist()


def main(argv: list[str] | None = None) -> int:
    """Print the audit; return 1 for a failing defect, 2 for an input error, else 0."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)
    try:
        report = audit_correspondence_gt(row for path in args.paths for row in _rows(path))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: cannot read input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if report["n_rows"] == 0:
        print("warning: no correspondence rows found in the input; nothing audited", file=sys.stderr)
        return 2
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
