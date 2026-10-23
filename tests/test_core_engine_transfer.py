"""Hand-count contracts for additive pipeline/LegalBench/isolation engines."""
import math
import pytest
from llm_dojo_scoring import pipeline_scoring as ps
from llm_dojo_scoring import legalbench_scoring as lb
from llm_dojo_scoring import agent_rubrics as ar


def test_strict_classes_cardinality_and_errors():
    """No regex recovery, no empty-label hit, no silently truncated generators."""
    assert ps.classes_match(" CONTRACT ", "contract")
    for exp, pred in [(None, None), (" ", " "), ("contract", None),
                      ("contract", "not a contract"), ("merger_agreement", "contract"),
                      ("contract", "ERROR: timeout")]:
        assert not ps.classes_match(exp, pred)
    assert ps.score_exact_classification(["a", "a", None], ["a", None, None]) == {
        "n": 3, "exact_n": 1, "exact_accuracy": 0.333, "aligned_n": 1,
        "aligned_accuracy": 0.333, "aligned_equals_exact": True,
    }
    with pytest.raises(ValueError, match="expected length 2 != predicted length 1"):
        ps.score_exact_classification(iter(["a", "b"]), iter(["a"]))


def test_raw_experiment_union_and_stage_population():
    """False-positive-only classes join macro F1; missing GT stays a miss."""
    rows = [
        {"expected": "contract", "got": " CONTRACT ", "has_stage": True, "stage_ok": True},
        {"expected": "contract", "got": "surprise", "has_stage": False},
        {"expected": "corporate_record", "got": None, "has_stage": True, "stage_ok": False},
        {"expected": None, "got": None, "has_stage": False},
    ]
    assert ps.score_experiment_rows(rows) == {
        "class_accuracy": 0.25, "macro_class_accuracy": 0.1667,
        "macro_f1": 0.1667, "stage_accuracy": 0.5,
    }
    assert ps.score_experiment_rows([]) == {}
    assert "stage_accuracy" not in ps.score_experiment_rows([{"expected": "a", "got": None}])
    with pytest.raises(ValueError, match="expected length"):
        ps.raw_classification_stats(["a", "b"], ["a"])
    with pytest.raises(ValueError, match="expected length"):
        ps.raw_classification_stats(["a"], ["a"], correct=[])
    with pytest.raises(ValueError, match="label_universe"):
        ps.raw_classification_stats([], [], label_universe="all")


def test_binary_category_population_and_nonfinite_confidence():
    """Error rows excluded; A accuracy 2/3, B zero; yes TP=FP=FN=1."""
    rows = [
        {"status": "ok", "category": "A", "expected": "yes", "predicted": "yes", "correct": True, "confidence": 0.5},
        {"status": "ok", "category": "A", "expected": "no", "predicted": "no", "correct": True, "confidence": 0.5},
        {"status": "ok", "category": "A", "expected": "yes", "predicted": "no", "correct": False, "confidence": float("nan")},
        {"status": "ok", "category": "B", "expected": "no", "predicted": "yes", "correct": False, "confidence": float("inf")},
        {"status": "error", "predicted": "yes"}, {"status": "ok", "predicted": None},
        {"status": "ok", "predicted": "error"},
    ]
    assert lb.score_binary(rows) == {
        "accuracy": 0.5, "macro_category_accuracy": 0.3333, "yes_f1": 0.5,
        "n_questions": 4, "n_yes": 2, "n_no": 2, "n_error": 3,
        "confidence_mean": 0.5, "calibration_error": 0.5,
        "per_category": {"A": 0.6667, "B": 0.0},
    }
    # Missing GT is not filtered; explicit producer flags remain authoritative.
    assert lb.score_binary([{"status": "ok", "expected": None, "predicted": "no", "correct": True}])["accuracy"] == 1.0
    assert lb.score_binary([])["n_questions"] == 0
    assert lb.score_binary([{"status": "error"}])["n_error"] == 1


def test_ece_is_binned_not_mean_absolute_error():
    """Half-confidence half-correct bucket is perfectly calibrated."""
    assert lb.expected_calibration_error([(0.5, True), (0.5, False)]) == 0.0
    assert lb.expected_calibration_error([(0.0, True), (1.0, False)]) == 1.0
    assert math.isnan(lb.expected_calibration_error([(float("nan"), True)]))
    with pytest.raises(OverflowError, match="infinity"):
        lb.expected_calibration_error([(float("inf"), False)])
    assert lb.expected_calibration_error([]) == 0.0


def test_multiclass_expected_family_f1_and_equivalence():
    """Macro over three GT families: mean(0,2/3,2/3), not union with other."""
    rows = [
        {"status": "ok", "family": "maintenance", "expected": "maintenance", "predicted": "license", "correct": False},
        {"status": "ok", "family": "license", "expected": "license", "predicted": "license", "correct": True},
        {"status": "ok", "family": "distributor", "expected": "distributor", "predicted": "distributor", "correct": True},
        {"status": "ok", "family": "distributor", "expected": "distributor", "predicted": "other", "correct": False},
        {"status": "error"},
    ]
    assert lb.score_multiclass(rows) == {
        "accuracy": 0.5, "accuracy_equiv": 0.75, "macro_f1": 0.4444,
        "n_documents": 4, "n_error": 1, "n_other_predicted": 1, "n_other_labeled": 0,
        "confidence_mean": 0.0, "calibration_error": 0.0,
        "per_family": {"distributor": 0.5, "license": 1.0, "maintenance": 0.0},
    }
    assert lb.score_multiclass([])["macro_f1"] == 0.0
    # Group and expected need not agree: preserve the old support/flag contract.
    inconsistent = [{"status": "ok", "family": "group", "expected": "a", "predicted": "group", "correct": True}]
    assert lb.score_multiclass(inconsistent)["macro_f1"] == 1.0


