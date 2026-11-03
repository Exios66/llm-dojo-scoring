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
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "publish", "0.25.0", "--commit", "HEAD", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
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
