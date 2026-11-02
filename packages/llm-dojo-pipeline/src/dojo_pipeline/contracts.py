"""Metric contracts for the primary pipeline task families.

Each family declares the keys every result must carry for each task key.
``planned`` lists contract items the core does not emit yet. They are tracked
in #69-#72 and #83, and are reported but never treated as violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "FamilyContract",
    "CONTRACTS",
    "TASK_FAMILY",
    "family_for_task",
    "required_keys",
]

_LABEL = ("exact_match", "exact_match_ci", "macro_accuracy", "per_class",
          "confusion", "n")
_HIER = ("doc_type_accuracy", "precision_macro", "recall_macro", "f1_macro",
         "f2_macro", "per_class", "n")
_HIER_SUBCLASS = ("subclass_accuracy", "subclass_accuracy_ci", "per_subclass")
_ENRON = ("accuracy", "f1_macro", "per_class", "confusion", "n")
_WER = ("wer", "cer", "word_accuracy", "character_accuracy", "n")


@dataclass(frozen=True)
class FamilyContract:
    """Required result keys per task key for one primary family."""

    family: str
    scope: str
    required: Mapping[str, tuple[str, ...]]
    #: Extra keys required only when the second-level subclass is supplied.
    required_with_subclass: tuple[str, ...] = ()
    planned: tuple[str, ...] = ()
    suites: tuple[str, ...] = field(default_factory=tuple)

    @property
    def task_keys(self) -> tuple[str, ...]:
        """Task keys the family owns, in declaration order."""
        return tuple(self.required)


CONTRACTS: Mapping[str, FamilyContract] = MappingProxyType({
    "classification": FamilyContract(
        family="classification",
        scope="CUAD 25-family subtype, primary doc-class, generic multi-class",
        required={"subtype": _LABEL, "doc_class": _LABEL, "multiclass": _LABEL},
        planned=("subtype alias canonicalization via equivalences.normalize_subtype",),
    ),
    "hierarchical": FamilyContract(
        family="hierarchical",
        scope="Hierarchical doc_type + second-level subclass",
        required={"docclass": _HIER, "maud_docclass": _HIER},
        required_with_subclass=_HIER_SUBCLASS,
        planned=("exact_match/confusion without subclass",
                 "valid= honoured for doc_type"),
        suites=("sorter",),
    ),
    "maud": FamilyContract(
        family="maud",
        scope="MAUD consideration answers + 22 Hub questions",
        required={
            "maud_question": _LABEL,
            "maud_extraction": ("maud_question_accuracy",
                                "maud_question_macro_accuracy",
                                "per_question", "n_questions"),
        },
        planned=("maud_extraction exact_match_ci", "maud_extraction per-class",
                 "maud_extraction shared accuracy/n keys"),
        suites=("merger_agreement_specialist",),
    ),
    "correspondence": FamilyContract(
        family="correspondence",
        scope="Enron correspondence topics & sentiment",
        required={"enron_topic": _ENRON, "enron_sentiment": _ENRON},
        planned=("per-class precision/recall/f1", "drop 'error:' pseudo-label"),
        suites=("correspondence_specialist",),
    ),
    "transcription": FamilyContract(
        family="transcription",
        scope="PDF transcriber, image transcriber / OCR, transcription WER/CER",
        required={"transcription": _WER, "wer": _WER, "cer": _WER},
        planned=("per-document WER/CER", "WER/CER bootstrap CI",
                 "OCR layout / reading-order metrics"),
        suites=("pdf_transcriber", "image_extractor"),
    ),
})

#: Task key (including dojo aliases) -> family name.
TASK_FAMILY: Mapping[str, str] = MappingProxyType({
    **{k: name for name, c in CONTRACTS.items() for k in c.task_keys},
    "maud_clause": "maud",
    "content_topic": "correspondence",
    "sentiment": "correspondence",
})

_ALIAS_TARGET = {"maud_clause": "maud_extraction", "content_topic": "enron_topic",
                 "sentiment": "enron_sentiment"}


def family_for_task(task: str) -> FamilyContract:
    """Return the contract owning ``task``; non-primary keys raise ``KeyError``."""
    try:
        return CONTRACTS[TASK_FAMILY[task]]
    except KeyError:
        raise KeyError(
            f"{task!r} is not a primary pipeline task; primary keys: "
            f"{sorted(TASK_FAMILY)} (non-primary scorers live in "
            "llm_dojo_scoring.mixed_source)"
        ) from None


def required_keys(task: str, *, with_subclass: bool = False) -> tuple[str, ...]:
    """Keys a result for ``task`` must carry under its family contract."""
    contract = family_for_task(task)
    keys = contract.required[_ALIAS_TARGET.get(task, task)]
    return keys + contract.required_with_subclass if with_subclass else keys
