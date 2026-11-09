"""Field-scoring tests: scalar scorers, entity lists, factuality audit, and
composite score_extraction (ported behavior)."""

from datetime import date

import pytest

from llm_dojo_scoring import field_scoring as fs
from llm_dojo_scoring.schemas.gt_metadata import ANNOTATION_KEYS


@pytest.mark.parametrize("key", sorted(ANNOTATION_KEYS))
def test_annotations_never_score_or_enter_factuality_audit_even_with_explicit_map(key):
    """Exclude annotation keys from extraction scores and factuality audits despite explicit maps."""
    result = fs.score_extraction(
        doc_class="insurance_claim",
        expected={"claim_number": "CLM-1", key: "expected annotation"},
        predicted={"claim_number": "CLM-1", key: "different annotation"},
        field_types={"claim_number": "id", key: "free_text"},
        doc_text="Claim CLM-1 was received.",
    )
    assert result.field_scores == {"claim_number": 1.0}
    assert result.overall_score == 1.0
    assert key not in result.entity_list_audit
    assert "claim_number" in result.entity_list_audit


@pytest.mark.parametrize("empty", ["[]", "{}", " N/A ", "null"])
def test_empty_serialized_prediction_does_not_enter_factuality_audit(empty):
    """Skip empty serialized predictions when auditing otherwise perfect extractions."""
    result = fs.score_extraction(
        doc_class="insurance_claim",
        expected={"claim_number": "CLM-1"},
        predicted={"claim_number": "CLM-1", "denial_reasons": empty},
        field_types={"claim_number": "id", "denial_reasons": "entity_list:free_text"},
        doc_text="Claim CLM-1 was received.",
    )
    assert result.overall_score == 1.0
    assert set(result.entity_list_audit) == {"claim_number"}


def test_stringified_entity_lists_match_native_lists_without_mutating_records():
    """Match serialized and native entity lists without modifying either input record."""
    expected = {"reference_ids": '["A-1", "B-2"]'}
    predicted = {"reference_ids": '["B-2", "A-1"]'}
    result = fs.score_extraction(
        "contract", {"reference_ids": "entity_list:id"}, predicted, expected,
    )
    assert result.field_scores == {"reference_ids": 1.0}
    assert result.entity_list_scores["reference_ids"].precision == 1.0
    assert result.entity_list_scores["reference_ids"].recall == 1.0
    assert expected == {"reference_ids": '["A-1", "B-2"]'}
    assert predicted == {"reference_ids": '["B-2", "A-1"]'}


# ---------------------------------------------------------------------------
# Scalar scorers
# ---------------------------------------------------------------------------

def test_id_field():
    """Compare normalized identifiers while rejecting different identifier values."""
    assert fs.score_id_field("ABC-123", "ABC-123") == 1.0
    assert fs.score_id_field("ABC-123", "ABC-124") == 0.0
    assert fs.score_id_field("", "") == 1.0


def test_money_field():
    """Compare normalized monetary values while rejecting materially different amounts."""
    assert fs.score_money_field("$250,001", "$250001") == 1.0
    assert fs.score_money_field("$250,001", "$250,000") == 0.0
    assert fs.score_money_field("2M", "$2,000,000") == 1.0
    assert fs.score_money_field("approx. two million", "$2,000,000") >= 0.0


def test_name_field():
    """Tolerate name punctuation and containment while penalizing unrelated entities."""
    assert fs.score_name_field("Goosehead Insurance Agency, LLC", "Goosehead Insurance Agency LLC") == 1.0
    assert fs.score_name_field("FRANCHISE AGREEMENT", "Goosehead Insurance Agency, LLC Franchise Agreement") == 1.0
    assert fs.score_name_field("BETA", "SOVEREIGN STATE BANK OF OHIO") < 0.8


def test_free_text_field():
    """Award exact free-text matches and reject empty predictions for populated GT."""
    assert fs.score_free_text_field("termination upon 90 days notice", "termination upon 90 days notice") == 1.0
    assert fs.score_free_text_field("", "something") == 0.0


def test_containment_field():
    """Give partial credit for contained spans and zero for missing predictions."""
    assert fs.score_containment_field("the laws of the State of Delaware", "the laws of the State of Delaware") == 1.0
    assert fs.score_containment_field("", "the laws of the State of Delaware") == 0.0
    partial = fs.score_containment_field("the State of Delaware", "the laws of the State of Delaware")
    assert 0.0 < partial < 1.0


