#!/usr/bin/env python3
"""PreToolUse guard: refuse Edit/Write/NotebookEdit on files Claude must not hand-edit.

Reads the hook JSON on stdin. Exit 2 (with a reason on stderr) blocks the call and
shows the reason to Claude; any other exit lets it through. Fails open on malformed
input so a hook bug can never wedge a session.
"""

from __future__ import annotations

import json
import re
import sys

# (regex searched against the POSIX path, explanation shown to Claude)
RULES = [
    (
        r"(^|/)\.env(\.(?!example$)[^/]+)?$",
        "Secrets file. Only .env.example is tracked; ask the user to edit .env themselves.",
    ),
    (
        r"(^|/)uv\.lock$",
        "uv.lock is generated. Edit pyproject.toml and run `uv lock` instead.",
    ),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    except Exception:
        return 0
    path = path.replace("\\", "/")
    for pattern, reason in RULES:
        if re.search(pattern, path):
            print(f"Blocked edit to {path}: {reason}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
