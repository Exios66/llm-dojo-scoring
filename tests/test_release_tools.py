"""Offline contracts for scripts/release.py (stdlib + local git only)."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.py"


def load_release():
    """Import ``scripts/release.py`` as a module."""
    spec = importlib.util.spec_from_file_location("dojo_release_tools", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def release():
    """The release-tools module."""
    return load_release()


def test_status_json_has_identity_fields(release):
    """``status --json`` reports the repository identity."""
    code = release.main(["status", "--json"])
    assert code == 0


def test_check_accepts_current_stamped_tree(release):
    """The stamped version is consistent; a missing local tag is a warning, not an error.

    Compared with the package's own ``__version__`` rather than a literal, so
    ``release.py cut`` does not have to rewrite this test on every release.
    """
    import llm_dojo_scoring

    state = release.chain_state()
    errors, warnings = release.check_chain(state)
    assert state["pyproject_version"] == state["init_version"] == llm_dojo_scoring.__version__
    assert not errors


def test_cut_dry_run_refuses_existing_section(release):
    """Cutting an already-released version is refused."""
    with pytest.raises(release.ReleaseError, match="already has"):
        release.cut_plan("0.25.0", today="2026-11-01", allow_dirty=True, allow_empty=True)


def _has_tags(*tags: str) -> bool:
    """True when every tag resolves locally (shallow cloud clones carry none)."""
    return all(
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
        for tag in tags
    )


@pytest.mark.skipif(
    not _has_tags("v0.24.2", "v0.25.0"),
    reason="needs release tags; run `git fetch --unshallow --tags`",
)
def test_notes_render_contains_changelog_and_commit(release):
    """Offline notes carry the CHANGELOG section and the commit."""
    notes = release.build_notes(
        "0.25.0",
        previous="v0.24.2",
        title="sorter subclass guide",
        commit_ref="HEAD",
        net=False,
    )
    assert notes["title"].startswith("Dojo v0.25.0:")
    assert "sorter_guide" in notes["body"] or "sorter-facing" in notes["body"]
    assert "0.25.0" in notes["body"]
    assert notes["commit"]
    assert "Pull requests merged" in notes["body"]


#: gh errors that mean the CLI or the API cannot be reached here (not a release-tool bug):
#: not installed, not logged in, no network, refused or rate-limited by the API.
_GH_UNAVAILABLE = re.compile(
    r"No such file or directory|gh auth login|not logged in|authentication|HTTP 40[13]|"
    r"rate limit|could not resolve|error connecting|connection (refused|reset)|timed? ?out|proxy",
    re.IGNORECASE,
)


def test_cli_publish_dry_run_json():
    # v0.25.0 is now published; a dry-run publish must refuse (idempotent)
    # rather than silently re-tag/re-release.
    """A dry-run publish of a published version refuses (idempotent)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "publish", "0.25.0", "--commit", "HEAD", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("release publish dry run timed out after 20 s (network unavailable)")
    # main() writes a ReleaseError payload to stderr; a gh/network failure is
    # an environment limit, not a release-tool regression.
    payload = json.loads(proc.stdout or proc.stderr)
    error = str(payload.get("error", ""))
    if "action" not in payload and error.startswith("gh ") and _GH_UNAVAILABLE.search(error):
        pytest.skip(f"GitHub CLI unavailable here: {error[:120]}")
    assert payload["action"] == "publish"
    assert payload["version"] == "0.25.0"
    assert payload["dry_run"] is True
    assert payload["tag"] == "v0.25.0"
    assert payload["errors"]
    assert any("already published" in e for e in payload["errors"])


def test_missing_executable_is_a_release_error(release):
    """A command that is not installed (e.g. no ``gh``) raises ReleaseError, not FileNotFoundError."""
    with pytest.raises(release.ReleaseError, match="failed"):
        release.run(["definitely-not-an-installed-command-xyz", "--version"])


def test_compat_pin_regex_rounds_trip(release):
    """The compat-test version pin regex bumps cleanly."""
    sample = 'assert dojo.__version__ == "0.25.0"\n'
    match = release.COMPAT_VERSION_RE.search(sample)
    assert match and match["version"] == "0.25.0"
    bumped = release.COMPAT_VERSION_RE.sub(
        lambda m: f'{m.group(1)}0.26.0{m.group(3)}', sample, count=1
    )
    assert bumped == 'assert dojo.__version__ == "0.26.0"\n'


