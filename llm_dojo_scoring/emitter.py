"""Unified score emitter — ONE routing layer for scores instead of each repo
calling observability backends directly.

Sits ON TOP of the calculation modules (nothing here computes metrics):

- :func:`register_metric` / the YAML registry define WHAT exists.
- :class:`Emitter` routes computed values to sinks: a network-free
  :class:`LocalManifestSink` (JSONL, always available) and an optional
  :class:`LangfuseSink` (no-ops when the SDK/config is absent, matching
  llm-mailroom's observability facade philosophy).

Typical consumer (llm-entity-extraction ``src/score_emitter.py``)::

    from llm_dojo_scoring.emitter import Emitter, LocalManifestSink

    emitter = Emitter(sinks=[LocalManifestSink("reports/scores.jsonl")])
    emitter.emit_score("sorter", doc_id="doc_17", metric="f1_macro", value=0.93)
    card = emitter.scorecard("sorter", run_id="run_42", min_tier=0)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Protocol

from .registry import MetricTier, Registry, load_registry


def _wire_score_name(name: str) -> str:
    """Langfuse transport name (35-char config limit aliases)."""
    from .mailroom import langfuse_score_name

    return langfuse_score_name(name)

__all__ = [
    "ScoreRecord",
    "ScoreSink",
    "LocalManifestSink",
    "LangfuseSink",
    "Emitter",
    "get_emitter",
    "reset_default_emitter",
]


@dataclass(frozen=True)
class ScoreRecord:
    """One emitted score. Plain data — JSON-serializable via ``as_dict``."""

    agent: str
    metric: str
    value: float | str | None
    doc_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "metric": self.metric,
            "value": self.value,
            "doc_id": self.doc_id,
            "run_id": self.run_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreRecord":
        known = {k: data[k] for k in ("agent", "metric", "value", "doc_id", "run_id", "metadata", "timestamp") if k in data}
        return cls(**known)


class ScoreSink(Protocol):
    """Anything that accepts records and can flush."""

    def emit(self, record: ScoreRecord) -> None: ...

    def flush(self) -> None: ...


class LocalManifestSink:
    """Append-only JSONL manifest. Network-free, always available."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(
            path
            or os.environ.get("LLM_DOJO_SCORING_MANIFEST")
            or Path.home() / ".llm_dojo" / "scores.jsonl"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: ScoreRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")

    def flush(self) -> None:  # pragma: no cover - nothing buffered
        return None

    def read_all(self) -> list[ScoreRecord]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(ScoreRecord.from_dict(json.loads(line)))
        return out


class LangfuseSink:
    """Optional Langfuse sink — silently inert when the SDK is unavailable.

    ``client`` may be any object exposing ``score(trace_id=..., name=...,
    value=..., data_type=...)``-style calls; when omitted, the constructor
    tries ``langfuse.Langfuse()`` lazily. On any failure the sink marks
    itself unavailable and ``emit`` becomes a no-op (never raises into the
    scoring path).
    """

    def __init__(self, client: Any | None = None, *, strict: bool = False) -> None:
        self._client = client
        self.available = True
        if self._client is None:
            # Credential precheck: a keyless SDK builds a silently disabled
            # client, so require explicit creds before constructing one.
            # Consumers with file-based key setups pass ``client=`` directly.
            import os

            if not (
                os.environ.get("LANGFUSE_PUBLIC_KEY")
                or os.environ.get("LANGFUSE_SECRET_KEY")
            ):
                self.available = False
                if strict:
                    raise RuntimeError("LangfuseSink: no LANGFUSE_PUBLIC_KEY/SECRET_KEY configured")
                return
            try:
                from langfuse import Langfuse  # type: ignore[import-not-found]

                self._client = Langfuse()
            except Exception:  # pragma: no cover - depends on env
                self.available = False
                if strict:
                    raise

    def emit(self, record: ScoreRecord) -> None:
        if not self.available or self._client is None:
            return
        try:
            self._client.score(
                trace_id=record.metadata.get("trace_id"),
                name=_wire_score_name(record.metric),
                value=record.value,
                data_type=record.metadata.get("data_type", "NUMERIC"),
                comment=record.metadata.get("comment"),
            )
        except Exception:  # pragma: no cover - backend hiccups never fatal
            return

    def flush(self) -> None:
        if self.available and self._client is not None:
            try:
                self._client.flush()
            except Exception:  # pragma: no cover
                return


