"""Document-type-aware metric bundles (KANBAN-067).

Where :data:`~llm_dojo_scoring.bundles.BUILTIN_BUNDLES` groups metrics by
TASK (classify / extract / audit / ...), ``DOC_TYPE_BUNDLES`` groups them by
the KIND OF DOCUMENT flowing through the mailroom. Same :class:`Bundle`
shape, same registry validation at load — a separate namespace so task
bundles and doc bundles can evolve independently.

Honesty mandate (KANBAN-067): a doc type gets type-specific metrics ONLY
where real, checkable scoring logic exists today. Types whose specialist
scorers are still future work say so in their description instead of
pretending. New scorers land in the matching key — the registry is the
modular extension point.

Doc-type → dataset grounding:

==================  =====================================================
doc type            corpus / benchmark grounding
==================  =====================================================
contract            CUAD v1 (via atticus) — contracteval + laziness metrics
merger_agreement    MAUD (EDA: Exios66/atticus-investigation) — MAUD-derived
                    scorers PENDING; today = contract surface + notes
correspondence      Enron email corpus (EDA:
                    Exios66/Enron-Evaluation-Environment) — demand-letter /
                    client-email scorers PENDING; today = extraction base
due_diligence       no external benchmark — synthetic samples only
corporate_record    no external benchmark — synthetic samples only
compliance_filing   no external benchmark — synthetic samples only
court_opinion       LegalBench subsets — legalbench_* metrics (real)
insurance_claim     CMS DE-SynPUF candidate corpus, EDA pending — claims
                    scorers PENDING; today = extraction base + notes
==================  =====================================================
"""

from __future__ import annotations

from .bundles import Bundle
from .registry import Registry, load_registry

__all__ = [
    "DOC_TYPE_BUNDLES",
    "DOC_TYPES",
    "get_doc_bundle",
    "list_doc_types",
    "validate_doc_bundle",
]

#: The canonical document classes, in mailroom taxonomy order (the sorter's
#: 7 labels) plus ``merger_agreement`` — the MAUD-grounded contract subtype
#: scored as its own final-output class per KANBAN-067.
DOC_TYPES: tuple[str, ...] = (
    "contract",
    "corporate_record",
    "due_diligence",
    "correspondence",
    "compliance_filing",
    "court_opinion",
    "insurance_claim",
    "merger_agreement",
)


def _doc(
    name: str,
    description: str,
    metric_names: tuple[str, ...],
    agent_overrides: dict[str, tuple[str, ...]] | None = None,
) -> Bundle:
    return Bundle(
        name=f"doc:{name}",
        description=description,
        metric_names=metric_names,
        agent_overrides=agent_overrides or {},
    )


_EXTRACTION_BASE: tuple[str, ...] = (
    "extraction_overall_score",
    "field_presence",
    "entity_list_precision",
    "entity_list_recall",
    "verified_precision",
    "completeness",
    "schema_valid",
    "parse_error",
    "success_rate",
    "estimated_cost_usd",
    "cost_per_document",
)


#: Doc-type bundles. ``name`` is conventionally prefixed ``doc:`` so a bundle
#: instance is never confused with a task bundle in logs/dashboards; lookup
#: keys in DOC_TYPE_BUNDLES are the bare doc types.
DOC_TYPE_BUNDLES: dict[str, Bundle] = {
    name: _doc(name, description, metric_names, overrides)
    for name, description, metric_names, overrides in (
        (
            "contract",
            "Contracts — CUAD-grounded; laziness/hallucination surface via "
            "contracts_specialist overrides",
            _EXTRACTION_BASE,
            {
                "contracts_specialist": (
                    "jaccard_similarity",
                    "laziness_rate",
                    "hallucination_rate",
                ),
            },
        ),
        (
            "merger_agreement",
            "Merger agreements — MAUD-grounded (EDA: "
            "Exios66/atticus-investigation). HONEST GAP: no MAUD-derived "
            "scorer exists yet; today this is the contract surface. "
            "MAUD-specific scorers (clause-category F1, amendment drift) "
            "land here when implemented.",
            _EXTRACTION_BASE,
            {
                "contracts_specialist": (
                    "jaccard_similarity",
                    "laziness_rate",
                    "hallucination_rate",
                ),
            },
        ),
        (
            "correspondence",
            "Correspondence — Enron-grounded (EDA: "
            "Exios66/Enron-Evaluation-Environment): client emails, attorney "
            "demand letters, inter-agency messaging. HONEST GAP: no "
            "demand-letter or email-thread scorer exists yet; today this is "
            "the typed-extraction base. Enron-derived scorers land here.",
            _EXTRACTION_BASE,
            {},
        ),
        (
            "due_diligence",
            "Due-diligence materials — no external benchmark (synthetic "
            "samples only); typed-extraction base",
            _EXTRACTION_BASE,
            {},
        ),
        (
            "corporate_record",
            "Corporate records — no external benchmark (synthetic samples "
            "only); typed-extraction base",
            _EXTRACTION_BASE,
            {},
        ),
        (
            "compliance_filing",
            "Compliance filings — no external benchmark (synthetic samples "
            "only); typed-extraction base. Future: deadline/date-field "
            "emphasis via field_presence weighting.",
            _EXTRACTION_BASE,
            {},
        ),
        (
            "court_opinion",
            "Court opinions — LegalBench-grounded; the one doc type with "
            "real benchmark metrics shipping today",
            _EXTRACTION_BASE,
            {
                "court_opinions_specialist": (
                    "legalbench_accuracy",
                    "legalbench_macro_f1",
                ),
            },
        ),
        (
            "insurance_claim",
            "Insurance claims — HONEST GAP: no external benchmark yet; CMS "
            "DE-SynPUF is the candidate corpus (EDA pending), so samples "
            "are synthetic-only today. Claims-specific scorers "
            "(determination-consistency, amount-exactness) land here when "
            "implemented; today this is the typed-extraction base.",
            _EXTRACTION_BASE,
            {},
        ),
    )
}


def get_doc_bundle(
    doc_type: str,
    *,
    registry: Registry | None = None,
    validate: bool = True,
) -> Bundle:
    """Return the doc-type bundle; ``KeyError`` on unknown doc types."""
    try:
        bundle = DOC_TYPE_BUNDLES[doc_type]
    except KeyError:
        raise KeyError(
            f"unknown doc type {doc_type!r}; known: {sorted(DOC_TYPE_BUNDLES)}"
        ) from None
    if validate:
        validate_doc_bundle(bundle, registry=registry)
    return bundle


def list_doc_types() -> list[str]:
    return sorted(DOC_TYPE_BUNDLES)


def validate_doc_bundle(
    bundle: Bundle,
    *,
    registry: Registry | None = None,
) -> list[str]:
    """Every metric (incl. per-agent extras) must resolve in the registry."""
    reg = registry or load_registry()
    for name in bundle.metric_names:
        reg.get(name)
    for extras in bundle.agent_overrides.values():
        for extra in extras:
            reg.get(extra)
    return list(bundle.metric_names)