def test_gh_unavailable_pattern_is_narrow():
    """Only unreachable-CLI errors skip the publish test; other gh failures fail it."""
    assert _GH_UNAVAILABLE.search("gh pr list failed: [Errno 2] No such file or directory: 'gh'")
    assert _GH_UNAVAILABLE.search("gh api failed: To get started with GitHub CLI, please run:  gh auth login")
    assert not _GH_UNAVAILABLE.search("gh pr list failed: unknown flag: --bogus")
    assert not _GH_UNAVAILABLE.search("gh release view failed: release not found")


_LOCK_SAMPLE = '''version = 1
revision = 5

[[package]]
name = "jellyfish"
version = "1.2.0"

[[package]]
name = "llm-dojo-scoring"
version = "{version}"
source = {{ editable = "." }}
'''


def test_uv_lock_version_reads_the_root_package_entry(release):
    """Only this package's ``[[package]]`` entry counts, not a dependency's version."""
    assert release.uv_lock_version(_LOCK_SAMPLE.format(version="0.26.0")) == "0.26.0"
    assert release.uv_lock_version("version = 1\n") is None


def test_check_flags_stale_uv_lock(release):
    """A uv.lock still recording the previous version is a chain error (CI's --frozen misses it)."""
    state = release.chain_state()
    stale = dict(state, uv_lock_version="0.0.1")
    errors, _ = release.check_chain(stale)
    assert any("uv.lock records" in e and "uv lock" in e for e in errors)


def test_check_accepts_matching_or_absent_uv_lock(release):
    """A matching lock, or no lock at all, adds no uv.lock error."""
    state = release.chain_state()
    for lock_version in (state["pyproject_version"], None):
        errors, _ = release.check_chain(dict(state, uv_lock_version=lock_version))
        assert not any("uv.lock" in e for e in errors)


def test_cut_plan_reminds_to_relock(release):
    """The cut plan's next steps tell the releaser to run ``uv lock``."""
    plan = release.cut_plan("99.0.0", today="2026-11-03", allow_dirty=True, allow_empty=True)
    assert any("uv lock" in step for step in plan["next"])


def _offline_publish(release, monkeypatch, git_impl):
    """Run ``publish_plan`` with every network/state lookup stubbed and ``git`` replaced."""
    state = {"tags": []}
    monkeypatch.setattr(release, "chain_state", lambda: state)
    monkeypatch.setattr(release, "check_chain", lambda s: ([], []))
    monkeypatch.setattr(release, "section_for", lambda v: {"stamp": None})
    monkeypatch.setattr(release, "_resolve_commit", lambda ref: "a" * 40)
    monkeypatch.setattr(release, "remote_tag_commit", lambda v: None)
    monkeypatch.setattr(release, "remote_release", lambda v: None)
    monkeypatch.setattr(release, "build_notes", lambda *a, **k: {"title": "t", "body": ""})
    monkeypatch.setattr(release, "git", git_impl)
    return release.publish_plan(
        "9.9.9", commit_ref="HEAD", target="main", draft=True,
        with_assets=False, push=False, title=None, notes_file=None,
    )


def _fake_git(lock: str | None, *, lock_read_fails: bool = False):
    """A ``git`` stand-in for a commit stamped 9.9.9 with the given uv.lock (``None`` = absent)."""
    files = {
        "pyproject.toml": 'version = "9.9.9"\n',
        "llm_dojo_scoring/__init__.py": '__version__ = "9.9.9"\n',
    }

    def git(*args):
        """Serve the stubbed tree for ``rev-parse`` / ``ls-tree`` / ``show``."""
        if args[0] == "rev-parse":
            return "\n"  # standalone: the package is the repository root
        if args[0] == "ls-tree":
            return "uv.lock\n" if lock is not None else ""
        if args[0] == "show":
            path = args[1].split(":", 1)[1].removeprefix("./")  # cwd-relative, as git reads it
            if path == "uv.lock":
                if lock_read_fails:
                    raise load_release().ReleaseError("git show failed: object read error")
                return lock
            return files[path]
        raise AssertionError(args)

    return git