def _aggregate(values: list[Any], mode: str) -> Any:
    if not values:
        return None
    numeric = [v for v in values if isinstance(v, (int, float))]
    if mode == "sum":
        return float(sum(numeric)) if numeric else None
    if mode == "none":
        return values[-1]
    # default: mean over numeric values
    return float(fmean(numeric)) if numeric else values[-1]


class Emitter:
    """Routes score records to sinks and answers scorecard queries."""

    def __init__(
        self,
        sinks: Iterable[ScoreSink] | None = None,
        *,
        registry: Registry | None = None,
    ) -> None:
        self.sinks: list[ScoreSink] = list(sinks) if sinks is not None else [LocalManifestSink()]
        self.registry = registry or load_registry()
        self._records: list[ScoreRecord] = []

    # -- emitting ------------------------------------------------------------

    def register_metric(self, name: str, tier: int | MetricTier, **spec: Any) -> None:
        """Register an ad-hoc metric definition (in-memory)."""
        from .registry import MetricDef

        self.registry.metrics[name] = MetricDef(
            name=name, tier=MetricTier(tier), **spec
        )

    def emit_score(
        self,
        agent_name: str,
        doc_id: str | None,
        metric_name: str,
        value: float | str | None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> ScoreRecord:
        """Validate against the registry, then fan out to every sink."""
        self.registry.get(metric_name)  # KeyError on unknown metric: fail fast
        record = ScoreRecord(
            agent=agent_name,
            metric=metric_name,
            value=value,
            doc_id=doc_id,
            run_id=run_id,
            metadata=dict(metadata or {}),
        )
        self._records.append(record)
        for sink in self.sinks:
            sink.emit(record)
        return record

    def flush(self) -> None:
        for sink in self.sinks:
            sink.flush()

    # -- queries ---------------------------------------------------------------

    def _run_records(self, agent: str, run_id: str | None) -> list[ScoreRecord]:
        return [
            r
            for r in self._records
            if r.agent == agent and (run_id is None or r.run_id == run_id)
        ]

    def get_scorecard(
        self,
        agent_name: str,
        run_id: str | None = None,
        min_tier: int | MetricTier = MetricTier.LOG,
    ) -> dict[str, Any]:
        """Aggregated per-metric scorecard for an agent (optionally one run).

        ``min_tier=1`` keeps headline+core only — the dashboard default.
        """
        max_tier = MetricTier(min_tier)
        defs = {
            m.name: m
            for m in self.registry.filter(max_tier=max_tier, agent=agent_name)
        }
        agg: dict[str, list[Any]] = {}
        for r in self._run_records(agent_name, run_id):
            if r.metric in defs:
                agg.setdefault(r.metric, []).append(r.value)
        return {
            name: _aggregate(vals, defs[name].aggregation)
            for name, vals in sorted(agg.items())
        }

    def compare_headlines(
        self,
        agent_a: str,
        agent_b: str,
        run_id_a: str | None = None,
        run_id_b: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Compare two agents/runs on their T0 headline metrics."""
        card_a = self.get_scorecard(agent_a, run_id_a, min_tier=MetricTier.HEADLINE)
        card_b = self.get_scorecard(agent_b, run_id_b, min_tier=MetricTier.HEADLINE)
        out: dict[str, dict[str, Any]] = {}
        for name in sorted(set(card_a) | set(card_b)):
            va, vb = card_a.get(name), card_b.get(name)
            delta = (
                round(vb - va, 6)
                if isinstance(va, (int, float)) and isinstance(vb, (int, float))
                else None
            )
            out[name] = {"a": va, "b": vb, "delta_b_minus_a": delta}
        return out


_DEFAULT_EMITTER: Emitter | None = None


def get_emitter() -> Emitter:
    """Process-wide default emitter (local manifest sink + registry)."""
    global _DEFAULT_EMITTER
    if _DEFAULT_EMITTER is None:
        _DEFAULT_EMITTER = Emitter()
    return _DEFAULT_EMITTER


def reset_default_emitter() -> None:
    global _DEFAULT_EMITTER
    _DEFAULT_EMITTER = None
