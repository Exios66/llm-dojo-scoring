"""Capture sandbox scoring goldens for the per-document-type scorers.

Runs inside a local-mailroom-sandbox virtualenv (it imports the sandbox's scorer
and its vendored mailroom/dojo), for example::

    <sandbox>/.venv/bin/python scripts/capture_sandbox_goldens.py \\
        --sandbox <sandbox> \\
        --inputs tests/fixtures/doc_scorers/inputs.json \\
        --out tests/fixtures/doc_scorers/goldens.json

For every input case it records:

- ``payload``: ``score_extraction_row(...)`` (or ``{"error": ...}`` if it raised);
- ``adherence``: ``assess_extraction_payload(...)`` (or ``{"error": ...}``);
- ``model_fields`` / ``typed_valid``: the mailroom pydantic model's field names and
  its verdict on the coerced payload, so dojo tests can replay mailroom's schema
  check without importing mailroom.

Output is JSON with ``sort_keys=True`` so re-captures diff cleanly.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert scorer output (dataclasses, sets, tuples, NaN) into plain JSON values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(to_jsonable(v) for v in value)
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _error(exc: BaseException) -> dict[str, str]:
    """Record an exception as data so parity tests can compare failures too."""
    return {"error": f"{type(exc).__name__}: {exc}"}


def _model_facts(doc_type: str, predicted: Any) -> tuple[list[str] | None, bool | None]:
    """The core mailroom model's field names and its verdict on the coerced payload."""
    from mailroom_sandbox.eval.schema_adherence import coerce_predicted_payload
    from schemas.documents import get_extraction_schema

    model = get_extraction_schema(str(doc_type or "").strip())
    if model is None:
        return None, None
    fields = sorted(model.model_fields)
    payload, meta = coerce_predicted_payload(predicted)
    if payload is None:
        return fields, None
    try:
        model.model_validate(dict(payload))
        return fields, True
    except Exception:
        return fields, False


def capture(cases: list[dict]) -> dict[str, dict]:
    """Score every case with the sandbox and return the goldens keyed by case id."""
    from mailroom_sandbox.eval.schema_adherence import assess_extraction_payload
    from mailroom_sandbox.eval.scoring import score_extraction_row

    out: dict[str, dict] = {}
    for case in cases:
        sub = case.get("doc_subclass") or case.get("expected_subclass")
        try:
            payload = score_extraction_row(
                case["doc_type"],
                case["predicted"],
                case["expected"],
                doc_text=case.get("doc_text"),
                doc_subclass=case.get("doc_subclass"),
                expected_subclass=case.get("expected_subclass"),
            )
        except Exception as exc:  # recorded, not raised: parity covers failures too
            payload = _error(exc)
        try:
            adherence = assess_extraction_payload(case["predicted"], case["doc_type"], doc_subclass=sub)
        except Exception as exc:
            adherence = _error(exc)
        fields, typed = _model_facts(case["doc_type"], case["predicted"])
        out[case["case_id"]] = {
            "payload": to_jsonable(payload),
            "adherence": to_jsonable(adherence),
            "model_fields": fields,
            "typed_valid": typed,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    """Capture goldens for ``--inputs`` and write them to ``--out``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(args.sandbox / "src"))
    import mailroom_sandbox  # noqa: F401  (puts the vendored trees on sys.path)
    import llm_dojo_scoring

    commit = subprocess.run(
        ["git", "-C", str(args.sandbox), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    cases = json.loads(args.inputs.read_text())["cases"]
    goldens = {
        "sandbox_commit": commit,
        "dojo_version": llm_dojo_scoring.__version__,
        "cases": capture(cases),
    }
    args.out.write_text(json.dumps(goldens, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(cases)} cases to {args.out} (sandbox {commit[:12]}, dojo {goldens['dojo_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
