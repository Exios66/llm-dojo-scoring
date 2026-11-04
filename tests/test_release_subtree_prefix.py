"""Release and audit tools work when Dojo sits under a hub prefix.

Digital-Mailroom imports this repo as ``packages/llm-dojo-scoring/``. There the
git root is the hub, so ``git show <commit>:<path>`` with a root-relative path
names the wrong file, and a fresh worktree's root is the hub, not the package.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import load_script

PREFIX = "packages/llm-dojo-scoring"


def _git(root: Path, *args: str) -> str:
    """Run git in ``root`` with a fixed identity and return stdout."""
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def hub(tmp_path):
    """A hub-shaped repo whose root and package both carry a ``pyproject.toml``."""
    root = tmp_path / "hub"
    package = root / PREFIX
    (package / "llm_dojo_scoring").mkdir(parents=True)
    (root / "pyproject.toml").write_text('version = "9.9.9"\n')
    (package / "pyproject.toml").write_text('version = "1.2.3"\n')
    (package / "llm_dojo_scoring" / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (package / "llm_dojo_scoring" / "core.py").write_text("VALUE = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


@pytest.fixture
def release_in(monkeypatch):
    """Point the release module at a given package root."""
    release = load_script("release")

    def bind(package_root: Path):
        """Return the release module with ``REPO_ROOT`` set to ``package_root``."""
        monkeypatch.setattr(release, "REPO_ROOT", package_root)
        return release

    return bind


def test_package_prefix_names_the_hub_subtree(hub, release_in):
    """Under a hub, the prefix is the package directory; standalone it is empty."""
    assert release_in(hub / PREFIX).package_prefix() == f"{PREFIX}/"
    assert release_in(hub).package_prefix() == ""


def test_show_at_commit_reads_the_package_file_not_the_hub_root(hub, release_in):
    """``show_at_commit`` reads the package's files at a commit, even under a prefix."""
    release = release_in(hub / PREFIX)
    assert release.show_at_commit("HEAD", "pyproject.toml") == 'version = "1.2.3"\n'
    init = release.show_at_commit("HEAD", "llm_dojo_scoring/__init__.py")
    assert init == '__version__ = "1.2.3"\n'


def test_show_at_commit_still_works_standalone(hub, release_in):
    """At a repository root the same call reads root files, as before."""
    assert release_in(hub).show_at_commit("HEAD", "pyproject.toml") == 'version = "9.9.9"\n'


def test_build_assets_builds_from_the_package_dir(hub, release_in, monkeypatch):
    """The detached worktree build reads the package's pyproject and builds there."""
    release = release_in(hub / PREFIX)
    builds: list[Path] = []
    real_run = release.run

    def fake_run(cmd, *, check=True, cwd=None, env=None):
        """Record build commands instead of running a real build."""
        if "build" in cmd:
            builds.append(Path(cwd))
            out = Path(cmd[cmd.index("--out-dir" if "--out-dir" in cmd else "--outdir") + 1])
            (out / "pkg-1.2.3.tar.gz").write_text("artifact")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, check=check, cwd=cwd, env=env)

    monkeypatch.setattr(release, "run", fake_run)
    commit = _git(hub, "rev-parse", "HEAD").strip()
    out_dir = hub / PREFIX / "dist" / "release"  # the default asset dir is in the package
    release._build_assets_at_commit("1.2.3", out_dir=out_dir, commit=commit)
    assert len(builds) == 1 and builds[0].as_posix().endswith(PREFIX)
    assert (out_dir / "pkg-1.2.3.tar.gz").read_text() == "artifact"


def test_build_assets_removes_the_worktree_when_the_prefix_lookup_fails(hub, release_in, monkeypatch):
    """A failing prefix lookup still runs the cleanup that unregisters the worktree."""
    release = release_in(hub / PREFIX)

    def broken_prefix():
        """Fail the way a git error would."""
        raise release.ReleaseError("rev-parse failed")

    monkeypatch.setattr(release, "package_prefix", broken_prefix)
    commit = _git(hub, "rev-parse", "HEAD").strip()
    with pytest.raises(release.ReleaseError, match="rev-parse failed"):
        release._build_assets_at_commit("1.2.3", out_dir=hub / PREFIX / "dist" / "release", commit=commit)
    worktrees = [line for line in _git(hub, "worktree", "list", "--porcelain").splitlines()
                 if line.startswith("worktree ")]
    assert len(worktrees) == 1, worktrees


def test_consumer_audit_reads_a_package_under_a_prefix(hub):
    """The consumer-surface audit reads a git tree whose root is a hub package."""
    audit = load_script("audit_consumer_surface")
    files = audit._read_git_tree(hub / PREFIX, "HEAD")
    assert files == {
        "llm_dojo_scoring/__init__.py": '__version__ = "1.2.3"\n',
        "llm_dojo_scoring/core.py": "VALUE = 1\n",
    }