def test_date_field():
    """Normalize date formats, grade near misses, and recognize blank template dates."""
    assert fs.score_date_field("March 3, 2024", "03/03/2024") == 1.0
    assert fs.score_date_field("2024-03-03", "March 3, 2024") == 1.0
    assert fs.score_date_field("March 3, 2024", "March 1, 2024") == 0.67  # within 45 days
    assert fs.score_date_field("March 3, 2024", "2023-01-01") == 0.0
    # blank template expectation: null prediction is CORRECT
    assert fs.score_date_field("", "_____ day of ________, 19____") == 1.0
    assert fs.score_date_field("March 3, 2024", "_____ day of ________, 19____") == 0.0
    # containment: multi-date prediction containing the label's date
    assert fs.score_date_field("Executed March 1, 1996 and November 5, 1996", "November 5, 1996") == 1.0


@pytest.fixture
def freeze_clock(monkeypatch):
    """Return ``freeze(year)``: make dateutil's parse default (``datetime.now()``) report ``year``."""
    import datetime as real_datetime
    import types

    from dateutil.parser import _parser

    def freeze(year: int) -> None:
        """Pin the clock that dateutil reads when it fills missing date components."""

        class _Frozen(real_datetime.datetime):
            """A datetime whose ``now()`` is pinned to the chosen year."""

            @classmethod
            def now(cls, tz=None):
                """Return a fixed mid-year instant in ``year``."""
                return cls(year, 7, 15, 12, 0, 0)

        fake = types.SimpleNamespace(**vars(real_datetime))
        fake.datetime = _Frozen
        monkeypatch.setattr(_parser, "datetime", fake)

    return freeze


def _scores_in_years(freeze, pred, exp, years=(2014, 2031)):
    """Score one pair under several frozen clocks and return the score for each."""
    seen = []
    for year in years:
        freeze(year)
        seen.append(fs.score_date_field(pred, exp))
    return seen


@pytest.mark.parametrize(
    ("pred", "exp", "expected"),
    [
        # yearless GT, dated prediction with the same month/day: the year cannot be
        # verified, so never a full match (the year is critical)
        ("August 18, 2014", "18th day of August", 0.67),
        ("2014-08-18", "August 18", 0.67),
        ("August 18", "18th day of August", 1.0),
        # yearless GT, day differs: month only
        ("August 20, 2014", "18th day of August", 0.33),
        # month differs (day matches only): nothing shared
        ("September 18, 2014", "18th day of August", 0.0),
        # dated GT, yearless prediction: partial credit, never 1.0
        ("August 18", "August 18, 2014", 0.67),
        ("18th day of August", "August 18, 2014", 0.67),
        ("18 August", "18 August 2014", 0.67),  # a prediction inside the label is not a full match
        ("August 20", "August 18, 2014", 0.33),
        ("September 18", "August 18, 2014", 0.0),
        # dayless GT: the prediction may state any day
        ("August 18, 2014", "August 2014", 1.0),
        ("August 2014", "August 2014", 1.0),
        ("August 2015", "August 2014", 0.33),
        # dayless prediction against a fully dated GT
        ("August 2014", "August 18, 2014", 0.67),
        # both yearless
        ("August 18", "18th day of August", 1.0),
        ("August 19", "18th day of August", 0.33),
        # Feb 29 only exists in leap years; the clock year must not matter
        ("February 29", "29th day of February", 1.0),
        ("February 29, 2024", "29th day of February", 0.67),
        ("February 29", "February 29, 2024", 0.67),
        # yearless GT is not "contained" in a different day that merely shares a prefix
        ("August 18, 2014", "August 1", 0.33),
    ],
)
def test_date_field_partial_dates_are_clock_independent(freeze_clock, pred, exp, expected):
    """Score yearless and dayless dates on the components both sides state, in any year."""
    assert _scores_in_years(freeze_clock, pred, exp) == [expected, expected]


def test_partial_date_phrase_matches_on_word_boundaries():
    """A yearless phrase is found only as whole words, not inside a different day."""
    assert fs._date_phrase_contained("signed on august 18 2014", "on august 18")
    assert not fs._date_phrase_contained("signed on august 18 2014", "on august 1")


def test_date_field_yearless_gt_does_not_depend_on_wall_clock_year(freeze_clock):
    """Issue #134: a yearless GT scored 1.0 in the prediction's year and 0.33 in every other.

    It now scores the same in every run year: 0.67, because a yearless label cannot
    verify the year the prediction states.
    """
    scores = _scores_in_years(freeze_clock, "August 18, 2014", "18th day of August", years=(2014, 2026, 2031))
    assert scores == [0.67, 0.67, 0.67]


