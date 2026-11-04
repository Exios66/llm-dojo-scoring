#!/usr/bin/env python3
"""Agent-facing Dojo release governor (cut, notes, assets, publish, edit).

Keeps the changelog ↔ semver tag ↔ package version ↔ README pin chain honest,
and publishes GitHub Releases with optional wheel / checksum / manifest assets
(issue #92 Option B).

Designed for agents:
  - every mutating command is dry-run unless ``--apply`` is passed
  - ``--json`` returns a stable plan/result object with a ``next`` step list
  - exit 0 = success / clean dry-run; exit 1 = structural refusal; exit 2 = usage
  - never force-pushes, never deletes tags, never amends commits
  - ``publish`` can target an already-merged release commit via ``--commit``

Commands:
  status [--json]
  check [--json]
  cut VERSION [--apply] [--json] [--allow-dirty] [--allow-empty] [--date YYYY-MM-DD]
  notes VERSION [--out FILE] [--json] [--no-net] [--title TEXT] [--commit REF]
  assets VERSION [--out-dir DIR] [--json] [--apply] [--commit REF]
  publish VERSION [--apply] [--push] [--json] [--commit REF] [--target REF]
           [--draft] [--no-assets] [--title TEXT] [--notes-file FILE]
  edit VERSION [--apply] [--json] [--title TEXT] [--notes-file FILE]
           [--latest | --not-latest]

Stdlib + local git for chain ops. ``gh`` is required only for notes PR lookup
(online), publish, and edit.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "llm_dojo_scoring" / "__init__.py"
README = REPO_ROOT / "README.md"
COMPAT_TEST = REPO_ROOT / "tests" / "test_consumer_compat.py"
UV_LOCK = REPO_ROOT / "uv.lock"
TEMPLATE = REPO_ROOT / ".github" / "RELEASE_TEMPLATE.md"
DEFAULT_ASSET_DIR = REPO_ROOT / "dist" / "release"

REPO = "Exios66/llm-dojo-scoring"
REPO_URL = f"https://github.com/{REPO}"
TAG_PREFIX = "v"
TAG_MESSAGE_PREFIX = "llm-dojo-scoring"
PACKAGE_NAME = "llm-dojo-scoring"

SECTION_RE = re.compile(r"^## \[(?P<name>[^\]]+)\](?P<stamp> - \d{4}-\d{2}-\d{2})?\s*$")
VERSION_RE = re.compile(r"^(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)(?:-[0-9A-Za-z.-]+)?$")
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"(?P<version>[^"]+)"\s*$', re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"(?P<version>[^"]+)"\s*$', re.MULTILINE)
# The root package's own ``[[package]]`` entry in uv.lock. CI installs with
# ``uv sync --frozen``, which never notices a stale root version, so check it here.
UV_LOCK_VERSION_RE = re.compile(
    rf'^\[\[package\]\]\nname = "{re.escape(PACKAGE_NAME)}"\nversion = "(?P<version>[^"]+)"\n',
    re.MULTILINE,
)
COMPAT_VERSION_RE = re.compile(
    r'(assert dojo\.__version__\s*==\s*")(?P<version>\d+\.\d+\.\d+)(")'
)
PR_MERGE_RE = re.compile(r"\bMerge pull request #(?P<num>\d+) from")
DMR_RE = re.compile(r"\b(?:DMR|DOJO)-\d{2,}\b")


class ReleaseError(Exception):
    """Structural refusal (exit 1)."""


# ---------------------------------------------------------------------------
# subprocess helpers
# ---------------------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command in the repository and return the completed process (raise on failure when ``check``)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:  # e.g. no ``gh`` installed: a ReleaseError like any failed command
        raise ReleaseError(f"{' '.join(cmd)} failed: {exc}") from exc
    if check and proc.returncode != 0:
        raise ReleaseError(f"{' '.join(cmd)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def git(*args: str) -> str:
    """Return the stdout of a git command."""
    return run(["git", *args]).stdout


def gh_json(*args: str) -> object:
    """Run a gh command and decode its JSON stdout (``None`` when empty)."""
    proc = run(["gh", *args], check=False)
    if proc.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def emit(payload: dict, *, as_json: bool, human_lines: list[str] | None = None) -> int:
    """Print the payload as JSON or as human lines (plus next steps); return its exit code."""
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in human_lines or []:
            print(line)
        if payload.get("next") and not as_json:
            print("\nnext:")
            for step in payload["next"]:
                print(f"  - {step}")
    return int(payload.get("exit_code", 0))


# ---------------------------------------------------------------------------
# version / changelog parsing
# ---------------------------------------------------------------------------


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)`` for an ``X.Y.Z`` or ``vX.Y.Z`` string, else ``None``."""
    match = VERSION_RE.match(version.removeprefix(TAG_PREFIX))
    if not match:
        return None
    return int(match["maj"]), int(match["min"]), int(match["pat"])


def normalize_version(version: str) -> str:
    """Strip the tag prefix and require ``X.Y.Z``."""
    version = version.removeprefix(TAG_PREFIX)
    if parse_semver(version) is None:
        raise ReleaseError(f"{version!r} is not semver X.Y.Z")
    return version


def tag_for(version: str) -> str:
    """Return the git tag name of a version."""
    return f"{TAG_PREFIX}{normalize_version(version)}"


def pyproject_version() -> str:
    """Return the version declared in ``pyproject.toml``."""
    match = PYPROJECT_VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError("no version = line in pyproject.toml")
    return match["version"]


