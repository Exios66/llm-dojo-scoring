from llm_dojo_scoring import INTENT_LABELS, get_suite, normalize_intent
from llm_dojo_scoring.field_scoring import score_extraction


def test_vocabularies_match_mailroom_bee7f46():
    assert INTENT_LABELS["correspondence"] == (
        "payment_demand", "notice", "analysis", "request", "update",
        "meeting_invite", "press_communication", "other",
    )
    assert INTENT_LABELS["corporate_record"][-1] == "other"
    assert len(INTENT_LABELS["corporate_record"]) == 6
    assert INTENT_LABELS["insurance_claim"] == (
        "claim_filing", "coverage_determination", "loss_report",
        "claim_data_record", "other",
    )
    assert "merger_agreement" not in INTENT_LABELS
    assert "contract" not in INTENT_LABELS


def test_aliases_resolve_in_class_only():
    assert normalize_intent("correspondence", "demand_payment") == "payment_demand"
    assert normalize_intent("insurance_claim", "notice_of_loss") == "claim_filing"
    assert normalize_intent("corporate_record", "request_information") == ""
    assert normalize_intent("correspondence", "threaten litigation") == ""
    assert normalize_intent("merger_agreement", "notice") == ""


LABEL = {"intent": "label", "sender": "name"}


def _intent_score(doc, exp, pred, types=LABEL):
    out = score_extraction(
        doc, types, {"sender": "A", "intent": pred}, {"sender": "A", "intent": exp}
    )
    return out.field_scores.get("intent")


def test_label_scoring_is_exact_after_canonicalization():
    assert _intent_score("correspondence", "payment_demand", "demand_payment") == 1.0
    assert _intent_score("correspondence", "notice", "other") == 0.0
    assert _intent_score("correspondence", "request", "update") == 0.0


def test_foreign_class_token_scores_zero():  # Review Focus 2
    assert _intent_score("correspondence", "notice", "entity_formation") == 0.0


def test_null_gt_other_prediction_is_spurious_fill():  # Review Focus 3
    suite = get_suite("correspondence_specialist")
    clean = suite.score_document(
        {"sender": "A", "intent": None}, {"sender": "A", "intent": None},
        field_types=LABEL,
    )
    spurious = suite.score_document(
        {"sender": "A", "intent": None}, {"sender": "A", "intent": "other"},
        field_types=LABEL,
    )
    assert spurious["extraction_precision"] < clean["extraction_precision"]


def test_explicit_name_type_keeps_fuzzy_rescoring():  # Review Focus 4
    types = {"intent": "name", "sender": "name"}
    assert 0.0 < _intent_score("correspondence", "notice", "other", types) < 1.0
