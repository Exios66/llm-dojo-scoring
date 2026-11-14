"""Central, importable configuration for the dojo scoring suite.

Replaces the ad-hoc per-module config accessors (``src/taxonomy.py`` +
hardcoded fallbacks in ``src/field_scoring.py`` + equivalence constants in
``agents/sorter_agent.py``) with ONE settings object that can be:

- overridden in code (``configure(...)`` / ``set_settings(...)``),
- loaded from a YAML file (``load_settings(path)``), and
- overridden per-run via the ``LLM_DOJO_SCORING_CONFIG`` env var.

All thresholds, equivalence sets, subtype lists, cost tables, and failure-mode
definitions live here so the consuming projects (llm-mailroom,
local-mailroom-sandbox) can stop redefining them.
"""

from __future__ import annotations

import math
import numbers
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .schemas.doc_classes import DOC_CLASSES, LIVE_DOC_TYPES, RETIRED_DOC_TYPES

# ---------------------------------------------------------------------------
# Contract subtypes (CUAD corpus, 25 families + "other")
# ---------------------------------------------------------------------------

CONTRACT_SUBTYPES: list[dict[str, str]] = [
    {"key": "affiliate", "label": "Affiliate Agreement", "description": "Affiliate/referral program agreements"},
    {"key": "agency", "label": "Agency Agreement", "description": "Agency representation agreements"},
    {"key": "collaboration", "label": "Collaboration / Cooperation Agreement", "description": "R&D and cooperation collaborations"},
    {"key": "co_branding", "label": "Co-Branding Agreement", "description": "Co-branded marketing/product agreements"},
    {"key": "consulting", "label": "Consulting Agreement", "description": "Consulting and advisory services"},
    {"key": "development", "label": "Development Agreement", "description": "Product/software/services development"},
    {"key": "distributor", "label": "Distributor Agreement", "description": "Distribution and resale rights"},
    {"key": "endorsement", "label": "Endorsement Agreement", "description": "Endorsements and endorsement riders"},
    {"key": "franchise", "label": "Franchise Agreement", "description": "Franchise rights and operations"},
    {"key": "hosting", "label": "Hosting Agreement", "description": "Web/application hosting services"},
    {"key": "ip", "label": "IP Agreement", "description": "Intellectual property transfer/license agreements"},
    {"key": "joint_venture", "label": "Joint Venture Agreement", "description": "Joint venture and project collaborations"},
    {"key": "license", "label": "License Agreement", "description": "Licensing of technology, content, or IP"},
    {"key": "maintenance", "label": "Maintenance Agreement", "description": "Maintenance and support services"},
    {"key": "manufacturing", "label": "Manufacturing Agreement", "description": "Manufacturing and supply of goods"},
    {"key": "marketing", "label": "Marketing Agreement", "description": "Marketing and promotion services"},
    {"key": "non_compete_no_solicit", "label": "Non-Compete / No-Solicit / Non-Disparagement Agreement", "description": "Restrictive-covenant agreements"},
    {"key": "outsourcing", "label": "Outsourcing Agreement", "description": "Business-process outsourcing"},
    {"key": "promotion", "label": "Promotion Agreement", "description": "Promotional services and campaigns"},
    {"key": "reseller", "label": "Reseller Agreement", "description": "Reseller and value-added distribution"},
    {"key": "service", "label": "Service Agreement", "description": "General professional/support services"},
    {"key": "sponsorship", "label": "Sponsorship Agreement", "description": "Sponsorship of events/content"},
    {"key": "strategic_alliance", "label": "Strategic Alliance Agreement", "description": "Strategic alliances and partnerships"},
    {"key": "supply", "label": "Supply Agreement", "description": "Supply of goods or materials"},
    {"key": "transportation", "label": "Transportation Agreement", "description": "Transportation and logistics services"},
]

CONTRACT_SUBTYPE_KEYS: list[str] = [s["key"] for s in CONTRACT_SUBTYPES]
CONTRACT_SUBTYPE_LABELS: dict[str, str] = {s["key"]: s["label"] for s in CONTRACT_SUBTYPES}

