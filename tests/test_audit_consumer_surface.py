"""Regression tests for ``scripts/audit_consumer_surface.py`` (PR #103 review).

Network-free and checkout-free: every consumer repository here is a temporary
directory, so the tests never depend on the developer paths in ``REPOS``.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

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


# ---------------------------------------------------------------------------
# --only CODES / checkout locations / provenance without local paths
# ---------------------------------------------------------------------------


def _site(repo: str, file: str = "a.py", line: int = 1) -> dict:
    """One recorded consumer site."""
    return {"repo": repo, "file": file, "line": line}


def _meta(label: str, scanned: bool = True, commit: str | None = "c" * 40) -> dict:
    """A ``generated_from`` entry as recorded (repo code and commit, no path)."""
    return {
        "label": label,
        "ref": "main" if scanned else None,
        "commit": commit if scanned else None,
        "scanned": scanned,
        "reason": None if scanned else "path does not exist",
        "files_scanned": 3 if scanned else 0,
    }


def _surface(sites_by_name: dict, *, mail_sites=None) -> dict:
    """A payload with top-level names, one module attr, one dispatch key and one patch."""
    payload = _fixture_payload(scanned=True)
    payload["generated_from"] = {"MAIL": _meta("MAIL"), "SBX": _meta("SBX"), "EDA": _meta("EDA")}
    payload["top_level"] = {
        name: {"kind": "function", "in_all": True, "defined_in": "m", "consumers": sites}
        for name, sites in sites_by_name.items()
    }
    payload["modules"] = {
        "scoring.suites": {
            "legacy": True,
            "attrs": {
                "get_suite": {"consumers": mail_sites or [], "private": False, "defined_in": "scoring.suites"}
            },
        }
    }
    payload["dispatch"] = {
        "get_suite": {
            "dynamic": [],
            "literals": {"sorter": mail_sites or []},
            "supported": ["sorter"],
        }
    }
    payload["patches"] = [{**s, "target": "llm_dojo_scoring.x"} for s in (mail_sites or [])]
    payload["scores"] = {"aliases": {}, "registry_ids": [], "visualizer_reads": {}}
    return payload


def test_merge_rescans_only_the_requested_codes_and_leaves_the_rest(monkeypatch):
    """Sites of other consumers survive; sites of requested codes are replaced by the rescan."""
    existing = _surface(
        {
            "shared": [_site("MAIL", "old.py"), _site("EDA", "eda.py")],
            "gone": [_site("MAIL", "old.py")],
            "eda_only": [_site("EDA", "eda.py")],
        },
        mail_sites=[_site("MAIL", "old.py"), _site("EDA", "eda.py", 9)],
    )
    fresh = _surface({"shared": [_site("MAIL", "new.py")], "added": [_site("MAIL", "new.py")]},
                     mail_sites=[_site("MAIL", "new.py")])
    fresh["generated_from"] = {"MAIL": _meta("MAIL", commit="d" * 40)}

    merged = audit.merge_fixture(existing, fresh, {"MAIL"})

    assert [s["file"] for s in merged["top_level"]["shared"]["consumers"]] == ["eda.py", "new.py"]
    assert "gone" not in merged["top_level"]  # its only consumer was a rescanned code
    assert merged["top_level"]["eda_only"] == existing["top_level"]["eda_only"]
    assert [s["file"] for s in merged["top_level"]["added"]["consumers"]] == ["new.py"]
    attr = merged["modules"]["scoring.suites"]["attrs"]["get_suite"]["consumers"]
    assert sorted((s["repo"], s["file"]) for s in attr) == [("EDA", "eda.py"), ("MAIL", "new.py")]
    literal = merged["dispatch"]["get_suite"]["literals"]["sorter"]
    assert sorted((s["repo"], s["file"]) for s in literal) == [("EDA", "eda.py"), ("MAIL", "new.py")]
    assert [p["file"] for p in merged["patches"]] == ["eda.py", "new.py"]
    assert merged["generated_from"]["MAIL"]["commit"] == "d" * 40
    assert merged["generated_from"]["SBX"] == existing["generated_from"]["SBX"]
    assert merged["generated_from"]["EDA"] == existing["generated_from"]["EDA"]


def test_merge_with_no_changes_reproduces_the_fixture():
    """Rescanning the same sources gives back exactly the recorded fixture."""
    existing = _surface({"x": [_site("MAIL"), _site("SBX")]}, mail_sites=[_site("MAIL"), _site("SBX")])
    fresh = _surface({"x": [_site("MAIL")]}, mail_sites=[_site("MAIL")])
    fresh["generated_from"] = {"MAIL": existing["generated_from"]["MAIL"]}
    assert audit.merge_fixture(existing, fresh, {"MAIL"}) == existing


def test_only_checks_just_the_requested_codes(monkeypatch, tmp_path, capsys):
    """``--only MAIL`` ignores a pinned checkout (EDA) that is unavailable here."""
    pinned = _surface({"x": [_site("EDA"), _site("MAIL")]}, mail_sites=[_site("MAIL")])
    fresh = _surface({"x": [_site("MAIL")]}, mail_sites=[_site("MAIL")])
    fresh["generated_from"] = {"MAIL": pinned["generated_from"]["MAIL"]}
    _redirect_fixture(monkeypatch, tmp_path, pinned, fresh)
    monkeypatch.setattr(audit, "build_fixture", lambda *a, **k: json.loads(json.dumps(fresh)))

    assert audit.main(["--only", "MAIL", "--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_only_exits_2_when_a_requested_checkout_is_missing(monkeypatch, tmp_path, capsys):
    """A requested code that cannot be scanned is exit 2 for both ``--check`` and ``--write``."""
    pinned = _surface({"x": [_site("MAIL")]}, mail_sites=[_site("MAIL")])
    fixture = _redirect_fixture(monkeypatch, tmp_path, pinned, pinned)
    fresh = _surface({}, mail_sites=[])
    fresh["generated_from"] = {"MAIL": _meta("MAIL", scanned=False)}
    monkeypatch.setattr(audit, "build_fixture", lambda *a, **k: json.loads(json.dumps(fresh)))
    before = fixture.read_text(encoding="utf-8")

    assert audit.main(["--only", "MAIL", "--check"]) == 2
    assert audit.main(["--only", "MAIL", "--write"]) == 2
    assert fixture.read_text(encoding="utf-8") == before
    assert "MAIL" in capsys.readouterr().err


def test_only_rejects_unknown_codes(capsys):
    """An unknown consumer code is a usage error (exit 2)."""
    assert audit.main(["--only", "NOPE", "--check"]) == 2
    assert "NOPE" in capsys.readouterr().err


def test_root_rejects_unknown_codes_before_scanning_or_writing(monkeypatch, tmp_path, capsys):
    """A mistyped ``--root`` code is a usage error: it must not silently scan the default checkout."""
    pinned = _surface({"x": [_site("MAIL")]}, mail_sites=[_site("MAIL")])
    fixture = _redirect_fixture(monkeypatch, tmp_path, pinned, pinned)

    def _must_not_scan(*args, **kwargs):
        """Fail the test if the audit starts scanning despite the bad ``--root`` code."""
        raise AssertionError("scanned despite an unknown --root code")

    monkeypatch.setattr(audit, "build_fixture", _must_not_scan)
    before = fixture.read_text(encoding="utf-8")

    for argv in (
        ["--only", "MAIL", "--root", "MAL=/x", "--write"],
        ["--root", "MAL=/x", "--check"],
    ):
        assert audit.main(argv) == 2
        err = capsys.readouterr().err
        assert "MAL" in err and "MAIL" in err  # names the bad code and the known ones
    assert fixture.read_text(encoding="utf-8") == before


def test_only_write_refreshes_requested_codes_and_keeps_the_others(monkeypatch, tmp_path):
    """``--only MAIL --write`` rewrites the fixture with the merge result."""
    pinned = _surface({"keep": [_site("EDA")], "x": [_site("MAIL", "old.py")]},
                      mail_sites=[_site("MAIL", "old.py")])
    fresh = _surface({"x": [_site("MAIL", "new.py")]}, mail_sites=[_site("MAIL", "new.py")])
    fresh["generated_from"] = {"MAIL": pinned["generated_from"]["MAIL"]}
    fixture = _redirect_fixture(monkeypatch, tmp_path, pinned, fresh)
    monkeypatch.setattr(audit, "build_fixture", lambda *a, **k: json.loads(json.dumps(fresh)))

    assert audit.main(["--only", "MAIL", "--write"]) == 0

    written = json.loads(fixture.read_text(encoding="utf-8"))
    assert written["top_level"]["keep"] == pinned["top_level"]["keep"]
    assert [s["file"] for s in written["top_level"]["x"]["consumers"]] == ["new.py"]


def test_root_flag_overrides_the_checkout_location(tmp_path, monkeypatch):
    """``--root CODE=PATH`` locates a checkout without environment variables."""
    root = tmp_path / "mail"
    root.mkdir()
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    monkeypatch.delenv("MAILROOM_ROOT", raising=False)
    spec = next(s for s in audit.REPOS if s.label == "MAIL")
    files, meta = audit.scan_repo(spec, {"MAIL": str(root)})
    assert files == {"a.py": "a = 1\n"}
    assert meta["scanned"] is True


def test_scan_provenance_has_a_repo_code_and_commit_but_no_local_path(tmp_path, monkeypatch):
    """``generated_from`` identifies a checkout by code and commit, never by filesystem path."""
    root = tmp_path / "consumer"
    _make_git_repo(root)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.setenv("AUDIT_TEST_ROOT", str(root))
    _, meta = audit.scan_repo(audit.RepoSpec("T", "unused", "AUDIT_TEST_ROOT"))
    assert meta["label"] == "T" and len(meta["commit"]) == 40
    assert "path" not in meta
    assert str(tmp_path) not in json.dumps(meta)


def test_default_checkout_locations_are_siblings_not_developer_paths():
    """No built-in default points at a developer's home directory."""
    for spec in audit.REPOS:
        assert Path(spec.default_path).parent == audit.REPO_ROOT.parent, spec.label
        assert spec.default_path.endswith(("local-mailroom-sandbox", "llm-mailroom", "Mailroom-Corpus-EDA",
                                           "eval-environment", "mailroom-ml", "The-Mailroom"))


def test_committed_fixture_records_no_local_paths():
    """The pinned fixture holds repo codes and commits only."""
    fixture = audit.FIXTURE_PATH.read_text(encoding="utf-8")
    assert "/Users/" not in fixture
    for label, meta in json.loads(fixture)["generated_from"].items():
        assert "path" not in meta, label
