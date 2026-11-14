"""Local JSONL files for grounding records (audits, candidates, confirmations, labels).

One JSON object per line, UTF-8. A record with an ``as_dict()`` method is written in
that form; a plain mapping is written as it is. Local files only: moving them to a
hosted store is the caller's job.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


def _as_mapping(item: Any) -> Mapping[str, Any]:
    """The JSON object for one record (``as_dict()`` output or the mapping itself)."""
    as_dict = getattr(item, "as_dict", None)
    data = as_dict() if callable(as_dict) else item
    if not isinstance(data, Mapping):
        raise TypeError(f"cannot write {type(item).__name__} as a JSONL record: not a mapping")
    return data


def write_jsonl(items: Iterable[Any], path: str | os.PathLike[str], *, append: bool = False) -> int:
    """Write ``items`` to ``path``, one JSON object per line; returns the count written.

    Without ``append`` the file is replaced atomically (written beside it, then
    renamed), so a failed write never leaves a half-written file. With ``append`` the
    lines are added to the end, which is how a confirmation ledger grows. Every record
    is serialised before anything is written, so an unserialisable record raises
    ``TypeError`` and the file is left unchanged.
    """
    lines = [json.dumps(_as_mapping(item), ensure_ascii=False) + "\n" for item in items]
    target = Path(path)
    if append:
        with target.open("a", encoding="utf-8") as handle:
            handle.writelines(lines)
        return len(lines)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return len(lines)


def read_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Every JSON object in ``path``, in file order; blank lines are skipped.

    A line that is not a JSON object raises ``ValueError`` naming the line number;
    nothing is skipped silently.
    """
    records: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: not valid JSON ({exc.msg})") from exc
            if not isinstance(data, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object, got {type(data).__name__}")
            records.append(data)
    return records