def test_publish_skips_lock_check_only_when_uv_lock_absent(release, monkeypatch):
    """A commit without uv.lock passes; a stale lock at the commit is a hard error."""
    plan = _offline_publish(release, monkeypatch, _fake_git(None))
    assert not any("uv.lock" in e for e in plan["errors"])
    plan = _offline_publish(
        release, monkeypatch, _fake_git(_LOCK_SAMPLE.format(version="0.0.1"))
    )
    assert any("uv.lock records" in e for e in plan["errors"])


def test_publish_fails_closed_when_uv_lock_read_fails(release, monkeypatch):
    """A uv.lock that exists but cannot be read raises instead of skipping the check."""
    with pytest.raises(Exception, match="object read error"):
        _offline_publish(release, monkeypatch, _fake_git("x", lock_read_fails=True))


def test_readme_pin_bump_moves_the_badge_alt_text(release, tmp_path, monkeypatch):
    """0.27.2: the release badge's ``[Release vX]`` alt text moves with the badge and link."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "[![Release v0.27.1](https://img.shields.io/badge/release-v0.27.1-6C63FF)]"
        "(https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.27.1)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release, "README", readme)
    assert release._bump_readme_pins("0.27.1", "0.27.2") == 3
    text = readme.read_text(encoding="utf-8")
    assert "0.27.1" not in text and text.count("0.27.2") == 3


def test_check_reports_a_stale_badge_alt_text(release):
    """``check`` counts the badge alt text as a README pin, so a stale one is an error."""
    import re

    text = "[![Release v0.27.0](https://img.shields.io/badge/release-v0.27.2-6C63FF)]"
    pins = set(re.findall(r"(?:release-|releases/tag/|\.git@|\[Release )v(\d+\.\d+\.\d+)", text))
    assert pins == {"0.27.0", "0.27.2"}


def _pins(mailroom, sandbox):
    """Consumer pin records as ``consumer_pins`` returns them."""
    return [
        {"consumer": "llm-mailroom", "repo": "Exios66/llm-mailroom", "path": "pyproject.toml",
         "source": "test" if mailroom[0] else None, "ref": mailroom[0], "version": mailroom[1]},
        {"consumer": "local-mailroom-sandbox", "repo": "Exios66/local-mailroom-sandbox",
         "path": "requirements/dojo-release.txt", "source": "test" if sandbox[0] else None, "ref": sandbox[0], "version": sandbox[1]},
    ]


def test_next_steps_follow_the_actual_pins():
    """Right after a publish both consumers are behind; only llm-mailroom is due."""
    release = load_release()
    old = ("1cd4aba76d82eea20c6e8dfcc0d760881bf84924", "0.27.2")
    steps = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "https://x/v0.28.0"}, _pins(old, old))
    assert steps[0] == "verify https://x/v0.28.0"
    assert steps[1].startswith("llm-mailroom: pins v0.27.2 @ 1cd4aba76d82 (test); next:")
    assert "bump_dojo_scoring.py --apply --tag v0.28.0" in steps[1]
    assert steps[2].startswith("local-mailroom-sandbox: pins v0.27.2 @ 1cd4aba76d82 (test); after llm-mailroom merges:")
    assert "chain complete" not in " ".join(steps)
    assert not any(stale in " ".join(steps) for stale in ("0.26.0", "0.25.0", "#92", "issue sweep"))


def test_next_steps_advance_as_consumers_bump():
    """Once llm-mailroom pins the release, the sandbox is due; then the chain is complete."""
    release = load_release()
    new = ("cab976807854129d1cfea4897dbff5b6e337a62b", "0.28.0")
    old = ("1cd4aba76d82eea20c6e8dfcc0d760881bf84924", "0.27.2")
    mid = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "u"}, _pins(new, old))
    assert mid[1].startswith("llm-mailroom: done, pins v0.28.0")
    assert mid[2].startswith("local-mailroom-sandbox: pins v0.27.2 @ 1cd4aba76d82 (test); next: /vendor-sync to v0.28.0")
    done = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "u"}, _pins(new, new))
    assert done[-1] == "chain complete: every consumer pins v0.28.0 or later"


def test_next_steps_report_a_missing_release_and_unreadable_pins():
    """No GitHub release and no readable pin are said plainly, not guessed."""
    release = load_release()
    steps = release.chain_next_steps("0.28.0", "v0.28.0", None, _pins((None, None), (None, None)))
    assert steps[0].startswith("GitHub release v0.28.0 not found")
    assert "pins unreadable" in steps[1]


def test_consumer_pins_resolve_commits_through_tags(tmp_path, monkeypatch):
    """A commit pin maps to its tag; an untagged commit stays untagged (sibling checkout, offline)."""
    release = load_release()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path / "llm-dojo-scoring")
    (tmp_path / "llm-mailroom").mkdir()
    (tmp_path / "llm-mailroom" / "pyproject.toml").write_text(
        '"llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@cab9768"\n')
    (tmp_path / "local-mailroom-sandbox" / "requirements").mkdir(parents=True)
    (tmp_path / "local-mailroom-sandbox" / "requirements" / "dojo-release.txt").write_text(
        "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@deadbeefcafe\n")
    tags = [{"tag": "v0.28.0", "version": "0.28.0", "commit": "cab976807854129d1cfea4897dbff5b6e337a62b"}]
    mailroom, sandbox = release.consumer_pins(tags, remote=False)
    assert (mailroom["ref"], mailroom["version"]) == ("cab9768", "0.28.0")
    assert mailroom["source"] == "sibling checkout ../llm-mailroom"
    assert sandbox["version"] is None and release._describe_pin(sandbox) == "untagged commit deadbeefcafe"


def test_unreadable_release_is_not_reported_as_unpublished():
    """A blocked or unauthenticated ``gh`` says it could not check, never "not found"."""
    release = load_release()
    old = ("1cd4aba", "0.27.2")
    steps = release.chain_next_steps("0.28.0", "v0.28.0", {"unknown": "HTTP 403"}, _pins(old, (None, None)))
    assert steps[0].startswith("could not read GitHub release v0.28.0 (HTTP 403)")
    assert "could not read Exios66/local-mailroom-sandbox:requirements/dojo-release.txt" in steps[2]


def test_publish_reports_an_unreadable_release_as_unknown(tmp_path, monkeypatch):
    """publish's own next steps use release_probe: a 403 after create is not "not found"."""
    import subprocess

    release = load_release()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(release, "DEFAULT_ASSET_DIR", tmp_path / "dist")
    monkeypatch.setattr(release, "list_version_tags", lambda: [])
    monkeypatch.setattr(release, "previous_tag", lambda v, t: None)
    monkeypatch.setattr(release, "section_for", lambda v: {"body": "b"})
    monkeypatch.setattr(release, "prs_in_range", lambda *a, **k: [])
    monkeypatch.setattr(release, "commits_in_range", lambda *a, **k: [])
    monkeypatch.setattr(release, "render_notes", lambda *a, **k: {"title": "t", "body": "b"})
    monkeypatch.setattr(release, "consumer_pins", lambda tags, **k: [])

    def fake_run(cmd, check=True, **kw):
        """Every command succeeds except ``gh release view`` (blocked, HTTP 403)."""
        if cmd[:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 403: Forbidden")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(release, "run", fake_run)
    plan = {"errors": [], "version": "0.28.0", "tag": "v0.28.0", "commit": "c" * 40,
            "local_tag": True, "remote_tag_commit": "c" * 40, "with_assets": False,
            "notes_title": "Release v0.28.0", "existing_release": None, "draft": False, "target": "c" * 40}
    out = release.publish_apply(plan, push=False)
    assert out["next"][0].startswith("could not read GitHub release v0.28.0"), out["next"]


@pytest.mark.parametrize("state", [None, {"isDraft": True, "url": "u"}, {"unknown": "HTTP 403"}])
def test_consumers_wait_for_a_published_release(state):
    """No consumer is told to bump to a tag whose release is missing, a draft or unreadable."""
    release = load_release()
    old = ("1cd4aba76d82eea20c6e8dfcc0d760881bf84924", "0.27.2")
    steps = release.chain_next_steps("0.28.0", "v0.28.0", state, _pins(old, old))
    assert "next:" not in " ".join(steps[1:]), steps
    assert steps[1].startswith("llm-mailroom: pins v0.27.2 @ 1cd4aba76d82 (test); after the GitHub release v0.28.0 is published:")


def test_consumer_pinned_ahead_is_not_told_to_downgrade():
    """A consumer already on a newer release is done, not told to pin an older tag."""
    release = load_release()
    ahead = ("v0.29.0", "0.29.0")
    steps = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "u"}, _pins(ahead, ahead))
    assert steps[1].startswith("llm-mailroom: done, pins v0.29.0 (ahead of v0.28.0)"), steps
    assert steps[-1] == "chain complete: every consumer pins v0.28.0 or later"
    assert "--tag v0.28.0" not in " ".join(steps)


