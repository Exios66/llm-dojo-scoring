"""The contract mailroom-ml vendors, and the intake-classifier scorecard.

mailroom-ml copies the Dojo's label tables and intake clerk instead of importing
them. These tests hold the committed ``ml_contract.json`` to the live tables, make
sure each golden case is what the Dojo's own functions return, and score a small
realistic batch of classifier predictions.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import llm_dojo_scoring
from llm_dojo_scoring.analysis.bootstrap import wilson_ci
from llm_dojo_scoring.analysis.calibration import expected_calibration_error
from llm_dojo_scoring.metrics.registry import get_registry
from llm_dojo_scoring.metrics.score_changelog import SCORE_CHANGELOG
from llm_dojo_scoring.metrics.scorecard_honesty import _METRIC_ID_BY_NAME
from llm_dojo_scoring.ml import contract as contract_module
from llm_dojo_scoring.ml import load_contract, ml_contract, score_intake_model
from llm_dojo_scoring.ml.metrics import METRIC_IDS
from llm_dojo_scoring.pipeline.intake import INTAKE_PREP_STEPS, deterministic_normalize
from llm_dojo_scoring.schemas.corpus import CORPUS_SUBCLASS_SURFACES, normalize_corpus_subclass
from llm_dojo_scoring.schemas.doc_classes import LIVE_DOC_TYPES
from conftest import load_script

ROOT = Path(__file__).resolve().parents[2]


def test_committed_contract_matches_the_live_tables():
    """What mailroom-ml vendors is exactly what the Dojo computes today."""
    assert load_contract() == json.loads(json.dumps(ml_contract()))
    assert load_contract()["doc_types"] == list(LIVE_DOC_TYPES)


def test_export_check_names_the_stale_part(tmp_path, monkeypatch, capsys):
    """--check passes on the committed file and names the part that drifted."""
    script = load_script("export_ml_contract")
    assert script.main(["--check"]) == 0
    stale = tmp_path / "ml_contract.json"
    assert script.main(["--write", "--path", str(stale)]) == 0
    patched = dict(contract_module.SUBTYPE_ALIASES, new_family_agreements="supply")
    monkeypatch.setattr(contract_module, "SUBTYPE_ALIASES", patched)
    assert script.main(["--check", "--path", str(stale)]) == 1
    assert "parts changed: subtype_aliases" in capsys.readouterr().err


def test_every_corpus_surface_maps_to_a_canonical_key():
    """Each live class lists all its corpus surfaces, each resolving inside its own subclass set."""
    contract = ml_contract()
    for doc_type in LIVE_DOC_TYPES:
        table = contract["subclass_normalization"][doc_type]
        assert set(CORPUS_SUBCLASS_SURFACES.get(doc_type, ())) <= set(table)
        allowed = set(contract["subclasses"][doc_type]) | {contract["subclass_unknown"]}
        for surface, key in table.items():
            assert key == normalize_corpus_subclass(doc_type, surface)
            assert key in allowed, (doc_type, surface, key)
    assert contract["subclass_normalization"]["contract"]["License_Agreements"] == "license"


def test_intake_cases_cover_every_prep_step_and_are_stable():
    """A golden case per prep step; each output is the clerk's output and a fixed point."""
    cases = ml_contract()["intake"]["cases"]
    assert set(INTAKE_PREP_STEPS) <= {case["name"] for case in cases}
    for case in cases:
        output, stats = deterministic_normalize(case["input"])
        assert (case["output"], case["stats"]) == (output, stats)
        assert deterministic_normalize(output)[0] == output


def test_digests_track_their_parts():
    """Every part has a digest, and changing one part moves only its digest."""
    contract = ml_contract()
    assert set(contract["digests"]) == set(contract) - {"schema", "digests"}
    assert contract["digests"]["doc_types"] == contract_module._digest(contract["doc_types"])


