"""``filter_untrusted_labels``: flagged GT labels are dropped with ``pending_annotation`` semantics (#171, #164, #94)."""

from __future__ import annotations

import copy
import json

import pytest

import llm_dojo_scoring as dojo
from llm_dojo_scoring.schemas.gt_label_quality import (
    ADJUDICATED_LABEL_SOURCES,
    count_untrusted_labels,
    filter_untrusted_labels,
)
from llm_dojo_scoring.schemas.gt_metadata import gt_presence_map, scoring_gt_fields

TEMPLATED_KEYWORDS = [
    "general_business", "email", "delainey-d", "_sent_mail", "2001-05-14T09:32:00+00:00",
]


def _correspondence(**overrides):
    """A templated, heuristic-intent correspondence row in the Hub shape."""
    row = {
        "intent": "notice",
        "intent_source": "heuristic",
        "intent_status": "auto_labeled",
        "subject_matter": "Correspondence concerning general_business.",
        "keywords": json.dumps(TEMPLATED_KEYWORDS),
        "gt_presence": json.dumps(
            {"intent": "populated", "subject_matter": "populated", "keywords": "populated"}
        ),
    }
    row.update(overrides)
    return row


def _corporate(**overrides):
    """A templated, heuristic-intent corporate-record row in the Hub shape."""
    row = {
        "intent": "governance",
        "intent_source": "heuristic",
        "subject_matter": "bylaws of Acme Corp (CIK 0000000001) (SEC EDGAR exhibit: EXHIBIT 3.2).",
        "keywords": json.dumps(["bylaws", "EX-3.2", "S-1/A"]),
        "expected_subclass": "bylaws",
        "gt_presence": json.dumps(
            {"intent": "populated", "subject_matter": "populated", "keywords": "populated"}
        ),
    }
    row.update(overrides)
    return row


def test_correspondence_flagged_labels_are_dropped_and_reported():
    """Heuristic intent, templated subject_matter and metadata keywords leave the scored GT."""
    out, report = filter_untrusted_labels("correspondence", _correspondence())
    assert report == {
        "intent": "intent_heuristic",
        "subject_matter": "subject_matter_templated",
        "keywords": "keywords_all_metadata",
    }
    assert not {"intent", "subject_matter", "keywords"} & set(out)
    assert gt_presence_map(out) == {f: "pending_annotation" for f in report}
    assert out["intent_source"] == "heuristic"  # annotation keys stay for downstream scoping
    assert scoring_gt_fields(out, doc_type="correspondence") == {}


def test_corporate_record_flagged_labels_are_dropped_and_reported():
    """The corporate equivalents: heuristic intent, EDGAR-template subject, provenance-id keywords."""
    out, report = filter_untrusted_labels("corporate_record", _corporate())
    assert report == {
        "intent": "intent_heuristic",
        "subject_matter": "subject_matter_template",
        "keywords": "keywords_provenance_ids",
    }
    assert not {"intent", "subject_matter", "keywords"} & set(out)
    assert out["expected_subclass"] == "bylaws"


def test_clean_labels_are_kept():
    """Real prose, content keywords and a non-heuristic intent are never filtered."""
    row = _correspondence(
        intent_source="llm_zero_shot",
        subject_matter="Request to move the Thursday gas desk meeting to 3pm.",
        keywords=json.dumps(["gas desk", "meeting", "reschedule"]),
    )
    out, report = filter_untrusted_labels("correspondence", row)
    assert report == {}
    assert out["intent"] == "notice" and out["keywords"] == ["gas desk", "meeting", "reschedule"]
    assert gt_presence_map(out)["intent"] == "populated"


def test_keywords_rule_is_the_narrow_one():
    """One strong metadata keyword among content keywords does not drop the whole list."""
    row = _correspondence(
        intent_source="manual",
        subject_matter="Quarterly gas trading review.",
        keywords=json.dumps(["general_business", "gas trading", "quarterly review"]),
    )
    _, report = filter_untrusted_labels("correspondence", row)
    assert report == {}


@pytest.mark.parametrize("doc_type, row_fn", [("correspondence", _correspondence), ("corporate_record", _corporate)])
@pytest.mark.parametrize("source", ["claude_refined", "manual", "Claude_Refined:v2", "human_review"])
def test_refined_labels_win(doc_type, row_fn, source):
    """A label whose own source is adjudicated is never filtered, even if its text looks templated."""
    assert {"claude_refined", "manual"} <= ADJUDICATED_LABEL_SOURCES
    row = row_fn(
        intent_source=source,
        provenance={"subject_matter": source, "keywords": source},
    )
    out, report = filter_untrusted_labels(doc_type, row)
    assert report == {}
    assert {"intent", "subject_matter", "keywords"} <= set(out)


def test_refined_provenance_is_per_field():
    """Only the field with adjudicated provenance is protected; the others are still filtered."""
    row = _correspondence(provenance={"keywords": "claude_refined"})
    out, report = filter_untrusted_labels("correspondence", row)
    assert set(report) == {"intent", "subject_matter"}
    assert "keywords" in out and gt_presence_map(out)["keywords"] == "populated"


def test_fields_already_unlabelled_are_not_reported():
    """An absent, pending or empty field has nothing to drop."""
    row = _correspondence(
        gt_presence=json.dumps({"intent": "pending_annotation", "subject_matter": "not_applicable",
                                "keywords": "populated"}),
        subject_matter="",
    )
    _, report = filter_untrusted_labels("correspondence", row)
    assert report == {"keywords": "keywords_all_metadata"}


