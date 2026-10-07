#!/usr/bin/env python3
"""Re-vendor the ``production`` prompt family from a live llm-mailroom checkout.

Usage::

    OPENROUTER_API_KEY=dummy PYTHONPATH=<mailroom>/src \\
        python scripts/sync_production_prompts.py --mailroom <mailroom> [--check]

Writes each live ``llm.prompts.prompt_templates()`` body to
``llm_dojo_scoring/prompts/templates/<agent>.production.md`` (verbatim, behind
the provenance comment) and updates the matching ``production`` rows of
``catalog.yaml`` (``version`` / ``source_key`` / ``source_commit`` / ``kind``).
``--check`` writes nothing and exits 1 listing drifted agents.

Stdlib + the mailroom import only; all paths are relative to this repo root.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "llm_dojo_scoring" / "prompts"
TEMPLATES = PROMPTS / "templates"
CATALOG = PROMPTS / "catalog.yaml"

# Live agents whose production row is not an LLM prompt in the dojo catalog.
DETERMINISTIC = {"reporter"}



def _git_head(mailroom: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(mailroom), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _body(text: str) -> str:
    """Canonical body: no trailing blank lines, exactly one final newline."""
    return text.rstrip("\n") + "\n"


def _render(source_key: str, text: str) -> str:
    return f"<!-- provenance: llm-mailroom {source_key} -->\n\n{_body(text)}"


def _split_blocks(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    head: list[str] = []
    blocks: list[list[str]] = []
    for ln in lines:
        if ln.startswith("- agent:"):
            blocks.append([ln])
        elif blocks:
            blocks[-1].append(ln)
        else:
            head.append(ln)
    return head, blocks


def _field(block: list[str], key: str) -> str | None:
    for ln in block:
        m = re.match(rf"^  {re.escape(key)}: (.*)$", ln)
        if m:
            return m.group(1).strip()
    return None


def _set_field(block: list[str], key: str, value: str, after: str | None = None) -> None:
    for i, ln in enumerate(block):
        if re.match(rf"^  {re.escape(key)}: ", ln):
            block[i] = f"  {key}: {value}"
            return
    anchor = after or "agent"
    for i, ln in enumerate(block):
        if re.match(rf"^(  |- ){re.escape(anchor)}: ", ln):
            block.insert(i + 1, f"  {key}: {value}")
            return
    block.append(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mailroom", required=True, type=Path, help="llm-mailroom checkout")
    ap.add_argument("--check", action="store_true", help="exit 1 if the vendored copy drifted")
    args = ap.parse_args(argv)
    mailroom = args.mailroom.resolve()
    sys.path.insert(0, str(mailroom / "src"))
    from llm.prompts import _bound_prompt_versions, prompt_templates

    live = prompt_templates()
    bound = _bound_prompt_versions()
    commit = _git_head(mailroom)

    head, blocks = _split_blocks(CATALOG.read_text(encoding="utf-8").splitlines())
    drifted: list[str] = []
    writes: dict[Path, str] = {}
    seen: set[str] = set()

    for block in blocks:
        if _field(block, "family") != "production":
            continue
        template = _field(block, "template")
        if not template or template == "null" or not template.endswith(".production.md"):
            continue
        agent = template[: -len(".production.md")]
        if agent not in live:
            continue  # retired in mailroom (e.g. compliance); left untouched
        seen.add(agent)
        row_agent = block[0][len("- agent:"):].strip()
        frozen = bound.get(agent) == "frozen_v1"
        version, source_key = ("v1", "frozen_v1") if frozen else (
            _field(block, "version") or "", _field(block, "source_key") or "")
        want_kind = "deterministic" if agent in DETERMINISTIC else "llm"
        rendered = _render(source_key, live[agent])
        path = TEMPLATES / template
        cur = path.read_text(encoding="utf-8") if path.exists() else None
        if cur != rendered or _field(block, "version") != version \
                or _field(block, "source_key") != source_key \
                or _field(block, "kind") != want_kind:
            drifted.append(f"{row_agent} ({template})")
        writes[path] = rendered
        _set_field(block, "version", version)
        _set_field(block, "kind", want_kind)
        _set_field(block, "source_key", source_key)
        _set_field(block, "source_commit", commit, after="source_key")

    unvendored = sorted(set(live) - seen)
    if args.check:
        if drifted:
            print("drifted production prompts:\n  " + "\n  ".join(drifted))
            return 1
        print(f"production prompts in sync with mailroom {commit[:7]}")
        return 0

    for path, text in writes.items():
        path.write_text(text, encoding="utf-8")
    out = list(head)
    for b in blocks:
        out.extend(b)
    CATALOG.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"synced {len(writes)} templates from mailroom {commit[:7]}")
    if unvendored:
        print("not vendored (no production row / template): " + ", ".join(unvendored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