def init_version() -> str:
    """Return ``llm_dojo_scoring.__version__`` as written in ``__init__.py``."""
    match = INIT_VERSION_RE.search(INIT_PY.read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError("no __version__ in llm_dojo_scoring/__init__.py")
    return match["version"]


def uv_lock_version(text: str | None = None) -> str | None:
    """Return the version uv.lock records for this package, or ``None`` if absent."""
    if text is None:
        if not UV_LOCK.exists():
            return None
        text = UV_LOCK.read_text(encoding="utf-8")
    match = UV_LOCK_VERSION_RE.search(text)
    return match["version"] if match else None


def list_version_tags() -> list[dict]:
    """List local version tags, newest first, with type, object and subject."""
    out = git(
        "tag",
        "--list",
        f"{TAG_PREFIX}*",
        "--format=%(refname:short)%09%(objecttype)%09%(objectname)%09%(contents:subject)",
    )
    tags: list[dict] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        name, objtype, objname, subject = (parts + ["", "", ""])[:4]
        version = name[len(TAG_PREFIX) :] if name.startswith(TAG_PREFIX) else name
        if parse_semver(version) is None:
            continue
        # Annotated tags report the tag object; resolve to the peeled commit.
        commit = git("rev-list", "-n", "1", name).strip()
        tags.append(
            {
                "tag": name,
                "version": version,
                "type": objtype,
                "object": objname,
                "commit": commit,
                "subject": subject,
            }
        )
    tags.sort(key=lambda t: parse_semver(t["version"]) or (0, 0, 0), reverse=True)
    return tags


def parse_changelog() -> list[dict]:
    """Parse the CHANGELOG ``## [X.Y.Z]`` sections into dicts (name, line, date, unreleased flag)."""
    sections: list[dict] = []
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, start=1):
        match = SECTION_RE.match(line)
        if match:
            sections.append(
                {
                    "name": match["name"],
                    "stamp": match["stamp"].lstrip(" -") if match["stamp"] else "",
                    "line_no": line_no,
                    "is_unreleased": match["name"].lower() == "unreleased",
                }
            )
    if not sections:
        raise ReleaseError("no ## [section] headers in CHANGELOG.md")
    if not sections[0]["is_unreleased"]:
        raise ReleaseError("CHANGELOG.md must open with ## [Unreleased]")
    for idx, section in enumerate(sections):
        end = sections[idx + 1]["line_no"] - 1 if idx + 1 < len(sections) else len(lines)
        body = lines[section["line_no"] : end]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        section["body"] = "\n".join(body)
    return sections


def section_for(version: str) -> dict:
    """Return the released CHANGELOG section of a version."""
    version = normalize_version(version)
    for section in parse_changelog():
        if section["name"] == version and not section["is_unreleased"]:
            return section
    raise ReleaseError(f"no ## [{version}] section in CHANGELOG.md — cut first")


def chain_state() -> dict:
    """Snapshot the release chain: versions, tags, CHANGELOG sections and the working tree."""
    tags = list_version_tags()
    sections = parse_changelog()
    version_sections = [s["name"] for s in sections if not s["is_unreleased"]]
    head = git("rev-parse", "HEAD").strip()
    dirty = bool(git("status", "--porcelain").strip())
    return {
        "repo": REPO,
        "head": head,
        "dirty": dirty,
        "pyproject_version": pyproject_version(),
        "init_version": init_version(),
        "uv_lock_version": uv_lock_version(),
        "tags": tags,
        "newest_tag": tags[0]["tag"] if tags else None,
        "newest_tag_version": tags[0]["version"] if tags else None,
        "sections": [s["name"] for s in sections],
        "version_sections": version_sections,
        "unreleased_empty": not sections[0]["body"].strip(),
        "github_release_latest": None,
    }


