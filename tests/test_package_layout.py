"""The subpackage layout, and the legacy flat import paths consumers still use."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import llm_dojo_scoring
from llm_dojo_scoring._layout import LEGACY_MODULES

PKG_DIR = Path(llm_dojo_scoring.__file__).parent
SUBPACKAGES = {"schemas", "scoring", "pipeline", "metrics", "analysis", "integrations", "prompts"}


@pytest.mark.parametrize("name", sorted(LEGACY_MODULES))
def test_legacy_path_is_the_same_module(name):
    """``llm_dojo_scoring.<old>`` and its subpackage path are one module object."""
    old = importlib.import_module(f"llm_dojo_scoring.{name}")
    new = importlib.import_module(f"llm_dojo_scoring.{LEGACY_MODULES[name]}")
    assert old is new
    assert new.__name__ == new.__spec__.name == f"llm_dojo_scoring.{LEGACY_MODULES[name]}"


def test_legacy_from_import_and_patch_reach_the_real_module(monkeypatch):
    """Patching through the old path is visible through the new one."""
    from llm_dojo_scoring.field_scoring import score_extraction
    from llm_dojo_scoring.scoring import field_scoring

    assert score_extraction is field_scoring.score_extraction
    monkeypatch.setattr("llm_dojo_scoring.field_scoring.CMS_CLAIM_TYPES", frozenset({"x"}))
    assert field_scoring.CMS_CLAIM_TYPES == frozenset({"x"})


def test_package_root_stays_organized():
    """Only the entry points live at the root; every module sits in a subpackage."""
    root_modules = {p.stem for p in PKG_DIR.glob("*.py")}
    assert root_modules == {"__init__", "_layout", "config", "cli"}
    subpackages = {p.name for p in PKG_DIR.iterdir() if (p / "__init__.py").is_file()}
    assert subpackages == SUBPACKAGES
    for name, path in LEGACY_MODULES.items():
        assert (PKG_DIR / (path.replace(".", "/") + ".py")).is_file(), name


def test_root_attributes_are_kept():
    """Modules the package root exposed as attributes are still there."""
    for name in ("field_scoring", "registry", "emitter", "io", "visualize", "suites", "prompts", "config"):
        assert hasattr(llm_dojo_scoring, name)
