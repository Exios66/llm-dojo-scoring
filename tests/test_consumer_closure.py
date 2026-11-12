"""Tests for ``scripts/consumer_closure.py`` (keep / hold / delete decision).

Network-free and checkout-free: the package, the consumers and the fixtures are
all temporary directories. The one test that touches the real package only reads
the committed JSON; it never needs the consumer checkouts.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import load_script

cc = load_script("consumer_closure")

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: file -> source of a small package named like the real one (consumers import it by name).
_FAKE_PACKAGE = {
    "__init__.py": (
        "from ._layout import install_legacy_aliases\n"
        "from .orphan import orphan_fn\n"
        "from .scoring.core import core_fn\n"
        "from .scoring.util import util_fn as renamed_util\n"
        "__version__ = '0'\n"
    ),
    "_layout.py": "LEGACY_MODULES: dict[str, str] = {'core': 'scoring.core'}\n",
    "orphan.py": "def orphan_fn():\n    return 1\n",
    "lazy.py": "def lazy_fn():\n    return 2\n",
    "scoring/__init__.py": "",
    "scoring/core.py": (
        "from .util import util_fn\n"
        "def core_fn():\n"
        "    from ..lazy import lazy_fn\n"
        "    return util_fn() + lazy_fn()\n"
    ),
    "scoring/util.py": "def util_fn():\n    return 3\n",
    "scoring/suites.py": "def get_suite(name):\n    return name\n",
    "scoring/tasks.py": "def score_task(task):\n    return task\n",
    "held/__init__.py": "",
    "held/one.py": "from .two import two_fn\n",
    "held/two.py": "def two_fn():\n    return 4\n",
    "withinit/__init__.py": "from . import member\n",
    "withinit/member.py": "def member_fn():\n    return 5\n",
    "withinit/other.py": "def other_fn():\n    return 6\n",
    "tidy/__init__.py": "from .leaf import leaf_fn\n",
    "tidy/leaf.py": "def leaf_fn():\n    return 7\n",
    "tidy/user.py": "x = 1\n",
}


def _write_tree(base: Path, files: dict[str, str]) -> Path:
    """Write *files* below *base* and return *base*."""
    for rel, text in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return base


@pytest.fixture()
def fake_package(tmp_path):
    """A tiny ``llm_dojo_scoring`` package; the directory name is the package name."""
    return _write_tree(tmp_path / "pkg" / "llm_dojo_scoring", _FAKE_PACKAGE)


def _git(root, *args):
    """Run one git command in *root*, failing the test on error."""
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repo(root):
    """Create a git repository with a local test identity."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_all(root, message="c"):
    """Commit everything in *root* and return the commit id."""
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# import_graph / closure
# ---------------------------------------------------------------------------


def test_import_graph_follows_relative_absolute_and_function_level_imports(fake_package):
    """Relative, absolute and nested imports all become edges between dotted modules."""
    (fake_package / "scoring" / "util.py").write_text(
        "def util_fn():\n"
        "    import llm_dojo_scoring.orphan as _o\n"
        "    return _o\n",
        encoding="utf-8",
    )
    graph = cc.import_graph(fake_package)
    assert graph["scoring.core"] == {"scoring.util", "lazy"}
    assert graph["scoring.util"] == {"orphan"}
    assert set(graph) >= {"__init__", "_layout", "scoring", "scoring.core", "held.one"}


def test_closure_follows_function_level_and_relative_imports(fake_package):
    """A root pulls in its direct, relative and function-level imports, transitively."""
    graph = cc.import_graph(fake_package)
    assert cc.closure({"scoring.core"}, graph) == {"scoring.core", "scoring.util", "lazy"}
    assert cc.closure({"held.one"}, graph) == {"held.one", "held.two"}
    assert cc.closure(set(), graph) == set()


def test_module_imported_only_by_the_root_init_is_not_kept(fake_package):
    """The root ``__init__`` imports ``orphan`` and ``core``; neither is kept by that alone."""
    graph = cc.import_graph(fake_package)
    assert graph["__init__"] == set()
    assert "orphan" not in cc.closure({"scoring.core"}, graph)
    assert "orphan" not in cc.closure({"__init__"}, graph)


