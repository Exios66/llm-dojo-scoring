#!/usr/bin/env python3
"""Pin the downstream ``llm_dojo_scoring`` import and dispatch surface.

The manifest in ``tests/fixtures/consumer_surface.json`` is built from a static
AST scan of the consumer repositories.  Consumer code is never imported and no
consumer dependency needs to be installed.  Missing checkouts are recorded as
``scanned: false``; a file that cannot be parsed is a hard error.

Usage::

    uv run --python 3.12 python scripts/audit_consumer_surface.py --check
    uv run --python 3.12 python scripts/audit_consumer_surface.py --write

``--check`` (the default) regenerates the manifest in memory and exits 1 when
the pinned surface drifts from the fixture.  ``--write`` refreshes the fixture.
Both exit 2, without touching the fixture, when a checkout the fixture pins as
scanned is unavailable on this machine.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

PACKAGE = "llm_dojo_scoring"
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "consumer_surface.json"
SCHEMA_VERSION = 1
GENERATED_BY = "scripts/audit_consumer_surface.py"

#: Directories that never contain consumer source we pin.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "vendor",
        "venv",
    }
)

DISPATCH_FUNCS = ("get_suite", "score_task", "suite_for_doc_type")

#: The first (dispatch) parameter of each function, for keyword calls.
_DISPATCH_PARAM = {"get_suite": "name", "score_task": "task", "suite_for_doc_type": "doc_type"}

#: The variables The-Mailroom's runtime reads Langfuse scores into.  Values are
#: (repo-relative file, assignment name, literal container kind).
TMR_SCORE_VARIABLES = (
    ("mailroom_ui/metrics.py", "grounded_keys", "mapping"),
    ("mailroom_ui/pipeline_schema.py", "SUITE_EXTRA_SCORES", "sequence"),
    ("mailroom_ui/trace_interpreter.py", "JUDGE_VERDICT_SCORES", "sequence"),
    ("mailroom_ui/trace_interpreter.py", "JUDGE_QUALITY_SCORES", "sequence"),
)

#: Runtime source trees whose score-map lookups count as visualizer reads.
TMR_RUNTIME_PREFIXES = ("hosted/", "mailroom_ui/", "operator_desk/", "server/", "tui/")


@dataclass(frozen=True)
class RepoSpec:
    """A consumer checkout and how to read a stable snapshot of its source."""

    label: str
    default_path: str
    env_var: str
    ref: str | None = None
    git_tree: bool = False


REPOS = (
    RepoSpec(
        "SBX",
        "/Users/morningstar/.t3/worktrees/local-mailroom-sandbox/t3-65a57387",
        "SANDBOX_ROOT",
        ref="origin/main",
        git_tree=True,
    ),
    RepoSpec("MAIL", "/tmp/llm-mailroom-check", "MAILROOM_ROOT"),
    RepoSpec(
        "EDA",
        "/Users/morningstar/.t3/worktrees/constellation-readmes/Mailroom-Corpus-EDA",
        "CORPUS_EDA_ROOT",
    ),
    RepoSpec(
        "EE",
        "/Users/morningstar/Digital-Mailroom/packages/eval-environment",
        "EVAL_ENVIRONMENT_ROOT",
    ),
    RepoSpec(
        "ML",
        "/Users/morningstar/.t3/worktrees/constellation-readmes/mailroom-ml",
        "MAILROOM_ML_ROOT",
    ),
    RepoSpec(
        "TMR",
        "/Users/morningstar/Digital-Mailroom/packages/The-Mailroom",
        "THE_MAILROOM_ROOT",
    ),
)

Site = tuple[str, str, int]
_MISSING = object()


# ---------------------------------------------------------------------------
# Source access
# ---------------------------------------------------------------------------


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in ``root`` and return the completed process."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git failed"
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return proc


def _is_git_checkout(root: Path) -> bool:
    """Return whether ``root`` is inside a git work tree."""
    return _run_git(root, "rev-parse", "--git-dir", check=False).returncode == 0


def _git_rev(root: Path, ref: str) -> str | None:
    """Resolve ``ref`` to a commit id, or ``None`` when it is not a git repo."""
    if not _is_git_checkout(root):
        return None
    proc = _run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _head_metadata(root: Path) -> tuple[str | None, str | None]:
    """Return (branch/ref, commit) for the checkout's HEAD."""
    if not _is_git_checkout(root):
        return None, None
    ref = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    return (ref or None), _git_rev(root, "HEAD")


