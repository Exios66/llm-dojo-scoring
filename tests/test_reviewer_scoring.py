"""Reviewer-lane scorecard: class/subclass, risk, calibration, routing, cost."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.analysis.calibration import clopper_pearson_upper
from llm_dojo_scoring.scoring.reviewer import (
    HUMAN_VERDICTS,
    ReviewRecord,
    review_record_from_run_item,
    score_review_lane,
)


def _record(**overrides) -> ReviewRecord:
    """One reviewer row with a clean accept as the default."""
    values = {
        "doc_id": "doc",
        "expected_doc_type": "contract",
        "expected_doc_subclass": "license",
        "sorter_doc_type": "contract",
        "sorter_doc_subclass": "license",
        "sorter_confidence": 0.93,
        "reviewer_doc_type": "contract",
        "reviewer_doc_subclass": "license",
        "reviewer_confidence": 0.99,
        "reviewer_model": "gpt-6-luna-decisions",
        "reviewer_verdict": "continue_sorter_correct",
        "route": "extract",
        "cutoff": 0.8,
        "cost_usd": 0.001,
        "question_set": "3.1.0",
    }
    values.update(overrides)
    return ReviewRecord(**values)


def _population() -> list[ReviewRecord]:
    """Ten rows covering accepts, parks, wrong accepts, and missing evidence."""
    return [
        _record(doc_id="ok-contract"),
        _record(
            doc_id="ok-insurance",
            expected_doc_type="insurance_claim",
            expected_doc_subclass="carrier",
            sorter_doc_type="insurance_claim",
            sorter_doc_subclass="carrier",
            reviewer_doc_type="insurance_claim",
            reviewer_doc_subclass="carrier",
        ),
        _record(
            doc_id="wrong-accept",
            expected_doc_type="contract",
            expected_doc_subclass="license",
            sorter_doc_type="insurance_claim",
            sorter_doc_subclass="carrier",
            reviewer_doc_type="insurance_claim",
            reviewer_doc_subclass="carrier",
            reviewer_verdict="continue_sorter_correct",
        ),
        _record(
            doc_id="disagreement",
            expected_doc_type="corporate_record",
            expected_doc_subclass="bylaws",
            sorter_doc_type="corporate_record",
            sorter_doc_subclass="bylaws",
            reviewer_doc_type="contract",
            reviewer_doc_subclass="license",
            reviewer_verdict="reclassify",
            route="human_review",
            causes=("reviewer_disagreement",),
        ),
        _record(
            doc_id="low-confidence",
            reviewer_confidence=0.4,
            route="human_review",
            causes=("reviewer_low_confidence",),
        ),
        _record(
            doc_id="subclass-wrong",
            reviewer_doc_subclass="service",
            reviewer_verdict="continue_sorter_correct",
            route="human_review",
        ),
        _record(
            doc_id="human-verdict",
            reviewer_verdict="route_to_human_review",
            route="human_review",
            causes=("reviewer_low_confidence",),
        ),
        _record(
            doc_id="no-text",
            expected_doc_type="correspondence",
            expected_doc_subclass="email",
            reviewer_doc_type=None,
            reviewer_doc_subclass=None,
            reviewer_confidence=None,
            reviewer_verdict="unreadable",
            has_text=False,
            route="human_review",
            causes=("reviewer_no_text",),
        ),
        _record(
            doc_id="unavailable",
            expected_doc_type="correspondence",
            expected_doc_subclass="email",
            reviewer_doc_type=None,
            reviewer_doc_subclass=None,
            reviewer_confidence=None,
            reviewer_verdict=None,
            route="human_review",
            causes=("reviewer_unavailable",),
        ),
        _record(
            doc_id="no-cutoff",
            expected_doc_type="corporate_record",
            expected_doc_subclass="bylaws",
            sorter_doc_type="corporate_record",
            sorter_doc_subclass="bylaws",
            reviewer_doc_type="corporate_record",
            reviewer_doc_subclass="other",
            cutoff=None,
        ),
    ]


def test_class_accuracy_and_macro_accuracy():
    """Accuracy is over answered rows; unanswered rows are counted separately."""
    card = score_review_lane(_population())
    quality = card["quality"]
    assert quality["n_expected"] == 10
    assert quality["n_scored"] == 8
    assert quality["n_unanswered"] == 2
    assert quality["correct"] == 6
    assert quality["class_accuracy"] == 0.75
    assert quality["class_macro_accuracy"] is not None
    assert quality["per_class"]["contract"]["n"] == 5


def test_wrong_accept_risk_and_sample_shortfall():
    """One wrong accept in four cannot meet a 1% upper bound."""
    card = score_review_lane(_population())
    acceptance = card["acceptance"]
    assert acceptance["n_accepted"] == 4
    assert acceptance["n_accepted_with_truth"] == 4
    assert acceptance["n_wrong_accepts"] == 1
    assert acceptance["wrong_accept_rate"] == 0.25
    assert acceptance["wrong_accept_upper_95"] == pytest.approx(0.7514, abs=1e-4)
    assert acceptance["required_accepts"] == 473
    assert acceptance["sample_shortfall"] == 469
    assert acceptance["meets_risk_bar"] is False


def test_zero_wrong_accepts_still_needs_the_sample():
    """299 clean accepts are required for a 1% upper bound."""
    rows = [_record(doc_id=f"ok-{index}") for index in range(299)]
    card = score_review_lane(rows)
    acceptance = card["acceptance"]
    assert acceptance["n_wrong_accepts"] == 0
    assert acceptance["wrong_accept_upper_95"] == pytest.approx(0.00997, abs=1e-5)
    assert acceptance["required_accepts"] == 299
    assert acceptance["meets_risk_bar"] is True


def test_subclass_accuracy_is_conditioned_on_the_class():
    """Only class-correct rows with a scorable subclass enter subclass accuracy."""
    card = score_review_lane(_population())
    subclass = card["quality"]["subclass"]
    assert subclass["subclass_scored"] == 6
    assert subclass["subclass_correct"] == 4
    assert subclass["subclass_accuracy"] == pytest.approx(0.666667, abs=1e-6)
    assert subclass["accepted_subclass_wrong"] == 1


def test_verdict_confusion_uses_the_derivable_expected_verdict():
    """The model's verdict is scored against the sorter handoff and target."""
    card = score_review_lane(_population())
    verdict = card["quality"]["verdict"]
    assert verdict["n"] == 9
    assert verdict["verdict_accuracy"] is not None
    assert verdict["verdicts_by_expected"]["continue_sorter_correct"][
        "continue_sorter_correct"
    ] >= 4
    assert "route_to_human_review" in verdict["human_verdicts"]


