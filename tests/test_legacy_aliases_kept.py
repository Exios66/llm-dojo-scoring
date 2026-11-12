"""Every module a consumer imports, or that is held for in-flight work, still imports.

The production slim-down deletes modules no consumer reaches (decided by
``scripts/consumer_closure.py``). These tests pin the other side of that cut: each
module recorded in ``tests/fixtures/consumer_surface.json`` still imports, through its
subpackage path and through its legacy flat path, with every attribute consumers use;
and every held module still imports.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from llm_dojo_scoring._layout import LEGACY_MODULES
from conftest import load_script

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "llm_dojo_scoring"
SURFACE = json.loads((ROOT / "tests" / "fixtures" / "consumer_surface.json").read_text())
_FLAT_BY_TARGET = {target: flat for flat, target in LEGACY_MODULES.items()}


def _module_file_exists(dotted: str) -> bool:
    """Return True when ``dotted`` (relative to the package) is a module or package on disk."""
    base = PKG_DIR.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


@pytest.mark.parametrize("dotted", sorted(SURFACE["modules"]))
def test_consumed_module_imports_with_its_attributes(dotted):
    """A consumed module imports by its subpackage path and keeps every consumed attribute."""
    module = importlib.import_module(f"llm_dojo_scoring.{dotted}")
    missing = [a for a in SURFACE["modules"][dotted]["attrs"] if not hasattr(module, a)]
    assert not missing, f"llm_dojo_scoring.{dotted} lost consumed attributes {missing}"


@pytest.mark.parametrize(
    "dotted", sorted(d for d in SURFACE["modules"] if d in _FLAT_BY_TARGET)
)
def test_consumed_module_imports_through_its_legacy_flat_path(dotted):
    """The legacy flat path of a consumed module resolves to the same module object."""
    flat = importlib.import_module(f"llm_dojo_scoring.{_FLAT_BY_TARGET[dotted]}")
    assert flat is importlib.import_module(f"llm_dojo_scoring.{dotted}")


@pytest.mark.parametrize("dotted", sorted(load_script("consumer_closure").HOLD))
def test_held_module_imports(dotted):
    """Every module held for in-flight work still imports."""
    importlib.import_module(f"llm_dojo_scoring.{dotted}")


def test_every_legacy_alias_points_at_an_existing_module():
    """No legacy flat name aliases a module that was deleted."""
    dangling = sorted(f for f, t in LEGACY_MODULES.items() if not _module_file_exists(t))
    assert not dangling, f"LEGACY_MODULES entries point at deleted modules: {dangling}"
