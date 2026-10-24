"""The ``TraceSink`` / ``TraceSource`` protocols and a shared base class."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from ..events import ScoreEvent

__all__ = ["BaseTraceSink", "SinkTargetMissing", "TraceSink", "TraceSource"]


class SinkTargetMissing(ValueError):
    """The sink needs a trace/observation target the event does not carry."""


@runtime_checkable
class TraceSink(Protocol):
    """Anything that can receive pipeline score events."""

    name: str

    def emit(self, event: ScoreEvent) -> None:
        """Accept one event."""
        ...

    def emit_many(self, events: Sequence[ScoreEvent]) -> None:
        """Accept a batch of events."""
        ...

    def flush(self) -> None:
        """Deliver anything buffered before returning."""
        ...

    def close(self) -> None:
        """Flush and release resources."""
        ...

    def wire_name(self, metric: str) -> str:
        """Name sent on the wire for a canonical metric (identity by default)."""
        ...

    def failure_counts(self) -> dict[str, int]:
        """Per-sink emit/flush failure counters."""
        ...


@runtime_checkable
class TraceSource(Protocol):
    """Read side for sync flows. Planned (#83); no adapter implements it yet."""

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        """Return one trace as a plain dict."""
        ...

    def list_scores(self, trace_id: str | None = None,
                    name: str | None = None) -> Iterable[ScoreEvent]:
        """Yield scores, optionally filtered, with canonical metric names."""
        ...


class BaseTraceSink:
    """Default batching, identity wire names and per-instance failure counters."""

    name = "base"

    def __init__(self) -> None:
        self._failures: Counter[str] = Counter()

    def emit(self, event: ScoreEvent) -> None:  # pragma: no cover - abstract
        """Subclasses deliver one event."""
        raise NotImplementedError

    def emit_many(self, events: Sequence[ScoreEvent]) -> None:
        """Emit each event in order."""
        for event in events:
            self.emit(event)

    def flush(self) -> None:
        """Nothing buffered by default."""

    def close(self) -> None:
        """Flush on close."""
        self.flush()

    def wire_name(self, metric: str) -> str:
        """Identity: canonical names go on the wire unchanged."""
        return metric

    def failure_counts(self) -> dict[str, int]:
        """Snapshot of this sink's failure counters."""
        return dict(self._failures)