def check_chain(state: dict) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for inconsistencies in the release chain."""
    errors: list[str] = []
    warnings: list[str] = []

    if state["pyproject_version"] != state["init_version"]:
        errors.append(
            f"pyproject version {state['pyproject_version']} != "
            f"__init__ version {state['init_version']}"
        )

    tagged = {t["version"]: t for t in state["tags"]}
    for version, tag in tagged.items():
        # Historical tags may predate Keep-a-Changelog discipline; publish still
        # requires a section for the version being released (see publish_plan).
        if version not in state["version_sections"]:
            warnings.append(
                f"tag {tag['tag']} has no matching CHANGELOG section [{version}]"
            )
        if tag["type"] != "tag":
            warnings.append(f"tag {tag['tag']} is lightweight — prefer annotated tags")
        elif not tag["subject"].startswith(f"{TAG_MESSAGE_PREFIX} "):
            warnings.append(
                f"tag {tag['tag']} message outside '{TAG_MESSAGE_PREFIX} vX.Y.Z' convention"
            )

    for version in state["version_sections"]:
        if parse_semver(version) is None:
            errors.append(f"CHANGELOG section [{version}] is not semver")
            continue
        if version not in tagged:
            warnings.append(
                f"CHANGELOG section [{version}] is stamped but tag {TAG_PREFIX}{version} "
                "is not local yet"
            )

    seen: set[str] = set()
    parsed: list[tuple[int, int, int]] = []
    for version in state["version_sections"]:
        if version in seen:
            errors.append(f"duplicate CHANGELOG section [{version}]")
        seen.add(version)
        if sv := parse_semver(version):
            parsed.append(sv)
    if parsed != sorted(parsed, reverse=True):
        errors.append("CHANGELOG version sections are not strictly descending")

    if state["newest_tag_version"] is not None:
        pv = parse_semver(state["pyproject_version"])
        nv = parse_semver(state["newest_tag_version"])
        if pv is None:
            errors.append(f"pyproject version {state['pyproject_version']!r} is not semver")
        elif nv is not None and pv < nv:
            errors.append(
                f"pyproject {state['pyproject_version']} is behind newest tag "
                f"{state['newest_tag']}"
            )

    readme = README.read_text(encoding="utf-8")
    pins = set(re.findall(r"(?:release-|releases/tag/|\.git@|\[Release )v(\d+\.\d+\.\d+)", readme))
    if pins and pins != {state["pyproject_version"]}:
        errors.append(
            f"README release pins {sorted(pins)} do not match pyproject "
            f"{state['pyproject_version']}"
        )

    compat = COMPAT_TEST.read_text(encoding="utf-8")
    match = COMPAT_VERSION_RE.search(compat)
    if match and match["version"] != state["pyproject_version"]:
        errors.append(
            f"test_consumer_compat pins {match['version']} != pyproject "
            f"{state['pyproject_version']}"
        )

    lock_version = state.get("uv_lock_version")
    if lock_version is not None and lock_version != state["pyproject_version"]:
        errors.append(
            f"uv.lock records {PACKAGE_NAME} {lock_version} != pyproject "
            f"{state['pyproject_version']} — run `uv lock` and commit uv.lock"
        )

    return errors, warnings


# ---------------------------------------------------------------------------
# cut
# ---------------------------------------------------------------------------


def _stamp_changelog(version: str, today: str) -> None:
    """Turn ``[Unreleased]`` into the dated version section and open a fresh ``[Unreleased]``."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    unreleased_idx = next(
        (
            idx
            for idx, line in enumerate(lines)
            if SECTION_RE.match(line) and line.rstrip().lower() == "## [unreleased]"
        ),
        None,
    )
    if unreleased_idx is None:
        raise ReleaseError("expected ## [Unreleased] in CHANGELOG.md")
    end = len(lines)
    for idx in range(unreleased_idx + 1, len(lines)):
        if SECTION_RE.match(lines[idx]):
            end = idx
            break
    body = lines[unreleased_idx + 1 : end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    stamped = [
        *lines[:unreleased_idx],
        "## [Unreleased]",
        "",
        f"## [{version}] - {today}",
        *body,
        "",
        *lines[end:],
    ]
    CHANGELOG.write_text("\n".join(stamped).rstrip() + "\n", encoding="utf-8")


def _replace_once(
    path: Path,
    pattern: re.Pattern[str],
    repl: str | Callable[[re.Match[str]], str],
    label: str,
) -> None:
    """Replace exactly one regex match in a file, or raise naming ``label``."""
    text = path.read_text(encoding="utf-8")
    new_text, count = pattern.subn(repl, text, count=1)
    if count != 1:
        raise ReleaseError(f"failed to bump {label} in {path.relative_to(REPO_ROOT)}")
    path.write_text(new_text, encoding="utf-8")


def _bump_readme_pins(old: str, new: str) -> int:
    """Move the README release badges and install pins from ``old`` to ``new``; return the count."""
    text = README.read_text(encoding="utf-8")
    replacements = (
        (f"release-v{old}", f"release-v{new}"),
        (f"[Release v{old}]", f"[Release v{new}]"),  # the badge's alt text
        (f"releases/tag/v{old}", f"releases/tag/v{new}"),
        (f".git@v{old}", f".git@v{new}"),
    )
    count = 0
    for src, dst in replacements:
        occurrences = text.count(src)
        if occurrences:
            text = text.replace(src, dst)
            count += occurrences
    if count == 0:
        raise ReleaseError(f"README had no v{old} release pins to bump")
    README.write_text(text, encoding="utf-8")
    return count


def cut_plan(version: str, *, today: str, allow_dirty: bool, allow_empty: bool) -> dict:
    """Plan a release cut (CHANGELOG stamp and version bumps) without writing anything."""
    version = normalize_version(version)
    state = chain_state()
    if state["dirty"] and not allow_dirty:
        raise ReleaseError("working tree is dirty — commit/stash or pass --allow-dirty")
    if version in state["version_sections"]:
        raise ReleaseError(f"CHANGELOG already has [{version}]")
    if any(t["version"] == version for t in state["tags"]):
        raise ReleaseError(f"tag {tag_for(version)} already exists")
    if state["unreleased_empty"] and not allow_empty:
        raise ReleaseError("[Unreleased] is empty — pass --allow-empty to force")

    old = state["pyproject_version"]
    awareness = REPO_ROOT / "tests" / "test_update_awareness.py"
    awareness_hits = 0
    if awareness.exists():
        awareness_hits = len(re.findall(rf"\b{re.escape(old)}\b", awareness.read_text(encoding="utf-8")))

    changes = [
        {"path": "CHANGELOG.md", "op": "stamp", "to": f"## [{version}] - {today}"},
        {"path": "pyproject.toml", "op": "bump", "from": old, "to": version},
        {"path": "llm_dojo_scoring/__init__.py", "op": "bump", "from": old, "to": version},
        {"path": "README.md", "op": "retarget_pins", "from": old, "to": version},
        {
            "path": "tests/test_consumer_compat.py",
            "op": "bump",
            "from": old,
            "to": version,
        },
    ]
    warnings = []
    if awareness_hits:
        warnings.append(
            f"tests/test_update_awareness.py still mentions {old} "
            f"({awareness_hits} hits) — review fixtures after cut"
        )
    return {
        "action": "cut",
        "version": version,
        "date": today,
        "from_version": old,
        "changes": changes,
        "warnings": warnings,
        "next": [
            "re-run with --apply to write",
            "run `uv lock` so uv.lock records the new version (check fails until you do)",
            "commit the stamped files on a release PR",
            "after merge: python scripts/release.py publish VERSION --commit <merge-sha> --apply --push",
        ],
        "exit_code": 0,
    }


def cut_apply(plan: dict) -> None:
    """Apply a cut plan to CHANGELOG, pyproject, ``__init__`` and README pins."""
    version = plan["version"]
    old = plan["from_version"]
    _stamp_changelog(version, plan["date"])
    _replace_once(PYPROJECT, PYPROJECT_VERSION_RE, f'version = "{version}"', "pyproject version")
    _replace_once(INIT_PY, INIT_VERSION_RE, f'__version__ = "{version}"', "__version__")
    _bump_readme_pins(old, version)
    _replace_once(
        COMPAT_TEST,
        COMPAT_VERSION_RE,
        lambda match: f'{match.group(1)}{version}{match.group(3)}',
        "consumer compat version pin",
    )


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------


def previous_tag(version: str, tags: list[dict]) -> str | None:
    """Return the highest version tag below ``version``, if any."""
    target = parse_semver(version)
    for tag in tags:
        sv = parse_semver(tag["version"])
        if sv is None or sv == target:
            continue
        if sv < target:  # type: ignore[operator]
            return tag["tag"]
    return None


def _resolve_commit(ref: str | None) -> str:
    """Resolve a ref (default ``HEAD``) to a full commit SHA."""
    return git("rev-parse", ref or "HEAD").strip()


def commits_in_range(prev_tag: str | None, end_ref: str) -> list[dict]:
    """List the non-merge commits between the previous tag and ``end_ref``."""
    if prev_tag:
        out = git("log", "--oneline", "--no-merges", f"{prev_tag}..{end_ref}")
    else:
        out = git("log", "--oneline", "--no-merges", end_ref)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        commits.append({"sha": sha[:12], "subject": subject.strip()})
    return commits


def prs_in_range(prev_tag: str | None, end_ref: str, *, net: bool) -> list[dict]:
    """List the pull requests merged between the previous tag and ``end_ref`` (GitHub lookup when ``net``)."""
    if prev_tag:
        merge_log = git("log", "--oneline", "--merges", f"{prev_tag}..{end_ref}")
    else:
        merge_log = git("log", "--oneline", "--merges", end_ref)
    merge_shas = [line.split()[0] for line in merge_log.splitlines() if line.strip()]
    if not merge_shas:
        return []

    if not net:
        prs = []
        for line in merge_log.splitlines():
            match = PR_MERGE_RE.search(line)
            if match:
                prs.append(
                    {
                        "number": int(match["num"]),
                        "title": "(offline)",
                        "merged_at": "",
                        "url": f"{REPO_URL}/pull/{match['num']}",
                    }
                )
        return prs

    merged = gh_json(
        "pr",
        "list",
        "--repo",
        REPO,
        "--state",
        "merged",
        "--limit",
        "200",
        "--json",
        "number,title,mergedAt,mergeCommit,url",
    )
    by_sha = {
        (pr.get("mergeCommit") or {}).get("oid", ""): pr
        for pr in (merged or [])
        if isinstance(pr, dict)
    }
    window: list[dict] = []
    seen: set[int] = set()
    for sha in merge_shas:
        full = git("rev-parse", sha).strip()
        pr = by_sha.get(full)
        if not pr or pr["number"] in seen:
            continue
        seen.add(pr["number"])
        window.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "merged_at": (pr.get("mergedAt") or "")[:10],
                "url": pr.get("url") or f"{REPO_URL}/pull/{pr['number']}",
            }
        )
    return window


