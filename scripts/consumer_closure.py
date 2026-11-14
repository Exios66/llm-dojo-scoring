#!/usr/bin/env python3
"""Decide which Dojo modules the consumers reach (keep), hold, or nobody reaches (delete).

The Dojo grew faster than its consumers use it.  This tool answers "which modules
does anything in production actually need?" mechanically, so a later change can
delete from the answer instead of from opinion.

Inputs
------
* ``tests/fixtures/consumer_surface.json`` (every recorded consumer) and
  ``tests/fixtures/contract_surface.json`` (the 0.27 audit-row contract names);
* a fresh static scan of the ``llm-mailroom`` and ``local-mailroom-sandbox``
  checkouts (committed blobs at ``HEAD``, never the working tree);
* optionally the same scan of extra mailroom git refs (open stacked PRs), read with
  ``git ls-tree`` / ``git cat-file`` and never checked out.

Each input yields *roots*: the modules a consumer imports.  A root-level name import
(``from llm_dojo_scoring import X``) roots the module that *defines* ``X`` (resolved
through the root ``__init__``'s re-exports), not the whole package.  Legacy flat
paths (``llm_dojo_scoring.field_scoring``) resolve through ``_layout.LEGACY_MODULES``.
Dispatch keys (``get_suite("sorter")``, ``score_task("legalbench")``,
``suite_for_doc_type(...)``) are recorded and root the modules that define the
dispatch functions; every module those functions can reach is a static (including
function-level) import of those modules, so the closure covers them.

Graph rules (what makes an edge)
--------------------------------
* Absolute, relative and function-level imports, including ``TYPE_CHECKING`` ones.
* ``from pkg import name`` edges to ``pkg`` and, when ``pkg.name`` is a module, to it.
* ``importlib.import_module("<package>.x")`` / ``__import__`` / ``resources.files``
  with a literal dotted name of this package.  No other string-based import exists
  in the package today; ``_layout.LEGACY_MODULES`` is an alias table, not an edge
  (every module has an alias, so treating it as one would make everything reachable).
* The root ``__init__.py`` has **no** edges.  It eagerly imports nearly every module;
  that bloat is what this tool measures.  The root ``__init__`` and ``_layout`` are
  structural and always kept.
* A subpackage ``__init__.py`` has the edges of its imports, followed only when the
  package is imported *explicitly* (``from pkg import ...``, ``import pkg``).  Parent
  packages of a kept module are kept as markers, but importing ``pkg.mod`` does not
  follow what ``pkg/__init__.py`` imports.  Today only ``prompts`` and
  ``scoring.doc_scorers`` have non-trivial inits.

Decision
--------
``keep`` = reachable from any root (plus structural modules and the parent packages of
kept modules).  ``hold`` = named in :data:`HOLD` or imported by a held module and not
kept.  ``delete`` = everything else.

Usage::

    uv run python scripts/consumer_closure.py --mailroom PATH --sandbox PATH \\
        [--extra-ref GITREF ...] --write
    uv run python scripts/consumer_closure.py --mailroom PATH --sandbox PATH \\
        [--extra-ref GITREF ...] --check

``--check`` exits 1 and prints a diff when the committed JSON drifts, and 2 when a
requested checkout or ref is missing, a checkout has no Python files, a consumer file
does not parse (its imports would be invisible), or a consumer imports a name or module
path the package does not have; in every exit-2 case nothing is written or accepted.  A consumer ``import *`` is
expanded: the root's ``__all__`` roots each exported name's module, a module or package
roots itself.  Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

PACKAGE = "llm_dojo_scoring"
REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / PACKAGE
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
OUTPUT_PATH = REPO_ROOT / "docs" / "analysis" / "data" / "consumer_closure.json"
SCHEMA_VERSION = 1

#: Key of the root ``__init__.py`` in every module table.
ROOT = "__init__"

#: Always kept: the package root and the legacy alias installer it needs to import.
STRUCTURAL: dict[str, str] = {
    ROOT: "package root (its eager imports are ignored; Task 5 makes it lazy)",
    "_layout": "legacy flat-path alias installer, imported by the package root",
}

#: Modules held back from deletion although no consumer reaches them today.  A key
#: that names a package holds every module below it.  Reasons carry the issue number.
HOLD: dict[str, str] = {
    "pipeline.archive": "unified audit row, Dojo #120 (mailroom PRs #226-#229)",
    "scoring.doc_scorers": "per-document-type scorers, Dojo #120 (mailroom PRs #226-#229)",
    "scoring.extraction_scope": "extraction scoping for the audit row, Dojo #120 (mailroom PRs #226-#229)",
    "pipeline.sandbox_schema_adherence": "schema adherence for the audit row, Dojo #120 (mailroom PRs #226-#229)",
    "schemas.v10_rows": "v10 dataset row loaders, mailroom #174",
    "schemas.correspondence_gt_audit": "correspondence ground-truth audit, Dojo #94",
    "schemas.corporate_record_relabel": "corporate record relabelling, Dojo #52",
    "integrations.update_awareness": "release tooling behind the dojo-version CLI, Dojo #66",
    "analysis.failure_modes": "source of registry metric failure_mode_breakdown (sorter bundle), Dojo #66",
    "scoring.decision_lanes": "judge/arbiter/boss/review-tray scorecards; llm-mailroom wires its decision export next (stacked on Dojo #140)",
}

#: Dispatch functions whose first (or named) argument selects what runs.
DISPATCH_FUNCS = ("get_suite", "score_task", "suite_for_doc_type")
_DISPATCH_PARAM = {"get_suite": "name", "score_task": "task", "suite_for_doc_type": "doc_type"}

#: Calls whose sole literal argument names a module of this package.
_STRING_IMPORT_CALLS = frozenset({"import_module", "__import__", "files"})

#: Consumer directories scanned (committed files below these prefixes only).
MAILROOM_DIRS = ("src", "tools", "experiments")
SANDBOX_DIRS = ("src", "scripts", "tests", "deploy", "api-evals", "vendor/llm-mailroom/src")

#: Directory names that never hold consumer source (matches audit_consumer_surface).
SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", "build", "dist", "node_modules", "vendor", "venv"}
)


def _load_audit():
    """Load the sibling ``audit_consumer_surface`` script by path (shared git helpers)."""
    path = Path(__file__).resolve().with_name("audit_consumer_surface.py")
    spec = importlib.util.spec_from_file_location("_dojo_audit_consumer_surface", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_audit = _load_audit()
if tuple(_audit.DISPATCH_FUNCS) != DISPATCH_FUNCS:  # pragma: no cover - guards drift
    raise SystemExit("DISPATCH_FUNCS drifted from audit_consumer_surface.DISPATCH_FUNCS")


# ---------------------------------------------------------------------------
# The package: modules, legacy aliases, root-level names
# ---------------------------------------------------------------------------


@dataclass
class Package:
    """Static facts about one package directory (never imported)."""

    name: str
    root: Path
    files: dict[str, Path]
    packages: frozenset[str]
    legacy: dict[str, str]
    root_names: dict[str, str | None] = field(default_factory=dict)
    #: The root ``__all__`` when it is a literal list/tuple of strings, else ``None``.
    root_all: list[str] | None = None

    def package_of(self, module: str) -> str:
        """Dotted package a module's relative imports are resolved against (``''`` = root)."""
        if module == ROOT:
            return ""
        if module in self.packages:
            return module
        return module.rpartition(".")[0]

    def root_module(self, name: str) -> str | None:
        """Module defining the root-level attribute ``name``, or ``None`` if unknown/root-defined."""
        if name in self.root_names:
            return self.root_names[name]
        if name in self.legacy and name not in self.files:
            return self.legacy[name]
        if name in self.files and name != ROOT:
            return name
        return None


