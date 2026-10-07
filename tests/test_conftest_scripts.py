import sys
import types

from conftest import load_script


def test_load_script_ignores_a_shadowing_scripts_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "scripts", types.ModuleType("scripts"))
    mod = load_script("gen_maud_catalog")
    assert mod.__file__.endswith("scripts/gen_maud_catalog.py")