# Canonical workbook order — matches the reference Sorter workbooks exactly
# (co_branding BEFORE collaboration; the agent enum differs on those two).
PER_SUBTYPE: list[str] = [
    "affiliate", "agency", "co_branding", "collaboration", "consulting",
    "development", "distributor", "endorsement", "franchise", "hosting",
    "ip", "joint_venture", "license", "maintenance", "manufacturing",
    "marketing", "non_compete_no_solicit", "outsourcing", "promotion",
    "reseller", "service", "sponsorship", "strategic_alliance", "supply",
    "transportation",
]

SUBTYPE_UNKNOWN = "other"

# CUAD folder-name aliases -> canonical subtype key.
SUBTYPE_ALIASES: dict[str, str] = {
    "affiliate_agreements": "affiliate",
    "affiliate_agreement": "affiliate",
    "agency_agreements": "agency",
    "co_branding": "co_branding",
    "collaboration": "collaboration",
    "consulting_agreements": "consulting",
    "development": "development",
    "distributor": "distributor",
    "endorsement": "endorsement",
    "endorsement_agreement": "endorsement",
    "franchise": "franchise",
    "hosting": "hosting",
    "ip": "ip",
    "joint_venture": "joint_venture",
    "joint_venture_filing": "joint_venture",
    "license_agreements": "license",
    "maintenance": "maintenance",
    "manufacturing": "manufacturing",
    "marketing": "marketing",
    "non_compete_non_solicit": "non_compete_no_solicit",
    "outsourcing": "outsourcing",
    "promotion": "promotion",
    "reseller": "reseller",
    "service": "service",
    "sponsorship": "sponsorship",
    "strategic_alliance": "strategic_alliance",
    "supply": "supply",
    "transportation": "transportation",
}

# Semantically interchangeable contract families: a classification into ANY
# member of the same equivalence class is a correct routing decision.
SUBTYPE_EQUIVALENCES: list[frozenset[str]] = [
    frozenset({"reseller", "distributor"}),
    frozenset({"maintenance", "license"}),
    frozenset({"development", "license"}),
    frozenset({"affiliate", "joint_venture"}),
]

# Docclass (hierarchical) subclass equivalences — the doc_subclass mirror of
# SUBTYPE_EQUIVALENCES.
DOC_SUBCLASS_EQUIVALENCES: list[frozenset[str]] = [
    frozenset({"mixed_cash_stock", "mixed_cash_stock_election"}),
]

# Failure-mode taxonomy for the sorter/subtype task, with human-readable
# labels and descriptions for reports and plots.
SORTER_FAILURE_MODES: dict[str, dict[str, str]] = {
    "function_over_form": {
        "label": "Function over form",
        "description": "doc_type miss — a document whose function overrode its contract form (e.g. an SEC filing agreement).",
    },
    "other_fallback": {
        "label": "Other fallback",
        "description": "The sorter answered 'other' for a contract the corpus files under a family.",
    },
    "equivalent_family": {
        "label": "Equivalent family",
        "description": "Predicted family is a defensible equivalent of the expected one (recovered by the equivalence mapping).",
    },
    "family_confusion": {
        "label": "Family confusion",
        "description": "A genuine wrong-family pick — no equivalence, not a doc_type miss.",
    },
}

DOCCLASS_FAILURE_MODES: dict[str, dict[str, str]] = {
    "doc_type_miss": {
        "label": "Doc-type miss",
        "description": "The document's doc_type was classified incorrectly.",
    },
    "subclass_miss": {
        "label": "Subclass miss",
        "description": "doc_type correct but the subclass was misclassified.",
    },
}

# ---------------------------------------------------------------------------
# Additional document hierarchy (issue #19 / KANBAN-047) — task registries
# ---------------------------------------------------------------------------

# Full historical + live class set the scorer still understands, derived from
# ``schemas/doc_classes.py`` (edit the registry, not these lists).
# Live pipeline extracts five of these; court_opinion, due_diligence, and
# compliance_filing are RETIRED (sorter emits ``unknown``); merger_agreement
# is ``MergerAgreementExtraction``. See :mod:`llm_dojo_scoring.pipeline.mailroom`.
DOC_CLASS_KEYS: list[str] = list(DOC_CLASSES)
LIVE_DOC_CLASS_KEYS: list[str] = list(LIVE_DOC_TYPES)
# Retired classes: excluded from the classifier's valid label set. The live
# pipeline extracts five classes (``LIVE_DOC_CLASS_KEYS``); court_opinion,
# due_diligence, and compliance_filing are RETIRED (sorter emits ``unknown``,
# and llm-mailroom taxonomy.yaml no longer carries a compliance_filing class).
# merger_agreement is ``MergerAgreementExtraction``. See
# :mod:`llm_dojo_scoring.pipeline.mailroom`.
RETIRED_DOC_CLASS_KEYS: list[str] = list(RETIRED_DOC_TYPES)