def test_subpackage_init_imports_count_only_when_the_package_is_imported(fake_package):
    """A package ``__init__``'s imports are followed for an explicit import of the package.

    Importing a sibling module of the package reaches the package only implicitly,
    so what the package ``__init__`` imports is not kept by that alone.
    """
    graph = cc.import_graph(fake_package)
    assert graph["withinit"] == {"withinit.member"}
    assert cc.closure({"withinit"}, graph) == {"withinit", "withinit.member"}
    assert cc.closure({"withinit.other"}, graph) == {"withinit.other"}
    assert cc.closure({"tidy.user"}, graph) == {"tidy.user"}


def test_legacy_flat_paths_resolve_to_the_subpackage_module(fake_package):
    """``llm_dojo_scoring.core`` resolves through ``_layout.LEGACY_MODULES``."""
    pkg = cc.load_package(fake_package)
    assert cc.resolve_modules(pkg, "core") == ("scoring.core", [])
    assert cc.resolve_modules(pkg, "scoring.core.core_fn") == ("scoring.core", ["core_fn"])
    assert cc.resolve_modules(pkg, "nonexistent") == (None, ["nonexistent"])


def test_root_names_resolve_to_the_module_that_defines_them(fake_package):
    """A root name import roots its defining module, not the whole package."""
    pkg = cc.load_package(fake_package)
    assert pkg.root_module("core_fn") == "scoring.core"
    assert pkg.root_module("renamed_util") == "scoring.util"
    assert pkg.root_module("__version__") is None  # defined in the root itself
    assert pkg.root_module("core") == "scoring.core"  # legacy flat module name
    assert pkg.root_module("scoring") == "scoring"


def test_string_based_imports_inside_the_package_are_edges(fake_package):
    """``importlib.import_module("<pkg>.x")`` with a literal name is an edge."""
    (fake_package / "lazy.py").write_text(
        "import importlib\n"
        "def lazy_fn():\n"
        "    return importlib.import_module('llm_dojo_scoring.orphan')\n",
        encoding="utf-8",
    )
    assert cc.import_graph(fake_package)["lazy"] == {"orphan"}


# ---------------------------------------------------------------------------
# scanning consumer source
# ---------------------------------------------------------------------------


def test_scan_roots_the_defining_module_of_root_names_and_flat_paths(fake_package):
    """Consumer imports of every spelling root the module that defines the name."""
    pkg = cc.load_package(fake_package)
    source = (
        "from llm_dojo_scoring import core_fn, orphan_fn as o\n"
        "from llm_dojo_scoring.core import something\n"
        "from llm_dojo_scoring.scoring import util\n"
        "import llm_dojo_scoring.lazy\n"
        "def f():\n"
        "    from llm_dojo_scoring.held.one import x\n"
    )
    found = cc.scan_source(pkg, source)
    assert found.modules == {
        "scoring.core",
        "orphan",
        "scoring",
        "scoring.util",
        "lazy",
        "held.one",
    }


def test_root_star_import_roots_every_module_the_root_exports(fake_package):
    """``from llm_dojo_scoring import *`` binds the root's public names, so it roots their modules."""
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring import *\n")
    assert {"orphan", "scoring.core", "scoring.util"} <= found.modules
    assert "lazy" not in found.modules  # the fake root does not export it


def test_root_star_import_honours_the_root_all(fake_package):
    """With a root ``__all__`` the star import reaches exactly the listed names' modules."""
    init = fake_package / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8") + "__all__ = ['core_fn']\n", encoding="utf-8")
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring import *\n")
    assert found.modules == {"scoring.core"}


def test_subpackage_star_import_roots_the_package_and_its_all_submodules(fake_package):
    """A star import from a package roots it and the submodules its ``__all__`` lists."""
    (fake_package / "scoring" / "__init__.py").write_text("__all__ = ['util']\n", encoding="utf-8")
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring.scoring import *\n")
    assert found.modules == {"scoring", "scoring.util"}


def test_module_star_import_roots_the_module(fake_package):
    """A star import from a module (flat legacy path too) roots that module."""
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring.core import *\n")
    assert found.modules == {"scoring.core"}


