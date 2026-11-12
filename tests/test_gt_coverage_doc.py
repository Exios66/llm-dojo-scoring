"""``scripts/render_gt_coverage.py`` and the generated ``docs/schemas/GT_COVERAGE.md``.

Covers the rendering, the ``--check`` gate, the "never seen" section, and the
property the page exists for: a dataset revision that labels more rows changes a
field's status with no code edit.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from conftest import load_script
from llm_dojo_scoring.schemas import extraction_schemas as es


@pytest.fixture(scope="module")
def mod():
    """The render script, loaded by path."""
    return load_script("render_gt_coverage")


@pytest.fixture
def inject_status(monkeypatch):
    """Serve a synthetic status through the module's ``_status_data`` accessor, then restore."""

    def install(status: dict) -> None:
        """Replace the status data and drop the memoised schemas built from the old one."""
        monkeypatch.setattr(es, "_status_data", lambda: status)
        es._cached.cache_clear()

    yield install
    monkeypatch.undo()
    es._cached.cache_clear()


def _status(adjuster_populated: int, rows: int = 1100) -> dict:
    """A synthetic status: one insurance subtype, two labelled fields."""
    absent = rows - adjuster_populated
    return {
        "dataset": "example/dataset",
        "config": "ground_truth",
        "revision": "vTEST",
        "commit": "f" * 40,
        "rows": rows,
        "doc_types": {
            "insurance_claim": {
                "auto": {
                    "rows": rows,
                    "surfaces": {"auto": rows},
                    "fields": {
                        "claim_number": {"populated": rows},
                        "adjuster": {
                            "populated": adjuster_populated,
                            **({"schema_documented_absence": absent} if absent else {}),
                        },
                    },
                }
            },
            "merger_agreement": {
                "all_cash": {
                    "rows": 10,
                    "surfaces": {"All Cash": 10},
                    "fields": {"intent": {"not_applicable": 10}},
                }
            },
        },
        "vocabulary": {
            "insurance_claim": {
                "intent": {
                    "rows_with_value": rows,
                    "values": {"claim_filing": rows, "loss_report": 0},
                    "outside_vocabulary": {},
                }
            },
            "merger_agreement": {
                "intent": {"rows_with_value": 0, "values": {"amend_merger": 0}, "outside_vocabulary": {}}
            },
        },
    }