def _module_name(rel: Path) -> tuple[str, bool]:
    """Dotted module name of a package source file, and whether it is a package ``__init__``."""
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
        return (".".join(parts) or ROOT), bool(parts)
    return ".".join(parts), False


def _assigned_dict(tree: ast.Module, name: str) -> dict[str, str]:
    """The literal dict assigned to module-level ``name``, else empty.

    Values are strings; a tuple or list value (``(module, attr)``) contributes its first item.
    """
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            try:
                literal = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return {}
            if isinstance(literal, dict):
                return {
                    str(k): str(v[0] if isinstance(v, (tuple, list)) and v else v)
                    for k, v in literal.items()
                }
    return {}


def _literal_all(tree: ast.Module) -> list[str] | None:
    """The literal ``__all__`` of a module (list/tuple of strings), or ``None`` if absent/dynamic."""
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            try:
                literal = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
            if isinstance(literal, (list, tuple)) and all(isinstance(n, str) for n in literal):
                return list(literal)
            return None
    return None


def _toplevel_statements(body: Iterable[ast.stmt]) -> Iterable[ast.stmt]:
    """Statements run at import time: the body plus ``if``/``try``/``with`` blocks, no functions."""
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _toplevel_statements(node.body)
            yield from _toplevel_statements(node.orelse)
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *[h.body for h in node.handlers]):
                yield from _toplevel_statements(block)
        elif isinstance(node, ast.With):
            yield from _toplevel_statements(node.body)


def _normalize_lazy_target(pkg_name: str, value: str) -> str:
    """Strip the package prefix, leading dots and a ``:attr`` suffix from a lazy-table value."""
    value = value.split(":", 1)[0].lstrip(".")
    if value.startswith(pkg_name + "."):
        value = value[len(pkg_name) + 1 :]
    return value


def _root_names(pkg: Package, tree: ast.Module) -> dict[str, str | None]:
    """Map each name bound by the root ``__init__`` to the module that defines it.

    ``None`` marks a name the root defines itself.  The lazy root's ``_LAZY`` (name ->
    (module, attr)) and ``_SUBMODULES`` (name -> module) tables are read as well.
    """
    names: dict[str, str | None] = {}
    for node in _toplevel_statements(tree.body):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            dotted = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                if dotted:
                    module, rest = resolve_modules(pkg, dotted)
                    sub = f"{dotted}.{alias.name}"
                    if sub in pkg.files:
                        names[bound] = sub
                    elif module is not None and not rest:
                        names[bound] = module
                elif alias.name in pkg.files:
                    names[bound] = alias.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.setdefault(node.name, None)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.setdefault(target.id, None)
    lazy = {**_assigned_dict(tree, "_SUBMODULES"), **_assigned_dict(tree, "_LAZY")}
    for key, value in lazy.items():
        target = _normalize_lazy_target(pkg.name, value)
        module, _ = resolve_modules(pkg, target)
        names[key] = module
    return names