def test_star_import_keeps_the_exported_module_out_of_the_delete_list(tmp_path, fake_package):
    """End to end: a consumer star import must not let ``--write`` mark an exported module delete."""
    mail = _write_tree(tmp_path / "mail", {"src/app.py": "from llm_dojo_scoring import *\n"})
    sbx = _write_tree(tmp_path / "sbx", {"scripts/run.py": "x = 1\n"})
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 0
    data = json.loads((tmp_path / "out" / "closure.json").read_text(encoding="utf-8"))
    assert {"orphan", "scoring.core", "scoring.util"} <= set(data["roots"]["MAIL"])
    assert data["modules"]["orphan"]["decision"] == "keep"


def test_scan_follows_package_aliases_attributes_and_patch_strings(fake_package):
    """Attribute access on a package alias and ``mock.patch`` target strings are roots."""
    pkg = cc.load_package(fake_package)
    source = (
        "import llm_dojo_scoring as dojo\n"
        "import llm_dojo_scoring.scoring.util as u\n"
        "dojo.orphan_fn()\n"
        "patch('llm_dojo_scoring.lazy.lazy_fn')\n"
        "print('see llm_dojo_scoring.held.two for details')\n"
    )
    found = cc.scan_source(pkg, source)
    assert found.modules == {"orphan", "scoring.util", "lazy"}


def test_scan_records_dispatch_keys_and_roots_the_dispatch_modules(fake_package):
    """String keys passed to the dispatch functions are recorded; dynamic ones are counted."""
    pkg = cc.load_package(fake_package)
    source = (
        "from llm_dojo_scoring import get_suite\n"
        "import llm_dojo_scoring.scoring.tasks as t\n"
        "get_suite('sorter')\n"
        "get_suite(kind)\n"
        "t.score_task(task='legalbench')\n"
    )
    found = cc.scan_source(pkg, source)
    assert found.dispatch == {"get_suite": {"sorter"}, "score_task": {"legalbench"}}
    assert found.dynamic == {"get_suite": 1}
    assert {"scoring.suites", "scoring.tasks"} <= found.modules


def test_root_star_import_binds_the_exported_dispatch_functions(fake_package):
    """After ``from <pkg> import *`` a bare ``get_suite("sorter")`` records its dispatch key."""
    init = fake_package / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8") + "from .scoring.suites import get_suite\n", encoding="utf-8")
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring import *\nget_suite('sorter')\n")
    assert found.dispatch == {"get_suite": {"sorter"}}
    assert "scoring.suites" in found.modules


def test_module_star_import_binds_the_dispatch_functions_it_defines(fake_package):
    """``from <pkg>.scoring.suites import *`` binds ``get_suite`` for the call scanner too."""
    pkg = cc.load_package(fake_package)
    found = cc.scan_source(pkg, "from llm_dojo_scoring.scoring.suites import *\nget_suite('sorter')\n")
    assert found.dispatch == {"get_suite": {"sorter"}}


def test_contract_surface_name_defined_in_the_root_is_not_unresolved(fake_package):
    """A ``package:name`` entry for a name the root itself defines is resolved; a missing one is not."""
    pkg = cc.load_package(fake_package)
    found = cc.scan_contract_surface(pkg, {"names": {"llm_dojo_scoring:__version__": 1, "llm_dojo_scoring:gone": 1}})
    assert found.unresolved == {"llm_dojo_scoring:gone"}


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


def _decisions(fake_package, roots_by_source, hold=None):
    """Classify the fake package for the given roots and hold list."""
    pkg = cc.load_package(fake_package)
    graph = cc.import_graph(fake_package)
    lines = {name: 1 for name in graph}
    return cc.classify(
        graph,
        lines,
        roots_by_source,
        hold={} if hold is None else hold,
        init_imports={"orphan", "scoring.core", "scoring.util"},
    ), pkg


def test_classify_keeps_roots_and_their_closure_and_deletes_the_rest(fake_package):
    """Reached modules are kept, parents of kept modules too, everything else is deleted."""
    decisions, _ = _decisions(fake_package, {"MAIL": {"scoring.core"}})
    kept = {m for m, d in decisions.items() if d["decision"] == "keep"}
    assert kept == {"__init__", "_layout", "scoring", "scoring.core", "scoring.util", "lazy"}
    assert decisions["orphan"]["decision"] == "delete"
    assert "root __init__" in decisions["orphan"]["reason"]
    assert decisions["scoring.core"]["reason"] == "consumer import: MAIL"
    assert decisions["scoring.util"]["reason"] == "imported by kept scoring.core"
    assert decisions["scoring"]["reason"].startswith("package of kept")
    assert set(decisions) == set(cc.import_graph(fake_package))


