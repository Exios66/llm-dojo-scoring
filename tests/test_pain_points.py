"""Pain-point composites (pipeline/pain_points.py): penalty points per document, per run and per experiment.

The ladder is the client's: a needless human review is the worst outcome on both composites
(4 points), a correct and complete document earns none, a wrong subclass under the right class
costs less than a wrong class, and some correct entities cost less than under a third, which
costs less than a fully fabricated extraction. Ported from the sandbox's hotfix tests, then
extended with the per-document, breakdown and compare APIs.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

import llm_dojo_scoring
from llm_dojo_scoring.pipeline import pain_points as pp
from llm_dojo_scoring.scoring import field_scoring as fs
from llm_dojo_scoring.scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES


def _doc(doc_class: str | None = "contract", *, stage: str = "archived", predicted: str | None = "contract",
         expected_stage: str | None = "archived", scored: dict | None = None, **extra) -> pp.PainPointDocument:
    """Build a document with the common defaults of these tests."""
    return pp.PainPointDocument(expected_class=doc_class, predicted_class=predicted, stage=stage,
                                expected_stage=expected_stage, extraction=scored, **extra)


def _scored(tp=None, fn=None, fp=0, wrong=0, partial=0, **extra) -> dict:
    """Build a scored extraction row from event counts."""
    out = {"tp": tp, "fn": fn, "fp": fp, "n_value_wrong": wrong, "n_value_partial": partial,
           "scoring_method": "suite", **extra}
    return {k: v for k, v in out.items() if v is not None}


def _cls(**kw):
    """Classification outcome of a document built from keywords."""
    return pp.classification_outcome(_doc(**kw))


def _ext(scored, **kw):
    """Extraction outcome of a document built from a scored row."""
    return pp.extraction_outcome(_doc(scored=scored, **kw))


class TestClassificationLadder:
    """Tests for classification ladder."""

    def test_correct_and_complete_costs_nothing(self):
        """Correct and complete costs nothing."""
        out = _cls(subclass_correct=True)
        assert (out.points, out.reasons) == (0.0, ("correct",))

    def test_unnecessary_review_is_the_worst_outcome(self):
        """Unnecessary review is the worst outcome."""
        out = _cls(stage="review")
        assert (out.points, out.reason) == (4.0, "unnecessary_review")
        assert out.points == pp.DEFAULT_SCALE.max_points

    def test_necessary_review_costs_nothing(self):
        """Necessary review costs nothing."""
        out = _cls(expected_stage="review", stage="review", predicted="other")
        assert (out.points, out.reason) == (0.0, "necessary_review")

    def test_wrong_subtype_costs_less_than_wrong_doc_type(self):
        """Wrong subtype costs less than wrong doc type."""
        subtype = _cls(subclass_correct=False)
        doc_type = _cls(predicted="corporate_record", subclass_correct=False)
        assert (subtype.points, subtype.reason) == (1.0, "wrong_subtype")
        assert (doc_type.points, doc_type.reasons) == (3.0, ("wrong_doc_type",))
        assert 0 < subtype.points < doc_type.points < _cls(stage="review").points

    def test_missed_review_is_a_misarchive_below_a_wrong_class(self):
        """Missed review is a misarchive below a wrong class."""
        out = _cls(expected_stage="review")
        assert (out.points, out.reason) == (2.0, "missed_review")

    def test_worst_reason_wins_and_every_reason_is_kept(self):
        """Worst reason wins and every reason is kept."""
        out = _cls(expected_stage="review", predicted="corporate_record")
        assert (out.points, out.reasons) == (3.0, ("wrong_doc_type", "missed_review"))

    def test_class_comparison_is_case_insensitive(self):
        """Class comparison is case insensitive."""
        assert _cls(doc_class="Contract", predicted=" contract ").points == 0.0

    def test_archive_without_a_class_is_a_wrong_class(self):
        """Archive without a class is a wrong class."""
        assert _cls(predicted=None).reason == "wrong_doc_type"
        assert _cls(predicted="").reason == "wrong_doc_type"

    @pytest.mark.parametrize("kw", [
        {"failed": True}, {"stage": "failed"}, {"stage": None}, {"stage": "extract"}, {"stage": ""},
    ])
    def test_errors_and_unfinished_documents_are_pipeline_failures(self, kw):
        """Errors and unfinished documents are pipeline failures."""
        out = _cls(**kw)
        assert (out.points, out.reason) == (4.0, "pipeline_failure")

    def test_unlabelled_document_is_never_scored(self):
        """Unlabelled document is never scored."""
        assert _cls(doc_class=None) is None
        assert _cls(doc_class=" ") is None

    def test_missing_expected_stage_defaults_to_archived(self):
        """Missing expected stage defaults to archived."""
        assert _cls(expected_stage=None, stage="review").reason == "unnecessary_review"
        assert _cls(expected_stage=None).reason == "correct"


class TestExtractionLadder:
    """Tests for extraction ladder."""

    def test_complete_extraction_costs_nothing(self):
        """Complete extraction costs nothing."""
        out = _ext(_scored(tp=5, fn=0))
        assert (out.points, out.reason) == (0.0, "complete")

    def test_some_valid_entities_are_partial(self):
        """Some valid entities are partial."""
        assert _ext(_scored(tp=2, fn=1)).reason == "partial"
        # Exactly a third reported correctly is not under a third.
        assert _ext(_scored(tp=1, fn=2)).reason == "partial"

    def test_under_a_third_is_low_recall(self):
        """Under a third is low recall."""
        out = _ext(_scored(tp=1, fn=3))
        assert (out.points, out.reason) == (2.0, "low_recall")

    def test_extraction_that_stated_nothing_is_low_recall(self):
        """Extraction that stated nothing is low recall."""
        assert _ext(_scored(tp=0, fn=4)).reason == "low_recall"

    def test_fully_fabricated_extraction(self):
        """Fully fabricated extraction."""
        wrong_values = _ext(_scored(tp=0, fn=4, wrong=4))
        invented_fields = _ext(_scored(tp=0, fn=4, fp=2))
        assert (wrong_values.points, wrong_values.reason) == (3.0, "fabricated")
        assert invented_fields.reason == "fabricated"

    def test_near_misses_are_not_fabrication(self):
        """Near misses are not fabrication."""
        assert _ext(_scored(tp=0, fn=4, wrong=2, partial=2)).reason == "low_recall"

    def test_one_correct_entity_is_not_fully_fabricated(self):
        """One correct entity is not fully fabricated."""
        assert _ext(_scored(tp=1, fn=9, wrong=9)).reason == "low_recall"

    def test_invented_values_beside_a_full_recall_are_not_complete(self):
        """Invented values beside a full recall are not complete."""
        assert _ext(_scored(tp=4, fn=0, fp=1)).reason == "partial"

    def test_only_empty_truth(self):
        """Only empty truth."""
        assert _ext(_scored(tp=0, fn=0)).reason == "complete"
        assert _ext(_scored(tp=0, fn=0, fp=1)).reason == "fabricated"

    def test_ladder_order_matches_the_client(self):
        """Ladder order matches the client."""
        points = {
            "unnecessary_review": _ext(_scored(tp=5, fn=0), stage="review").points,
            "fabricated": _ext(_scored(tp=0, fn=3, wrong=3)).points,
            "low_recall": _ext(_scored(tp=0, fn=3)).points,
            "partial": _ext(_scored(tp=2, fn=1)).points,
            "complete": _ext(_scored(tp=3, fn=0)).points,
        }
        assert list(points.values()) == sorted(points.values(), reverse=True)
        assert len(set(points.values())) == len(points)
        assert points["complete"] == 0.0

    def test_review_outcomes_override_the_extraction(self):
        """Review outcomes override the extraction."""
        assert _ext(_scored(tp=5, fn=0), stage="review").reason == "unnecessary_review"
        assert _ext(_scored(tp=0, fn=5), stage="review", expected_stage="review").reason == "necessary_review"
        assert _ext(_scored(tp=5, fn=0), failed=True).reason == "pipeline_failure"

    def test_documents_without_field_truth_or_class_are_not_scored(self):
        """Documents without field truth or class are not scored."""
        assert _ext(None) is None
        assert _ext(_scored(tp=1, fn=0), doc_class=None) is None

    def test_scorer_without_any_figure_is_left_out(self):
        """Scorer without any figure is left out."""
        assert _ext({"scoring_method": "suite"}) is None
        assert _ext({}) is None

    @pytest.mark.parametrize("method", ["suite+maud", "suite+cuad"])
    def test_clause_label_rows_use_the_headline_share(self, method):
        # Clause-label rows carry suite event counts that never meet their truth: ignore them.
        """Clause label rows use the headline share."""
        base = {"tp": 0, "fn": 9, "n_value_wrong": 9, "scoring_method": method}
        assert _ext({**base, "overall_extraction_score": 1.0}).reason == "complete"
        assert _ext({**base, "overall_extraction_score": 0.5}).reason == "partial"
        assert _ext({**base, "overall_extraction_score": 0.1}).reason == "low_recall"
        assert _ext({**base, "overall_extraction_score": None}) is None

    def test_rows_without_event_counts_use_the_headline_share(self):
        """Rows without event counts use the headline share."""
        assert _ext({"overall_extraction_score": 0.2}).reason == "low_recall"

    def test_per_field_counts_stand_in_for_missing_event_counts(self):
        """Per field counts stand in for missing event counts."""
        scored = {"n_targeted": 4, "n_value_correct": 0, "n_value_wrong": 4, "scoring_method": "suite",
                  "overall_extraction_score": 0.4}
        assert _ext(scored).reason == "fabricated"
        assert _ext({**scored, "n_value_correct": 2, "n_value_wrong": 0}).reason == "partial"
        # Without fp, documented-absence hallucinations count as values invented on empty truth.
        hallucinated = {"n_targeted": 2, "n_value_correct": 2, "n_hallucinated": 1, "scoring_method": "suite"}
        assert _ext(hallucinated).reason == "partial"
        # Dojo event counts win when both are present.
        both = {"tp": 3, "fn": 0, "fp": 0, "n_targeted": 3, "n_value_correct": 0, "scoring_method": "suite"}
        assert _ext(both).reason == "complete"

    def test_bool_counts_are_not_numbers(self):
        """Bool counts are not numbers."""
        assert _ext({"tp": True, "fn": True, "overall_extraction_score": 0.5}).reason == "partial"


class TestPenaltyScale:
    """Tests for penalty scale."""

    def test_default_scale_is_profile_amfam_v1(self):
        """Default scale is profile amfam v1."""
        scale = pp.PenaltyScale()
        assert (scale.unnecessary_review, scale.wrong_doc_type, scale.missed_review, scale.wrong_subtype) == (4, 3, 2, 1)
        assert (scale.fabricated, scale.low_recall, scale.partial) == (3, 2, 1)
        assert scale.low_recall_below == pytest.approx(1 / 3)
        assert scale.profile == pp.PROFILE == "amfam-v1"
        assert scale == pp.DEFAULT_SCALE and scale.max_points == 4.0

    @pytest.mark.parametrize("override", [
        {"fabricated": 4.0},  # must stay under a needless review
        {"wrong_subtype": 3.0},  # must stay under a wrong class
        {"low_recall": 0.5},  # must stay over partial
        {"missed_review": 3.0},  # must stay under a wrong class
        {"pipeline_failure": 5.0},
        {"low_recall_below": 1.0},
        # NaN fails every comparison, so it must be refused before the order checks.
        {"fabricated": float("nan")},
        {"wrong_subtype": float("nan")},
        {"low_recall_below": float("nan")},
        {"unnecessary_review": float("inf"), "pipeline_failure": 4.0},
        {"profile": ""},
        {"profile": "  "},
    ])
    def test_scale_refuses_an_order_the_client_did_not_ask_for(self, override):
        """Scale refuses an order the client did not ask for."""
        with pytest.raises(ValueError):
            pp.PenaltyScale(**override)

    def test_nan_is_refused_even_under_the_default_profile(self):
        """Nan is refused even under the default profile."""
        with pytest.raises(ValueError, match="finite"):
            pp.PenaltyScale(fabricated=float("nan"))

    def test_custom_scale_needs_its_own_profile_id(self):
        """Custom scale needs its own profile id."""
        with pytest.raises(ValueError, match="own profile id"):
            pp.PenaltyScale(unnecessary_review=10.0, pipeline_failure=10.0)
        with pytest.raises(ValueError, match="own profile id"):
            pp.PenaltyScale(profile=pp.PROFILE, partial=0.5)

    def test_custom_scale_flows_through(self):
        """Custom scale flows through."""
        scale = pp.PenaltyScale(profile="strict-v1", unnecessary_review=10.0, pipeline_failure=10.0)
        assert scale.max_points == 10.0
        assert pp.classification_outcome(_doc(stage="review"), scale).points == 10.0
        assert pp.score_run([_doc(stage="review")], scale)["profile"] == "strict-v1"

    def test_the_default_values_under_a_custom_profile_are_allowed(self):
        """The default values under a custom profile are allowed."""
        assert pp.PenaltyScale(profile="copy").unnecessary_review == 4.0

    def test_the_scale_is_frozen(self):
        """The scale is frozen."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            pp.DEFAULT_SCALE.partial = 2.0  # type: ignore[misc]