# MAUD merger-agreement consideration-type subclass (expert GT dimension —
# `Type of Consideration`). Keys are the canonical snake_case form used by the
# docclass eval's `expected_subclass`; the labels are the MAUD answer surface.
MAUD_CONSIDERATION_TYPES: list[str] = [
    "all_cash", "all_stock", "mixed_cash_stock",
    "mixed_cash_stock_election", "other",
]
MAUD_CONSIDERATION_LABELS: dict[str, str] = {
    "all_cash": "All Cash",
    "all_stock": "All Stock",
    "mixed_cash_stock": "Mixed Cash & Stock",
    "mixed_cash_stock_election": "Mixed Cash & Stock (Election)",
    "other": "Other / Unspecified",
}
MAUD_CONSIDERATION_ALIASES: dict[str, str] = {
    "all cash": "all_cash", "all cash consideration": "all_cash",
    "cash": "all_cash",
    "all stock": "all_stock", "all stock consideration": "all_stock",
    "stock": "all_stock",
    "mixed cash and stock": "mixed_cash_stock",
    "mixed cash stock": "mixed_cash_stock",
    "mixed cash and stock election": "mixed_cash_stock_election",
    "mixed cash stock election": "mixed_cash_stock_election",
    "other": "other", "unspecified": "other", "none": "other",
}
# Defensible family-level reads for consideration subclasses (the docclass
# equivalence mirror of SUBTYPE_EQUIVALENCES): an election structure IS a
# mixed cash+stock deal with a per-shareholder choice.
MAUD_CONSIDERATION_EQUIVALENCES: dict[str, set[str]] = {
    "mixed_cash_stock": {"mixed_cash_stock_election"},
    "mixed_cash_stock_election": {"mixed_cash_stock"},
}

# LegalBench task-mode labels (binary Yes/No; multiclass sets pass `valid=`).
LEGALBENCH_BINARY_LABELS: tuple[str, ...] = ("yes", "no")
LEGALBENCH_YES_NO: dict[str, set[str]] = {
    "yes": {"y", "yes", "true", "1", "1.0"},
    "no": {"n", "no", "false", "0", "0.0"},
}

# Court-opinion doc class (judicial opinions and orders).
COURT_OPINION_CLASS = "court_opinion"

# ContractEval (arXiv 2508.03080) task constants — clause-level legal risk
# identification over the CUAD test split, one (contract, question) call per
# row. The paper's ``Evaluation.py`` flags a positive row's output as correct
# when every ground-truth label span is verbatim-contained in the output, and
# flags the "no related clause" answer via this exact phrase; the false-"no
# related clause" rate is computed over the paper's HARDCODED positive count
# (1,244) — reported alongside the run's own positive count.
CONTRACTEVAL_NO_RELATED_PHRASE = "no related clause"
CONTRACTEVAL_POSITIVE_DENOMINATOR = 1244

# Task-type registry: task key -> scoring kind. Unknown keys fall back to
# plain label classification.
TASK_KINDS: dict[str, str] = {
    "subtype": "subtype",
    "doc_class": "doc_class",
    "docclass": "docclass",
    "maud_docclass": "docclass",
    "maud_question": "maud_question",
    "legalbench": "legalbench",
    "multiclass": "multiclass",
    "court_opinion": "court_opinion",
    "chained": "chained",
    "contracteval": "contracteval",
    "pipeline": "pipeline",
    "document-pipeline": "pipeline",
    "enron_topic": "enron_topic",
    "content_topic": "enron_topic",
    "enron_sentiment": "enron_sentiment",
    "sentiment": "enron_sentiment",
    "maud_extraction": "maud_extraction",
    "maud_clause": "maud_extraction",
    "transcription": "transcription",
    "wer": "transcription",
    "cer": "transcription",
    "intake": "intake",
}

# ---------------------------------------------------------------------------
# Cost models (per-1M token USD, input / output) — OpenRouter list prices
# ---------------------------------------------------------------------------

