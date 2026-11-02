"""Regression tests for ``scripts/audit_consumer_surface.py`` (PR #103 review).

Network-free and checkout-free: every consumer repository here is a temporary
directory, so the tests never depend on the developer paths in ``REPOS``.
"""

from __future__ import annotations

import ast
import json
import subprocess

import pytest

from conftest import load_script

audit = load_script("audit_consumer_surface")


def _git(root, *args):
    """Run one git command in *root*, failing the test on error."""
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _make_git_repo(root):
    """Create an empty git repository with a local test identity."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")


def test_filesystem_reader_prunes_skip_dirs_and_ignores_py_named_directories(tmp_path):
    """Skipped trees are pruned and a ``*.py`` directory is never read as a file."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "site.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "z.py").write_text("z = 3\n", encoding="utf-8")
    # A directory whose name ends in ``.py`` used to crash ``read_text``.
    (tmp_path / "weird.py").mkdir()
    (tmp_path / "weird.py" / "inner.py").write_text("w = 4\n", encoding="utf-8")

    files = audit._read_filesystem_tree(tmp_path)

    assert files == {"pkg/mod.py": "x = 1\n", "weird.py/inner.py": "w = 4\n"}
    assert list(files) == sorted(files)


def test_git_checkout_is_read_from_committed_blobs_not_the_working_tree(tmp_path, monkeypatch):
    """A git checkout is scanned at HEAD; dirty and untracked files are ignored."""
    root = tmp_path / "consumer"
    _make_git_repo(root)
    (root / "app.py").write_text("committed = True\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "init")
    # Uncommitted edit and untracked scratch file must not leak into the scan.
    (root / "app.py").write_text("committed = False\n", encoding="utf-8")
    (root / "scratch.py").write_text("import llm_dojo_scoring\n", encoding="utf-8")

    monkeypatch.setenv("AUDIT_TEST_ROOT", str(root))
    spec = audit.RepoSpec("T", str(tmp_path / "unused"), "AUDIT_TEST_ROOT")
    files, meta = audit.scan_repo(spec)

    assert files == {"app.py": "committed = True\n"}
    assert meta["scanned"] is True
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert meta["commit"] == head
    assert meta["ref"]  # the branch the snapshot was read from


def test_non_git_directory_still_uses_the_filesystem_reader(tmp_path, monkeypatch):
    """A plain directory (no git) is still scanned from the filesystem."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    monkeypatch.setenv("AUDIT_TEST_ROOT", str(root))
    monkeypatch.setattr(audit, "_is_git_checkout", lambda _root: False)
    files, meta = audit.scan_repo(audit.RepoSpec("T", str(root), "AUDIT_TEST_ROOT"))
    assert files == {"a.py": "a = 1\n"}
    assert meta["scanned"] is True and meta["commit"] is None


@pytest.fixture(scope="module")
def index():
    """One package index shared by the collector tests."""
    return audit.PackageIndex()


@pytest.mark.parametrize(
    "source",
    [
        "from llm_dojo_scoring.scoring import suites\nsuites.get_suite('sorter')\n",
        "from llm_dojo_scoring.scoring import suites as s\ns.get_suite('sorter')\n",
        # Legacy flat package path still resolves to the canonical submodule.
        "from llm_dojo_scoring import suites\nsuites.get_suite('sorter')\n",
    ],
)
def test_submodule_alias_dispatch_calls_are_recorded(index, source):
    """``from llm_dojo_scoring.<pkg> import <module>`` aliases feed dispatch pins."""
    surface = audit.Surface(index)
    surface.collect_file("T", "consumer.py", ast.parse(source))
    assert "sorter" in surface.dispatch_literals["get_suite"]


def test_non_module_names_from_a_subpackage_are_not_module_aliases(index):
    """Only real submodules become module aliases."""
    source = (
        "from llm_dojo_scoring.scoring import not_a_module\n"
        "not_a_module.get_suite('sorter')\n"
    )
    surface = audit.Surface(index)
    surface.collect_file("T", "consumer.py", ast.parse(source))
    assert "sorter" not in surface.dispatch_literals["get_suite"]


def _fixture_payload(scanned: bool) -> dict:
    """A minimal manifest with one MAIL checkout, scanned or not."""
    return {
        "schema_version": 1,
        "generated_by": audit.GENERATED_BY,
        "generated_from": {
            "MAIL": {
                "label": "MAIL",
                "path": "/x",
                "ref": None,
                "commit": None,
                "scanned": scanned,
                "reason": None if scanned else "path does not exist",
                "files_scanned": 3 if scanned else 0,
            }
        },
        "top_level": {"get_suite": {"kind": "function"}} if scanned else {},
        "modules": {},
        "dispatch": {},
        "scores": {},
        "patches": [],
    }


def _redirect_fixture(monkeypatch, tmp_path, pinned: dict, fresh: dict):
    """Point the script at a temp fixture and a canned fresh scan."""
    fixture = tmp_path / "tests" / "fixtures" / "consumer_surface.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(audit._dump(pinned), encoding="utf-8")
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit, "FIXTURE_PATH", fixture)
    monkeypatch.setattr(audit, "build_fixture", lambda: json.loads(json.dumps(fresh)))
    return fixture


def test_write_refuses_to_erase_pinned_checkouts_that_are_unavailable(
    monkeypatch, tmp_path, capsys
):
    """``--write`` exits 2 and leaves the fixture alone when a pinned checkout is missing."""
    pinned = _fixture_payload(scanned=True)
    fixture = _redirect_fixture(monkeypatch, tmp_path, pinned, _fixture_payload(scanned=False))
    before = fixture.read_text(encoding="utf-8")

    assert audit.main(["--write"]) == 2

    assert fixture.read_text(encoding="utf-8") == before
    assert "refusing --write" in capsys.readouterr().err


def test_check_reports_unavailable_checkouts_instead_of_drift(monkeypatch, tmp_path, capsys):
    """``--check`` names missing checkouts and exits 2 rather than reporting drift."""
    _redirect_fixture(
        monkeypatch, tmp_path, _fixture_payload(scanned=True), _fixture_payload(scanned=False)
    )

    assert audit.main(["--check"]) == 2

    err = capsys.readouterr().err
    assert "unavailable here: MAIL" in err
    assert "drift" not in err


def test_write_allows_checkouts_that_were_never_pinned_as_scanned(monkeypatch, tmp_path):
    """A checkout already ``scanned: false`` in the fixture does not block ``--write``."""
    # EE is ``scanned: false`` in the committed fixture; that must not block writes.
    fresh = _fixture_payload(scanned=False)
    fixture = _redirect_fixture(monkeypatch, tmp_path, _fixture_payload(scanned=False), fresh)
    assert audit.main(["--write"]) == 0
    assert json.loads(fixture.read_text(encoding="utf-8")) == fresh


def test_check_still_reports_real_drift(monkeypatch, tmp_path, capsys):
    """Genuine surface changes still exit 1 as drift."""
    fresh = _fixture_payload(scanned=True)
    fresh["top_level"] = {"renamed": {"kind": "function"}}
    _redirect_fixture(monkeypatch, tmp_path, _fixture_payload(scanned=True), fresh)
    assert audit.main(["--check"]) == 1
    assert "consumer surface drift" in capsys.readouterr().err