def test_hold_entries_get_hold_decision_and_their_imports_are_held(fake_package):
    """A HOLD entry is held (a package entry covers its modules); its imports follow it."""
    hold = {"held": "in-flight work #1", "orphan": "in-flight work #2"}
    decisions, _ = _decisions(fake_package, {"MAIL": {"scoring.core"}}, hold=hold)
    assert decisions["held"] == {"decision": "hold", "reason": "in-flight work #1", "lines": 1}
    assert decisions["held.one"]["decision"] == "hold"
    assert decisions["held.two"]["decision"] == "hold"
    assert decisions["orphan"]["decision"] == "hold"
    assert decisions["orphan"]["reason"] == "in-flight work #2"
    assert decisions["tidy.leaf"]["decision"] == "delete"


def test_hold_closure_marks_imports_of_held_modules_as_held(fake_package):
    """A module imported by a held module is held unless a consumer already reaches it."""
    hold = {"held.one": "in-flight work"}
    decisions, _ = _decisions(fake_package, {"MAIL": set()}, hold=hold)
    assert decisions["held.one"]["decision"] == "hold"
    assert decisions["held.two"] == {
        "decision": "hold",
        "reason": "imported by held held.one",
        "lines": 1,
    }
    assert decisions["held"]["decision"] == "hold"  # package of a held module


def test_a_held_module_that_a_consumer_reaches_stays_keep(fake_package):
    """``keep`` wins over ``hold``."""
    decisions, _ = _decisions(fake_package, {"MAIL": {"held.one"}}, hold={"held.one": "x"})
    assert decisions["held.one"]["decision"] == "keep"
    assert decisions["held.two"]["decision"] == "keep"