def test_date_field_fully_dated_pairs_are_unchanged(freeze_clock):
    """Keep the 45-day window and the year/month tiers for fully dated pairs."""
    freeze_clock(2031)
    assert fs.score_date_field("March 3, 2024", "03/03/2024") == 1.0
    assert fs.score_date_field("March 3, 2024", "March 1, 2024") == 0.67
    assert fs.score_date_field("March 3, 2024", "March 30, 2024") == 0.67
    assert fs.score_date_field("March 3, 2024", "April 10, 2024") == 0.67  # 38 days
    assert fs.score_date_field("March 3, 2024", "June 3, 2024") == 0.33  # same year only
    assert fs.score_date_field("March 3, 2024", "June 3, 2023") == 0.0
    assert fs.score_date_field("March 3, 2024", "March 3, 2023") == 0.33
    assert fs.score_date_field("March 3, 2024", "2023-01-01") == 0.0


def test_date_field_window_applies_only_to_fully_dated_pairs(freeze_clock):
    """A yearless side is compared by components, never by distance in days."""
    freeze_clock(2014)
    # 7 days apart in 2014, but the GT states no year: day differs, month matches.
    assert fs.score_date_field("August 25, 2014", "August 18") == 0.33
    # Crossing a month boundary is not rescued by closeness either.
    assert fs.score_date_field("September 2, 2014", "August 30") == 0.0


def test_parse_date_is_deterministic_for_partial_dates(freeze_clock):
    """parse_date returns a date only when year, month and day are all stated; never reads the clock."""
    import datetime

    for year in (2014, 2031):
        freeze_clock(year)
        assert fs.parse_date("18th day of August") is None
        assert fs.parse_date("August 18") is None
        assert fs.parse_date("August 2014") is None
        assert fs.parse_date("2014") is None
        assert fs.parse_date("February 29") is None
        assert fs.parse_date("August 18, 2014") == datetime.date(2014, 8, 18)
        assert fs.parse_date("18th day of August, 2014") == datetime.date(2014, 8, 18)
        assert fs.parse_date("2024-02-29") == datetime.date(2024, 2, 29)
        assert fs.parse_date("Effective Date") is None
        assert fs.parse_date("") is None


def test_parse_date_returns_none_for_yearless_and_dayless_text():
    """No date component is invented: partial text is not a date."""
    assert fs.parse_date("18th day of August") is None
    assert fs.parse_date("August 2014") is None


def test_year_is_never_invented_or_overlooked(freeze_clock):
    """A year the GT states is checked; a mismatching year never counts as a match."""
    freeze_clock(2014)
    assert fs.score_date_field("August 18", "August 18, 2014") < 1.0
    assert fs.score_date_field("August 2014", "August 18, 2014") < 1.0
    assert fs.score_date_field("August 18, 2015", "August 18, 2014") == 0.33  # not a match
    assert fs.score_date_field("August 18, 2015", "August 2014") == 0.33
    # a yearless GT cannot verify a stated year, so a dated pred is never a full match
    assert fs.score_date_field("August 18, 1999", "18th day of August") == 0.67


def test_date_parsing_never_reads_the_clock():
    """Every dateutil call passes an explicit default; no scoring code asks for today's date."""
    import ast
    import pathlib

    import llm_dojo_scoring

    root = pathlib.Path(llm_dojo_scoring.__file__).parent
    importers = set()
    for path in root.rglob("*.py"):
        text = path.read_text()
        if "dateutil" in text:
            importers.add(path.relative_to(root).as_posix())
    assert importers == {"scoring/field_scoring.py"}

    tree = ast.parse((root / "scoring" / "field_scoring.py").read_text())
    parse_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        assert node.func.attr not in {"now", "today", "utcnow"}
        if node.func.attr == "parse":
            parse_calls += 1
            assert "default" in {kw.arg for kw in node.keywords}
    assert parse_calls == 2


def test_date_parts_report_only_stated_components(freeze_clock):
    """The component parser names exactly what the text states, whatever the clock says."""
    for year in (2014, 2031):
        freeze_clock(year)
        assert fs._parse_date_parts("18th day of August") == (None, 8, 18)
        assert fs._parse_date_parts("August 2014") == (2014, 8, None)
        assert fs._parse_date_parts("February 29") == (None, 2, 29)
        assert fs._parse_date_parts("2000-01-01") == (2000, 1, 1)
        assert fs._parse_date_parts("August 18, 2014") == (2014, 8, 18)
        assert fs._parse_date_parts("18") is None  # a bare day number is not a date
        assert fs._parse_date_parts("_____ day of ________, 19____") is None



def test_stated_year_survives_spacing_and_punctuation_noise(freeze_clock):
    """A year the text states is never reported as missing (CUAD spans in mailroom-dataset v9.3)."""
    for year in (2014, 2031):
        freeze_clock(year)
        assert fs._parse_date_parts("March 12,1999") == (1999, 3, 12)
        assert fs._parse_date_parts("16 day of August. 2012") == (2012, 8, 16)
        assert fs.parse_date("March 12,1999") == date(1999, 3, 12)
        assert fs.score_date_field("March 12, 1999", "March 12,1999") == 1.0
        assert fs.score_date_field("March 12, 2003", "March 12,1999") == 0.33