def test_calibration_reports_ece_brier_and_confidence_split():
    """Calibration is over answered rows with a valid confidence and target."""
    card = score_review_lane(_population())
    calibration = card["calibration"]
    assert calibration["n"] == 8
    assert calibration["ece"] is not None
    assert calibration["brier"] is not None
    assert calibration["mean_confidence_wrong"] is not None


def test_routing_counts_causes_and_human_review_rate():
    """Every cause is counted and the human-review rate uses the reached set."""
    card = score_review_lane(_population())
    routing = card["routing"]
    assert routing["n_reached"] == 10
    assert routing["routed_to_human_review"] == 6
    assert routing["routed_to_human_review_rate"] == 0.6
    assert routing["cause_counts"]["reviewer_low_confidence"] == 2
    assert card["routed_to_human_review"] == 6
    assert card["routed_to_human_review_basis"] == "reviewer"


def test_accept_rule_violations_fail_closed():
    """An accepted row without a cutoff is named, and the rule flag is false."""
    card = score_review_lane(_population())
    routing = card["routing"]
    assert routing["accept_rule_ok"] is False
    assert routing["accept_rule_violations"] == [
        {"doc_id": "no-cutoff", "violations": ["accept_without_cutoff"]}
    ]


def test_cost_is_reported_only_when_every_row_is_priced():
    """A partial cost set is not presented as the whole run."""
    card = score_review_lane(_population())
    cost = card["cost"]
    assert cost["complete"] is True
    assert cost["total_usd"] == 0.01
    assert cost["per_accepted_usd"] == 0.0025
    partial = score_review_lane(
        [_record(doc_id="a"), _record(doc_id="b", cost_usd=None)]
    )
    assert partial["cost"]["complete"] is False
    assert partial["cost"]["total_usd"] is None
    assert partial["cost"]["priced_total_usd"] == 0.001