def _skip(rel: Path) -> bool:
    """True when any parent directory of ``rel`` is a vendored/generated tree."""
    return any(part in SKIP_DIRS for part in rel.parts[:-1])


def _read_filesystem_tree(root: Path) -> dict[str, str]:
    """Read every consumer ``.py`` file below ``root``.

    Skipped trees (``.venv``, ``node_modules`` ...) are pruned before descent,
    and only regular files are read, so a directory named ``*.py`` is ignored.
    """
    files: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if not path.is_file():
                continue
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return dict(sorted(files.items()))


def _read_git_tree(root: Path, ref: str) -> dict[str, str]:
    """Read every ``.py`` blob at ``ref`` without consulting the working tree."""
    if not _is_git_checkout(root):
        raise RuntimeError("not a git checkout")
    verify = _run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if verify.returncode != 0:
        raise RuntimeError(f"git ref {ref!r} not found")

    # ``-z``: NUL-separated, unquoted paths (core.quotePath would otherwise
    # quote non-ASCII names and silently drop them from the surface).
    listing = _run_git(root, "ls-tree", "-r", "-z", "--name-only", ref)
    files: dict[str, str] = {}
    for raw in listing.stdout.split("\0"):
        if not raw:
            continue
        rel = Path(raw)
        if rel.suffix != ".py" or _skip(rel):
            continue
        blob = _run_git(root, "show", f"{ref}:{rel.as_posix()}")
        files[rel.as_posix()] = blob.stdout
    return files


def scan_repo(spec: RepoSpec) -> tuple[dict[str, str], dict[str, Any]]:
    """Read one consumer checkout and return its source plus provenance."""
    override = os.environ.get(spec.env_var)
    root = Path(override).expanduser() if override else Path(spec.default_path)
    meta: dict[str, Any] = {
        "label": spec.label,
        "path": str(root),
        "ref": None,
        "commit": None,
        "scanned": False,
        "reason": None,
        "files_scanned": 0,
    }
    if not root.is_dir():
        meta["reason"] = "path does not exist"
        return {}, meta

    if spec.git_tree:
        ref = spec.ref or "HEAD"
        if not _is_git_checkout(root):
            meta["reason"] = "not a git checkout"
            return {}, meta
        if _git_rev(root, ref) is None:
            meta["reason"] = f"git ref {ref!r} not found"
            return {}, meta
        files = _read_git_tree(root, ref)
        meta["ref"] = ref
        meta["commit"] = _git_rev(root, ref)
        meta["scanned"] = True
        meta["files_scanned"] = len(files)
        return files, meta

    if _is_git_checkout(root) and _git_rev(root, spec.ref or "HEAD") is not None:
        # A git checkout is read from committed blobs, so uncommitted edits and
        # untracked scratch files never leak into the pinned surface.
        ref = spec.ref or "HEAD"
        files = _read_git_tree(root, ref)
        branch, _ = _head_metadata(root)
        meta["ref"] = spec.ref or branch
        meta["commit"] = _git_rev(root, ref)
    else:
        files = _read_filesystem_tree(root)
        meta["ref"], meta["commit"] = _head_metadata(root)
    meta["scanned"] = True
    meta["files_scanned"] = len(files)
    return files, meta


# ---------------------------------------------------------------------------
# Package index / collector
# ---------------------------------------------------------------------------