def test_date_field_blank_template_gt_is_still_null_in_any_year(freeze_clock):
    """A partial-date parse must not turn a blank-template GT into a real date."""
    for year in (2014, 2031):
        freeze_clock(year)
        assert fs.score_date_field("", "_____ day of ________, 19____") == 1.0
        assert fs.score_date_field("March 3, 2024", "_____ day of ________, 19____") == 0.0


# ---------------------------------------------------------------------------
# Entity lists
# ---------------------------------------------------------------------------

def test_entity_list_exact():
    """Award perfect F1 and overall list score for matching entities."""
    score = fs.score_entity_list("name", ["Alpha Corp"], ["Alpha Corp"])
    assert score.f1 == 1.0
    assert score.score == 1.0


def test_entity_list_reorder_and_extra():
    """Ignore entity ordering while reducing precision for extra predictions."""
    score = fs.score_entity_list(
        "name",
        ["Beta LLC", "Alpha LLC", "Extra Corp"],
        ["Alpha LLC", "Beta LLC"],
    )
    assert score.matched == 2
    assert score.precision == pytest.approx(2 / 3)
    assert score.recall == 1.0


def test_entity_list_empty_sides():
    """Treat two empty lists as perfect and missing expected entities as zero recall."""
    assert fs.score_entity_list("name", [], []).f1 == 1.0
    assert fs.score_entity_list("name", [], ["a"]).recall == 0.0


def test_entity_list_partial_gt_role_words():
    # partial-GT: role-word label matched by mere presence of a named party
    """Allow role-word expansions when scoring partially labeled entity lists."""
    score = fs.score_entity_list("name", ["Shipper Co."], ["Shipper"], partial_gt=True)
    assert score.score == 1.0  # recall


def test_entity_list_partial_gt_precision_capped_at_1():
    # hub#38: role-word credits are bounded — an all-role-word expected list
    # vs a single named party must never inflate precision beyond 1.0.
    """Keep partial-GT list precision and recall bounded by one."""
    score = fs.score_entity_list(
        "name", ["ACME Corp"], ["Seller", "Buyer"], partial_gt=True
    )
    assert score.precision <= 1.0
    assert score.recall <= 1.0


def test_entity_list_partial_gt_contained_items_credit_capped():
    # hub#38: contained-label credits are bounded — a 1-item prediction whose
    # tokens contain an expected 3-6-token label gets the credit, but the
    # composite may not exceed min(n_pred, n_exp).
    """Cap credit when multiple contained items match partial ground truth."""
    score = fs.score_entity_list(
        "clause",
        ["indemnification obligations of the seller"],
        ["indemnification obligations", "obligations of the seller"],
        partial_gt=True,
    )
    assert score.precision <= 1.0
    assert score.recall <= 1.0


def test_entity_list_partial_gt_mixed_case_bounded():
    # hub#38: mixed role-word + real-entity expected list vs a single
    # predicted entity — matched starts at the Hungarian hit, gets role
    # credits, then clamps to min(n_pred, n_exp) = 1.
    """Limit mixed-case partial matches to available predicted entities."""
    score = fs.score_entity_list(
        "name", ["ACME Corp"], ["Seller", "ACME Corp", "Buyer"], partial_gt=True
    )
    assert score.matched <= 1
    assert score.precision == 1.0
    assert score.recall == pytest.approx(1 / 3)


def test_entity_list_partial_gt_property_precision_recall_bounded():
    # hub#38: for random (pred, exp) pairs with partial_gt, precision and
    # recall stay within [0, 1].
    """Keep partial-GT precision and recall within unit bounds across generated lists."""
    import random

    pool = [
        "Seller", "Buyer", "Shipper", "Receiver", "Party A",
        "ACME Corp", "Acme Corp", "Shipper Co.", "Big Corp", "Consignee",
        "indemnification obligations", "confidentiality", "termination",
    ]
    rng = random.Random(1337)
    for _ in range(100):
        n_pred, n_exp = rng.randint(1, 4), rng.randint(1, 4)
        pred = [rng.choice(pool) for _ in range(n_pred)]
        exp = [rng.choice(pool) for _ in range(n_exp)]
        score = fs.score_entity_list("name", pred, exp, partial_gt=True)
        assert 0.0 <= score.precision <= 1.0
        assert 0.0 <= score.recall <= 1.0


def test_entity_list_to_dict():
    """Serialize entity-list counts and matched totals."""
    d = fs.score_entity_list("name", ["A"], ["A"]).to_dict()
    assert d["n_predicted"] == 1
    assert d["matched"] == 1


# ---------------------------------------------------------------------------
# Factuality audit
# ---------------------------------------------------------------------------

