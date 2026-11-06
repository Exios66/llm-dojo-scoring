"""Keep the supported-API and migration guides in step with the code and the consumer scan."""

from __future__ import annotations

import json
from pathlib import Path

import llm_dojo_scoring
from llm_dojo_scoring._layout import LEGACY_MODULES

ROOT = Path(__file__).resolve().parents[1]
SURFACE = json.loads((ROOT / "tests" / "fixtures" / "consumer_surface.json").read_text())
PUBLIC_API = (ROOT / "docs" / "guides" / "PUBLIC_API.md").read_text(encoding="utf-8")
MIGRATION = (ROOT / "docs" / "guides" / "MIGRATION.md").read_text(encoding="utf-8")


def test_every_consumed_root_name_is_documented():
    """Each package-root name a consumer imports is listed as supported."""
    missing = [n for n in SURFACE["top_level"] if f"`{n}`" not in PUBLIC_API]
    assert not missing, f"add to docs/guides/PUBLIC_API.md: {missing}"


def test_every_consumed_module_is_documented():
    """Each module a consumer imports by path is listed as supported."""
    missing = [m for m in SURFACE["modules"] if f"`llm_dojo_scoring.{m}`" not in PUBLIC_API]
    assert not missing, f"add to docs/guides/PUBLIC_API.md: {missing}"


def test_documented_archive_contract_is_exported():
    """The archive-contract names the guide promises are importable from the root."""
    for name in (
        "score_archive_block",
        "upsert_archive_scoring",
        "format_audit_entry",
        "prepare_archivist_handoff",
        "archivist_sign_off",
    ):
        assert f"`{name}`" in PUBLIC_API
        assert hasattr(llm_dojo_scoring, name)


def test_migration_table_covers_every_legacy_path():
    """The flat-path table lists every alias, mapped to its current location."""
    for old, new in LEGACY_MODULES.items():
        row = f"| `llm_dojo_scoring.{old}` | `llm_dojo_scoring.{new}` |"
        assert row in MIGRATION, f"MIGRATION.md is missing: {row}"