def test_contract_ships_in_the_wheel():
    """package-data includes the JSON, so an installed Dojo can hand it out."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "ml/data/*.json" in config["tool"]["setuptools"]["package-data"]["llm_dojo_scoring"]
    assert contract_module.contract_path().is_file()


# A small realistic batch: raw corpus surfaces as gold, mixed fast-path use.
BATCH = [
    {"doc_type": "contract", "subclass": "License_Agreements", "pred_doc_type": "contract",
     "pred_subclass": "license", "doc_type_confidence": 0.95, "subclass_confidence": 0.9,
     "fast_path": True},
    {"doc_type": "insurance_claim", "subclass": "carrier", "pred_doc_type": "insurance_claim",
     "pred_subclass": "inpatient", "doc_type_confidence": 0.9, "subclass_confidence": 0.8,
     "fast_path": True},
    {"doc_type": "correspondence", "subclass": "email", "pred_doc_type": "Correspondence",
     "pred_subclass": "email", "doc_type_confidence": 0.6, "subclass_confidence": 0.55,
     "fast_path": False},
    {"doc_type": "corporate_record", "subclass": "bylaws", "pred_doc_type": "contract",
     "pred_subclass": "bylaws", "doc_type_confidence": 0.7, "subclass_confidence": 0.7,
     "fast_path": False},
    {"doc_type": "merger_agreement", "pred_doc_type": "merger_agreement",
     "doc_type_confidence": 0.99, "fast_path": True},
    {"doc_type": "nan", "pred_doc_type": "contract", "fast_path": True},
]


def test_intake_scorecard_on_a_mixed_batch():
    """Per-head accuracy and ECE, coverage, and fast-path risk with its Wilson bound."""
    card = score_intake_model(BATCH)
    m = card["metrics"]
    assert (card["n"], card["n_scored"], card["n_subclass_scored"], card["n_fast_path"]) == (6, 5, 4, 3)
    assert card["n_unscored_by_reason"] == {"no_gold_doc_type": 1}
    assert m["doc_type_accuracy"] == 0.8
    assert m["doc_type_macro_f1"] == pytest.approx(0.7333, abs=1e-3)
    assert m["doc_type_ece"] == expected_calibration_error(
        [(0.95, True), (0.9, True), (0.6, True), (0.7, False), (0.99, True)]
    )
    # License_Agreements and license are one answer; a right subclass under a wrong class is wrong.
    assert m["subclass_accuracy"] == 0.5
    assert m["subclass_ece"] == expected_calibration_error(
        [(0.9, True), (0.8, False), (0.55, True), (0.7, False)]
    )
    assert m["fast_path_coverage"] == 0.6
    assert m["selective_risk"] == pytest.approx(1 / 3, abs=1e-6)
    assert m["selective_risk_upper"] == wilson_ci(1 / 3, 3)["hi"]
    assert m["selective_risk_upper"] > m["selective_risk"]


def test_no_fast_path_and_no_gold_report_none_not_zero():
    """Undefined rates are None: a model that never took the fast path has no risk yet."""
    card = score_intake_model([{**row, "fast_path": False} for row in BATCH[:2]])
    assert card["metrics"]["selective_risk"] is None
    assert card["metrics"]["selective_risk_upper"] is None
    assert card["metrics"]["fast_path_coverage"] == 0.0
    empty = score_intake_model([{"doc_type": None}, {"doc_type": " "}])
    assert empty["n_scored"] == 0
    assert all(value is None for value in empty["metrics"].values())


def test_out_of_range_confidence_is_left_out_of_calibration():
    """A logit or a missing confidence does not enter ECE; the prediction is still scored."""
    rows = [{"doc_type": "contract", "pred_doc_type": "contract", "doc_type_confidence": 4.2},
            {"doc_type": "contract", "pred_doc_type": "contract", "doc_type_confidence": True}]
    card = score_intake_model(rows)
    assert card["metrics"]["doc_type_accuracy"] == 1.0
    assert card["metrics"]["doc_type_ece"] is None


def test_numpy_rows_score_like_python_rows():
    """Rows read from a DataFrame carry numpy flags and floats; they count the same."""
    np = pytest.importorskip("numpy")
    row = {"doc_type": "contract", "pred_doc_type": "contract",
           "doc_type_confidence": np.float32(0.9), "fast_path": np.True_}
    card = score_intake_model([row])
    assert card["n_fast_path"] == 1
    assert card["metrics"]["selective_risk"] == 0.0
    assert card["metrics"]["doc_type_ece"] == expected_calibration_error([(float(np.float32(0.9)), True)])
    assert score_intake_model([{**row, "fast_path": "yes"}])["n_fast_path"] == 0


def test_class_without_a_subclass_catalog_is_not_subclass_scored():
    """Two arbitrary labels both normalize to other there; that is no evidence of a right answer."""
    card = score_intake_model([{"doc_type": "due_diligence", "subclass": "foo",
                                "pred_doc_type": "due_diligence", "pred_subclass": "bar"}])
    assert card["n_subclass_scored"] == 0
    assert card["metrics"]["subclass_accuracy"] is None


def test_metric_ids_are_registered_and_changelogged():
    """Each ml.intake id is in the registry, the honesty map and the score changelog."""
    registry = get_registry()
    changelogged = {mid for entry in SCORE_CHANGELOG for mid in entry["metric_ids"]}
    for key, metric_id in METRIC_IDS.items():
        name = f"ml_intake_{key}"
        assert metric_id == f"ml.intake.{key}"
        assert _METRIC_ID_BY_NAME[name] == metric_id
        assert registry.get(name).source == "ml.score_intake_model"
        assert metric_id in changelogged
    assert set(score_intake_model(BATCH)["metrics"]) == set(METRIC_IDS)


def test_ml_stays_off_the_package_root():
    """The consumer surface is unchanged: nothing from ml is a root export."""
    assert not {"ml_contract", "score_intake_model", "load_contract"} & set(llm_dojo_scoring.__all__)
