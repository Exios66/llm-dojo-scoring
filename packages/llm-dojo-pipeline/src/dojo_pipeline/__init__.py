"""Dedicated full-pipeline scoring for the Mailroom constellation (skeleton).

Built on the dojo primary tier: the classification, hierarchical, MAUD,
correspondence and transcription/OCR families, emitted through any
:class:`~dojo_pipeline.sinks.TraceSink`. Not released; tracking issue #83.
"""

from .contracts import CONTRACTS, TASK_FAMILY, FamilyContract, family_for_task, required_keys
from .events import ScoreEvent, events_from_result, infer_data_type
from .families import ContractViolation, FamilyResult, score_family
from .pipeline import NODE_TASKS, PipelineScorer

__version__ = "0.1.0.dev0"

__all__ = [
    "CONTRACTS",
    "ContractViolation",
    "FamilyContract",
    "FamilyResult",
    "NODE_TASKS",
    "PipelineScorer",
    "ScoreEvent",
    "TASK_FAMILY",
    "__version__",
    "events_from_result",
    "family_for_task",
    "infer_data_type",
    "required_keys",
    "score_family",
]
