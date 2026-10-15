#!/usr/bin/env python3
"""Replay a perfect prediction over the real mailroom-dataset GT and assert zero penalties.

For every ``ground_truth`` row of each split:

* parse ``gt_fields`` through the dojo Hub-metadata path,
* build a perfect prediction from the normalized GT,
* score extraction with real TP/FP/FN and assert zero FN, zero FP, zero
  spurious fills wherever events exist, plus full presence;
* for merger rows carrying ``maud_clause_labels``, assert MAUD parity:
  ``maud_question_accuracy`` / ``maud_clause_presence`` /
  ``maud_valid_class_rate`` / ``maud_category_accuracy`` all ``1.0``, and
  every expected answer is a member of its row's ``valid_classes`` (the
  "never guess" invariant).

Portable usage (from the repo root)::

    pip install -e ".[dev,catalog]"
    python scripts/verify_gt_penalties.py                      # test + train
    python scripts/verify_gt_penalties.py --split test
    python scripts/verify_gt_penalties.py --parquet-dir DIR    # offline

``--parquet-dir`` layout matches ``scripts/gen_maud_catalog.py``::

    DIR/test/test-00000-of-00001.parquet
    DIR/train/train-00000-of-00001.parquet

Exits non-zero when any penalty or MAUD parity failure is observed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATASET_REPO = "Lucius-Morningstar/mailroom-dataset"
DATASET_REVISION = "bc9eab280044befb51e19dda3071d290a8677f42"
PARQUET_TEMPLATE = "parquet/ground_truth/{split}/{split}-00000-of-00001.parquet"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llm_dojo_scoring import get_suite  # noqa: E402
from llm_dojo_scoring.content_scoring import (  # noqa: E402
    NON_EXTRACTION_KEYS,
    is_valid_maud_answer,
)
from llm_dojo_scoring.extraction_metrics import extraction_binary_metrics  # noqa: E402
from llm_dojo_scoring.gt_metadata import (  # noqa: E402
    CUAD_PRESENCE_KEY,
    is_empty_value,
    parse_gt_fields,
    scoring_gt_fields,
)

SUITE_BY_SPEC = {
    "contracts_specialist": "contracts_specialist",
    "corporate_records_specialist": "corporate_records_specialist",
    "correspondence_specialist": "correspondence_specialist",
    "insurance_claims_specialist": "insurance_claims_specialist",
}
EXTRA_KEYS = ("content_topic", "sentiment_label", "maud_clause_labels")
MAUD_PARITY_METRICS = (
    "maud_question_accuracy",
    "maud_clause_presence",
    "maud_valid_class_rate",
    "maud_category_accuracy",
)


def perfect_prediction(scoped):
    """Copy scoped GT fields, omitting CUAD presence metadata and empty values.

    Uses :func:`is_empty_value` for absence tokens; retained values are
    shared with ``scoped``, not deep-copied.
    """
    return {
        k: v
        for k, v in scoped.items()
        if k != CUAD_PRESENCE_KEY and not is_empty_value(v)
    }


def _load_split(split: str, parquet_dir: Path | None, revision: str):
    """Read a split into a DataFrame from local parquet or the Hub cache.

    ``parquet_dir`` is the ground-truth root containing
    ``<split>/<split>-00000-of-00001.parquet``. When omitted, download the
    file at ``revision`` through the Hub cache; local files ignore revision.
    A missing local file raises ``SystemExit``. Import, download, and parquet
    read errors propagate.
    """
    import pandas as pd

    if parquet_dir is not None:
        path = parquet_dir / split / f"{split}-00000-of-00001.parquet"
        if not path.exists():
            raise SystemExit(f"missing parquet for split {split!r}: {path}")
    else:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            DATASET_REPO,
            PARQUET_TEMPLATE.format(split=split),
            repo_type="dataset",
            revision=revision,
        )
    return pd.read_parquet(path)


def _maud_labels(fields):
    """Return the MAUD label dict, decoding a JSON string when needed.

    Missing labels, invalid JSON, and non-dictionary values return ``{}``.
    An existing dict is returned without copying.
    """
    labels = fields.get("maud_clause_labels")
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except json.JSONDecodeError:
            return {}
    return labels if isinstance(labels, dict) else {}


def _check_maud_labels(labels, failures, row):
    """Count invalid MAUD answers and append mismatch tuples to ``failures``.

    Each tuple contains ``(row, "maud-class-mismatch", question, answer)``;
    the answer is stringified and ``row`` is the caller's row index.
    Skip non-dictionary records, missing or empty-string answers, and absent
    or empty classes. Invalid JSON class strings are also skipped.
    Validity follows :func:`is_valid_maud_answer`, including its consideration
    alias exception; validation errors propagate.
    """
    mismatches = 0
    for question, rec in labels.items():
        if not isinstance(rec, dict):
            continue
        answer = rec.get("answer")
        classes = rec.get("valid_classes")
        if isinstance(classes, str):
            try:
                classes = json.loads(classes)
            except json.JSONDecodeError:
                classes = None
        if answer in (None, "") or not classes:
            continue
        if not is_valid_maud_answer(question, answer, classes):
            mismatches += 1
            failures.append((row, "maud-class-mismatch", question, str(answer)))
    return mismatches


def verify_split(split: str, parquet_dir: Path | None, revision: str) -> dict:
    """Replay perfect predictions for a split and return a penalty report.

    Load input as described in :func:`_load_split`. Return ``split``, overall
    ``totals``, ``per_specialist`` counts, and ``failures`` with zero-based
    row positions. Unscorable rows contribute row and MAUD class-check counts
    but skip extraction, presence, and MAUD parity checks.

    Penalties are recorded rather than raised. Unknown specialist names or
    missing required columns raise ``KeyError``; loading, GT parsing, and
    scoring errors propagate, including ``SystemExit`` for missing local
    parquet files.
    """
    df = _load_split(split, parquet_dir, revision)
    totals = {
        "rows": 0, "scored": 0, "unscorable": 0, "events": 0,
        "fn": 0, "fp": 0, "spurious": 0, "f1_fail": 0, "presence_fail": 0,
        "maud_rows": 0, "maud_parity_fail": 0, "maud_class_mismatch": 0,
    }
    failures: list[tuple] = []
    per_spec: dict[str, dict] = {}
    for i in range(len(df)):
        spec = str(df["expected_specialist"].iloc[i])
        suite = get_suite(SUITE_BY_SPEC[spec])
        fields = parse_gt_fields(df["gt_fields"].iloc[i])
        scoped = scoring_gt_fields(
            fields, field_types=suite.field_types, extra_keys=EXTRA_KEYS, drop_unmapped=True
        )
        pred = perfect_prediction(scoped)
        # Contract presence rows: predict "<Category>: <answer>" spans,
        # mirroring presence_expectations_from_cuad_labels (first scorable
        # span — placeholder-only categories are skipped by the helper).
        cuad = fields.get(CUAD_PRESENCE_KEY)
        if isinstance(cuad, dict):
            spans = []
            for category, entries in cuad.items():
                for entry in entries or []:
                    if isinstance(entry, dict):
                        text = str(entry.get("text") or "")
                        if any(ch.isalnum() for ch in text):
                            spans.append(f"{category}: {text}")
                            break
            if spans:
                pred["cuad_clauses"] = spans

        labels = _maud_labels(fields)
        if labels:
            totals["maud_rows"] += 1
            totals["maud_class_mismatch"] += _check_maud_labels(labels, failures, i)

        out = suite.score_document(fields, pred)
        totals["rows"] += 1
        stats = per_spec.setdefault(spec, {
            "rows": 0, "scored": 0, "unscorable": 0, "events": 0,
            "fn": 0, "fp": 0, "spurious": 0, "presence_fail": 0,
        })
        stats["rows"] += 1
        if out.get("status") == "unscorable":
            totals["unscorable"] += 1
            stats["unscorable"] += 1
            continue
        totals["scored"] += 1
        stats["scored"] += 1

        extraction_expected = {
            k: v for k, v in scoped.items()
            if k not in NON_EXTRACTION_KEYS and k != CUAD_PRESENCE_KEY
        }
        extraction_pred = {
            k: v for k, v in pred.items()
            if k not in NON_EXTRACTION_KEYS and k != CUAD_PRESENCE_KEY
        }
        if any(not is_empty_value(v) for v in extraction_expected.values()):
            metrics = extraction_binary_metrics(
                extraction_expected, extraction_pred, field_map=suite.field_types
            )
            for key in ("events", "fn", "fp", "spurious"):
                value = metrics["expected_events"] if key == "events" else (
                    metrics["n_spurious_fill"] if key == "spurious" else metrics[key]
                )
                totals[key] += value or 0
                stats[key] += value or 0
            if metrics["expected_events"] and metrics["extraction_f1"] != 1.0:
                totals["f1_fail"] += 1
                failures.append((
                    i, spec, "f1", metrics["extraction_f1"],
                    metrics["extraction_precision"], metrics["extraction_recall"],
                ))
        presence = out.get("extraction_category_presence")
        if presence is not None and presence < 1.0:
            totals["presence_fail"] += 1
            stats["presence_fail"] += 1
            failures.append((i, spec, "presence", presence, None, None))

        if labels:
            for metric in MAUD_PARITY_METRICS:
                value = out.get(metric)
                if value is None:
                    totals["maud_parity_fail"] += 1
                    failures.append((i, spec, f"maud-missing:{metric}", None, None, None))
                elif value < 1.0:
                    totals["maud_parity_fail"] += 1
                    failures.append((i, spec, f"maud:{metric}", value, None, None))
    return {"split": split, "totals": totals, "per_specialist": per_spec,
            "failures": failures}


def main() -> int:
    """Print replay reports for the requested splits (both by default).

    Return 1 if any report contains failures or penalty counts, otherwise 0.
    Argument parsing may raise ``SystemExit``; errors from :func:`verify_split`
    propagate rather than becoming a return code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", action="append", choices=("test", "train"),
                        help="split to verify (repeatable; default: both)")
    parser.add_argument("--parquet-dir", type=Path, default=None,
                        help="offline parquet/ground_truth tree (see module docstring)")
    parser.add_argument("--revision", default=DATASET_REVISION,
                        help=f"dataset revision (default: {DATASET_REVISION})")
    args = parser.parse_args()

    splits = args.split or ["test", "train"]
    failed = False
    for split in splits:
        report = verify_split(split, args.parquet_dir, args.revision)
        totals = report["totals"]
        print(f"=== {split} ===")
        print("TOTALS:", json.dumps(totals, indent=2))
        print("PER SPECIALIST:", json.dumps(report["per_specialist"], indent=2))
        failures = report["failures"]
        penalty_fail = any(totals[k] for k in
                           ("fn", "fp", "spurious", "f1_fail", "presence_fail",
                            "maud_parity_fail", "maud_class_mismatch"))
        if failures:
            failed = True
            print(f"FAILURES: {len(failures)} (first 10)")
            for failure in failures[:10]:
                print(" ", failure)
        if penalty_fail:
            failed = True
        else:
            print("FAILURES: none — zero FN / zero FP / zero spurious; "
                  "MAUD parity and class membership hold")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
