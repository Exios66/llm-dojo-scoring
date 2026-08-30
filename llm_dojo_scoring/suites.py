"""Dedicated per-agent scoring suites.

Task bundles (``bundles``) group metrics by what an agent *does*.
Doc-type bundles (``doc_bundles``) group them by the *kind of document*.
This module is the third, consumer-facing layer: **one importable suite
per pipeline agent**, so llm-mailroom / llm-entity-extraction can do::

    from llm_dojo_scoring import get_suite, score_suite

    result = get_suite("sorter").score(expected, predicted)
    result = get_suite("insurance_claims_specialist").score(
        expected_fields, predicted_fields, doc_text=text,
    )
    result = get_suite("contract").score(...)   # doc-type alias

instead of assembling a profile + bundle + field-type map themselves.

Honesty mandate (KANBAN-067): suites only compute with functions that
already exist in this package. Type-specific scorers that are still
future work are recorded on ``ScoringSuite.honest_gap`` rather than
invented here. Enron topic/sentiment, MAUD per-question extraction,
WER/CER, field-micro extraction P/R/F1/F2, and insurance
determination-consistency now ship as real scorers. Remaining gaps
(retired court/DD, zero-row compliance, corporate_record with no
*external* extraction benchmark, CMS GT homogeneity) stay documented.
New scorers land by adding a metric to the registry and an extra on
the matching suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .bundles import Bundle, bundle_metric_names
from .field_scoring import ExtractionScoreResult, score_extraction, score_field
from .profiles import AgentProfile, DEFAULT_PROFILES, get_profile
from .registry import load_registry
from .tasks import score_task

__all__ = [
    "ScoringSuite",
    "DEFAULT_SUITES",
    "DEFAULT_FIELD_TYPES",
    "LEGACY_FULL_EXTRACTION_FIELD_TYPES",
    "SPECIALIST_DOC_TYPES",
    "DOC_TYPE_ALIASES",
    "get_suite",
    "list_suites",
    "score_suite",
    "suite_for_doc_type",
]


#: Specialist profile name → native mailroom document class.
SPECIALIST_DOC_TYPES: dict[str, str] = {
    "contracts_specialist": "contract",
    "corporate_records_specialist": "corporate_record",
    "due_diligence_specialist": "due_diligence",
    "correspondence_specialist": "correspondence",
    "compliance_specialist": "compliance_filing",
    "court_opinions_specialist": "court_opinion",
    "insurance_claims_specialist": "insurance_claim",
}

#: Doc-type lookup aliases (mailroom ``doc_type`` → specialist suite).
#: ``merger_agreement`` is a MAUD-grounded contract subtype scored by the
#: contracts specialist with the MAUD consideration catalog rebound.
DOC_TYPE_ALIASES: dict[str, str] = {
    **{doc_type: agent for agent, doc_type in SPECIALIST_DOC_TYPES.items()},
    "merger_agreement": "contracts_specialist",
}

#: Default field→scoring-type maps, mirrored from llm-mailroom
#: ``config/taxonomy.yaml`` / ``EXTRACTION_SCHEMAS`` (v0.6.0 pared product).
#: Open-ended ``key_obligations`` / ``termination_clauses`` / ``key_provisions``
#: / long ``key_points`` are retired from the live board — score CUAD/MAUD/
#: insurance checklists + the semantic trio instead. Override with
#: ``field_types=`` on ``score()``, or use
#: :data:`LEGACY_FULL_EXTRACTION_FIELD_TYPES` for historical free-text dumps.
DEFAULT_FIELD_TYPES: dict[str, dict[str, str]] = {
    "contract": {
        "document_name": "name",
        "parties": "entity_list:name",
        "effective_date": "date",
        "term_length": "free_text",
        "governing_law": "name",
        "contract_value": "money",
        "renewal_terms": "free_text",
        "cuad_family": "name",
        "merger_consideration": "name",
        "cuad_clauses": "entity_list:free_text",
        "maud_clauses": "entity_list:free_text",
    },
    "corporate_record": {
        "entity_name": "name",
        "record_type": "name",
        "effective_date": "date",
        "signatories": "entity_list:name",
        "jurisdiction": "name",
        "filing_number": "id",
        "intent": "name",
        "subject_matter": "free_text",
        "keywords": "entity_list:name",
    },
    "due_diligence": {
        "target_entity": "name",
        "diligence_type": "name",
        "material_findings": "entity_list:free_text",
        "risk_flags": "entity_list:free_text",
        "outstanding_items": "entity_list:free_text",
        "document_date": "date",
        "prepared_by": "name",
    },
    "correspondence": {
        "sender": "name",
        "recipient": "name",
        "additional_recipients": "entity_list",
        "communication_type": "name",
        "communication_date": "date",
        "demand_amount": "money",
        "action_items": "entity_list",
        "urgency": "name",
        "intent": "name",
        "subject_matter": "free_text",
        "keywords": "entity_list:name",
    },
    "compliance_filing": {
        "filing_type": "name",
        "regulatory_body": "name",
        "filing_date": "date",
        "due_date": "date",
        "entity_name": "name",
        "key_requirements": "entity_list:free_text",
        "status": "name",
        "reference_number": "id",
    },
    "court_opinion": {
        "case_name": "name",
        "court": "name",
        "date_decided": "date",
        "docket_number": "id",
        "opinion_type": "name",
        "parties": "entity_list:name",
        "holding": "free_text",
        "legal_issues": "entity_list:free_text",
        "outcome": "free_text",
        "citations": "entity_list:id",
        "authored_by": "name",
    },
    "insurance_claim": {
        "claim_number": "id",
        "policy_number": "id",
        "insurer": "name",
        "insured_party": "name",
        "claim_type": "name",
        "date_of_loss": "date",
        "date_filed": "date",
        "claimed_amount": "money",
        "adjuster": "name",
        "damages_description": "free_text",
        "coverage_determination": "name",
        "denial_reasons": "entity_list:free_text",
        "supporting_documents": "entity_list",
        "intent": "name",
        "subject_matter": "free_text",
        "keywords": "entity_list:name",
        "claim_checklist": "entity_list:free_text",
    },
    "merger_agreement": {
        "document_name": "name",
        "parties": "entity_list:name",
        "effective_date": "date",
        "term_length": "free_text",
        "governing_law": "name",
        "contract_value": "money",
        "renewal_terms": "free_text",
        "cuad_family": "name",
        "merger_consideration": "name",
        "cuad_clauses": "entity_list:free_text",
        "maud_clauses": "entity_list:free_text",
    },
}

#: Pre-v0.6.0 mailroom field maps that still score open-ended free-text
#: obligation dumps. Use only for historical rescoring — live board numbers
#: should use :data:`DEFAULT_FIELD_TYPES`.
LEGACY_FULL_EXTRACTION_FIELD_TYPES: dict[str, dict[str, str]] = {
    "contract": {
        "document_name": "name",
        "parties": "entity_list:name",
        "effective_date": "date",
        "term_length": "free_text",
        "termination_clauses": "entity_list:free_text",
        "governing_law": "name",
        "key_obligations": "entity_list:free_text",
        "contract_value": "money",
        "renewal_terms": "free_text",
        "cuad_family": "name",
        "merger_consideration": "name",
        "cuad_clauses": "entity_list:free_text",
        "maud_clauses": "entity_list:free_text",
    },
    "merger_agreement": {
        "document_name": "name",
        "parties": "entity_list:name",
        "effective_date": "date",
        "term_length": "free_text",
        "termination_clauses": "entity_list:free_text",
        "governing_law": "name",
        "key_obligations": "entity_list:free_text",
        "contract_value": "money",
        "renewal_terms": "free_text",
        "cuad_family": "name",
        "merger_consideration": "name",
        "cuad_clauses": "entity_list:free_text",
        "maud_clauses": "entity_list:free_text",
    },
    "corporate_record": {
        "entity_name": "name",
        "record_type": "name",
        "effective_date": "date",
        "key_provisions": "entity_list:free_text",
        "signatories": "entity_list:name",
        "jurisdiction": "name",
        "filing_number": "id",
    },
    "correspondence": {
        "sender": "name",
        "recipient": "name",
        "additional_recipients": "entity_list",
        "communication_type": "name",
        "communication_date": "date",
        "key_points": "entity_list",
        "demand_amount": "money",
        "action_items": "entity_list",
        "urgency": "name",
        "referenced_communications": "entity_list",
    },
}

#: Per-agent extras on top of the task-bundle surface. Only names that
#: already resolve in the registry (no invented KPIs).
_AGENT_EXTRAS: dict[str, tuple[str, ...]] = {
    "sorter": (
        "confusion_matrix",
        "failure_mode_breakdown",
        "per_class_stats",
        "bootstrap_ci",
    ),
    "sorter_reviewer": (
        "confusion_matrix",
        "per_class_stats",
        "bootstrap_ci",
    ),
    "judge": ("confidence_calibration_error",),
    "contracts_specialist": (
        "jaccard_similarity",
        "laziness_rate",
        "hallucination_rate",
        "extraction_category_presence",
        "date_mae_days",
        "money_mae_usd",
        "maud_question_accuracy",
        "maud_question_macro_accuracy",
        "maud_clause_presence",
        "maud_valid_class_rate",
    ),
    "corporate_records_specialist": (
        "date_mae_days",
        "per_field_scores",
        "hallucination_rate",
    ),
    "due_diligence_specialist": (
        "date_mae_days",
        "per_field_scores",
        "hallucination_rate",
    ),
    "correspondence_specialist": (
        "date_mae_days",
        "money_mae_usd",
        "per_field_scores",
        "hallucination_rate",
        "content_topic_accuracy",
        "content_topic_f1_macro",
        "sentiment_accuracy",
        "sentiment_f1_macro",
    ),
    "compliance_specialist": (
        "date_mae_days",
        "per_field_scores",
        "hallucination_rate",
    ),
    "court_opinions_specialist": (
        "legalbench_accuracy",
        "legalbench_macro_f1",
        "date_mae_days",
        "hallucination_rate",
    ),
    "insurance_claims_specialist": (
        "date_mae_days",
        "money_mae_usd",
        "per_field_scores",
        "hallucination_rate",
        "determination_consistency",
        "amount_exactness",
        "extraction_f2",
    ),
    "pdf_transcriber": (
        "wer",
        "cer",
        "word_accuracy",
    ),
    "image_extractor": (
        "wer",
        "cer",
        "word_accuracy",
    ),
    "intake": (
        "intake_prep_completeness",
        "intake_changed_rate",
        "intake_messy_rate",
        "intake_hyphen_unwraps",
        "intake_collapsed_blanks",
    ),
    "local_vs_api": (
        "ttft_seconds",
        "tokens_per_second",
        "tpot_seconds",
        "e2e_latency_seconds",
        "gpu_utilization",
        "kv_cache_utilization",
        "serving_kind",
        "quantization",
        "model",
        "provider",
    ),
}

#: MAUD per-question extras rebound onto ``get_suite("merger_agreement")``.
_MERGER_EXTRAS: tuple[str, ...] = (
    "maud_question_accuracy",
    "maud_question_macro_accuracy",
    "maud_clause_presence",
    "maud_valid_class_rate",
    "maud_category_accuracy",
)

#: Honest-gap notes — type-specific scorers that do NOT exist yet.
_HONEST_GAPS: dict[str, str] = {
    "insurance_claims_specialist": (
        "HONEST GAP: CMS DE-SynPUF ground truth in the published merge is "
        "homogeneous — coverage_determination is all-approved and "
        "denial_reasons is empty — so determination_consistency is "
        "degenerate (always 1.0 on GT-shaped predictions). The scorer "
        "itself now exists (approved ⇒ empty reasons; denied/partial ⇒ "
        "non-empty). Mailroom claim_type accepts Hub source-table tokens "
        "plus legacy FNOL lines; those catalogs are orthogonal and are "
        "not a KPI. adjuster is Optional (null valid for CMS rows)."
    ),
    "due_diligence_specialist": (
        "HONEST GAP: due_diligence was RETIRED from the live llm-mailroom "
        "pipeline (v0.5.0 / PR #21). The sorter emits unknown (human review) "
        "instead of extracting. This suite remains for historical traces; "
        "zero rows in Lucius-Morningstar/docclass-merged."
    ),
    "court_opinions_specialist": (
        "HONEST GAP: court_opinion was RETIRED from the live llm-mailroom "
        "pipeline (v0.5.0 / PR #21). The sorter emits unknown. LegalBench "
        "metrics still ship as the real benchmark surface."
    ),
    "corporate_records_specialist": (
        "HONEST GAP: no *external* extraction benchmark (CUAD/MAUD-grade "
        "coverage is not claimed). The published merge covers 39 "
        "corporate_record rows with record-type subclasses "
        "(articles_of_incorporation, rights_instrument, …). Suite scores "
        "typed-extraction field-micro P/R/F1/F2 plus that subclass catalog."
    ),
    "compliance_specialist": (
        "HONEST GAP: compliance_filing has zero rows in Lucius-Morningstar/"
        "docclass-merged. Hub SEC form-body inventory (10-K, 10-Q, 8-K, …) "
        "is the live subclass catalog; suite scores typed-extraction plus "
        "that inventory (no corpus-backed rows yet)."
    ),
    "local_vs_api": (
        "HONEST GAP: TTFT is None unless a first-token timestamp or explicit "
        "ttft_seconds is recorded — never inferred from e2e/n_tokens. GPU "
        "utilization, KV-cache occupancy, and GPU memory are local-only; "
        "API-key providers (OpenRouter, …) cannot supply them. Local Ollama "
        "tags without an OpenRouter price table leave estimated_cost_usd None "
        "(do not fabricate electricity)."
    ),
}

#: score() kind — routes to an existing package function.
_KIND_CLASSIFICATION = "classification"
_KIND_REVIEW = "review"
_KIND_EXTRACTION = "extraction"
_KIND_AUDIT = "audit"
_KIND_TRANSCRIPTION = "transcription"
_KIND_INTAKE = "intake"
_KIND_REPORTER = "reporter"
_KIND_COST = "cost"
_KIND_SERVING = "serving"

_COMPUTABLE_KINDS = frozenset(
    {
        _KIND_CLASSIFICATION,
        _KIND_REVIEW,
        _KIND_EXTRACTION,
        _KIND_AUDIT,
        _KIND_TRANSCRIPTION,
        _KIND_INTAKE,
        _KIND_SERVING,
    }
)


def _kind_for(profile: AgentProfile) -> str:
    if profile.name == "intake" or "prepare" in profile.tasks or "normalize" in profile.tasks:
        return _KIND_INTAKE
    if profile.name in SPECIALIST_DOC_TYPES:
        return _KIND_EXTRACTION
    if profile.name in ("sorter", "judge"):
        return _KIND_CLASSIFICATION
    if profile.name == "sorter_reviewer":
        return _KIND_REVIEW
    if (
        profile.name == "audit_agent"
        or profile.name.endswith("_auditor")
        or profile.name == "arbiter"
    ):
        return _KIND_AUDIT
    if "transcribe" in profile.tasks:
        return _KIND_TRANSCRIPTION
    if profile.name == "archivist" or "store" in profile.tasks:
        return _KIND_COST
    if profile.name == "local_vs_api" or "compare" in profile.tasks:
        return _KIND_SERVING
    return _KIND_REPORTER


def _task_key_for(profile: AgentProfile, kind: str) -> str | None:
    if profile.name == "sorter":
        return "docclass"
    if profile.name == "sorter_reviewer":
        return "docclass"
    if profile.name == "judge":
        return "multiclass"
    if profile.name == "court_opinions_specialist":
        return "court_opinion"
    if profile.name == "intake":
        return "intake"
    if kind in (_KIND_CLASSIFICATION, _KIND_REVIEW):
        return "multiclass"
    return None


@dataclass(frozen=True)
class ScoringSuite:
    """One agent's dedicated, importable scoring suite."""

    name: str
    title: str
    kind: str
    profile: AgentProfile
    doc_type: str | None = None
    field_types: dict[str, str] = field(default_factory=dict)
    extra_metrics: tuple[str, ...] = ()
    honest_gap: str | None = None
    task_key: str | None = None
    #: Canonical subclass keys for this agent's document class (empty if none).
    subclasses: tuple[str, ...] = ()
    #: Corpus GT columns that differentiate this document class.
    differentiators: tuple[str, ...] = ()
    #: True when the published docclass-merged corpus has rows of this type.
    in_corpus: bool = False
    #: True when the live llm-mailroom pipeline no longer dispatches this agent.
    retired: bool = False

    @property
    def computable(self) -> bool:
        """True when :meth:`score` can run against (expected, predicted)."""
        return self.kind in _COMPUTABLE_KINDS

    def resolve_bundle(self, *, fallback: bool = False) -> Bundle:
        return self.profile.resolve_bundle(fallback=fallback)

    def resolve_doc_bundle(
        self,
        doc_type: str | None = None,
        *,
        fallback: bool = True,
    ) -> tuple[Bundle, bool]:
        return self.profile.resolve_doc_bundle(
            doc_type or self.doc_type, fallback=fallback
        )

    def materialize_bundle(self) -> Bundle:
        """Dedicated ``agent:<name>`` bundle: task surface + extras."""
        base = self.resolve_bundle()
        names = list(base.metrics_for(self.name))
        for extra in self.extra_metrics:
            if extra not in names:
                names.append(extra)
        return Bundle(
            name=f"agent:{self.name}",
            description=self.title or f"Dedicated suite for {self.name}",
            metric_names=tuple(names),
        )

    def metric_names(self, *, max_tier: int | None = None) -> list[str]:
        """Full dedicated metric list (task bundle ∩ agent extras)."""
        names = bundle_metric_names(
            self.resolve_bundle(), agent=self.name, max_tier=max_tier
        )
        if max_tier is None:
            for extra in self.extra_metrics:
                if extra not in names:
                    names.append(extra)
        else:
            reg = load_registry()
            for extra in self.extra_metrics:
                if extra not in names and int(reg.get(extra).tier) <= max_tier:
                    names.append(extra)
        return names

    def headline_names(self) -> list[str]:
        from .pruning import headline_metrics

        return headline_metrics(self.name)

    def normalize_subclass(self, value: Any, *, doc_type: str | None = None) -> str:
        """Normalize a raw subclass into a canonical catalog.

        *doc_type* overrides the suite's bound type so the sorter can
        normalize a label once the parent class is known. Without a
        parent type the result is ``"other"`` — CUAD prefixes are not
        applied to unlabeled values.
        """
        from .corpus import normalize_corpus_subclass

        return normalize_corpus_subclass(doc_type or self.doc_type, value)

    def score(
        self,
        expected: Any,
        predicted: Any,
        *,
        doc_text: str | None = None,
        field_types: dict[str, str] | None = None,
        task: str | None = None,
        metrics: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Score this agent's outputs with the existing package functions.

        Routing:

        - **extraction** — :func:`score_extraction` with this suite's
          field-type map (override via ``field_types=``). Accepts one
          document (dicts) or a list of documents. Correspondence
          ``content_topic`` / ``sentiment_label`` and merger
          ``maud_clause_labels`` are scored as content extras (not
          extraction fields) when present on the dicts or passed as
          kwargs.
        - **classification / review** — :func:`score_task` (default task
          from the suite; override via ``task=``).
        - **audit** — field-type-aware comparison of specialist vs
          auditor output (dicts) via :func:`score_extraction`, plus a
          disagreement rate (``1 - overall_score``).
        - **transcription** — exact match + free-text token F1 + WER/CER.
        - **intake** — deterministic clerk gold vs predicted cleaned text
          or ``normalize-intake`` span payload (prep completeness, messy /
          changed flags, hyphen unwraps). LLM intake is scored against the
          same clerk.
        - **serving** (`local_vs_api`) — compare local vs API-key runs
          (:func:`llm_dojo_scoring.serving.compare_serving`). ``expected``
          is the local record(s); ``predicted`` is the API record(s).
        - **reporter / cost** — emit-only. Pass ``metrics=`` to validate
          a precomputed dict against the suite; otherwise ``TypeError``.
        """
        if metrics is not None:
            return self.validate_metrics(metrics)
        if not self.computable:
            raise TypeError(
                f"{self.name} suite is emit-only (kind={self.kind}); "
                "pass metrics={{name: value}} to validate, or emit through "
                f"Emitter using metric_names={self.metric_names()!r}"
            )
        if self.kind == _KIND_EXTRACTION:
            return self._score_extraction(
                expected, predicted, doc_text=doc_text, field_types=field_types,
                **kwargs,
            )
        if self.kind == _KIND_AUDIT:
            return self._score_audit(
                expected, predicted, doc_text=doc_text, field_types=field_types
            )
        if self.kind == _KIND_TRANSCRIPTION:
            return self._score_transcription(expected, predicted)
        if self.kind == _KIND_INTAKE:
            return self._score_intake(
                expected, predicted, raw_text=kwargs.get("raw_text")
            )
        if self.kind == _KIND_SERVING:
            from .serving import compare_serving

            return compare_serving(
                expected, predicted, quality_metric=kwargs.get("quality_metric")
            )
        task_name = task or self.task_key or "multiclass"
        if (
            self.kind in (_KIND_CLASSIFICATION, _KIND_REVIEW)
            and kwargs.get("expected_subclass") is not None
        ):
            task_name = "docclass"
        return score_task(task_name, expected, predicted, **kwargs)

    def validate_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Keep only registry-known names; unknown keys are dropped.

        Returns ``{"emitted": {name: value}, "skipped": [name, ...]}`` so
        consumers never silently invent KPIs.
        """
        reg = load_registry()
        known = set(self.metric_names()) | set(reg.names())
        emitted: dict[str, Any] = {}
        skipped: list[str] = []
        for name, value in metrics.items():
            if name not in known:
                skipped.append(name)
                continue
            emitted[name] = value
        return {"emitted": emitted, "skipped": skipped}

    def _score_extraction(
        self,
        expected: Any,
        predicted: Any,
        *,
        doc_text: str | None,
        field_types: dict[str, str] | None,
        **kwargs: Any,
    ) -> ExtractionScoreResult | list[ExtractionScoreResult] | dict[str, Any]:
        from .content_scoring import (
            peel_non_extraction_fields,
            score_correspondence_content,
            score_maud_extraction,
        )
        from .extraction_metrics import (
            extraction_binary_metrics,
            merge_extraction_counts,
            prf_bundle_keys,
        )

        ftypes = field_types or self.field_types
        doc_class = self.doc_type or self.name
        extras: dict[str, Any] = {}
        peeled_exp: list = []
        peeled_pred: list = []

        def _run(exp: Any, pred: Any, text: str | None):
            return score_extraction(doc_class, ftypes, pred, exp, doc_text=text)

        def _prf_one(exp: Any, pred: Any, result: ExtractionScoreResult) -> dict[str, Any]:
            if not isinstance(exp, dict) or not isinstance(pred, dict):
                return {}
            return extraction_binary_metrics(
                exp, pred, field_map=ftypes, doc_class=doc_class, result=result
            )

        topic_e = kwargs.get("expected_topic")
        topic_p = kwargs.get("predicted_topic")
        sent_e = kwargs.get("expected_sentiment")
        sent_p = kwargs.get("predicted_sentiment")
        maud_e = kwargs.get("expected_maud")
        maud_p = kwargs.get("predicted_maud")

        if isinstance(expected, list) and isinstance(predicted, list):
            texts: Iterable[str | None]
            if isinstance(doc_text, list):
                texts = doc_text
            else:
                texts = [doc_text] * len(expected)
            topics_e: list = []
            topics_p: list = []
            sents_e: list = []
            sents_p: list = []
            mauds_e: list = []
            mauds_p: list = []
            saw_topic = saw_sent = saw_maud = False
            for exp, pred in zip(expected, predicted):
                if isinstance(exp, dict) and isinstance(pred, dict):
                    e2, p2, payload = peel_non_extraction_fields(exp, pred)
                    peeled_exp.append(e2)
                    peeled_pred.append(p2)
                    if "content_topic" in payload:
                        saw_topic = True
                        topics_e.append(payload["content_topic"][0])
                        topics_p.append(payload["content_topic"][1])
                    if "sentiment_label" in payload:
                        saw_sent = True
                        sents_e.append(payload["sentiment_label"][0])
                        sents_p.append(payload["sentiment_label"][1])
                    if "maud" in payload:
                        saw_maud = True
                        mauds_e.append(payload["maud"][0])
                        mauds_p.append(payload["maud"][1])
                else:
                    peeled_exp.append(exp)
                    peeled_pred.append(pred)
            extraction = [
                _run(exp, pred, text)
                for exp, pred, text in zip(peeled_exp, peeled_pred, texts)
            ]
            if saw_topic and topic_e is None:
                topic_e, topic_p = topics_e, topics_p
            if saw_sent and sent_e is None:
                sent_e, sent_p = sents_e, sents_p
            if saw_maud and maud_e is None:
                maud_e, maud_p = mauds_e, mauds_p
        elif isinstance(expected, dict) and isinstance(predicted, dict):
            e2, p2, payload = peel_non_extraction_fields(expected, predicted)
            peeled_exp, peeled_pred = [e2], [p2]
            extraction = _run(e2, p2, doc_text)
            if "content_topic" in payload and topic_e is None:
                topic_e, topic_p = payload["content_topic"]
            if "sentiment_label" in payload and sent_e is None:
                sent_e, sent_p = payload["sentiment_label"]
            if "maud" in payload and maud_e is None:
                maud_e, maud_p = payload["maud"]
        else:
            extraction = _run(expected, predicted, doc_text)

        if topic_e is not None or topic_p is not None:
            extras.update(
                score_correspondence_content(
                    expected_topic=topic_e if topic_e is not None else "",
                    predicted_topic=topic_p if topic_p is not None else "",
                )
            )
        if sent_e is not None or sent_p is not None:
            extras.update(
                score_correspondence_content(
                    expected_sentiment=sent_e if sent_e is not None else "",
                    predicted_sentiment=sent_p if sent_p is not None else "",
                )
            )
        if maud_e is not None or maud_p is not None:
            maud_result = score_maud_extraction(maud_e, maud_p)
            if maud_result.get("n_questions"):
                extras.update(maud_result)

        # CUAD / claim checklist presence (mailroom v0.6.0 board path). Pass
        # presence_expectations= from Hub GT; default field is cuad_clauses.
        presence = kwargs.get("presence_expectations")
        if presence:
            from .field_scoring import score_category_presence

            pred_rows: list = []
            if peeled_pred:
                pred_rows = [p for p in peeled_pred if isinstance(p, dict)]
            elif isinstance(predicted, dict):
                pred_rows = [predicted]
            elif isinstance(predicted, list):
                pred_rows = [p for p in predicted if isinstance(p, dict)]
            if isinstance(presence, list):
                pairs = [
                    (pred, pe)
                    for pred, pe in zip(pred_rows, presence)
                    if isinstance(pe, dict) and pe
                ]
            else:
                pairs = [(pred, presence) for pred in pred_rows]
            presence_scores: list[float] = []
            presence_detail = None
            for pred, pe in pairs:
                score, detail = score_category_presence(pred, pe, ftypes)
                presence_scores.append(float(score))
                presence_detail = detail
            if presence_scores:
                extras["extraction_category_presence"] = (
                    round(sum(presence_scores) / len(presence_scores), 4)
                    if len(presence_scores) > 1
                    else presence_scores[0]
                )
                if len(presence_scores) == 1 and presence_detail is not None:
                    extras["extraction_category_presence_detail"] = presence_detail

        is_batch = isinstance(extraction, list)
        prf_payload: dict[str, Any] = {}
        if is_batch and peeled_exp:
            rows = [
                _prf_one(exp, pred, result)
                for exp, pred, result in zip(peeled_exp, peeled_pred, extraction)
                if isinstance(result, ExtractionScoreResult)
            ]
            rows = [row for row in rows if row]
            if rows:
                prf_payload = prf_bundle_keys(merge_extraction_counts(rows))
        elif isinstance(extraction, ExtractionScoreResult) and peeled_exp:
            one = _prf_one(peeled_exp[0], peeled_pred[0], extraction)
            if one:
                prf_payload = prf_bundle_keys(one)

        # Claims extras wrap the return (batch always; single-doc stays the
        # dataclass unless other extras already force a dict).
        if self.name == "insurance_claims_specialist" and peeled_exp and is_batch:
            from .claims_consistency import score_claims_extras

            claim_rows = [
                score_claims_extras(exp, pred)
                for exp, pred in zip(peeled_exp, peeled_pred)
                if isinstance(exp, dict) and isinstance(pred, dict)
            ]
            if claim_rows:
                consist = [row["determination_consistency"] for row in claim_rows]
                amounts = [
                    row["amount_exactness"]
                    for row in claim_rows
                    if row["amount_exactness"] is not None
                ]
                extras["determination_consistency"] = (
                    round(sum(consist) / len(consist), 4) if consist else None
                )
                extras["amount_exactness"] = (
                    round(sum(amounts) / len(amounts), 4) if amounts else None
                )

        if not extras and not is_batch:
            return extraction
        if not extras and is_batch:
            return {"extraction": extraction, **prf_payload}
        filtered = {
            k: v for k, v in extras.items()
            if k not in {"task", "kind", "topic", "sentiment", "per_question",
                         "per_document"}
        }
        return {"extraction": extraction, **prf_payload, **filtered, "detail": extras}

    def _score_audit(
        self,
        expected: Any,
        predicted: Any,
        *,
        doc_text: str | None,
        field_types: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Compare auditor output to specialist (or GT) output.

        ``expected`` is the reference (specialist or GT dict); ``predicted``
        is the auditor dict. Disagreement is the complement of the
        field-type-aware overall score — no new algorithm.
        """
        if not isinstance(expected, dict) or not isinstance(predicted, dict):
            raise TypeError(
                f"{self.name} audit suite.score() expects two field dicts "
                "(reference, auditor_output)"
            )
        ftypes = field_types or self.field_types
        if not ftypes:
            # Generic auditor / arbiter: treat every shared key as free_text.
            keys = set(expected) | set(predicted)
            ftypes = {k: "free_text" for k in keys if k != "confidence"}
        result = score_extraction(
            self.doc_type or "audit", ftypes, predicted, expected, doc_text=doc_text
        )
        overall = result.overall_score
        disagreement = None if overall is None else round(1.0 - overall, 4)
        return {
            "extraction": result,
            "audit_disagreement_rate": disagreement,
            "audit_resolution_rate": overall,
            "overall_score": overall,
        }

    def _score_transcription(self, expected: Any, predicted: Any) -> dict[str, Any]:
        from .asr import score_transcription
        from .classification import accuracy, exact_match

        asr = score_transcription(expected, predicted)
        if isinstance(expected, list) and isinstance(predicted, list):
            per_row = [exact_match(p, e) for e, p in zip(expected, predicted)]
            token_f1 = [
                float(score_field("free_text", p, e) or 0.0)
                for e, p in zip(expected, predicted)
            ]
            return {
                "accuracy": accuracy(expected, predicted),
                "f1_macro": round(sum(token_f1) / len(token_f1), 4) if token_f1 else 0.0,
                "wer": asr["wer"],
                "cer": asr["cer"],
                "word_accuracy": asr["word_accuracy"],
                "character_accuracy": asr["character_accuracy"],
                "n": len(per_row),
            }
        em = exact_match(predicted, expected)
        token_f1 = float(score_field("free_text", predicted, expected) or 0.0)
        return {
            "accuracy": em,
            "f1_macro": token_f1,
            "wer": asr["wer"],
            "cer": asr["cer"],
            "word_accuracy": asr["word_accuracy"],
            "character_accuracy": asr["character_accuracy"],
            "n": 1,
        }

    def _score_intake(
        self,
        expected: Any,
        predicted: Any,
        *,
        raw_text: str | None = None,
    ) -> dict[str, Any]:
        from .intake import score_intake

        return score_intake(expected, predicted, raw_text=raw_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "metrics_bundle": self.profile.metrics_bundle,
            "doc_type": self.doc_type,
            "task_key": self.task_key,
            "computable": self.computable,
            "ground_truth": self.profile.ground_truth,
            "metric_names": self.metric_names(),
            "headline_names": self.headline_names(),
            "honest_gap": self.honest_gap,
            "field_types": dict(self.field_types),
            "subclasses": list(self.subclasses),
            "differentiators": list(self.differentiators),
            "in_corpus": self.in_corpus,
            "retired": self.retired,
        }


def _suite_for_profile(profile: AgentProfile) -> ScoringSuite:
    kind = _kind_for(profile)
    doc_type = SPECIALIST_DOC_TYPES.get(profile.name) or profile.doc_bundle
    # Per-specialist auditors inherit the specialist's field types so
    # audit.score(specialist_out, auditor_out) is type-aware.
    auditor_doc = None
    if profile.name.endswith("_auditor") and profile.name != "audit_agent":
        stem = profile.name[: -len("_auditor")]
        # contract_auditor → contracts_specialist; others are 1:1.
        specialist = {
            "contract": "contracts_specialist",
            "corporate_records": "corporate_records_specialist",
            "due_diligence": "due_diligence_specialist",
            "correspondence": "correspondence_specialist",
            "compliance": "compliance_specialist",
            "court_opinions": "court_opinions_specialist",
            "insurance_claims": "insurance_claims_specialist",
        }.get(stem)
        if specialist:
            auditor_doc = SPECIALIST_DOC_TYPES[specialist]
            doc_type = auditor_doc
    field_types: dict[str, str] = {}
    if doc_type and doc_type in DEFAULT_FIELD_TYPES:
        field_types = dict(DEFAULT_FIELD_TYPES[doc_type])
    from .corpus import (
        CORPUS_DIFFERENTIATORS,
        CORPUS_DOC_TYPES,
        CORPUS_EXTRACTION_FIELDS,
        DOC_TYPE_SUBCLASSES,
    )

    # Sorter / reviewer see the full merged catalog (no single doc_type).
    subclasses: tuple[str, ...] = ()
    differentiators: tuple[str, ...] = ()
    in_corpus = False
    if doc_type:
        subclasses = DOC_TYPE_SUBCLASSES.get(doc_type, ())
        differentiators = CORPUS_DIFFERENTIATORS.get(doc_type, ())
        in_corpus = doc_type in CORPUS_DOC_TYPES
        expected_fields = CORPUS_EXTRACTION_FIELDS.get(doc_type)
        if expected_fields and set(field_types) != set(expected_fields):
            # Prefer the corpus-aligned field set; keep scoring types from
            # DEFAULT_FIELD_TYPES and default unknown keys to name.
            aligned = {}
            for key in expected_fields:
                aligned[key] = field_types.get(key) or "name"
            field_types = aligned
    elif profile.name in ("sorter", "sorter_reviewer"):
        in_corpus = True
    from .mailroom import RETIRED_AUDITORS, RETIRED_SPECIALISTS

    retired = profile.name in RETIRED_SPECIALISTS or profile.name in RETIRED_AUDITORS
    return ScoringSuite(
        name=profile.name,
        title=profile.title,
        kind=kind,
        profile=profile,
        doc_type=doc_type,
        field_types=field_types,
        extra_metrics=_AGENT_EXTRAS.get(profile.name, ()),
        honest_gap=_HONEST_GAPS.get(profile.name),
        task_key=_task_key_for(profile, kind),
        subclasses=subclasses,
        differentiators=differentiators,
        in_corpus=in_corpus,
        retired=retired,
    )


DEFAULT_SUITES: dict[str, ScoringSuite] = {
    name: _suite_for_profile(profile) for name, profile in DEFAULT_PROFILES.items()
}


def _resolve_suite_name(name: str) -> str:
    if name in DEFAULT_SUITES:
        return name
    if name.startswith("agent:"):
        stripped = name[len("agent:") :]
        if stripped in DEFAULT_SUITES:
            return stripped
    if name.startswith("doc:"):
        name = name[len("doc:") :]
    if name in DOC_TYPE_ALIASES:
        return DOC_TYPE_ALIASES[name]
    raise KeyError(
        f"unknown scoring suite {name!r}; known agents: {sorted(DEFAULT_SUITES)}; "
        f"doc-type aliases: {sorted(DOC_TYPE_ALIASES)}"
    )


def _requested_doc_type(name: str) -> str | None:
    """Return the mailroom class if *name* is a doc-type alias (incl. ``doc:``)."""
    key = name[4:] if name.startswith("doc:") else name
    return key if key in DOC_TYPE_ALIASES else None


def _rebind_for_doc_type(suite: ScoringSuite, doc_type: str) -> ScoringSuite:
    """Keep the specialist profile but bind this document class's catalogs.

    ``merger_agreement`` shares the contracts specialist (same extraction
    fields) but has a MAUD consideration subclass — not the CUAD family
    catalog. Without this rebind, ``get_suite("merger_agreement")`` would
    silently score CUAD families.
    """
    from dataclasses import replace

    from .corpus import (
        CORPUS_DIFFERENTIATORS,
        CORPUS_DOC_TYPES,
        CORPUS_EXTRACTION_FIELDS,
        DOC_TYPE_SUBCLASSES,
    )

    field_types = dict(DEFAULT_FIELD_TYPES.get(doc_type, suite.field_types))
    expected_fields = CORPUS_EXTRACTION_FIELDS.get(doc_type)
    if expected_fields and set(field_types) != set(expected_fields):
        field_types = {key: field_types.get(key) or "name" for key in expected_fields}
    honest = suite.honest_gap
    extras = suite.extra_metrics
    if doc_type == "merger_agreement":
        honest = None
        extras = tuple(dict.fromkeys((*suite.extra_metrics, *_MERGER_EXTRAS)))
    return replace(
        suite,
        doc_type=doc_type,
        field_types=field_types,
        extra_metrics=extras,
        subclasses=DOC_TYPE_SUBCLASSES.get(doc_type, ()),
        differentiators=CORPUS_DIFFERENTIATORS.get(doc_type, ()),
        in_corpus=doc_type in CORPUS_DOC_TYPES,
        honest_gap=honest,
    )


def get_suite(name: str) -> ScoringSuite:
    """Return the dedicated suite for an agent or document type.

    Accepts profile names (``sorter``), ``agent:`` prefixes, bare doc
    types (``insurance_claim``), and ``doc:`` prefixes.

    Doc-type aliases that share a specialist but have their own subclass
    catalog (today: ``merger_agreement``) are rebound so ``suite.doc_type``,
    ``suite.subclasses``, and ``suite.differentiators`` match the requested
    class — not the specialist's native class.
    """
    suite = DEFAULT_SUITES[_resolve_suite_name(name)]
    requested = _requested_doc_type(name)
    if requested and requested != suite.doc_type:
        return _rebind_for_doc_type(suite, requested)
    return suite


def list_suites(*, kind: str | None = None, live_only: bool = False) -> list[str]:
    """Sorted suite names, optionally filtered by kind and live roster."""
    names = sorted(DEFAULT_SUITES)
    if kind is not None:
        names = [n for n in names if DEFAULT_SUITES[n].kind == kind]
    if live_only:
        names = [n for n in names if not DEFAULT_SUITES[n].retired]
    return names


def suite_for_doc_type(doc_type: str) -> ScoringSuite:
    """Specialist suite for a mailroom document class."""
    try:
        return get_suite(doc_type)
    except KeyError as exc:
        raise KeyError(
            f"unknown doc type {doc_type!r}; known: {sorted(DOC_TYPE_ALIASES)}"
        ) from exc


def score_suite(
    name: str,
    expected: Any,
    predicted: Any,
    **kwargs: Any,
) -> Any:
    """Convenience: ``get_suite(name).score(expected, predicted, **kwargs)``."""
    return get_suite(name).score(expected, predicted, **kwargs)


# Touch get_profile so a typo in DEFAULT_PROFILES fails at import.
for _name in DEFAULT_SUITES:
    get_profile(_name)