def load_package(package_dir: Path) -> Package:
    """Index a package directory: its modules, legacy aliases and root-level names."""
    package_dir = Path(package_dir)
    files: dict[str, Path] = {}
    packages: set[str] = set()
    for path in sorted(package_dir.rglob("*.py")):
        rel = path.relative_to(package_dir)
        if "__pycache__" in rel.parts:
            continue
        name, is_package = _module_name(rel)
        files[name] = path
        if is_package:
            packages.add(name)
    legacy: dict[str, str] = {}
    layout = files.get("_layout")
    if layout is not None:
        legacy = _assigned_dict(ast.parse(layout.read_text(encoding="utf-8")), "LEGACY_MODULES")
    pkg = Package(package_dir.name, package_dir, files, frozenset(packages), legacy)
    root_init = files.get(ROOT)
    if root_init is not None:
        root_tree = ast.parse(root_init.read_text(encoding="utf-8"))
        pkg.root_names = _root_names(pkg, root_tree)
        pkg.root_all = _literal_all(root_tree)
    return pkg


def resolve_modules(pkg: Package, dotted: str) -> tuple[str | None, list[str]]:
    """Longest module prefix of ``dotted`` (a path below the package) and the rest.

    A first segment that is a legacy flat name is replaced by its subpackage path.
    """
    segments = dotted.split(".") if dotted else []
    if segments and segments[0] in pkg.legacy and segments[0] not in pkg.files:
        segments = pkg.legacy[segments[0]].split(".") + segments[1:]
    for k in range(len(segments), 0, -1):
        candidate = ".".join(segments[:k])
        if candidate in pkg.files:
            return candidate, segments[k:]
    return None, segments


# ---------------------------------------------------------------------------
# Import graph
# ---------------------------------------------------------------------------


def absolute_target(pkg: Package, node: ast.ImportFrom, importer: str | None) -> str | None:
    """Dotted path below the package an ``ImportFrom`` names (``''`` = root), else ``None``.

    ``importer`` is the importing module for relative imports, or ``None`` for code
    outside the package (where only absolute imports of the package count).
    """
    module = node.module or ""
    if node.level == 0:
        if module == pkg.name:
            return ""
        if module.startswith(pkg.name + "."):
            return module[len(pkg.name) + 1 :]
        return None
    if importer is None:
        return None
    base = [p for p in pkg.package_of(importer).split(".") if p]
    up = node.level - 1
    if up > len(base):
        return None
    base = base[: len(base) - up]
    return ".".join(base + ([p for p in module.split(".") if p] if module else []))


def modules_for_from_import(pkg: Package, target: str, names: Iterable[str]) -> set[str]:
    """Modules a ``from <target> import names`` reaches (the target and named submodules)."""
    reached: set[str] = set()
    if target == "":
        for name in names:
            module = pkg.root_module(name)
            if module:
                reached.add(module)
        return reached
    module, rest = resolve_modules(pkg, target)
    if module is None:
        return reached
    reached.add(module)
    if not rest:
        for name in names:
            sub = f"{module}.{name}"
            if sub in pkg.files:
                reached.add(sub)
    return reached