def test_groups_by_model_and_question_set():
    """Per-model and per-question-set views are present and independent."""
    card = score_review_lane(_population())
    assert set(card["by_model"]) == {"gpt-6-luna-decisions"}
    assert set(card["by_question_set"]) == {"3.1.0"}
    assert card["by_model"]["gpt-6-luna-decisions"]["quality"]["class_accuracy"] == 0.75
    assert card["provenance"]["prompt_id"] == "3.1.0"
    assert card["provenance"]["metric_id"] == "review.lane.class_accuracy"


def test_operating_points_expose_a_cutoff_and_curve():
    """Each predicted class reports a target cutoff, a risk cutoff, and a curve."""
    card = score_review_lane(_population())
    contract = card["operating_points"]["contract"]
    assert contract["n"] > 0
    assert "cutoff_at_target" in contract
    assert contract["curve"]


def test_reviewer_scorecard_scales_to_a_thousand_documents():
    """A 1,000+ document reviewer run stays linear and keeps the risk bound exact."""
    rows = [_record(doc_id=f"ok-{index}") for index in range(1_200)]
    rows.append(
        _record(
            doc_id="wrong",
            expected_doc_type="correspondence",
            expected_doc_subclass="email",
            sorter_doc_type="correspondence",
            sorter_doc_subclass="email",
            reviewer_doc_type="contract",
            reviewer_doc_subclass="license",
        )
    )
    card = score_review_lane(rows)
    assert card["n"] == 1_201
    assert card["acceptance"]["n_accepted"] == 1_201
    assert card["acceptance"]["n_wrong_accepts"] == 1
    assert card["acceptance"]["required_accepts"] == 473
    assert card["acceptance"]["meets_risk_bar"] is True
    assert card["operating_points"]["contract"]["n"] >= 1


@pytest.mark.parametrize(
    "accepted,wrong,meets",
    [
        (536, 0, True),
        (405, 1, False),
        (896, 1, True),
        (985, 0, True),
        (135, 0, False),
    ],
)
def test_v3_report_bounds_expose_the_qualification_gap(accepted, wrong, meets):
    """Corporate and merger do not clear the 1% bar on the current v3 sample."""
    upper = clopper_pearson_upper(wrong, accepted)
    assert (upper <= 0.01) is meets


def test_empty_population_returns_nulls_not_zeros():
    """No records is no evidence, not a perfect score."""
    card = score_review_lane([])
    assert card["n"] == 0
    assert card["quality"]["class_accuracy"] is None
    assert card["acceptance"]["wrong_accept_upper_95"] is None
    assert card["routing"]["accept_rule_ok"] is True


def test_from_mapping_accepts_pipeline_and_run_store_aliases():
    """A run-store row maps without a consumer-specific adapter."""
    record = ReviewRecord.from_mapping(
        {
            "item_id": "doc-1",
            "expected_doc_class": "contract",
            "expected_subclass": "license",
            "sorter_doc_type": "contract",
            "reviewer_doc_type": "contract",
            "reviewer_confidence": 0.97,
            "review_verdict": "decision_accepts",
            "review_route": "extract",
            "review_causes": [],
            "reviewer_model": "m",
            "questions": "3.1.0",
        }
    )
    assert record.doc_id == "doc-1"
    assert record.expected_doc_type == "contract"
    assert record.route == "extract"
    assert record.route_verdict == "decision_accepts"
    assert record.question_set == "3.1.0"