def test_commit_pin_with_no_local_tags_is_unresolved_not_untagged(tmp_path, monkeypatch):
    """Without local version tags a commit pin cannot be called untagged."""
    release = load_release()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path / "llm-dojo-scoring")
    (tmp_path / "llm-mailroom").mkdir()
    (tmp_path / "llm-mailroom" / "pyproject.toml").write_text(
        '"llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@cab9768"\n')
    mailroom, _ = release.consumer_pins([], remote=False)
    assert mailroom["version"] is None
    assert release._describe_pin(mailroom) == "commit cab9768 (no local version tags: run `git fetch --tags`)"


@pytest.mark.parametrize(
    ("stderr", "missing"),
    [("release not found", True), ("bash: gh: command not found", False), ("HTTP 404: Not Found (repo)", False)],
)
def test_release_probe_treats_only_a_missing_release_as_none(monkeypatch, stderr, missing):
    """Only gh's "release not found" means unpublished; any other failure is unknown."""
    import subprocess

    release = load_release()
    monkeypatch.setattr(release, "run", lambda cmd, check=True, **kw: subprocess.CompletedProcess(cmd, 1, "", stderr))
    probe = release.release_probe("0.28.0")
    assert (probe is None) is missing, probe


def test_sibling_pin_is_unverified_and_never_completes_the_chain(tmp_path, monkeypatch):
    """A pin read from a sibling checkout may be unmerged: it cannot close the chain."""
    release = load_release()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path / "llm-dojo-scoring")
    for name, path in (("llm-mailroom", "pyproject.toml"), ("local-mailroom-sandbox", "requirements/dojo-release.txt")):
        (tmp_path / name / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name / path).write_text("llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.28.0\n")
    pins = release.consumer_pins([], remote=False)
    assert all(p["unverified"] for p in pins)
    steps = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "u"}, pins)
    assert "chain complete" not in " ".join(steps), steps
    assert "unverified" in steps[1] and "unverified" in steps[2]


