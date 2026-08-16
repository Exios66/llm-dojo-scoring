import pytest

from llm_dojo_scoring.config import (
    CONTRACT_SUBTYPE_KEYS,
    PER_SUBTYPE,
    Settings,
    configure,
    load_settings,
)
from llm_dojo_scoring.equivalences import (
    equivalent_doc_subclasses,
    equivalent_subtypes,
    normalize_doc_subclass,
    normalize_subtype,
)


def test_subtype_lists():
    assert "license" in CONTRACT_SUBTYPE_KEYS
    assert len(PER_SUBTYPE) == 25
    assert set(PER_SUBTYPE) == set(CONTRACT_SUBTYPE_KEYS)


def test_normalize_subtype_aliases_and_labels():
    assert normalize_subtype("License_Agreements") == "license"
    assert normalize_subtype("License Agreement") == "license"
    assert normalize_subtype("Non-Compete") == "non_compete_no_solicit"
    assert normalize_subtype("garbage") == "other"
    assert normalize_subtype(None) == "other"


def test_equivalent_subtypes():
    assert equivalent_subtypes("reseller", "distributor")
    assert equivalent_subtypes("license", "maintenance")
    assert equivalent_subtypes("license", "development")
    assert equivalent_subtypes("affiliate", "joint_venture")
    assert not equivalent_subtypes("license", "franchise")
    assert equivalent_subtypes("license", "license")


def test_equivalent_doc_subclasses_scoped():
    assert equivalent_doc_subclasses("mixed_cash_stock", "mixed_cash_stock_election")
    assert equivalent_doc_subclasses("mixed_cash_stock", "bylaws") is False
    assert not equivalent_doc_subclasses(
        "mixed_cash_stock", "mixed_cash_stock_election", allowed={"bylaws"}
    )


def test_normalize_doc_subclass_scoped():
    allowed = {"cash", "stock", "mixed_cash_stock"}
    assert normalize_doc_subclass("Mixed Cash Stock", allowed=allowed) == "mixed_cash_stock"
    assert normalize_doc_subclass("bylaws", allowed=allowed) == "other"


def test_settings_yaml_load_and_override(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "field_scoring:\n"
        "  bipartite_match_threshold: 0.8\n"
        "  partial_gt_fields: [parties]\n"
        "subtype_equivalences:\n"
        "  - [a, b]\n"
    )
    settings = load_settings(cfg)
    assert settings.field_scoring.bipartite_match_threshold == 0.8
    assert settings.field_scoring.partial_gt_fields == {"parties"}
    assert settings.equivalent_subtypes("a", "b")
    assert settings.equivalent_subtypes("a", "c") is False


def test_configure_dotted_override():
    settings = configure(field_scoring__ambiguous_band=(0.4, 0.9))
    assert settings.field_scoring.ambiguous_band == (0.4, 0.9)


def test_default_settings():
    s = Settings()
    assert s.subtype_unknown == "other"
    assert s.contract_subtype_keys == CONTRACT_SUBTYPE_KEYS