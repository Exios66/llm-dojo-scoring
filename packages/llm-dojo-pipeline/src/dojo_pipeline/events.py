"""The sink-neutral score event.

The core ``ScoreRecord`` keeps the trace target, data type and comment in loose
``metadata``. Here they are typed fields, so every sink reads the same shape.
``metric`` is always the canonical (long) name. Any wire alias is applied
sink-side by :meth:`TraceSink.wire_name`.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from llm_dojo_scoring.emitter import ScoreRecord

from .families import FamilyResult

__all__ = ["DataType", "ScoreEvent", "events_from_result", "infer_data_type"]

DataType = Literal["NUMERIC", "BOOLEAN", "CATEGORICAL", "TEXT"]


def infer_data_type(value: Any) -> DataType:
    """Map a Python value to a sink data type. Strings default to CATEGORICAL."""
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, (int, float)) or value is None:
        return "NUMERIC"
    return "CATEGORICAL"


@dataclass(frozen=True)
class ScoreEvent:
    """One score ready for any trace sink."""

    metric: str
    value: float | int | bool | str | None
    agent: str
    data_type: DataType = "NUMERIC"
    doc_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    observation_id: str | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable mapping of every field."""
        return asdict(self)

    def to_score_record(self) -> ScoreRecord:
        """Down-convert to the core ``ScoreRecord`` for existing dojo sinks."""
        meta = dict(self.metadata)
        for key in ("trace_id", "observation_id", "session_id", "comment"):
            if getattr(self, key) is not None:
                meta[key] = getattr(self, key)
        meta["data_type"] = self.data_type
        return ScoreRecord(agent=self.agent, metric=self.metric, value=self.value,
                           doc_id=self.doc_id, run_id=self.run_id, metadata=meta,
                           timestamp=self.timestamp)


def events_from_result(result: FamilyResult, *, agent: str,
                       metrics: tuple[str, ...] | None = None,
                       **target: Any) -> list[ScoreEvent]:
    """Flatten the scalar headline metrics of ``result`` into events.

    ``metrics`` selects which keys to emit (default: every scalar). Nested
    structures such as ``per_class`` or ``confusion`` are never emitted as
    scores. ``target`` holds ScoreEvent fields like ``trace_id`` or ``run_id``.
    """
    meta = {"task": result.task, "family": result.family, **target.pop("metadata", {})}
    keys = metrics if metrics is not None else tuple(result.metrics)
    out: list[ScoreEvent] = []
    for key in keys:
        value = result.metrics.get(key)
        if isinstance(value, (dict, list, tuple)) or key in ("task", "kind"):
            continue
        out.append(ScoreEvent(metric=key, value=value, agent=agent,
                              data_type=infer_data_type(value), metadata=meta,
                              **target))
    return out
