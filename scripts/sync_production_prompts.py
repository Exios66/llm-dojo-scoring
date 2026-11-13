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
import hashlib
import json
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

# A production row with this ``source_repo`` is authored here (e.g. production v2 of the
# contracts and merger specialists), so mailroom's body, still frozen_v1, must not replace it.
DOJO_AUTHORED = "llm-dojo-scoring"



def _git_head(mailroom: Path) -> str:
    """Return the HEAD commit hash of the mailroom checkout."""
    return subprocess.run(
        ["git", "-C", str(mailroom), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _body(text: str) -> str:
    """Canonical body: no trailing blank lines, exactly one final newline."""
    return text.rstrip("\n") + "\n"


def _render(source_key: str, text: str) -> str:
    """Prefix a normalized prompt body with its mailroom source-key provenance."""
    return f"<!-- provenance: llm-mailroom {source_key} -->\n\n{_body(text)}"


def _split_blocks(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Split catalog lines into a header and agent-entry blocks."""
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
    """Read a two-space-indented scalar field from an agent catalog block."""
    for ln in block:
        m = re.match(rf"^  {re.escape(key)}: (.*)$", ln)
        if m:
            return m.group(1).strip()
    return None


def _set_field(block: list[str], key: str, value: str, after: str | None = None) -> None:
    """Replace a scalar field or insert it after an anchor, modifying the block."""
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
    """Vendor live mailroom production prompts and metadata, or report content drift."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mailroom", required=True, type=Path, help="llm-mailroom checkout")
    ap.add_argument("--check", action="store_true", help="exit 1 if the vendored copy drifted")
    args = ap.parse_args(argv)
    mailroom = args.mailroom.resolve()
    sys.path.insert(0, str(mailroom / "src"))
    try:
        from llm.prompts import _bound_prompt_versions, prompt_templates
    except ImportError as exc:
        print(f"cannot import mailroom prompts from {mailroom / 'src'}: {exc}", file=sys.stderr)
        return 2

    live = prompt_templates()
    bound = _bound_prompt_versions()
    commit = _git_head(mailroom)

    lineage_path = mailroom / "src" / "llm" / "frozen_v1" / "lineage.json"
    frozen = json.loads(lineage_path.read_text(encoding="utf-8")).get("specialists", {}) \
        if lineage_path.is_file() else {}

    head, blocks = _split_blocks(CATALOG.read_text(encoding="utf-8").splitlines())
    drifted: list[str] = []
    refused: list[str] = []
    authored: list[str] = []
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
        if _field(block, "source_repo") == DOJO_AUTHORED:
            authored.append(row_agent)  # left as is: neither digest-checked nor overwritten
            continue
        key = bound.get(agent)
        if key == "frozen_v1":
            # mailroom serves frozen v1 from whichever dojo it resolves, so check the
            # body against mailroom's own recorded digest before labelling it frozen_v1
            want = (frozen.get(agent) or {}).get("sha256")
            got = hashlib.sha256(live[agent].encode("utf-8")).hexdigest()
            if want != got:
                refused.append(
                    f"{row_agent}: frozen_v1 body sha256 {got[:12]} != mailroom lineage.json "
                    f"{want[:12]}" if want else
                    f"{row_agent}: no frozen_v1 digest for it in {lineage_path}")
                continue
            version, source_key = "v1", "frozen_v1"
        elif key and key != "production":
            # a lineage key mailroom wires into production (e.g. sorter_v15): the
            # vendored body is that version, so the row and provenance must name it
            version = source_key = key
        else:  # Langfuse-managed ("production" label): keep the catalog's own fields
            version, source_key = _field(block, "version") or "", _field(block, "source_key") or ""
        want_kind = "deterministic" if agent in DETERMINISTIC else "llm"
        rendered = _render(source_key, live[agent])
        path = TEMPLATES / template
        cur = path.read_text(encoding="utf-8") if path.exists() else None
        cur_key = re.match(r"<!-- provenance: \S+ (\S+) -->", cur or "")
        if key in (None, "production") and cur is not None and cur != rendered \
                and cur_key and cur_key.group(1) == source_key:
            # a managed body changed (or an agent just moved to the managed binding) while
            # the catalog still names the old body's key: give the new body its own name first
            refused.append(f"{row_agent}: managed production body changed but its catalog "
                           f"source_key is still {source_key}; set a new version and "
                           "source_key for it, then re-sync")
            continue
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
    if authored:
        print("authored in this repo, not synced: " + ", ".join(authored))
    if refused:
        print("refused (nothing written):\n  " + "\n  ".join(refused), file=sys.stderr)
        return 1
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
