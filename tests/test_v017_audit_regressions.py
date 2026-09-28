"""0.17.0 audit regressions — each test pins a wrong-but-plausible score or a
crash the 0.16.0 engine produced (see CHANGELOG ``[0.17.0]`` / MIGRATION)."""

from __future__ import annotations

import datetime
import math
from unittest.mock import patch

import pandas as pd
import pytest

from llm_dojo_scoring import field_scoring as fs
from llm_dojo_scoring.bootstrap import bootstrap_ci, delta_significance
from llm_dojo_scoring.classification import accuracy
from llm_dojo_scoring.config import configure, get_settings, load_settings
from llm_dojo_scoring.cost import price_for, tokens_summary
from llm_dojo_scoring.emitter import Emitter, LangfuseSink, ScoreRecord
from llm_dojo_scoring.equivalences import normalize_subtype
from llm_dojo_scoring.extraction_metrics import extraction_binary_metrics
from llm_dojo_scoring.mailroom import (
    LIVE_DOC_TYPES,
    RETIRED_DOC_TYPES,
    resolve_extract_class,
    score_aligned_classification,
)
from llm_dojo_scoring.report import _md_table
from llm_dojo_scoring.suites import DEFAULT_FIELD_TYPES, get_suite


# ------------------------------------------------------------------ names

@pytest.mark.parametrize(
    "pred, gold",
    [("John", "John Smith"), ("Bank", "Bank of America"), ("the", "The Coca-Cola Company")],
)
def test_truncated_name_is_not_a_perfect_match(pred, gold):
    assert fs.score_name_field(pred, gold) < 0.85


def test_token_set_ratio_is_symmetric_and_subset_is_not_one():
    assert fs._token_set_ratio("john", "john smith") == fs._token_set_ratio("john smith", "john")
    assert fs._token_set_ratio("john", "john smith") < 1.0


def test_gold_inside_prediction_and_title_subphrase_still_match():
    assert fs.score_name_field("John Smith Jr.", "John Smith") == 1.0
    assert fs.score_name_field(
        "FRANCHISE AGREEMENT", "Goosehead Insurance Agency, LLC Franchise Agreement"
    ) == 1.0


def test_suffix_only_values_are_not_blanked():
    assert fs.score_name_field("CO", "PA") == 0.0
    assert fs.normalize_text("Acme Corp") == "ACME"


def test_typographic_quotes_and_none():
    assert fs.score_name_field("O’Brien", "O'Brien") == 1.0
    assert fs.score_name_field("None", None) == 0.0


# ------------------------------------------------------------------ dates

def test_partial_dates_do_not_depend_on_today():
    # Missing components fill from a fixed default, never from today's date
    # (0.16 scored "March 15, 2024" vs "March 2024" 1.0 only on the 15th).
    assert fs._parse_date("March 2024") == datetime.date(2024, 3, 1)
    assert fs._parse_date("2024") == datetime.date(2024, 1, 1)
    assert fs._date_precision("March 2024") == "month"
    assert fs._date_precision("2024") == "year"
    assert fs._date_precision("March 3, 2024") == "day"


def test_partial_date_precision_scoring():
    assert fs.score_date_field("March 15, 2024", "March 2024") == 1.0
    assert fs.score_date_field("March 2024", "March 15, 2024") == 0.67
    assert fs.score_date_field("2024-05-01", "2024") == 1.0
    assert fs.score_date_field("March 3, 2024", "March 3, 2024") == 1.0


# ------------------------------------------------------------------ money / ids

@pytest.mark.parametrize(
    "text, value",
    [("5M USD", 5e6), ("$1.5 million", 1.5e6), ("(1,000)", -1000.0), ("USD 100", 100.0)],
)
def test_money_forms_parse(text, value):
    assert fs._parse_money(text) == pytest.approx(value)


def test_money_currency_mismatch_and_bool():
    assert fs.score_money_field("€100", "$100") == 0.0
    assert fs._parse_money(True) is None


def test_id_ignores_spacing_and_hyphens():
    assert fs.score_id_field("AB 123", "AB123") == 1.0
    assert fs.score_id_field("12-345", "12345") == 1.0
    assert fs.score_id_field("CO-1", "PA-1") == 0.0


# ------------------------------------------------------------------ lists

def test_empty_gold_with_predictions_has_zero_precision():
    assert fs.score_entity_list("name", ["A", "B"], []).precision == 0.0


def test_subthreshold_pairs_do_not_steal_a_real_match():
    sims = {("A", "X"): 1.0, ("A", "Y"): 0.59, ("B", "X"): 0.59, ("B", "Y"): 0.0}
    with patch.object(fs, "_element_similarity", lambda _t, p, e, _emb=None: sims[(p, e)]):
        with patch.object(fs, "get_bipartite_match_threshold", return_value=0.6):
            result = fs.score_entity_list("name", ["A", "B"], ["X", "Y"])
    pytest.importorskip("scipy")
    assert result.matched == 1