def bullet_summaries(body: str, limit: int = 8) -> list[str]:
    """Top-level changelog bullets, collapsed to one line each."""
    lines = body.splitlines()
    bullets: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        if raw.startswith("- "):
            buf = raw[2:].strip()
            while i + 1 < len(lines) and lines[i + 1].startswith("  "):
                i += 1
                buf += " " + lines[i].strip()
            buf = re.sub(r"\s+", " ", buf).strip().strip("`")
            if len(buf) > 160:
                buf = buf[:157].rstrip() + "..."
            bullets.append(buf)
        i += 1
    return bullets[:limit] or ["See the changelog section below."]


def key_commits(commits: list[dict], limit: int = 12) -> list[dict]:
    """Pick the commits worth naming in release notes: release and DMR commits first."""
    preferred = [c for c in commits if DMR_RE.search(c["subject"]) or "Release" in c["subject"]]
    others = [c for c in commits if c not in preferred]
    return (preferred + others)[:limit]


def render_notes(
    version: str,
    *,
    title: str | None,
    commit: str,
    previous: str | None,
    body: str,
    prs: list[dict],
    commits: list[dict],
    artifacts_text: str,
) -> dict:
    """Render the release-notes Markdown body."""
    version = normalize_version(version)
    highlights = bullet_summaries(body)
    if title:
        epoch = title.strip()
    else:
        epoch = highlights[0]
        if len(epoch) > 72:
            epoch = epoch[:69].rstrip() + "..."

    prev = previous.removeprefix(TAG_PREFIX) if previous else None
    compare_label = (
        f"{TAG_PREFIX}{prev}...{TAG_PREFIX}{version}" if prev else f"first release {TAG_PREFIX}{version}"
    )
    compare_url = (
        f"{REPO_URL}/compare/{compare_label}"
        if prev
        else f"{REPO_URL}/releases/tag/{TAG_PREFIX}{version}"
    )
    prs_text = (
        "\n".join(
            f"- **{p['title']}** — #{p['number']}"
            + (f" ({p['merged_at']})" if p.get("merged_at") else "")
            for p in prs
        )
        or "None."
    )
    commits_text = (
        "\n".join(f"- `{c['sha']}` {c['subject'][:120]}" for c in key_commits(commits))
        or "None."
    )
    vars_ = {
        "version": version,
        "epoch_title": epoch,
        "summary": (
            f"Dojo **v{version}** — {epoch}. Cut from the stamped changelog "
            f"section below; consumers should pin the annotated tag."
        ),
        "highlights": "\n".join(f"- {h}" for h in highlights),
        "changelog_section": body,
        "prs": prs_text,
        "commits": commits_text,
        "artifacts": artifacts_text or "_Wheel, SHA256SUMS, and release manifest attach on publish._",
        "changelog_url": f"{REPO_URL}/blob/main/CHANGELOG.md",
        "compare_label": compare_label,
        "compare_url": compare_url,
        "commit": commit,
        "previous": prev or "n/a",
        "previous_release_url": (
            f"{REPO_URL}/releases/tag/{TAG_PREFIX}{prev}" if prev else "(none)"
        ),
    }
    if not TEMPLATE.exists():
        raise ReleaseError(f"missing release template at {TEMPLATE.relative_to(REPO_ROOT)}")
    rendered = TEMPLATE.read_text(encoding="utf-8")
    for key, value in vars_.items():
        rendered = rendered.replace("{{" + key + "}}", value or "")
    return {
        "version": version,
        "title": f"Dojo v{version}: {epoch}",
        "previous": prev,
        "commit": commit,
        "body": rendered,
        "vars": vars_,
    }


def build_notes(
    version: str,
    *,
    previous: str | None,
    title: str | None,
    commit_ref: str | None,
    net: bool,
    artifacts_text: str = "",
) -> dict:
    """Collect the CHANGELOG section, commits and PRs for a version and render its notes."""
    version = normalize_version(version)
    tags = list_version_tags()
    prev = previous or previous_tag(version, tags)
    commit = _resolve_commit(commit_ref)
    section = section_for(version)
    end_ref = tag_for(version) if any(t["version"] == version for t in tags) else commit
    commits = commits_in_range(prev, end_ref)
    prs = prs_in_range(prev, end_ref, net=net)
    return render_notes(
        version,
        title=title,
        commit=commit,
        previous=prev,
        body=section["body"],
        prs=prs,
        commits=commits,
        artifacts_text=artifacts_text,
    )


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_assets(version: str, *, out_dir: Path, commit: str) -> dict:
    """Build the sdist/wheel and checksum assets of a version."""
    version = normalize_version(version)
    if pyproject_version() != version or init_version() != version:
        # Allow publishing an older already-cut tag from a newer worktree by
        # building inside a temporary worktree at the release commit.
        return _build_assets_at_commit(version, out_dir=out_dir, commit=commit)

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*"):
        if stale.is_file():
            stale.unlink()

    if shutil.which("uv"):
        run(["uv", "build", "--out-dir", str(out_dir)])
    else:
        run([sys.executable, "-m", "build", "--outdir", str(out_dir)])

    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    if not wheels and not sdists:
        raise ReleaseError(f"uv/build produced no artifacts in {out_dir}")

    sums_lines = []
    files = []
    for artifact in [*wheels, *sdists]:
        digest = sha256_file(artifact)
        sums_lines.append(f"{digest}  {artifact.name}")
        files.append(
            {
                "name": artifact.name,
                "path": str(artifact.relative_to(REPO_ROOT))
                if artifact.is_relative_to(REPO_ROOT)
                else str(artifact),
                "sha256": digest,
                "size": artifact.stat().st_size,
                "kind": "wheel" if artifact.suffix == ".whl" else "sdist",
            }
        )
    sums_path = out_dir / "SHA256SUMS"
    sums_path.write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

    manifest = {
        "package": PACKAGE_NAME,
        "version": version,
        "tag": tag_for(version),
        "commit": commit,
        "created_at": _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }
    manifest_path = out_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    asset_paths = [Path(f["path"] if Path(f["path"]).is_absolute() else REPO_ROOT / f["path"]) for f in files]
    asset_paths.extend([sums_path, manifest_path])
    return {
        "version": version,
        "commit": commit,
        "out_dir": str(out_dir),
        "files": files,
        "sha256sums": str(sums_path.relative_to(REPO_ROOT)),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "upload": [str(p) for p in asset_paths],
        "artifacts_markdown": "\n".join(
            f"- `{f['name']}` ({f['kind']}) — sha256 `{f['sha256']}`" for f in files
        )
        + f"\n- `SHA256SUMS`\n- `release-manifest.json` (commit `{commit[:12]}`)",
    }