class TestFieldValueOutcomes:
    """Tests for field value outcomes."""

    @pytest.mark.parametrize("placeholder", ["n/a", "N/A", "null", "none", "nan", "[]", "{}", "n.a.", "", None,
                                              [], ["", None], [[""], []], (), {}, float("nan")])
    def test_placeholder_predictions_are_blank_not_wrong(self, placeholder):
        """The Dojo scores these placeholders as blank, so a field filled with one is a plain miss,
        never an invented value that could make an extraction fabricated."""
        out = pp.field_value_outcomes({"a": "x", "b": "y"}, {"a": placeholder, "b": placeholder},
                                      {"a": 0.0, "b": 0.0})
        assert out == {"n_targeted": 2, "n_value_correct": 0, "n_value_wrong": 0, "n_value_partial": 0}
        scored = {"n_targeted": 2, "n_value_correct": 0, "scoring_method": "suite", **out}
        assert _ext(scored).reason == "low_recall"

    def test_a_list_holding_a_placeholder_is_a_stated_value(self):
        """Parity with the sandbox and the Dojo scorer: ``["n/a"]`` is a non-empty list, a value."""
        out = pp.field_value_outcomes({"parties": ["Acme"]}, {"parties": ["n/a"]}, {"parties": 0.0})
        assert out["n_value_wrong"] == 1
        scored = {"n_targeted": 1, "n_value_correct": 0, "scoring_method": "suite", **out}
        assert _ext(scored).reason == "fabricated"

    def test_placeholder_truth_is_not_targeted(self):
        """Placeholder truth is not targeted."""
        out = pp.field_value_outcomes({"a": "n/a", "b": [], "c": [None, ""], "d": 0, "e": False},
                                      {"d": 0, "e": False}, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 1.0, "e": 1.0})
        assert out == {"n_targeted": 2, "n_value_correct": 2, "n_value_wrong": 0, "n_value_partial": 0}

    def test_split_wrong_from_near_misses(self):
        """Split wrong from near misses."""
        out = pp.field_value_outcomes(
            {"a": "x", "b": "y", "c": "z", "d": "w", "e": ""},
            {"a": "x", "b": "nope", "c": "close", "d": "", "e": "invented"},
            {"a": 1.0, "b": 0.1, "c": 0.8, "d": 0.0, "e": 0.0},
        )
        # a correct, b wrong, c near miss, d blank (a plain miss), e empty truth (an fp, not counted here).
        assert out == {"n_targeted": 4, "n_value_correct": 1, "n_value_wrong": 1, "n_value_partial": 1}

    def test_the_bar_is_half_a_point(self):
        """The bar is half a point."""
        assert pp.FABRICATION_MAX_FIELD_SCORE == 0.5
        out = pp.field_value_outcomes({"a": "x", "b": "y"}, {"a": "p", "b": "q"}, {"a": 0.49, "b": 0.5})
        assert (out["n_value_wrong"], out["n_value_partial"]) == (1, 1)

    def test_no_field_scores_gives_nothing(self):
        """No field scores gives nothing."""
        assert pp.field_value_outcomes({"a": "x"}, {"a": "y"}, None) == {}
        assert pp.field_value_outcomes({"a": "x"}, {"a": "y"}, [("a", 0.0)]) == {}

    def test_unscored_and_non_numeric_scores_are_not_targeted(self):
        """Unscored and non numeric scores are not targeted; with none targeted there are no counts."""
        out = pp.field_value_outcomes({"a": "x", "b": "y", "c": "z"}, {"a": "x"},
                                      {"a": True, "b": "1.0"})
        assert out == {}
        mixed = pp.field_value_outcomes({"a": "x", "b": "y"}, {"a": "x"}, {"a": 1.0, "b": "1.0"})
        assert mixed["n_targeted"] == 1 and mixed["n_value_correct"] == 1


