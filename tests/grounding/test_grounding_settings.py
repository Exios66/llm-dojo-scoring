"""GroundingSettings: defaults, YAML and taxonomy wiring, configure() and validation."""

from __future__ import annotations

import re

import pytest
import yaml
from grounding_inputs import sample_candidates

from llm_dojo_scoring.config import (
    GroundingSettings,
    Settings,
    clear_settings_cache,
    configure,
    configure_from_taxonomy,
    get_settings,
    load_settings,
)
from llm_dojo_scoring.grounding.labels import derive_valid_labels
from llm_dojo_scoring.grounding.ledger import ingest_confirmations


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    """Every test starts and ends on default settings."""
    monkeypatch.delenv("LLM_DOJO_SCORING_CONFIG", raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_defaults_match_the_design():
    """The defaults are the design's §6.4 proposals."""
    assert Settings().grounding == GroundingSettings(
        trust_bar=0.95, trust_min_n=50, trust_window=200, certainty_floor=0.9,
        spot_check_rate=0.10, spot_check_min_per_agent=20,
    )
    assert GroundingSettings().validate() == GroundingSettings()


def test_yaml_block_is_applied_and_unknown_keys_ignored(tmp_path):
    """A grounding: block in the YAML config overrides the defaults."""
    path = tmp_path / "dojo.yaml"
    path.write_text(yaml.safe_dump({"grounding": {"trust_bar": 0.97, "trust_min_n": 30,
                                                  "future_knob": 1}}), encoding="utf-8")
    grounding = load_settings(path).grounding
    assert (grounding.trust_bar, grounding.trust_min_n, grounding.trust_window) == (0.97, 30, 200)
    assert isinstance(grounding.trust_min_n, int)


def test_taxonomy_block_is_applied():
    """configure_from_taxonomy wires the same block into the process settings."""
    configure_from_taxonomy({"grounding": {"certainty_floor": 0.8, "spot_check_rate": 0.25}})
    assert (get_settings().grounding.certainty_floor, get_settings().grounding.spot_check_rate) == (0.8, 0.25)


@pytest.mark.parametrize(("block", "message"), [
    ({"trust_bar": 1.5}, "trust_bar must be a number in"),
    ({"certainty_floor": -0.1}, "certainty_floor must be a number in"),
    ({"spot_check_rate": "high"}, "spot_check_rate must be a finite number"),
    ({"trust_min_n": True}, "trust_min_n must be a finite number"),
    ({"trust_min_n": float("inf")}, "trust_min_n must be a finite number"),
    ({"trust_bar": float("nan")}, "trust_bar must be a finite number"),
    ({"trust_bar": 10**400}, "trust_bar must be a finite number"),
    ({"trust_min_n": 2.5}, "trust_min_n must be a whole number"),
    ({"spot_check_min_per_agent": -1}, "spot_check_min_per_agent must be a whole number >= 0"),
    ({"trust_window": 10}, "trust_window (10) must be at least grounding.trust_min_n (50)"),
    ({"trust_min_n": 0}, "trust_min_n must be at least 1"),
])
def test_bad_block_raises_and_keeps_old_values(block, message):
    """A bad value raises ValueError naming it, and nothing in the block is applied."""
    with pytest.raises(ValueError, match=re.escape(message)):
        configure_from_taxonomy({"grounding": {"trust_bar": 0.5, **block}})
    assert get_settings().grounding == GroundingSettings()


def test_configure_validates_before_setting():
    """configure(grounding__…) sets a good value and refuses a bad one."""
    configure(grounding__trust_bar=0.99)
    assert get_settings().grounding.trust_bar == 0.99
    with pytest.raises(ValueError, match="trust_bar"):
        configure(grounding__trust_bar=2)
    assert get_settings().grounding.trust_bar == 0.99
    with pytest.raises(AttributeError, match="unknown setting"):
        configure(grounding__trust_bars=0.9)


def test_label_certainty_floor_follows_settings():
    """derive_valid_labels reads its default certainty floor from the settings."""
    candidate = sample_candidates()["adjuster"]
    ledger = ingest_confirmations([{
        "candidate_id": candidate.candidate_id, "verdict": "valid", "reviewer_kind": "agent",
        "reviewer_id": "boss@v1", "certainty": 0.85, "confirmed_at": 100,
    }], [candidate])

    class TrustAll:
        """Trusts every agent."""

        def trusted_snapshot_id(self, ledger, reviewer_id, at):
            """Always trusted."""
            return "snap"

    assert derive_valid_labels(ledger, TrustAll()).pending
    configure(grounding__certainty_floor=0.8)
    assert derive_valid_labels(ledger, TrustAll()).labels


def test_bad_grounding_block_leaves_every_section_untouched():
    """A bad grounding value raises before any other block of the same config is applied."""
    before = get_settings().field_scoring.bipartite_match_threshold
    with pytest.raises(ValueError, match="trust_bar"):
        configure_from_taxonomy({"field_scoring": {"bipartite_match_threshold": 0.123},
                                 "subtype_equivalences": [["a", "b"]],
                                 "grounding": {"trust_bar": 9}})
    assert get_settings().field_scoring.bipartite_match_threshold == before
    assert frozenset({"a", "b"}) not in get_settings().subtype_equivalences


@pytest.mark.parametrize("block", ["trust_bar", [1], False, 0, "", []])
def test_non_mapping_block_raises(block):
    """A grounding block that is not a mapping is a ValueError, falsy ones included."""
    before = get_settings().field_scoring.bipartite_match_threshold
    with pytest.raises(ValueError, match="must be a mapping"):
        configure_from_taxonomy({"field_scoring": {"bipartite_match_threshold": 0.123}, "grounding": block})
    assert get_settings().field_scoring.bipartite_match_threshold == before


@pytest.mark.parametrize("block", [None, {}])
def test_absent_or_empty_block_changes_nothing(block):
    """``grounding: null`` and ``grounding: {}`` keep the current values."""
    configure_from_taxonomy({"grounding": block})
    assert get_settings().grounding == GroundingSettings()


def test_configure_validates_overrides_together_in_any_order():
    """Related overrides are checked together, so their order does not matter."""
    configure(grounding__trust_min_n=300, grounding__trust_window=400)
    assert (get_settings().grounding.trust_min_n, get_settings().grounding.trust_window) == (300, 400)


def test_configure_coerces_like_the_yaml_path():
    """configure accepts the same numbers the YAML path does, numpy included."""
    np = pytest.importorskip("numpy")
    configure(grounding__trust_min_n=40.0, grounding__trust_bar=np.float32(0.5),
              grounding__spot_check_min_per_agent=np.int64(7))
    grounding = get_settings().grounding
    assert (grounding.trust_min_n, grounding.trust_bar, grounding.spot_check_min_per_agent) == (40, 0.5, 7)
    assert all(type(v) in (int, float) for v in (grounding.trust_min_n, grounding.trust_bar,
                                                 grounding.spot_check_min_per_agent))


def test_whole_section_is_coerced_like_overrides():
    """``grounding=GroundingSettings(trust_min_n=40.0)`` works as ``grounding__trust_min_n=40.0`` does."""
    configure(grounding=GroundingSettings(trust_min_n=40.0, trust_bar=1))
    grounding = get_settings().grounding
    assert (grounding.trust_min_n, grounding.trust_bar) == (40, 1.0)
    assert (type(grounding.trust_min_n), type(grounding.trust_bar)) == (int, float)
    clear_settings_cache()
    configure(grounding__trust_min_n=40.0, grounding__trust_bar=1)
    assert get_settings().grounding == grounding
    with pytest.raises(ValueError, match="whole number"):
        configure(grounding=GroundingSettings(trust_min_n=40.5))


@pytest.mark.parametrize("value", [None, {"trust_bar": 0.9}, GroundingSettings(trust_bar=5)])
def test_configure_whole_section_is_validated(value):
    """configure(grounding=…) needs a valid GroundingSettings."""
    with pytest.raises(ValueError):
        configure(grounding=value)
    assert get_settings().grounding == GroundingSettings()
    configure(grounding=GroundingSettings(trust_bar=0.8))
    assert get_settings().grounding.trust_bar == 0.8


def test_updates_are_in_place():
    """A kept reference to the grounding section sees later updates."""
    section = get_settings().grounding
    configure(grounding__trust_bar=0.9)
    configure_from_taxonomy({"grounding": {"trust_min_n": 10}})
    configure(grounding=GroundingSettings(spot_check_rate=0.5))
    assert get_settings().grounding is section
    assert section.spot_check_rate == 0.5


@pytest.mark.parametrize("floor", [-1, 1.5, float("nan"), True, "0.9"])
def test_explicit_certainty_floor_is_validated(floor):
    """An explicit floor is checked like the setting: no fail-open below 0, no NaN, no bool."""
    with pytest.raises(ValueError, match="certainty_floor"):
        derive_valid_labels(ingest_confirmations([], sample_candidates().values()), certainty_floor=floor)


def test_spot_check_floor_fits_in_the_trust_window():
    """The spot-check floor is counted over the trust window, so it cannot exceed it."""
    with pytest.raises(ValueError, match="spot_check_min_per_agent"):
        configure(grounding__spot_check_min_per_agent=300)
    configure(grounding__spot_check_min_per_agent=200)