def _build_assets_at_commit(version: str, *, out_dir: Path, commit: str) -> dict:
    """Build release artifacts from a detached commit via temporary worktree."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dojo-release-") as tmp:
        work = Path(tmp) / "src"
        run(["git", "worktree", "add", "--detach", str(work), commit])
        try:
            # Ensure the detached tree still declares the release version.
            text = (work / "pyproject.toml").read_text(encoding="utf-8")
            match = PYPROJECT_VERSION_RE.search(text)
            if not match or match["version"] != version:
                raise ReleaseError(
                    f"commit {commit[:12]} pyproject version "
                    f"{match['version'] if match else '?'} != {version}"
                )
            nested_out = work / "dist" / "release"
            nested_out.mkdir(parents=True, exist_ok=True)
            if shutil.which("uv"):
                run(["uv", "build", "--out-dir", str(nested_out)], cwd=work)
            else:
                run([sys.executable, "-m", "build", "--outdir", str(nested_out)], cwd=work)
            for stale in out_dir.glob("*"):
                if stale.is_file():
                    stale.unlink()
            for artifact in nested_out.iterdir():
                if artifact.is_file():
                    shutil.copy2(artifact, out_dir / artifact.name)
        finally:
            run(["git", "worktree", "remove", "--force", str(work)], check=False)

    # Re-hash and write manifest against the copied artifacts.
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    files = []
    sums_lines = []
    for artifact in [*wheels, *sdists]:
        digest = sha256_file(artifact)
        sums_lines.append(f"{digest}  {artifact.name}")
        files.append(
            {
                "name": artifact.name,
                "path": str(artifact.relative_to(REPO_ROOT)),
                "sha256": digest,
                "size": artifact.stat().st_size,
                "kind": "wheel" if artifact.suffix == ".whl" else "sdist",
            }
        )
    sums_path = out_dir / "SHA256SUMS"
    sums_path.write_text("\n".join(sums_lines) + "\n", encoding="utf-8")
    manifest = {
        "package": PACKAGE_NAME,
        "version": version,
        "tag": tag_for(version),
        "commit": commit,
        "created_at": _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }
    manifest_path = out_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "version": version,
        "commit": commit,
        "out_dir": str(out_dir),
        "files": files,
        "sha256sums": str(sums_path.relative_to(REPO_ROOT)),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "upload": [str(REPO_ROOT / f["path"]) for f in files]
        + [str(sums_path), str(manifest_path)],
        "artifacts_markdown": "\n".join(
            f"- `{f['name']}` ({f['kind']}) — sha256 `{f['sha256']}`" for f in files
        )
        + f"\n- `SHA256SUMS`\n- `release-manifest.json` (commit `{commit[:12]}`)",
    }


# ---------------------------------------------------------------------------
# publish / edit
# ---------------------------------------------------------------------------


def remote_release(version: str) -> dict | None:
    """Return the published GitHub release of a version, or ``None``."""
    tag = tag_for(version)
    proc = run(
        ["gh", "release", "view", tag, "--repo", REPO, "--json", "name,tagName,isDraft,url,targetCommitish"],
        check=False,
    )
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)


def remote_tag_commit(version: str) -> str | None:
    """Return the commit a remote version tag points at (peeled), or ``None``."""
    proc = run(["git", "ls-remote", "--tags", "origin", tag_for(version)], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # ls-remote prints "<sha>\\trefs/tags/vX.Y.Z" and optionally "^{}" peeled.
    peeled = None
    direct = None
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.endswith("^{}"):
            peeled = sha
        else:
            direct = sha
    return peeled or direct


def publish_plan(
    version: str,
    *,
    commit_ref: str | None,
    target: str,
    draft: bool,
    with_assets: bool,
    push: bool,
    title: str | None,
    notes_file: Path | None,
) -> dict:
    """Plan a publish (tag, push, release, assets) and collect the refusals that block it."""
    version = normalize_version(version)
    state = chain_state()
    errors, warnings = check_chain(state)
    # Publishing an already-stamped version while the tree also has local
    # unreleased tooling is fine; only hard-fail on identity skew for THIS version.
    section = section_for(version)
    commit = _resolve_commit(commit_ref)
    tag = tag_for(version)
    local_tag = next((t for t in state["tags"] if t["version"] == version), None)
    remote_sha = remote_tag_commit(version)
    existing = remote_release(version)

    hard = [
        e
        for e in errors
        if "README release pins" not in e
        and "test_consumer_compat" not in e
        and "uv.lock records" not in e
    ]
    # When publishing an older stamped version from a newer worktree, pyproject
    # may already be ahead — that is expected. Require only that the target
    # commit declares the release version.
    show = git("show", f"{commit}:pyproject.toml")
    match = PYPROJECT_VERSION_RE.search(show)
    if not match or match["version"] != version:
        hard.append(
            f"commit {commit[:12]} pyproject version "
            f"{match['version'] if match else '?'} != {version}"
        )
    init_show = git("show", f"{commit}:llm_dojo_scoring/__init__.py")
    init_match = INIT_VERSION_RE.search(init_show)
    if not init_match or init_match["version"] != version:
        hard.append(
            f"commit {commit[:12]} __version__ "
            f"{init_match['version'] if init_match else '?'} != {version}"
        )
    # Only an absent uv.lock (older commits predate it) skips the check; any
    # other read failure raises so publishing cannot proceed unchecked.
    lock_listed = git("ls-tree", "--name-only", commit, "--", "uv.lock").strip()
    lock_show = git("show", f"{commit}:uv.lock") if lock_listed else None
    lock_at_commit = uv_lock_version(lock_show) if lock_show is not None else None
    if lock_show is not None and lock_at_commit != version:
        hard.append(
            f"commit {commit[:12]} uv.lock records {PACKAGE_NAME} "
            f"{lock_at_commit or '?'} != {version} — run `uv lock` before publishing"
        )

    if existing and not existing.get("isDraft"):
        hard.append(f"GitHub release {tag} already published at {existing.get('url')}")

    if local_tag and local_tag["commit"] != commit:
        hard.append(
            f"local tag {tag} points at {local_tag['commit'][:12]}, not {commit[:12]}"
        )
    if remote_sha and remote_sha != commit:
        hard.append(
            f"origin {tag} points at {remote_sha[:12]}, not {commit[:12]}"
        )

    notes = None
    if notes_file:
        body = notes_file.read_text(encoding="utf-8")
        notes = {
            "version": version,
            "title": title or f"Dojo v{version}",
            "body": body,
            "commit": commit,
            "previous": previous_tag(version, state["tags"]),
        }
    else:
        notes = build_notes(
            version,
            previous=None,
            title=title,
            commit_ref=commit,
            net=True,
            artifacts_text="",
        )

    steps = []
    if not local_tag:
        steps.append(
            {
                "op": "git_tag",
                "tag": tag,
                "commit": commit,
                "message": f"{TAG_MESSAGE_PREFIX} {tag}",
            }
        )
    if push and (not remote_sha):
        steps.append({"op": "git_push_tag", "tag": tag})
    elif push and remote_sha:
        steps.append({"op": "git_push_tag", "tag": tag, "skipped": "already on origin"})
    if with_assets:
        steps.append({"op": "build_assets", "out_dir": str(DEFAULT_ASSET_DIR.relative_to(REPO_ROOT))})
    steps.append(
        {
            "op": "gh_release_create" if not existing else "gh_release_edit",
            "tag": tag,
            "title": notes["title"],
            "target": target,
            "draft": draft,
            "commit": commit,
        }
    )

    return {
        "action": "publish",
        "version": version,
        "tag": tag,
        "commit": commit,
        "target": target,
        "draft": draft,
        "with_assets": with_assets,
        "push": push,
        "changelog_stamp": section.get("stamp"),
        "notes_title": notes["title"],
        "notes_body": notes["body"],
        "existing_release": existing,
        "local_tag": local_tag,
        "remote_tag_commit": remote_sha,
        "steps": steps,
        "errors": hard,
        "warnings": warnings,
        "next": [
            "re-run with --apply to tag/create",
            "add --push to push the annotated tag to origin",
            "consumers: retarget pins from the merge SHA to the tag",
        ],
        "exit_code": 1 if hard else 0,
    }


def publish_apply(plan: dict, *, push: bool) -> dict:
    """Execute a publish plan: tag, optionally push, create the release and upload assets."""
    if plan["errors"]:
        raise ReleaseError("; ".join(plan["errors"]))

    version = plan["version"]
    tag = plan["tag"]
    commit = plan["commit"]
    results = []

    if not plan["local_tag"]:
        run(
            [
                "git",
                "tag",
                "-a",
                tag,
                commit,
                "-m",
                f"{TAG_MESSAGE_PREFIX} {tag}",
            ]
        )
        results.append({"op": "git_tag", "tag": tag, "commit": commit, "ok": True})

    if push and not plan["remote_tag_commit"]:
        run(["git", "push", "origin", tag])
        results.append({"op": "git_push_tag", "tag": tag, "ok": True})

    assets = None
    upload_args: list[str] = []
    artifacts_md = ""
    if plan["with_assets"]:
        assets = build_assets(version, out_dir=DEFAULT_ASSET_DIR, commit=commit)
        artifacts_md = assets["artifacts_markdown"]
        upload_args = assets["upload"]
        results.append({"op": "build_assets", "files": [f["name"] for f in assets["files"]], "ok": True})

    # Refresh notes so the Artifacts section lists real digests.
    tags = list_version_tags()
    prev = previous_tag(version, tags)
    notes = render_notes(
        version,
        title=plan["notes_title"].split(": ", 1)[-1] if ": " in plan["notes_title"] else None,
        commit=commit,
        previous=prev,
        body=section_for(version)["body"],
        prs=prs_in_range(prev, commit, net=True),
        commits=commits_in_range(prev, commit),
        artifacts_text=artifacts_md,
    )
    title = notes["title"]
    body = notes["body"]

    notes_path = DEFAULT_ASSET_DIR / f"RELEASE_NOTES_v{version}.md"
    DEFAULT_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(body, encoding="utf-8")

    if plan["existing_release"] and plan["existing_release"].get("isDraft"):
        cmd = [
            "gh",
            "release",
            "edit",
            tag,
            "--repo",
            REPO,
            "--title",
            title,
            "--notes-file",
            str(notes_path),
        ]
        if not plan["draft"]:
            cmd.append("--draft=false")
        run(cmd)
        if upload_args:
            run(["gh", "release", "upload", tag, *upload_args, "--repo", REPO, "--clobber"])
        results.append({"op": "gh_release_edit", "tag": tag, "ok": True})
    else:
        cmd = [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            REPO,
            "--title",
            title,
            "--notes-file",
            str(notes_path),
            "--target",
            plan["target"],
        ]
        if plan["draft"]:
            cmd.append("--draft")
        # Attach assets in the same create call when present.
        cmd.extend(upload_args)
        run(cmd)
        results.append({"op": "gh_release_create", "tag": tag, "ok": True})

    release = remote_release(version)
    return {
        "action": "publish",
        "version": version,
        "tag": tag,
        "commit": commit,
        "results": results,
        "assets": assets,
        "release": release,
        "notes_file": str(notes_path.relative_to(REPO_ROOT)),
        "next": [
            f"verify {release.get('url') if release else tag}",
            "comment on #92 that v0.25.0 is published" if version == "0.25.0" else "notify consumers",
            "open/continue the v0.26.0 issue sweep PR",
        ],
        "exit_code": 0,
    }


def edit_release(
    version: str,
    *,
    title: str | None,
    notes_file: Path | None,
    latest: bool | None,
    apply: bool,
) -> dict:
    """Plan or apply an edit to a published release's title, notes or latest flag."""
    version = normalize_version(version)
    existing = remote_release(version)
    if not existing:
        raise ReleaseError(f"no GitHub release for {tag_for(version)}")
    steps = []
    if title:
        steps.append({"op": "set_title", "title": title})
    if notes_file:
        steps.append({"op": "set_notes_file", "path": str(notes_file)})
    if latest is True:
        steps.append({"op": "mark_latest"})
    if latest is False:
        steps.append({"op": "mark_not_latest"})
    if not steps:
        raise ReleaseError("edit requires --title and/or --notes-file and/or --latest/--not-latest")

    plan = {
        "action": "edit",
        "version": version,
        "tag": tag_for(version),
        "url": existing.get("url"),
        "steps": steps,
        "next": ["re-run with --apply to update the GitHub release"],
        "exit_code": 0,
    }
    if not apply:
        return plan

    cmd = ["gh", "release", "edit", tag_for(version), "--repo", REPO]
    if title:
        cmd.extend(["--title", title])
    if notes_file:
        cmd.extend(["--notes-file", str(notes_file)])
    if latest is True:
        cmd.append("--latest")
    if latest is False:
        cmd.append("--latest=false")
    run(cmd)
    plan["applied"] = True
    plan["release"] = remote_release(version)
    plan["next"] = [f"verify {plan['release'].get('url') if plan.get('release') else plan['tag']}"]
    return plan


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """``status``: print the release-chain identity."""
    state = chain_state()
    payload = {"action": "status", **state, "exit_code": 0, "next": []}
    lines = [
        f"repo                  : {state['repo']}",
        f"HEAD                  : {state['head'][:12]}{' (dirty)' if state['dirty'] else ''}",
        f"pyproject version     : {state['pyproject_version']}",
        f"__init__ version      : {state['init_version']}",
        f"newest version tag    : {state['newest_tag'] or '(none)'}",
        f"version tags          : {len(state['tags'])}",
    ]
    for tag in state["tags"][:8]:
        lines.append(
            f"    {tag['tag']:<12} {tag['type']:<8} {tag['commit'][:12]}  {tag['subject']}"
        )
    lines.append(f"changelog sections    : {', '.join(state['sections'][:8])}...")
    lines.append(
        "unreleased            : "
        + ("empty" if state["unreleased_empty"] else "content pending release")
    )
    return emit(payload, as_json=args.json, human_lines=lines)