class TestScoreDocument:
    """Tests for score document."""

    def test_both_composites_with_every_reason(self):
        """Both composites with every reason."""
        doc = _doc(doc_id="d1", expected_stage="review", predicted="corporate_record",
                   scored=_scored(tp=1, fn=3), groups={"experiment": "A"})
        out = pp.score_document(doc)
        assert out["doc_id"] == "d1" and out["expected_class"] == "contract"
        assert out["groups"] == {"experiment": "A"}
        assert out["classification"] == {"points": 3.0, "reason": "wrong_doc_type",
                                         "reasons": ["wrong_doc_type", "missed_review"]}
        assert out["extraction"] == {"points": 2.0, "reason": "low_recall", "reasons": ["low_recall"]}

    def test_unscored_composites_are_none(self):
        """Unscored composites are none."""
        out = pp.score_document(_doc(doc_class=None, doc_id="d2"))
        assert out["classification"] is None and out["extraction"] is None
        assert pp.score_document(_doc())["extraction"] is None

    def test_the_result_is_plain_json(self):
        """The result is plain json."""
        import json

        json.dumps(pp.score_document(_doc(scored=_scored(tp=1, fn=0), groups={"arm": "x"})))


class TestRunSummary:
    """Tests for run summary."""

    def test_summary_counts_means_score_reasons_and_classes(self):
        """Summary counts means score reasons and classes."""
        out = pp.summarize([
            (pp.Outcome(4.0, ("unnecessary_review",)), "contract"),
            (pp.Outcome(0.0, ("correct",)), "contract"),
            (pp.Outcome(1.0, ("wrong_subtype",)), "corporate_record"),
            (None, "contract"),
        ], pp.CLASSIFICATION_REASONS)
        assert (out["n"], out["excluded"], out["points"]) == (3, 1, 5.0)
        assert out["mean"] == pytest.approx(5 / 3, abs=1e-6)
        assert out["score"] == pytest.approx(1 - (5 / 3) / 4, abs=1e-6)
        assert list(out["reasons"]) == list(pp.CLASSIFICATION_REASONS)
        assert out["reasons"]["unnecessary_review"] == 1 and out["reasons"]["missed_review"] == 0
        assert out["by_class"]["contract"] == {"n": 2, "points": 4.0, "mean": 2.0}

    def test_empty_run_has_no_mean(self):
        """Empty run has no mean."""
        out = pp.summarize([], pp.EXTRACTION_REASONS)
        assert (out["n"], out["mean"], out["score"]) == (0, None, None)
        assert list(out["reasons"]) == list(pp.EXTRACTION_REASONS)

    def test_a_class_less_outcome_counts_under_unknown(self):
        """A class less outcome counts under unknown."""
        out = pp.summarize([(pp.Outcome(1.0, ("partial",)), None)], pp.EXTRACTION_REASONS)
        assert out["by_class"] == {"unknown": {"n": 1, "points": 1.0, "mean": 1.0}}

    def test_score_run_reports_both_composites(self):
        """Score run reports both composites."""
        docs = [_doc(scored=_scored(tp=3, fn=0)), _doc(stage="review"),
                _doc(expected_stage="review", stage="review", scored=_scored(tp=0, fn=3)),
                _doc(doc_class=None)]
        out = pp.score_run(docs)
        assert out["profile"] == "amfam-v1" and out["scale"]["unnecessary_review"] == 4.0
        cls = out["classification"]
        assert (cls["n"], cls["excluded"], cls["points"]) == (3, 1, 4.0)
        assert cls["reasons"]["unnecessary_review"] == 1 and cls["reasons"]["necessary_review"] == 1
        ext = out["extraction"]
        assert (ext["n"], ext["excluded"], ext["points"]) == (2, 2, 4.0 - 4.0 + 0.0)
        assert ext["reasons"]["complete"] == 1 and ext["reasons"]["necessary_review"] == 1

    def test_score_run_takes_any_iterable_once(self):
        """Score run takes any iterable once."""
        out = pp.score_run(iter([_doc(), _doc(stage="review")]))
        assert out["classification"]["n"] == 2 and out["classification"]["mean"] == 2.0

    def test_empty_run(self):
        """Empty run."""
        out = pp.score_run([])
        assert out["classification"]["n"] == 0 and out["extraction"]["mean"] is None


