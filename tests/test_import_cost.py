"""``import llm_dojo_scoring`` must stay cheap for scoring-only consumers."""

from __future__ import annotations

import subprocess
import sys


def _modules_after_import(code: str) -> set[str]:
    """Run ``code`` in a fresh interpreter and return the loaded module names."""
    proc = subprocess.run(
        [sys.executable, "-c", f"{code}\nimport sys\nprint('\\n'.join(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(proc.stdout.split())


def test_package_import_does_not_load_pyplot():
    """pyplot is the costliest import; only drawing a plot should load it."""
    assert "matplotlib.pyplot" not in _modules_after_import("import llm_dojo_scoring")


def test_visualize_plt_still_resolves():
    """``visualize.plt`` keeps working for callers that reached for it."""
    loaded = _modules_after_import(
        "from llm_dojo_scoring import visualize\nassert visualize.plt.__name__ == 'matplotlib.pyplot'"
    )
    assert "matplotlib.pyplot" in loaded
