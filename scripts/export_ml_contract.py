"""Write or check the committed ML contract (``llm_dojo_scoring/ml/data/ml_contract.json``).

``--write`` regenerates it from the Dojo's tables; ``--check`` exits 1 with a diff
summary when the committed file is stale. Network-free.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_dojo_scoring.ml.contract import contract_path, ml_contract  # noqa: E402


def render() -> str:
    """The contract as committed: indented, key-sorted JSON with a final newline."""
    return json.dumps(ml_contract(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``--write`` or ``--check`` (exactly one)."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the committed contract")
    mode.add_argument("--check", action="store_true", help="exit 1 when the committed contract is stale")
    parser.add_argument("--path", type=Path, default=contract_path(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    fresh = render()
    if args.write:
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(fresh, encoding="utf-8")
        print(f"wrote {args.path.name}")
        return 0
    current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
    if current == fresh:
        print(f"{args.path.name} is current")
        return 0
    stale = json.loads(current).get("digests", {}) if current else {}
    changed = sorted(k for k, v in json.loads(fresh)["digests"].items() if stale.get(k) != v)
    print(f"{args.path.name} is stale; parts changed: {', '.join(changed) or 'layout'}", file=sys.stderr)
    print("run: uv run --locked python scripts/export_ml_contract.py --write", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