def test_literal_visualizer_predicates_do_not_become_pipeline_normalization():
    """Keep literal alignment and exact subclasses; missing labels stay misses."""
    assert not ps.pipeline_labels_equal(None, None)
    assert not ps.pipeline_labels_equal(" CONTRACT ", "contract")
    assert not ps.pipeline_classes_aligned(" CONTRACT ", "contract")
    assert not ps.pipeline_classes_aligned("merger_agreement", "contract")
    assert not ps.pipeline_classes_aligned("contract", None)
    # Missing GT must not match an absent alias entry.
    assert not ps.pipeline_classes_aligned(None, "contract")
    assert ps.pipeline_subclass_match(" LICENSE ", "license")
    assert not ps.pipeline_subclass_match("maintenance", "license")
    assert not ps.pipeline_subclass_match(None, None)
    assert not ps.pipeline_subclass_match("other", "alien")
    assert not ps.pipeline_subclass_match(" ", " ")


@pytest.mark.parametrize("row,mode", [
    ({"stage": "failed", "error": "bad", "aligned_ok": True}, "failed"),
    ({"error": "bad"}, "error"),
    ({"stage": "review", "expected": "a"}, "review"),
    ({"stage": "human_review"}, "review"),
    ({"stage": "archived", "expected": "a"}, "wrong_class"),
    ({"expected": "a", "aligned_ok": True, "extracted_data": {}}, "ok"),
    ({"stage": "archive", "extracted_data": {"_meta": 1}}, "empty_extract"),
    ({"stage": "archived", "extracted_data": {}, "error": "bad"}, "ok"),
    ({"stage": "report", "extracted_data": {"zero": 0}}, "ok"),
    ({}, "unknown_stage"), ({"stage": "working"}, "wrong_class"),
])
def test_lifecycle_failure_priority(row, mode):
    """Pipeline stage/error priority must not turn into sorter failure modes."""
    assert ps.classify_pipeline_failure(row) == mode


def test_visualizer_rows_flags_missing_gt_and_asymmetric_subclasses():
    """All five rows count; only four with subclass GT form subclass support."""
    rows = [
        {"expected": "contract", "predicted": "contract", "exact_ok": True, "aligned_ok": True, "stage": "archived", "expected_subclass": "license", "predicted_subclass": "LICENSE"},
        {"expected": "merger_agreement", "predicted": "contract", "stage": "archived", "expected_subclass": "cash", "predicted_subclass": "cash", "subclass_ok": False},
        {"expected": None, "predicted": None, "stage": "archived", "predicted_subclass": "license"},
        {"expected": "contract", "predicted": None, "stage": "failed", "expected_subclass": "license"},
        {"expected": "contract", "predicted": "contract", "stage": "review", "exact_ok": True, "aligned_ok": True, "expected_subclass": "other", "predicted_subclass": "alien"},
    ]
    result = ps.score_pipeline_rows(rows)
    assert result == {
        "n": 5, "exact_accuracy": 0.4, "aligned_accuracy": 0.4, "n_subclass": 4,
        "subclass_accuracy": 0.25,
        "failure_modes": {"ok": 2, "wrong_class": 1, "failed": 1, "review": 1},
        "by_class": {"contract": {"n": 3, "exact": 2, "aligned": 2}, "merger_agreement": {"n": 1, "exact": 0, "aligned": 0}, "unknown": {"n": 1, "exact": 0, "aligned": 0}},
        "confusion": {"contract": {"contract": 2, "none": 1}, "merger_agreement": {"contract": 1}, "unknown": {"none": 1}},
    }
    assert ps.score_pipeline_rows([])["subclass_accuracy"] is None
    assert ps.score_pipeline_rows([{"exact_ok": True}])["exact_accuracy"] == 1.0


def test_isolation_rubrics_are_literal_and_have_explicit_empty_support():
    """Token multiplicity ignored; keys in values count, absent GT stays None."""
    assert ar.token_set_f1("A a b", "a c") == 0.5
    assert ar.token_set_f1("", "") == 1.0
    assert ar.token_set_f1("a,", "a") == 0.0
    assert ar.key_presence('{"note": "party"}', ["party", "date"]) == 0.5
    assert ar.key_presence("Party", ["party"]) == 0.0
    assert ar.key_presence("", []) is None
    assert ar.decision_valid("approved", ("approved", "review")) == 1
    assert ar.decision_valid(None, ("approved", "review")) == 0


def test_local_pack_homogeneity_ignores_unlabeled_without_fabricating_support():
    """Preserve approved aliases and the historical reason-list policy."""
    approved = {"coverage_determination": " Covered ", "denial_reasons": []}
    assert ar.insurance_expected_set_is_homogeneous([{}, approved])
    assert not ar.insurance_expected_set_is_homogeneous([{}, None])
    assert not ar.insurance_expected_set_is_homogeneous([approved, {"coverage_determination": "denied"}])
    assert not ar.insurance_gt_is_homogeneous(dict(approved, denial_reasons=[None]))
    assert ar.determination_consistency_is_quality({}) is True


def test_missing_or_blank_labels_never_create_grounded_matches():
    """Absent alias lookups and blank subclasses are not scoring evidence."""
    for expected, predicted in [(None, None), (None, "contract"), ("", "contract"), (" ", " ")]:
        assert not ps.pipeline_labels_equal(expected, predicted)
        assert not ps.pipeline_classes_aligned(expected, predicted)
    assert not ps.pipeline_subclass_match(" ", " ")
    result = ps.score_pipeline_rows([{"expected_subclass": " ", "predicted_subclass": " "}])
    assert result["n_subclass"] == 0
    assert result["subclass_accuracy"] is None
