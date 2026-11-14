"""Guards in scripts/sync_production_prompts.py: a frozen_v1 body must match mailroom's
recorded digest, and a managed (``production``-bound) body may not change under the
catalog's existing version name."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from conftest import load_script

CATALOG = """description: test
prompts:
- agent: sorter
  family: production
  version: sorter_condensed_v5
  kind: llm
  source_repo: llm-mailroom
  source_key: sorter_condensed_v5
  source_commit: old
  template: sorter.production.md
- agent: corporate_records_specialist
  family: production
  version: v1
  kind: llm
  source_repo: llm-mailroom
  source_key: frozen_v1
  source_commit: old
  template: corporate_records_specialist.production.md
- agent: judge
  family: production
  version: judge_v3
  kind: llm
  source_repo: llm-mailroom
  source_key: judge_v3
  source_commit: old
  template: judge.production.md
"""


def _mailroom(tmp_path, *, specialist="SPEC BODY\n", judge="JUDGE BODY\n", digest=None):
    """Build a minimal git-backed mailroom checkout with prompts and a frozen_v1 lineage."""
    root = tmp_path / "mailroom"
    pkg = root / "src" / "llm"
    (pkg / "frozen_v1").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "prompts.py").write_text(
        "def _bound_prompt_versions():\n"
        "    return {'sorter': 'sorter_condensed_v5', 'corporate_records_specialist': 'frozen_v1',"
        " 'judge': 'production'}\n"
        "def prompt_templates():\n"
        f"    return {{'sorter': 'SORTER\\n', 'corporate_records_specialist': {specialist!r},"
        f" 'judge': {judge!r}}}\n"
    )
    sha = digest or hashlib.sha256(specialist.encode()).hexdigest()
    (pkg / "frozen_v1" / "lineage.json").write_text(
        json.dumps({"specialists": {"corporate_records_specialist": {"sha256": sha}}}))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    return root


@pytest.fixture
def sync(tmp_path, monkeypatch):
    """Load the sync script with its catalog and templates redirected to tmp_path."""
    mod = load_script("sync_production_prompts")
    templates = tmp_path / "templates"
    templates.mkdir()
    (tmp_path / "catalog.yaml").write_text(CATALOG)
    (templates / "judge.production.md").write_text(mod._render("judge_v3", "JUDGE BODY\n"))
    monkeypatch.setattr(mod, "TEMPLATES", templates)
    monkeypatch.setattr(mod, "CATALOG", tmp_path / "catalog.yaml")
    for name in [m for m in sys.modules if m == "llm" or m.startswith("llm.")]:
        monkeypatch.delitem(sys.modules, name)
    yield mod, templates, tmp_path / "catalog.yaml"
    for name in [m for m in sys.modules if m == "llm" or m.startswith("llm.")]:
        sys.modules.pop(name, None)


def test_sync_writes_when_digest_matches_and_managed_body_is_unchanged(sync, tmp_path, capsys):
    """A matching digest and an unchanged managed body sync and move source_commit."""
    mod, templates, catalog = sync
    assert mod.main(["--mailroom", str(_mailroom(tmp_path))]) == 0
    assert (templates / "corporate_records_specialist.production.md").read_text() == \
        mod._render("frozen_v1", "SPEC BODY\n")
    assert "source_commit: old" not in catalog.read_text()


def test_frozen_body_with_wrong_digest_is_refused_and_nothing_is_written(sync, tmp_path, capsys):
    """A frozen_v1 body that misses mailroom's digest is refused; nothing is written."""
    mod, templates, catalog = sync
    assert mod.main(["--mailroom", str(_mailroom(tmp_path, digest="0" * 64))]) == 1
    assert "frozen_v1 body sha256" in capsys.readouterr().err
    assert not (templates / "corporate_records_specialist.production.md").exists()
    assert catalog.read_text() == CATALOG


def test_changed_managed_body_is_refused_under_its_old_version(sync, tmp_path, capsys):
    """A changed managed body is refused instead of shipping under its old version."""
    mod, templates, catalog = sync
    assert mod.main(["--mailroom", str(_mailroom(tmp_path, judge="NEW JUDGE\n"))]) == 1
    assert "managed production body changed" in capsys.readouterr().err
    assert (templates / "judge.production.md").read_text() == mod._render("judge_v3", "JUDGE BODY\n")
    assert catalog.read_text() == CATALOG


def test_changed_managed_body_syncs_once_the_catalog_names_it(sync, tmp_path):
    """Following the refusal's instruction (a new version and source_key) lets the sync run."""
    mod, templates, catalog = sync
    catalog.write_text(CATALOG.replace("version: judge_v3", "version: judge_v4")
                       .replace("source_key: judge_v3", "source_key: judge_v4"))
    assert mod.main(["--mailroom", str(_mailroom(tmp_path, judge="NEW JUDGE\n"))]) == 0
    assert (templates / "judge.production.md").read_text() == mod._render("judge_v4", "NEW JUDGE\n")
    assert "source_key: judge_v4" in catalog.read_text()


def test_missing_lineage_refuses_frozen_bodies_with_a_clear_reason(sync, tmp_path, capsys):
    """No lineage.json means no digest to check, so frozen_v1 bodies are refused by name."""
    mod, _, _ = sync
    root = _mailroom(tmp_path)
    (root / "src" / "llm" / "frozen_v1" / "lineage.json").unlink()
    assert mod.main(["--mailroom", str(root)]) == 1
    assert "no frozen_v1 digest" in capsys.readouterr().err


def test_dojo_authored_row_is_neither_overwritten_nor_digest_checked(sync, tmp_path, capsys):
    """A production row authored here (v2) keeps its body and metadata though mailroom serves frozen_v1."""
    mod, templates, catalog = sync
    authored = (CATALOG.replace("version: v1", "version: v2")
                .replace("source_repo: llm-mailroom\n  source_key: frozen_v1",
                         "source_repo: llm-dojo-scoring\n  source_key: production_v2"))
    catalog.write_text(authored)
    v2 = mod._render("production_v2", "V2 BODY WITH EVERY FIELD\n")
    (templates / "corporate_records_specialist.production.md").write_text(v2)
    # a wrong frozen digest would refuse a frozen_v1 row; the authored row is not checked at all
    assert mod.main(["--mailroom", str(_mailroom(tmp_path, digest="0" * 64))]) == 0
    assert (templates / "corporate_records_specialist.production.md").read_text() == v2
    row = catalog.read_text().split("- agent: corporate_records_specialist")[1].split("- agent: judge")[0]
    assert "version: v2" in row and "source_key: production_v2" in row and "source_commit: old" in row
    assert "authored in this repo, not synced: corporate_records_specialist" in capsys.readouterr().out
    assert mod.main(["--mailroom", str(_mailroom(tmp_path / "again", digest="0" * 64)), "--check"]) == 0
    assert "(not compared: corporate_records_specialist)" in capsys.readouterr().out