DEFAULT_COST_MODELS: dict[str, tuple[float, float]] = {
    "qwen/qwen3.7-flash": (0.03, 0.13),
    "deepseek/deepseek-v4-flash": (0.05, 0.25),
    "deepseek/deepseek-v4-pro": (0.435, 0.87),
}

# Model slug -> display name (matches the reference workbooks).
DEFAULT_MODEL_DISPLAY: dict[str, str] = {
    "qwen/qwen3.7-flash": "Qwen 3.7-Flash",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
}

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class FieldScoringSettings:
    """Thresholds, embedding options, and field policies for extraction scoring."""
    ambiguous_band: tuple[float, float] = (0.5, 0.85)
    bipartite_match_threshold: float = 0.6
    embedding_enabled: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_rescue_below: float = 0.7
    presence_embedding_threshold: float = 0.7
    # Per-field-type ambiguous-band overrides. Values are one of:
    #   ("always",)   -> every field of that type escalates to the LLM judge
    #   ("never",)    -> no field of that type ever escalates
    #   (low, high)   -> half-open band check (low <= score < high)
    # Populated by configure_from_taxonomy() from the taxonomy.yaml
    # ``field_scoring.type_bands`` block; empty by default (global
    # ``ambiguous_band`` applies to every field type).
    type_bands: dict[str, tuple] = field(default_factory=dict)
    partial_gt_fields: set[str] = field(
        default_factory=lambda: {
            "parties",
            "keywords",
            "cuad_clauses",
            "maud_clauses",
            "claim_checklist",
            "action_items",
        }
    )
    containment_fields: set[str] = field(
        default_factory=lambda: {
            "governing_law",
            "term_length",
            "renewal_terms",
            "subject_matter",
        }
    )
    verification_enabled: bool = True
    verification_token_coverage: float = 0.7


MISSING_CONFIDENCE_MODES: tuple[str, ...] = ("absent", "assume_1", "assume_0")


@dataclass
class TraceKnobSettings:
    """Experimental knobs over model-emitted ``confidence`` and ``reasoning``.

    Captured for experiment logs and gates. Never mixed into
    ``overall_score`` / field-micro F1. Sweep via ``configure`` /
    ``trace_knobs:`` YAML / ``configure_from_taxonomy``.
    """

    capture_confidence: bool = True
    capture_reasoning: bool = True
    #: Drop / flag predictions below this floor (``None`` = no floor).
    confidence_min: float | None = None
    #: Half-open band ``[low, high)`` tagged ``in_band`` (``None`` = off).
    confidence_band: tuple[float, float] | None = None
    #: When True, ``reasoning.entries[]`` may route CUAD presence spans.
    reasoning_routes_presence: bool = True
    compute_calibration_error: bool = True
    #: ``absent`` leaves missing confidence as None; ``assume_1`` / ``assume_0``
    #: fill a value for gating and calibration only.
    missing_confidence: str = "absent"


