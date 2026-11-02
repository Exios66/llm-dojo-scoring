#!/usr/bin/env python3
"""PostToolUse: run the repo's ruff correctness gate on a just-edited .py file.

Exit 2 feeds ruff's findings back to Claude so it fixes them in the same turn.
Silently skips when ruff is not installed or the file is not Python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        path = (payload.get("tool_input") or {}).get("file_path") or ""
    except Exception:
        return 0
    if not path.endswith(".py") or shutil.which("ruff") is None:
        return 0
    result = subprocess.run(
        ["ruff", "check", "--output-format", "concise", path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return 0
    print(result.stdout + result.stderr, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
