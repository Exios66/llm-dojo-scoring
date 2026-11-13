"""production_prompts lineage — eval-environment frozen v1 specialist stems.

The sha256 values pin the current text. Corporate-records and correspondence carry the
field-guidance corrections that eval-environment froze as mutations
``corporate_records_specialist_v7`` / ``correspondence_specialist_v7`` (#29).
Source lineage comes from the sandbox
``config/prompts/eval_environment_lineage.json`` (``mailroom-dataset-v1``,
frozen 2026-09-26T05:09:29+00:00). Network-free; no sandbox checkout needed.
"""

from __future__ import annotations

import hashlib

import pytest

from llm_dojo_scoring.prompts import FAMILIES, get_prompt, get_prompt_version, list_prompts
from llm_dojo_scoring.prompts.alignment import prompt_fields
from llm_dojo_scoring.schemas.doc_classes import field_types
from llm_dojo_scoring.schemas.intents import MERGER_INTENTS

FROZEN_V1: dict[str, dict[str, object]] = {
    "contracts_specialist": {
        "eval_key": "contracts_specialist_v1",
        "sandbox_stem": "contracts_specialist_v33_simplified",
        "sha256": "d91de3967cc3b12cbd222cc5a4ae167b39578125abc83be7422498dc5024fd24",
        "chars": 9882,
        "opening": "You are the contracts specialist.",
        "doc_bundle": "contract",
    },
    "corporate_records_specialist": {
        "eval_key": "corporate_records_specialist_v7",
        "sandbox_stem": "corporate_records_specialist_simplified",
        "sha256": "253559fcb7ac6b36878453821a4fab0aa94228ad5add77d5aeabb06bb265134c",
        "chars": 5462,
        "opening": "You are the corporate-records specialist.",
        "doc_bundle": "corporate_record",
    },
    "correspondence_specialist": {
        "eval_key": "correspondence_specialist_v7",
        "sandbox_stem": "correspondence_specialist_simplified",
        "sha256": "2b0b81ff98920b9207627707443e2b023db39212fda5bdcba7bfbded39fa38b6",
        "chars": 6113,
        "opening": "You are the correspondence specialist.",
        "doc_bundle": "correspondence",
    },
    "insurance_claims_specialist": {
        "eval_key": "insurance_claims_specialist_v1",
        "sandbox_stem": "insurance_claims_specialist_simplified",
        "sha256": "6c2776bcbe00091200aecbcfd21c99f197398d929143dd0c7c722811fa100034",
        "chars": 6277,
        "opening": "You are the insurance-claims specialist.",
        "doc_bundle": "insurance_claim",
    },
    "merger_agreement_specialist": {
        "eval_key": "merger_agreement_specialist_v1",
        "sandbox_stem": "merger_agreement_specialist_simplified",
        "sha256": "003232584d6890054d956398135f439b86692a1123683f58914c0393b5e1a00b",
        "chars": 6116,
        "opening": "You are the merger-agreement specialist.",
        "doc_bundle": "merger_agreement",
    },
}


def _frozen_sha(text: str) -> str:
    """Hash prompt bytes with the frozen catalog's trailing-newline convention."""
    raw = text if text.endswith("\n") else text + "\n"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_production_prompts_family_is_declared():
    """Expose the frozen evaluation prompt family in the catalog."""
    assert "production_prompts" in FAMILIES


def test_production_prompts_records_are_llm_only():
    """Include exactly the frozen specialist set with nonempty LLM prompt bodies."""
    recs = list_prompts(family="production_prompts")
    assert {r.agent for r in recs} == set(FROZEN_V1)
    assert all(r.kind == "llm" for r in recs)
    assert all(r.text.strip() for r in recs)


@pytest.mark.parametrize("agent", sorted(FROZEN_V1))
def test_frozen_v1_record_matches_lineage(agent):
    """Pin frozen prompt bytes, lengths, openings, and source metadata to recorded lineage."""
    rec = get_prompt(agent, family="production_prompts")
    meta = FROZEN_V1[agent]
    assert rec.kind == "llm"
    assert rec.version == "v1"
    assert rec.source_repo == "LLM-Mailroom-Services/eval-environment"
    assert rec.source_key == meta["eval_key"]
    assert rec.sha256 == meta["sha256"]
    assert rec.doc_bundle == meta["doc_bundle"]
    assert _frozen_sha(rec.text) == meta["sha256"]
    assert len(rec.text) == meta["chars"]
    assert rec.text.splitlines()[0].startswith(str(meta["opening"]))


def test_frozen_v1_notes_pin_lineage_and_sandbox_stem():
    """Record the dataset lineage and matching sandbox prompt stem in frozen notes."""
    for agent, meta in FROZEN_V1.items():
        rec = get_prompt(agent, family="production_prompts")
        assert "mailroom-dataset-v1" in rec.notes
        assert str(meta["sandbox_stem"]) in rec.notes


def test_frozen_v1_distinct_from_docclass():
    # The evaluation stems remain distinct from the docclass lineage.
    """Keep frozen evaluation prompts distinct from historical docclass templates."""
    for agent in FROZEN_V1:
        v1 = get_prompt(agent, family="production_prompts").text
        docclass = get_prompt(agent, family="docclass").text
        assert v1 != docclass


def test_provenance_comment_is_stripped_from_model_visible_text():
    """Remove HTML provenance comments before exposing prompts to the model."""
    for agent in FROZEN_V1:
        rec = get_prompt(agent, family="production_prompts")
        assert "<!--" not in rec.text
        assert rec.text.startswith("You are the")


# --- v0.20.0: production family re-vendored from live mailroom -------------