@dataclass
class GroundingSettings:
    """Thresholds for unlabelled-value grounding's reviewer trust (``grounding:`` YAML block).

    Read by :mod:`llm_dojo_scoring.grounding`; never by the scoring path, so no
    value here can change a headline score. ``trust_*`` gate an agent's
    confirmations on the precision of its ``valid`` verdicts against people
    (Wilson lower bound at least ``trust_bar`` over its last ``trust_window`` paired
    checks, with at least ``trust_min_n`` of them); ``certainty_floor`` is the least
    certainty an agent's ``valid`` needs; ``spot_check_*`` size the sample of each
    agent's confirmations sent to people. Call :meth:`validate` after changing a
    value by hand (``configure`` and the YAML loader do).
    """

    trust_bar: float = 0.95
    trust_min_n: int = 50
    trust_window: int = 200
    certainty_floor: float = 0.9
    spot_check_rate: float = 0.10
    spot_check_min_per_agent: int = 20

    def coerced(self) -> "GroundingSettings":
        """A validated copy with every value coerced as the YAML block and overrides are.

        ``trust_min_n=40.0`` becomes ``40`` and ``trust_bar=1`` becomes ``1.0``; a
        non-finite, non-numeric or fractional whole-number value raises ``ValueError``.
        """
        return replace(self, **{key: _grounding_value(key, getattr(self, key))
                                for key in _GROUNDING_KEYS}).validate()

    def validate(self) -> "GroundingSettings":
        """Raise ``ValueError`` naming the first out-of-range value; return ``self``."""
        for name in ("trust_bar", "certainty_floor", "spot_check_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError(f"grounding.{name} must be a number in [0, 1], got {value!r}")
        for name in ("trust_min_n", "trust_window", "spot_check_min_per_agent"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"grounding.{name} must be a whole number >= 0, got {value!r}")
        if self.trust_min_n < 1:
            raise ValueError(f"grounding.trust_min_n must be at least 1, got {self.trust_min_n!r}")
        if self.trust_window < self.trust_min_n:
            raise ValueError(
                f"grounding.trust_window ({self.trust_window}) must be at least "
                f"grounding.trust_min_n ({self.trust_min_n})"
            )
        if self.spot_check_min_per_agent > self.trust_window:
            raise ValueError(
                f"grounding.spot_check_min_per_agent ({self.spot_check_min_per_agent}) must be at most "
                f"grounding.trust_window ({self.trust_window}): the floor is counted over that window"
            )
        return self


def _assign_grounding(settings: "Settings", validated: GroundingSettings) -> None:
    """Copy validated values onto ``settings.grounding`` in place.

    In place, like ``field_scoring`` and ``trace_knobs``, so a reference kept from
    ``get_settings().grounding`` sees the new values.
    """
    for spec in fields(GroundingSettings):
        setattr(settings.grounding, spec.name, getattr(validated, spec.name))


#: The ``grounding:`` YAML keys and how each is coerced.
_GROUNDING_KEYS: dict[str, type] = {
    "trust_bar": float,
    "trust_min_n": int,
    "trust_window": int,
    "certainty_floor": float,
    "spot_check_rate": float,
    "spot_check_min_per_agent": int,
}


@dataclass
class Settings:
    """One importable configuration for the whole suite."""

    field_scoring: FieldScoringSettings = field(default_factory=FieldScoringSettings)
    trace_knobs: TraceKnobSettings = field(default_factory=TraceKnobSettings)
    grounding: GroundingSettings = field(default_factory=GroundingSettings)
    contract_subtypes: list[dict[str, str]] = field(
        default_factory=lambda: [dict(s) for s in CONTRACT_SUBTYPES]
    )
    subtype_aliases: dict[str, str] = field(
        default_factory=lambda: dict(SUBTYPE_ALIASES)
    )
    subtype_equivalences: list[frozenset[str]] = field(
        default_factory=lambda: [frozenset(s) for s in SUBTYPE_EQUIVALENCES]
    )
    doc_subclass_equivalences: list[frozenset[str]] = field(
        default_factory=lambda: [frozenset(s) for s in DOC_SUBCLASS_EQUIVALENCES]
    )
    per_subtype: list[str] = field(default_factory=lambda: list(PER_SUBTYPE))
    cost_models: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_COST_MODELS)
    )
    # Doc-class -> {field: scoring-type} mapping, captured from the wired
    # taxonomy's ``doc_classes`` blocks by configure_from_taxonomy(). Lets
    # field_scoring.get_field_types(doc_class) resolve WITHOUT the caller
    # passing its taxonomy every time (the consuming project wires once).
    doc_class_field_types: dict[str, dict[str, str]] = field(default_factory=dict)
    model_display: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_DISPLAY)
    )

    # -- derived helpers ----------------------------------------------------

    @property
    def contract_subtype_keys(self) -> list[str]:
        """Return configured contract subtype keys in configuration order."""
        return [s["key"] for s in self.contract_subtypes]

    @property
    def subtype_unknown(self) -> str:
        """Return the canonical unknown-subtype token."""
        return SUBTYPE_UNKNOWN

    def equivalent_subtypes(self, a: str, b: str) -> bool:
        """True when two subtype keys are the same family or members of the
        same interchangeable family class."""
        a, b = str(a), str(b)
        if a == b:
            return True
        return any(a in cls and b in cls for cls in self.subtype_equivalences)

    def equivalent_doc_subclasses(self, a: str | None, b: str | None,
                                  allowed: set[str] | None = None) -> bool:
        """True when two doc_subclass keys are the same family or members of
        the same equivalence class, optionally scoped to an allowed key set."""
        if a == b:
            return True
        if a is None or b is None:
            return False
        if allowed is not None and (a not in allowed or b not in allowed):
            return False
        return any(a in cls and b in cls for cls in self.doc_subclass_equivalences)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_ENV_CONFIG_PATH = "LLM_DOJO_SCORING_CONFIG"