def cmd_check(args: argparse.Namespace) -> int:
    """``check``: validate the release chain; non-zero on errors."""
    state = chain_state()
    errors, warnings = check_chain(state)
    payload = {
        "action": "check",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "state": {
            "pyproject_version": state["pyproject_version"],
            "init_version": state["init_version"],
            "newest_tag": state["newest_tag"],
            "head": state["head"],
            "dirty": state["dirty"],
        },
        "next": [] if not errors else ["fix structural errors before cut/publish"],
        "exit_code": 1 if errors else 0,
    }
    lines = [f"WARN  {w}" for w in warnings] + [f"ERROR {e}" for e in errors]
    lines.append(
        f"\nrelease chain: {'OK' if not errors else 'FAIL'} "
        f"({len(errors)} error(s), {len(warnings)} warning(s))"
    )
    return emit(payload, as_json=args.json, human_lines=lines)


def cmd_cut(args: argparse.Namespace) -> int:
    """``cut``: stamp CHANGELOG and bump versions (dry run unless ``--apply``)."""
    today = args.date or _dt.date.today().isoformat()
    plan = cut_plan(
        args.version,
        today=today,
        allow_dirty=args.allow_dirty,
        allow_empty=args.allow_empty,
    )
    if not args.apply:
        plan["dry_run"] = True
        lines = [f"cut plan — v{plan['version']} ({plan['date']}):"]
        for change in plan["changes"]:
            lines.append(f"  - {change['path']}: {change['op']} {change.get('from', '')} -> {change.get('to', change.get('to', ''))}".rstrip())
        for warning in plan["warnings"]:
            lines.append(f"WARN  {warning}")
        lines.append("\ndry run — pass --apply to write")
        return emit(plan, as_json=args.json, human_lines=lines)

    cut_apply(plan)
    plan["dry_run"] = False
    plan["applied"] = True
    plan["next"] = [
        "git diff --stat",
        "commit on a release branch / PR",
        f"after merge: python scripts/release.py publish {plan['version']} --commit <merge-sha> --apply --push",
    ]
    return emit(
        plan,
        as_json=args.json,
        human_lines=[f"applied cut for v{plan['version']}", *plan["next"]],
    )


