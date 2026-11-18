"""``is_parse_compat_key`` reads a str-Enum document class by its value (CodeRabbit, #181)."""

from __future__ import annotations

from enum import Enum

from llm_dojo_scoring.scoring.field_scoring import is_parse_compat_key


class _DocType(str, Enum):
    """A str-Enum whose ``str()`` is ``"_DocType.CONTRACT"``, not its value."""

    CONTRACT = "contract"
    MERGER = "merger_agreement"


def test_str_enum_contract_is_recognised_like_the_plain_string():
    """The enum member and its value agree on every parse-compat key."""
    for key in ("merger_consideration", "maud_clauses"):
        assert is_parse_compat_key(_DocType.CONTRACT, key) is is_parse_compat_key("contract", key) is True
        assert is_parse_compat_key(_DocType.MERGER, key) is False


def test_explicit_field_type_still_opts_an_enum_contract_back_in():
    """``field_types`` naming the key keeps it scored, enum class or not."""
    assert is_parse_compat_key(_DocType.CONTRACT, "maud_clauses", {"maud_clauses": "list"}) is False
