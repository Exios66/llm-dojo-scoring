#!/usr/bin/env python3
"""Write a repaired corporate_record ground-truth proposal (does NOT publish).

Usage::

    python scripts/relabel_corporate_record_gt.py OUT.jsonl PATH [PATH ...]

PATH: mailroom-dataset ``ground_truth`` parquet(s). Only ``corporate_record``
rows are emitted, repaired by ``llm_dojo_scoring.corporate_record_relabel``;
prints the change counts and the post-repair audit. Review the JSONL before
anything is pushed to the Hub. Needs ``pyarrow``.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from llm_dojo_scoring.corporate_record_relabel import relabel_row
from llm_dojo_scoring.corporate_record_schema import audit_gt_rows


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    out_path, paths = Path(argv[1]), [Path(p) for p in argv[2:]]
    rows = [r for p in paths for r in pq.read_table(p).to_pylist() if r["expected"] == "corporate_record"]
    fixed, counts = [], collections.Counter()
    for row in rows:
        new, changes = relabel_row(row)
        fixed.append(new)
        counts.update(c.split(":")[0] if c.startswith("intent") else c for c in changes)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in fixed:
            fh.write(json.dumps(row, default=str) + "\n")
    print(f"{len(fixed)} rows -> {out_path}")
    print("changes:", dict(sorted(counts.items())))
    report = audit_gt_rows(fixed)
    print("post-repair audit totals:", report["totals"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
