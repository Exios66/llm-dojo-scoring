"""Hand-counted contracts for final source-owned primary quality policies."""
import math
import pytest
from llm_dojo_scoring import get_suite
from llm_dojo_scoring.field_support import pilot_ground_truth_scores, schema_gt_support, field_audit_support
from llm_dojo_scoring.pilot_summary import pilot_classification_summary
from llm_dojo_scoring.pilot_labels import pilot_subclass_match, normalize_sorter_token, normalize_inventory_label
from llm_dojo_scoring.sandbox_agent_scoring import label_match, contains_match, reporter_keys
from llm_dojo_scoring.scorecard_honesty import aggregate_quality_honest
from llm_dojo_scoring.pipeline_scoring import score_exact_classification


def test_required_fields_are_not_schema_coverage():
    """Seven required keys, only three present; blank/None expectations excluded."""
    expected = {"a": [], "b": {}, "c": False, "d": 0, "e": " ", "f": [None], "g": "x", "skip": None, "blank": ""}
    predicted = {"a": [], "b": {}, "c": False, "d": 0, "e": " ", "f": [None], "g": "wrong"}
    out = pilot_ground_truth_scores(True, False, predicted, expected, .6666)
    assert out == {"class_correct": 1, "stage_correct": 0, "expected_field_presence": .429, "confidence_calibration_error": .333}
    assert schema_gt_support(list(expected), expected) == {"n_schema": 9, "n_labeled": 5, "labeled_fields": ["c", "d", "e", "f", "g"], "coverage": .556}


@pytest.mark.parametrize("confidence", [True, False, None, "0.4"])
def test_calibration_nonnumeric_and_bool_omitted(confidence):
    """Bool is never accepted as a confidence measurement."""
    assert pilot_ground_truth_scores(False, True, {}, {}, confidence) == {"class_correct": 0, "stage_correct": 1}


def test_calibration_retains_unbounded_and_nonfinite_legacy_values():
    """No new clamping or finite-value convention sneaks into an exact transfer."""
    assert pilot_ground_truth_scores(0, 0, {}, {}, -1.25)["confidence_calibration_error"] == 1.25
    assert math.isnan(pilot_ground_truth_scores(1, 0, {}, {}, float('nan'))["confidence_calibration_error"])
    assert schema_gt_support([], {})["coverage"] is None


def test_audit_support_is_mean_of_eligible_fields_not_entities():
    """1 predicted versus 9 predicted fields each receive one vote; zero retained."""
    audit = {"a": {"n_predicted": 1, "verified_precision": 1., "hallucination_rate": 0.}, "b": {"n_predicted": 9, "verified_precision": 0., "hallucination_rate": 1.}, "skip": {"n_predicted": 0, "verified_precision": 100., "hallucination_rate": 100.}}
    assert field_audit_support(audit) == {"n_audited": 2, "verified_precision": .5, "hallucination_rate": .5}
    assert field_audit_support({}) == {"n_audited": 0, "verified_precision": None, "hallucination_rate": None}
    with pytest.raises(KeyError, match="hallucination_rate"):
        field_audit_support({"broken": {"n_predicted": 1, "verified_precision": 0.}})


def test_actual_suite_result_has_canonical_audit_support():
    """Execute real correspondence field audits, without replacing any scorer."""
    payload = get_suite('correspondence_specialist').score_document(
        {"sender": "Alice", "subject_matter": "meeting"},
        {"sender": "Alice", "subject_matter": "meeting"}, doc_text='Alice meeting')
    result = payload['extraction']
    assert result.audit_support['n_audited'] == 2
    assert result.audit_support['verified_precision'] == 1.
    assert result.audit_support['hallucination_rate'] == 0.
    assert 'audit_support' not in result.to_dict()  # published serialization unchanged


