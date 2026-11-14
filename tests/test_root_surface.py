"""The package root resolves its names lazily and explains removed ones (#80).

``import llm_dojo_scoring`` loads only the legacy-path finder; every re-exported
name and submodule is imported on first access through ``__getattr__``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import llm_dojo_scoring as dojo

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONSUMED = sorted(json.loads((FIXTURES / "consumer_surface.json").read_text())["top_level"])


def _fresh(code: str) -> str:
    """Run ``code`` in a fresh interpreter and return its stdout."""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return proc.stdout


@pytest.mark.parametrize("name", CONSUMED)
def test_consumed_root_name_is_exported_and_resolves(name):
    """Every root name a consumer imports is in ``__all__`` and resolves."""
    assert name in dojo.__all__
    assert getattr(dojo, name) is not None


def test_every_name_in_all_resolves():
    """No name in ``__all__`` is dangling."""
    missing = [n for n in dojo.__all__ if not hasattr(dojo, n)]
    assert not missing


def test_lazy_name_is_the_defining_object():
    """A lazily resolved name is the object its defining module holds."""
    from llm_dojo_scoring.analysis.bootstrap import wilson_ci
    from llm_dojo_scoring.scoring.field_scoring import score_extraction

    assert dojo.wilson_ci is wilson_ci
    assert dojo.score_extraction is score_extraction


def test_removed_name_points_at_the_changelog():
    """A name removed in the production slim-down fails with a pointer to CHANGELOG.md."""
    for name in ("rescore_file", "build_grid_report", "langfuse_sync", "visualize"):
        with pytest.raises(AttributeError, match="CHANGELOG.md"):
            getattr(dojo, name)


def test_unknown_name_raises_plain_attribute_error():
    """An attribute that never existed raises an ordinary AttributeError."""
    with pytest.raises(AttributeError, match="no attribute 'definitely_not_here'"):
        dojo.definitely_not_here  # noqa: B018


def test_import_loads_no_scoring_module():
    """``import llm_dojo_scoring`` loads no subpackage and no heavy dependency."""
    out = _fresh(
        "import sys, llm_dojo_scoring\n"
        "print(sorted(m for m in sys.modules if m.startswith('llm_dojo_scoring.')))\n"
        "print(sorted(m for m in ('pandas', 'numpy', 'scipy', 'matplotlib', 'openpyxl') if m in sys.modules))"
    ).splitlines()
    assert out == ["['llm_dojo_scoring._layout']", "[]"]


def test_legacy_flat_path_is_the_subpackage_module():
    """``llm_dojo_scoring.field_scoring`` is still the same object as its subpackage path."""
    out = _fresh(
        "import llm_dojo_scoring.field_scoring as a, llm_dojo_scoring.scoring.field_scoring as b\n"
        "import llm_dojo_scoring as d\n"
        "print(a is b, d.field_scoring is b)"
    )
    assert out.strip() == "True True"


def test_dir_lists_lazy_names():
    """``dir()`` shows lazy names, so tab completion and introspection still work."""
    assert {"score_extraction", "get_suite", "field_scoring"} <= set(dir(dojo))