def test_run_item_adapter_joins_pred_truth_handoff_and_cutoffs():
    """The sandbox's item/dataset/handoff/lock shape maps without custom glue."""
    record = review_record_from_run_item(
        {
            "item_id": "doc-1",
            "ok": True,
            "pred": {
                "doc_type": "contract",
                "doc_subclass": "license",
                "confidence": 0.91,
                "verdict": "continue_sorter_correct",
                "route_to_human": False,
                "usage": {"input_tokens": 900, "output_tokens": 0, "cost": 0.00009},
            },
        },
        truth={"expected_doc_class": "contract", "expected_subclass": "license"},
        handoff={
            "sorter_doc_type": "contract",
            "sorter_doc_subclass": "license",
            "sorter_confidence": 0.93,
            "review_trigger": ["decision_class_review"],
        },
        cutoffs={"contract": 0.8},
        lock={
            "reviewer": {"model": "openai/gpt-6-luna-decisions", "questions": "3.1.0"},
            "dataset": {"revision": "r1", "split": "train", "sample_seed": 42},
            "engine": {"kind": "openrouter"},
        },
    )
    assert record.doc_id == "doc-1"
    assert record.expected_doc_type == "contract"
    assert record.sorter_doc_type == "contract"
    assert record.reviewer_confidence == 0.91
    assert record.route is None  # derived from cutoff + agreement, not forced
    assert record.cutoff == 0.8
    assert record.reviewer_model == "openai/gpt-6-luna-decisions"
    assert record.question_set == "3.1.0"
    assert record.cost_usd == 0.00009
    assert record.dataset_revision == "r1"


def test_human_verdicts_are_the_four_human_routes():
    """The human-verdict set is stable and excludes continue/reclassify."""
    assert set(HUMAN_VERDICTS) == {
        "route_to_human_review",
        "unreadable",
        "out_of_scope",
        "multiple_documents",
    }


# --- PR #103 review regressions -------------------------------------------


def test_run_item_adapter_keeps_measured_zero_cost_and_tokens():
    """A free model reporting ``cost: 0.0`` is priced, not unpriced."""
    record = review_record_from_run_item(
        {
            "item_id": "free",
            "pred": {
                "doc_type": "contract",
                "confidence": 0.99,
                "usage": {"cost": 0.0, "cost_usd": 5.0, "input_tokens": 0, "output_tokens": 0,
                          "prompt_tokens": 7, "completion_tokens": 9},
            },
        },
        truth={"expected_doc_class": "contract"},
        handoff={"sorter_doc_type": "contract"},
        cutoffs={"contract": 0.8},
    )
    assert record.cost_usd == 0.0
    assert record.prompt_tokens == 0
    assert record.completion_tokens == 0
    card = score_review_lane([record])
    assert card["cost"]["complete"] is True
    assert card["cost"]["total_usd"] == 0.0


def test_run_item_adapter_falls_back_when_the_primary_usage_key_is_absent():
    """``cost_usd`` is used when ``cost`` is absent."""
    record = review_record_from_run_item(
        {"item_id": "x", "pred": {"doc_type": "contract", "usage": {"cost_usd": 0.002}}}
    )
    assert record.cost_usd == 0.002


def test_inferred_route_without_a_cutoff_is_not_an_auto_accept():
    """With no recorded route, a missing cutoff cannot fall through to extract."""
    card = score_review_lane([_record(route=None, cutoff=None)])
    assert card["acceptance"]["n_accepted"] == 0
    assert card["routing"]["n_human_review"] == 1
    assert card["routing"]["accept_rule_violations"] == []


def test_inferred_route_without_a_confidence_is_not_an_auto_accept():
    """A missing reviewer confidence keeps an unrouted row out of the accepts."""
    card = score_review_lane([_record(route=None, reviewer_confidence=None)])
    assert card["acceptance"]["n_accepted"] == 0


def test_inferred_route_with_an_ineligible_label_is_not_an_auto_accept():
    """An ineligible label keeps an unrouted row out of the accepts."""
    card = score_review_lane([_record(route=None, eligible=False)])
    assert card["acceptance"]["n_accepted"] == 0
    assert card["routing"]["n_human_review"] == 1


