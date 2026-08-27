"""Citation / inclusion / ground-truth metadata for T0+T1 registry names.

Merged onto :class:`~llm_dojo_scoring.registry.MetricDef` when those YAML
keys are empty. Custom registries still load: the three fields default to
``""``. Do not invent methods — every citation matches an implemented scorer
or an explicit honesty gap (emitter-only / unemitted ``source``).
"""

from __future__ import annotations

__all__ = ["ALLOWED_GROUND_TRUTH", "METRIC_META"]

ALLOWED_GROUND_TRUTH = frozenset({"required", "optional", "structural", "none", ""})

_EMITTER = {
    "citation": (
        "Not computed in llm-dojo-scoring. Mailroom SCORE_CONFIGS / Langfuse "
        "transport alias preserved so consolidation is lossless."
    ),
    "inclusion": (
        "Never produced by this package's scorers; value is whatever the "
        "pipeline emits. Skip when the emitter omits the key."
    ),
    "ground_truth": "none",
}

_VAN_RIJSBERGEN = (
    "van Rijsbergen Fβ (Information Retrieval, 1979); F1 is the harmonic "
    "mean (β=1), F2 uses β=2 so 5PR/(4P+R)."
)

_ACE = (
    "ACE / CoNLL / SemEval slot-filling: (field, value) events. TP requires "
    "the typed field score ≥ 1.0; partial list matches are not TP."
)

_MACRO = (
    "Unweighted macro-average of one-vs-rest P/R/Fβ over the label set "
    "(Sokolova & Lapalme 2009-style). Same Fβ as classification.fbeta."
)

_SQUAD = (
    "SQuAD token-F1 over token multisets (Rajpurkar et al., EMNLP 2016) as "
    "implemented by field_scoring.score_field for free_text."
)

_HUNGARIAN = (
    "Optimal bipartite matching (Hungarian / Kuhn–Munkres via scipy "
    "linear_sum_assignment) over a pairwise similarity matrix, then "
    "P/R/F1 on the matched set."
)

_CLS_SKIP = (
    "Computed when expected and predicted label sequences are non-empty. "
    "Empty/null labels are dropped. score_task drops ERROR_PREFIX rows. "
    "Returns 0.0 with n=0 rather than inventing a score on an empty run."
)

_EXTRACT_SKIP = (
    "Skipped when expected is empty/null (no events). Empty GT field values "
    "are not FN. ERROR_PREFIX predictions are dropped by the suite. "
    "entity_list F1 is None when the document has no list fields."
)

_SUBCLASS = (
    "Attached by score_task only when subclass kwargs (or per-row subclass "
    "labels) are present; otherwise the subclass_* keys are omitted / None."
)


def _m(citation: str, inclusion: str, ground_truth: str) -> dict[str, str]:
    return {
        "citation": citation,
        "inclusion": inclusion,
        "ground_truth": ground_truth,
    }


