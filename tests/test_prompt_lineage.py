"""eval-environment prompt lineage — archived / frozen / mutation catalog.

Synced from eval-environment bdba24c by ``scripts/sync_eval_environment_lineage.py``.
The texts are historical eval-environment bytes, so the anti-priming rule from
``docs/PROMPTS.md`` is deliberately not asserted here. Network-free.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re

import pytest

import llm_dojo_scoring.prompts as prompts_pkg
from llm_dojo_scoring.prompts import (
    LINEAGE_SOURCE,
    PromptVersion,
    clear_prompt_cache,
    default_prompt_version,
    diff_prompt_versions,
    get_prompt,
    get_prompt_version,
    latest_prompt_version,
    list_prompt_versions,
    prompt_chain,
    prompt_roles,
)

ARCHIVED = {
    "contracts_specialist_v0",
    "contracts_specialist_v33",
    "corporate_records_specialist_v0",
    "correspondence_specialist_v0",
    "insurance_claims_specialist_v0",
}
FROZEN = {
    "sorter_v1",
    "contracts_specialist_v1",
    "corporate_records_specialist_v1",
    "correspondence_specialist_v1",
    "insurance_claims_specialist_v1",
    "sorter_reviewer_v1",
    "arbiter_v1",
    "boss_v1",
    "judge_v1",
    "judge-classification_v1",
    "judge-correctness_v1",
    "intake_v1",
    "pipeline_verdict_v1",
    "pipeline_quality_v1",
    "merger_agreement_specialist_v1",
}
MUTATIONS = {
    "sorter_v2",
    "sorter_v3",
    "sorter_v4",
    "contracts_specialist_v2",
    "contracts_specialist_v3",
    "corporate_records_specialist_v2",
    "corporate_records_specialist_v3",
    "corporate_records_specialist_v4",
    "corporate_records_specialist_v5",
    "corporate_records_specialist_v6",
    "correspondence_specialist_v2",
    "correspondence_specialist_v3",
    "correspondence_specialist_v4",
    "correspondence_specialist_v5",
    "correspondence_specialist_v6",
    "correspondence_specialist_v7",
    "insurance_claims_specialist_v2",
    "insurance_claims_specialist_v3",
    "merger_agreement_specialist_v2",
    "merger_agreement_specialist_v3",
}
ALL_KEYS = ARCHIVED | FROZEN | MUTATIONS


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_counts_and_key_set():
    assert {v.key for v in list_prompt_versions()} == ALL_KEYS
    assert len(ALL_KEYS) == 40
    assert {v.key for v in list_prompt_versions(lineage="archived")} == ARCHIVED
    assert {v.key for v in list_prompt_versions(lineage="frozen")} == FROZEN
    assert {v.key for v in list_prompt_versions(lineage="mutation")} == MUTATIONS


def test_source_metadata():
    assert dict(LINEAGE_SOURCE) == {
        "source_repo": "LLM-Mailroom-Services/eval-environment",
        "source_commit": "bdba24ca561aefa8f512d18362534626521601d8",
        "lineage_id": "mailroom-dataset-v1",
    }


@pytest.mark.parametrize("v", list_prompt_versions(), ids=lambda v: v.key)
def test_entry_integrity(v: PromptVersion):
    assert v.sha256 == _sha(v.text)
    assert v.chars == len(v.text)
    m = re.fullmatch(r"(.+)_v(\d+)", v.key)
    assert (v.role, v.version) == (m[1], int(m[2]))
    assert v.memo and v.created_at and v.source
    if v.predecessor is None:
        assert v.changes is None
    else:
        assert v.changes["against"] == v.predecessor
        assert v.changes["chars_delta"] == v.chars - get_prompt_version(v.predecessor).chars


def test_lineage_specific_links():
    for v in list_prompt_versions(lineage="mutation"):
        parent = get_prompt_version(v.parent)
        assert parent.role == v.role and parent.version == v.version - 1
        assert v.supersedes is None and v.anchor_head
        assert v.source == f"mutation-of:{v.parent}"
    for v in list_prompt_versions(lineage="archived"):
        assert v.parent is None and v.supersedes is None and v.anchor_head is None
    for v in list_prompt_versions(lineage="frozen"):
        assert v.version == 1 and v.parent is None and v.anchor_head is None
        v0 = f"{v.role}_v0"
        assert v.supersedes == (v0 if v0 in ARCHIVED else None)
        assert v.created_at == "2026-09-26T05:09:29+00:00"


def test_list_sorted_and_filtered():
    vs = list_prompt_versions()
    assert [(v.role, v.version) for v in vs] == sorted((v.role, v.version) for v in vs)
    assert [v.version for v in list_prompt_versions(role="correspondence_specialist")] == list(range(8))
    assert list_prompt_versions(role="nope") == []
    with pytest.raises(ValueError):
        list_prompt_versions(lineage="production")


def test_roles_including_hyphens():
    roles = prompt_roles()
    assert roles == sorted(roles)
    assert {"judge-classification", "judge-correctness", "sorter_reviewer"} <= set(roles)
    assert len(roles) == 15


@pytest.mark.parametrize(
    "role,tip,length",
    [("correspondence_specialist", 7, 8), ("corporate_records_specialist", 6, 7)],
)
def test_chain_v0_to_tip(role, tip, length):
    chain = prompt_chain(role)
    assert [v.key for v in chain] == [f"{role}_v{i}" for i in range(tip + 1)]
    assert len(chain) == length
    assert chain[0].lineage == "archived" and chain[1].supersedes == chain[0].key
    assert chain[-1].key == latest_prompt_version(role).key
    assert [v.key for v in prompt_chain(f"{role}_v3")] == [v.key for v in chain[:4]]


def test_chain_of_root_and_unknown():
    assert [v.key for v in prompt_chain("sorter_reviewer_v1")] == ["sorter_reviewer_v1"]
    assert [v.key for v in prompt_chain("sorter")] == [
        "sorter_v1", "sorter_v2", "sorter_v3", "sorter_v4",
    ]
    with pytest.raises(KeyError):
        prompt_chain("nonexistent_role")


def test_latest_prefers_frozen_and_mutation_over_archived():
    assert latest_prompt_version("sorter").key == "sorter_v4"
    # archived contracts_specialist_v33 (a re-keyed v0) must not win on number.
    assert latest_prompt_version("contracts_specialist").key == "contracts_specialist_v3"
    assert [v.key for v in prompt_chain("contracts_specialist")] == [
        f"contracts_specialist_v{i}" for i in range(4)
    ]
    for role in prompt_roles():
        assert latest_prompt_version(role).lineage != "archived"
    with pytest.raises(KeyError):
        latest_prompt_version("nope")


def test_v33_listed_and_explicit_chain_works():
    assert "contracts_specialist_v33" in {v.key for v in list_prompt_versions(role="contracts_specialist")}
    assert [v.key for v in prompt_chain("contracts_specialist_v33")] == ["contracts_specialist_v33"]
    v33, v0 = (get_prompt_version(k) for k in ("contracts_specialist_v33", "contracts_specialist_v0"))
    assert v33.text.rstrip("\n") == v0.text.rstrip("\n") and v33.text != v0.text
    assert "Text equals contracts_specialist_v0 apart from a trailing newline" in v33.memo


def test_default_is_frozen_v1():
    for role in prompt_roles():
        d = default_prompt_version(role)
        assert d.key == f"{role}_v1" and d.lineage == "frozen"
    with pytest.raises(KeyError):
        default_prompt_version("nope")


def test_unknown_key_suggests_close_matches():
    with pytest.raises(KeyError) as ei:
        get_prompt_version("correspondence_specialist_v77")
    assert "correspondence_specialist_v7" in str(ei.value)
    with pytest.raises(KeyError):
        get_prompt_version("zzz")


@pytest.mark.parametrize(
    "key,role",
    [
        ("correspondence_specialist_v7", "correspondence_specialist"),
        ("corporate_records_specialist_v6", "corporate_records_specialist"),
    ],
)
def test_corrected_records_equal_production_prompts_catalog(key, role):
    v = get_prompt_version(key)
    rec = get_prompt(role, family="production_prompts")
    assert v.text == rec.text
    assert rec.source_key == key
    # Two digest conventions: eval-environment hashes the raw text; the dojo
    # catalog hashes the text with a trailing newline ensured. These specialist
    # texts already end in "\n", so the digests coincide.
    assert v.text.endswith("\n")
    assert v.sha256 == rec.sha256 == _sha(rec.text)


def test_digest_conventions_differ_for_unterminated_text():
    sorter = get_prompt_version("sorter_v1")
    assert not sorter.text.endswith("\n")
    assert sorter.sha256 == _sha(sorter.text) != _sha(sorter.text + "\n")


def test_diff_prompt_versions():
    d = diff_prompt_versions("correspondence_specialist_v6", "correspondence_specialist_v7")
    lines = d.splitlines()
    assert lines[0] == "--- correspondence_specialist_v6"
    assert lines[1] == "+++ correspondence_specialist_v7"
    assert sum(ln.startswith("-") for ln in lines[2:]) == 5
    assert sum(ln.startswith("+") for ln in lines[2:]) == 5
    ch = get_prompt_version("correspondence_specialist_v7").changes
    assert (ch["lines_added"], ch["lines_removed"]) == (5, 5)
    assert diff_prompt_versions("boss_v1", "boss_v1") == ""
    assert len(diff_prompt_versions("sorter_v1", "sorter_v2", context=0)) < len(
        diff_prompt_versions("sorter_v1", "sorter_v2", context=5)
    )
    with pytest.raises(KeyError):
        diff_prompt_versions("boss_v1", "boss_v9")


def test_changes_summary_shape():
    ch = get_prompt_version("sorter_v2").changes
    assert ch["against"] == "sorter_v1"
    assert (ch["lines_added"], ch["lines_removed"]) == (12, 0)
    assert ch["sections_changed"] == ['CORPORATE RECORD SUBCLASS (only when doc_type is "corporate_record"):']
    assert ch["removed_excerpt"] == []
    for v in list_prompt_versions():
        if v.changes:
            for k in ("added_excerpt", "removed_excerpt"):
                assert len(v.changes[k]) <= 5 and all(len(s) <= 160 for s in v.changes[k])


def test_frozen_v1_changes_are_against_archived_v0():
    ch = get_prompt_version("contracts_specialist_v1").changes
    assert ch["against"] == "contracts_specialist_v0" and ch["chars_delta"] < 0


def test_data_file_is_deterministic_and_packaged():
    raw = importlib.resources.files("llm_dojo_scoring.prompts").joinpath(
        "eval_environment_lineage.json"
    ).read_text(encoding="utf-8")
    data = json.loads(raw)
    assert json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n" == raw
    assert "synced_at" not in data or re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:+]+", data["synced_at"])
    keys = [(v["role"], v["version"]) for v in data["versions"]]
    assert keys == sorted(keys)
    assert [v["key"] for v in data["versions"]] == [v.key for v in list_prompt_versions()]


def test_package_data_declares_json():
    import pathlib

    tomllib = pytest.importorskip("tomllib")  # py311+

    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    cfg = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "prompts/*.json" in cfg["tool"]["setuptools"]["package-data"]["llm_dojo_scoring"]


def test_clear_prompt_cache_reloads_lineage():
    before = list_prompt_versions()
    clear_prompt_cache()
    after = list_prompt_versions()
    assert before == after and before[0] is not after[0]


def test_reexported_from_package():
    for name in (
        "PromptVersion", "LINEAGE_SOURCE", "list_prompt_versions", "get_prompt_version",
        "prompt_roles", "prompt_chain", "latest_prompt_version", "default_prompt_version",
        "diff_prompt_versions",
    ):
        assert name in prompts_pkg.__all__ and hasattr(prompts_pkg, name)


def test_sorter_chain_is_explicit():
    chain = prompt_chain("sorter")
    assert [v.key for v in chain] == ["sorter_v1", "sorter_v2", "sorter_v3", "sorter_v4"]
    assert [v.lineage for v in chain] == ["frozen", "mutation", "mutation", "mutation"]
    assert [v.parent for v in chain] == [None, "sorter_v1", "sorter_v2", "sorter_v3"]
    assert [v.predecessor for v in chain] == [None, "sorter_v1", "sorter_v2", "sorter_v3"]
    assert chain[0].supersedes is None and chain[0].source == "production:sorter"
    assert latest_prompt_version("sorter").key == "sorter_v4"
    assert default_prompt_version("sorter").key == "sorter_v1"
    assert [v.key for v in list_prompt_versions(role="sorter")] == [
        "sorter_v1", "sorter_v2", "sorter_v3", "sorter_v4",
    ]
    # sorter_v2/v3 were created (2026-09-16) before the sorter_v1 freeze
    # (2026-09-26), so created_at is NOT monotonic along this chain.
    assert chain[1].created_at < chain[0].created_at
    assert "not monotonic" in chain[1].changes["notes"][0]


def test_sorter_v3_duplicated_corporate_record_block_is_recorded():
    # Known upstream defect: sorter_v3 carries its corporate_record block twice.
    v3 = get_prompt_version("sorter_v3")
    heading = 'CORPORATE RECORD SUBCLASS (only when doc_type is "corporate_record"):'
    assert v3.text.count(heading) == 2
    assert get_prompt_version("sorter_v2").text.count(heading) == 1
    assert any("appears 2 times" in n for n in v3.changes["notes"])
    assert v3.changes["sections_changed"] == [heading, heading + "#2"]


def test_notes_only_where_expected():
    flagged = {v.key for v in list_prompt_versions() if v.changes and v.changes["notes"]}
    assert flagged == {"sorter_v2", "sorter_v3", "sorter_v4"}


def test_sorter_v4_drops_the_duplicate_block_and_matches_production():
    v4 = get_prompt_version("sorter_v4")
    assert v4.parent == "sorter_v3" and v4.lineage == "mutation" and v4.version == 4
    assert v4.text.count("CORPORATE RECORD SUBCLASS") == 1
    for stale in ("formation_documents", "minutes", "cap_table", "resolutions"):
        assert stale not in v4.text
    assert any("duplicate removed" in n for n in v4.changes["notes"])
    assert get_prompt_version("sorter_v3").changes["notes"]  # v3 keeps its duplicate-block note
    # Without its corporate_record block, sorter_v4 is production sorter_v14.
    # The dojo template ends in exactly one "\n"; the lineage text is raw.
    a = v4.text.index("\n\nCORPORATE RECORD SUBCLASS")
    b = v4.text.index("\n\nCONTRACT SUBGROUP")
    assert a < b
    stripped = v4.text[:a] + v4.text[b:]
    prod = get_prompt("sorter").text
    assert prod == stripped + "\n"
    assert not v4.text.endswith("\n")
