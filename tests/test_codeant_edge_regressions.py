"""CodeAnt boundary regressions: absent labels never manufacture support."""
import pytest
from llm_dojo_scoring import intake, legalbench_scoring, pilot_labels
from llm_dojo_scoring import sandbox_schema_adherence as schema
from llm_dojo_scoring import sandbox_scoring as benchmark


@pytest.mark.parametrize('value', [float('inf'), -float('inf'), float('nan')])
def test_invalid_integer_metadata_is_a_mismatch(value):
    """Non-finite metadata follows the documented invalid-conversion contract."""
    assert intake._int_match(value, 1) == 0.0
    assert intake._int_match(1, value) == 0.0
    assert intake._int_match(None, value) is None


@pytest.mark.parametrize('blank', ['', ' ', None])
def test_blank_legalbench_labels_are_unscorable(blank):
    """Only rows with actual expected and predicted labels enter the report."""
    bad = {'status': 'ok', 'expected': blank, 'predicted': blank, 'correct': False}
    good = {'status': 'ok', 'expected': 'license', 'predicted': 'license', 'correct': True}
    result = legalbench_scoring.score_multiclass([bad, good])
    assert result['n_documents'] == 1 and result['n_error'] == 1
    assert result['accuracy'] == result['accuracy_equiv'] == 1.0


@pytest.mark.parametrize('groups', [None, [('license', 'softwarelicense')]])
@pytest.mark.parametrize('missing', [None, ''])
def test_unresolved_contract_subclasses_are_not_equivalent(groups, missing):
    """Raw nonblank GT cannot match two absent normalized candidates."""
    assert pilot_labels.pilot_subclass_match('contract', 'unrecognized GT',
        sorter_token=missing, expected_token=missing, contract_equivalences=groups) is False
    assert pilot_labels.pilot_subclass_match('contract', None) is None
    assert pilot_labels.pilot_subclass_match('contract', 'license',
        sorter_token='license', expected_token='license', contract_equivalences=groups) is True


@pytest.mark.parametrize('keys', [(), ('sender',)])
def test_fallback_metadata_only_payload_has_no_schema_fields(keys):
    """Metadata is not evidence of a parsed extraction object with fields."""
    assert schema.assess_extraction_facts({'confidence': .9, 'reasoning': 'ok'}, {},
        schema_keys=keys)['schema_valid'] is False
    assert schema.assess_extraction_facts({'sender': None}, {},
        schema_keys=keys)['schema_valid'] is True


@pytest.mark.parametrize('encoded', [False, True])
def test_json_null_maud_label_is_missing_but_literal_none_is_a_real_class(encoded):
    """JSON null never becomes the catalog's meaningful string answer None."""
    import json
    question = 'Agreement provides for matching rights in connection with COR'
    null = {question: {'answer': None}}
    literal = {question: {'answer': 'None'}}
    if encoded:
        null, literal = json.dumps(null), json.dumps(literal)
    assert question not in benchmark.gt_labels(null)
    assert benchmark.gt_labels(literal)[question] == 'None'
    assert benchmark.score_maud({question: 'None'}, null)['maud_questions'] == 0


def test_legalbench_can_bind_producer_equivalences_without_global_mutation():
    """A consumer's frozen policy survives supported global configuration."""
    from llm_dojo_scoring.config import configure_from_taxonomy, get_settings
    original = get_settings().subtype_equivalences
    row = {'status': 'ok', 'expected': 'license', 'predicted': 'maintenance', 'correct': False}
    try:
        configure_from_taxonomy({'subtype_equivalences': []})
        assert legalbench_scoring.score_multiclass([row])['accuracy_equiv'] == 0.0
        bound = legalbench_scoring.score_multiclass([row], subtype_equivalences=[['license', 'maintenance']])
        assert bound['accuracy_equiv'] == 1.0
        assert get_settings().subtype_equivalences == []
    finally:
        configure_from_taxonomy({'subtype_equivalences': original})


def test_pilot_calibration_aggregates_unrounded_errors_then_rounds_once():
    """Per-row rounding would incorrectly change this report from .001 to .000."""
    from llm_dojo_scoring.pilot_summary import pilot_calibration_error
    assert pilot_calibration_error([(.00049, False), (.00049, False), (.00149, False)]) == .001
    assert pilot_calibration_error([]) is None
    assert pilot_calibration_error([(.9, True), (.2, False)]) == .15


@pytest.mark.parametrize("side", ["expected", "predicted", "both"])
@pytest.mark.parametrize("correct", [False, True])
def test_nan_legalbench_labels_are_unscorable(side, correct):
    """A missing numeric label cannot enter any report denominator or calibration."""
    bad = {"status": "ok", "expected": "license", "predicted": "license",
           "correct": correct, "family": "missing", "confidence": 1.0}
    for key in ("expected", "predicted"):
        if side in (key, "both"):
            bad[key] = float("nan")
    good = {"status": "ok", "expected": "license", "predicted": "license",
            "correct": True, "family": "license", "confidence": 0.5}
    assert legalbench_scoring.score_multiclass([bad, good]) == {
        "accuracy": 1.0, "accuracy_equiv": 1.0, "macro_f1": 1.0,
        "n_documents": 1, "n_error": 1, "n_other_predicted": 0,
        "n_other_labeled": 0, "confidence_mean": 0.5,
        "calibration_error": 0.5, "per_family": {"license": 1.0},
    }
    empty = legalbench_scoring.score_multiclass([bad])
    assert empty["n_documents"] == 0 and empty["n_error"] == 1
    assert empty["accuracy_equiv"] == empty["confidence_mean"] == 0.0
    assert empty["per_family"] == {}


@pytest.mark.parametrize("label", [0, False, 0.0, 1, "nan", "None", "other"])
def test_legalbench_nonmissing_falsy_and_literal_labels_keep_support(label):
    """Public row values are Any; missing detection must not become a truthiness filter."""
    row = {"status": "ok", "expected": label, "predicted": label, "correct": True}
    result = legalbench_scoring.score_multiclass([row])
    assert result["n_documents"] == 1 and result["n_error"] == 0
    assert result["accuracy"] == result["accuracy_equiv"] == 1.0