def test_every_real_hold_entry_names_a_module_of_the_real_package():
    """HOLD must name real modules; an entry for a missing module is a stale entry."""
    graph = cc.import_graph(_REPO_ROOT / "llm_dojo_scoring")
    assert cc.missing_hold_entries(cc.HOLD, graph) == []
    expanded = cc.expand_hold(cc.HOLD, graph)
    assert {"scoring.doc_scorers", "scoring.doc_scorers.dispatch", "pipeline.archive"} <= set(expanded)
    for reason in cc.HOLD.values():
        assert re.search(r"#\d+", reason), f"HOLD reason needs an issue number: {reason!r}"


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _cli_args(tmp_path, fake_package, *extra):
    """Argument list that points the CLI at the fake package, consumers and fixtures."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "consumer_surface.json").write_text(
        json.dumps({"top_level": {"orphan_fn": {}}, "modules": {}, "dispatch": {}, "patches": []}),
        encoding="utf-8",
    )
    (fixtures / "contract_surface.json").write_text(json.dumps({"names": {}}), encoding="utf-8")
    return [
        "--package-dir", str(fake_package),
        "--fixtures-dir", str(fixtures),
        "--output", str(tmp_path / "out" / "closure.json"),
        *extra,
    ]


@pytest.fixture(autouse=True)
def _fake_hold(request, monkeypatch):
    """CLI tests run on the fake package, so the real hold list (real modules) is replaced."""
    if request.node.name.startswith(
        ("test_write", "test_check", "test_extra", "test_missing_extra", "test_a_consumer", "test_star_import")
    ):
        monkeypatch.setattr(cc, "HOLD", {"held": "in-flight work #1"})


@pytest.fixture()
def consumers(tmp_path):
    """Two plain-directory consumers that import the fake package."""
    mail = _write_tree(
        tmp_path / "mail",
        {"src/app.py": "from llm_dojo_scoring.core import core_fn\n", "vendor/skip.py": "import llm_dojo_scoring.lazy\n"},
    )
    sbx = _write_tree(
        tmp_path / "sbx",
        {"scripts/run.py": "from llm_dojo_scoring.scoring.util import util_fn\n"},
    )
    return mail, sbx


def test_write_then_check_round_trips_and_is_deterministic(tmp_path, fake_package, consumers):
    """``--write`` produces the JSON; ``--check`` against the same inputs exits 0."""
    mail, sbx = consumers
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    out = tmp_path / "out" / "closure.json"

    assert cc.main([*args, "--write"]) == 0
    first = out.read_text(encoding="utf-8")
    assert cc.main([*args, "--check"]) == 0
    assert cc.main([*args, "--write"]) == 0
    assert out.read_text(encoding="utf-8") == first

    data = json.loads(first)
    assert set(data["roots"]) == {"MAIL", "SBX", "consumer_surface", "contract_surface"}
    assert data["roots"]["MAIL"] == ["scoring.core"]  # vendor/ is skipped
    assert data["roots"]["consumer_surface"] == ["orphan"]
    assert data["modules"]["orphan"]["decision"] == "keep"
    assert data["modules"]["scoring.core"]["lines"] == 4
    assert str(tmp_path) not in first


def test_check_exits_1_on_drift_and_prints_a_diff(tmp_path, fake_package, consumers, capsys):
    """A changed decision (or a changed consumer) is drift: exit 1 with a diff."""
    mail, sbx = consumers
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 0
    capsys.readouterr()

    out = tmp_path / "out" / "closure.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    data["modules"]["lazy"]["decision"] = "delete"
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert cc.main([*args, "--check"]) == 1
    err = capsys.readouterr().err
    assert "drift" in err
    assert '"decision": "delete"' in err or "lazy" in err


def test_check_exits_1_when_a_consumer_changes(tmp_path, fake_package, consumers):
    """A new consumer import changes the roots, so ``--check`` reports drift."""
    mail, sbx = consumers
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 0
    (mail / "src" / "extra.py").write_text("from llm_dojo_scoring.held.two import two_fn\n", encoding="utf-8")
    assert cc.main([*args, "--check"]) == 1


def test_check_exits_2_when_a_requested_checkout_is_missing(tmp_path, fake_package, consumers, capsys):
    """A missing checkout is not drift: exit 2, and nothing is written."""
    mail, _ = consumers
    args = _cli_args(
        tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(tmp_path / "absent")
    )
    assert cc.main([*args, "--check"]) == 2
    assert cc.main([*args, "--write"]) == 2
    assert not (tmp_path / "out" / "closure.json").exists()
    assert "SBX" in capsys.readouterr().err


def test_a_consumer_file_that_does_not_parse_fails_closed_and_writes_nothing(
    tmp_path, fake_package, consumers, capsys
):
    """An unparsable consumer file hides imports: exit 2 naming the file, no JSON written."""
    mail, sbx = consumers
    (mail / "src" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 2
    err = capsys.readouterr().err
    assert "src/broken.py" in err and "MAIL" in err
    assert not (tmp_path / "out" / "closure.json").exists()


def test_a_consumer_import_of_a_removed_name_fails_closed_and_writes_nothing(
    tmp_path, fake_package, consumers, capsys
):
    """An import the package no longer satisfies cannot be rooted: exit 2 naming it, no JSON written."""
    mail, sbx = consumers
    (mail / "src" / "stale.py").write_text(
        "from llm_dojo_scoring import removed_name\nfrom llm_dojo_scoring import __version__\n", encoding="utf-8"
    )
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 2
    assert cc.main([*args, "--check"]) == 2
    err = capsys.readouterr().err
    assert "removed_name" in err and "__version__" not in err
    assert not (tmp_path / "out" / "closure.json").exists()


def test_check_does_not_accept_a_scan_with_parse_failures(tmp_path, fake_package, consumers, capsys):
    """``--check`` against matching JSON still exits 2 when a consumer file does not parse."""
    mail, sbx = consumers
    args = _cli_args(tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx))
    assert cc.main([*args, "--write"]) == 0
    (sbx / "scripts" / "broken.py").write_text("class (:\n", encoding="utf-8")
    capsys.readouterr()
    assert cc.main([*args, "--check"]) == 2
    assert "SBX" in capsys.readouterr().err


def test_extra_refs_are_read_without_checking_them_out(tmp_path, fake_package):
    """``--extra-ref`` reads a branch's files with git; the work tree is never touched."""
    mail = tmp_path / "mailgit"
    _init_repo(mail)
    _write_tree(mail, {"src/app.py": "from llm_dojo_scoring.lazy import lazy_fn\n"})
    _commit_all(mail, "main")
    _git(mail, "checkout", "-q", "-b", "stack/x")
    _write_tree(mail, {"tools/more.py": "from llm_dojo_scoring.orphan import orphan_fn\n"})
    ref_sha = _commit_all(mail, "stack")
    _git(mail, "checkout", "-q", "main")
    sbx = _write_tree(tmp_path / "sbx", {"scripts/run.py": "x = 1\n"})

    args = _cli_args(
        tmp_path, fake_package,
        "--mailroom", str(mail), "--sandbox", str(sbx), "--extra-ref", "stack/x",
    )
    assert cc.main([*args, "--write"]) == 0
    data = json.loads((tmp_path / "out" / "closure.json").read_text(encoding="utf-8"))

    assert data["roots"]["MAIL"] == ["lazy"]
    assert data["roots"]["MAIL@stack/x"] == ["lazy", "orphan"]
    assert data["sources"]["MAIL@stack/x"]["commit"] == ref_sha
    assert not (mail / "tools" / "more.py").exists()  # not checked out
    assert str(tmp_path) not in json.dumps(data)


