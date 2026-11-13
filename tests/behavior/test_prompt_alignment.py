"""Prompt <-> schema alignment guard and the generated prompt changelog.

Each production specialist prompt lists the fields it asks the model for. The registry says
which fields are scored. These tests hold the difference to the recorded gaps, so a new
drift and a silently fixed gap both fail, and keep ``docs/prompts/PROMPT_CHANGELOG.md``
true to the catalog.
"""

from __future__ import annotations

import hashlib
import re

import pytest
from conftest import load_script

from llm_dojo_scoring.prompts import alignment, get_prompt
from llm_dojo_scoring.prompts.alignment import (
    META_KEYS,
    alignment_report,
    compare_to_recorded,
    prompt_fields,
    recorded_gaps,
)
from llm_dojo_scoring.schemas.doc_classes import field_types

changelog = load_script("render_prompt_changelog")


def _template_without(monkeypatch, agent: str, field: str) -> None:
    """Serve ``agent``'s prompt with the ``- field (...)`` line removed."""
    real = alignment.get_prompt
    rec = real(agent, "production")
    text = "\n".join(
        line for line in rec.text.splitlines() if not line.startswith(f"- {field} (")
    )
    assert text != rec.text, f"{field} is not a field line of {agent}"
    patched = type(rec)(**{**rec.__dict__, "text": text})
    monkeypatch.setattr(alignment, "get_prompt", lambda a, f="production": patched if a == agent else real(a, f))


def test_prompt_gaps_match_the_recorded_gaps_exactly():
    """A new drift or a fixed-but-still-listed gap fails with the entries to change."""
    new, fixed = compare_to_recorded()
    assert not new, (
        f"prompt and schema drifted: {new}. Fix the prompt, or record the gap with a reason "
        "in llm_dojo_scoring/prompts/data/alignment_gaps.json"
    )
    assert not fixed, (
        f"these recorded gaps are gone: {fixed}. Remove them from "
        "llm_dojo_scoring/prompts/data/alignment_gaps.json, then re-run "
        "scripts/render_prompt_changelog.py --write"
    )


def test_every_recorded_gap_has_a_reason_and_a_known_side():
    """Gaps are not silent: each names an agent in the report, a side and a reason."""
    report = alignment_report()
    for gap in recorded_gaps():
        assert gap["agent"] in report
        assert gap["side"] in ("missing_from_prompt", "extra_in_prompt")
        assert len(gap["reason"].split()) >= 4


def test_new_gap_and_fixed_gap_are_reported_in_the_right_direction(monkeypatch):
    """Dropping a field from a prompt is a new gap; a gap the record lists but is closed is fixed."""
    _template_without(monkeypatch, "correspondence_specialist", "sender")
    new, fixed = compare_to_recorded()
    assert ("correspondence_specialist", "sender", "missing_from_prompt") in new
    assert not fixed
    report = alignment_report()
    report["contracts_specialist"]["missing_from_prompt"].remove("territory")
    _, fixed = compare_to_recorded(report)
    assert ("contracts_specialist", "territory", "missing_from_prompt") in fixed


def test_template_missing_a_field_shows_up_as_missing(monkeypatch):
    """A field the schema scores but the prompt no longer lists is ``missing_from_prompt``."""
    assert "claim_number" in field_types("insurance_claim")
    assert alignment_report()["insurance_claims_specialist"]["missing_from_prompt"] == []
    _template_without(monkeypatch, "insurance_claims_specialist", "claim_number")
    assert alignment_report()["insurance_claims_specialist"]["missing_from_prompt"] == ["claim_number"]


def test_meta_keys_are_never_extra():
    """``confidence`` and ``reasoning`` are asked for but never count as extra keys."""
    assert "confidence" in prompt_fields("correspondence_specialist")
    assert "reasoning" in prompt_fields("contracts_specialist")
    for row in alignment_report().values():
        assert not META_KEYS & set(row["extra_in_prompt"])


def test_report_covers_exactly_the_live_production_specialists():
    """Retired classes and auditors are not compared; the five live specialists are."""
    assert sorted(alignment_report()) == [
        "contracts_specialist",
        "corporate_records_specialist",
        "correspondence_specialist",
        "insurance_claims_specialist",
        "merger_agreement_specialist",
    ]


def test_prompt_fields_reads_name_and_declared_type():
    """The field block yields ``name -> declared type``; prose lines are ignored."""
    fields = prompt_fields("insurance_claims_specialist")
    assert fields["claim_number"].startswith("string")
    assert all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in fields)


def test_changelog_check_passes_on_the_committed_page():
    """The committed page is current."""
    assert changelog.main(["--check"]) == 0


def test_changelog_check_fails_on_a_stale_copy(tmp_path, capsys):
    """A page that no longer matches the catalog fails ``--check`` with a short message."""
    stale = tmp_path / "PROMPT_CHANGELOG.md"
    stale.write_text(changelog.render().replace("contracts_specialist", "contracts_specialisT", 1), encoding="utf-8")
    assert changelog.main(["--check", "--path", str(stale)]) == 1
    assert "is stale" in capsys.readouterr().err
    assert changelog.main(["--check", "--path", str(tmp_path / "missing.md")]) == 1


def test_changelog_write_then_check_round_trips(tmp_path):
    """``--write`` to a fresh path produces a page ``--check`` accepts."""
    page = tmp_path / "docs" / "PROMPT_CHANGELOG.md"
    assert changelog.main(["--write", "--path", str(page)]) == 0
    assert changelog.main(["--check", "--path", str(page)]) == 0


@pytest.mark.parametrize("agent", ["contracts_specialist", "sorter"])
def test_changelog_template_digest_is_the_template_file_digest(agent):
    """The sha256 in the page is the digest of the template file on disk."""
    rec = get_prompt(agent)
    digest = hashlib.sha256((changelog.TEMPLATES / rec.template).read_bytes()).hexdigest()
    assert f"| `{agent}` |" in changelog.render()
    row = next(line for line in changelog.render().splitlines() if line.startswith(f"| `{agent}` |"))
    assert digest in row
    assert changelog.template_sha256(rec.template) == digest


def test_changelog_lists_recorded_reasons_in_the_alignment_section():
    """Every recorded gap and its reason is printed under its agent."""
    page = changelog.render()
    section = page.split("## Prompt <-> schema alignment", 1)[1]
    for gap in recorded_gaps():
        assert f"`{gap['field']}`" in section
        assert gap["reason"] in section