def test_row_without_a_presence_map_does_not_gain_one():
    """A plain field dict keeps its shape: values are removed, no ``gt_presence`` is invented."""
    row = _correspondence()
    del row["gt_presence"]
    out, report = filter_untrusted_labels("correspondence", row)
    assert len(report) == 3 and "gt_presence" not in out


def test_input_is_not_mutated_and_strings_parse():
    """Mappings are copied; JSON string rows are accepted."""
    row = _correspondence()
    before = copy.deepcopy(row)
    filter_untrusted_labels("correspondence", row)
    assert row == before
    out, report = filter_untrusted_labels("correspondence", json.dumps(row))
    assert len(report) == 3 and "intent" not in out


@pytest.mark.parametrize("doc_type", ["contract", "insurance_claim", "merger_agreement", "unknown", ""])
def test_other_classes_are_unchanged(doc_type):
    """Only correspondence and corporate-record rows are filtered."""
    row = _correspondence()
    out, report = filter_untrusted_labels(doc_type, row)
    assert report == {} and out["intent"] == "notice" and out["subject_matter"].startswith("Correspondence")


def test_none_and_empty_rows_and_bad_input():
    """``None`` and ``{}`` are empty rows; malformed GT raises like ``parse_gt_fields``."""
    assert filter_untrusted_labels("correspondence", None) == ({}, {})
    assert filter_untrusted_labels("correspondence", {}) == ({}, {})
    with pytest.raises(TypeError):
        filter_untrusted_labels("correspondence", ["not", "a", "row"])  # type: ignore[arg-type]


def test_filtered_labels_are_counted():
    """``count_untrusted_labels`` totals the reports by ``field:reason``."""
    reports = [
        filter_untrusted_labels("correspondence", _correspondence())[1],
        filter_untrusted_labels("correspondence", _correspondence(intent_source="manual"))[1],
        filter_untrusted_labels("correspondence", _correspondence(subject_matter="A real summary."))[1],
        filter_untrusted_labels("corporate_record", _corporate())[1],
    ]
    assert count_untrusted_labels(reports) == {
        "intent:intent_heuristic": 3,
        "keywords:keywords_all_metadata": 3,
        "keywords:keywords_provenance_ids": 1,
        "subject_matter:subject_matter_template": 1,
        "subject_matter:subject_matter_templated": 2,
    }
    assert count_untrusted_labels([]) == {}


PRED = {
    "intent": "request",
    "subject_matter": "Asks to move the gas desk meeting to Thursday.",
    "keywords": ["gas desk", "meeting"],
}


def test_a_correct_extraction_is_not_a_miss_once_the_flagged_labels_are_filtered():
    """Against a refined subject_matter, templated intent and keywords stop costing the row."""
    suite = dojo.get_suite("correspondence_specialist")
    row = _correspondence(
        subject_matter="Asks to move the gas desk meeting to Thursday.",
        provenance={"subject_matter": "claude_refined"},
    )
    raw = suite.score_document(row, dict(PRED))
    assert raw["extraction"].field_scores == {"intent": 0.0, "subject_matter": 1.0, "keywords": 0.0}
    assert raw["extraction_precision"] == 0.3333
    filtered, report = filter_untrusted_labels("correspondence", row)
    assert set(report) == {"intent", "keywords"}
    out = suite.score_document(filtered, dict(PRED))
    assert out["extraction"].field_scores == {"subject_matter": 1.0}
    assert (out["extraction_precision"], out["extraction_recall"]) == (1.0, 1.0)
    # The filtered fields are unlabelled, not blanked: a stated value is not a false positive.
    assert out["schema"]["unlabelled_fields"] == ["intent", "keywords"]


def test_a_row_with_every_label_filtered_is_unscorable_not_zero():
    """No trusted label left: the row is unscorable instead of scoring 0 on templated gold."""
    suite = dojo.get_suite("correspondence_specialist")
    filtered, _ = filter_untrusted_labels("correspondence", _correspondence())
    out = suite.score_document(filtered, dict(PRED))
    assert out["status"] == "unscorable" and out["reason"] == "gt_no_extractable_fields"


def test_the_filter_is_opt_in_default_scoring_is_untouched():
    """Without the filter the templated row scores as before (zeros on all three fields)."""
    suite = dojo.get_suite("correspondence_specialist")
    raw = suite.score_document(_correspondence(), dict(PRED))
    assert raw["extraction"].field_scores == {"intent": 0.0, "subject_matter": 0.0, "keywords": 0.0}


def test_corporate_record_filtered_labels_are_unlabelled_in_the_suite():
    """The corporate suite leaves the filtered fields unscored and does not penalise stated values."""
    suite = dojo.get_suite("corporate_records_specialist")
    row = _corporate(
        entity_name="Acme Corp",
        gt_presence=json.dumps({"entity_name": "populated", "intent": "populated",
                                "subject_matter": "populated", "keywords": "populated"}),
    )
    pred = {"entity_name": "Acme Corp", "intent": "governance", "subject_matter": "Bylaws of Acme Corp",
            "keywords": ["bylaws", "board of directors"]}
    raw = suite.score_document(dict(row), dict(pred))
    filtered, report = filter_untrusted_labels("corporate_record", row)
    assert len(report) == 3
    out = suite.score_document(filtered, dict(pred))
    assert out["extraction"].field_scores == {"entity_name": 1.0}
    assert (out["extraction_precision"], out["extraction_recall"]) == (1.0, 1.0)
    assert raw["extraction"].field_scores["subject_matter"] < 1.0 and raw["extraction"].field_scores["keywords"] < 1.0
    assert (raw["extraction_precision"], raw["extraction_recall"]) == (0.6667, 0.5)
