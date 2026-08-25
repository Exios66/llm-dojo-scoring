"""Metric definitions registry — the single source mapping every score name
to its tier, units, aggregation, and the agents that consume it.

The registry is ORGANIZATIONAL, not computational: every metric here maps to a
function that already exists in this package (see ``source``), or — for the
audit-agent metrics — to a definition consumed by ``llm_dojo_scoring.emitter``.
No calculation logic lives in this module.

Tiers (the dashboard discipline — everything below T1 is opt-in exploration):

- **T0 HEADLINE** — board-level. ONE number per agent on the default view.
- **T1 CORE** — "what broke yesterday?" diagnostics (P/R/F1/F2, rates, cost).
- **T2 DEEP** — root-cause investigation (confusion matrices, failure modes,
  bootstrap CIs, calibration).
- **T3 LOG** — audit trail / regression comparison only; never on dashboards.

Resolution order for a custom registry file:

1. explicit ``path`` argument to :func:`load_registry`
2. ``LLM_DOJO_SCORING_REGISTRY`` environment variable
3. the built-in :data:`DEFAULT_METRICS_YAML` (always present, always valid)

The built-in YAML embeds the full current surface: the classification/task
metrics from this package, the 37 flat Langfuse score-config names from
llm-mailroom's ``observability/scores.py`` (so consolidation is lossless),
and the two new audit-agent metrics.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Iterable

import yaml

__all__ = [
    "MetricTier",
    "MetricDef",
    "Registry",
    "DEFAULT_METRICS_YAML",
    "SPECIALIST_AGENTS",
    "AUDITOR_AGENTS",
    "CLASSIFIER_AGENTS",
    "TRANSCRIBER_AGENTS",
    "expand_agent_families",
    "load_registry",
    "get_registry",
    "clear_registry_cache",
]

# Canonical pipeline roster. Family tokens in ``applicable_agents``
# (``SPECIALISTS``, ``AUDITORS``, ``CLASSIFIERS``, ``TRANSCRIBERS``) expand
# to these tuples so a newly added specialist cannot be omitted from the
# extraction metric surface (the v0.7.0 ``insurance_claims_specialist`` gap).
SPECIALIST_AGENTS: tuple[str, ...] = (
    "contracts_specialist",
    "corporate_records_specialist",
    "due_diligence_specialist",
    "correspondence_specialist",
    "compliance_specialist",
    "court_opinions_specialist",
    "insurance_claims_specialist",
)

AUDITOR_AGENTS: tuple[str, ...] = (
    "audit_agent",
    "contract_auditor",
    "corporate_records_auditor",
    "due_diligence_auditor",
    "correspondence_auditor",
    "compliance_auditor",
    "court_opinions_auditor",
    "insurance_claims_auditor",
    "arbiter",
)

CLASSIFIER_AGENTS: tuple[str, ...] = (
    "sorter",
    "sorter_reviewer",
    "judge",
)

TRANSCRIBER_AGENTS: tuple[str, ...] = (
    "pdf_transcriber",
    "image_extractor",
)

_AGENT_FAMILIES: dict[str, tuple[str, ...]] = {
    "SPECIALISTS": SPECIALIST_AGENTS,
    "AUDITORS": AUDITOR_AGENTS,
    "CLASSIFIERS": CLASSIFIER_AGENTS,
    "TRANSCRIBERS": TRANSCRIBER_AGENTS,
}


def expand_agent_families(agents: Iterable[str]) -> tuple[str, ...]:
    """Expand roster family tokens; unknown names pass through unchanged."""
    out: list[str] = []
    seen: set[str] = set()
    for agent in agents:
        members = _AGENT_FAMILIES.get(agent, (agent,))
        for member in members:
            if member not in seen:
                seen.add(member)
                out.append(member)
    return tuple(out)

_ENV_VAR = "LLM_DOJO_SCORING_REGISTRY"


class MetricTier(IntEnum):
    """Dashboard tier. Lower = more prominent."""

    HEADLINE = 0
    CORE = 1
    DEEP = 2
    LOG = 3


_TIER_NAMES = {
    "headline": MetricTier.HEADLINE,
    "core": MetricTier.CORE,
    "deep": MetricTier.DEEP,
    "log": MetricTier.LOG,
}


@dataclass(frozen=True)
class MetricDef:
    """One metric definition. Pure metadata — no behavior."""

    name: str
    tier: MetricTier
    units: str = "float[0,1]"
    description: str = ""
    #: Agents that consume the metric; ``["ALL"]`` means every agent.
    applicable_agents: tuple[str, ...] = ("ALL",)
    #: How per-document values roll up to run level.
    aggregation: str = "mean"
    #: Dotted path of the existing function that computes it, if any.
    source: str | None = None
    #: Migration/pruning notes (aliases, consolidations, promotions).
    notes: str = ""

    def applies_to(self, agent: str) -> bool:
        return "ALL" in self.applicable_agents or agent in self.applicable_agents


@dataclass
class Registry:
    """A loaded set of metric definitions with tier/agent filtering."""

    metrics: dict[str, MetricDef] = field(default_factory=dict)

    # -- lookups -------------------------------------------------------------

    def get(self, name: str) -> MetricDef:
        try:
            return self.metrics[name]
        except KeyError:
            raise KeyError(
                f"unknown metric {name!r}; known: {sorted(self.metrics)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self.metrics)

    # -- filtering -----------------------------------------------------------

    def filter(
        self,
        *,
        max_tier: int | MetricTier | None = None,
        tier: int | MetricTier | None = None,
        agent: str | None = None,
    ) -> list[MetricDef]:
        """Metrics matching the filters, ordered by tier then name.

        ``max_tier=1`` (the common dashboard query) returns T0+T1 only;
        ``agent="sorter"`` keeps metrics whose ``applicable_agents`` include
        the agent (or declare ``ALL``).
        """
        out: list[MetricDef] = []
        for m in self.metrics.values():
            if tier is not None and m.tier != MetricTier(tier):
                continue
            if max_tier is not None and m.tier > MetricTier(max_tier):
                continue
            if agent is not None and not m.applies_to(agent):
                continue
            out.append(m)
        return sorted(out, key=lambda m: (m.tier, m.name))

    def names_for(self, *, max_tier: int | None = None, agent: str | None = None) -> list[str]:
        return [m.name for m in self.filter(max_tier=max_tier, agent=agent)]

    # -- construction ----------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Registry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Registry":
        reg = cls()
        for name, spec in (data.get("metrics") or {}).items():
            spec = dict(spec or {})
            tier_raw = str(spec.get("tier", 1)).strip().lower()
            tier = _TIER_NAMES.get(tier_raw, None)
            if tier is None:
                tier = MetricTier(int(tier_raw))
            agents = spec.get("applicable_agents") or ["ALL"]
            if isinstance(agents, str):
                agents = [agents]
            agents = expand_agent_families(agents)
            reg.metrics[name] = MetricDef(
                name=name,
                tier=tier,
                units=str(spec.get("units", "float[0,1]")),
                description=str(spec.get("description", "")),
                applicable_agents=agents,
                aggregation=str(spec.get("aggregation", "mean")),
                source=spec.get("source"),
                notes=str(spec.get("notes", "")),
            )
        return reg


# ---------------------------------------------------------------------------
# Built-in default registry
# ---------------------------------------------------------------------------

DEFAULT_METRICS_YAML = """
# llm-dojo-scoring default metric registry (KANBAN-061).
# Every entry maps to an EXISTING package function (source:) or is an
# emitter-level definition (audit metrics). Aliases of the 37 flat
# llm-mailroom SCORE_CONFIGS names are preserved as notes so the
# consolidation is lossless.