LIVE = ("contracts_specialist", "corporate_records_specialist", "correspondence_specialist",
        "insurance_claims_specialist", "merger_agreement_specialist")


#: Specialists whose production prompt is v2: authored in this repo as frozen v1 plus every
#: registry field. Their frozen v1 bytes stay in the production_prompts family.
PRODUCTION_V2 = ("contracts_specialist", "merger_agreement_specialist")


def test_production_specialists_are_frozen_v1():
    """Use frozen specialist bodies while retaining the production corporate-records v6 pin."""
    for a in LIVE:
        if a in PRODUCTION_V2:
            continue
        if a == "corporate_records_specialist":
            # Mailroom still pins v6; evaluation v7 must not advance production.
            text = get_prompt(a).text
            assert text == get_prompt_version("corporate_records_specialist_v6").text
            assert _frozen_sha(text) == "fe13501f667fcd9f64f7dfbf8b0f124f81d9dd039f4109288b43f106f82b1399"
            assert text != get_prompt(a, family="production_prompts").text
        else:
            assert get_prompt(a).text == get_prompt(a, family="production_prompts").text


def test_production_specialist_rows_say_frozen_v1():
    """Attach frozen-v1 version metadata and a source commit to the specialists still on frozen v1."""
    for a in LIVE:
        if a in PRODUCTION_V2:
            continue
        rec = get_prompt(a)
        assert rec.version == "v1"
        assert rec.source_key == "frozen_v1"
        assert rec.source_commit


#: sha256 (frozen-catalog convention) and character count of each production v2 template.
V2_TEMPLATES = {
    "contracts_specialist": ("21dc7e398a6c5ce06cc8715f02a3709b57feb1b3add8a0d13464ee4849e69684", 11202),
    "merger_agreement_specialist": ("cb2ea4c75744a6477a19dc12dbaff45dfb26a9988fbdd5953de4585fb9352546", 8092),
}


@pytest.mark.parametrize("agent", PRODUCTION_V2)
def test_production_v2_row_is_authored_here_and_keeps_its_base_commit(agent):
    """The v2 row names this repo as its source and the llm-mailroom commit of the v1 base it grew from."""
    rec = get_prompt(agent)
    v1 = get_prompt(agent, family="production_prompts")
    assert rec.version == "v2"
    assert rec.source_repo == "llm-dojo-scoring"
    assert rec.source_key == "production_v2"
    assert rec.source_commit == "19203eac07f67c215f50af2fd498560ce195adae"
    assert "frozen_v1" in rec.notes and "not a commit of this repo" in rec.notes
    assert v1.version == "v1" and v1.source_key == FROZEN_V1[agent]["eval_key"]


@pytest.mark.parametrize("agent", PRODUCTION_V2)
def test_production_v2_text_extends_frozen_v1_with_every_registry_field(agent):
    """v2 differs from the frozen v1 bytes, which stay intact, and asks for every scored field."""
    rec = get_prompt(agent)
    v1 = get_prompt(agent, family="production_prompts")
    assert rec.text != v1.text
    assert _frozen_sha(v1.text) == FROZEN_V1[agent]["sha256"]
    asked = set(prompt_fields(agent))
    assert set(field_types(FROZEN_V1[agent]["doc_bundle"])) <= asked
    assert "<!--" not in rec.text and rec.text.startswith("You are the")


@pytest.mark.parametrize("agent", PRODUCTION_V2)
def test_production_v2_field_block_follows_the_registry_order(agent):
    """The field block lists reasoning first, the registry fields in registry order, confidence last."""
    names = list(prompt_fields(agent))
    registry = list(field_types(FROZEN_V1[agent]["doc_bundle"]))
    assert names == ["reasoning", *registry, "confidence"]


@pytest.mark.parametrize("agent", sorted(V2_TEMPLATES))
def test_production_v2_template_digest_is_pinned(agent):
    """Pin the v2 template bytes; a prompt edit must change the pin, the version and the changelog."""
    sha, chars = V2_TEMPLATES[agent]
    text = get_prompt(agent).text
    assert _frozen_sha(text) == sha
    assert len(text) == chars


def test_contract_prompt_no_longer_asks_for_merger_keys():
    """Merger keys belong to the merger specialist; the contract prompt only says not to emit them."""
    text = get_prompt("contracts_specialist").text
    assert "- merger_consideration (" not in text and "- maud_clauses (" not in text
    assert "Do not emit merger_consideration or maud_clauses" in text


def test_merger_intent_line_lists_the_registry_tokens():
    """The intent field names exactly the MERGER_INTENTS tokens, not examples."""
    line = next(ln for ln in get_prompt("merger_agreement_specialist").text.splitlines() if ln.startswith("- intent ("))
    assert ", ".join(MERGER_INTENTS) in line


def test_production_family_has_no_retired_vocabulary():
    """Exclude retired classes and allow retired fields only in explicit prohibitions."""
    for a in ("sorter", "boss", "arbiter", "sorter_reviewer", "judge", "judge-classification", *LIVE):
        text = get_prompt(a).text
        assert "compliance_filing" not in text
        for retired in ("key_obligations", "termination_clauses", "key_provisions", "key_points", "referenced_communications"):
            # The immutable frozen v1 bytes may name a retired field only to
            # forbid it ("Do not emit ...").
            for line in text.splitlines():
                if retired in line:
                    assert "not emit" in line.lower(), (a, retired)


def test_reporter_is_deterministic():
    """Classify the reporter as deterministic rather than an LLM prompt."""
    assert get_prompt("reporter").kind == "deterministic"