def test_audit_list_field_grounded_and_hallucinated():
    """Distinguish document-grounded list items from hallucinated predictions."""
    doc = "Alpha Corp and Beta LLC agree that the effective date is March 1 2024."
    audit = fs.audit_list_field("free_text", ["Alpha Corp and Beta LLC agree"],
                                ["Alpha Corp and Beta LLC agree"], doc)
    assert audit["verified_precision"] == 1.0
    assert audit["hallucination_rate"] == 0.0

    audit2 = fs.audit_list_field("free_text", ["Completely fabricated clause about unicorns"],
                                 [], doc)
    assert audit2["hallucination_rate"] == 1.0


def test_audit_scalar_field_date():
    """Verify a scalar date against supporting document text."""
    doc = "Executed on 04-01-06."
    audit = fs.audit_scalar_field("date", "2006-04-01", "4/1/2006", doc)
    assert audit["true_items"] == 1


def test_verify_list_items():
    """Return per-item grounding flags for present and absent document entities."""
    doc = "the parties shall terminate upon ninety days notice"
    flags = fs.verify_list_items(["ninety days notice"], doc)
    assert flags == [True]
    flags2 = fs.verify_list_items(["zebra hallucination"], doc)
    assert flags2 == [False]


def test_score_category_presence():
    """Match expected clause presence without requiring nonexistent categories."""
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": "shall not assign", "field": "cuad_clauses"},
        "Non-Existent": {"expected": False, "answer": "", "field": "cuad_clauses"},
    }
    field_types = {"cuad_clauses": "entity_list:free_text"}
    score, detail = fs.score_category_presence(
        {"cuad_clauses": ["Anti-Assignment: party shall not assign any rights"]},
        expectations, field_types,
    )
    assert score == 1.0
    assert detail["Non-Existent"]["expected"] is False


def test_score_category_presence_defaults_field_to_cuad_clauses():
    """Use CUAD clauses as the default field for category-presence scoring."""
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": "shall not assign"},
    }
    score, detail = fs.score_category_presence(
        {"cuad_clauses": ["shall not assign any rights"]},
        expectations,
        {"cuad_clauses": "entity_list:free_text"},
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["field"] == "cuad_clauses"


def test_disaggregate_clause_spans():
    """Split concatenated categorized clause spans without losing their content."""
    merged = [
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER PARTY, "
        "ASSIGN THIS AGREEMENT; the Company shall not solicit or hire any employee; "
        "Distributor shall not sell products outside the Territory."
    ]
    spans = fs.disaggregate_clause_spans(merged)
    assert len(spans) == 3
    assert "ASSIGN THIS AGREEMENT" in spans[0]
    assert "solicit or hire any employee" in spans[1]
    assert "outside the Territory" in spans[2]


def test_disaggregate_clause_spans_single_passes_through():
    """Preserve standalone spans and return empty lists for absent input."""
    assert fs.disaggregate_clause_spans(["a single standalone clause"]) == [
        "a single standalone clause"
    ]
    assert fs.disaggregate_clause_spans([]) == []
    assert fs.disaggregate_clause_spans(None) == []


def test_score_category_presence_disaggregated():
    """Issue #21 fix #1/#3: 4 clauses merged into ONE item no longer dilutes
    the match — after disaggregation the labeled clause is contained at 1.0."""
    anti_assignment = (
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER "
        "PARTY, ASSIGN THIS AGREEMENT"
    )
    merged = ";\n".join([
        anti_assignment,
        "the Company shall not solicit or hire any employee of the Distributor",
        "during the Term, Distributor shall not sell products outside the Territory",
        "this Agreement may be terminated by either party upon ninety (90) days written notice",
    ])
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": anti_assignment, "field": "cuad_clauses"},
    }
    field_types = {"cuad_clauses": "entity_list:free_text"}
    score, detail = fs.score_category_presence(
        {"cuad_clauses": [merged]}, expectations, field_types,
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["matched"] is True


def test_score_category_presence_routed_entries():
    """Issue #21 fix #2/#3: a reasoning-trace entry tagged with the canonical
    category name routes its evidence straight to the category evaluator even
    when the checklist item does not cover the label."""
    anti_assignment = (
        "NEITHER PARTY SHALL, WITHOUT THE PRIOR WRITTEN CONSENT OF THE OTHER "
        "PARTY, ASSIGN THIS AGREEMENT"
    )
    predicted = {
        "cuad_clauses": ["an unrelated exclusivity provision"],
        "reasoning": {
            "entries": [
                {"field": "Anti-Assignment", "evidence": anti_assignment,
                 "section_ref": "7.1"},
            ]
        },
    }
    expectations = {
        "Anti-Assignment": {"expected": True, "answer": anti_assignment, "field": "cuad_clauses"},
    }
    score, detail = fs.score_category_presence(
        predicted, expectations, {"cuad_clauses": "entity_list:free_text"},
    )
    assert score == 1.0
    assert detail["Anti-Assignment"]["matched"] is True



# ---------------------------------------------------------------------------
# Composite score_extraction
# ---------------------------------------------------------------------------

FIELD_TYPES = {
    "document_name": "name",
    "parties": "entity_list:name",
    "effective_date": "date",
    "contract_value": "money",
    "governing_law": "containment",
    "key_obligations": "entity_list:free_text",
}


def test_score_extraction_null_date_rule():
    """Treat an empty prediction as correct for an unfilled template date."""
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "A", "effective_date": None},
        {"document_name": "A", "effective_date": "_____ day of ________, 19____"},
    )
    assert result.field_scores["effective_date"] == 1.0
    assert result.overall_score == 1.0


