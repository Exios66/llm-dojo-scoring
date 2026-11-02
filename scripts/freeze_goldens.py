#!/usr/bin/env python3
"""Freeze or check the committed golden-number scoring baseline (issue #67).

The fixture under ``tests/fixtures/golden/`` covers **every** key in
``llm_dojo_scoring.config.TASK_KINDS`` and **every** live scoring suite from
``list_suites(live_only=True)``. ``inputs.json`` is hand-authored; ``scores.json``
is generated from it by this script.

Usage::

    # Default is check-only: regenerate in memory, print a unified diff, exit 1.
    uv run --python 3.12 python scripts/freeze_goldens.py --check

    # Rewrite the baseline after an intentional scoring change. The reason is
    # printed for the review trail; the script re-collects after writing and
    # refuses to leave a non-idempotent baseline.
    uv run --python 3.12 python scripts/freeze_goldens.py --write \
        --reason "Fix CUAD date normalization (PR #123)"

Canonical form: dataclasses go through ``.to_dict()``; sets and non-finite
floats are rejected; keys are sorted, indentation is 2 spaces, non-ASCII is
preserved, and the file ends with one LF. The only masked value is
``provenance.scorer_version`` (replaced with ``"<SCORER_VERSION>"``), because a
package version bump is not a scoring change. Tests separately pin the real
version to ``SCORER_VERSION``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import fields, is_dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_dojo_scoring.config import TASK_KINDS, clear_settings_cache, get_settings
from llm_dojo_scoring.scoring.suites import get_suite, list_suites
from llm_dojo_scoring.scoring.tasks import chained_summary, score_task

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
INPUTS_PATH = GOLDEN_DIR / "inputs.json"
SCORES_PATH = GOLDEN_DIR / "scores.json"

SCORER_VERSION_PLACEHOLDER = "<SCORER_VERSION>"
DEFAULT_AMBIGUOUS_BAND = (0.5, 0.85)



def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to a unique sibling temp file, then atomically replace ``path``.

    Each call stages its own file, so overlapping ``--write`` runs cannot share
    a staging path, and a failed write never truncates the committed baseline.
    """
    fd, staged_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    staged = Path(staged_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise

def canonicalize(value: Any) -> Any:
    """Recursively convert a scoring payload into JSON-safe canonical data.

    Dataclasses use ``.to_dict()`` (or their fields as a fallback). Sets and
    non-finite floats are rejected rather than silently coerced. ``None`` and
    ``0.0`` stay distinct. Only ``provenance.scorer_version`` is masked.
    """
    if is_dataclass(value) and not isinstance(value, type):
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            value = to_dict()
        else:
            value = {field.name: getattr(value, field.name) for field in fields(value)}
    elif callable(getattr(value, "to_dict", None)) and not isinstance(
        value, (dict, list, tuple, set, frozenset, str, bytes)
    ):
        value = value.to_dict()

    if isinstance(value, dict):
        canonical: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string mapping key {key!r} ({type(key).__name__})")
            if key == "provenance" and isinstance(item, dict):
                item = dict(item)
                if "scorer_version" in item:
                    item["scorer_version"] = SCORER_VERSION_PLACEHOLDER
            canonical[key] = canonicalize(item)
        return canonical

    if isinstance(value, (set, frozenset)):
        raise TypeError("sets are not allowed in the golden baseline")
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float {value!r} is not allowed")
        return value
    raise TypeError(f"unsupported golden value {type(value).__name__}: {value!r}")


def render_goldens(payload: Any) -> str:
    """Canonical JSON text with sorted keys, 2-space indent, and one trailing LF."""
    return (
        json.dumps(
            canonicalize(payload),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def load_inputs(path: Path = INPUTS_PATH) -> dict[str, Any]:
    """Read the committed ``inputs.json`` fixture."""
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    validate_inputs(data)
    return data


def validate_inputs(inputs: dict[str, Any]) -> None:
    """Fail when an input entry is missing for a task key or live suite."""
    if not isinstance(inputs, dict):
        raise ValueError("golden inputs must be a JSON object")

    task_cases = inputs.get("task_cases")
    if not isinstance(task_cases, dict):
        raise ValueError("golden inputs need a 'task_cases' object")
    expected_tasks = set(TASK_KINDS)
    missing_tasks = sorted(expected_tasks - set(task_cases))
    extra_tasks = sorted(set(task_cases) - expected_tasks)
    if missing_tasks or extra_tasks:
        raise ValueError(
            "golden task input drift: "
            f"missing={missing_tasks or 'none'} unexpected={extra_tasks or 'none'}"
        )

    for task, case in task_cases.items():
        if not isinstance(case, dict):
            raise ValueError(f"task case {task!r} must be an object")
        for key in ("expected", "predicted"):
            if key not in case:
                raise ValueError(f"task case {task!r} is missing {key!r}")
        if task == "chained":
            for key in ("guard", "summary"):
                if key not in case:
                    raise ValueError(f"chained case is missing {key!r}")
            if case["guard"].get("raises") != "ValueError":
                raise ValueError("chained guard must declare raises='ValueError'")
            if not isinstance(case["summary"], dict):
                raise ValueError("chained summary must be an object")

    suite_cases = inputs.get("suite_cases")
    if not isinstance(suite_cases, dict):
        raise ValueError("golden inputs need a 'suite_cases' object")
    live_suites = set(list_suites(live_only=True))
    missing_suites = sorted(live_suites - set(suite_cases))
    extra_suites = sorted(set(suite_cases) - live_suites)
    if missing_suites or extra_suites:
        raise ValueError(
            "golden suite input drift: "
            f"missing={missing_suites or 'none'} unexpected={extra_suites or 'none'}"
        )

    for name, case in suite_cases.items():
        if not isinstance(case, dict):
            raise ValueError(f"suite case {name!r} must be an object")
        if case.get("computable") is False:
            continue
        for key in ("expected", "predicted"):
            if key not in case:
                raise ValueError(f"suite case {name!r} is missing {key!r}")


def _ensure_default_settings() -> None:
    """Refuse to freeze against a non-default settings/env configuration."""
    env_path = os.environ.get("LLM_DOJO_SCORING_CONFIG", "")
    if env_path.strip() and Path(env_path).exists():
        raise RuntimeError(
            "golden baselines require default settings; unset "
            f"LLM_DOJO_SCORING_CONFIG (currently {env_path!r})"
        )
    clear_settings_cache()
    band = tuple(get_settings().field_scoring.ambiguous_band)
    if band != DEFAULT_AMBIGUOUS_BAND:
        raise RuntimeError(
            "golden baselines require the default ambiguous_band "
            f"{DEFAULT_AMBIGUOUS_BAND}, got {band}"
        )


def _collect_task_case(task: str, case: dict[str, Any]) -> dict[str, Any]:
    """Score one task-key case, including the chained guard + summary shape."""
    if task == "chained":
        try:
            score_task(task, case["expected"], case["predicted"])
        except ValueError as exc:
            guard = {"raises": "ValueError", "message": str(exc)}
        else:  # pragma: no cover - a broken guard must fail the freeze loudly
            raise RuntimeError("score_task('chained', ...) did not raise ValueError")
        return {
            "kind": "chained",
            "score_task_guard": guard,
            "chained_summary": chained_summary(**case["summary"]),
        }

    kwargs = {
        key: value
        for key, value in case.items()
        if key not in ("expected", "predicted")
    }
    return {
        "kind": TASK_KINDS[task],
        "score": score_task(task, case["expected"], case["predicted"], **kwargs),
    }


def _collect_suite_case(name: str, case: dict[str, Any]) -> dict[str, Any]:
    """Score one live-suite case, or record the explicit emit-only refusal."""
    suite = get_suite(name)
    declared_computable = case.get("computable")
    if declared_computable is not None and declared_computable != suite.computable:
        raise RuntimeError(
            f"suite {name!r} computable={suite.computable}, inputs declare "
            f"{declared_computable!r}"
        )

    if not suite.computable:
        if "kind" in case and case["kind"] != suite.kind:
            raise RuntimeError(
                f"suite {name!r} kind={suite.kind!r}, inputs declare {case['kind']!r}"
            )
        try:
            suite.score(None, None)
        except TypeError as exc:
            # Only the documented emit-only refusal counts; an unrelated
            # TypeError from inside the scorer is a regression, not the contract.
            if "emit-only" not in str(exc):
                raise RuntimeError(
                    f"emit-only suite {name!r} raised an unexpected TypeError: {exc}"
                ) from exc
        else:  # pragma: no cover - emit-only suites must keep refusing
            raise RuntimeError(f"emit-only suite {name!r} did not raise TypeError")
        return {
            "computable": False,
            "kind": suite.kind,
            "score_raises": "TypeError",
            "metric_names": suite.metric_names(),
        }

    kwargs = dict(case.get("kwargs") or {})
    expected = case["expected"]
    predicted = case["predicted"]
    if suite.kind == "extraction":
        return {
            "computable": True,
            "kind": suite.kind,
            "score": suite.score(expected, predicted, **kwargs),
            "score_document": suite.score_document(expected, predicted, **kwargs),
        }
    return {
        "computable": True,
        "kind": suite.kind,
        "score": suite.score(expected, predicted, **kwargs),
    }


def collect_goldens(inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Regenerate the full baseline from ``inputs.json`` in memory."""
    _ensure_default_settings()
    if inputs is None:
        inputs = load_inputs()
    else:
        validate_inputs(inputs)

    return {
        "task_kinds": {
            task: _collect_task_case(task, inputs["task_cases"][task])
            for task in sorted(TASK_KINDS)
        },
        "suites": {
            name: _collect_suite_case(name, inputs["suite_cases"][name])
            for name in sorted(list_suites(live_only=True))
        },
    }


def _unified_diff(committed: str, regenerated: str) -> str:
    """Unified diff between the committed baseline and a regenerated one."""
    return "".join(
        unified_diff(
            committed.splitlines(keepends=True),
            regenerated.splitlines(keepends=True),
            fromfile=str(SCORES_PATH),
            tofile=f"{SCORES_PATH} (regenerated)",
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Run check mode by default; ``--write --reason`` rewrites the baseline."""
    parser = argparse.ArgumentParser(
        description="Freeze/check golden scoring baselines for tasks and live suites."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory, compare, and exit 1 on drift (default)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite scores.json (requires --reason)",
    )
    parser.add_argument(
        "--reason",
        metavar="TEXT",
        help="audit reason for an intentional baseline rewrite",
    )
    args = parser.parse_args(argv)

    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    if args.write and not args.reason:
        parser.error("--write requires --reason TEXT")
    if args.reason and not args.write:
        parser.error("--reason is only valid with --write")

    inputs = load_inputs()
    regenerated = render_goldens(collect_goldens(inputs))

    if args.write:
        previous = (
            SCORES_PATH.read_text(encoding="utf-8") if SCORES_PATH.exists() else None
        )
        def _restore() -> None:
            """Put the previous baseline back (or remove a newly created one)."""
            if previous is None:
                SCORES_PATH.unlink(missing_ok=True)
            else:
                _atomic_write(SCORES_PATH, previous)

        SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(SCORES_PATH, regenerated)
        try:
            recollected = render_goldens(collect_goldens(load_inputs()))
        except BaseException:
            # A failed second collection must not leave an unverified baseline.
            _restore()
            raise
        if recollected != regenerated:
            _restore()
            print(
                "error: golden generation is not idempotent; previous baseline restored",
                file=sys.stderr,
            )
            return 1
        print(f"wrote {SCORES_PATH}")
        print(f"reason: {args.reason}")
        print("idempotence check: OK")
        return 0

    try:
        committed = SCORES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: missing committed baseline {SCORES_PATH}", file=sys.stderr)
        return 1
    if committed == regenerated:
        print(f"golden scores match {SCORES_PATH}")
        return 0

    print(_unified_diff(committed, regenerated), end="")
    print(
        "\nerror: committed golden scores drifted; review the diff and rerun with "
        '--write --reason "..." if the change is intentional',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
