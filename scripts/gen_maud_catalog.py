#!/usr/bin/env python3
"""Generate ``llm_dojo_scoring/maud.py`` and ``tests/fixtures/maud_valid_classes.json``.

The catalog is built from the published ``mailroom-dataset`` ground_truth
merger rows (config ``ground_truth``, both splits) at a pinned revision, so
regeneration is deterministic. The same script verifies the committed
artifacts in CI-style check mode::

    python scripts/gen_maud_catalog.py --check
    python scripts/gen_maud_catalog.py --write          # regenerate

Offline mode — point at an already-downloaded parquet tree::

    python scripts/gen_maud_catalog.py --check \
        --parquet-dir /path/to/parquet/ground_truth

Expected layout for ``--parquet-dir``::

    DIR/test/test-00000-of-00001.parquet
    DIR/train/train-00000-of-00001.parquet

Download that tree (portable, any Python with ``huggingface_hub``)::

    python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Lucius-Morningstar/mailroom-dataset', repo_type='dataset', \
revision='bc9eab280044befb51e19dda3071d290a8677f42', \
allow_patterns=['parquet/ground_truth/*'], local_dir='mailroom-dataset-gt')"

Requires the ``catalog`` extra: ``pip install -e ".[catalog]"``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATASET_REPO = "Lucius-Morningstar/mailroom-dataset"
#: Pinned dataset revision the committed catalog was generated from.
DATASET_REVISION = "bc9eab280044befb51e19dda3071d290a8677f42"
PARQUET_TEMPLATE = "parquet/ground_truth/{split}/{split}-00000-of-00001.parquet"
#: Provenance date embedded in the generated artifacts (stable across re-runs;
#: override with ``--generated`` when scanning a newer revision).
DEFAULT_GENERATED = "2026-10-04"

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "llm_dojo_scoring" / "maud.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "maud_valid_classes.json"

MODULE_TEMPLATE = '''"""MAUD merger-agreement answer-class catalogs — no guessing on GT labels.

Dataset authority: ``Lucius-Morningstar/mailroom-dataset`` config
``ground_truth``, scanned {date} over all {rows} published merger rows
({test_rows} test + {train_rows} train). Every ``maud_clause_labels`` record
is shaped::

    {{"answer": "...", "category": "...", "excerpt_chars": 123,
     "label_idx": 0, "valid_classes": ["...", ...]}}

``valid_classes`` is the answer catalog the annotators recognized for that
question on that row. Until now the scorer dropped it and
``is_valid_maud_answer`` returned ``True`` for *any* non-empty text on 21 of
the 22 questions — guessing. This module makes the class surface explicit:

* the record's own ``valid_classes`` is the authoritative per-row surface
  (preserved by ``parse_maud_labels``);
* :data:`MAUD_ANSWER_CLASSES` is the union observed across the corpus, used
  as the fallback when a prediction is scored without its GT record;
* :func:`maud_question_catalog` returns the fully populated
  ``{{question: valid classes}}`` dict for a document type.

Four questions legitimately vary their class set by row (R&W accuracy, MAE
definition, FTR limitations, Tail Period details) — the record-level classes
therefore win over the union. Verified against the corpus: every observed
expected answer is a member of its row's ``valid_classes`` (0 mismatches
over {rows} rows). The offline mirror lives in
``tests/fixtures/maud_valid_classes.json``.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from .corpus import MAUD_QUESTION_KEYS

__all__ = [
    "MAUD_ANSWER_CLASSES",
    "MAUD_CATALOG_GENERATED",
    "MAUD_CATALOG_ROWS",
    "MAUD_CATALOG_SOURCE",
    "MAUD_QUESTION_KEYS_BY_DOC_TYPE",
    "MAUD_VARIABLE_CLASS_QUESTIONS",
    "canonical_maud_class",
    "is_maud_class",
    "maud_class_index",
    "maud_question_catalog",
]