def test_pilot_populations_and_rounding():
    """All 4 rows class support, 2 subclass flags, including a truthy flag sans GT."""
    rows = [
        {"expected": 'contract', "predicted": ' CONTRACT ', "subclass_ok": True, "expected_subclass": 'license'},
        {"expected": 'contract', "predicted": 'merger_agreement', "exact_ok": True, "subclass_ok": False},
        {"expected": 'corporate_record', "exact_ok": True},
        {"expected": None, "exact_ok": True},
    ]
    out = pilot_classification_summary(rows)
    assert (out['exact_n'], out['exact_accuracy'], out['subclass_n'], out['subclass_correct'], out['subclass_accuracy']) == (2, .5, 2, 1, .5)
    assert out['per_class']['unknown']['exact'] == 1  # per-class legacy flag differs from strict aggregate
    assert out['per_class']['contract']['exact_accuracy'] == .5
    assert out['per_subclass'][('contract', '_')]['subclass_accuracy'] == 0.
    assert pilot_classification_summary([])['subclass_accuracy'] is None
    with pytest.raises(ValueError, match='length'):
        score_exact_classification(iter(['a', 'b']), iter(['a']))


def test_subclass_tokens_and_asymmetric_support():
    """Unknown-to-other is retained; absent GT differs from absent prediction."""
    assert pilot_subclass_match('contract', '') is None
    assert pilot_subclass_match('contract', 'license', sorter_token='maintenance', expected_token='license') is True
    assert pilot_subclass_match('contract', 'license', sorter_token='other', expected_token='license') is False
    assert normalize_sorter_token('corporate_record', 'alien', {'other', 'bylaws'}) == 'other'
    assert normalize_sorter_token('correspondence', 'alien', {'email'}) is None
    assert pilot_subclass_match('corporate_record', 'alien', sorter_token='other', expected_token='other') is True
    assert pilot_subclass_match('insurance_claim', 'auto', sorter_token=None, expected_token='auto', loose_predicted='') is False
    assert normalize_inventory_label('Attorney demand document', ('demand','attorney_demand'), {}) == 'attorney_demand'


def test_sandbox_rubrics_keep_literal_blank_case_and_key_quirks():
    """Case-sensitive classes, lowercase labels without strip, literal substring keys."""
    assert label_match('', '') == 1.
    assert label_match('contract', 'CONTRACT') == 0.
    assert label_match('OK', 'ok', lowercase=True) == 1.
    assert label_match(' ok', 'ok', lowercase=True) == 0.
    assert contains_match('', ' ') == 1.
    assert contains_match('foo', 'FOOBAR') == 1.
    assert reporter_keys({'x': 'SUMMARY confidence'}, ['summary','confidence']) == {'match': 1., 'missing': ['summary','confidence'], 'keys': ['x']}
    assert reporter_keys({}, ['summary']) == {'match': 0., 'missing': ['summary']}


def test_honest_aggregate_known_zero_mixed_and_no_gt():
    """Two scored of four attempted: (1+0)/2, not 1/4; missing GT is not zero."""
    result = aggregate_quality_honest([{'overall_score': 1.}, {'overall_score': 0.}, {'status': 'unscorable', 'overall_score': None}, {'status': 'error'}])
    assert result == {'n_scored': 2, 'n_unscorable': 1, 'quality_mean': .5, 'quality_population': 'scored_only', 'export_verdict': 'scored'}
    assert aggregate_quality_honest([{'status':'unscorable','overall_score':None}])['quality_mean'] is None


def test_explicit_equivalence_policy_is_separate_from_published_task_defaults(monkeypatch):
    """Frozen pipeline groups remain literal while Dojo global settings still work."""
    from llm_dojo_scoring.config import get_settings
    from llm_dojo_scoring.equivalences import equivalent_subtypes
    from llm_dojo_scoring.pilot_labels import catalog_subtypes_equivalent
    monkeypatch.setattr(get_settings(),'subtype_equivalences',[])
    assert equivalent_subtypes('license','maintenance') is False
    assert catalog_subtypes_equivalent('license','maintenance',[frozenset({'license','maintenance'})]) is True
