#!/usr/bin/env python3
"""Freeze per-field GT status for every (document type, subtype) of the corpus.

Reads the ``ground_truth`` parquet of ``Lucius-Morningstar/mailroom-dataset``
and writes ``llm_dojo_scoring/schemas/data/extraction_status.json``: for each of
the five mailroom classes and each canonical subtype, the row count and, per
field, how many rows carry it as ``populated``, ``schema_documented_absence``,
``not_applicable`` or ``pending_annotation`` (``gt_presence``), plus label-source
coverage for the CUAD / MAUD derived fields. The extraction-schema registry
(:mod:`llm_dojo_scoring.schemas.extraction_schemas`) classifies fields from it.

Usage (pyarrow is not a Dojo dependency). One command from the pinned live
dataset; ``--commit`` must be the full 40-hex SHA (a branch name moves)::

    uv run --extra dev --with pyarrow python scripts/build_extraction_status.py \\
        --from-hub --commit ccd040f6a1b6b414bdefd161cdc622b68f6dacf8 --revision v9.3

or from shards you already hold::

    uv run --extra dev --with pyarrow python scripts/build_extraction_status.py \\
        --parquet-dir path/to/parquet/ground_truth --commit <40-hex> --revision v9.3

``--check`` rebuilds in memory and exits 1 when the tracked file differs. After a
rebuild run ``scripts/render_gt_coverage.py --write`` to refresh
``docs/schemas/GT_COVERAGE.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_dojo_scoring.pipeline.sandbox_scoring import gt_categories
from llm_dojo_scoring.schemas import doc_classes
from llm_dojo_scoring.schemas.corpus import normalize_corpus_subclass
from llm_dojo_scoring.schemas.gt_metadata import (
    ANNOTATION_KEYS,
    gt_presence_map,
    is_empty_value,
    parse_gt_fields,
)

OUT_PATH = Path(__file__).resolve().parents[1] / "llm_dojo_scoring/schemas/data/extraction_status.json"
DATASET = "Lucius-Morningstar/mailroom-dataset"
#: The live classes of ``llm_dojo_scoring/schemas/doc_classes.py`` (the registry), in pipeline order.
FIVE = doc_classes.LIVE_DOC_TYPES
#: Label sources the derived fields read; their coverage is recorded per subtype.
LABEL_SOURCES = ("cuad_clause_labels", "maud_clause_labels")
#: Closed-vocabulary fields whose GT value counts are recorded per class.
VOCABULARY_FIELDS = (
    "intent", "claim_type", "coverage_determination", "record_type", "content_topic", "sentiment_label",
)
_HUB = "https://huggingface.co"
_PARQUET_ROOT = "parquet/ground_truth"
_SPLITS = ("train", "test")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_USER_AGENT = "llm-dojo-scoring-status-builder"
_CHUNK = 1 << 20


def _request(url: str) -> urllib.request.Request:
    """A GET request with a generic User-Agent."""
    return urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})


def hub_shards(commit: str, split: str, opener: Callable[..., Any] = urllib.request.urlopen) -> list[dict[str, Any]]:
    """The ``ground_truth`` parquet files of ``split`` at ``commit`` (Hub tree API), sorted by path."""
    url = f"{_HUB}/api/datasets/{DATASET}/tree/{commit}/{_PARQUET_ROOT}/{split}"
    with opener(_request(url), timeout=60) as response:
        entries = json.loads(response.read().decode("utf-8"))
    files = [e for e in entries if e.get("type") == "file" and str(e.get("path", "")).endswith(".parquet")]
    return sorted(files, key=lambda e: e["path"])


def download_ground_truth(
    commit: str, dest: Path, opener: Callable[..., Any] = urllib.request.urlopen
) -> list[Path]:
    """Download every ``ground_truth`` shard of ``commit`` into ``dest/<split>/``.

    Files come from ``/resolve/<commit>/…`` so the bytes are those of the pinned
    commit; each is checked against the Hub's LFS sha256 when the listing gives one.
    """
    written: list[Path] = []
    for split in _SPLITS:
        shards = hub_shards(commit, split, opener)
        if not shards:
            raise RuntimeError(f"no ground_truth parquet shard for split {split!r} at {commit}")
        (dest / split).mkdir(parents=True, exist_ok=True)
        for entry in shards:
            path = str(entry["path"])
            target = dest / split / path.rsplit("/", 1)[-1]
            url = f"{_HUB}/datasets/{DATASET}/resolve/{commit}/{path}"
            digest = hashlib.sha256()
            with opener(_request(url), timeout=300) as response, target.open("wb") as handle:
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    handle.write(chunk)
            expected = (entry.get("lfs") or {}).get("oid")
            if expected and digest.hexdigest() != expected:
                target.unlink()
                raise RuntimeError(f"sha256 mismatch for {path}: got {digest.hexdigest()}, Hub says {expected}")
            written.append(target)
    return written


def _rows(parquet_dir: Path) -> list[dict[str, Any]]:
    """Train + test rows of the ground_truth config."""
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = []
    for split in _SPLITS:
        paths = sorted((parquet_dir / split).glob("*.parquet"))
        if not paths:
            raise FileNotFoundError(f"no parquet shard under {parquet_dir / split}")
        for path in paths:
            table = pq.read_table(path, columns=["expected", "expected_subclass", "gt_fields"])
            rows.extend(table.to_pylist())
    return rows


def _vocabularies(doc_type: str) -> dict[str, tuple[str, ...]]:
    """The closed vocabularies the Dojo defines for ``doc_type``, by field (never restated here)."""
    from llm_dojo_scoring.schemas.corporate_record_schema import RECORD_TYPES
    from llm_dojo_scoring.schemas.corpus import CORRESPONDENCE_SENTIMENT_LABELS, CORRESPONDENCE_TOPICS
    from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS

    vocab = {
        name: tuple(tokens)
        for name, (tokens, _) in SCORED_ENUM_FIELDS.get(doc_type, {}).items()
        if name in VOCABULARY_FIELDS
    }
    if doc_type == "corporate_record":
        vocab["record_type"] = tuple(RECORD_TYPES)
    if doc_type == "correspondence":
        vocab["content_topic"] = tuple(CORRESPONDENCE_TOPICS)
        vocab["sentiment_label"] = tuple(CORRESPONDENCE_SENTIMENT_LABELS)
    return vocab


def _fold(doc_type: str, field: str, value: Any, vocabulary: tuple[str, ...]) -> str:
    """The vocabulary token ``value`` folds onto (the scorer's own folding), or ``""``."""
    from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS, canonical_label

    if field in SCORED_ENUM_FIELDS.get(doc_type, {}):
        return canonical_label(doc_type, field, value)
    key = re.sub(r"[^a-z0-9]", "", str(value).lower())
    return next((t for t in vocabulary if re.sub(r"[^a-z0-9]", "", t.lower()) == key), "")


def _vocabulary_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per class and closed-vocabulary field: GT rows per token (zeros kept) and unmatched values."""
    out: dict[str, Any] = {}
    for doc_type in FIVE:
        vocabs = _vocabularies(doc_type)
        if not vocabs:
            continue
        tally = {
            field: {"rows_with_value": 0, "values": dict.fromkeys(tokens, 0), "outside_vocabulary": Counter()}
            for field, tokens in vocabs.items()
        }
        for row in rows:
            if row["expected"] != doc_type:
                continue
            fields = parse_gt_fields(row["gt_fields"] or "{}")
            presence = gt_presence_map(fields)
            for field, tokens in vocabs.items():
                value = fields.get(field)
                if presence.get(field, "populated") != "populated" or is_empty_value(value):
                    continue
                entry = tally[field]
                entry["rows_with_value"] += 1
                token = _fold(doc_type, field, value, tokens)
                if token in entry["values"]:
                    entry["values"][token] += 1
                else:
                    entry["outside_vocabulary"][str(value)] += 1
        out[doc_type] = {
            field: {**entry, "outside_vocabulary": dict(sorted(entry["outside_vocabulary"].items()))}
            for field, entry in tally.items()
        }
    return out


def _cuad_category_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per CUAD category, contract rows whose labels carry it (``labeled``) and hold a span (``with_spans``).

    A CUAD-derived field is scored only on rows whose label universe carries its
    category (``pipeline.sandbox_scoring.field_value_ok``), so this is that field's
    own coverage; the container count says only that a row has some labels.
    """
    labeled: Counter[str] = Counter()
    with_spans: Counter[str] = Counter()
    for row in rows:
        if row["expected"] != "contract":
            continue
        raw = parse_gt_fields(row["gt_fields"] or "{}").get("cuad_clause_labels")
        for category, spans in gt_categories(raw).items():
            labeled[category] += 1
            with_spans[category] += bool(spans)
    if not labeled:
        return {}
    return {
        "contract": {
            "cuad_clause_labels": {
                c: {"labeled": labeled[c], "with_spans": with_spans[c]} for c in sorted(labeled)
            }
        }
    }


def build(rows: list[dict[str, Any]], revision: str, commit: str) -> dict[str, Any]:
    """The status document for ``rows``."""
    counts: Counter[tuple[str, str]] = Counter()
    surfaces: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    status: dict[tuple[str, str], dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        doc_type = row["expected"]
        if doc_type not in FIVE:
            continue
        subtype = normalize_corpus_subclass(doc_type, row["expected_subclass"])
        key = (doc_type, subtype)
        counts[key] += 1
        surfaces[key][str(row["expected_subclass"] or "")] += 1
        fields = parse_gt_fields(row["gt_fields"] or "{}")
        presence = gt_presence_map(fields)
        for name in sorted(set(fields) | set(presence)):
            if name in ANNOTATION_KEYS and name not in LABEL_SOURCES:
                continue
            state = presence.get(name)
            if state is None:
                state = "populated" if not is_empty_value(fields.get(name)) else "missing"
            status[key][name][state] += 1
    out: dict[str, Any] = {
        "dataset": DATASET,
        "config": "ground_truth",
        "revision": revision,
        "commit": commit,
        "rows": sum(counts.values()),
        "doc_types": {},
        "vocabulary": _vocabulary_counts(rows),
        "label_categories": _cuad_category_counts(rows),
    }
    for doc_type in FIVE:
        live_fields = set(doc_classes.field_names(doc_type))
        subtypes = {}
        for (dt, subtype), n in sorted(counts.items()):
            if dt != doc_type:
                continue
            fields = {
                name: dict(sorted(c.items()))
                for name, c in sorted(status[(dt, subtype)].items())
                # A field marked not_applicable everywhere is usually another
                # class's key carried in the union schema; it is kept only when
                # this class's live field map declares it (GT says "n/a" there).
                if set(c) != {"not_applicable"} or name in live_fields
            }
            subtypes[subtype] = {
                "rows": n,
                "surfaces": dict(sorted(surfaces[(dt, subtype)].items())),
                "fields": fields,
            }
        if subtypes:  # a class with no rows stays absent, so registry checks see the gap
            out["doc_types"][doc_type] = subtypes
    return out


def render(doc: dict[str, Any]) -> str:
    """Stable JSON text."""
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-hub", action="store_true", help="download the shards of --commit from the Hub")
    parser.add_argument("--parquet-dir", type=Path, help="directory holding train/ and test/ parquet shards")
    parser.add_argument("--revision", required=True, help="Hub tag, e.g. v9.3")
    parser.add_argument("--commit", help="Hub commit the tag points at (40-hex SHA)")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.from_hub == (args.parquet_dir is not None):
        parser.error("name exactly one source: --from-hub or --parquet-dir")
    if args.from_hub or args.commit is not None:
        if not args.commit or not _SHA_RE.fullmatch(args.commit):
            parser.error("--commit must be the full 40-hex lowercase SHA (a branch or tag name is not immutable)")
    elif args.commit is None:
        parser.error("--commit is required")
    if args.from_hub:
        with tempfile.TemporaryDirectory(prefix="gt-shards-") as tmp:
            download_ground_truth(args.commit, Path(tmp))
            rows = _rows(Path(tmp))
    else:
        rows = _rows(args.parquet_dir)
    text = render(build(rows, args.revision, args.commit))
    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != text:
            print(f"{OUT_PATH} is stale; rebuild without --check", file=sys.stderr)
            return 1
        print(f"{OUT_PATH} is current")
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
