"""#167: ``agreement_date`` and ``expiration_date`` evidence their CUAD categories, for recall only.

CUAD often leaves the Agreement or Expiration Date unannotated on a contract that prints one,
so a filled date field earns the category where CUAD labels it and is never a false positive
where CUAD does not.
"""
from __future__ import annotations

import json

from llm_dojo_scoring.pipeline.sandbox_scoring import field_value_ok, score_cuad


def _labels(**cats):
    """CUAD ``cuad_clause_labels`` JSON: each category maps to its annotated spans."""
    return json.dumps({k: [{"text": t} for t in v] for k, v in cats.items()})


def test_a_filled_agreement_date_earns_a_labelled_category():
    """A filled ``agreement_date`` is a true positive where CUAD labels the Agreement Date."""
    labels = _labels(**{"Parties": ["Acme"], "Agreement Date": ["March 1, 2010"]})
    scored = score_cuad({"parties": ["Acme"], "agreement_date": "2010-03-01"}, labels)
    assert (scored["cuad_tp"], scored["cuad_fp"], scored["cuad_fn"]) == (2, 0, 0)


def test_an_unlabelled_agreement_date_is_not_a_false_positive():
    """Where CUAD leaves the Agreement Date unlabelled, a filled date is neither TP nor FP."""
    labels = _labels(**{"Parties": ["Acme"], "Agreement Date": []})
    scored = score_cuad({"parties": ["Acme"], "agreement_date": "2010-03-01"}, labels)
    assert (scored["cuad_tp"], scored["cuad_fp"], scored["cuad_fn"]) == (1, 0, 0)
    assert field_value_ok("agreement_date", "2010-03-01", labels) is None


def test_expiration_date_is_recall_only_but_term_length_still_counts_both_ways():
    """``expiration_date`` is recall-only; ``term_length`` still scores a false positive."""
    labelled = _labels(**{"Expiration Date": ["five years from the Effective Date"]})
    assert score_cuad({"expiration_date": "2015-03-01"}, labelled)["cuad_tp"] == 1
    unlabelled = _labels(**{"Parties": ["Acme"], "Expiration Date": []})
    assert score_cuad({"parties": ["Acme"], "expiration_date": "2015-03-01"}, unlabelled)["cuad_fp"] == 0
    assert score_cuad({"parties": ["Acme"], "term_length": "5 years"}, unlabelled)["cuad_fp"] == 1


def test_a_clause_line_naming_an_unlabelled_date_is_still_a_false_positive():
    """An explicit ``cuad_clauses`` line keeps its strict scoring, unlabelled date or not."""
    labels = _labels(**{"Parties": ["Acme"], "Agreement Date": []})
    scored = score_cuad({"parties": ["Acme"], "cuad_clauses": ["Agreement Date: March 1, 2010"]}, labels)
    assert scored["cuad_fp"] == 1


def test_a_missing_date_field_is_a_miss_where_cuad_labels_it():
    """An empty date field is a false negative where CUAD labels the category."""
    labels = _labels(**{"Agreement Date": ["March 1, 2010"]})
    assert score_cuad({}, labels)["cuad_fn"] == 1
    assert field_value_ok("agreement_date", None, labels) is False