def _run_docs():
    """Two experiments over the same four documents; B fixes d2 and breaks d4."""
    def mk(exp, doc_id, doc_class, stage="archived", predicted=None, scored=None):
        """Mk."""
        return pp.PainPointDocument(doc_id=doc_id, expected_class=doc_class,
                                    predicted_class=predicted or doc_class, stage=stage,
                                    extraction=scored, groups={"experiment": exp, "model": "m1"})
    return [
        mk("A", "d1", "contract", scored=_scored(tp=3, fn=0)),
        mk("A", "d2", "contract", stage="review", scored=_scored(tp=3, fn=0)),
        mk("A", "d3", "correspondence", scored=_scored(tp=1, fn=3)),
        mk("A", "d4", "correspondence", scored=_scored(tp=2, fn=0)),
        mk("B", "d1", "contract", scored=_scored(tp=3, fn=0)),
        mk("B", "d2", "contract", scored=_scored(tp=3, fn=0)),
        mk("B", "d3", "correspondence", scored=_scored(tp=1, fn=3)),
        mk("B", "d4", "correspondence", predicted="contract", scored=_scored(tp=2, fn=0)),
    ]


class TestBreakdown:
    """Tests for breakdown."""

    def test_one_entry_per_group_sorted_with_cis(self):
        """One entry per group sorted with cis."""
        out = pp.breakdown(_run_docs())
        assert out["profile"] == "amfam-v1" and out["by"] == ["experiment"]
        assert [g["key"] for g in out["groups"]] == [{"experiment": "A"}, {"experiment": "B"}]
        a, b = out["groups"]
        assert a["classification"]["n"] == 4 and a["classification"]["mean"] == 1.0  # one needless review
        assert b["classification"]["mean"] == 0.75  # one wrong doc type (3 points)
        assert a["classification"]["ci"]["n"] == 4 and b["extraction"]["ci"]["n"] == 4
        # 1 needless review (4) + low recall (2), over 4 documents.
        assert a["extraction"]["points"] == 4.0 + 2.0 + 0.0 + 0.0
        assert a["classification"]["ci"]["lo"] <= a["classification"]["mean"] <= a["classification"]["ci"]["hi"]

    def test_groups_sum_to_the_run(self):
        """Groups sum to the run."""
        docs = _run_docs()
        run = pp.score_run(docs)
        groups = pp.breakdown(docs)["groups"]
        for composite in ("classification", "extraction"):
            assert sum(g[composite]["n"] for g in groups) == run[composite]["n"]
            assert sum(g[composite]["points"] for g in groups) == pytest.approx(run[composite]["points"])

    def test_doc_class_key_reads_the_expected_class_lowercased(self):
        """Doc class key reads the expected class lowercased."""
        docs = [_doc("Contract"), _doc("contract", stage="review"), _doc("correspondence"), _doc(None)]
        out = pp.breakdown(docs, by=("doc_class",))
        assert [g["key"] for g in out["groups"]] == [
            {"doc_class": "contract"}, {"doc_class": "correspondence"}, {"doc_class": "unknown"}]
        contract = out["groups"][0]["classification"]
        assert (contract["n"], contract["mean"]) == (2, 2.0)
        assert out["groups"][2]["classification"]["n"] == 0 and out["groups"][2]["classification"]["ci"] is None

    def test_missing_label_is_unknown(self):
        """Missing label is unknown."""
        docs = [_doc(groups={"arm": "x"}), _doc(), _doc(groups={"arm": " "}), _doc(groups={"arm": None})]
        out = pp.breakdown(docs, by=("arm",))
        assert [g["key"] for g in out["groups"]] == [{"arm": "unknown"}, {"arm": "x"}]
        assert out["groups"][0]["classification"]["n"] == 3

    def test_two_keys_make_a_grid(self):
        """Two keys make a grid."""
        out = pp.breakdown(_run_docs(), by=("experiment", "doc_class"))
        keys = [(g["key"]["experiment"], g["key"]["doc_class"]) for g in out["groups"]]
        assert keys == [("A", "contract"), ("A", "correspondence"), ("B", "contract"), ("B", "correspondence")]
        assert out["by"] == ["experiment", "doc_class"]

    def test_a_string_key_is_one_key(self):
        """A string key is one key."""
        assert pp.breakdown(_run_docs(), by="model")["groups"][0]["key"] == {"model": "m1"}

    def test_ci_is_none_under_two_scored_documents(self):
        """Ci is none under two scored documents."""
        out = pp.breakdown([_doc(groups={"experiment": "A"})])
        group = out["groups"][0]
        assert group["classification"]["n"] == 1 and group["classification"]["ci"] is None
        assert group["extraction"]["ci"] is None and group["extraction"]["n"] == 0

    def test_ci_ignores_unscored_documents(self):
        """Ci ignores unscored documents."""
        docs = [_doc(groups={"experiment": "A"}, scored=_scored(tp=1, fn=0)),
                _doc(groups={"experiment": "A"}), _doc(groups={"experiment": "A"})]
        group = pp.breakdown(docs)["groups"][0]
        assert group["extraction"]["n"] == 1 and group["extraction"]["excluded"] == 2
        assert group["extraction"]["ci"] is None
        assert group["classification"]["ci"]["n"] == 3

    def test_is_deterministic_and_seeded(self):
        """Is deterministic and seeded."""
        docs = _run_docs()
        assert pp.breakdown(docs) == pp.breakdown(docs)
        ci = pp.breakdown(docs, n_boot=50, seed=7)["groups"][0]["classification"]["ci"]
        assert (ci["seed"], ci["n_boot"]) == (7, 50)

    def test_empty_run_has_no_groups(self):
        """Empty run has no groups."""
        assert pp.breakdown([])["groups"] == []

    @pytest.mark.parametrize("by", [(), "", ("",), (" ",), [1]])
    def test_bad_keys_are_refused(self, by):
        """Bad keys are refused."""
        with pytest.raises(ValueError):
            pp.breakdown(_run_docs(), by=by)

    def test_custom_scale_is_carried(self):
        """Custom scale is carried."""
        scale = pp.PenaltyScale(profile="strict-v1", unnecessary_review=8.0, pipeline_failure=8.0)
        out = pp.breakdown(_run_docs(), scale=scale)
        assert out["profile"] == "strict-v1" and out["scale"]["unnecessary_review"] == 8.0
        assert out["groups"][0]["classification"]["points"] == 8.0