def test_score_extraction_overall_and_ambiguity():
    """Average field scores and flag borderline date matches for judge review."""
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "Franchise Agreement", "effective_date": "2024-03-01"},
        {"document_name": "Franchise Agreement", "effective_date": "2024-02-15"},
    )
    # name exact (1.0), date within 45 days (0.67) -> ambiguous band
    assert result.field_scores["document_name"] == 1.0
    assert result.field_scores["effective_date"] == 0.67
    assert result.overall_score == pytest.approx(0.835)
    assert result.ambiguous_fields == ["effective_date"]
    assert result.needs_judge_review is True


def test_score_extraction_missing_field_zero():
    """Assign zero credit to an omitted expected extraction field."""
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"document_name": "A"},
        {"document_name": "A", "contract_value": "$100,000"},
    )
    assert result.field_scores["contract_value"] == 0.0


def test_score_extraction_entity_list_scores_and_audit():
    """Expose entity-list match details and document-grounding audits in extraction results."""
    result = fs.score_extraction(
        "contract", FIELD_TYPES,
        {"parties": ["Acme LLC"], "key_obligations": ["deliver quarterly reports"]},
        {"parties": ["Acme LLC"]},
        doc_text="Acme LLC shall deliver quarterly reports.",
    )
    assert "parties" in result.entity_list_scores
    assert result.entity_list_scores["parties"].score == 1.0
    assert "key_obligations" in result.entity_list_audit
    assert result.entity_list_audit["key_obligations"]["true_items"] == 1


def test_score_extraction_skips_confidence_reasoning_and_empty_lists():
    """``confidence`` / ``reasoning`` and matching empty lists never score as fields."""
    result = fs.score_extraction(
        "contract",
        FIELD_TYPES,
        {
            "document_name": "MSA",
            "parties": [],
            "confidence": 0.99,
            "reasoning": {"summary": "trace"},
        },
        {
            "document_name": "MSA",
            "parties": [],
            "confidence": 0.5,
            "reasoning": {"summary": "other"},
        },
    )
    assert "confidence" not in result.field_scores
    assert "reasoning" not in result.field_scores
    assert "parties" not in result.field_scores
    assert result.overall_score == 1.0
    assert result.trace["confidence"] == 0.99
    assert result.trace["reasoning"]["summary"] == "trace"


def test_score_extraction_to_dict_serializable():
    """Serialize overall extraction and nested entity-list scores as plain data."""
    result = fs.score_extraction("contract", FIELD_TYPES,
                                 {"parties": ["Acme"]}, {"parties": ["Acme"]})
    d = result.to_dict()
    assert d["overall_score"] == 1.0
    assert d["entity_list_scores"]["parties"]["f1"] == 1.0


def test_get_field_types_from_taxonomy():
    """Read field types from supplied taxonomy and return an empty map without it."""
    taxonomy = {"doc_classes": [{"key": "contract", "field_types": {"a": "date"}}]}
    assert fs.get_field_types("contract", taxonomy) == {"a": "date"}
    assert fs.get_field_types("contract") == {}


def test_heuristic_field_type():
    """Infer date, money, identifier, and entity-list types from field names and values."""
    assert fs._heuristic_field_type("effective_date", "x") == "date"
    assert fs._heuristic_field_type("contract_value", "x") == "money"
    assert fs._heuristic_field_type("docket_number", "x") == "id"
    assert fs._heuristic_field_type("note", ["x"]) == "entity_list"


def test_cms_table_token_on_claim_type_no_longer_matches_health_gt():
    """#93 retired the SAND-042 fold: a table token is not a product line."""
    from llm_dojo_scoring.scoring.field_scoring import score_extraction

    exp = {"claim_type": "health", "cms_source_table": "pde"}
    for token in ("pde", "inpatient", "outpatient", "carrier"):
        out = score_extraction("insurance_claim", {}, {"claim_type": token}, exp)
        assert out.field_scores["claim_type"] == 0.0, token
    right = score_extraction("insurance_claim", {}, {"claim_type": "health"}, exp)
    assert right.field_scores["claim_type"] == 1.0