def _call_name(func: ast.AST) -> str | None:
    """The bare name of a called function (``a.b.f`` -> ``f``)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _string_import(pkg: Package, node: ast.Call) -> str | None:
    """Module named by ``import_module("<pkg>.x")``-style calls with a literal argument."""
    if _call_name(node.func) not in _STRING_IMPORT_CALLS or len(node.args) != 1:
        return None
    arg = node.args[0]
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return None
    value = arg.value
    if value != pkg.name and not value.startswith(pkg.name + "."):
        return None
    module, _ = resolve_modules(pkg, value[len(pkg.name) + 1 :])
    return module


def _module_edges(pkg: Package, module: str, tree: ast.AST) -> set[str]:
    """Every module of the package that ``module`` imports (any scope, any spelling)."""
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(pkg.name + "."):
                    found, _ = resolve_modules(pkg, alias.name[len(pkg.name) + 1 :])
                    if found:
                        edges.add(found)
        elif isinstance(node, ast.ImportFrom):
            target = absolute_target(pkg, node, module)
            if target is not None:
                names = [a.name for a in node.names if a.name != "*"]
                edges |= modules_for_from_import(pkg, target, names)
        elif isinstance(node, ast.Call):
            found = _string_import(pkg, node)
            if found:
                edges.add(found)
    edges.discard(module)
    return edges


def import_graph(package_dir: Path) -> dict[str, set[str]]:
    """Import graph of a package: dotted module (below the package) -> modules it imports.

    Keys cover every module file (the root ``__init__`` is ``"__init__"``, a
    subpackage ``__init__`` is the package's dotted name).  The root ``__init__`` has
    no edges (see the module docstring).  The package is parsed, never imported.
    """
    pkg = load_package(package_dir)
    graph: dict[str, set[str]] = {}
    for name, path in pkg.files.items():
        if name == ROOT:
            graph[name] = set()
            continue
        graph[name] = _module_edges(pkg, name, ast.parse(path.read_text(encoding="utf-8")))
    return graph


def root_init_imports(package_dir: Path) -> set[str]:
    """Modules the root ``__init__`` imports (ignored by the graph; used in delete reasons)."""
    pkg = load_package(package_dir)
    root = pkg.files.get(ROOT)
    if root is None:
        return set()
    return _module_edges(pkg, ROOT, ast.parse(root.read_text(encoding="utf-8")))


def reach(roots: Iterable[str], graph: Mapping[str, set[str]]) -> dict[str, str | None]:
    """Breadth-first reach from ``roots``; maps each reached module to the module that led to it."""
    parent: dict[str, str | None] = {}
    queue = sorted(r for r in set(roots) if r in graph)
    for root in queue:
        parent[root] = None
    while queue:
        nxt: list[str] = []
        for module in queue:
            for target in sorted(graph.get(module, ())):
                if target in graph and target not in parent:
                    parent[target] = module
                    nxt.append(target)
        queue = nxt
    return parent


def closure(roots: set[str], graph: dict[str, set[str]]) -> set[str]:
    """Every module reachable from ``roots`` (roots included) along import edges."""
    return set(reach(roots, graph))


# ---------------------------------------------------------------------------
# Scanning consumer source
# ---------------------------------------------------------------------------


@dataclass
class Scan:
    """What one body of consumer source (or fixture) reaches."""

    modules: set[str] = field(default_factory=set)
    dispatch: dict[str, set[str]] = field(default_factory=dict)
    dynamic: dict[str, int] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    parse_failures: list[str] = field(default_factory=list)

    def update(self, other: Scan) -> None:
        """Merge another scan into this one."""
        self.modules |= other.modules
        for func, keys in other.dispatch.items():
            self.dispatch.setdefault(func, set()).update(keys)
        for func, count in other.dynamic.items():
            self.dynamic[func] = self.dynamic.get(func, 0) + count
        self.unresolved |= other.unresolved
        self.parse_failures.extend(other.parse_failures)


_DOTTED = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*")


def dispatch_homes(pkg: Package) -> dict[str, str]:
    """Module that defines each dispatch function (found by AST, not hard-coded)."""
    homes: dict[str, str] = {}
    for name, path in sorted(pkg.files.items()):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and node.name in DISPATCH_FUNCS:
                homes.setdefault(node.name, name)
    return homes


def _dotted_string(pkg: Package, value: str) -> str | None:
    """Return the path below the package if ``value`` is wholly a dotted path of it."""
    if not value.startswith(pkg.name + ".") or not _DOTTED.fullmatch(value):
        return None
    return value[len(pkg.name) + 1 :]


def _attribute_chain(node: ast.AST) -> tuple[str | None, list[str]]:
    """Split ``a.b.c`` into (``a``, ``['b', 'c']``); ``(None, [])`` for anything else."""
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, list(reversed(attrs))
    return None, []


def root_star_names(pkg: Package) -> list[str]:
    """Names ``from <package> import *`` binds: the root ``__all__``, else every public root name."""
    if pkg.root_all is not None:
        return list(pkg.root_all)
    return [n for n in pkg.root_names if not n.startswith("_")]


def star_import_modules(pkg: Package, target: str) -> set[str]:
    """Modules a consumer's ``from <package>[.<target>] import *`` binds names from.

    A root star import binds the root's ``__all__`` (every public root name when there is
    none), so each name's defining module is a root.  A star import of a module or package
    roots that module (its own imports are graph edges); for a package, the submodules its
    literal ``__all__`` lists are imported by the star import too.
    """
    reached: set[str] = set()
    if target == "":
        for name in root_star_names(pkg):
            module = pkg.root_module(name)
            if module:
                reached.add(module)
        return reached
    module, rest = resolve_modules(pkg, target)
    if module is None:
        return reached
    reached.add(module)
    path = pkg.files.get(module)
    if not rest and module in pkg.packages and path is not None:
        exported = _literal_all(ast.parse(path.read_text(encoding="utf-8"))) or []
        reached |= {f"{module}.{n}" for n in exported if f"{module}.{n}" in pkg.files}
    return reached


def scan_source(pkg: Package, text: str, homes: Mapping[str, str] | None = None) -> Scan:
    """Statically scan one Python source for what it imports from the package."""
    scan = Scan()
    tree = ast.parse(text)
    homes = dispatch_homes(pkg) if homes is None else homes
    pkg_aliases: set[str] = set()
    mod_aliases: dict[str, str] = {}
    func_aliases: dict[str, str] = {}

    def root_name(name: str) -> None:
        """Root the module defining the root-level name ``name`` (or note it as unresolved)."""
        module = pkg.root_module(name)
        if module:
            scan.modules.add(module)
        elif name not in pkg.root_names:
            scan.unresolved.add(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == pkg.name:
                    pkg_aliases.add(alias.asname or pkg.name)
                elif alias.name.startswith(pkg.name + "."):
                    dotted = alias.name[len(pkg.name) + 1 :]
                    module, rest = resolve_modules(pkg, dotted)
                    if module:
                        scan.modules.add(module)
                    if module is None or rest:  # ``import a.b.c`` needs every segment to be a module
                        scan.unresolved.add(dotted)
                    if alias.asname:
                        if module:
                            mod_aliases[alias.asname] = module
                    else:
                        pkg_aliases.add(pkg.name)
        elif isinstance(node, ast.ImportFrom):
            target = absolute_target(pkg, node, None)
            if target is None:
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name == "*":
                    scan.modules |= star_import_modules(pkg, target)
                    star_module = resolve_modules(pkg, target)[0] if target else None
                    exported = set(root_star_names(pkg)) if target == "" else set()
                    for func in DISPATCH_FUNCS:
                        if func in exported or (star_module is not None and homes.get(func) == star_module):
                            func_aliases[func] = func
                    continue
                if alias.name in DISPATCH_FUNCS:
                    func_aliases[bound] = alias.name
                if target == "":
                    module = pkg.root_module(alias.name)
                    root_name(alias.name)
                    if module and (module == alias.name or alias.name in pkg.legacy):
                        mod_aliases[bound] = module
                else:
                    module, rest = resolve_modules(pkg, target)
                    if module and not rest and f"{module}.{alias.name}" in pkg.files:
                        mod_aliases[bound] = f"{module}.{alias.name}"
            names = [a.name for a in node.names if a.name != "*"]
            module, rest = resolve_modules(pkg, target) if target else (None, [])
            if target and (module is None or rest):  # ``from a.b import`` needs a module a.b
                scan.unresolved.add(target)
            scan.modules |= modules_for_from_import(pkg, target, names) if target else set()
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            dotted = _dotted_string(pkg, node.value)
            if dotted is not None:
                module, _ = resolve_modules(pkg, dotted)
                if module:
                    scan.modules.add(module)
                else:
                    first = dotted.split(".")[0]
                    resolved = pkg.root_module(first)
                    if resolved:
                        scan.modules.add(resolved)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            base, attrs = _attribute_chain(node)
            if base in pkg_aliases:
                current = ""
            elif base in mod_aliases:
                current = mod_aliases[base]
            else:
                continue
            for attr in attrs:
                if current == "":
                    module = pkg.root_module(attr)
                    if module:
                        scan.modules.add(module)
                    if module and attr in pkg.files:
                        current = attr
                        continue
                    break
                sub = f"{current}.{attr}"
                if sub in pkg.files:
                    scan.modules.add(sub)
                    current = sub
                else:
                    break
        elif isinstance(node, ast.Call):
            func = _dispatch_function(node.func, func_aliases, pkg_aliases, mod_aliases)
            if func is None:
                continue
            argument: ast.AST | None = node.args[0] if node.args else None
            if argument is None:
                wanted = [k.value for k in node.keywords if k.arg == _DISPATCH_PARAM[func]]
                argument = wanted[0] if wanted else None
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                scan.dispatch.setdefault(func, set()).add(argument.value)
            else:
                scan.dynamic[func] = scan.dynamic.get(func, 0) + 1
            home = homes.get(func)
            if home:
                scan.modules.add(home)
    return scan


def _dispatch_function(
    func: ast.AST,
    func_aliases: Mapping[str, str],
    pkg_aliases: set[str],
    mod_aliases: Mapping[str, str],
) -> str | None:
    """Name of the dispatch function a call target is, when it comes from the package."""
    if isinstance(func, ast.Name):
        return func_aliases.get(func.id)
    if isinstance(func, ast.Attribute) and func.attr in DISPATCH_FUNCS:
        base, _ = _attribute_chain(func)
        if base in pkg_aliases or base in mod_aliases:
            return func.attr
    return None


# ---------------------------------------------------------------------------
# Fixture roots
# ---------------------------------------------------------------------------


def scan_consumer_surface(pkg: Package, data: Mapping[str, Any], homes: Mapping[str, str]) -> Scan:
    """Roots recorded in ``consumer_surface.json`` (names, modules, patches, dispatch keys)."""
    scan = Scan()
    for name in data.get("top_level", {}):
        module = pkg.root_module(name)
        if module:
            scan.modules.add(module)
        elif name not in pkg.root_names:
            scan.unresolved.add(name)
    for dotted in data.get("modules", {}):
        module, rest = resolve_modules(pkg, dotted)
        if module:
            scan.modules.add(module)
        if module is None or rest:  # a recorded module path must name a whole module
            scan.unresolved.add(dotted)
    for patch in data.get("patches", []):
        dotted = _dotted_string(pkg, str(patch.get("target", "")))
        module, _ = resolve_modules(pkg, dotted) if dotted else (None, [])
        if module:
            scan.modules.add(module)
    for func, entry in data.get("dispatch", {}).items():
        keys = set(entry.get("literals", {}))
        if keys or entry.get("dynamic"):
            home = homes.get(func)
            if home:
                scan.modules.add(home)
        if keys:
            scan.dispatch.setdefault(func, set()).update(keys)
    return scan


def scan_contract_surface(pkg: Package, data: Mapping[str, Any]) -> Scan:
    """Roots named in ``contract_surface.json`` (``package.module:name`` entries)."""
    scan = Scan()
    for entry in data.get("names", {}):
        module_path, _, name = entry.partition(":")
        below = module_path[len(pkg.name) + 1 :] if module_path.startswith(pkg.name + ".") else ""
        at_root = module_path == pkg.name or not below
        if at_root:
            module = pkg.root_module(name)
        else:
            module, _ = resolve_modules(pkg, below)
        if module:
            scan.modules.add(module)
        elif not (at_root and name in pkg.root_names):  # a name the root itself defines is resolved
            scan.unresolved.add(entry)
    return scan


# ---------------------------------------------------------------------------
# Reading consumer repositories
# ---------------------------------------------------------------------------


class MissingInput(Exception):
    """A requested checkout or git ref is not available on this machine."""


def _skipped(rel_below_prefix: Path) -> bool:
    """True when a path below a scanned prefix sits in a vendored or generated directory."""
    return any(part in SKIP_DIRS for part in rel_below_prefix.parts[:-1])


def _git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run git in ``root`` and return its raw stdout (raises ``MissingInput`` on failure)."""
    proc = subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True)
    if proc.returncode != 0:
        raise MissingInput(f"git {' '.join(args[:2])}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def commit_of(root: Path, ref: str) -> str | None:
    """Commit id ``ref`` resolves to in the checkout at ``root``, or ``None``."""
    if not _audit._is_git_checkout(root):
        return None
    return _audit._git_rev(root, ref)


def read_git_tree(root: Path, ref: str, prefixes: tuple[str, ...]) -> dict[str, str]:
    """Python files below ``prefixes`` at ``ref``, read from the object store (no checkout)."""
    if commit_of(root, ref) is None:
        raise MissingInput(f"git ref {ref!r} not found in the checkout")
    listing = _git_bytes(root, "ls-tree", "-r", "-z", ref).split(b"\0")
    wanted: dict[str, str] = {}
    for raw in listing:
        if not raw:
            continue
        meta, _, path_bytes = raw.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or fields[1] != b"blob":
            continue
        path = path_bytes.decode("utf-8", errors="replace")
        if not path.endswith(".py"):
            continue
        for prefix in prefixes:
            if path.startswith(prefix + "/"):
                if not _skipped(Path(path[len(prefix) + 1 :])):
                    wanted[path] = fields[2].decode()
                break
    if not wanted:
        return {}
    ordered = sorted(wanted)
    blob = _git_bytes(root, "cat-file", "--batch", stdin="".join(f"{wanted[p]}\n" for p in ordered).encode())
    files: dict[str, str] = {}
    cursor = 0
    for path in ordered:
        end = blob.index(b"\n", cursor)
        _, _, size = blob[cursor:end].decode().split()
        start = end + 1
        files[path] = blob[start : start + int(size)].decode("utf-8", errors="replace")
        cursor = start + int(size) + 1
    return files


def read_filesystem_tree(root: Path, prefixes: tuple[str, ...]) -> dict[str, str]:
    """Python files below ``prefixes`` in a plain (non-git) directory."""
    files: dict[str, str] = {}
    for prefix in prefixes:
        base = root / prefix
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if filename.endswith(".py") and path.is_file():
                    files[path.relative_to(root).as_posix()] = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
    return dict(sorted(files.items()))


def read_consumer(root: Path, ref: str | None, prefixes: tuple[str, ...]) -> dict[str, str]:
    """Source of one consumer: committed blobs when ``root`` is a git checkout, else files."""
    if not root.is_dir():
        raise MissingInput(f"checkout not found: {root.name}")
    if _audit._is_git_checkout(root):
        return read_git_tree(root, ref or "HEAD", prefixes)
    if ref is not None:
        raise MissingInput(f"{root.name} is not a git checkout, cannot read ref {ref!r}")
    return read_filesystem_tree(root, prefixes)


def scan_files(pkg: Package, files: Mapping[str, str], homes: Mapping[str, str]) -> tuple[Scan, int]:
    """Scan many sources; returns the merged scan and the number that failed to parse.

    The scan's ``parse_failures`` names each file that did not parse: its imports are
    invisible, so the closure built from it is incomplete.
    """
    total = Scan()
    failures = 0
    for rel, text in sorted(files.items()):
        try:
            total.update(scan_source(pkg, text, homes))
        except SyntaxError:
            failures += 1
            total.parse_failures.append(rel)
            print(f"warning: could not parse {rel}", file=sys.stderr)
    return total, failures


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def expand_hold(hold: Mapping[str, str], graph: Mapping[str, set[str]]) -> dict[str, str]:
    """Hold table expanded to modules: a package entry holds every module below it."""
    expanded: dict[str, str] = {}
    for key, reason in sorted(hold.items()):
        for module in sorted(graph):
            if module == key or module.startswith(key + "."):
                expanded.setdefault(module, reason)
    return expanded


def missing_hold_entries(hold: Mapping[str, str], graph: Mapping[str, set[str]]) -> list[str]:
    """Hold keys that are neither a module nor a package of the graph (stale entries)."""
    return sorted(key for key in hold if key not in graph and not any(m.startswith(key + ".") for m in graph))


def _ancestors(module: str, graph: Mapping[str, set[str]]) -> list[str]:
    """Parent packages of a dotted module that exist in the graph."""
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts)) if ".".join(parts[:i]) in graph]