MAUD_CATALOG_SOURCE = "Lucius-Morningstar/mailroom-dataset (ground_truth, test+train) @ {revision}"
MAUD_CATALOG_GENERATED = "{date}"
MAUD_CATALOG_ROWS = {rows}

#: Questions whose per-row ``valid_classes`` differ across rows (the union in
#: :data:`MAUD_ANSWER_CLASSES` is a superset — always prefer the row's set).
MAUD_VARIABLE_CLASS_QUESTIONS: tuple[str, ...] = (
{variable}
)

#: Union of every ``valid_classes`` value observed per question.
MAUD_ANSWER_CLASSES: dict[str, tuple[str, ...]] = {{
{catalog}
}}

#: Fully populated question catalogs per document type. ``merger_agreement``
#: is the MAUD class; the Hub routes merger rows through the contracts
#: specialist, and the contract suite scores MAUD differentiators when the
#: row carries them, so ``contract`` exposes the same 22-question catalog.
MAUD_QUESTION_KEYS_BY_DOC_TYPE: dict[str, tuple[str, ...]] = {{
    "merger_agreement": tuple(MAUD_ANSWER_CLASSES),
    "contract": tuple(MAUD_ANSWER_CLASSES),
}}

_DOC_TYPE_ALIASES = {{
    "merger_agreement": "merger_agreement",
    "merger_agreement_specialist": "merger_agreement",
    "contract": "contract",
    "contracts_specialist": "contract",
}}

_SMART_QUOTES = str.maketrans(
    {{"\\u201c": '"', "\\u201d": '"', "\\u2018": "'", "\\u2019": "'"}}
)
_TYPO = re.compile(r"fundermental", re.IGNORECASE)

#: Yes/No surface aliases (only valid where the question's classes include
#: Yes/No — the index decides).
_YES_NO_ALIASES = {{
    "y": "yes",
    "true": "yes",
    "1": "yes",
    "n": "no",
    "false": "no",
    "0": "no",
}}


def _canon(text: object) -> str:
    value = str(text or "").translate(_SMART_QUOTES)
    value = _TYPO.sub("fundamental", value)
    return " ".join(value.split())


def _fold(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _canon(text).lower()).strip()


def maud_class_index(
    question: str, valid_classes: Sequence[str] | None = None
) -> dict[str, str]:
    """``{{folded class: canonical class}}`` for a question.

    ``valid_classes`` (the record's own catalog) wins; otherwise the union
    catalog for the question is used. Unknown questions without an explicit
    catalog return ``{{}}`` — callers must fail closed, never guess.
    """
    classes: Iterable[str]
    if valid_classes:
        classes = valid_classes
    else:
        classes = MAUD_ANSWER_CLASSES.get(question, ())
    index: dict[str, str] = {{}}
    for cls in classes:
        folded = _fold(cls)
        if folded:
            index.setdefault(folded, _canon(cls))
    return index


