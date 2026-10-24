"""Concrete trace-sink adapters: local manifest, Langfuse, fan-out, planned stubs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from llm_dojo_scoring.mailroom import langfuse_score_name

from ..events import ScoreEvent
from .base import BaseTraceSink, SinkTargetMissing, TraceSink

__all__ = [
    "FanoutSink",
    "LangfuseTraceSink",
    "LocalManifestTraceSink",
    "OTelTraceSink",
    "PhoenixTraceSink",
]


class LocalManifestTraceSink(BaseTraceSink):
    """Append events as JSON lines. Needs no trace target and no network."""

    name = "local_manifest"

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: ScoreEvent) -> None:
        """Write one event line."""
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.as_dict(), sort_keys=True, default=str) + "\n")

    def read_all(self) -> list[ScoreEvent]:
        """Re-load every event written so far."""
        if not self.path.exists():
            return []
        return [ScoreEvent(**json.loads(line))
                for line in self.path.read_text(encoding="utf-8").splitlines() if line]


class LangfuseTraceSink(BaseTraceSink):
    """Langfuse adapter over an injected client. This module never imports langfuse.

    Wire names go through the dojo's ``LANGFUSE_SCORE_NAME_ALIASES``, the one
    table that The-Mailroom visualizer and the mailroom score configs rely on.
    An event without ``trace_id`` raises :class:`SinkTargetMissing`. It is never
    sent unattached.
    """

    name = "langfuse"

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.client = client

    def wire_name(self, metric: str) -> str:
        """Apply the dojo Langfuse transport alias (35-char score-name limit)."""
        return langfuse_score_name(metric)

    def emit(self, event: ScoreEvent) -> None:
        """Send one score attached to its trace (and observation, when set)."""
        if not event.trace_id:
            self._failures["missing_trace_id"] += 1
            raise SinkTargetMissing(
                f"langfuse: {event.metric!r} has no trace_id; refusing an unattached score"
            )
        payload = {
            "trace_id": event.trace_id,
            "name": self.wire_name(event.metric),
            "value": event.value,
            "data_type": event.data_type,
            "comment": event.comment,
        }
        if event.observation_id:
            payload["observation_id"] = event.observation_id
        send = getattr(self.client, "create_score", None) or self.client.score
        try:
            send(**payload)
        except Exception:
            self._failures["emit"] += 1
            raise

    def flush(self) -> None:
        """Flush the client when it buffers."""
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:
                self._failures["flush"] += 1
                raise


class FanoutSink(BaseTraceSink):
    """Deliver each event to every child sink. Failures are counted, then re-raised."""

    name = "fanout"

    def __init__(self, sinks: Iterable[TraceSink]) -> None:
        super().__init__()
        self.sinks: Sequence[TraceSink] = tuple(sinks)

    def emit(self, event: ScoreEvent) -> None:
        """Emit to every child. Raise the first error after all children are tried."""
        errors: list[Exception] = []
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception as exc:  # noqa: BLE001 - collected and re-raised
                self._failures[f"{sink.name}.emit"] += 1
                errors.append(exc)
        if errors:
            raise errors[0]

    def flush(self) -> None:
        """Flush every child."""
        for sink in self.sinks:
            sink.flush()


class _PlannedSink(BaseTraceSink):
    """Placeholder for a sink that is not implemented yet."""

    def emit(self, event: ScoreEvent) -> None:
        """Raise until the adapter lands."""
        raise NotImplementedError(
            f"{self.name} trace sink is planned (llm-dojo-scoring #83), not implemented"
        )


class PhoenixTraceSink(_PlannedSink):
    """Arize Phoenix span-annotation sink (planned)."""

    name = "phoenix"


class OTelTraceSink(_PlannedSink):
    """OpenTelemetry span-event/attribute sink (planned)."""

    name = "otel"