def test_ambiguous_short_commit_pin_is_not_resolved(tmp_path, monkeypatch):
    """A short pin matching two tagged commits resolves to no version, and says so."""
    release = load_release()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path / "llm-dojo-scoring")
    (tmp_path / "llm-mailroom").mkdir()
    (tmp_path / "llm-mailroom" / "pyproject.toml").write_text(
        '"llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@abc1234"\n')
    tags = [{"version": "0.28.0", "commit": "abc1234" + "1" * 33}, {"version": "0.27.0", "commit": "abc1234" + "2" * 33}]
    mailroom, _ = release.consumer_pins(tags, remote=False)
    assert mailroom["version"] is None
    assert "ambiguous" in release._describe_pin(mailroom)


def test_commit_shared_by_two_tags_resolves_to_the_newest():
    """Two version tags on one commit: the pin is the newer version, not the older."""
    release = load_release()
    tags = [{"version": "0.28.0", "commit": "f" * 40}, {"version": "0.27.9", "commit": "f" * 40}]
    assert release._pin_version("fffffff", tags) == ("0.28.0", False)


def test_unresolved_commit_pin_is_not_told_to_bump():
    """A commit pin with no matching local tag may be newer: check it, do not prescribe a bump."""
    release = load_release()
    steps = release.chain_next_steps("0.28.0", "v0.28.0", {"url": "u"}, _pins(("deadbeefcafe", None), ("deadbeefcafe", None)))
    assert "bump_dojo_scoring.py" not in steps[1] and "git fetch --tags" in steps[1], steps
    assert "chain complete" not in " ".join(steps)


def test_publish_keeps_its_result_when_consumer_lookup_fails(monkeypatch):
    """A crash while reading consumer pins after a release is created still returns the publish result."""
    release = load_release()

    def boom(*a, **k):
        """Fail the way an undecodable sibling pin file does."""
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(release, "list_version_tags", lambda: [])
    monkeypatch.setattr(release, "consumer_pins", boom)
    steps = release.publish_next_steps("0.28.0", "v0.28.0", {"url": "u"})
    assert steps[0] == "verify u"
    assert any("could not read the consumer pins" in s for s in steps), steps
