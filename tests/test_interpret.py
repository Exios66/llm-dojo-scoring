import pytest

from llm_dojo_scoring import interpret as interp
from llm_dojo_scoring.io import normalize_results_frame


@pytest.fixture
def df(sorter_frame) -> object:
    return normalize_results_frame(sorter_frame)


def test_interpret_winner_and_notes(df):
    interpretation = interp.interpret(df, target=0.94)
    assert interpretation.summary["winner"] == "qwen3.7-flash_sorter_v13_subtype_langfuse"
    assert interpretation.summary["winner_score"] == pytest.approx(0.9430)
    kinds = {n.kind for n in interpretation.notes}
    assert {"winner", "target", "version", "model", "hotspot", "failure", "reliability"} <= kinds
    assert any(n.kind == "target" and n.severity == "info" for n in interpretation.notes)


def test_interpret_target_not_met(df):
    interpretation = interp.interpret(df, target=0.95)
    assert any(n.kind == "target" and n.severity == "warning" for n in interpretation.notes)


def test_interpret_regression_alert(df):
    interpretation = interp.interpret(df)
    # v12: 0.9234 -> 0.88 and v13: 0.9430 -> gpt 0.8978 are >= 2pt drops
    assert any(n.kind == "regression" and n.severity == "critical"
               for n in interpretation.notes)


def test_interpret_to_dict_and_by_severity(df):
    interpretation = interp.interpret(df)
    d = interpretation.to_dict()
    assert "notes" in d and "summary" in d
    severities = interpretation.by_severity()
    assert sum(len(v) for v in severities.values()) == len(interpretation.notes)


def test_render_notes(df):
    text = interp.render_notes(interp.interpret(df))
    assert "[i] Best run:" in text
    assert "[!]" in text


def test_interpret_no_runs():
    import pandas as pd

    empty = interp.interpret(pd.DataFrame(), min_n=10)
    assert empty.notes[0].severity == "warning"


def test_cost_note(df):
    interpretation = interp.interpret(df, cost_column="Cost Estimated USD")
    assert any(n.kind == "cost" for n in interpretation.notes)