# ------------------------------------------------------------------ judge gate

def test_judge_gate_honours_type_bands():
    settings = get_settings()
    saved = dict(settings.field_scoring.type_bands)
    try:
        settings.field_scoring.type_bands = {"date": ("never",)}
        result = fs.score_extraction(
            "contract", {"effective_date": "date"},
            {"effective_date": "March 2024"}, {"effective_date": "March 15, 2024"},
        )
        assert result.field_scores["effective_date"] == 0.67
        assert result.ambiguous_fields == []
    finally:
        settings.field_scoring.type_bands = saved


# ------------------------------------------------------------------ gt_presence

def test_empty_gold_containers_are_not_misses():
    result = fs.score_extraction(
        "insurance_claim", {"denial_reasons": "entity_list:free_text", "claim_number": "id"},
        {"denial_reasons": [], "claim_number": "C-1"},
        {"denial_reasons": [], "claim_number": "C-1"},
    )
    assert result.field_scores == {"claim_number": 1.0}


def test_gt_presence_codes_skip_non_populated_fields():
    presence = '{"adjuster": "not_applicable", "claim_number": "populated", "insurer": "pending_annotation"}'
    result = fs.score_extraction(
        "insurance_claim", DEFAULT_FIELD_TYPES["insurance_claim"],
        {"claim_number": "C-1"},
        {"claim_number": "C-1", "adjuster": "Jane Roe", "insurer": "Acme"},
        gt_presence=presence,
    )
    assert set(result.field_scores) == {"claim_number"}


def test_binary_metrics_presence_metadata_and_wrong_scalars():
    out = extraction_binary_metrics(
        {"claim_number": "C-1", "insurer": "Acme"},
        {"claim_number": "C-9", "insurer": "Acme", "reasoning": {"x": 1},
         "confidence": 0.9, "adjuster": "Invented"},
        field_map=DEFAULT_FIELD_TYPES["insurance_claim"],
        gt_presence={"adjuster": "schema_documented_absence"},
    )
    # TP insurer; FN + FP for the wrong claim_number; FP for the populated
    # documented-absence field; reasoning/confidence are never FPs.
    assert (out["tp"], out["fn"], out["fp"]) == (1, 1, 2)


# ------------------------------------------------------------------ taxonomy sync

def test_merger_is_live_with_its_own_schema_and_compliance_is_retired():
    assert "merger_agreement" in LIVE_DOC_TYPES
    assert "compliance_filing" in RETIRED_DOC_TYPES
    assert resolve_extract_class("merger_agreement") == "merger_agreement"
    assert fs.get_field_types("merger_agreement", {
        "doc_classes": [{"key": "merger_agreement", "field_types": {"effective_time": "free_text"}}]
    }) == {"effective_time": "free_text"}
    merger = get_suite("merger_agreement")
    assert merger.name == "merger_agreement_specialist"
    assert "cuad_clauses" not in merger.field_types


def test_headline_accuracy_is_exact_not_aligned():
    out = score_aligned_classification(["merger_agreement"], ["contract"])
    assert out["exact_accuracy"] == 0.0 and out["aligned_accuracy"] == 1.0


def test_taxonomy_dict_cost_models_resolve():
    assert price_for("openrouter/free") == (0.0, 0.0)
    assert price_for("z-ai/glm-5.2:free") == (0.0, 0.0)
    settings = get_settings()
    from llm_dojo_scoring.config import _apply_dict

    _apply_dict(settings, {"cost_models": {"x/y": {"input_per_million": 1, "output_per_million": 2}}})
    assert price_for("x/y") == (1.0, 2.0)
    settings.cost_models.pop("x/y", None)


def test_corpus_pin_is_v91():
    from llm_dojo_scoring.corpus import CORPUS_REVISION, CORPUS_REVISION_SHA

    assert CORPUS_REVISION == "v9.1"
    assert CORPUS_REVISION_SHA.startswith("ed7576b")


# ------------------------------------------------------------------ statistics

def test_bootstrap_drops_nan_and_paired_delta():
    ci = bootstrap_ci([0.5, 0.7, float("nan"), 0.9])
    assert ci is not None and not math.isnan(ci["lo"]) and ci["n"] == 3
    a = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    b = [x + 0.05 for x in a]
    paired = delta_significance(a, b, paired=True)
    assert paired["method"] == "paired-percentile-bootstrap"
    assert paired["significant"] is True  # constant +0.05 on the same docs
    with pytest.raises(ValueError):
        delta_significance([1, 2], [1, 2, 3], paired=True)


def test_accuracy_rejects_length_mismatch():
    with pytest.raises(ValueError):
        accuracy(["a", "b"], ["a"])


