#!/usr/bin/env python3
"""Regenerate the eval-environment prompt lineage catalog from a checkout.

Usage::

    python scripts/sync_eval_environment_lineage.py --eval-env <eval-environment> [--check]

Reads (never imports) the eval-environment lineage data:

* ``prompts/manifest.json`` + ``src/evals/prompts/frozen_v1.py``   -> ``frozen``
* ``prompts/archive/manifest.json`` + ``archived_production.py``   -> ``archived``
* ``prompts/mutations.json``                                       -> ``mutation``

and writes ``llm_dojo_scoring/prompts/eval_environment_lineage.json``
(sorted, pretty-printed, byte-deterministic: no wall-clock stamp). The Python
sources are parsed with ``ast`` (string literals only), so no eval-environment
code runs and the ``llm`` mailroom package is not needed. eval-environment's
live ``production`` lineage kind is not a frozen version and is skipped.

Every recorded sha256 is checked against ``sha256(text.encode("utf-8"))`` (the
raw text, eval-environment's convention); a mismatch fails the sync. ``--check``
writes nothing and exits 1 when the version content drifted; a moved
``source_commit`` over identical content is reported but is not drift.

Stdlib only; all paths are relative to this repo root.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "llm_dojo_scoring" / "prompts" / "eval_environment_lineage.json"

SOURCE_REPO = "LLM-Mailroom-Services/eval-environment"
EXCERPT_LINES = 5
EXCERPT_CHARS = 160

_KEY_RE = re.compile(r"^(?P<role>.+)_v(?P<version>\d+)$")
_BULLET_RE = re.compile(r"^(?:[-*+•]\s|\d+[.)]\s)")


class SyncError(RuntimeError):
    """The eval-environment data is inconsistent; nothing is written."""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def _split_key(key: str) -> tuple[str, int]:
    m = _KEY_RE.match(key)
    if not m:
        raise SyncError(f"key {key!r} does not end in _v<N>")
    return m["role"], int(m["version"])


def _literal_strings(path: Path) -> dict[str, str]:
    """Module-level ``name = '<str>'`` assignments, parsed without executing."""
    out: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def _versions_map(path: Path, literals: dict[str, str]) -> dict[str, str]:
    """Resolve the ``VERSIONS`` dict (key -> module-level name) to its text."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target != "VERSIONS" or not isinstance(node.value, ast.Dict):
            continue
        out: dict[str, str | None] = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not (isinstance(k, ast.Constant) and isinstance(v, ast.Name)):
                raise SyncError(f"{path.name}: unsupported VERSIONS entry")
            out[k.value] = literals.get(v.id)
        return out  # type: ignore[return-value]
    raise SyncError(f"{path.name}: no VERSIONS dict")


def _verified(key: str, text: str, recorded: dict) -> tuple[str, int]:
    digest = sha256(text)
    if recorded.get("sha256") and recorded["sha256"] != digest:
        raise SyncError(f"{key}: sha256 mismatch (recorded {recorded['sha256']}, text {digest})")
    # eval-environment's archive manifest records contracts_specialist_v33 as a
    # UTF-8 *byte* count (32736 bytes = 32582 chars); accept either measure.
    want = recorded.get("chars")
    if want is not None and want not in (len(text), len(text.encode("utf-8"))):
        raise SyncError(f"{key}: chars mismatch (recorded {want}, text {len(text)})")
    return digest, len(text)


# --------------------------------------------------------------------------- changes

def _heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 100:
        return False
    if s.startswith("#"):
        return True
    if _BULLET_RE.match(s):
        return False
    if s.endswith(":"):
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and s == s.upper() and len(s) <= 80


