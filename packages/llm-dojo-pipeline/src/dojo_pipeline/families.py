"""Score a primary task family by delegating to the dojo core.

The numbers come from ``llm_dojo_scoring.score_task`` unchanged. This layer
adds the family identity and checks the result against its contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_dojo_scoring import score_task

from .contracts import family_for_task, required_keys

__all__ = ["ContractViolation", "FamilyResult", "score_family"]


class ContractViolation(ValueError):
    """A strict score result is missing keys its family contract requires."""


@dataclass(frozen=True)
class FamilyResult:
    """One family score: the raw core dict plus contract bookkeeping."""

    task: str
    family: str
    metrics: dict[str, Any]
    contract_gaps: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when every contract key is present."""
        return not self.contract_gaps


def score_family(task: str, expected: Any, predicted: Any, *,
                 strict: bool = False, **kwargs: Any) -> FamilyResult:
    """Score ``task`` with the core and check it against its family contract.

    ``kwargs`` pass straight to :func:`llm_dojo_scoring.score_task`. For example,
    ``expected_subclass`` / ``predicted_subclass`` for the hierarchical family.
    """
    contract = family_for_task(task)
    metrics = score_task(task, expected, predicted, **kwargs)
    with_subclass = (kwargs.get("expected_subclass") is not None
                     and kwargs.get("predicted_subclass") is not None)
    gaps = tuple(k for k in required_keys(task, with_subclass=with_subclass)
                 if k not in metrics)
    if strict and gaps:
        raise ContractViolation(
            f"{task!r} ({contract.family}) result is missing contract keys {list(gaps)}"
        )
    return FamilyResult(task=task, family=contract.family, metrics=metrics,
                        contract_gaps=gaps)