_SCALAR_KEYS = {
    "ambiguous_band": ("field_scoring", tuple, "ambiguous_band"),
    "bipartite_match_threshold": ("field_scoring", float, "bipartite_match_threshold"),
    "embedding_enabled": ("field_scoring", bool, "embedding_enabled"),
    "embedding_model": ("field_scoring", str, "embedding_model"),
    "embedding_rescue_below": ("field_scoring", float, "embedding_rescue_below"),
    "presence_embedding_threshold": ("field_scoring", float, "presence_embedding_threshold"),
    "verification_enabled": ("field_scoring", bool, "verification_enabled"),
    "verification_token_coverage": ("field_scoring", float, "verification_token_coverage"),
}


def _apply_dict(settings: Settings, data: dict[str, Any]) -> None:
    """Apply a raw config dict's ``field_scoring`` / ``trace_knobs`` / other blocks onto ``settings``.

    The ``grounding:`` block is coerced and validated before anything is changed, so
    a bad grounding value raises with every section untouched.
    """
    grounding = _grounding_from_block(settings.grounding, data.get("grounding"))
    fs = data.get("field_scoring") or {}
    fs_settings = settings.field_scoring
    if "ambiguous_band" in fs and isinstance(fs["ambiguous_band"], (list, tuple)) and len(fs["ambiguous_band"]) == 2:
        fs_settings.ambiguous_band = (float(fs["ambiguous_band"][0]), float(fs["ambiguous_band"][1]))
    if "bipartite_match_threshold" in fs:
        fs_settings.bipartite_match_threshold = float(fs["bipartite_match_threshold"])
    if "embedding_enabled" in fs:
        fs_settings.embedding_enabled = bool(fs["embedding_enabled"])
    if "embedding_model" in fs:
        fs_settings.embedding_model = str(fs["embedding_model"])
    if "embedding_rescue_below" in fs:
        fs_settings.embedding_rescue_below = float(fs["embedding_rescue_below"])
    if "presence_embedding_threshold" in fs:
        fs_settings.presence_embedding_threshold = float(fs["presence_embedding_threshold"])
    if "partial_gt_fields" in fs:
        fs_settings.partial_gt_fields = {str(f) for f in (fs["partial_gt_fields"] or [])}
    if "containment_fields" in fs:
        fs_settings.containment_fields = {str(f) for f in (fs["containment_fields"] or [])}
    if "factuality_verification" in fs:
        fv = fs["factuality_verification"] or {}
        if "enabled" in fv:
            fs_settings.verification_enabled = bool(fv["enabled"])
        if "token_coverage" in fv:
            fs_settings.verification_token_coverage = float(fv["token_coverage"])

    if "type_bands" in fs:
        fs_settings.type_bands = _coerce_type_bands(fs["type_bands"])

    tk = data.get("trace_knobs") or {}
    if tk:
        _apply_trace_knobs(settings.trace_knobs, tk)

    if "subtype_equivalences" in data:
        settings.subtype_equivalences = [
            frozenset(str(x) for x in cls) for cls in (data["subtype_equivalences"] or [])
        ]
    if "doc_subclass_equivalences" in data:
        settings.doc_subclass_equivalences = [
            frozenset(str(x) for x in cls) for cls in (data["doc_subclass_equivalences"] or [])
        ]
    if "contract_subtypes" in data:
        settings.contract_subtypes = [dict(s) for s in (data["contract_subtypes"] or [])]
    if "subtype_aliases" in data:
        settings.subtype_aliases = {str(k): str(v) for k, v in (data["subtype_aliases"] or {}).items()}
    if "per_subtype" in data:
        settings.per_subtype = [str(k) for k in (data["per_subtype"] or [])]
    cost = data.get("cost_models") or {}
    for model, prices in cost.items():
        if isinstance(prices, (list, tuple)) and len(prices) == 2:
            settings.cost_models[str(model)] = (float(prices[0]), float(prices[1]))
    display = data.get("model_display") or {}
    for model, label in display.items():
        settings.model_display[str(model)] = str(label)

    # Doc-class field-type maps (for auto-resolving get_field_types).
    doc_class_field_types: dict[str, dict[str, str]] = {}
    for cls in data.get("doc_classes") or []:
        key = cls.get("key") if isinstance(cls, dict) else None
        if key:
            doc_class_field_types[str(key)] = {
                str(f): str(t) for f, t in (cls.get("field_types") or {}).items()
            }
    if doc_class_field_types:
        settings.doc_class_field_types.update(doc_class_field_types)
    _assign_grounding(settings, grounding)


