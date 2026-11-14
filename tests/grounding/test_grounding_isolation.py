"""The grounding pass is structurally off the scoring path (spec §6.1, anti-goals)."""

from __future__ import annotations

import subprocess
import sys

from grounding_inputs import DOC_TEXT, hub_row, with_presence

from llm_dojo_scoring import get_suite
from llm_dojo_scoring.grounding.audit import audit_unlabelled_values

_SCORING_PATH = (
    "llm_dojo_scoring",
    "llm_dojo_scoring.scoring.suites",
    "llm_dojo_scoring.scoring.field_scoring",
    "llm_dojo_scoring.metrics.emitter",
    "llm_dojo_scoring.metrics.registry",
)


def test_scoring_path_never_imports_grounding():
    """Importing the scorers, the emitter and the registry loads no grounding module."""
    code = (
        "import importlib, sys\n"
        f"for name in {_SCORING_PATH!r}: importlib.import_module(name)\n"
        "import llm_dojo_scoring.scoring.suites as s; s.get_suite('insurance_claim')\n"
        "print('\\n'.join(m for m in sys.modules if m.startswith('llm_dojo_scoring.grounding')))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""


def test_auditing_leaves_extraction_scores_unchanged():
    """Scoring the same document before and after a grounding audit gives identical payloads."""
    labels = {"claim_type": "carrier", "claim_number": "AB-12/34", "insurer": "Acme Holdings"}
    gt = with_presence(hub_row(**labels), "adjuster", "pending_annotation")
    predicted = {**labels, "adjuster": "Robin Example", "claimed_amount": "$1,250.00"}
    suite = get_suite("insurance_claim")
    before = suite.score_document(gt, predicted, doc_subclass=None)
    audits = audit_unlabelled_values(gt, predicted, doc_class="insurance_claim", doc_text=DOC_TEXT,
                                     doc_subclass=None)
    after = suite.score_document(gt, predicted, doc_subclass=None)
    assert {a.field for a in audits} == {"adjuster"}
    assert before == after