def test_subtype_prefix_no_longer_steals_unrelated_labels():
    assert normalize_subtype("Affiliate License-Licensee") != "affiliate"


# ------------------------------------------------------------------ robustness

def test_category_presence_accepts_string_reasoning():
    score, _ = fs.score_category_presence(
        {"reasoning": "free text", "cuad_clauses": ["x"]},
        {"Cap": {"expected": True, "answer": "cap on liability", "field": "cuad_clauses"}},
        {},
    )
    assert score == 0.0


def test_tokens_summary_parses_numeric_strings():
    out = tokens_summary([{"prompt_tokens": "12.5", "completion_tokens": 3, "cost": True}])
    assert out["prompt_tokens"] == 12 and out["cost_total_usd"] == 0.0


def test_langfuse_sink_uses_create_score_and_never_logs_value(caplog):
    class V4Client:
        def __init__(self):
            self.calls = []

        def create_score(self, **kw):
            self.calls.append(kw)

    sink = LangfuseSink(client=V4Client())
    sink.emit(ScoreRecord(agent="a", doc_id=None, metric="m", value=0.5, metadata={"trace_id": "t"}))
    assert sink._client.calls and sink._client.calls[0]["value"] == 0.5

    class Broken:
        def create_score(self, **kw):
            raise RuntimeError("boom")

    sink = LangfuseSink(client=Broken())
    sink.emit(ScoreRecord(agent="a", doc_id=None, metric="m", value="SECRET-DOC-TEXT", metadata={}))
    assert "SECRET-DOC-TEXT" not in caplog.text


def test_register_metric_does_not_leak_into_shared_registry():
    from llm_dojo_scoring.registry import load_registry

    Emitter(sinks=[]).register_metric("adhoc_metric_x", 1, description="x")
    assert "adhoc_metric_x" not in load_registry().metrics


def test_explicit_settings_path_does_not_evict_process_settings(tmp_path):
    process = get_settings()
    cfg = tmp_path / "c.yaml"
    cfg.write_text("per_subtype: []\n")
    load_settings(cfg)
    assert get_settings() is process
    with pytest.raises(AttributeError):
        configure(not_a_real_setting=1)


def test_import_is_light():
    import subprocess
    import sys

    code = (
        "import sys, llm_dojo_scoring as d\n"
        "assert 'matplotlib.pyplot' not in sys.modules\n"
        "assert 'pandas' not in sys.modules\n"
        "d.visualize\n"
        "assert 'matplotlib.pyplot' in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_md_table_handles_na_and_pipes():
    table = _md_table(pd.DataFrame({"a": ["x|y", pd.NA]}))
    assert "x\\|y" in table


def test_asr_levenshtein_trims_shared_affixes():
    from llm_dojo_scoring.asr import _levenshtein

    base = list("a" * 20000)
    assert _levenshtein(base, base[:-1] + ["b"]) == 1
    assert _levenshtein(list("kitten"), list("sitting")) == 3


# ------------------------------------------------------------------ visuals

def test_metric_ci_uses_the_metrics_own_ci_columns():
    import matplotlib

    matplotlib.use("Agg")
    from llm_dojo_scoring import visualize as viz

    frame = pd.DataFrame({
        "Experiment Name": ["a", "b"],
        "Exact Match": [0.8, 0.6],
        "Exact Match CI (lo)": [0.7, 0.5],
        "Exact Match CI (hi)": [0.9, 0.7],
        "Subtype Accuracy CI (lo)": [0.0, 0.0],
        "Subtype Accuracy CI (hi)": [1.0, 1.0],
    })
    lo, hi = viz._ci_columns(frame, "Exact Match")
    assert list(lo) == [0.7, 0.5] and list(hi) == [0.9, 0.7]
    fig = viz.plot_metric_ci(frame, "Exact Match")
    matplotlib.pyplot.close(fig)


def test_mailroom_plots_and_palette_order():
    import matplotlib

    matplotlib.use("Agg")
    from llm_dojo_scoring import visualize as viz

    fig = viz.plot_confusion_matrix(["contract", "merger_agreement"], ["contract", "contract"])
    matplotlib.pyplot.close(fig)
    fig = viz.plot_field_accuracy({"parties": [1.0, 0.5], "effective_date": 0.67})
    matplotlib.pyplot.close(fig)
    assert viz._series_colors(9)[-1] == viz.OTHER  # never cycles a 9th hue
    with pytest.raises(ValueError):
        viz.plot_field_accuracy({})


def test_render_notes_markdown_is_a_list():
    from llm_dojo_scoring.interpret import Interpretation, InterpretationNote, render_notes

    notes = Interpretation(notes=[InterpretationNote("regression", "warning", "Drop", detail="details")])
    md = render_notes(notes, markdown=True)
    assert md.startswith("- **Warning [!]** Drop") and "<br>details" in md
    assert render_notes(notes).startswith("[!] Drop")