def test_inferred_route_that_passes_the_accept_rule_is_still_accepted():
    """A clean unrouted row is still inferred as an auto-accept."""
    card = score_review_lane([_record(route=None)])
    assert card["acceptance"]["n_accepted"] == 1
    assert card["routing"]["accept_rule_ok"] is True


def test_recorded_extract_route_still_reports_its_violations():
    """A pipeline that recorded ``extract`` without a cutoff is flagged, not hidden."""
    card = score_review_lane([_record(route="extract", cutoff=None)])
    assert card["acceptance"]["n_accepted"] == 1
    violations = card["routing"]["accept_rule_violations"]
    assert violations and "accept_without_cutoff" in violations[0]["violations"]


def test_missing_predicted_subclass_counts_as_a_subclass_miss():
    """A right class with no subclass answer must not inflate subclass accuracy."""
    card = score_review_lane(
        [
            _record(doc_id="a"),
            _record(doc_id="b", reviewer_doc_subclass=None),
        ]
    )
    subclass = card["quality"]["subclass"]
    assert subclass["subclass_scored"] == 2
    assert subclass["subclass_correct"] == 1
    assert subclass["subclass_accuracy"] == 0.5
    assert subclass["accepted_subclass_wrong"] == 1
    assert card["subclass_accuracy"] == 0.5


def test_unscorable_target_subclass_is_still_excluded():
    """Merger ``other`` stays out of subclass scoring even with no prediction."""
    card = score_review_lane(
        [
            _record(
                expected_doc_type="merger_agreement",
                expected_doc_subclass="other",
                sorter_doc_type="merger_agreement",
                reviewer_doc_type="merger_agreement",
                reviewer_doc_subclass=None,
            )
        ]
    )
    assert card["quality"]["subclass"]["subclass_scored"] == 0


def _key_shape(value):
    """Nested key structure of a scorecard (dict keys only, not values)."""
    if isinstance(value, dict):
        return {key: _key_shape(item) for key, item in value.items()}
    return None


def test_empty_scorecard_has_the_same_keys_as_a_non_empty_one():
    """Consumers reading ``card["routed_to_human_review"]`` must not KeyError on []."""
    empty = score_review_lane([])
    full = score_review_lane([_record()])
    assert set(empty) == set(full)
    for section in ("acceptance", "routing", "calibration", "cost"):
        assert set(empty[section]) == set(full[section]), section
    assert set(empty["quality"]) == set(full["quality"])
    assert set(empty["quality"]["subclass"]) == set(full["quality"]["subclass"])
    assert set(empty["quality"]["verdict"]) == set(full["quality"]["verdict"])


def test_empty_scorecard_values_match_the_zero_accept_defaults():
    """The empty card uses nulls/zeros and the zero-error sample size."""
    empty = score_review_lane([], risk=0.02, confidence=0.9)
    assert empty["n"] == 0
    assert empty["routed_to_human_review"] == 0
    assert empty["routed_to_human_review_rate"] is None
    assert empty["subclass_accuracy"] is None
    assert empty["verdicts_by_expected"] == {}
    assert empty["acceptance"]["risk"] == 0.02
    assert empty["acceptance"]["confidence"] == 0.9
    assert empty["acceptance"]["meets_risk_bar"] is False
    from llm_dojo_scoring.analysis.calibration import required_samples

    assert empty["acceptance"]["required_accepts"] == required_samples(0, risk=0.02, confidence=0.9)


def test_unanswered_accept_with_truth_is_not_counted_as_missing_truth():
    """A labelled accept with no usable reviewer answer is counted on its own."""
    records = [
        _record(doc_id="graded"),
        _record(doc_id="no-gt", expected_doc_type=None, expected_doc_subclass=None),
        _record(doc_id="reviewer-error", error="timeout", reviewer_doc_type=None),
    ]
    acceptance = score_review_lane(records)["acceptance"]
    assert acceptance["n_accepted"] == 3
    assert acceptance["n_accepted_with_truth"] == 1
    assert acceptance["n_accepted_without_truth"] == 1
    assert acceptance["n_accepted_unanswered"] == 1
    assert score_review_lane([])["acceptance"]["n_accepted_unanswered"] == 0