def test_missing_extra_ref_exits_2(tmp_path, fake_package, consumers):
    """An unknown ref cannot be scanned: exit 2."""
    mail = tmp_path / "mailgit"
    _init_repo(mail)
    _write_tree(mail, {"src/app.py": "x = 1\n"})
    _commit_all(mail)
    _, sbx = consumers
    args = _cli_args(
        tmp_path, fake_package, "--mailroom", str(mail), "--sandbox", str(sbx), "--extra-ref", "nope"
    )
    assert cc.main([*args, "--check"]) == 2


# ---------------------------------------------------------------------------
# the committed JSON
# ---------------------------------------------------------------------------


_COMMITTED = _REPO_ROOT / "docs" / "analysis" / "data" / "consumer_closure.json"
_ABSOLUTE_PATH = re.compile(r"(^|[\s\"'=(])(/(home|Users|tmp|root|var|mnt|private)/|[A-Za-z]:\\)")


def test_committed_json_covers_every_module_file_of_the_real_package():
    """The committed decision covers each module file; regenerate it with ``--write``."""
    data = json.loads(_COMMITTED.read_text(encoding="utf-8"))
    package = _REPO_ROOT / "llm_dojo_scoring"
    on_disk = set(cc.import_graph(package))
    assert set(data["modules"]) == on_disk
    for name, entry in data["modules"].items():
        assert entry["decision"] in {"keep", "hold", "delete"}, name
        assert isinstance(entry["reason"], str) and entry["reason"], name
        assert isinstance(entry["lines"], int) and entry["lines"] >= 0, name
    assert list(data["modules"]) == sorted(data["modules"])


def test_committed_json_has_no_local_paths_or_timestamps():
    """Only repo codes and commit ids identify the inputs: no filesystem paths, no times."""
    text = _COMMITTED.read_text(encoding="utf-8")
    assert not _ABSOLUTE_PATH.search(text)
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    data = json.loads(text)
    for source, meta in data["sources"].items():
        commit = meta.get("commit")
        assert commit is None or re.fullmatch(r"[0-9a-f]{40}", commit), source


def test_committed_json_honours_the_hold_list_and_the_structural_modules():
    """Held modules are keep or hold, never delete; the package root is always kept."""
    data = json.loads(_COMMITTED.read_text(encoding="utf-8"))
    graph = cc.import_graph(_REPO_ROOT / "llm_dojo_scoring")
    for name in cc.expand_hold(cc.HOLD, graph):
        assert data["modules"][name]["decision"] in {"keep", "hold"}, name
    for name in cc.STRUCTURAL:
        assert data["modules"][name]["decision"] == "keep"


def test_lazy_root_tables_resolve_root_names(fake_package):
    """A PEP 562 root (``_LAZY`` name -> (module, attr), ``_SUBMODULES`` name -> module) maps names."""
    (fake_package / "__init__.py").write_text(
        "from ._layout import install_legacy_aliases\n"
        "_LAZY: dict[str, tuple[str, str]] = {\n"
        "    'core_fn': ('scoring.core', 'core_fn'),\n"
        "    'renamed_util': ('scoring.util', 'util_fn'),\n"
        "}\n"
        "_SUBMODULES: dict[str, str] = {'lazy': 'lazy', 'held_two': 'held.two'}\n"
        "__version__ = '0'\n"
    )
    names = cc.load_package(fake_package).root_names
    assert names["core_fn"] == "scoring.core"
    assert names["renamed_util"] == "scoring.util"
    assert names["lazy"] == "lazy"
    assert names["held_two"] == "held.two"