def _module_relpath(path: Path, package_root: Path) -> str:
    """Map a package source file onto its dotted path (``__init__`` at root)."""
    rel = path.relative_to(package_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


class PackageIndex:
    """Static facts about this package used while interpreting consumer ASTs."""

    def __init__(self) -> None:
        """Load the package, its legacy aliases, and every module path once."""
        import llm_dojo_scoring as dojo
        from llm_dojo_scoring._layout import LEGACY_MODULES

        self.package = dojo
        self.legacy: dict[str, str] = dict(LEGACY_MODULES)
        package_root = Path(dojo.__file__).resolve().parent
        self.module_paths: set[str] = set()
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            self.module_paths.add(_module_relpath(path, package_root))
        self.module_names: set[str] = self.module_paths | set(self.legacy)
        self.module_targets = sorted(self.module_names, key=lambda name: (-len(name), name))
        self.definitions = self._read_definitions(package_root)
        self._module_cache: dict[str, ModuleType] = {}

    def _read_definitions(self, package_root: Path) -> dict[str, tuple[str, ...]]:
        """Map top-level assigned/declared names to candidate defining modules."""
        found: dict[str, set[str]] = defaultdict(set)
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            module = _module_relpath(path, package_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found[node.name].add(module)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            found[target.id].add(module)
        return {name: tuple(sorted(paths)) for name, paths in found.items()}

    def resolve(self, module_path: str) -> tuple[str, bool]:
        """Return (canonical module path, uses_legacy_flat_path)."""
        if module_path in self.legacy:
            return self.legacy[module_path], True
        return module_path, False

    def get_module(self, module_path: str) -> ModuleType:
        """Import a canonical package module (root package for ``__init__``)."""
        if module_path not in self._module_cache:
            dotted = PACKAGE if module_path == "__init__" else f"{PACKAGE}.{module_path}"
            self._module_cache[module_path] = importlib.import_module(dotted)
        return self._module_cache[module_path]


@dataclass
class Surface:
    """Accumulated consumer sites, converted to the fixture schema at the end."""

    index: PackageIndex
    top_level: dict[str, set[Site]] = field(default_factory=lambda: defaultdict(set))
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    dispatch_literals: dict[str, dict[str, set[Site]]] = field(
        default_factory=lambda: {name: defaultdict(set) for name in DISPATCH_FUNCS}
    )
    dispatch_dynamic: dict[str, set[tuple[str, str, int, str]]] = field(
        default_factory=lambda: {name: set() for name in DISPATCH_FUNCS}
    )
    patches: set[tuple[str, str, int, str]] = field(default_factory=set)

    def module_entry(self, module_path: str) -> tuple[str, dict[str, Any]]:
        """Register a module and return (canonical path, mutable entry)."""
        canonical, legacy = self.index.resolve(module_path)
        entry = self.modules.setdefault(
            canonical, {"legacy": False, "attrs": defaultdict(set)}
        )
        entry["legacy"] = bool(entry["legacy"] or legacy)
        return canonical, entry

    def record_top_level(self, name: str, site: Site) -> None:
        """Pin ``from llm_dojo_scoring import name``."""
        self.top_level[name].add(site)
        if name in self.index.module_names:
            self.module_entry(name)

    def record_attr(
        self, canonical: str, entry: dict[str, Any], attr: str, site: Site
    ) -> None:
        """Pin an attribute imported from a canonical module."""
        submodule = f"{canonical}.{attr}"
        if attr != "__init__" and submodule in self.index.module_paths:
            self.module_entry(submodule)
            return
        entry["attrs"][attr].add(site)

    def _record_patch_target(self, target: str, site: Site) -> None:
        """Map a ``mock.patch("llm_dojo_scoring...")`` string onto its module."""
        rest = target[len(PACKAGE) :].lstrip(".")
        if not rest:
            return
        for candidate in self.index.module_targets:
            if rest == candidate:
                self.module_entry(candidate)
                return
            if rest.startswith(candidate + "."):
                canonical, entry = self.module_entry(candidate)
                self.record_attr(canonical, entry, rest[len(candidate) + 1 :].split(".")[0], site)
                return
        self.record_top_level(rest.split(".")[0], site)

    def collect_file(self, repo: str, rel: str, tree: ast.AST) -> None:
        """Collect imports, dispatch literals and mock.patch targets from one file."""
        function_aliases: dict[str, str] = {}
        module_aliases: set[str] = {PACKAGE}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == PACKAGE:
                        module_aliases.add(alias.asname or PACKAGE)
                    elif alias.name.startswith(PACKAGE + "."):
                        module_aliases.add(alias.asname or PACKAGE)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == PACKAGE:
                    for alias in node.names:
                        if alias.name == "*":
                            _bind_star_dispatch(function_aliases, PACKAGE)
                        elif alias.name in DISPATCH_FUNCS:
                            function_aliases[alias.asname or alias.name] = alias.name
                        if alias.name in self.index.module_names:
                            module_aliases.add(alias.asname or alias.name)
                elif module.startswith(PACKAGE + "."):
                    canonical, _ = self.index.resolve(module[len(PACKAGE) + 1 :])
                    for alias in node.names:
                        if alias.name == "*":
                            _bind_star_dispatch(function_aliases, f"{PACKAGE}.{canonical}")
                        elif alias.name in DISPATCH_FUNCS:
                            function_aliases[alias.asname or alias.name] = alias.name
                        elif f"{canonical}.{alias.name}" in self.index.module_paths:
                            # ``from llm_dojo_scoring.scoring import suites``
                            module_aliases.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            site: Site = (repo, rel, getattr(node, "lineno", 0))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(PACKAGE + "."):
                        self.module_entry(alias.name[len(PACKAGE) + 1 :])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == PACKAGE:
                    for alias in node.names:
                        if alias.name == "*":
                            # A star import binds every exported name: pin them all.
                            for star in _star_names(PACKAGE):
                                self.record_top_level(star, site)
                        else:
                            self.record_top_level(alias.name, site)
                elif module.startswith(PACKAGE + "."):
                    canonical, entry = self.module_entry(module[len(PACKAGE) + 1 :])
                    for alias in node.names:
                        if alias.name == "*":
                            for star in _star_names(f"{PACKAGE}.{canonical}"):
                                self.record_attr(canonical, entry, star, site)
                        else:
                            self.record_attr(canonical, entry, alias.name, site)
            elif isinstance(node, ast.Call):
                self._collect_call(node, site, function_aliases, module_aliases)

    def _collect_call(
        self,
        node: ast.Call,
        site: Site,
        function_aliases: dict[str, str],
        module_aliases: set[str],
    ) -> None:
        """Record dispatch literals/dynamic arguments and mock.patch targets."""
        if _is_patch_call(node):
            target: str | None = None
            if node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    target = value
            for keyword in node.keywords:
                if keyword.arg == "target" and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, str):
                        target = value
            if target and (target == PACKAGE or target.startswith(PACKAGE + ".")):
                self.patches.add((*site, target))
                self._record_patch_target(target, site)

        name, is_dojo_call = _dispatch_call_name(node.func, function_aliases, module_aliases)
        if not is_dojo_call or name is None:
            return
        if node.args:
            arg = node.args[0]
        else:
            # ``get_suite(name="sorter")``: the dispatch parameter by keyword.
            keywords = [
                keyword for keyword in node.keywords
                if keyword.arg == _DISPATCH_PARAM.get(name)
            ]
            if not keywords:
                self.dispatch_dynamic[name].add((*site, "<no-argument>"))
                return
            arg = keywords[0].value
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            self.dispatch_literals[name][arg.value].add(site)
        else:
            self.dispatch_dynamic[name].add((*site, ast.unparse(arg)))


def _bind_star_dispatch(function_aliases: dict[str, str], module_name: str) -> None:
    """A star import binds the dispatch functions the module exports."""
    for star in _star_names(module_name):
        if star in DISPATCH_FUNCS:
            function_aliases[star] = star


def _star_names(module_name: str) -> list[str]:
    """Names ``from module_name import *`` binds: ``__all__``, else public names."""
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return []
    names = getattr(module, "__all__", None)
    if names is None:
        names = [name for name in vars(module) if not name.startswith("_")]
    return sorted(str(name) for name in names)


def _root_name(node: ast.AST) -> str | None:
    """Return the left-most name of an attribute chain."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_patch_call(node: ast.Call) -> bool:
    """True for ``patch(...)`` / ``mock.patch(...)`` / ``mocker.patch(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "patch"
    return isinstance(func, ast.Attribute) and func.attr == "patch"


def _dispatch_call_name(
    func: ast.AST,
    function_aliases: dict[str, str],
    module_aliases: set[str],
) -> tuple[str | None, bool]:
    """Resolve a call target to a dojo dispatch function, if it is one."""
    if isinstance(func, ast.Name):
        resolved = function_aliases.get(func.id)
        return resolved, resolved is not None
    if isinstance(func, ast.Attribute):
        root = _root_name(func)
        if root in module_aliases and func.attr in DISPATCH_FUNCS:
            return func.attr, True
    return None, False


# ---------------------------------------------------------------------------
# Fixture sections
# ---------------------------------------------------------------------------


def _sites(values: set[Site] | list[Site]) -> list[dict[str, Any]]:
    """Sort sites and render the fixture's repo-relative shape."""
    return [
        {"repo": repo, "file": file, "line": line}
        for repo, file, line in sorted(values, key=lambda item: (item[0], item[1], item[2]))
    ]


def _relative_module_name(module: ModuleType) -> str:
    """Turn a module object into a package-relative dotted path."""
    name = module.__name__
    if name == PACKAGE:
        return "__init__"
    if name.startswith(PACKAGE + "."):
        return name[len(PACKAGE) + 1 :]
    return name


def _identity_defined_in(
    name: str,
    obj: Any,
    index: PackageIndex,
    fallback: str | None,
) -> str | None:
    """Find the module whose attribute is the same object as ``obj``."""
    candidates = index.definitions.get(name, ())
    # Defining modules first: the import path (``fallback``) always re-exports
    # ``obj``, so checking it first would hide where the name is defined.
    ordered = sorted(candidates)
    if fallback and fallback not in ordered:
        ordered.append(fallback)
    if obj is not _MISSING:
        for candidate in ordered:
            try:
                module = index.get_module(candidate)
            except Exception:
                continue
            if getattr(module, name, _MISSING) is obj:
                return candidate
    if fallback:
        return fallback
    if candidates:
        return sorted(candidates)[0]
    if isinstance(obj, ModuleType):
        return _relative_module_name(obj)
    module_name = getattr(obj, "__module__", None)
    if isinstance(module_name, str) and module_name.startswith(PACKAGE + "."):
        return module_name[len(PACKAGE) + 1 :]
    return None


def _classify_top_level(name: str, index: PackageIndex) -> tuple[str, str | None]:
    """Return (kind, defined_in) for a name imported from the package root."""
    if name in index.module_names:
        canonical, _ = index.resolve(name)
        return "module", canonical
    obj = getattr(index.package, name, _MISSING)
    if obj is _MISSING:
        return "missing", None
    if isinstance(obj, ModuleType):
        return "module", _relative_module_name(obj)
    if inspect.isclass(obj):
        kind = "class"
    elif inspect.isfunction(obj) or inspect.isbuiltin(obj) or inspect.ismethod(obj):
        kind = "function"
    elif isinstance(obj, (str, int, float, bool, type(None), dict, list, tuple, set, frozenset)):
        kind = "constant"
    else:
        kind = "attribute"
    return kind, _identity_defined_in(name, obj, index, None)


def build_top_level(surface: Surface) -> dict[str, dict[str, Any]]:
    """Render the pinned top-level import section."""
    out: dict[str, dict[str, Any]] = {}
    all_names = set(getattr(surface.index.package, "__all__", ()))
    for name in sorted(surface.top_level):
        kind, defined_in = _classify_top_level(name, surface.index)
        out[name] = {
            "kind": kind,
            "in_all": name in all_names,
            "defined_in": defined_in,
            "consumers": _sites(surface.top_level[name]),
        }
    return out


def build_modules(surface: Surface) -> dict[str, dict[str, Any]]:
    """Render the pinned ``from llm_dojo_scoring.<module> import ...`` section."""
    out: dict[str, dict[str, Any]] = {}
    for module_path in sorted(surface.modules):
        entry = surface.modules[module_path]
        try:
            module = surface.index.get_module(module_path)
        except Exception:
            module = None
        attrs: dict[str, dict[str, Any]] = {}
        for attr in sorted(entry["attrs"]):
            obj = getattr(module, attr, _MISSING) if module is not None else _MISSING
            attrs[attr] = {
                "consumers": _sites(entry["attrs"][attr]),
                "private": attr.startswith("_"),
                "defined_in": _identity_defined_in(attr, obj, surface.index, module_path),
            }
        out[module_path] = {"legacy": entry["legacy"], "attrs": attrs}
    return out


def build_dispatch(surface: Surface) -> dict[str, dict[str, Any]]:
    """Render observed dispatch arguments plus the package's supported vocabulary."""
    from llm_dojo_scoring.config import TASK_KINDS

    supported = {
        "get_suite": sorted(surface.index.package.list_suites()),
        "score_task": sorted(TASK_KINDS),
        "suite_for_doc_type": sorted(surface.index.package.DOC_TYPE_ALIASES),
    }
    out: dict[str, dict[str, Any]] = {}
    for name in DISPATCH_FUNCS:
        out[name] = {
            "dynamic": [
                {
                    "repo": repo,
                    "file": file,
                    "line": line,
                    "expression": expression,
                }
                for repo, file, line, expression in sorted(
                    surface.dispatch_dynamic[name],
                    key=lambda item: (item[0], item[1], item[2], item[3]),
                )
            ],
            "literals": {
                value: _sites(sites)
                for value, sites in sorted(surface.dispatch_literals[name].items())
            },
            "supported": supported[name],
        }
    return out


def _assigned_strings(tree: ast.AST, name: str, container: str) -> list[tuple[str, int]]:
    """Collect literal strings assigned to ``name`` in a mapping/sequence."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        if container == "mapping" and isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.append((key.value, key.lineno))
        elif container == "sequence" and isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    found.append((element.value, element.lineno))
    return found


def _score_map_reads(tree: ast.AST) -> list[tuple[str, int]]:
    """Collect literal reads through a score-map receiver (``score_map.get(...)``)."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "get" or not node.args:
                continue
            receiver = node.func.value
            is_score_map = (
                isinstance(receiver, ast.Name) and "score" in receiver.id.lower()
            ) or (
                isinstance(receiver, ast.Attribute)
                and "score" in receiver.attr.lower()
            )
            arg = node.args[0]
            if is_score_map and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((arg.value, node.lineno))
        elif isinstance(node, ast.Subscript):
            receiver = node.value
            is_score_map = (
                isinstance(receiver, ast.Name) and "score" in receiver.id.lower()
            ) or (
                isinstance(receiver, ast.Attribute)
                and "score" in receiver.attr.lower()
            )
            key = node.slice
            if is_score_map and isinstance(key, ast.Constant) and isinstance(key.value, str):
                found.append((key.value, node.lineno))
    return found


def build_scores(tmr_files: dict[str, str] | None) -> dict[str, Any]:
    """Pin the Langfuse score names the visualizer reads and the dojo aliases."""
    from llm_dojo_scoring.metrics.registry import load_registry
    from llm_dojo_scoring.pipeline.mailroom import LANGFUSE_SCORE_NAME_ALIASES

    aliases = dict(sorted(LANGFUSE_SCORE_NAME_ALIASES.items()))
    registry = set(load_registry().metrics)
    reads: dict[str, set[Site]] = defaultdict(set)
    if tmr_files is not None:
        for rel, variable, container in TMR_SCORE_VARIABLES:
            text = tmr_files.get(rel)
            if text is None:
                continue
            tree = ast.parse(text, filename=f"TMR:{rel}")
            values = _assigned_strings(tree, variable, container)
            if not values:
                raise SystemExit(
                    f"TMR:{rel}: expected a literal {container} assignment named {variable!r}"
                )
            for value, line in values:
                reads[value].add(("TMR", rel, line))
        for rel, text in sorted(tmr_files.items()):
            if not rel.startswith(TMR_RUNTIME_PREFIXES):
                continue
            for value, line in _score_map_reads(ast.parse(text, filename=f"TMR:{rel}")):
                if value in registry:
                    reads[value].add(("TMR", rel, line))

    registry_ids = sorted(set(reads) | set(aliases) | set(aliases.values()))
    return {
        "aliases": aliases,
        "registry_ids": registry_ids,
        "visualizer_reads": {
            name: _sites(sites) for name, sites in sorted(reads.items())
        },
    }


# ---------------------------------------------------------------------------
# Build / compare / write
# ---------------------------------------------------------------------------


def build_fixture() -> dict[str, Any]:
    """Scan every configured consumer and return the manifest payload."""
    index = PackageIndex()
    surface = Surface(index)
    generated_from: dict[str, dict[str, Any]] = {}
    tmr_files: dict[str, str] | None = None

    for spec in REPOS:
        files, meta = scan_repo(spec)
        generated_from[spec.label] = meta
        if spec.label == "TMR" and meta["scanned"]:
            tmr_files = files
        if not meta["scanned"]:
            continue
        for rel, text in sorted(files.items()):
            try:
                tree = ast.parse(text, filename=f"{spec.label}:{rel}")
            except SyntaxError as exc:
                raise SystemExit(
                    f"parse failure in {spec.label}:{rel}:{exc.lineno}: {exc.msg}"
                ) from exc
            surface.collect_file(spec.label, rel, tree)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "generated_from": generated_from,
        "top_level": build_top_level(surface),
        "modules": build_modules(surface),
        "dispatch": build_dispatch(surface),
        "scores": build_scores(tmr_files),
        "patches": [
            {"repo": repo, "file": file, "line": line, "target": target}
            for repo, file, line, target in sorted(
                surface.patches, key=lambda item: (item[0], item[1], item[2], item[3])
            )
        ],
    }


def _dump(data: dict[str, Any]) -> str:
    """Serialize deterministically (sorted keys, stable indentation)."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _surface_view(data: dict[str, Any]) -> dict[str, Any]:
    """Drop machine-local checkout metadata before comparing manifests."""
    view = json.loads(json.dumps(data))
    for meta in view.get("generated_from", {}).values():
        for key in ("path", "ref", "commit"):
            meta.pop(key, None)
    return view


def _diff(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Return short paths where two JSON values differ (bounded by caller)."""
    if type(expected) is not type(actual):
        return [f"{path or '<root>'}: {type(expected).__name__} != {type(actual).__name__}"]
    if isinstance(expected, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}" if path else str(key)
            if key not in expected:
                out.append(f"{child}: added")
            elif key not in actual:
                out.append(f"{child}: removed")
            else:
                out.extend(_diff(expected[key], actual[key], child))
        return out
    if isinstance(expected, list):
        if expected != actual:
            return [f"{path}: list changed ({len(expected)} -> {len(actual)} items)"]
        return []
    if expected != actual:
        return [f"{path}: {expected!r} != {actual!r}"]
    return []


def _print_coverage(data: dict[str, Any]) -> None:
    """Print one line per configured consumer checkout."""
    for label, meta in sorted(data["generated_from"].items()):
        if meta["scanned"]:
            print(f"  {label}: {meta['files_scanned']} files @ {meta['commit'] or 'no-git'}")
        else:
            print(f"  {label}: skipped ({meta['reason']})")


def _lost_checkouts(existing: dict[str, Any] | None, data: dict[str, Any]) -> list[str]:
    """Checkouts the pinned fixture scanned that this machine could not scan."""
    pinned = (existing or {}).get("generated_from", {})
    return sorted(
        label
        for label, meta in data["generated_from"].items()
        if not meta["scanned"] and pinned.get(label, {}).get("scanned")
    )


def main(argv: list[str] | None = None) -> int:
    """Run the audit: refresh the fixture or check it for drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the fixture")
    mode.add_argument("--check", action="store_true", help="check for drift (default)")
    args = parser.parse_args(argv)

    data = build_fixture()
    _print_coverage(data)
    text = _dump(data)
    counts = f"{len(data['top_level'])} top-level names, {len(data['modules'])} modules"

    existing: dict[str, Any] | None = None
    if FIXTURE_PATH.is_file():
        existing = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    lost = _lost_checkouts(existing, data)

    if args.write:
        if lost:
            # Writing now would silently erase the pinned surface of these repos.
            print(
                "refusing --write; pinned checkouts are unavailable here: "
                + ", ".join(lost)
                + " (set their *_ROOT environment variables)",
                file=sys.stderr,
            )
            return 2
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)} ({counts})")
        return 0

    if existing is None:
        print(f"missing fixture: {FIXTURE_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    if lost:
        # Not drift: the surface cannot be checked without these checkouts.
        print(
            "cannot check consumer surface; pinned checkouts are unavailable here: "
            + ", ".join(lost)
            + " (set their *_ROOT environment variables)",
            file=sys.stderr,
        )
        return 2
    if _surface_view(existing) == _surface_view(data):
        print(f"OK {FIXTURE_PATH.relative_to(REPO_ROOT)} ({counts})")
        return 0

    changes = _diff(_surface_view(existing), _surface_view(data))
    print("consumer surface drift:", file=sys.stderr)
    for change in changes[:40]:
        print(f"  {change}", file=sys.stderr)
    if len(changes) > 40:
        print(f"  ... and {len(changes) - 40} more", file=sys.stderr)
    print("run with --write to refresh the fixture", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