class TestCompare:
    """Tests for compare."""

    def test_pairs_on_doc_id_and_signs_the_delta(self):
        """Pairs on doc id and signs the delta."""
        out = pp.compare(_run_docs(), baseline="A")
        assert (out["by"], out["baseline"], out["profile"]) == ("experiment", "A", "amfam-v1")
        (cls,) = out["classification"]
        assert cls["candidate"] == "B" and cls["n_paired"] == 4
        # A: 4+0+0+0, B: 0+0+0+3 -> same mean points 1.0 vs 0.75, so B costs less.
        assert (cls["baseline_mean"], cls["candidate_mean"], cls["delta"]) == (1.0, 0.75, -0.25)
        assert (cls["only_baseline"], cls["only_candidate"]) == (0, 0)
        assert cls["ci"]["n"] == 4
        (ext,) = out["extraction"]
        # A: 4 (review) + 0 + 2 + 0; B: 0 + 0 + 2 + 0.
        assert (ext["baseline_mean"], ext["candidate_mean"], ext["delta"]) == (1.5, 0.5, -1.0)

    def test_positive_delta_means_more_penalty(self):
        """Positive delta means more penalty."""
        (cls,) = pp.compare(_run_docs(), baseline="B")["classification"]
        assert cls["candidate"] == "A" and cls["delta"] == 0.25 > 0

    def test_every_other_group_is_a_candidate_sorted(self):
        """Every other group is a candidate sorted."""
        docs = _run_docs() + [dataclasses.replace(d, groups={"experiment": "C"}) for d in _run_docs()[:4]]
        out = pp.compare(docs, baseline="A")
        assert [c["candidate"] for c in out["classification"]] == ["B", "C"]
        assert out["classification"][1]["delta"] == 0.0 and out["classification"][1]["n_paired"] == 4

    def test_unpaired_documents_are_counted_not_scored(self):
        """Unpaired documents are counted not scored."""
        docs = [d for d in _run_docs() if not (d.groups["experiment"] == "B" and d.doc_id == "d1")]
        docs.append(pp.PainPointDocument(doc_id="d9", expected_class="contract", predicted_class="contract",
                                         stage="archived", groups={"experiment": "B"}))
        (cls,) = pp.compare(docs, baseline="A")["classification"]
        assert (cls["n_paired"], cls["only_baseline"], cls["only_candidate"]) == (3, 1, 1)
        assert cls["baseline_mean"] == pytest.approx(4 / 3, abs=1e-6)  # d2 4, d3 0, d4 0

    def test_a_document_unscored_on_one_side_is_unpaired_for_that_composite(self):
        """A document unscored on one side is unpaired for that composite."""
        docs = _run_docs()
        docs[7] = dataclasses.replace(docs[7], extraction=None)  # B / d4 loses its field truth
        out = pp.compare(docs, baseline="A")
        assert out["classification"][0]["n_paired"] == 4
        ext = out["extraction"][0]
        assert (ext["n_paired"], ext["only_baseline"], ext["only_candidate"]) == (3, 1, 0)

    def test_no_pairs_gives_none(self):
        """No pairs gives none."""
        docs = [dataclasses.replace(d, doc_id=f"{d.groups['experiment']}-{d.doc_id}") for d in _run_docs()]
        (cls,) = pp.compare(docs, baseline="A")["classification"]
        assert cls["n_paired"] == 0 and cls["delta"] is None and cls["ci"] is None
        assert cls["baseline_mean"] is None and cls["candidate_mean"] is None
        assert (cls["only_baseline"], cls["only_candidate"]) == (4, 4)

    def test_ci_is_none_under_two_pairs(self):
        """Ci is none under two pairs."""
        docs = [d for d in _run_docs() if d.doc_id == "d1"]
        (cls,) = pp.compare(docs, baseline="A")["classification"]
        assert cls["n_paired"] == 1 and cls["ci"] is None and cls["delta"] == 0.0

    def test_ci_brackets_a_consistent_improvement(self):
        """Ci brackets a consistent improvement."""
        docs = []
        for i in range(12):
            docs.append(pp.PainPointDocument(doc_id=f"d{i}", expected_class="contract", predicted_class="contract",
                                             stage="review", groups={"experiment": "before"}))
            docs.append(pp.PainPointDocument(doc_id=f"d{i}", expected_class="contract", predicted_class="contract",
                                             stage="archived", groups={"experiment": "after"}))
        (cls,) = pp.compare(docs, baseline="before")["classification"]
        assert cls["delta"] == -4.0 and (cls["ci"]["lo"], cls["ci"]["hi"]) == (-4.0, -4.0)

    def test_compares_by_any_group_key_or_doc_class(self):
        """Compares by any group key or doc class."""
        docs = [dataclasses.replace(d, groups={**d.groups, "arm": "ctl" if d.groups["experiment"] == "A" else "new"})
                for d in _run_docs()]
        assert pp.compare(docs, by="arm", baseline="ctl")["classification"][0]["candidate"] == "new"
        by_class = pp.compare([pp.PainPointDocument(doc_id=str(i), expected_class=c, predicted_class=c, stage="archived")
                               for i, c in enumerate(["contract", "correspondence"])],
                              by="doc_class", baseline="contract")
        assert by_class["classification"][0]["candidate"] == "correspondence"

    def test_unknown_baseline_is_refused(self):
        """Unknown baseline is refused."""
        with pytest.raises(ValueError, match="unknown baseline 'Z'"):
            pp.compare(_run_docs(), baseline="Z")

    def test_baseline_label_is_stripped(self):
        """A baseline with surrounding spaces names the same group the labels do."""
        assert pp.compare(_run_docs(), baseline=" A ")["baseline"] == "A"

    def test_missing_doc_id_is_refused(self):
        """Missing doc id is refused."""
        docs = _run_docs() + [pp.PainPointDocument(expected_class="contract", groups={"experiment": "B"})]
        with pytest.raises(ValueError, match="doc_id"):
            pp.compare(docs, baseline="A")
        blank = _run_docs() + [pp.PainPointDocument(doc_id="  ", groups={"experiment": "B"})]
        with pytest.raises(ValueError, match="doc_id"):
            pp.compare(blank, baseline="A")

    def test_duplicate_doc_id_inside_a_group_is_refused(self):
        """Duplicate doc id inside a group is refused."""
        docs = _run_docs() + [_run_docs()[0]]
        with pytest.raises(ValueError, match="duplicate doc_id"):
            pp.compare(docs, baseline="A")
        with pytest.raises(ValueError, match="duplicate doc_id"):
            pp.compare(docs, baseline="B")

    def test_the_same_doc_id_across_groups_is_the_pairing_not_a_duplicate(self):
        """The same doc id across groups is the pairing not a duplicate."""
        assert pp.compare(_run_docs(), baseline="A")["classification"][0]["n_paired"] == 4

    @pytest.mark.parametrize("by", ["", " ", ("experiment",), None])
    def test_by_is_one_key_name(self, by):
        """By is one key name."""
        with pytest.raises(ValueError):
            pp.compare(_run_docs(), by=by, baseline="A")

    def test_one_group_has_no_candidates(self):
        """One group has no candidates."""
        docs = [d for d in _run_docs() if d.groups["experiment"] == "A"]
        out = pp.compare(docs, baseline="A")
        assert out["classification"] == [] and out["extraction"] == []


