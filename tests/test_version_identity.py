"""The loaded scorer must report its own source version in vendor deployments."""

from pathlib import Path
import subprocess
import sys
import tomllib


def test_source_version_ignores_unrelated_installed_distribution():
    """An older or unrelated installed wheel cannot relabel vendored scorer code."""
    import numpy

    root = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    dependencies = Path(numpy.__file__).resolve().parents[1]
    program = '''
import importlib.metadata, pathlib, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
original = importlib.metadata.version
def unrelated_version(name):
    """Simulate metadata for a separately installed distribution."""
    return "9.9.9" if name == "llm-dojo-scoring" else original(name)
importlib.metadata.version = unrelated_version
import llm_dojo_scoring
assert pathlib.Path(llm_dojo_scoring.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]))
assert llm_dojo_scoring.__version__ == sys.argv[3], llm_dojo_scoring.__version__
'''
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(root), str(dependencies), expected],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