def test_full_date_is_not_contained_in_a_different_day():
    """"1 August 2014" is a substring of "11 August 2014" but a different day."""
    assert fs.score_date_field("11 August 2014", "1 August 2014") < 1.0
    assert fs.score_date_field("1 August 2014", "11 August 2014") < 1.0
    assert fs.score_date_field("signed on 1 August 2014 by", "1 August 2014") == 1.0


@pytest.mark.parametrize(
    "text, year",
    [("1/1/77", 1977), ("1/1/50", 2050), ("1/1/68", 2068), ("1/1/69", 1969), ("1/1/00", 2000),
     ("March 3, 99", 1999), ("1/1/1877", 1877)],
)
@pytest.mark.parametrize("today", [2014, 2026, 2031, 2080])
def test_two_digit_year_uses_a_fixed_pivot_not_the_clock(monkeypatch, text, year, today):
    """A two-digit year maps to the same century whatever year the run happens in.

    dateutil's default ``parserinfo`` reads ``time.localtime()`` for its century
    pivot, so the test pins that clock and rebuilds the cached parserinfo.
    """
    import time

    pinned = time.struct_time((today, 6, 1, 12, 0, 0, 0, 152, 0))
    monkeypatch.setattr(time, "localtime", lambda *a: pinned)
    monkeypatch.setattr(fs, "_DATE_PARSERINFO", None, raising=False)
    assert fs._parse_date_parts(text).year == year


def test_full_date_pairs_are_parsed_once_per_side(monkeypatch):
    """Scoring a fully dated pair parses each side once, not again for the full-date branch."""
    calls = []
    real = fs._parse_date_parts
    monkeypatch.setattr(fs, "_parse_date_parts", lambda t: calls.append(t) or real(t))
    fs.score_date_field("March 1, 2014", "March 20, 2014")
    assert calls.count("March 1, 2014") <= 2 and calls.count("March 20, 2014") <= 2


@pytest.mark.parametrize(
    "pred, gt",
    [("12", "December 12, 2014"), ("12th", "12th day of December, 2014"),
     ("Tuesday", "Tuesday, December 12, 2014"), ("12", "2014-12-12"), ("12", "12/12/2014")],
)
def test_a_date_fragment_is_not_the_labelled_date(pred, gt):
    """A prediction stating no date component gets no fuzzy name credit against a dated label."""
    assert fs.score_date_field(pred, gt) == 0.0


def test_weekday_name_does_not_invent_a_day():
    """'Monday August 2014' states year and month; the weekday is not a day of the month."""
    assert tuple(fs._parse_date_parts("Monday August 2014")) == (2014, 8, None)
    assert tuple(fs._parse_date_parts("Tuesday, December 12, 2014")) == (2014, 12, 12)


@pytest.mark.parametrize("pred", ["Augus 18, 2014", "Aug. l8, 2014", "Augst 18 2014"])
def test_garbled_date_naming_the_year_keeps_fuzzy_credit(pred):
    """OCR-garbled dates that name the labelled year keep fuzzy credit instead of 0.0."""
    assert fs.score_date_field(pred, "August 18, 2014") > 0.67


def test_garbled_date_with_the_wrong_year_is_capped():
    """A garbled date naming a different year never scores above 0.33."""
    assert fs.score_date_field("Augus 18, 2015", "August 18, 2014") <= 0.33


@pytest.mark.parametrize(
    "text, parts",
    [("August 1-3, 2014", (2014, 8, 1)), ("1-3 August 2014", (2014, 8, 1)),
     ("2014-08-18", (2014, 8, 18)), ("18-08-2014", (2014, 8, 18))],
)
def test_day_range_reads_its_first_day_not_a_year(text, parts):
    """A day range never turns its second number into the year."""
    assert tuple(fs._parse_date_parts(text)) == parts


@pytest.mark.parametrize("label", ["Effective upon signing", "Wednesday", "12:30 pm"])
def test_exact_copy_of_a_non_date_label_matches(label):
    """An exact copy of a label that holds no date is the labelled value."""
    assert fs.score_date_field(label, label) == 1.0


@pytest.mark.parametrize("label", ["_____ day of ________, 19____", "Effective Date:", "Effective Date"])
def test_copied_blank_template_or_bare_label_is_not_a_match(label):
    """A copied blank template or bare label is not a date; only an empty answer is right."""
    assert fs.score_date_field(label, label) == 0.0
    assert fs.score_date_field("", label) == 1.0


def test_integral_float_year_matches_its_text():
    """A NaN-promoted year column (2014.0) scores like the text 2014."""
    assert fs.score_date_field(2014.0, "2014") == fs.score_date_field("2014", "2014")