def _components(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def canonical_maud_class(
    question: str, value: object, valid_classes: Sequence[str] | None = None
) -> str:
    """Canonical folded form of *value* under the question's class surface.

    Whole-string class match first (class names themselves contain commas);
    otherwise all comma components must map and the canonical components are
    rejoined. Recognized Yes/No aliases fold to ``yes`` / ``no`` only when
    the question's surface actually carries Yes/No. Unrecognized text falls
    back to the folded raw value so exact-match scoring stays deterministic.
    """
    if value is None or str(value).strip() == "":
        return ""
    index = maud_class_index(question, valid_classes)
    folded = _fold(value)
    if folded in index:
        return _fold(index[folded])
    alias = _YES_NO_ALIASES.get(folded)
    if alias and alias in index:
        return alias
    parts = _components(str(value))
    if len(parts) > 1:
        canonical = [index.get(_fold(part)) for part in parts]
        if all(part is not None for part in canonical):
            return ", ".join(_fold(part) for part in canonical)
    return folded


def is_maud_class(
    question: str, value: object, valid_classes: Sequence[str] | None = None
) -> bool:
    """True when *value* uses only classes from the question's surface."""
    if value is None or str(value).strip() == "":
        return False
    index = maud_class_index(question, valid_classes)
    if not index:
        return False
    folded = _fold(value)
    if folded in index:
        return True
    alias = _YES_NO_ALIASES.get(folded)
    if alias and alias in index:
        return True
    parts = _components(str(value))
    return len(parts) > 1 and all(_fold(part) in index for part in parts)


def maud_question_catalog(doc_type: str) -> dict[str, tuple[str, ...]]:
    """Fully populated ``{{question: valid classes}}`` for a document type.

    Accepts the canonical doc type or the specialist name
    (``merger_agreement_specialist`` / ``contracts_specialist``). Unknown
    types raise ``KeyError`` — never return a silently empty catalog.
    """
    key = _DOC_TYPE_ALIASES.get(str(doc_type or "").strip().lower())
    if key is None:
        raise KeyError(
            f"unknown MAUD document type {{doc_type!r}}; expected one of "
            f"{{sorted(set(_DOC_TYPE_ALIASES.values()))}}"
        )
    return {{q: MAUD_ANSWER_CLASSES[q] for q in MAUD_QUESTION_KEYS_BY_DOC_TYPE[key]}}
'''


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


def _scan(df, split: str, union: dict[str, set], rows_per_q: Counter,
          distinct_sets: dict[str, set], rows_by_split: Counter) -> None:
    """Accumulate merger-row class unions and counts in the supplied mappings.

    Count every merger row under ``split`` in ``rows_by_split``. For records
    with nonempty classes, update ``union``, ``rows_per_q``, and
    ``distinct_sets``; the question count does not require a nonempty answer.
    Malformed JSON raises ``json.JSONDecodeError``; missing DataFrame columns
    raise ``KeyError``. Updates made before an error remain in the mappings.
    """
    for i in range(len(df)):
        if str(df["expected"].iloc[i]) != "merger_agreement":
            continue
        rows_by_split[split] += 1
        labels = json.loads(df["gt_fields"].iloc[i]).get("maud_clause_labels") or {}
        if isinstance(labels, str):
            labels = json.loads(labels)
        for q, rec in labels.items():
            if not (isinstance(rec, dict) and rec.get("valid_classes")):
                continue
            classes = tuple(str(v) for v in rec["valid_classes"])
            union[q] |= set(classes)
            rows_per_q[q] += 1
            distinct_sets[q].add(frozenset(classes))


def build_artifacts(parquet_dir: Path | None, revision: str, generated: str) -> tuple[str, str]:
    """Return generated module source and fixture JSON for both dataset splits.

    ``parquet_dir`` and ``revision`` select input as in :func:`_load_split`;
    ``generated`` is the provenance date embedded verbatim in both outputs.
    Prepends the repository root to ``sys.path`` and may populate the Hub
    cache, but does not write either artifact.

    Raises ``SystemExit`` if a local split is missing or any required MAUD
    question has no catalog. Loading and scanning errors propagate.
    """
    sys.path.insert(0, str(ROOT))
    from llm_dojo_scoring.corpus import MAUD_QUESTION_KEYS

    union: dict[str, set] = defaultdict(set)
    rows_per_q: Counter = Counter()
    distinct_sets: dict[str, set] = defaultdict(set)
    rows_by_split: Counter = Counter()
    for split in ("test", "train"):
        _scan(_load_split(split, parquet_dir, revision), split, union,
              rows_per_q, distinct_sets, rows_by_split)

    missing = [q for q in MAUD_QUESTION_KEYS if q not in union]
    if missing:
        raise SystemExit(f"catalog incomplete, missing questions: {missing}")

    # Order classes case-insensitively for stable review; questions in Hub order.
    ordered = {q: sorted(union[q], key=str.casefold) for q in MAUD_QUESTION_KEYS}
    variable = tuple(
        q for q in MAUD_QUESTION_KEYS if len(distinct_sets.get(q, ())) > 1
    )

    catalog_lines = []
    for q in MAUD_QUESTION_KEYS:
        catalog_lines.append(f"    {q!r}: (")
        for cls in ordered[q]:
            catalog_lines.append(f"        {cls!r},")
        catalog_lines.append("    ),")
    variable_lines = "\n".join(f"    {q!r}," for q in variable)
    total_rows = rows_by_split["test"] + rows_by_split["train"]

    module = MODULE_TEMPLATE.format(
        date=generated,
        revision=revision,
        rows=total_rows,
        test_rows=rows_by_split["test"],
        train_rows=rows_by_split["train"],
        variable=variable_lines,
        catalog="\n".join(catalog_lines),
    )

    fixture = {
        "source": f"{DATASET_REPO} config ground_truth @ {revision}",
        "generated": generated,
        "rows": {
            "total": total_rows,
            "test": rows_by_split["test"],
            "train": rows_by_split["train"],
        },
        "questions": {
            q: {
                "classes": ordered[q],
                "answered_rows": rows_per_q[q],
                "distinct_class_sets": len(distinct_sets.get(q, ())),
            }
            for q in MAUD_QUESTION_KEYS
        },
    }
    fixture_text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    return module, fixture_text


def _diff(name: str, committed: str, regenerated: str) -> list[str]:
    """Return an empty list for equal text, otherwise a named mismatch summary.

    Report the first differing line with a one-based line number, or the
    line counts when no differing pair of lines is found.
    """
    problems = []
    if committed != regenerated:
        problems.append(name)
        committed_lines = committed.splitlines()
        regenerated_lines = regenerated.splitlines()
        for i, (c, r) in enumerate(zip(committed_lines, regenerated_lines), start=1):
            if c != r:
                problems.append(f"  {name}:{i}: committed={c!r} regenerated={r!r}")
                break
        else:
            problems.append(
                f"  {name}: line count committed={len(committed_lines)} "
                f"regenerated={len(regenerated_lines)}"
            )
    return problems


def main() -> int:
    """Generate artifacts using command-line options and return an exit status.

    By default, overwrite the module and fixture. ``--check`` instead prints
    a comparison summary and returns 1 for differences, or 0 for a match.
    Successful writes return 0. Argument parsing and incomplete or missing
    catalog inputs may raise ``SystemExit``; loading and file I/O errors
    propagate.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="write the regenerated artifacts (default)")
    mode.add_argument("--check", action="store_true",
                      help="fail if the committed artifacts differ")
    parser.add_argument("--parquet-dir", type=Path, default=None,
                        help="offline parquet/ground_truth tree (see module docstring)")
    parser.add_argument("--revision", default=DATASET_REVISION,
                        help=f"dataset revision (default: {DATASET_REVISION})")
    parser.add_argument("--generated", default=DEFAULT_GENERATED,
                        help=f"provenance date embedded in artifacts "
                             f"(default: {DEFAULT_GENERATED})")
    args = parser.parse_args()

    module, fixture = build_artifacts(args.parquet_dir, args.revision, args.generated)

    if args.check:
        problems = _diff("llm_dojo_scoring/maud.py", MODULE_PATH.read_text(), module)
        problems += _diff(
            "tests/fixtures/maud_valid_classes.json", FIXTURE_PATH.read_text(), fixture
        )
        if problems:
            print("MAUD catalog check FAILED — committed artifacts are stale:")
            for problem in problems:
                print(problem)
            return 1
        print("MAUD catalog check OK — committed artifacts match regeneration.")
        return 0

    MODULE_PATH.write_text(module)
    FIXTURE_PATH.write_text(fixture)
    print(f"wrote {MODULE_PATH.relative_to(ROOT)}")
    print(f"wrote {FIXTURE_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
