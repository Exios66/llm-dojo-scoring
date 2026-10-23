"""Compatibility precision for the existing scored-only canonical reducer."""


def test_reducer_opt_in_preserves_consumer_arithmetic_and_existing_default():
    """An additive precision option preserves runner sum/length without changing defaults."""
    from llm_dojo_scoring.scorecard_honesty import aggregate_quality_honest
    rows=[{'overall_score':v} for v in [1.,0.,0.]]+[{'status':'unscorable','overall_score':0.}]
    assert aggregate_quality_honest(rows)['quality_mean']==.3333
    out=aggregate_quality_honest(rows,precision=None)
    assert out=={'n_scored':3,'n_unscorable':1,'quality_mean':1/3,
                 'quality_population':'scored_only','export_verdict':'scored'}
    assert aggregate_quality_honest([{'overall_score':0.}],precision=None)['quality_mean']==0.
    assert aggregate_quality_honest([],precision=None)['quality_mean'] is None