def cmd_notes(args: argparse.Namespace) -> int:
    """``notes``: render release notes for a version."""
    notes = build_notes(
        args.version,
        previous=args.previous,
        title=args.title,
        commit_ref=args.commit,
        net=not args.no_net,
    )
    if args.out:
        Path(args.out).write_text(notes["body"], encoding="utf-8")
    payload = {
        "action": "notes",
        "version": notes["version"],
        "title": notes["title"],
        "previous": notes["previous"],
        "commit": notes["commit"],
        "body": notes["body"],
        "out": args.out,
        "next": [
            f"pass --notes-file {args.out or 'NOTES.md'} to publish/edit"
            if args.out
            else "pipe body to --notes-file for publish/edit"
        ],
        "exit_code": 0,
    }
    if args.json:
        return emit(payload, as_json=True)
    if args.out:
        print(f"wrote {args.out} ({len(notes['body'])} chars)")
        print(f"title: {notes['title']}")
        return 0
    print(notes["body"])
    return 0


def cmd_assets(args: argparse.Namespace) -> int:
    """``assets``: build release assets for a version."""
    version = normalize_version(args.version)
    commit = _resolve_commit(args.commit)
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_ASSET_DIR
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    plan = {
        "action": "assets",
        "version": version,
        "commit": commit,
        "out_dir": str(out_dir.relative_to(REPO_ROOT) if out_dir.is_relative_to(REPO_ROOT) else out_dir),
        "next": ["re-run with --apply to build wheel/sdist + SHA256SUMS + manifest"],
        "exit_code": 0,
    }
    if not args.apply:
        plan["dry_run"] = True
        return emit(
            plan,
            as_json=args.json,
            human_lines=[
                f"assets plan — v{version} @ {commit[:12]}",
                f"  out: {plan['out_dir']}",
                "dry run — pass --apply to build",
            ],
        )
    assets = build_assets(version, out_dir=out_dir, commit=commit)
    payload = {**plan, **assets, "dry_run": False, "applied": True, "next": ["attach via publish or gh release upload"]}
    return emit(
        payload,
        as_json=args.json,
        human_lines=[
            f"built assets for v{version} in {assets['out_dir']}",
            *[f"  - {f['name']} sha256 {f['sha256'][:12]}..." for f in assets["files"]],
            f"  - {assets['sha256sums']}",
            f"  - {assets['manifest']}",
        ],
    )


