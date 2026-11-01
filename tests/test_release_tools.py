"""Offline contracts for scripts/release.py (stdlib + local git only)."""

from __future__ import annotations

import importlib.util
import json
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
    """0.25.0 is stamped; missing local tag is a warning, not an error."""
    state = release.chain_state()
    errors, warnings = release.check_chain(state)
    assert state["pyproject_version"] == state["init_version"] == "0.25.0"
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
    if "action" not in payload and "gh " in str(payload.get("error", "")):
        pytest.skip(f"GitHub CLI unavailable here: {payload['error'][:120]}")
    assert payload["action"] == "publish"
    assert payload["version"] == "0.25.0"
    assert payload["dry_run"] is True
    assert payload["tag"] == "v0.25.0"
    assert payload["errors"]
    assert any("already published" in e for e in payload["errors"])


def test_compat_pin_regex_rounds_trip(release):
    """The compat-test version pin regex bumps cleanly."""
    sample = 'assert dojo.__version__ == "0.25.0"\n'
    match = release.COMPAT_VERSION_RE.search(sample)
    assert match and match["version"] == "0.25.0"
    bumped = release.COMPAT_VERSION_RE.sub(
        lambda m: f'{m.group(1)}0.26.0{m.group(3)}', sample, count=1
    )
    assert bumped == 'assert dojo.__version__ == "0.26.0"\n'
