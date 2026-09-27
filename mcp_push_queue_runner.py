#!/usr/bin/env python3
"""Track MCP push_files queue progress for Digital-Mailroom sync."""
from __future__ import annotations

import json
import sys
from pathlib import Path

QUEUE = Path("/tmp/push_queue.txt")
DONE = Path("/tmp/push_done_ids.txt")
COUNT = Path("/tmp/push_call_count.txt")


def done_ids() -> set[str]:
    if not DONE.is_file():
        return set()
    return {ln.strip() for ln in DONE.read_text().splitlines() if ln.strip()}


def inc_count() -> int:
    n = int(COUNT.read_text().strip() or "0") if COUNT.is_file() else 0
    n += 1
    COUNT.write_text(str(n) + "\n")
    return n


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "next"
    finished = done_ids()
    rows = [ln.split("\t") for ln in QUEUE.read_text().splitlines() if ln.strip()]
    pending = [(kind, label, path, nf, sz) for kind, label, path, nf, sz in rows if label not in finished]
    if cmd == "stats":
        print(json.dumps({"total": len(rows), "done": len(finished), "pending": len(pending),
                          "push_files_calls": int(COUNT.read_text().strip() or "0") if COUNT.is_file() else 0}))
        return 0
    if cmd == "mark":
        label = sys.argv[2]
        with DONE.open("a") as f:
            f.write(label + "\n")
        print("count", inc_count())
        return 0
    if cmd == "next":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        for kind, label, path, nf, sz in pending[:n]:
            print(kind, label, path, nf, sz)
        return 0
    if cmd == "payload":
        path = sys.argv[2]
        d = json.loads(Path(path).read_text())
        args = {k: d[k] for k in ("owner", "repo", "branch", "message", "files") if k in d}
        print(json.dumps(args, separators=(",", ":")))
        return 0
    print("usage: stats | next [N] | mark LABEL | payload PATH", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