class TestThroughTheScorer:
    """The extraction ladder on real Dojo scores (``score_extraction`` + ``extraction_binary_metrics``)."""

    FIELD_TYPES = DEFAULT_FIELD_TYPES["correspondence"]
    EXPECTED = {"sender": "Jane Roe", "recipient": "John Doe", "communication_type": "letter"}

    def _row(self, predicted, expected=None, doc_class="correspondence"):
        """Row."""
        expected = self.EXPECTED if expected is None else expected
        field_types = DEFAULT_FIELD_TYPES[doc_class]
        result = fs.score_extraction(doc_class, field_types, predicted, expected)
        prf = extraction_binary_metrics(expected, predicted, field_map=field_types, doc_class=doc_class, result=result)
        row = {k: prf[k] for k in ("tp", "fp", "fn")}
        row.update(pp.field_value_outcomes(expected, predicted, result.field_scores))
        row.update(overall_extraction_score=result.overall_score, scoring_method="suite")
        return row

    def _reason(self, predicted, **kw):
        """Reason."""
        row = self._row(predicted, **kw)
        return pp.extraction_outcome(_doc("correspondence", predicted="correspondence", scored=row)).reason, row

    def test_exact_copy_is_complete(self):
        """Exact copy is complete."""
        reason, row = self._reason(dict(self.EXPECTED))
        assert reason == "complete" and row["n_value_wrong"] == 0 and row["tp"] == 3

    def test_invented_values_are_fabricated(self):
        """Invented values are fabricated."""
        reason, row = self._reason({k: "zzqq entirely invented value" for k in self.EXPECTED})
        assert reason == "fabricated" and row["n_value_wrong"] > 0 and row["tp"] == 0

    def test_blank_extraction_is_low_recall(self):
        """Blank extraction is low recall."""
        reason, row = self._reason({})
        assert reason == "low_recall" and row["n_value_wrong"] == 0 and (row["tp"], row["fn"]) == (0, 3)

    def test_half_right_is_partial(self):
        """Half right is partial."""
        reason, _ = self._reason({"sender": "Jane Roe", "recipient": "John Doe"})
        assert reason == "partial"

    def test_placeholders_are_a_miss_not_a_fabrication(self):
        """Placeholders are a miss not a fabrication."""
        reason, row = self._reason({k: "n/a" for k in self.EXPECTED})
        assert reason == "low_recall" and row["n_value_wrong"] == 0

    def test_a_scored_run_flows_through_breakdown(self):
        """A scored run flows through breakdown."""
        docs = []
        for exp, predicted in (("good", dict(self.EXPECTED)), ("bad", {k: "zzqq entirely invented value" for k in self.EXPECTED})):
            for i in range(3):
                docs.append(pp.PainPointDocument(doc_id=f"d{i}", expected_class="correspondence",
                                                 predicted_class="correspondence", stage="archived",
                                                 extraction=self._row(predicted), groups={"experiment": exp}))
        groups = {g["key"]["experiment"]: g for g in pp.breakdown(docs)["groups"]}
        assert groups["good"]["extraction"]["mean"] == 0.0 and groups["bad"]["extraction"]["mean"] == 3.0
        (ext,) = pp.compare(docs, baseline="good")["extraction"]
        assert (ext["candidate"], ext["delta"], ext["n_paired"]) == ("bad", 3.0, 3)

    def test_detailed_path_rows_can_be_fabricated(self):
        """The detailed suite path returns no tp / fn; the per-field counts must still reach fabricated."""
        field_types = DEFAULT_FIELD_TYPES["corporate_record"]
        expected = {k: "Acme Holdings" for k in list(field_types)[:3]}
        invented = {k: "zzqq entirely invented value" for k in expected}
        result = fs.score_extraction("corporate_record", field_types, invented, expected)
        counts = pp.field_value_outcomes(expected, invented, result.field_scores)
        assert counts["n_targeted"] == 3 and counts["n_value_wrong"] > 0
        row = {**counts, "scoring_method": "suite"}  # no tp / fn, as on the detailed path
        assert pp.extraction_outcome(_doc("corporate_record", predicted="corporate_record", scored=row)).reason == "fabricated"
        right = {**pp.field_value_outcomes(expected, expected, fs.score_extraction(
            "corporate_record", field_types, expected, expected).field_scores), "scoring_method": "suite"}
        assert pp.extraction_outcome(_doc("corporate_record", predicted="corporate_record", scored=right)).reason == "complete"


