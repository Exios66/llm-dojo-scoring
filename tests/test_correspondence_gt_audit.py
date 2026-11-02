"""Correspondence GT audit and intent split (issue #94).

The SAND-042 RCA inferred that correspondence ``subject_matter`` / ``keywords``
GT is templated and that ``intent`` drives a bimodal headline. These tests pin
the detectors on synthetic rows shaped like that finding, plus clean rows the
audit must leave alone.
"""

from __future__ import annotations

import json

import pytest

from conftest import load_script
from llm_dojo_scoring.metrics.scorecard_honesty import aggregate_quality_honest, intent_split
from llm_dojo_scoring.schemas.correspondence_gt_audit import (
    CORRESPONDENCE_DEFECT_CODES,
    audit_correspondence_gt,
    audit_correspondence_gt_row,
    correspondence_populated_fields,
    is_metadata_keyword,
    is_templated_subject_matter,
)

audit_script = load_script("audit_correspondence_gt")

TEMPLATED_ROW = {
    "expected": "correspondence",
    "gt_fields": json.dumps(
        {
            "intent": "information_request",
            "subject_matter": "Correspondence concerning general_business.",
            "keywords": '["general_business", "inbox", "2001-05-14 09:32:00"]',
            "sender": "",
            "gt_presence": json.dumps({"sender": "pending_annotation"}),
        }
    ),
}
CLEAN_ROW = {
    "expected": "correspondence",
    "gt_fields": {
        "intent": "meeting_invite",
        "subject_matter": "Rescheduling the Q3 gas-trading review with the risk desk.",
        "keywords": ["gas trading", "risk desk", "Q3 review"],
        "sender": "Jeff Skilling",
    },
}


@pytest.mark.parametrize(
    "value",
    [
        "Correspondence concerning general_business.",
        "correspondence regarding energy market",
        "Email about scheduling",
        "Notes on the hr_personnel backlog",
    ],
)
def test_templated_subject_matter_is_flagged(value):
    """A topic-key frame or an embedded snake_case topic key is templated."""
    assert is_templated_subject_matter(value)


@pytest.mark.parametrize(
    "value",
    ["Rescheduling the Q3 review.", "Correspondence concerning the pipeline outage.", "", None, 3],
)
def test_real_subject_matter_is_not_flagged(value):
    """Grounded summaries, including ones that open with the frame, pass."""
    assert not is_templated_subject_matter(value)


@pytest.mark.parametrize(
    "value",
    [
        "general_business",
        "Sent Items",
        "_sent_mail",
        "skilling-j/inbox",
        "/enron/maildir/x",
        "2001-05-14",
        "05/14/2001 09:32",
        "9:32 am",
        "20010514093200",
        "jeff.skilling@enron.com",
    ],
)
def test_metadata_keywords_are_flagged(value):
    """Topic keys, folders, paths, stamps and addresses are metadata."""
    assert is_metadata_keyword(value)


@pytest.mark.parametrize("value", ["gas trading", "California ISO", "Q3 review", "2001 budget", "", 7])
def test_content_keywords_are_not_flagged(value):
    """Ordinary content keywords, even with a year in them, are not metadata."""
    assert not is_metadata_keyword(value)


def test_templated_row_reports_every_defect():
    """The RCA-shaped row trips both label detectors."""
    assert audit_correspondence_gt_row(TEMPLATED_ROW["gt_fields"]) == [
        "subject_matter_templated",
        "keywords_metadata",
        "keywords_all_metadata",
    ]


def test_clean_row_has_no_defects_and_counts_its_population():
    """A grounded row is clean; its populated fields are listed in map order."""
    assert audit_correspondence_gt_row(CLEAN_ROW["gt_fields"]) == []
    assert correspondence_populated_fields(CLEAN_ROW["gt_fields"]) == [
        "sender",
        "intent",
        "subject_matter",
        "keywords",
    ]


def test_presence_absence_and_missing_intent():
    """An absent-by-presence field is not population; missing intent is named."""
    row = {"subject_matter": "x", "gt_presence": {"intent": "not_applicable"}, "intent": "fyi"}
    assert audit_correspondence_gt_row(row) == ["intent_missing"]
    assert "sender" not in correspondence_populated_fields(TEMPLATED_ROW["gt_fields"])


def test_aggregate_counts_population_and_skips_other_classes():
    """The report states defects, per-field population and never-scored fields."""
    report = audit_correspondence_gt(
        [TEMPLATED_ROW, CLEAN_ROW, {"expected": "contract", "gt_fields": {}}, {"expected": "correspondence", "gt_fields": "{bad"}]
    )
    assert report["n_rows"] == 3
    assert report["totals"]["subject_matter_templated"] == 1
    assert report["totals"]["gt_unparseable"] == 1
    assert report["field_population"]["intent"] == 2
    assert report["field_population"]["sender"] == 1
    assert report["populated_field_counts"] == {0: 1, 3: 1, 4: 1}
    assert "urgency" in report["unscored_fields"]
    assert set(report["totals"]) <= set(CORRESPONDENCE_DEFECT_CODES)


def test_script_exits_one_on_templated_gt(tmp_path, capsys):
    """The CLI fails on templated GT and passes a clean file."""
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(TEMPLATED_ROW) + "\n", encoding="utf-8")
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps(CLEAN_ROW) + "\n", encoding="utf-8")
    assert audit_script.main([str(bad)]) == 1
    assert "subject_matter_templated: 1/1" in capsys.readouterr().out
    assert audit_script.main([str(good), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["n_rows"] == 1


def _three_field(intent):
    """A three-field correspondence document row with the given intent score."""
    fields = {"intent": intent, "subject_matter": 0.4, "keywords": 0.2}
    return {"overall_score": sum(fields.values()) / 3, "field_scores": fields}


def test_intent_split_makes_the_bimodality_visible():
    """Intent hits and misses are counted apart from the other fields."""
    rows = [_three_field(1.0), _three_field(1.0), _three_field(0.0), {"status": "unscorable"}]
    split = intent_split(rows)
    assert split == {
        "field": "intent",
        "n_intent": 3,
        "intent_mean": pytest.approx(0.6667, abs=1e-4),
        "n_intent_hit": 2,
        "n_intent_missed": 1,
        "n_other": 3,
        "other_fields_mean": pytest.approx(0.3),
    }


def test_intent_split_absent_without_intent_scores():
    """No intent field score means no split, and no key on the aggregate."""
    rows = [{"overall_score": 0.5, "field_scores": {"sender": 0.5}}]
    assert intent_split(rows) is None
    assert "intent_split" not in aggregate_quality_honest(rows, doc_class="correspondence")


def test_honest_aggregate_carries_intent_split_and_partial_scope():
    """The correspondence aggregate shows both the split and the 3-field scope."""
    out = aggregate_quality_honest([_three_field(1.0), _three_field(0.0)], doc_class="correspondence")
    assert out["intent_split"]["n_intent_missed"] == 1
    assert out["headline_scope"] == "partial"
    assert "intent_split" not in aggregate_quality_honest([_three_field(1.0)])
