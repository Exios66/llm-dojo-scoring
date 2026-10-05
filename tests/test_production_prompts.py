"""production_prompts lineage — eval-environment frozen v1 specialist stems.

The sha256 values pin the current text, including local field-guidance corrections.
Source lineage comes from the sandbox
``config/prompts/eval_environment_lineage.json`` (``mailroom-dataset-v1``,
frozen 2026-09-26T05:09:29+00:00). Network-free; no sandbox checkout needed.
"""

from __future__ import annotations

import hashlib

import pytest

from llm_dojo_scoring.prompts import FAMILIES, get_prompt, list_prompts

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
        "eval_key": "corporate_records_specialist_v1",
        "sandbox_stem": "corporate_records_specialist_simplified",
        "sha256": "fe13501f667fcd9f64f7dfbf8b0f124f81d9dd039f4109288b43f106f82b1399",
        "chars": 5865,
        "opening": "You are the corporate-records specialist.",
        "doc_bundle": "corporate_record",
    },
    "correspondence_specialist": {
        "eval_key": "correspondence_specialist_v1",
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
    raw = text if text.endswith("\n") else text + "\n"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_production_prompts_family_is_declared():
    assert "production_prompts" in FAMILIES


def test_production_prompts_records_are_llm_only():
    recs = list_prompts(family="production_prompts")
    assert {r.agent for r in recs} == set(FROZEN_V1)
    assert all(r.kind == "llm" for r in recs)
    assert all(r.text.strip() for r in recs)


@pytest.mark.parametrize("agent", sorted(FROZEN_V1))
def test_frozen_v1_record_matches_lineage(agent):
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
    for agent, meta in FROZEN_V1.items():
        rec = get_prompt(agent, family="production_prompts")
        assert "mailroom-dataset-v1" in rec.notes
        assert str(meta["sandbox_stem"]) in rec.notes


def test_frozen_v1_distinct_from_production_and_docclass():
    for agent in FROZEN_V1:
        v1 = get_prompt(agent, family="production_prompts").text
        production = get_prompt(agent).text
        docclass = get_prompt(agent, family="docclass").text
        assert v1 != production
        assert v1 != docclass


def test_provenance_comment_is_stripped_from_model_visible_text():
    for agent in FROZEN_V1:
        rec = get_prompt(agent, family="production_prompts")
        assert "<!--" not in rec.text
        assert rec.text.startswith("You are the")