class TestPublicSurface:
    """Tests for public surface."""

    def test_root_names_resolve_lazily_to_the_module(self):
        """Root names resolve lazily to the module."""
        assert llm_dojo_scoring.score_pain_points is pp.score_run
        assert llm_dojo_scoring.pain_point_breakdown is pp.breakdown
        assert llm_dojo_scoring.compare_pain_points is pp.compare
        assert llm_dojo_scoring.PainPointDocument is pp.PainPointDocument
        assert llm_dojo_scoring.pain_points is pp
        for name in ("score_pain_points", "pain_point_breakdown", "compare_pain_points", "PainPointDocument",
                     "pain_points"):
            assert name in llm_dojo_scoring.__all__

    def test_module_imports_only_what_the_sandbox_vendors(self):
        """The sandbox copies this file byte for byte: absolute imports from two Dojo modules only."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(pp))
        dojo = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, "relative import"
                if (node.module or "").startswith("llm_dojo_scoring"):
                    dojo.append((node.module, tuple(a.name for a in node.names)))
            elif isinstance(node, ast.Import):
                assert not any(a.name.startswith("llm_dojo_scoring") for a in node.names)
        assert sorted(dojo) == [("llm_dojo_scoring.analysis.bootstrap", ("bootstrap_ci",)),
                                ("llm_dojo_scoring.schemas.gt_metadata", ("is_empty_value",))]

    def test_registry_and_metric_ids_cover_the_run_headlines(self):
        """Registry and metric ids cover the run headlines."""
        from llm_dojo_scoring.metrics.registry import get_registry
        from llm_dojo_scoring.metrics.scorecard_honesty import metric_id_for

        reg = get_registry()
        for name, tier in (("pain_points_classification_mean", 1), ("pain_points_extraction_mean", 1),
                           ("pain_points_classification_score", 2), ("pain_points_extraction_score", 2)):
            assert int(reg.get(name).tier) == tier, name
            assert metric_id_for(name).startswith("pipeline.pain_points.")
        assert "lower is better" in reg.get("pain_points_classification_mean").description.lower()
        assert "lower is better" in reg.get("pain_points_extraction_mean").description.lower()
        # score = 1 - mean / max points, so the means are what a run reports as the headline.
        run = pp.score_run([_doc(stage="review"), _doc()])
        assert math.isclose(run["classification"]["score"], 1 - run["classification"]["mean"] / 4)


def test_headline_scores_use_the_registry_names():
    """The run headlines carry the four registry names, None for an empty composite."""
    from llm_dojo_scoring.metrics.registry import get_registry

    run = pp.score_run([pp.PainPointDocument(doc_id="1", expected_class="contract", predicted_class="contract",
                                             stage="review")])
    out = pp.headline_scores(run)
    assert out == {"pain_points_classification_mean": 4.0, "pain_points_classification_score": 0.0,
                   "pain_points_extraction_mean": None, "pain_points_extraction_score": None}
    names = set(get_registry().names())
    assert set(out) <= names



class TestRoundTwoHardening:
    """Adversarial review round 2: unusable figures, order, odd inputs."""

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
    def test_an_unusable_count_is_never_complete(self, bad):
        """A NaN, infinite or negative count is no figure; the next source decides."""
        pandas_row = {"tp": bad, "fn": bad, "fp": bad, "n_value_correct": 0.0, "n_targeted": 3.0,
                      "n_value_wrong": 2.0, "n_value_partial": float("nan"), "scoring_method": "suite"}
        # NaN is how pandas marks a missing cell: absent, so the per-field counts decide. A corrupt
        # (infinite, negative) fp makes the invented values unknown: the row is no usable figure.
        expected = "fabricated" if math.isnan(bad) else None
        outcome = _ext(pandas_row)
        assert (outcome.reason if outcome else None) == expected
        assert _ext({"tp": bad, "fn": 0, "overall_extraction_score": 0.1}).reason == "low_recall"
        assert _ext({"overall_extraction_score": float("nan")}) is None

    def test_inconsistent_per_field_counts_are_no_figure(self):
        """More correct fields than targeted ones falls back to the share."""
        assert _ext({"n_value_correct": 5, "n_targeted": 3, "overall_extraction_score": 0.5}).reason == "partial"

    def test_stages_compare_case_insensitively(self):
        """``Archived`` is archived and ``Review`` is review, as classes are case-folded."""
        doc = pp.PainPointDocument(expected_class="contract", predicted_class="contract", stage=" Archived ",
                                   expected_stage="Review")
        assert pp.classification_outcome(doc).reason == "missed_review"
        review = dataclasses.replace(doc, stage="REVIEW")
        assert pp.classification_outcome(review).reason == "necessary_review"

    def test_only_a_boolean_true_is_a_failure(self):
        """``failed`` is a boolean; the string ``"false"`` is not a failure."""
        doc = pp.PainPointDocument(expected_class="contract", predicted_class="contract", stage="archived",
                                   failed="false")  # type: ignore[arg-type]
        assert pp.classification_outcome(doc).reason == "correct"

    def test_partial_must_cost_something(self):
        """A custom scale cannot make a partial extraction free or negative."""
        for partial in (0.0, -1.0):
            with pytest.raises(ValueError, match="partial"):
                pp.PenaltyScale(profile="custom", partial=partial)

    def test_breakdown_interval_does_not_depend_on_order(self):
        """Shuffled documents give the same intervals."""
        import random

        docs = _run_docs() * 5
        docs = [dataclasses.replace(d, doc_id=f"{d.doc_id}-{i}") for i, d in enumerate(docs)]
        shuffled = list(docs)
        random.Random(7).shuffle(shuffled)
        assert pp.breakdown(docs, n_boot=300) == pp.breakdown(shuffled, n_boot=300)

    def test_odd_inputs_are_refused_or_tolerated_consistently(self):
        """None groups, non-mapping extraction, repeated or padded keys, bad n_boot."""
        doc = pp.PainPointDocument(doc_id="1", expected_class="contract", predicted_class="contract",
                                   stage="archived", extraction=["not", "a", "mapping"],  # type: ignore[arg-type]
                                   groups=None)  # type: ignore[arg-type]
        out = pp.score_document(doc)
        assert out["groups"] == {} and out["extraction"] is None
        assert json.dumps(pp.score_document(dataclasses.replace(doc, groups={"experiment": 3})))
        with pytest.raises(ValueError, match="repeat"):
            pp.breakdown(_run_docs(), by=("experiment", "experiment"))
        assert pp.breakdown(_run_docs(), by=" experiment ")["by"] == ["experiment"]
        with pytest.raises(ValueError, match="None"):
            pp.breakdown(_run_docs(), by=None)  # type: ignore[arg-type]
        for n_boot in (0, -5):
            with pytest.raises(ValueError, match="n_boot"):
                pp.breakdown(_run_docs(), n_boot=n_boot)
            with pytest.raises(ValueError, match="n_boot"):
                pp.compare(_run_docs(), baseline="A", n_boot=n_boot)


def test_the_pain_point_ids_are_in_the_score_ledger():
    """A release that adds metric ids lists them in the score ledger (COMPARABILITY.md)."""
    from llm_dojo_scoring.metrics.score_changelog import SCORE_CHANGELOG

    listed = {i for entry in SCORE_CHANGELOG for i in entry["metric_ids"]}
    assert {"pipeline.pain_points.classification.mean_penalty", "pipeline.pain_points.extraction.mean_penalty",
            "pipeline.pain_points.classification.score", "pipeline.pain_points.extraction.score"} <= listed


class TestRoundThreeHardening:
    """Adversarial review round 3: invention counts, numpy values, scale and id edge cases."""

    @pytest.mark.parametrize("fp", [-2, "2", 2.5, float("inf")])
    def test_a_corrupt_fp_is_never_read_as_no_invention(self, fp):
        """A present but corrupt fp makes invention unknown: never complete, the share decides."""
        assert _ext({"tp": 3, "fn": 0, "fp": fp}) is None
        assert _ext({"tp": 3, "fn": 0, "fp": fp, "overall_extraction_score": 0.5}).reason == "partial"

    def test_numpy_counts_are_counts(self):
        """numpy integers and floats (a DataFrame row) are read like Python numbers."""
        np = pytest.importorskip("numpy")
        assert _ext({"tp": np.int64(3), "fn": np.int64(0), "fp": np.int64(2)}).reason == "partial"
        assert _ext({"tp": np.float64(3), "fn": np.float64(0), "fp": np.float64(0)}).reason == "complete"
        assert _ext({"tp": 3, "fn": 0, "fp": np.float64("nan")}).reason == "complete"  # NaN = missing

    def test_fractional_counts_and_out_of_range_shares_are_no_figure(self):
        """A count must be whole; a share must lie in [0, 1]."""
        assert _ext({"tp": 0.4, "fn": 0}) is None
        assert _ext({"overall_extraction_score": 7}) is None
        assert _ext({"overall_extraction_score": -0.1}) is None

    def test_numpy_flags_are_read(self):
        """numpy booleans on failed / subclass_correct count like Python ones."""
        np = pytest.importorskip("numpy")
        base = pp.PainPointDocument(expected_class="contract", predicted_class="contract", stage="archived")
        assert pp.classification_outcome(dataclasses.replace(base, failed=np.True_)).reason == "pipeline_failure"
        assert pp.classification_outcome(dataclasses.replace(base, subclass_correct=np.False_)).reason == "wrong_subtype"

    @pytest.mark.parametrize("profile", [" amfam-v1", "AMFAM-v1", "amfam-v1 "])
    def test_the_client_profile_cannot_be_spoofed(self, profile):
        """A custom scale under any spelling of the client's profile id is refused."""
        with pytest.raises(ValueError, match="own profile id"):
            pp.PenaltyScale(profile=profile, partial=0.5)

    @pytest.mark.parametrize("points", [1e308, 1e4, 4e-7])
    def test_scale_points_are_bounded(self, points):
        """Points outside [0.001, 1000] are refused, so means stay finite and visible."""
        with pytest.raises(ValueError, match="must lie in"):
            pp.PenaltyScale(profile="x", unnecessary_review=points, pipeline_failure=points)

    def test_outcomes_must_be_valid(self):
        """summarize cannot be fed negative points or an outcome without a reason."""
        with pytest.raises(ValueError):
            pp.Outcome(-5.0, ("bogus",))
        with pytest.raises(ValueError):
            pp.Outcome(1.0, ())

    def test_seed_must_be_an_integer(self):
        """A None seed would not be deterministic."""
        with pytest.raises(ValueError, match="seed"):
            pp.breakdown(_run_docs(), seed=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="seed"):
            pp.compare(_run_docs(), baseline="A", seed=None)  # type: ignore[arg-type]

    def test_compare_pairs_and_deduplicates_on_the_stripped_id(self):
        """``d1`` and ``d1 `` are one document: paired across groups, a duplicate within one."""
        def doc(i, exp):
            """A correct archived contract with an id and an experiment label."""
            return pp.PainPointDocument(doc_id=i, expected_class="contract", predicted_class="contract",
                                        stage="archived", groups={"experiment": exp})
        out = pp.compare([doc("d1", "A"), doc("d1 ", "B")], baseline="A")
        assert out["classification"][0]["n_paired"] == 1
        with pytest.raises(ValueError, match="duplicate"):
            pp.compare([doc("d1", "A"), doc("d1 ", "A"), doc("d2", "B")], baseline="A")

    def test_non_finite_field_scores_are_not_targeted(self):
        """A NaN or infinite field score is no score: no field is targeted, so there are no counts."""
        out = pp.field_value_outcomes({"a": "x", "b": "y"}, {"a": "z", "b": "x"},
                                      {"a": float("nan"), "b": float("inf")})
        assert out == {}


