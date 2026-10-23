"""Additive sandbox benchmark regression tests with hand-counted outcomes."""

from llm_dojo_scoring import score_sandbox_cuad, score_sandbox_maud
from llm_dojo_scoring.content_scoring import score_maud_extraction
from llm_dojo_scoring.sandbox_scoring import score_cuad, score_maud


def test_public_sandbox_apis_use_one_dojo_implementation():
    """Root exports and compatibility entry points share the real engine."""
    assert score_sandbox_maud is score_maud
    assert score_sandbox_cuad is score_cuad


def test_sandbox_cuad_confusion_counts_and_empty_population():
    """One TP, FP, and FN give precision=recall=F1=one half."""
    gt = {"Parties": [{"text": "Acme and Beta"}],
          "Governing Law": [{"text": "New York"}], "Renewal Term": []}
    pred = {"parties": ["Acme"], "cuad_clauses": ["Renewal Term: invented", "Unknown: x"]}
    out = score_sandbox_cuad(pred, gt)
    assert (out["cuad_tp"], out["cuad_fp"], out["cuad_fn"]) == (1, 1, 1)
    assert out["cuad_presence_precision"] == 0.5
    assert out["cuad_presence_recall"] == 0.5
    assert out["cuad_presence_f1"] == 0.5
    assert out["cuad_out_of_universe"] == 1
    assert (out["cuad_value_checked"], out["cuad_value_correct"]) == (1, 1)
    assert score_sandbox_cuad({}, {})["cuad_presence_f1"] is None
    assert score_sandbox_cuad({}, {"Parties": []})["cuad_presence_f1"] == 0.0


def test_sandbox_maud_missing_conflict_and_catalog_none():
    """Catalog None is real; a missing answer and a conflict remain misses."""
    cor = "Agreement provides for matching rights in connection with COR"
    gt = {cor: {"answer": "None"}, "Breach of No Shop": {"answer": "No"},
          "Type of Consideration": {"answer": "All Cash"}}
    pred = {"maud_clauses": [f"{cor}: None", "Breach of No Shop: Yes", "Breach of No Shop: No"]}
    out = score_sandbox_maud(pred, gt)
    assert (out["maud_questions"], out["maud_answered"], out["maud_correct"], out["maud_conflicts"]) == (3, 2, 1, 1)
    assert out["maud_accuracy"] == 1 / 3
    assert out["maud_precision_answered"] == 0.5
    assert out["maud_clean_accuracy"] == 1 / 3
    assert score_sandbox_maud({}, {})["maud_accuracy"] is None


def test_existing_dojo_maud_population_and_placeholder_contract_are_preserved():
    """Additions do not change canonical clean-GT scoring's existing behavior."""
    gt = {"No-Shop": {"answer": "Yes"}}
    pred = {"maud_clauses": ["No-Shop: not specified"]}
    old = score_maud_extraction(gt, pred["maud_clauses"])
    adopted = score_sandbox_maud(pred, gt)
    assert old["n_present"] == 1
    assert old["maud_precision_answered"] == 0.0
    assert adopted["maud_answered"] == 0
    assert adopted["maud_precision_answered"] is None


def test_sandbox_emission_names_are_registered_and_populations_stay_distinct():
    """No quality emission on unlabeled rows and no unknown-name fallback."""
    import pytest

    from llm_dojo_scoring import get_registry, sandbox_metric_scores
    from llm_dojo_scoring.scorecard_honesty import metric_id_for

    out = score_sandbox_cuad({}, {"Parties": [{"text": "Acme"}]})
    scores = sandbox_metric_scores("cuad", out)
    assert scores["sandbox_cuad_presence_f1"] == 0.0
    assert get_registry().get("sandbox_cuad_presence_f1").tier == 1
    assert metric_id_for("sandbox_cuad_presence_f1") == "cuad.sandbox_category_detection.micro_f1"
    assert metric_id_for("maud_question_accuracy") == "maud.question.micro_accuracy"
    assert sandbox_metric_scores("cuad", score_sandbox_cuad({}, {})) == {}
    assert sandbox_metric_scores("maud", score_sandbox_maud({}, {})) == {}
    with pytest.raises(ValueError, match="unknown sandbox benchmark"):
        sandbox_metric_scores("unknown", {})


def test_sandbox_pooling_uses_counts_instead_of_mean_document_f1():
    """A perfect single event plus nine misses gives pooled F1=2/11."""
    from llm_dojo_scoring import aggregate_sandbox_scores

    rows = [{"cuad_tp": 1, "cuad_fp": 0, "cuad_fn": 0, "cuad_presence_f1": 1.0},
            {"cuad_tp": 0, "cuad_fp": 0, "cuad_fn": 9, "cuad_presence_f1": 0.0}]
    pooled = aggregate_sandbox_scores("cuad", rows)
    assert pooled["docs_labeled"] == 2
    assert pooled["precision"] == 1.0
    assert pooled["recall"] == 0.1
    assert pooled["f1"] == 0.1818
    missed = aggregate_sandbox_scores("cuad", [rows[1]])
    assert missed["f1"] == 0.0
    assert aggregate_sandbox_scores("cuad", [])["f1"] is None
    maud = aggregate_sandbox_scores("maud", [
        {"maud_questions": 1, "maud_correct": 1, "maud_answered": 1},
        {"maud_questions": 9, "maud_correct": 0, "maud_answered": 0}])
    assert maud["accuracy"] == 0.1
    assert maud["precision_answered"] == 1.0