def _blocks(text: str) -> dict[str, str]:
    """Heading-like line -> body of its block (duplicates get ``#2``, ``#3``)."""
    out: dict[str, list[str]] = {"(preamble)": []}
    current = "(preamble)"
    seen: dict[str, int] = {}
    for line in text.splitlines():
        if _heading(line):
            name = line.strip()
            seen[name] = seen.get(name, 0) + 1
            current = name if seen[name] == 1 else f"{name}#{seen[name]}"
            out[current] = []
        else:
            out[current].append(line.rstrip())
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def _excerpt(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            continue
        out.append(s if len(s) <= EXCERPT_CHARS else s[: EXCERPT_CHARS - 3] + "...")
        if len(out) == EXCERPT_LINES:
            break
    return out


def _heading_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        if _heading(line):
            counts[line.strip()] = counts.get(line.strip(), 0) + 1
    return counts


def _notes(against: str, old_e: dict, new_e: dict) -> list[str]:
    """Data-quality observations about this step (kept out of the diff counts)."""
    notes = []
    if new_e["created_at"] < old_e["created_at"]:
        notes.append(
            f"created_at {new_e['created_at']} precedes {against} created_at "
            f"{old_e['created_at']}: created_at is not monotonic along this chain"
        )
    old_c, new_c = _heading_counts(old_e["text"]), _heading_counts(new_e["text"])
    for h, n in new_c.items():
        if n > 1 and n > old_c.get(h, 0):
            notes.append(f"heading {h!r} appears {n} times in this version "
                         f"(duplicated block; {old_c.get(h, 0)} in {against})")
    for h, n in old_c.items():
        if n > 1 and new_c.get(h, 0) < n:
            notes.append(f"heading {h!r} appeared {n} times in {against}; "
                         f"{new_c.get(h, 0)} in this version (duplicate removed)")
    return notes


def summarize_changes(against: str, old: str, new: str) -> dict:
    """Compact, deterministic change summary of ``new`` versus ``old``."""
    a, b = old.splitlines(), new.splitlines()
    added: list[str] = []
    removed: list[str] = []
    for ln in difflib.unified_diff(a, b, n=0, lineterm=""):
        if ln.startswith(("+++", "---", "@@")):
            continue
        (added if ln.startswith("+") else removed).append(ln[1:])
    old_b, new_b = _blocks(old), _blocks(new)
    changed = [h for h in new_b if old_b.get(h) != new_b[h]]
    changed += [h for h in old_b if h not in new_b]
    return {
        "against": against,
        "lines_added": len(added),
        "lines_removed": len(removed),
        "chars_delta": len(new) - len(old),
        "sections_changed": changed,
        "added_excerpt": _excerpt(added),
        "removed_excerpt": _excerpt(removed),
        "notes": [],
    }


# --------------------------------------------------------------------------- build

def _entry(key: str, lineage: str, *, parent, supersedes, memo, anchor_head,
           created_at, source, text, digest) -> dict:
    role, version = _split_key(key)
    return {
        "key": key, "role": role, "version": version, "lineage": lineage,
        "parent": parent, "supersedes": supersedes, "memo": memo,
        "anchor_head": anchor_head, "created_at": created_at, "source": source,
        "sha256": digest, "chars": len(text), "text": text, "changes": None,
    }


def build(eval_env: Path) -> dict:
    prompts = eval_env / "prompts"
    code = eval_env / "src" / "evals" / "prompts"
    frozen_m = json.loads((prompts / "manifest.json").read_text(encoding="utf-8"))
    arch_m = json.loads((prompts / "archive" / "manifest.json").read_text(encoding="utf-8"))
    mut_m = json.loads((prompts / "mutations.json").read_text(encoding="utf-8"))
    lineage_id = frozen_m["lineage_id"]
    if arch_m.get("lineage_id") != lineage_id:
        raise SyncError(f"archive lineage_id {arch_m.get('lineage_id')!r} != {lineage_id!r}")

    entries: dict[str, dict] = {}

    def add(e: dict) -> None:
        if e["key"] in entries:
            raise SyncError(f"duplicate key {e['key']}")
        entries[e["key"]] = e

    # archived -------------------------------------------------------------
    arch_lit = _literal_strings(code / "archived_production.py")
    arch_text = _versions_map(code / "archived_production.py", arch_lit)
    for key, meta in sorted(arch_m["versions"].items()):
        text = arch_text.get(key)
        if text is None:  # `_archive_md("<stem>")` entries live in prompts/archive/<stem>.md
            md = prompts / "archive" / f"{key}.md"
            if not md.is_file():
                raise SyncError(f"{key}: no literal text and no {md}")
            text = md.read_text(encoding="utf-8").strip("\n") + "\n"
        digest, _ = _verified(key, text, meta)
        add(_entry(
            key, "archived", parent=None, supersedes=None,
            memo=meta.get("note") or arch_m["note"], anchor_head=None,
            created_at=arch_m["archived_at"],
            source=f"{meta['source_kind']}:{meta['source_key']}", text=text, digest=digest,
        ))
    if set(arch_text) != set(arch_m["versions"]):
        raise SyncError("archived_production.VERSIONS and archive manifest keys differ")

    # frozen ---------------------------------------------------------------
    frozen_lit = _literal_strings(code / "frozen_v1.py")
    frozen_text = _versions_map(code / "frozen_v1.py", frozen_lit)
    if set(frozen_text) != set(frozen_m["versions"]):
        raise SyncError("frozen_v1.VERSIONS and manifest keys differ")
    for key, meta in sorted(frozen_m["versions"].items()):
        text = frozen_text[key]
        if text is None:
            raise SyncError(f"{key}: frozen text is not a string literal")
        digest, _ = _verified(key, text, meta)
        role, version = _split_key(key)
        v0 = f"{role}_v0"
        source = f"{meta['source_kind']}:{meta['source_key']}"
        add(_entry(
            key, "frozen", parent=None, supersedes=v0 if v0 in entries else None,
            memo=(f"Frozen v1 of lineage {lineage_id} from {source}. "
                  f"Derivation: {frozen_m['derivation']}"),
            anchor_head=None, created_at=frozen_m["frozen_at"], source=source,
            text=text, digest=digest,
        ))

    # mutations ------------------------------------------------------------
    for row in mut_m["mutations"]:
        key = row["key"]
        digest, _ = _verified(key, row["text"], row)
        role, version = _split_key(key)
        if version != row["version"]:
            raise SyncError(f"{key}: version field {row['version']} != key suffix {version}")
        add(_entry(
            key, "mutation", parent=row["parent"], supersedes=None, memo=row["note"],
            anchor_head=row.get("anchor_head"), created_at=row["created_at"],
            source=f"mutation-of:{row['parent']}", text=row["text"], digest=digest,
        ))

    # an archived entry that re-keys another entry's text says so in its memo
    for e in entries.values():
        if e["lineage"] != "archived":
            continue
        for other in sorted(entries.values(), key=lambda x: x["key"]):
            if (other["key"] != e["key"] and other["lineage"] == "archived"
                    and other["version"] < e["version"] and other["role"] == e["role"]
                    and other["text"].strip("\n") == e["text"].strip("\n")):
                how = ("apart from a trailing newline" if other["text"] != e["text"]
                       else "exactly")
                e["memo"] += f" Text equals {other['key']} {how}."
                break

    # change summaries + integrity -----------------------------------------
    for e in entries.values():
        pred = e["parent"] or e["supersedes"]
        if pred is None:
            continue
        if pred not in entries:
            raise SyncError(f"{e['key']}: predecessor {pred!r} missing")
        e["changes"] = summarize_changes(pred, entries[pred]["text"], e["text"])
        e["changes"]["notes"] = _notes(pred, entries[pred], e)

    ordered = sorted(entries.values(), key=lambda e: (e["role"], e["version"]))
    return {
        "source_repo": SOURCE_REPO,
        "lineage_id": lineage_id,
        "versions": ordered,
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--eval-env", required=True, type=Path, help="eval-environment checkout")
    ap.add_argument("--check", action="store_true", help="exit 1 if the vendored JSON drifted")
    args = ap.parse_args(argv)
    eval_env = args.eval_env.resolve()

    try:
        commit = _git(eval_env, "rev-parse", "HEAD")
        commit_date = _git(eval_env, "log", "-1", "--format=%cI", "HEAD")
        dirty = _git(eval_env, "status", "--porcelain", "--untracked-files=no",
                     "--", "prompts", "src/evals/prompts")
        if dirty:
            print("eval-environment has uncommitted lineage changes; commit or stash first:\n"
                  + dirty, file=sys.stderr)
            return 2
        doc = build(eval_env)
    except (SyncError, OSError, subprocess.CalledProcessError, KeyError) as exc:
        print(f"sync failed: {exc!r}" if isinstance(exc, KeyError) else f"sync failed: {exc}",
              file=sys.stderr)
        return 2

    doc["source_commit"] = commit
    doc["synced_at"] = commit_date  # the source commit date, never wall-clock
    new_text = render(doc)
    cur_text = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    counts = {k: sum(1 for v in doc["versions"] if v["lineage"] == k)
              for k in ("archived", "frozen", "mutation")}

    if args.check:
        if cur_text is None:
            print(f"missing {OUT.relative_to(ROOT)}")
            return 1
        cur = json.loads(cur_text)
        def strip(d: dict) -> dict:
            return {k: v for k, v in d.items() if k not in ("source_commit", "synced_at")}

        if strip(cur) != strip(doc):
            old = {v["key"]: v for v in cur.get("versions", [])}
            new = {v["key"]: v for v in doc["versions"]}
            drifted = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
            print("drifted eval-environment lineage:\n  " + "\n  ".join(drifted or ["(top-level fields)"]))
            return 1
        note = "" if cur.get("source_commit") == commit else \
            f" (content identical; pinned commit {str(cur.get('source_commit'))[:7]} vs {commit[:7]})"
        print(f"eval-environment lineage in sync with {commit[:7]}{note}")
        return 0

    OUT.write_text(new_text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['versions'])} versions {counts} "
          f"from eval-environment {commit[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