def cmd_publish(args: argparse.Namespace) -> int:
    """``publish``: tag and create the GitHub release (dry run unless ``--apply``)."""
    plan = publish_plan(
        args.version,
        commit_ref=args.commit,
        target=args.target,
        draft=args.draft,
        with_assets=not args.no_assets,
        push=args.push,
        title=args.title,
        notes_file=Path(args.notes_file) if args.notes_file else None,
    )
    if plan["errors"]:
        plan["dry_run"] = not args.apply
        lines = [f"ERROR {e}" for e in plan["errors"]] + [f"WARN  {w}" for w in plan["warnings"]]
        return emit(plan, as_json=args.json, human_lines=lines)

    if not args.apply:
        plan["dry_run"] = True
        lines = [
            f"publish plan — {plan['tag']} @ {plan['commit'][:12]}",
            f"  title : {plan['notes_title']}",
            f"  target: {plan['target']}",
            f"  draft : {plan['draft']}",
            f"  assets: {plan['with_assets']}",
            f"  push  : {plan['push']}",
            "  steps:",
        ]
        for step in plan["steps"]:
            lines.append(f"    - {step}")
        lines.append("\ndry run — pass --apply (and --push to publish the tag)")
        return emit(plan, as_json=args.json, human_lines=lines)

    result = publish_apply(plan, push=args.push)
    lines = [
        f"published {result['tag']} @ {result['commit'][:12]}",
        f"release: {(result.get('release') or {}).get('url', '(pending)')}",
    ]
    return emit(result, as_json=args.json, human_lines=lines)


def cmd_edit(args: argparse.Namespace) -> int:
    """``edit``: change a published release."""
    latest = True if args.latest else False if args.not_latest else None
    plan = edit_release(
        args.version,
        title=args.title,
        notes_file=Path(args.notes_file) if args.notes_file else None,
        latest=latest,
        apply=args.apply,
    )
    if not args.apply:
        plan["dry_run"] = True
        lines = [f"edit plan — {plan['tag']}", *[f"  - {s}" for s in plan["steps"]], "dry run — pass --apply"]
        return emit(plan, as_json=args.json, human_lines=lines)
    return emit(
        plan,
        as_json=args.json,
        human_lines=[f"edited {plan['tag']}", f"url: {(plan.get('release') or {}).get('url')}"],
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="scripts/release.py",
        description="Cut, note, asset-build, publish, and edit Dojo GitHub releases.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="chain snapshot")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_check = sub.add_parser("check", help="verify changelog/tag/version identity")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_cut = sub.add_parser("cut", help="stamp [Unreleased] and bump package identity pins")
    p_cut.add_argument("version")
    p_cut.add_argument("--apply", action="store_true")
    p_cut.add_argument("--json", action="store_true")
    p_cut.add_argument("--allow-dirty", action="store_true")
    p_cut.add_argument("--allow-empty", action="store_true")
    p_cut.add_argument("--date", help="stamp date YYYY-MM-DD (default: today)")
    p_cut.set_defaults(func=cmd_cut)

    p_notes = sub.add_parser("notes", help="render GitHub release notes from CHANGELOG")
    p_notes.add_argument("version")
    p_notes.add_argument("--previous")
    p_notes.add_argument("--title")
    p_notes.add_argument("--commit", help="release commit (default HEAD)")
    p_notes.add_argument("--out")
    p_notes.add_argument("--no-net", action="store_true")
    p_notes.add_argument("--json", action="store_true")
    p_notes.set_defaults(func=cmd_notes)

    p_assets = sub.add_parser("assets", help="build wheel/sdist + SHA256SUMS + manifest")
    p_assets.add_argument("version")
    p_assets.add_argument("--out-dir", default=str(DEFAULT_ASSET_DIR.relative_to(REPO_ROOT)))
    p_assets.add_argument("--commit")
    p_assets.add_argument("--apply", action="store_true")
    p_assets.add_argument("--json", action="store_true")
    p_assets.set_defaults(func=cmd_assets)

    p_publish = sub.add_parser("publish", help="tag + GitHub release (+ assets)")
    p_publish.add_argument("version")
    p_publish.add_argument("--commit", help="immutable release commit (default HEAD)")
    p_publish.add_argument("--target", default="main", help="gh release --target (default main)")
    p_publish.add_argument("--title", help="override release title")
    p_publish.add_argument("--notes-file", help="use a pre-rendered notes file")
    p_publish.add_argument("--draft", action="store_true")
    p_publish.add_argument("--no-assets", action="store_true")
    p_publish.add_argument("--push", action="store_true", help="git push origin vX.Y.Z")
    p_publish.add_argument("--apply", action="store_true")
    p_publish.add_argument("--json", action="store_true")
    p_publish.set_defaults(func=cmd_publish)

    p_edit = sub.add_parser("edit", help="edit an existing GitHub release")
    p_edit.add_argument("version")
    p_edit.add_argument("--title")
    p_edit.add_argument("--notes-file")
    latest = p_edit.add_mutually_exclusive_group()
    latest.add_argument("--latest", action="store_true")
    latest.add_argument("--not-latest", action="store_true")
    p_edit.add_argument("--apply", action="store_true")
    p_edit.add_argument("--json", action="store_true")
    p_edit.set_defaults(func=cmd_edit)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line; a ``ReleaseError`` becomes an ``error`` payload and exit code 1."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ReleaseError as exc:
        payload = {"error": str(exc), "exit_code": 1}
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Avoid leaking GH tokens through accidental debug dumps.
    os.environ.setdefault("GH_PROMPT_DISABLED", "1")
    raise SystemExit(main())