def test_score_document_tolerates_non_mapping_groups():
    """A non-mapping ``groups`` reads as no labels, as ``breakdown`` reads it."""
    doc = pp.PainPointDocument(doc_id="1", expected_class="contract", predicted_class="contract", stage="archived",
                               groups=["experiment", "A"])  # type: ignore[arg-type]
    assert pp.score_document(doc)["groups"] == {}


class TestBugbotOn185:
    """Cursor Bugbot on llm-dojo-scoring#185."""

    def test_missing_labels_from_a_dataframe_are_missing(self):
        """A NaN or pd.NA expected class excludes the document; a NaN group label is "unknown"."""
        pd = pytest.importorskip("pandas")
        for missing in (float("nan"), pd.NA):
            doc = pp.PainPointDocument(doc_id="1", expected_class=missing, predicted_class="contract",
                                       stage="archived", groups={"experiment": missing})
            assert pp.classification_outcome(doc) is None
            (group,) = pp.breakdown([doc], n_boot=10)["groups"]
            assert group["key"] == {"experiment": "unknown"}

    @pytest.mark.parametrize("partial", [-1, 2.5, float("inf"), "x"])
    def test_a_corrupt_near_miss_count_is_never_read_as_zero(self, partial):
        """A corrupt n_value_partial makes the row no usable figure, not fabricated."""
        row = {"tp": 0, "fn": 3, "fp": 1, "n_value_partial": partial}
        assert _ext(row) is None
        assert _ext({**row, "overall_extraction_score": 0.1}).reason == "low_recall"

    def test_a_doc_class_baseline_is_folded_like_the_groups(self):
        """``compare(by="doc_class", baseline="Contract")`` names the ``contract`` group."""
        docs = [pp.PainPointDocument(doc_id=str(i), expected_class=c, predicted_class=c, stage="archived")
                for i, c in enumerate(["Contract", "correspondence"])]
        assert pp.compare(docs, by="doc_class", baseline="Contract")["baseline"] == "contract"


def test_score_document_echoes_a_missing_group_label_as_unknown():
    """A NaN group label is "unknown" in score_document, as in breakdown."""
    doc = pp.PainPointDocument(doc_id="1", expected_class="contract", predicted_class="contract", stage="archived",
                               groups={"experiment": float("nan"), "model": "m"})
    assert pp.score_document(doc)["groups"] == {"experiment": "unknown", "model": "m"}


class TestCodeRabbitOn185:
    """CodeRabbit on llm-dojo-scoring#185."""

    @pytest.mark.parametrize("scores", [{}, {"a": float("nan")}, {"a": None}, {"b": 1.0}])
    def test_stated_truth_without_a_usable_field_score_is_no_figure(self, scores):
        """Truth with a value but no usable score yields no counts, never a zero-count complete."""
        out = pp.field_value_outcomes({"a": "x"}, {"a": "x"}, scores)
        assert out == {}
        assert _ext({"scoring_method": "suite", **out}) is None
        assert _ext({"scoring_method": "suite", "overall_extraction_score": 0.5, **out}).reason == "partial"

    def test_genuinely_empty_truth_keeps_its_counts(self):
        """All-blank truth is targeted nowhere: zero counts, and nothing stated is complete."""
        out = pp.field_value_outcomes({"a": "", "b": None}, {}, {})
        assert out == {"n_targeted": 0, "n_value_correct": 0, "n_value_wrong": 0, "n_value_partial": 0}
        assert _ext({"scoring_method": "suite", **out}).reason == "complete"


class TestCodeAntOn185:
    """CodeAnt on llm-dojo-scoring#185 (raised after the merge)."""

    def test_a_missing_scoring_method_cell_reads_as_no_method(self):
        """A pandas NA / NaN / None ``scoring_method`` is no method, as an absent key is; never a TypeError."""
        pd = pytest.importorskip("pandas")
        absent = _ext(_scored(tp=1, fn=0))
        assert absent.reason == "complete"
        for missing in (pd.NA, float("nan"), None):
            assert _ext(_scored(tp=1, fn=0, scoring_method=missing)) == absent
            # Without counts the share decides, as it does for a row with no method.
            row = {"scoring_method": missing, "overall_extraction_score": 0.5}
            assert _ext(row).reason == "partial"