def _insurance_table_rows(text: str) -> dict[str, list[str]]:
    """Cells of the insurance_claim table rows, by field name."""
    section = text.split("## insurance_claim", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = re.match(r"\| `([a-z_]+)` \|", line)
        if match:
            assert match.group(1) not in rows, f"{match.group(1)} listed twice"
            rows[match.group(1)] = [cell.strip() for cell in line.strip("|").split("|")]
    return rows


def test_render_lists_each_field_once_with_status_and_populated_count(mod, inject_status):
    """A two-field status renders each labelled field once: status, populated / rows, share."""
    status = _status(150)
    inject_status(status)
    text = mod.render(status)
    rows = _insurance_table_rows(text)
    assert rows["adjuster"][2:5] == ["partial", "150 / 1,100", "13.6%"]
    assert rows["claim_number"][2:5] == ["scored", "1,100 / 1,100", "100.0%"]
    assert "vTEST" in text and "f" * 40 in text and "example/dataset" in text
    assert "scored now: 3 of 18 fields" in text.split("## insurance_claim", 1)[1]


def _cms_mixed_status() -> dict:
    """A status with one non-CMS (``auto``, 300 rows) and one CMS (``pde``, 150 rows) subtype."""
    status = _status(0, rows=300)
    insurance = status["doc_types"]["insurance_claim"]
    insurance["pde"] = {
        "rows": 150,
        "surfaces": {"pde": 150},
        "fields": {"claim_number": {"populated": 150}},
    }
    return status


def test_cms_source_table_counts_only_cms_subtypes(mod, inject_status):
    """``cms_source_table`` is derived on CMS tables only, so auto/property rows are not populated."""
    status = _cms_mixed_status()
    inject_status(status)
    cells = _insurance_table_rows(mod.render(status))["cms_source_table"]
    assert cells[3:5] == ["150 / 450", "33.3%"]


def test_other_subtype_derived_fields_still_count_every_subtype(mod, inject_status):
    """A class whose subtype *is* the truth (contract ``cuad_family``) is populated on every row."""
    status = _status(150)
    status["doc_types"]["contract"] = {
        "license": {"rows": 10, "surfaces": {"License": 10}, "fields": {}},
        "supply": {"rows": 5, "surfaces": {"Supply": 5}, "fields": {}},
    }
    inject_status(status)
    section = mod.render(status).split("## contract", 1)[1].split("\n## ", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith("| `cuad_family` |"))
    assert "| 15 / 15 | 100.0% |" in row


def _contract_status() -> dict:
    """A status whose contract rows carry a populated ``cuad_clause_labels`` container."""
    status = _status(150)
    status["doc_types"]["contract"] = {
        "license": {
            "rows": 10,
            "surfaces": {"License": 10},
            "fields": {"cuad_clause_labels": {"populated": 8}},
        }
    }
    return status


def test_label_container_counts_are_labelled_as_source_container_coverage(mod, inject_status):
    """CUAD/MAUD-derived counts are rows with a label container, not per-category answers: say so."""
    status = _contract_status()
    inject_status(status)
    text = mod.render(status)
    contract = text.split("## contract", 1)[1].split("\n## ", 1)[0]
    assert "source-container coverage" in contract
    note = next(line for line in contract.splitlines() if "source-container coverage" in line)
    assert "`cuad_clause_labels`" in note and "`maud_clause_labels`" not in note
    assert "not the rows that answer" in contract
    assert "8 / 10" in contract  # the counter itself is unchanged
    insurance = text.split("## insurance_claim", 1)[1].split("\n## ", 1)[0]
    assert "source-container coverage" not in insurance


def test_cuad_fields_count_rows_that_carry_their_own_category(mod, inject_status):
    """With per-category counts, a CUAD field shows rows whose span answers its category; ``cuad_clauses`` keeps the container."""
    status = _contract_status()
    status["label_categories"] = {
        "contract": {
            "cuad_clause_labels": {
                "Parties": {"labeled": 7, "with_spans": 6},
                "Governing Law": {"labeled": 5, "with_spans": 2},
            }
        }
    }
    inject_status(status)
    text = mod.render(status)
    contract = text.split("## contract", 1)[1].split("\n## ", 1)[0]
    rows = {
        m.group(1): line
        for line in contract.splitlines()
        if (m := re.match(r"\| `([a-z_]+)` \|", line))
    }
    assert "| 6 / 10 |" in rows["parties"]  # rows whose span gives a value
    assert "7 labelled, 1 with no span" in rows["parties"]
    assert "| 2 / 10 |" in rows["governing_law"]
    assert "5 labelled, 3 with no span" in rows["governing_law"]
    assert "| 0 / 10 |" in rows["renewal_terms"]  # no row labels that category
    assert "0 labelled" in rows["renewal_terms"]
    assert "| 8 / 10 |" in rows["cuad_clauses"]  # all categories: the container count
    assert "category coverage" in contract
    assert "source-container coverage" not in contract


def test_render_reports_a_class_with_no_rows(mod, inject_status):
    """A class absent from the status says so instead of inventing counts."""
    status = _status(150)
    inject_status(status)
    assert "no ground-truth rows" in mod.render(status).split("## contract", 1)[1].split("\n## ", 1)[0]


def test_never_seen_lists_zero_row_values_and_separates_not_applicable(mod, inject_status):
    """Zero-row vocabulary values are label gaps; a not-applicable field is noted apart."""
    status = _status(150)
    inject_status(status)
    text = mod.render(status)
    never = text.split("## Never seen in ground truth", 1)[1].split("\n## ", 1)[0]
    assert "insurance_claim" in never and "`loss_report`" in never
    assert "`claim_filing`" not in never
    assert "merger_agreement.intent" in never.split("not applicable", 1)[1]
    assert "`amend_merger`" not in never.split("not applicable", 1)[0]


def test_check_exits_1_with_a_diff_when_the_doc_differs_and_0_when_current(mod, tmp_path, capsys, monkeypatch):
    """``--check`` compares the rendered page with the file on disk."""
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps(_status(150)), encoding="utf-8")
    doc_path = tmp_path / "GT_COVERAGE.md"
    monkeypatch.setattr(mod, "STATUS_PATH", status_path)
    monkeypatch.setattr(mod, "DOC_PATH", doc_path)
    assert mod.main(["--check"]) == 1  # no file yet
    assert mod.main(["--write"]) == 0
    assert mod.main(["--check"]) == 0
    capsys.readouterr()
    doc_path.write_text(doc_path.read_text(encoding="utf-8") + "stale edit\n", encoding="utf-8")
    assert mod.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "-stale edit" in err and "scripts/render_gt_coverage.py --write" in err


def test_committed_doc_is_current(mod):
    """The page in the repository matches the committed status file."""
    assert mod.main(["--check"]) == 0


def test_committed_doc_names_the_pinned_revision(mod):
    """The header carries the dataset, revision and commit of the status file."""
    status = json.loads(mod.STATUS_PATH.read_text(encoding="utf-8"))
    text = mod.DOC_PATH.read_text(encoding="utf-8")
    for key in ("dataset", "revision", "commit"):
        assert status[key] in text
    assert text.lstrip().startswith("<!--") or "generated" in text.split("\n## ", 1)[0].lower()


def test_more_labels_flip_a_status_with_no_code_change(inject_status):
    """Review focus 3: adjuster labelled on 1,100 rows instead of 150 becomes scored."""
    base = _status(150)
    inject_status(base)
    assert es.extraction_schema("insurance_claim").fields["adjuster"].status == "partial"
    grown = copy.deepcopy(base)
    grown["doc_types"]["insurance_claim"]["auto"]["fields"]["adjuster"] = {"populated": 1100}
    inject_status(grown)
    assert es.extraction_schema("insurance_claim").fields["adjuster"].status == "scored"
    assert "adjuster" in es.extraction_schema("insurance_claim").scored_fields


def test_a_dropped_field_goes_back_to_pending_with_no_code_change(inject_status):
    """A revision that stops labelling a field makes it unscored again."""
    inject_status(_status(150))
    assert es.extraction_schema("insurance_claim").fields["claim_number"].status == "scored"
    without = _status(150)
    del without["doc_types"]["insurance_claim"]["auto"]["fields"]["claim_number"]
    inject_status(without)
    assert es.extraction_schema("insurance_claim").fields["claim_number"].status == "pending_annotation"
