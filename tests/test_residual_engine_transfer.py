"""Hand-computed controls for the exact residual engine namespaces."""
import math
import pytest
from llm_dojo_scoring import sandbox_schema_adherence as schema
from llm_dojo_scoring.pipeline_verdict import deterministic_verdict_label as verdict


@pytest.mark.parametrize('score,review,mismatch,band,want', [
    (None,False,False,None,'PARTIAL'), (None,True,True,None,'MISS'),
    (1,True,False,None,'PARTIAL'), (0,False,False,None,'MISS'),
    (.5,False,False,None,'MISS'), (.85,False,False,None,'CORRECT'),
    (.7,False,False,None,'PARTIAL'), (.8,False,False,[.2,.8],'CORRECT'),
    (.2,False,False,[.2,.8],'MISS'), (.7,False,False,[.9,.4],'CORRECT'),
    (.85,False,False,['bad',.1],'CORRECT'), (.85,False,False,[],'CORRECT'),
    (.85,False,False,[.2],'CORRECT'), (.85,False,False,{'x':.1},'CORRECT'),
    (math.nan,False,False,None,'PARTIAL'), (math.inf,False,False,None,'CORRECT'),
    (-math.inf,False,False,None,'MISS'), (True,False,False,None,'CORRECT'),
    ('0.5',False,False,None,'MISS'), ('bad',True,False,None,'PARTIAL'),
])
def test_verdict_priority_thresholds_and_legacy_coercion(score,review,mismatch,band,want):
    """Pin boundary inclusivity and unusual inputs without changing defaults."""
    assert verdict(score,needs_judge_review=review,class_mismatch=mismatch,ambiguous_band=band)==want


def test_invalid_score_still_raises():
    """Band fallback never conceals a malformed score."""
    with pytest.raises(ValueError,match='could not convert string to float'):
        verdict('invalid')


def test_schema_hand_counts_keep_independent_truthy_populations():
    """One parse failure, two valid rows, one actual adherent row out of three."""
    rows=[{'parse_error':True,'schema_valid':True,'prose_wrapper':True,'extra_schema_key_count':'2'},
          {'schema_valid':True,'legacy_schema_keys':['old']},
          {'schema_valid':False,'schema_adherence':1.,'extra_schema_key_count':-1}]
    assert schema.merge_schema_adherence(rows)=={
        'parse_error_count':1,'parse_error_rate':.3333,'schema_valid_count':2,
        'schema_valid_rate':.6667,'schema_adherence_rate':.3333,
        'prose_wrapper_count':1,'extra_schema_key_docs':1,'legacy_schema_key_docs':1}
    assert schema.merge_schema_adherence([])=={}
    with pytest.raises(ValueError,match='invalid literal for int'):
        schema.merge_schema_adherence([{'extra_schema_key_count':'invalid'}])


def test_schema_exact_structural_fallback_and_metadata_contract():
    """Typed-unavailable fallback retains truthiness with JSON-safe boolean values."""
    got=schema.assess_extraction_facts({'sender':'Alice','bogus':1,'confidence':.9}, {}, schema_keys={'sender'})
    assert got=={'parse_error':False,'schema_valid':True,'schema_adherence':1.,
        'parse_failure_reason':None,'extra_schema_keys':['bogus'],'extra_schema_key_count':1,
        'legacy_schema_keys':[],'prose_wrapper':False}
    assert schema.assess_extraction_facts({}, {})['schema_valid'] is False
    assert schema.assess_extraction_facts({'x':1}, {})['schema_valid'] is True
    assert schema.assess_extraction_facts({'bogus':1}, {},schema_keys={'sender'})['schema_valid'] is False
    assert schema.assess_extraction_facts({'sender':'Alice'}, {},typed_valid=False)['schema_adherence']==0.
    recovered=schema.assess_extraction_facts({'sender':'Alice'}, {'parse_error':True,'recovered_from_raw':True},typed_valid=True)
    assert recovered['schema_valid'] is False and recovered['recovered_from_raw'] is True


@pytest.mark.parametrize('row,want', [
    ({'schema_valid':False},'scorer'), ({'schema_adherence':0},'scorer'),
    ({'extra_schema_keys':['anything']},'schema'), ({'legacy_schema_keys':['old']},'schema'),
    ({'extra_schema_keys':['intent_source']},'schema'),
    ({'prose_wrapper':True,'extra_schema_keys':['anything']},'format'),
    ({'parse_error':True},'format')])
def test_floor_priority(row,want):
    """Floor reasons are payload diagnostics rather than a score threshold."""
    assert schema.classify_floor_mode(row)==want


@pytest.mark.parametrize('keys', [{'sender'}, ['sender'], ('sender',)])
def test_schema_collection_inputs_keep_the_same_structural_fallback(keys):
    """The additive Collection API accepts sets, lists and tuples identically."""
    result = schema.assess_extraction_facts({'sender': 'Alice', 'extra': 1}, {}, schema_keys=keys)
    assert result['schema_valid'] is True


def test_structural_fallback_is_a_serializable_boolean():
    """Typed-unavailable results cannot leak a set into experiment JSON."""
    import json

    result = schema.assess_extraction_facts({'sender': 'Alice', 'extra': 1}, {}, schema_keys={'sender'})
    assert json.loads(json.dumps(result))['schema_valid'] is True