def classify(
    graph: Mapping[str, set[str]],
    lines: Mapping[str, int],
    roots_by_source: Mapping[str, set[str]],
    *,
    hold: Mapping[str, str] = HOLD,
    structural: Mapping[str, str] = STRUCTURAL,
    init_imports: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Give every module a decision: ``keep``, ``hold`` or ``delete``, with a reason."""
    direct: dict[str, set[str]] = defaultdict(set)
    for source, modules in roots_by_source.items():
        for module in modules:
            if module in graph:
                direct[module].add(source)
    parent = reach(direct, graph)
    keep: dict[str, str] = {}
    for module in sorted(parent):
        if module in direct:
            keep[module] = "consumer import: " + ", ".join(sorted(direct[module]))
        else:
            keep[module] = f"imported by kept {parent[module]}"
    for module, reason in structural.items():
        if module in graph:
            keep.setdefault(module, reason)
    for module in sorted(list(keep)):
        for ancestor in _ancestors(module, graph):
            keep.setdefault(ancestor, f"package of kept {module}")

    held_direct = expand_hold(hold, graph)
    held_roots = [m for m in held_direct if m not in keep]
    held_parent = reach(held_roots, graph)
    held: dict[str, str] = {}
    for module in sorted(held_parent):
        if module in keep:
            continue
        if module in held_direct:
            held[module] = held_direct[module]
        else:
            held[module] = f"imported by held {held_parent[module]}"
    for module in sorted(list(held)):
        for ancestor in _ancestors(module, graph):
            if ancestor not in keep:
                held.setdefault(ancestor, f"package of held {module}")

    importers: dict[str, set[str]] = defaultdict(set)
    for module, targets in graph.items():
        for target in targets:
            importers[target].add(module)
    init_imports = init_imports or set()

    decisions: dict[str, dict[str, Any]] = {}
    for module in sorted(graph):
        if module in keep:
            decision, reason = "keep", keep[module]
        elif module in held:
            decision, reason = "hold", held[module]
        else:
            decision = "delete"
            who = sorted(importers.get(module, ()))
            if module in init_imports:
                who.append("the root __init__")
            if who:
                shown = ", ".join(who[:4]) + (", ..." if len(who) > 4 else "")
                reason = f"no consumer reaches it; imported only by {shown}"
            else:
                reason = "no consumer reaches it; nothing imports it"
        decisions[module] = {"decision": decision, "reason": reason, "lines": int(lines.get(module, 0))}
    return decisions


# ---------------------------------------------------------------------------
# Build / compare / write
# ---------------------------------------------------------------------------


@dataclass
class Source:
    """One input to the closure: its roots and how to identify it without a path."""

    roots: set[str]
    meta: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    """Load a fixture, raising ``MissingInput`` when it is absent."""
    if not path.is_file():
        raise MissingInput(f"fixture not found: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_sources(
    pkg: Package,
    *,
    fixtures_dir: Path,
    mailroom: Path,
    sandbox: Path,
    extra_refs: list[str],
) -> tuple[dict[str, Source], Scan]:
    """Gather every source's roots; also return the merged scan (dispatch keys, warnings)."""
    homes = dispatch_homes(pkg)
    sources: dict[str, Source] = {}
    merged = Scan()

    surface = scan_consumer_surface(pkg, _read_json(fixtures_dir / "consumer_surface.json"), homes)
    sources["consumer_surface"] = Source(surface.modules, {"file": "tests/fixtures/consumer_surface.json"})
    contract = scan_contract_surface(pkg, _read_json(fixtures_dir / "contract_surface.json"))
    sources["contract_surface"] = Source(contract.modules, {"file": "tests/fixtures/contract_surface.json"})
    merged.update(surface)
    merged.update(contract)

    plan = [("MAIL", mailroom, None, MAILROOM_DIRS), ("SBX", sandbox, None, SANDBOX_DIRS)]
    plan += [(f"MAIL@{ref}", mailroom, ref, MAILROOM_DIRS) for ref in extra_refs]
    for code, root, ref, prefixes in plan:
        try:
            files = read_consumer(root, ref, prefixes)
        except MissingInput as exc:
            raise MissingInput(f"{code}: {exc}") from exc
        if not files:
            raise MissingInput(f"{code}: no Python files under {', '.join(prefixes)} in the checkout")
        scan, failures = scan_files(pkg, files, homes)
        meta: dict[str, Any] = {"commit": commit_of(root, ref or "HEAD"), "files_scanned": len(files)}
        if failures:
            meta["parse_failures"] = failures
        sources[code] = Source(scan.modules, meta)
        scan.parse_failures = [f"{code}: {rel}" for rel in scan.parse_failures]
        merged.update(scan)
    return sources, merged


def build_report(package_dir: Path, sources: Mapping[str, Source], scan: Scan) -> dict[str, Any]:
    """Assemble the JSON document from the package and the gathered sources."""
    pkg = load_package(package_dir)
    graph = import_graph(package_dir)
    lines = {name: path.read_bytes().count(b"\n") for name, path in pkg.files.items()}
    decisions = classify(
        graph,
        lines,
        {code: source.roots for code, source in sources.items()},
        hold=HOLD,
        init_imports=root_init_imports(package_dir),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "scripts/consumer_closure.py",
        "roots": {code: sorted(sources[code].roots) for code in sorted(sources)},
        "sources": {code: dict(sorted(sources[code].meta.items())) for code in sorted(sources)},
        "dispatch_keys": {func: sorted(keys) for func, keys in sorted(scan.dispatch.items())},
        "modules": {name: decisions[name] for name in sorted(decisions)},
    }


def _dump(data: Mapping[str, Any]) -> str:
    """Serialize deterministically."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _comparable(data: Mapping[str, Any]) -> dict[str, Any]:
    """The part of the report whose change is drift (recorded commits are informational)."""
    view = json.loads(json.dumps(data))
    for meta in view.get("sources", {}).values():
        meta.pop("commit", None)
    return view


def _summary(report: Mapping[str, Any]) -> str:
    """One line with the decision totals."""
    totals: dict[str, list[int]] = {"keep": [0, 0], "hold": [0, 0], "delete": [0, 0]}
    for entry in report["modules"].values():
        totals[entry["decision"]][0] += 1
        totals[entry["decision"]][1] += entry["lines"]
    return ", ".join(f"{k} {n} modules / {ln} lines" for k, (n, ln) in totals.items())


def main(argv: list[str] | None = None) -> int:
    """Write or check ``docs/analysis/data/consumer_closure.json``."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mailroom", type=Path, required=True, help="llm-mailroom checkout")
    parser.add_argument("--sandbox", type=Path, required=True, help="local-mailroom-sandbox checkout")
    parser.add_argument("--extra-ref", action="append", default=[], metavar="GITREF",
                        help="extra llm-mailroom ref to scan (read with git, never checked out)")
    parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite the JSON")
    mode.add_argument("--check", action="store_true", help="exit 1 if the JSON drifted")
    args = parser.parse_args(argv)

    pkg = load_package(args.package_dir)
    graph = import_graph(args.package_dir)
    stale = missing_hold_entries(HOLD, graph)
    if stale:
        print("HOLD names modules that do not exist: " + ", ".join(stale), file=sys.stderr)
        return 2

    try:
        sources, scan = collect_sources(
            pkg,
            fixtures_dir=args.fixtures_dir,
            mailroom=args.mailroom,
            sandbox=args.sandbox,
            extra_refs=list(args.extra_ref),
        )
    except MissingInput as exc:
        print(f"cannot build the closure: {exc}", file=sys.stderr)
        return 2

    if scan.unresolved:
        print(
            "cannot build the closure: consumers import names or modules the package no longer "
            "has, so their former modules cannot be rooted (update the consumer or restore the "
            "name): " + ", ".join(sorted(scan.unresolved)),
            file=sys.stderr,
        )
        return 2
    if scan.parse_failures:
        print(
            "cannot build the closure: consumer files did not parse, so their imports are "
            "invisible (fix or exclude them): " + ", ".join(scan.parse_failures),
            file=sys.stderr,
        )
        return 2

    report = build_report(args.package_dir, sources, scan)
    text = _dump(report)

    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output.name}: {_summary(report)}")
        return 0

    if not args.output.is_file():
        print(f"missing {args.output.name}; run with --write", file=sys.stderr)
        return 1
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    if _dump(_comparable(existing)) == _dump(_comparable(report)):
        for code, meta in report["sources"].items():
            recorded = existing.get("sources", {}).get(code, {}).get("commit")
            if meta.get("commit") != recorded:
                print(f"note: {code} is at {meta.get('commit')}, recorded {recorded}; decisions unchanged")
        print(f"OK {args.output.name}: {_summary(report)}")
        return 0
    diff = list(
        difflib.unified_diff(
            _dump(_comparable(existing)).splitlines(),
            _dump(_comparable(report)).splitlines(),
            "recorded",
            "fresh",
            n=1,
            lineterm="",
        )
    )
    print("consumer closure drift:", file=sys.stderr)
    for line in diff[:80]:
        print(f"  {line}", file=sys.stderr)
    if len(diff) > 80:
        print(f"  ... and {len(diff) - 80} more diff lines", file=sys.stderr)
    print("run with --write to refresh the JSON", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