metrics:
  # ===================== T0 — HEADLINE =====================
  f1_macro:
    tier: 0
    description: "Macro-averaged F1 across classes — the universal classifier headline"
    applicable_agents: [ALL]
    aggregation: mean
    source: "classification.binary_metrics"
  accuracy:
    tier: 0
    description: "Overall exact-match accuracy"
    applicable_agents: [ALL]
    aggregation: mean
    source: "classification.accuracy"
  extraction_overall_score:
    tier: 0
    description: "Specialist headline: overall extraction score for the run"
    applicable_agents: [SPECIALISTS]
    aggregation: mean
    source: "field_scoring.score_extraction"

  # ===================== T1 — CORE =====================
  precision:
    tier: 1
    description: "Precision (TP / (TP + FP))"
    applicable_agents: [ALL]
    source: "classification.binary_metrics"
  recall:
    tier: 1
    description: "Recall (TP / (TP + FN))"
    applicable_agents: [ALL]
    source: "classification.binary_metrics"
  f2:
    tier: 1
    description: "F-beta beta=2 — recall-weighted; flags false negatives early (legal work)"
    applicable_agents: [ALL]
    source: "classification.binary_metrics"
  false_positive_rate:
    tier: 1
    description: "FP / (FP + TN)"
    applicable_agents: [ALL]
    source: "classification.binary_metrics"
  false_negative_rate:
    tier: 1
    description: "FN / (FN + TP)"
    applicable_agents: [ALL]
    source: "classification.binary_metrics"
  jaccard_similarity:
    tier: 1
    description: "Token-set Jaccard over positive spans (ContractEval method)"
    applicable_agents: [contracts_specialist, court_opinions_specialist, judge]
    source: "tasks.get_jaccard"
    notes: "Promoted to T1 per proposal section 3.1 (section 2.2 draft had T2); KANBAN-054 made ContractEval KPIs core."
  contracteval_false_no_related:
    tier: 1
    description: "Rate of 'no related clause' answers when ground truth expects content"
    applicable_agents: [contracts_specialist, judge]
    source: "tasks.contracteval_metrics"
    notes: "alias: laziness (KANBAN-054); mirrors ContractEval no_related_rate"
  laziness_rate:
    tier: 1
    description: "Laziness detector — empty/bail responses when content is expected"
    applicable_agents: [contracts_specialist, judge]
    source: "tasks.said_no_related"
    notes: "alias of contracteval_false_no_related at record level"
  field_presence:
    tier: 1
    description: "Share of expected fields populated by the model"
    applicable_agents: [SPECIALISTS]
    source: "field_scoring.score_extraction"
    notes: "mailroom alias: expected_field_presence"
  entity_list_precision:
    tier: 1
    description: "Precision over extracted list items (bipartite match)"
    applicable_agents: [SPECIALISTS]
    source: "field_scoring.score_entity_list"
  entity_list_recall:
    tier: 1
    description: "Recall over extracted list items (bipartite match)"
    applicable_agents: [SPECIALISTS]
    source: "field_scoring.score_entity_list"
  verified_precision:
    tier: 1
    description: "Precision restricted to doc-verifiable items"
    applicable_agents: [SPECIALISTS]
    source: "field_scoring.audit_list_field"
    notes: "mailroom alias: extraction_overall_verified_precision"
  schema_valid:
    tier: 1
    description: "Output parsed to the expected schema (quick health check — promoted per pruning plan)"
    applicable_agents: [ALL]
    notes: "mailroom SCORE_CONFIGS name preserved"
  parse_error:
    tier: 1
    description: "Output failed to parse (quick health check — promoted per pruning plan)"
    applicable_agents: [ALL]
    notes: "mailroom SCORE_CONFIGS name preserved"
  success_rate:
    tier: 1
    description: "Runs completing without abort/stage failure"
    applicable_agents: [ALL]
    notes: "consolidates mailroom stage_completed + run_aborted"
  completeness:
    tier: 1
    description: "Numeric completeness of the required output shape"
    applicable_agents: [ALL]
    notes: "mailroom completeness_label (CATEGORICAL) folds into this numeric score"
  classification_correct:
    tier: 1
    description: "Per-document classification correctness (strict/equiv)"
    applicable_agents: [CLASSIFIERS, boss]
    source: "classification.exact_match"
  class_correct:
    tier: 1
    description: "Per-document class correctness (mailroom pipeline pilot)"
    applicable_agents: [ALL]
    notes: "mailroom SCORE_CONFIGS name; alias of classification_correct"
  stage_correct:
    tier: 1
    description: "Per-stage correctness (mailroom pipeline pilot)"
    applicable_agents: [ALL]
    notes: "mailroom SCORE_CONFIGS name"
  extraction_correctness:
    tier: 1
    description: "Per-document extraction correctness (mailroom pilot)"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name"
  extraction_needs_judge_review:
    tier: 1
    description: "Routing signal: extraction ambiguous enough to escalate to the judge"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name"
  expected_field_presence:
    tier: 1
    description: "Share of expected fields populated"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; alias of field_presence"
  extraction_overall_verified_precision:
    tier: 1
    description: "Precision restricted to doc-verifiable items"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; alias of verified_precision"
  extraction_hallucination_rate:
    tier: 1
    description: "Share of reported values not grounded in GT or the source doc"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; complement of verified precision"
  completeness_label:
    tier: 2
    description: "Categorical completeness label (complete/partial/incomplete)"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; label form of completeness"
  extraction_correctness_label:
    tier: 2
    description: "Categorical correctness label (accurate/partial/inaccurate)"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; label form of extraction_correctness"
  estimated_cost_usd:
    tier: 1
    description: "Estimated USD cost of the call/run"
    applicable_agents: [ALL]
    units: USD
    aggregation: sum
    source: "cost.estimate_cost"
  cost_per_document:
    tier: 1
    description: "Total cost / documents processed"
    applicable_agents: [ALL]
    units: USD
    aggregation: mean
    source: "cost.estimate_for_record"
  audit_disagreement_rate:
    tier: 1
    description: "Rate where the audit pass disagrees with the specialist output"
    applicable_agents: [AUDITORS]
    notes: "NEW (KANBAN-061) — feeds KANBAN-060's contracts_audit_v0 pass; shared by every named auditor + arbiter"
  audit_resolution_rate:
    tier: 1
    description: "Rate where the specialist adopts the audit pass correction"
    applicable_agents: [AUDITORS]
    notes: "NEW (KANBAN-061); shared by every named auditor + arbiter"
  legalbench_accuracy:
    tier: 1
    description: "LegalBench binary accuracy"
    applicable_agents: [court_opinions_specialist]
    source: "tasks.legalbench_score"
    notes: "part of the legalbench_* cluster — one bundle entry, sub-fields"
  legalbench_macro_f1:
    tier: 1
    description: "LegalBench macro F1"
    applicable_agents: [court_opinions_specialist]
    source: "tasks.legalbench_score"
    notes: "legalbench_* cluster"
  date_mae_days:
    tier: 1
    units: days
    description: "Mean absolute date error in days (run-level diagnostic)"
    applicable_agents: [SPECIALISTS]
    source: "diagnostics.extraction_diagnostics"
    notes: "Existing diagnostics surface; registered so every specialist suite can emit it"
  money_mae_usd:
    tier: 1
    units: USD
    description: "Mean absolute money-field error in USD (run-level diagnostic)"
    applicable_agents: [SPECIALISTS]
    source: "diagnostics.extraction_diagnostics"
    notes: "Existing diagnostics surface; registered so money-bearing specialist suites can emit it"
  duration_mae_days:
    tier: 2
    units: days
    description: "Mean absolute duration-field error in days"
    applicable_agents: [SPECIALISTS]
    source: "diagnostics.extraction_diagnostics"

  # ===================== T2 — DEEP =====================
  confusion_matrix:
    tier: 2
    description: "Class-confusion matrix"
    applicable_agents: [CLASSIFIERS, boss]
    aggregation: none
    source: "classification.confusion_matrix"
  per_class_stats:
    tier: 2
    description: "Per-class precision/recall/support"
    applicable_agents: [CLASSIFIERS]
    aggregation: none
    source: "classification.per_class_stats"
  failure_mode_breakdown:
    tier: 2
    description: "Failure taxonomy counts (family_confusion, function_over_form, ...)"
    applicable_agents: [CLASSIFIERS]
    aggregation: none
    source: "failure_modes.summarize_failures"
  bootstrap_ci:
    tier: 2
    description: "Percentile bootstrap CI for the headline metric"
    applicable_agents: [ALL]
    aggregation: none
    source: "bootstrap.bootstrap_ci"
  confidence_calibration_error:
    tier: 2
    description: "|confidence - correctness| calibration gap"
    applicable_agents: [ALL]
    notes: "absorbs mailroom classification_confidence + extraction_confidence (raw confidences stay at T3 as inputs)"
  hallucination_rate:
    tier: 2
    description: "Rate of doc-unverifiable extracted items"
    applicable_agents: [SPECIALISTS, AUDITORS]
    source: "field_scoring.verify_list_items"
    notes: "mailroom alias: extraction_hallucination_rate"
  per_field_scores:
    tier: 2
    description: "Type-aware per-field scores (date MAE, money error, name fuzzy match)"
    applicable_agents: [SPECIALISTS]
    aggregation: none
    source: "field_scoring.score_field"
  extraction_field_score:
    tier: 2
    description: "Per-field score value (mailroom pilot detail)"
    applicable_agents: [SPECIALISTS]
    notes: "mailroom SCORE_CONFIGS name; sibling of per_field_scores"
  extraction_category_presence:
    tier: 2
    description: "Category-presence scoring result (verbatim-clause fields)"
    applicable_agents: [contracts_specialist]
    source: "field_scoring.score_category_presence"
    notes: "mailroom SCORE_CONFIGS name"
  classification_quality:
    tier: 3
    description: "Legacy numeric quality score (mailroom); superseded by structured metrics"
    applicable_agents: [sorter]
    notes: "mailroom SCORE_CONFIGS name; demoted per pruning plan"
  guardrail_triggered:
    tier: 2
    description: "Guardrail fired (interesting in aggregate, not per-document)"
    applicable_agents: [ALL]
    notes: "demoted from mailroom flat list per pruning plan"
  legalbench_calibration_error:
    tier: 2
    description: "LegalBench confidence calibration error"
    applicable_agents: [court_opinions_specialist]
    source: "tasks.legalbench_score"
    notes: "legalbench_* cluster"

  # ===================== T3 — LOG =====================
  classification_confidence:
    tier: 3
    description: "Raw classifier confidence (input to calibration)"
    applicable_agents: [CLASSIFIERS]
    notes: "merged into confidence_calibration_error per pruning plan"
  extraction_confidence:
    tier: 3
    description: "Raw extractor confidence (input to calibration)"
    applicable_agents: [SPECIALISTS]
    notes: "merged into confidence_calibration_error per pruning plan"
  judge_notes:
    tier: 3
    units: text
    description: "Free-text adjudication notes — belongs in logs, not scored metrics"
    applicable_agents: [judge]
    notes: "demoted from mailroom flat list per pruning plan"
  stage_completed:
    tier: 3
    description: "Legacy per-stage completion flag"
    applicable_agents: [ALL]
    notes: "consolidated into success_rate"
  run_aborted:
    tier: 3
    description: "Legacy abort flag"
    applicable_agents: [ALL]
    notes: "consolidated into success_rate"
  llm_call_count:
    tier: 3
    units: count
    description: "LLM calls made (cost-calc input, not performance)"
    applicable_agents: [ALL]
    aggregation: sum
    notes: "demoted per pruning plan"
  total_tokens:
    tier: 3
    units: count
    description: "Total tokens in+out"
    applicable_agents: [ALL]
    aggregation: sum
    source: "cost.tokens_summary"
  run_duration_seconds:
    tier: 3
    units: seconds
    description: "Wall-clock run duration"
    applicable_agents: [ALL]
    aggregation: mean
  classification_attempts:
    tier: 3
    units: count
    description: "Retry attempts for the classification stage"
    applicable_agents: [sorter]
    aggregation: sum
  extraction_attempts:
    tier: 3
    units: count
    description: "Retry attempts for the extraction stage"
    applicable_agents: [SPECIALISTS]
    aggregation: sum
  prompt_version:
    tier: 3
    units: tag
    description: "Prompt version used (permanent metadata tag)"
    applicable_agents: [ALL]
    aggregation: none
  model_slug:
    tier: 3
    units: tag
    description: "Model slug used"
    applicable_agents: [ALL]
    aggregation: none
  trace_id:
    tier: 3
    units: tag
    description: "Observability trace id (permanent, linked to source docs)"
    applicable_agents: [ALL]
    aggregation: none
  raw_prediction:
    tier: 3
    units: text
    description: "Per-document raw prediction (30-day retention window)"
    applicable_agents: [ALL]
    aggregation: none
  legalbench_n_questions:
    tier: 3
    units: count
    description: "LegalBench question count for the run"
    applicable_agents: [court_opinions_specialist]
    aggregation: sum
    notes: "legalbench_* cluster"
  legalbench_task:
    tier: 3
    units: tag
    description: "LegalBench task identifier"
    applicable_agents: [court_opinions_specialist]
    aggregation: none
    notes: "legalbench_* cluster"
"""

_CACHE: dict[str, Registry] = {}


def load_registry(path: str | Path | None = None) -> Registry:
    """Load a registry: explicit path > env var > built-in default."""
    resolved: str | Path | None = path or os.environ.get(_ENV_VAR)
    if resolved:
        key = str(Path(resolved).resolve())
        if key not in _CACHE:
            _CACHE[key] = Registry.from_yaml(key)
        return _CACHE[key]
    if "default" not in _CACHE:
        _CACHE["default"] = Registry.from_dict(
            yaml.safe_load(DEFAULT_METRICS_YAML)
        )
    return _CACHE["default"]


def get_registry() -> Registry:
    """Convenience accessor for the effective (default/custom) registry."""
    return load_registry()


def clear_registry_cache() -> None:
    """Drop cached registries (test isolation / config reload)."""
    _CACHE.clear()