METRIC_META: dict[str, dict[str, str]] = {
    # ----- T0 -----
    "f1_macro": _m(
        f"{_MACRO} {_VAN_RIJSBERGEN} Source: classification.macro_prf.",
        f"{_CLS_SKIP} For extraction/transcription suites, f1_macro may be "
        "rebound to token-F1 (see suite.score).",
        "required",
    ),
    "accuracy": _m(
        "Exact-match accuracy: mean of per-item equality after task-aware "
        "normalize_label (classification.accuracy).",
        _CLS_SKIP,
        "required",
    ),
    "extraction_overall_score": _m(
        "Mean of per-field typed scores from field_scoring.score_extraction "
        "(soft mean; partial list credit stays here, not in field-micro F1).",
        "None when there are no scorable fields. Empty/null expected dict "
        "yields no overall score.",
        "required",
    ),
    "extraction_f1": _m(
        f"{_ACE} {_VAN_RIJSBERGEN} Source: extraction_metrics.extraction_binary_metrics.",
        _EXTRACT_SKIP,
        "required",
    ),
    "extraction_f2": _m(
        f"{_ACE} {_VAN_RIJSBERGEN} Insurance claims board number; computed for every specialist.",
        _EXTRACT_SKIP,
        "required",
    ),
    "content_topic_f1_macro": _m(
        "Enron correspondence 11-topic catalog; unweighted macro-F1 over "
        "expected topics (content_scoring.score_content_topic).",
        "Computed when a content_topic gold label is present; skipped when "
        "the field is empty/null.",
        "required",
    ),
    # ----- T1 classification -----
    "precision": _m(
        f"One-vs-rest / binary precision TP/(TP+FP). {_VAN_RIJSBERGEN} "
        "score_task fills this from classification.macro_prf for multiclass.",
        _CLS_SKIP,
        "required",
    ),
    "recall": _m(
        f"One-vs-rest / binary recall TP/(TP+FN). {_VAN_RIJSBERGEN}",
        _CLS_SKIP,
        "required",
    ),
    "f2": _m(
        f"{_VAN_RIJSBERGEN} classification.binary_metrics / macro_prf.",
        _CLS_SKIP,
        "required",
    ),
    "false_positive_rate": _m(
        "FP/(FP+TN) from classification.binary_metrics.",
        "Undefined (None) when FP+TN is 0.",
        "required",
    ),
    "false_negative_rate": _m(
        "FN/(FN+TP) from classification.binary_metrics.",
        "Undefined (None) when FN+TP is 0.",
        "required",
    ),
    "precision_macro": _m(_MACRO, _CLS_SKIP, "required"),
    "recall_macro": _m(_MACRO, _CLS_SKIP, "required"),
    "f2_macro": _m(f"{_MACRO} {_VAN_RIJSBERGEN}", _CLS_SKIP, "required"),
    "classification_correct": _m(
        "Per-document exact-match after normalize_label (classification.exact_match).",
        "Skipped when either side is empty/null.",
        "required",
    ),
    "exact_accuracy": _m(
        "HF pipeline exact doc-type accuracy; merger_agreement ≠ contract "
        "(mailroom.score_aligned_classification).",
        "Requires paired predicted/expected doc types. Empty sequences skipped.",
        "required",
    ),
    "aligned_accuracy": _m(
        "HF pipeline aligned doc-type accuracy; merger_agreement ≡ contract "
        "(mailroom.score_aligned_classification).",
        "Requires paired predicted/expected doc types. Empty sequences skipped.",
        "required",
    ),
    "subclass_accuracy": _m(
        "Exact-match accuracy over the document subclass catalog "
        "(CUAD family / CMS table / Enron form / record type).",
        _SUBCLASS,
        "required",
    ),
    "subclass_f1_macro": _m(
        f"Macro-F1 over document subclasses. {_MACRO}",
        _SUBCLASS,
        "required",
    ),
    "subclass_precision_macro": _m(
        f"Macro precision over document subclasses. {_MACRO}",
        _SUBCLASS,
        "required",
    ),
    "subclass_recall_macro": _m(
        f"Macro recall over document subclasses. {_MACRO}",
        _SUBCLASS,
        "required",
    ),
    "subclass_f2_macro": _m(
        f"Macro F2 over document subclasses. {_MACRO} {_VAN_RIJSBERGEN}",
        _SUBCLASS,
        "required",
    ),
    # ----- T1 extraction field / list -----
    "extraction_precision": _m(
        f"{_ACE} Source: extraction_metrics.extraction_binary_metrics.",
        _EXTRACT_SKIP,
        "required",
    ),
    "extraction_recall": _m(
        f"{_ACE} Source: extraction_metrics.extraction_binary_metrics.",
        _EXTRACT_SKIP,
        "required",
    ),
    "entity_list_precision": _m(
        f"{_HUNGARIAN} Per-list-field precision from field_scoring.score_entity_list.",
        "None if the document has no entity_list fields. Empty GT lists are not FN.",
        "required",
    ),
    "entity_list_recall": _m(
        f"{_HUNGARIAN} Per-list-field recall from field_scoring.score_entity_list.",
        "None if the document has no entity_list fields.",
        "required",
    ),
    "entity_list_f1": _m(
        f"{_HUNGARIAN} Mean list F1 (extraction_metrics.mean_entity_list_f1); "
        "dashboard name for diagnostics.entity_list_raw_f1.",
        "None if the document has no list fields.",
        "required",
    ),
    "field_presence": _m(
        "ACE-style share of expected fields populated. Registry source points "
        "at field_scoring.score_extraction, which does not emit this name.",
        "Not computed in this package as of 0.11.0 — honesty gap, not a scorer. "
        "Do not treat a missing key as 0.0.",
        "required",
    ),
    "verified_precision": _m(
        "Precision restricted to doc-verifiable list items "
        "(field_scoring.audit_list_field token-coverage check).",
        "None when verification is disabled or the row has no audited list fields.",
        "optional",
    ),
    "jaccard_similarity": _m(
        "Token-set Jaccard over positive spans; ContractEval method "
        "(arXiv 2508.03080) via tasks.get_jaccard.",
        "Skipped when both sides are empty. ContractEval tasks only.",
        "required",
    ),
    "contracteval_false_no_related": _m(
        "ContractEval (arXiv 2508.03080) no-related rate: model says no related "
        "clause when GT expects content (tasks.contracteval_metrics).",
        "ContractEval rows only; skipped outside that task.",
        "required",
    ),
    "laziness_rate": _m(
        "Record-level alias of contracteval_false_no_related "
        "(tasks.said_no_related): empty/bail responses when content is expected.",
        "ContractEval / contracts specialist rows; skipped when GT expects empty.",
        "required",
    ),
    "date_mae_days": _m(
        "Mean absolute error in days after date parse (diagnostics.extraction_diagnostics).",
        "None when neither side parses to a date. Empty GT dates skipped.",
        "required",
    ),
    "money_mae_usd": _m(
        "Mean absolute money-field error in USD after one-cent normalize "
        "(diagnostics.extraction_diagnostics / field_scoring.parse_money).",
        "None when either side is unparseable. Empty GT amounts skipped.",
        "required",
    ),
    "determination_consistency": _m(
        "Structural check: coverage_determination agrees with denial_reasons "
        "(approved ⇒ empty reasons; denied/partial ⇒ non-empty). "
        "Ground truth is unused (claims_consistency.determination_consistency).",
        "Always defined on a predicted dict; 0.0 when determination is missing. "
        "CMS GT in the published merge is all-approved — the scorer is degenerate "
        "on GT-shaped predictions, not missing.",
        "structural",
    ),
    "amount_exactness": _m(
        "Claimed-amount exact match after money normalize (complement of "
        "money_mae_usd); claims_consistency.amount_exactness.",
        "None if either side is empty or unparseable.",
        "required",
    ),
    # ----- T1 content / MAUD / LegalBench / ASR / intake -----
    "content_topic_accuracy": _m(
        "Enron 11-topic exact-match accuracy (content_scoring.score_content_topic).",
        "Skipped when content_topic gold is empty/null.",
        "required",
    ),
    "sentiment_accuracy": _m(
        "Enron sentiment_label exact-match (negative/neutral/positive) "
        "(content_scoring.score_sentiment).",
        "Skipped when sentiment gold is empty/null.",
        "required",
    ),
    "sentiment_f1_macro": _m(
        "Enron sentiment_label macro-F1 (content_scoring.score_sentiment).",
        "Skipped when sentiment gold is empty/null.",
        "required",
    ),
    "maud_question_accuracy": _m(
        "MAUD per-question micro exact-answer accuracy over the 22 Hub keys "
        "(content_scoring.score_maud_extraction).",
        "None when no MAUD questions are present on the row.",
        "required",
    ),
    "maud_question_macro_accuracy": _m(
        "MAUD per-question macro accuracy (unweighted mean over questions) "
        "(content_scoring.score_maud_extraction).",
        "None when no MAUD questions are present on the row.",
        "required",
    ),
    "maud_clause_presence": _m(
        "Share of expected MAUD questions present in the prediction.",
        "None when the expected MAUD map is empty.",
        "required",
    ),
    "maud_valid_class_rate": _m(
        "Share of predicted MAUD answers in the question's known class set.",
        "None when there are no predicted MAUD answers.",
        "optional",
    ),
    "legalbench_accuracy": _m(
        "LegalBench binary accuracy (tasks.legalbench_score).",
        "Court-opinion / LegalBench rows only; skipped when no questions.",
        "required",
    ),
    "legalbench_macro_f1": _m(
        f"LegalBench macro-F1. {_MACRO}",
        "Court-opinion / LegalBench rows only; skipped when no questions.",
        "required",
    ),
    "wer": _m(
        "Word error rate: word-level Levenshtein / |reference| (NIST ASR; "
        "asr.word_error_rate). May exceed 1.0 when the hypothesis is longer.",
        "Requires a non-empty reference transcript. Empty hypothesis is WER=1.0 "
        "when reference is non-empty.",
        "required",
    ),
    "cer": _m(
        "Character error rate: character-level Levenshtein / |reference| "
        "(asr.character_error_rate).",
        "Requires a non-empty reference transcript.",
        "required",
    ),
    "word_accuracy": _m(
        "max(0, 1 − WER) complementary transcription headline (asr.word_accuracy).",
        "Same inclusion as wer.",
        "required",
    ),
    "intake_prep_completeness": _m(
        "Share of intake prep-step invariants that hold (NFC, newline unify, "
        "NBSP, zero-width, C0, hyphen unwrap, blank-run collapse, horizontal "
        "space, trim). Structural check on predicted text vs the clerk contract; "
        "not a labeled GT score (intake.intake_prep_completeness).",
        "Computed whenever predicted text is a string. Empty string still scores "
        "the invariants (trim/NFC hold; content is empty).",
        "structural",
    ),
    "intake_changed_rate": _m(
        "Share of documents whose intake clerk mutated the transcribed text "
        "(intake.score_intake).",
        "Requires paired pre/post text; skipped on empty runs.",
        "optional",
    ),
    "intake_messy_rate": _m(
        "Share of documents flagged looks_messy after intake (OCR residue / "
        "wrap artifacts) (intake.looks_messy).",
        "Computed on predicted (post-intake) text.",
        "none",
    ),
    # ----- T1 cost / audit -----
    "estimated_cost_usd": _m(
        "USD cost from token counts × model table (cost.estimate_cost).",
        "0 when usage is missing. Not a quality score.",
        "none",
    ),
    "cost_per_document": _m(
        "Total estimated cost / documents processed (cost.estimate_for_record).",
        "None when document count is 0.",
        "none",
    ),
    "audit_disagreement_rate": _m(
        "Complement of typed extraction overall_score between auditor output "
        "and the reference dict (suites.ScoringSuite._score_audit). No new "
        "algorithm — 1 − score_extraction.overall_score.",
        "None when overall_score is None (no scorable fields). Requires two dicts.",
        "optional",
    ),
    "audit_resolution_rate": _m(
        "Typed extraction overall_score of auditor vs reference — the rate "
        "the audit pass agrees with (and would correct toward) the reference "
        "(suites.ScoringSuite._score_audit).",
        "None when overall_score is None. Requires two dicts.",
        "optional",
    ),
    # ----- T1 emitter-only mailroom aliases -----
    "schema_valid": dict(_EMITTER),
    "parse_error": dict(_EMITTER),
    "success_rate": dict(_EMITTER),
    "completeness": dict(_EMITTER),
    "class_correct": dict(_EMITTER),
    "stage_correct": dict(_EMITTER),
    "extraction_correctness": dict(_EMITTER),
    "extraction_needs_judge_review": dict(_EMITTER),
    "expected_field_presence": dict(_EMITTER),
    "extraction_overall_verified_precision": dict(_EMITTER),
    "extraction_verified_precision": dict(_EMITTER),
    "mailroom-pipeline-judge": dict(_EMITTER),
    "mailroom-pipeline-quality": dict(_EMITTER),
    "extraction_hallucination_rate": dict(_EMITTER),
}
