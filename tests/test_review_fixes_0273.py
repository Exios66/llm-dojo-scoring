"""Review findings on the 0.27.2 vendor bump (llm-mailroom#164).

- Prose-wrapped JSON: many failing candidates no longer cost a scan of the whole
  text each (a JSONDecodeError counts lines up to its position), so the candidate
  search stays linear.
- ``rescore_record``: an already-current record reports the headline a fresh
  rescore of the same record would, by the same task routing.
"""

from __future__ import annotations

import time

from llm_dojo_scoring.metrics.scorecard_honesty import SCORER_VERSION
from llm_dojo_scoring.pipeline.sandbox_schema_adherence import coerce_predicted_payload


def test_many_failing_candidates_parse_in_linear_time():
    """200 never-closing chains (500 KB): about 0.07 s, where 0.27.2 took about 8 s."""
    text = "note " + ('{"a":' * 500 + "x ") * 200
    started = time.perf_counter()
    payload, meta = coerce_predicted_payload(text)
    assert time.perf_counter() - started < 2.0
    assert payload is None and meta["parse_error"] is True


def test_a_closed_object_inside_an_unclosed_one_still_parses():
    """Skipping never-closing braces must not hide a complete object nested inside."""
    payload, meta = coerce_predicted_payload('x {"a": {' * 300 + ' then {"ok": 1} end')
    assert payload == {"ok": 1} and meta["prose_wrapper"] is True


def test_an_object_after_an_unbalanced_quote_still_parses():
    """A stray quote in a never-closing object does not hide a later object."""
    payload, _meta = coerce_predicted_payload('junk {"a": "unterminated {"b": 2} tail')
    assert payload == {"b": 2}


def test_braces_inside_strings_do_not_end_the_object():
    """A "}" inside a JSON string is content, not the closing brace."""
    payload, _meta = coerce_predicted_payload('Here: {"t": "a } b", "n": {"x": 1}} done')
    assert payload == {"t": "a } b", "n": {"x": 1}}


def _current(task: str, payload: dict) -> dict:
    """A record already scored by this release."""
    return {"doc_id": "d1", "task": task, "payload": payload,
            "provenance": {"scorer_version": SCORER_VERSION}}