@pytest.mark.parametrize(
    "pred",
    ["dated August 18, 2015", "This Agreement is made as of August 18, 2015",
     "August 18, 2015 and August 18, 2016", "Augus 18, 2014"],
)
def test_yearless_label_caps_a_year_stated_anywhere_in_the_prediction(pred):
    """The yearless-label cap applies to years in prose and garbled dates too."""
    assert fs.score_date_field(pred, "August 18") <= 0.67


@pytest.mark.parametrize(
    "pred",
    ["August 1, 2014 and August 18, 2015", "August 18, 2014 and August 18, 2015"],
)
def test_prediction_naming_several_years_is_never_a_full_match(pred):
    """A prediction naming two different years is ambiguous."""
    assert fs.score_date_field(pred, "August 18, 2014") <= 0.67


@pytest.mark.parametrize(
    "text, parts",
    [("8-18, 2014", (2014, 8, 18)), ("12-14 2014", (2014, 12, 14)), ("Aug. 1-3, 2014", (2014, 8, 1))],
)
def test_numeric_month_day_is_not_read_as_a_day_range(text, parts):
    """Only a range next to a month word is a day range; "8-18, 2014" keeps its day."""
    got = fs._parse_date_parts(text)
    assert (None if got is None else tuple(got)) == parts


@pytest.mark.parametrize(
    "label",
    ["August 18, 2014 to August 18, 2016", "January 1, 2014 through December 31, 2016"],
)
def test_exact_copy_of_a_multi_year_label_is_a_full_match(label):
    """The several-years cap does not apply when the label states those years itself."""
    assert fs.score_date_field(label, label) == 1.0


def test_partial_date_prediction_is_grounded_by_an_agreeing_document_date():
    """A yearless prediction is grounded by a document date agreeing on what it states."""
    doc = "This Agreement is made on August 18, 2014 by the parties."
    assert fs._date_grounded_in_doc(fs._parse_date_parts("August 18"), doc)
    assert not fs._date_grounded_in_doc(fs._parse_date_parts("August 19"), doc)
    assert fs._date_grounded_in_doc(fs._parse_date_parts("August 18, 2014"), doc)
    assert not fs._date_grounded_in_doc(fs._parse_date_parts("August 18, 2015"), doc)


def test_audit_grounds_a_yearless_prediction_in_the_document():
    """audit_scalar_field verifies a partial date against an agreeing document date."""
    doc = "This Agreement is made on August 18, 2014 by the parties."
    assert fs.audit_scalar_field("date", "August 18", "", doc)["verified_in_doc"] == 1
    assert fs.audit_scalar_field("date", "August 19", "", doc)["verified_in_doc"] == 0


@pytest.mark.parametrize("text", ["Mon Aug 2014", "Tue Aug 2014", "Sat., Aug 2014", "Wed Aug 2014"])
def test_abbreviated_weekday_does_not_invent_a_day(text):
    """An abbreviated weekday is not a day of the month either."""
    assert tuple(fs._parse_date_parts(text)) == (2014, 8, None)


def test_garbled_prediction_never_exceeds_the_partial_ceiling_against_a_partial_label():
    """Fuzzy credit for an unparseable prediction stays within 0.67 against a partial label."""
    assert fs.score_date_field("Q3 2014", "August 2014") <= 0.67


def test_dated_prediction_is_never_a_list_match_for_a_yearless_label():
    """In lists the 0.67 field cap would clear the 0.6 match threshold; pairing refuses it."""
    res = fs.score_entity_list("date", ["August 18, 2015"], ["18th day of August"])
    assert res.matched == 0 and res.f1 == 0.0
    res = fs.score_entity_list("date", ["August 18"], ["18th day of August"])
    assert res.matched == 1 and res.f1 == 1.0
    res = fs.score_entity_list(
        "date", ["August 18, 2014", "March 1, 2015"], ["August 18, 2014", "1st day of March"]
    )
    assert res.matched == 1


def test_audits_do_not_count_an_unverified_year_as_matching_the_label():
    """audit_scalar_field and audit_list_field use the strict date match too."""
    assert fs.audit_scalar_field("date", "August 18, 2015", "18th day of August", None)["matched_gt"] == 0
    assert fs.audit_scalar_field("date", "August 18", "18th day of August", None)["matched_gt"] == 1
    assert fs.score_date_field("August 18, 2015", "18th day of August") == 0.67  # field score unchanged


def test_audit_list_field_does_not_match_an_unverified_year():
    """audit_list_field pairs dates with the same strict match."""
    out = fs.audit_list_field("date", ["August 18, 2015"], ["18th day of August"], None)
    assert out["matched_gt"] == 0
