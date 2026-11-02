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
        "/enron/maildir/inbox/x",
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


def test_honest_aggregate_intent_split_uses_only_rows_in_the_headline():
    """Rows with a missing, boolean or string score never enter the intent split."""
    rows = [
        {"overall_score": 0.9, "field_scores": {"intent": 1, "keywords": 0.8}},
        {"overall_score": None, "field_scores": {"intent": 0}},
        {"overall_score": True, "field_scores": {"intent": 0}},
        {"overall_score": "0.4", "field_scores": {"intent": 0}},
    ]
    out = aggregate_quality_honest(rows, doc_class="correspondence")
    assert out["n_scored"] == 1
    assert out["intent_split"]["n_intent"] == 1
    assert out["intent_split"]["intent_mean"] == 1.0
    # Standalone, only unscorable rows are skipped.
    assert intent_split(rows)["n_intent"] == 4


@pytest.mark.parametrize(
    "value",
    [
        "Correspondence concerning general_business: Construction Duration, Florida Peaker Project",
        "Correspondence concerning scheduling: End User Measurement",
        "Correspondence concerning general_business.",
        "Email regarding General Business. Follow-up attached",
    ],
)
def test_template_frame_with_title_suffix_is_flagged(value):
    """A frame plus topic key is templated even with a ``: title`` or trailing text."""
    assert is_templated_subject_matter(value)


@pytest.mark.parametrize(
    "value",
    [
        "Correspondence concerning the pipeline outage.",
        "Rescheduling the Q3 review.",
        "Revised RTO conference call schedule discussing PJM",
    ],
)
def test_prose_subject_matter_stays_unflagged(value):
    """Real summaries and non-topic frames are not templated."""
    assert not is_templated_subject_matter(value)


@pytest.mark.parametrize(
    "value",
    [
        "delainey-d",
        "sanders-r",
        "skilling-j",
        "email",
        "memo",
        "letter",
        "demand",
        "maildir/allen-p/inbox/12.",
        "allen-p/_sent_mail/3.",
        "C:\\mail\\inbox\\4.",
    ],
)
def test_metadata_keywords_mailbox_type_and_folder_paths(value):
    """Mailbox ids, communication-type tokens and any-segment folder paths are metadata."""
    assert is_metadata_keyword(value)


@pytest.mark.parametrize(
    "value",
    ["SPP/Entergy", "EFP/EFS PROCEDURES", "/s", "RTO Filing", "PJM", "July 25th", "2001 budget",
     "Notice # 02-46", "2.0.1", "10.12.15", "12345678", "20011314"],
)
def test_content_keywords_are_not_metadata(value):
    """Slashes, version numbers and arbitrary digit runs are not metadata."""
    assert not is_metadata_keyword(value)


@pytest.mark.parametrize(
    "value",
    [
        "2000-06-26T09:40:00+00:00",
        "2001-11-20T06:59:28+00:00",
        "2001-05-14",
        "05/14/2001 09:32",
        "9:32 am",
        "20010514",
        "20010514093200",
    ],
)
def test_date_and_time_stamps_are_metadata(value):
    """ISO timestamps with an offset, US dates, clock times and compact stamps are flagged."""
    assert is_metadata_keyword(value)


def test_real_hub_keyword_lists_are_all_metadata():
    """The two real Hub keyword shapes fire ``keywords_all_metadata``; clean ones do not."""
    for keywords in (
        ["general_business", "email", "delainey-d", "_sent_mail", "2000-06-26T09:40:00+00:00"],
        ["scheduling", "letter", "baughman-d", "inbox", "2001-11-20T06:59:28+00:00"],
    ):
        defects = audit_correspondence_gt_row(
            {"intent": "information_request", "keywords": keywords}
        )
        assert "keywords_all_metadata" in defects
    clean = ["RTO Filing", "PJM", "July 25th", "Notice # 02-46", "EFP/EFS PROCEDURES", "SPP/Entergy"]
    assert not audit_correspondence_gt_row({"intent": "information_request", "keywords": clean})
