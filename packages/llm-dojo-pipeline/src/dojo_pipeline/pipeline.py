"""Node-level scoring for the 13-node mailroom graph plus the transcriber agents.

``NODE_TASKS`` maps graph nodes to a primary task key. A node mapped to ``None``
is not scored by a primary family yet. Extraction goes through the dojo
suites, and the review, report and archive nodes are scored locally by
consumers (see the recon notes in the #66 plan).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .events import ScoreEvent, events_from_result
from .families import FamilyResult, score_family
from .sinks import FanoutSink, TraceSink

__all__ = ["NODE_TASKS", "PipelineScorer"]

NODE_TASKS: Mapping[str, str | None] = MappingProxyType({
    "intake": None,            # get_suite("intake"): pipeline plumbing, not a family
    "classify": "docclass",
    "retry_classify": "docclass",
    "review_classify": "docclass",
    "extract": None,           # suite_for_doc_type(...).score_document (planned wrapper)
    "retry_extract": None,
    "judge_verify": None,
    "arbiter": None,
    "human_review": None,
    "boss_escalation": None,
    "compile_report": None,
    "catalog_write": None,
    "archive": None,
    # Transcriber agents (dojo suites pdf_transcriber / image_extractor).
    "pdf_transcriber": "transcription",
    "image_extractor": "transcription",
})


class PipelineScorer:
    """Score pipeline nodes and emit to any set of trace sinks."""

    def __init__(self, sinks: Iterable[TraceSink] = (), *, strict: bool = False) -> None:
        self.sink = FanoutSink(sinks)
        self.strict = strict

    def task_for(self, node: str, task: str | None = None) -> str:
        """Resolve the task key for ``node``. An explicit ``task`` wins."""
        if task:
            return task
        if node not in NODE_TASKS:
            raise KeyError(f"unknown pipeline node {node!r}; known: {sorted(NODE_TASKS)}")
        resolved = NODE_TASKS[node]
        if resolved is None:
            raise NotImplementedError(
                f"node {node!r} has no primary-family scorer yet (llm-dojo-scoring #83)"
            )
        return resolved

    def score_node(self, node: str, expected: Any, predicted: Any, *,
                   task: str | None = None, **kwargs: Any) -> FamilyResult:
        """Score one node's outputs with its primary family."""
        return score_family(self.task_for(node, task), expected, predicted,
                            strict=self.strict, **kwargs)

    def emit(self, result: FamilyResult, *, agent: str,
             metrics: tuple[str, ...] | None = None, **target: Any) -> list[ScoreEvent]:
        """Turn ``result`` into events and send them to every sink."""
        events = events_from_result(result, agent=agent, metrics=metrics, **target)
        self.sink.emit_many(events)
        return events
