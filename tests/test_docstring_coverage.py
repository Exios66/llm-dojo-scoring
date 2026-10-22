"""Require docstrings on every repository Python module and definition."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORIES = ("llm_dojo_scoring", "scripts", "tests", "examples", "tools")


def _python_sources() -> list[Path]:
    """Collect repository-owned Python sources without inspecting virtualenvs."""
    sources = set(_ROOT.glob("*.py"))
    for directory in _SOURCE_DIRECTORIES:
        sources.update((_ROOT / directory).rglob("*.py"))
    return sorted(sources)


@pytest.mark.parametrize(
    "source", _python_sources(), ids=lambda path: str(path.relative_to(_ROOT))
)
def test_python_definitions_have_docstrings(source: Path) -> None:
    """Document modules, classes, and functions, including nested private helpers."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    definitions = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    missing = [
        f"{getattr(node, 'lineno', 1)}: {getattr(node, 'name', '<module>')}"
        for node in ast.walk(tree)
        if isinstance(node, definitions) and not ast.get_docstring(node)
    ]
    assert not missing, (
        f"Missing docstrings in {source.relative_to(_ROOT)}:\n" + "\n".join(missing)
    )