@lru_cache(maxsize=1)
def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file (or env-overridden path); falls back to
    pure defaults when no file is given or found. Cached for the env/default
    resolution — explicit ``path`` calls read fresh (tests / hot-reload)."""
    if path is not None and str(path).strip():
        return _load_from_path(Path(path))
    env_path = os.environ.get(_ENV_CONFIG_PATH, "")
    if env_path.strip() and Path(env_path).exists():
        return _load_from_path(Path(env_path))
    return Settings()


def _load_from_path(path: Path) -> Settings:
    """Load YAML overrides onto a fresh default settings object."""
    settings = Settings()
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _apply_dict(settings, data)
    return settings


def clear_settings_cache() -> None:
    """Drop the cached settings (test / hot-reload helper)."""
    load_settings.cache_clear()


def get_settings() -> Settings:
    """The process-wide settings object (lru-cached)."""
    return load_settings()


def _grounding_value(key: str, value: Any) -> int | float:
    """One ``grounding`` value coerced to its type, or ``ValueError`` naming the key.

    Any finite real number (Python or numpy) is accepted; a whole-number key needs an
    integral value (``50`` or ``50.0``), and a bool is never a number here.
    """
    try:
        finite = (not isinstance(value, bool) and isinstance(value, numbers.Real)
                  and math.isfinite(value))
    except OverflowError:  # an int too large for a float
        finite = False
    if not finite:
        raise ValueError(f"grounding.{key} must be a finite number, got {value!r}")
    if _GROUNDING_KEYS[key] is int:
        if value != int(value):
            raise ValueError(f"grounding.{key} must be a whole number, got {value!r}")
        return int(value)
    return float(value)


def _grounding_from_block(current: GroundingSettings, data: Any) -> GroundingSettings:
    """A validated copy of ``current`` with a ``grounding:`` block applied.

    ``None`` or an empty mapping returns ``current``. A block that is not a mapping
    (``false``, ``0``, ``""`` and ``[]`` included), a non-numeric or out-of-range value
    raises ``ValueError``. Unknown keys are
    ignored, as in the ``trace_knobs:`` block, so a newer consumer taxonomy never
    breaks an older Dojo.
    """
    if data is None:
        return current
    if not isinstance(data, Mapping):
        raise ValueError(f"the grounding block must be a mapping, got {type(data).__name__}")
    values = {key: _grounding_value(key, data[key]) for key in _GROUNDING_KEYS if key in data}
    return replace(current, **values).validate()


def _apply_trace_knobs(knobs: TraceKnobSettings, data: dict[str, Any]) -> None:
    """Apply a raw ``trace_knobs:`` config dict onto ``knobs`` in place."""
    if "capture_confidence" in data:
        knobs.capture_confidence = bool(data["capture_confidence"])
    if "capture_reasoning" in data:
        knobs.capture_reasoning = bool(data["capture_reasoning"])
    if "confidence_min" in data:
        raw = data["confidence_min"]
        knobs.confidence_min = None if raw in (None, "") else float(raw)
    if "confidence_band" in data:
        raw = data["confidence_band"]
        if raw in (None, "", []):
            knobs.confidence_band = None
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            knobs.confidence_band = (float(raw[0]), float(raw[1]))
    if "reasoning_routes_presence" in data:
        knobs.reasoning_routes_presence = bool(data["reasoning_routes_presence"])
    if "compute_calibration_error" in data:
        knobs.compute_calibration_error = bool(data["compute_calibration_error"])
    if "missing_confidence" in data:
        mode = str(data["missing_confidence"] or "absent").strip().lower()
        if mode not in MISSING_CONFIDENCE_MODES:
            raise ValueError(
                f"missing_confidence must be one of {MISSING_CONFIDENCE_MODES}, got {mode!r}"
            )
        knobs.missing_confidence = mode


def _coerce_type_bands(raw: dict) -> dict[str, tuple]:
    """Coerce a ``type_bands`` mapping to canonical ``{type: tuple}`` form.

    YAML values arrive as one of: ``"always"``, ``"never"``, or a 2-element
    list ``[low, high]``. The canonical form is a tuple so callers can match
    on ``("always",)`` / ``("never",)`` without string ambiguity.
    """
    out: dict[str, tuple] = {}
    for k, v in (raw or {}).items():
        if v == "always":
            out[str(k)] = ("always",)
        elif v == "never":
            out[str(k)] = ("never",)
        elif isinstance(v, (list, tuple)) and len(v) == 2:
            out[str(k)] = (float(v[0]), float(v[1]))
    return out


def configure(**overrides: Any) -> Settings:
    """Inline override path: ``configure(field_scoring__bipartite_match_threshold=0.7)``.

    Two-segment dotted keys mutate nested dataclasses; top-level keys set
    attributes directly on the cached settings object. Grounding overrides
    (``grounding=GroundingSettings(...)`` and every ``grounding__…`` key) are
    coerced and validated together before anything is set, so
    ``configure(grounding__trust_min_n=300, grounding__trust_window=400)`` works in
    either order and a bad grounding value changes nothing (as before, a bad
    non-grounding key fails after the overrides before it were applied).
    """
    settings = get_settings()
    grounding = settings.grounding
    if "grounding" in overrides:
        grounding = overrides["grounding"]
        if not isinstance(grounding, GroundingSettings):
            raise ValueError(f"grounding must be a GroundingSettings, got {type(grounding).__name__}")
    block = {key.split("__", 1)[1]: value for key, value in overrides.items()
             if key.startswith("grounding__")}
    unknown = sorted(set(block) - set(_GROUNDING_KEYS))
    if unknown:
        raise AttributeError(f"unknown setting grounding__{unknown[0]}")
    values = {key: _grounding_value(key, value) for key, value in block.items()}
    grounding = replace(grounding, **values).coerced()
    for key, value in overrides.items():
        if key == "grounding" or key.startswith("grounding__"):
            continue
        if "__" in key:
            section, attr = key.split("__", 1)
            obj = getattr(settings, section)
            if hasattr(obj, attr):
                setattr(obj, attr, value)
            else:
                raise AttributeError(f"unknown setting {key}")
        else:
            setattr(settings, key, value)
    _assign_grounding(settings, grounding)
    return settings


def configure_from_taxonomy(taxonomy: dict | None) -> Settings:
    """Wire a repo taxonomy dict into the package settings (single wiring path).

    This is the ONE place the taxonomy→settings mapping lives: consuming
    projects (llm-mailroom, local-mailroom-sandbox) load their
    own ``taxonomy.yaml`` and pass the parsed dict here — they no longer
    re-implement the field-scoring coercion or the equivalence/cost mapping.

    Handles the same blocks ``_apply_dict`` reads: ``field_scoring:``
    (including the ``type_bands`` overrides and ``factuality_verification``),
    ``trace_knobs:`` (confidence / reasoning capture and gates),
    ``grounding:`` (reviewer trust thresholds, :class:`GroundingSettings`),
    ``subtype_equivalences``, ``doc_subclass_equivalences``,
    ``contract_subtypes``, ``subtype_aliases``, ``per_subtype``,
    ``cost_models``, ``model_display``.

    Honors ``LLM_DOJO_SCORING_CONFIG``: when it points at an existing YAML
    file, that file wins wholesale (loaded fresh) and ``taxonomy`` is ignored
    — matching the pre-existing escape-hatch contract. Callers that need
    secrets loaded first (e.g. entity-extraction's env files) must do that
    before calling this.

    Returns the process-wide settings object (lru-cached, now wired).
    """
    env_path = os.environ.get(_ENV_CONFIG_PATH, "")
    if env_path.strip() and Path(env_path).exists():
        # External config file wins wholesale (escape hatch).
        load_settings.cache_clear()
        return load_settings(Path(env_path))

    if not taxonomy:
        return get_settings()

    # Mutate the cached settings object in place (same mechanism configure()
    # uses), so every downstream get_settings()/field_scoring getter observes
    # the wired values for the rest of the process.
    settings = get_settings()
    _apply_dict(settings, taxonomy)
    return settings
