#!/usr/bin/env python3
"""Generate ``tests/fixtures/taxonomy_field_types.json`` from mailroom's taxonomy.

The fixture is the dojo's live field-map authority. It pins the mailroom
``src/config/taxonomy.yaml`` by git blob sha1 so drift fails loudly in
``tests/test_live_roster_parity.py``.

    python scripts/gen_taxonomy_fixture.py --taxonomy ../llm-mailroom/src/config/taxonomy.yaml
    python scripts/gen_taxonomy_fixture.py --taxonomy PATH --check
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "taxonomy_field_types.json"
COMMENT = (
    "Live field-map authority for llm-dojo-scoring, generated from llm-mailroom "
    "src/config/taxonomy.yaml by scripts/gen_taxonomy_fixture.py. Do not hand-edit: "
    "regenerate from the pinned blob and run tests/test_live_roster_parity.py."
)
AUTHORITY = "Exios66/llm-mailroom@main:src/config/taxonomy.yaml"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}", key_node.start_mark,
                )
            seen.add(key)
        return mapping


def build_fixture(taxonomy_path: Path) -> dict:
    data = Path(taxonomy_path).read_bytes()
    taxonomy = yaml.load(data, Loader=_UniqueKeySafeLoader)
    if not isinstance(taxonomy, dict) or "doc_classes" not in taxonomy:
        raise ValueError("taxonomy must contain 'doc_classes' in a top-level mapping")
    classes = taxonomy["doc_classes"]
    return {
        "_comment": COMMENT,
        "authority": AUTHORITY,
        "authority_blob_sha1": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(),
        "authority_sha256": hashlib.sha256(data).hexdigest(),
        "captured_at": datetime.date.today().isoformat(),
        "live_doc_types": [c["key"] for c in classes],
        "doc_classes": {
            c["key"]: {
                "field_types": dict(c["field_types"]),
                "schema": c["schema"],
                "specialist": c["specialist"],
            }
            for c in classes
        },
    }


def _dump(fixture: dict) -> str:
    return json.dumps(fixture, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--taxonomy", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="exit 1 on any drift except captured_at")
    args = ap.parse_args(argv)
    fixture = build_fixture(args.taxonomy)
    if args.check:
        current = json.loads(args.out.read_text(encoding="utf-8"))
        current.pop("captured_at", None)
        fixture.pop("captured_at")
        if current != fixture:
            drifted = sorted(k for k in fixture if current.get(k) != fixture[k])
            print(f"fixture drift in: {', '.join(drifted)}", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(_dump(fixture), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
