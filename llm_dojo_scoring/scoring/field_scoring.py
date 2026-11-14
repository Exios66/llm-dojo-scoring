"""Deterministic, field-type-aware extraction scoring.

Ported from ``src/field_scoring.py`` (llm-entity-extraction, itself ported
from llm-mailroom) into the shared suite so both projects import ONE scoring
implementation. The exact-match-on-extraction approach treats all fields
identically, which is wrong: a date, a dollar amount, a party name, and a
free-text clause summary fail differently and need different normalization
before comparison. This module implements one scoring algorithm per field
type:

- ``id``          normalize (uppercase, strip punctuation/whitespace), then
                  exact match.
- ``date``        parse both sides to a canonical ISO date, then exact match
                  with containment + partial-credit fallbacks.
- ``money``       strip currency symbols/commas, parse to float, compare with
                  a one-cent tolerance; unparseable prose falls back to fuzzy
                  string matching.
- ``name``        normalized fuzzy matching: Jaro-Winkler (jellyfish) +
                  token-set ratio (stdlib difflib), with containment first.
- ``free_text``   SQuAD-style token F1 over token multisets.
- ``entity_list`` optimal bipartite matching (scipy Hungarian algorithm) over
                  a pairwise similarity matrix, thresholded, then
                  precision/recall/F1 over the matched set.

``name`` and ``free_text`` optionally use embedding cosine similarity as a
SECOND signal that rescues semantically-correct-but-lexically-distant fields
when the string score is ambiguous. The embedding layer is lazy and degrades
gracefully (pure string scoring) if unavailable.

All thresholds and field sets come from :mod:`llm_dojo_scoring.config`
(``Settings.field_scoring``) — override via YAML or ``configure(...)``.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, NamedTuple, Optional

import structlog

from ..config import get_settings
from ..schemas.corpus import CMS_DOCUMENTED_ABSENT_FIELDS, CMS_SOURCE_TABLES
from ..schemas.gt_metadata import ANNOTATION_KEYS, is_empty_value, parse_json_container
from ..schemas.intents import INTENT_LABELS, normalize_intent  # noqa: F401  (historic module attributes)
from ..schemas.scored_enums import canonical_label

logger = structlog.get_logger(__name__)

#: Trace / format artifacts and Hub annotation stats — never enter
#: :func:`score_extraction` (mailroom-issues #237 / #238).
NEVER_SCORED_FIELDS: frozenset[str] = frozenset(
    {"confidence", "reasoning"}
) | ANNOTATION_KEYS

#: Prompt-catalog keys retired from live models. Ignored unless the caller
#: passed them in an explicit ``field_types`` map (historical rescoring).
RETIRED_PROMPT_KEYS: frozenset[str] = frozenset(
    {
        "key_obligations",
        "termination_clauses",
        "key_provisions",
        "key_points",
        "referenced_communications",
    }
)

# ---------------------------------------------------------------------------
# Configuration accessors (kept for drop-in compatibility with the
# llm-entity-extraction API — all read the shared settings object)
# ---------------------------------------------------------------------------


#: CMS DE-SynPUF table tokens. They are a *source table*, not a product line:
#: the published merge labels every CMS row ``claim_type=health`` and the table
#: lives in its own field, ``cms_source_table`` (dojo #93). Before #93 a table
#: token predicted on ``claim_type`` was folded onto ``health`` (the SAND-042
#: equivalence); that fold is retired for scoring.
CMS_CLAIM_TYPES: frozenset[str] = frozenset({"pde", "inpatient", "outpatient", "carrier"})

#: Field types the scorer applies on a CMS row, explicitly (never an implicit
#: heuristic): the derived table is a controlled ``label``; supporting
#: documents are identifier strings (``provider NPI 5040521237``,
#: ``NDC 00703051002``, ``HCPCS detail (1 codes)``) compared by
#: :func:`score_cms_doc_ref`. Not part of ``DEFAULT_FIELD_TYPES``, which
#: mirrors the mailroom taxonomy and is pinned to it.
CMS_ROW_FIELD_TYPES: dict[str, str] = {
    # Closed product-line vocabulary on a CMS row (GT is always ``health``):
    # exact match, so a table token earns no fuzzy name credit.
    "claim_type": "label",
    "cms_source_table": "label",
    "supporting_documents": "entity_list:cms_doc_ref",
}


def canonical_claim_type(predicted: Any, expected: Any) -> Any:
    """Legacy SAND-042 fold: a CMS table token onto ``health`` when GT is ``health``.

    **No longer used by the scorer (dojo #93).** ``claim_type`` (product line)
    and ``cms_source_table`` are separate fields, so a table token predicted
    on ``claim_type`` scores as wrong there; ``score_extraction`` does not call
    this. The name stays importable for consumers that analysed stored runs
    under the old equivalence. Behaviour is unchanged: only the CMS -> health
    direction folds.
    """
    pred = str(predicted).strip().lower()
    if pred in CMS_CLAIM_TYPES and str(expected).strip().lower() == "health":
        return "health"
    return predicted


def expected_cms_source_table(doc_class: str | None, expected: Any) -> str | None:
    """The CMS source table an expected row carries, else ``None``.

    This is what makes a row a CMS row for scoring: the table is derived from
    ``expected_subclass`` (``scoring_gt_fields`` / ``cms_source_table``) and
    injected into the expected fields, so every scoring path that assembles GT
    that way shares one definition. Non-CMS rows never carry it.
    """
    if doc_class != "insurance_claim" or not isinstance(expected, dict):
        return None
    token = str(parse_json_container(expected.get("cms_source_table")) or "").strip().lower()
    if token not in CMS_SOURCE_TABLES:
        return None
    # Every published CMS row is ``claim_type=health``. A row whose GT names
    # another product line is not CMS, whatever stray key it carries.
    claim_type = parse_json_container(expected.get("claim_type"))
    if not is_empty_value(claim_type) and str(claim_type).strip().lower() != "health":
        return None
    return token


def is_unstated_cms_marker(key: str, cms_table: str | None, predicted: Any) -> bool:
    """True for a CMS row's ``cms_source_table`` that the prediction does not state (#132).

    The marker is derived from the row's subclass, not labelled in the ground truth. A
    prediction states a table either in ``cms_source_table`` or, as the frozen insurance
    prompt does, as a table token on ``claim_type``; both are scored. A prediction that
    states no table at all (``claim_type`` holds the product line) is neither a miss nor a
    hit: the marker is not scored for it.
    """
    if key != "cms_source_table" or cms_table is None or not isinstance(predicted, dict):
        return False
    if not is_empty_value(parse_json_container(predicted.get(key))):
        return False
    return str(predicted.get("claim_type") or "").strip().lower() not in CMS_CLAIM_TYPES


def get_ambiguous_band() -> tuple[float, float]:
    """Return the configured global half-open judge-review score band."""
    return get_settings().field_scoring.ambiguous_band


def get_bipartite_match_threshold() -> float:
    """Return the minimum similarity used for bipartite entity matching."""
    return get_settings().field_scoring.bipartite_match_threshold


def get_embedding_model() -> str:
    """Return the configured local sentence-transformer model name."""
    return get_settings().field_scoring.embedding_model


def get_embedding_rescue_below() -> float:
    """Return the string-score threshold below which embedding rescue is attempted."""
    return get_settings().field_scoring.embedding_rescue_below


def get_presence_embedding_threshold() -> float:
    """Minimum embedding cosine for a disaggregated clause span to satisfy a
    CUAD YES/NO category-presence expectation (issue #21)."""
    return get_settings().field_scoring.presence_embedding_threshold


def embedding_enabled() -> bool:
    """Return whether embedding-based scoring is enabled in settings."""
    return get_settings().field_scoring.embedding_enabled


def get_type_bands() -> dict[str, tuple]:
    """Per-field-type ambiguous-band overrides from the configured taxonomy.

    Values are canonical tuples:
      ``("always",)`` — every field of that type escalates to the LLM judge
      ``("never",)``  — no field of that type ever escalates (the
                        deterministic score is decisive both ways)
      ``(low, high)`` — half-open band check (``low <= score < high``)

    Populated by ``configure_from_taxonomy()``; empty (fall back to the
    global ``ambiguous_band``) when no taxonomy was wired.
    """
    return dict(get_settings().field_scoring.type_bands)


def field_is_ambiguous(field_type: str, score: float) -> bool:
    """Is this field score in the (possibly type-specific) ambiguous band?

    Checks the configured ``type_bands`` first (matching on the exact field
    type or its ``namespace:name`` prefix), then falls back to the global
    ``ambiguous_band``. Band check is half-open (``low <= score < high``): a
    perfect score of 1.0 is never ambiguous, and a score exactly at the low
    cutoff still escalates (fail-safe toward the judge).
    """
    bands = get_type_bands()
    band = bands.get(field_type) or bands.get(field_type.split(":", 1)[0])
    if band == ("always",):
        return True
    if band == ("never",):
        return False
    if band is not None:
        low, high = band
        return low <= score < high
    low, high = get_ambiguous_band()
    return low <= score < high


def warm_embedding_model(blocking: bool = False) -> None:
    """Load the embedding model OFF the document path (O-10).

    The first grounded run that needs a name/free-text embedding used to
    trigger a synchronous multi-minute SentenceTransformer download inside run
    finalization. This kicks the load into a background thread at process
    start instead. Failures are logged; scoring keeps the string-only score.

    No-op when embedding scoring is disabled (``embedding_enabled()`` false).
    """
    import logging
    import threading

    if not embedding_enabled():
        return

    log = logging.getLogger(__name__)

    def _run() -> None:
        """Warm the embedding matcher, logging failures without interrupting scoring."""
        try:
            _get_embedding()
        except Exception as exc:  # scoring degrades to string-only
            log.warning("embedding model warmup failed: %s", exc)

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name="embedding-warmup").start()


def get_partial_gt_fields() -> set[str]:
    """Field names whose CUAD-style ground truth is a PARTIAL sample of the
    document's content (QA-answer snippets), not an exhaustive list. For these
    fields the model's extraction is usually MORE complete than the label set,
    so they are scored by GROUND-TRUTH COVERAGE (recall) instead of F1."""
    return set(get_settings().field_scoring.partial_gt_fields)


def get_containment_fields() -> set[str]:
    """Field names scored by EXPECTED-WITHIN-PREDICTED token containment."""
    return set(get_settings().field_scoring.containment_fields)


def verification_enabled() -> bool:
    """Whether predicted items are verified against the source document text
    (the factuality guard)."""
    return get_settings().field_scoring.verification_enabled


def get_verification_coverage() -> float:
    """Minimum normalized-token coverage of a predicted item within the
    source document text for it to count as grounded (not hallucinated)."""
    return get_settings().field_scoring.verification_token_coverage


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Corporate / honorific suffixes removed from name tokens before matching
# ("Global Technologies, Ltd" vs "Global Technologies Ltd" — same entity).
_CORPORATE_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "LTD", "LIMITED", "CORP", "CORPORATION",
    "CO", "COMPANY", "PLC", "LLP", "LP", "PLLC", "PC", "PA", "ESQ",
    "ESQUIRE", "GMBH", "AG", "NV", "SA", "SARL", "BV", "PTY", "GROUP",
    "HOLDINGS", "TRUST",
}
_PUNCT_RE = re.compile(r"[,.;:'\"()\[\]{}!?@#$%^&*+=|\\/<>~`_-]")
_ORDINAL_RE = re.compile(r"(\d)(st|nd|rd|th|d)\b", re.IGNORECASE)  # "3d": the legal 3rd
_WS_RE = re.compile(r"\s+")


def normalize_text(text) -> str:
    """Uppercase, strip punctuation, drop corporate suffixes, collapse
    whitespace. The canonical form used by exact and fuzzy matching."""
    if not isinstance(text, str):
        text = str(text)
    tokens = _PUNCT_RE.sub(" ", text.upper()).split()
    tokens = [t for t in tokens if t not in _CORPORATE_SUFFIXES]
    return " ".join(tokens)


def _tokenize(text: str) -> list[str]:
    """Lowercase, punctuation-stripped tokens (for F1-style matching)."""
    if not isinstance(text, str):
        text = str(text)
    return _PUNCT_RE.sub(" ", text.lower()).split()


# Function words excluded from CONTAINMENT token sets only. Clause labels
# ("the laws of the State of Delaware") carry them; counting them inflates
# misses on short paraphrases and under-flags ambiguity.
_CONTAINMENT_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "by", "as",
    "is", "be", "are", "with", "its", "their", "his", "her", "such", "hereof",
    "hereunder", "shall", "any", "all", "this", "that", "these", "those",
    "from", "between", "into", "upon", "under", "over",
}


def _containment_tokens(text: str) -> set[str]:
    """Normalized token set for containment scoring (stopwords removed)."""
    return {t for t in _tokenize(text) if t not in _CONTAINMENT_STOPWORDS}


def _seq_ratio(a: str, b: str) -> float:
    """Return sequence similarity, scoring two empty strings as an exact match."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _token_set_ratio(a: str, b: str) -> float:
    """Token-set ratio (rapidfuzz-style) over space-joined sorted tokens."""
    ta, tb = set(_tokenize(a)), set(_tokenize(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if inter == ta and inter == tb:
        return 1.0
    base = _seq_ratio(" ".join(sorted(inter)), " ".join(sorted(ta)))
    diff = _seq_ratio(" ".join(sorted(ta - tb)), " ".join(sorted(tb - ta)))
    return max(base, diff)


def _token_f1(pred: str, exp: str) -> float:
    """SQuAD-style token-level F1 over lowercase token multisets."""
    pt, gt = _tokenize(pred), _tokenize(exp)
    if not gt:
        return 1.0 if not pt else 0.0
    if not pt:
        return 0.0
    common = Counter(gt) & Counter(pt)
    tp = sum(common.values())
    if tp == 0:
        return 0.0
    prec, rec = tp / len(pt), tp / len(gt)
    return 2 * prec * rec / (prec + rec)


# ---------------------------------------------------------------------------
# Scalar field scorers
# ---------------------------------------------------------------------------

_MONTH_NAMES = ["january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december"]


class _DateParts(NamedTuple):
    """The components of a date that its text actually states (``None`` = not stated)."""

    year: Optional[int]
    month: Optional[int]
    day: Optional[int]

    @property
    def is_full(self) -> bool:
        """True when year, month and day are all stated."""
        return None not in self

    @property
    def stated(self) -> frozenset:
        """Indexes (0 year, 1 month, 2 day) of the components the text states."""
        return frozenset(i for i, v in enumerate(self) if v is not None)


# Two fixed, distinct fill-in datetimes. dateutil fills every component the text
# does not state from ``default`` (its own default is the CURRENT date, which makes
# scores depend on the wall clock). The two differ in year, month AND day, so a
# component that comes out the same in both parses was stated by the text. Both
# years are leap years, so "February 29" parses.
_DATE_PROBE_A = (2000, 1, 1)
_DATE_PROBE_B = (2004, 3, 3)
# Two-digit years use a FIXED pivot, never the clock: dateutil's default
# parserinfo picks the century from today's year, so "1/1/77" would read as
# 1977 now and as 2077 from 2027. Like Python's ``%y``: 00-68 -> 2000-2068,
# 69-99 -> 1969-1999.
_TWO_DIGIT_YEAR_PIVOT = 69
_DATE_PARSERINFO = None


def _date_parserinfo():
    """Return the shared dateutil ``parserinfo`` with the fixed two-digit-year pivot."""
    global _DATE_PARSERINFO
    if _DATE_PARSERINFO is None:
        from dateutil import parser

        class _FixedPivotParserInfo(parser.parserinfo):
            """``parserinfo`` whose two-digit-year century never depends on the clock."""

            def convertyear(self, year, century_specified=False):
                """Map a two-digit year with the fixed pivot; leave stated centuries alone."""
                if year < 100 and not century_specified:
                    return year + (1900 if year >= _TWO_DIGIT_YEAR_PIVOT else 2000)
                return year

        _DATE_PARSERINFO = _FixedPivotParserInfo()
    return _DATE_PARSERINFO


# Written-out numbers in dates ("this third day of March, two thousand twenty-four").
_ORD_BASE = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
_CARDINAL_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_ORD_UNIT_WORDS = "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth"
#: "first" .. "thirty-first" (hyphen or one space); never "thirty-second": no such day.
_ORD_WORD = (
    r"(?:(?:" + "|".join(_ORD_BASE) + r")"
    r"|twenty[-\s](?:" + _ORD_UNIT_WORDS + r")|thirty[-\s]first)\b"
)
_CARDINAL_SUB100 = (
    r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|one|two|three|four|five|six|seven|eight|nine)"
)
#: "two thousand [and] twenty-four", "nineteen ninety-nine", "nineteen hundred".
_YEAR_WORDS = (
    r"(?:two\s{1,9}thousand(?:\s{1,9}(?:and\s{1,9})?" + _CARDINAL_SUB100 + r")?"
    r"|(?:eighteen|nineteen)\s{1,9}(?:hundred(?:\s{1,9}(?:and\s{1,9})?" + _CARDINAL_SUB100 + r")?"
    r"|" + _CARDINAL_SUB100 + r"))\b"
)
_MONTH_ANY_WORD = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)


def _ascii_digits(text: str) -> str:
    """Fold full-width and other Unicode digits to ASCII, so a date written with them reads."""
    if text.isascii():
        return text
    text = unicodedata.normalize("NFKC", text)
    return "".join(
        str(unicodedata.decimal(ch)) if ch > "\x7f" and ch.isdecimal() else ch for ch in text
    )


#: An ordinal word starts a day only when it is not the tail of a compound: "thirty-second",
#: "thirty second" and "fifty-third" are no day of the month, "twenty-first" is read from "twenty".
_TENS_WORDS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
#: A lookbehind is fixed-width, so it sees ONE whitespace character after the tens word. Both readers
#: of text collapse a longer run first: the value side (``_parse_date_parts`` collapses every run)
#: and the document scan (``_TENS_GAP_RE`` in ``_document_dates``).
_NOT_COMPOUND = r"(?<![-\w])" + "".join(rf"(?<!{t}\s)" for t in _TENS_WORDS)
#: "thirty   second", "twenty\n\nfirst": a run of whitespace after a tens word is one space, so the
#: compound guard and ``_ORD_WORD`` read it as they read the single-space form.
#: Unicode ``\s`` on purpose: the scan itself is ASCII-only, so a line or paragraph separator
#: (U+2028, U+2029, U+0085, U+001C-U+001F), which NFKC leaves alone, becomes a plain space here,
#: as it does on the value side (``_WS_RE``).
#: No leading ``\b``: "x_thirty   second" collapses like "x_thirty second", which the guard reads.
_TENS_GAP_RE = re.compile(r"(" + "|".join(_TENS_WORDS) + r")\s+", re.IGNORECASE)
_DAY_NUMBER = r"\d{1,2}(?:st|nd|rd|th)?"


def _ordinal_word_value(word: str) -> int:
    """The day number of "third", "twenty-first", "Thirty first"."""
    tokens = [t for t in re.split(r"[-\s]+", word.lower()) if t]
    if len(tokens) == 2:
        return _CARDINAL_WORDS[tokens[0]] + _ORD_BASE[tokens[1]]
    return _ORD_BASE[tokens[0]]


def _spelled_year_value(words: str) -> int:
    """The year in "two thousand twenty-four" (2024) or "nineteen ninety-nine" (1999)."""
    tokens = [t for t in re.split(r"[-\s]+", words.lower()) if t and t != "and"]
    base = {"two": 2000, "nineteen": 1900, "eighteen": 1800}[tokens[0]]
    rest = tokens[1:]
    if rest and rest[0] in ("thousand", "hundred"):
        rest = rest[1:]
    return base + sum(_CARDINAL_WORDS[t] for t in rest)


def _resolve_double_spelled_day(s: str) -> str:
    """"the 3rd (third) day of March" is the 3rd; "3rd (fourth)" names no day, so it is dropped."""

    def day(token: str) -> int:
        """The day number a digit or word ordinal names."""
        return int(re.match(r"\d+", token).group(0)) if token[0].isdigit() else _ordinal_word_value(token)

    def resolve(match: "re.Match[str]") -> str:
        """Keep the day when both forms agree, drop the whole phrase when they do not."""
        return f"{day(match.group('a'))}{match.group('tail')}" if day(match.group("a")) == day(match.group("b")) else ""

    return re.sub(
        _NOT_COMPOUND + r"(?P<a>" + _DAY_NUMBER + "|" + _ORD_WORD + r")\s{0,3}\(\s{0,3}"
        r"(?P<b>" + _DAY_NUMBER + "|" + _ORD_WORD + r")\s{0,3}\)(?P<tail>\s{1,3}(?:day\s{1,3})?of\s{1,3})"
        r"(?=" + _MONTH_ANY_WORD + r"\b)",
        resolve, s, flags=re.IGNORECASE,
    )


def _digits_for_written_numbers(s: str) -> str:
    """Replace a spelled-out day or year with digits, only where it is plainly a date.

    A day word counts only in "third day of March" / "third of March" (so "the second
    Monday of March" names no day), a year phrase only in the forms of ``_YEAR_WORDS``.
    """
    s = re.sub(
        r"\b" + _YEAR_WORDS, lambda m: str(_spelled_year_value(m.group(0))), s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        _NOT_COMPOUND + r"(" + _ORD_WORD + r")(\s+day)?\s+of\s+(?=" + _MONTH_ANY_WORD + r"\b)",
        lambda m: f"{_ordinal_word_value(m.group(1))}{m.group(2) or ''} of ",
        s, flags=re.IGNORECASE,
    )
    # "May twenty-fourth, 2024": a day word after the month counts when a year follows.
    return re.sub(
        r"(\b" + _MONTH_ANY_WORD + r"\b\.?\s{1,3}(?:the\s{1,3})?)" + _NOT_COMPOUND + r"(" + _ORD_WORD
        + r")(?=\s{0,3}(?:,\s{0,3})?\d{4}\b)",
        lambda m: f"{m.group(1)}{_ordinal_word_value(m.group(2))}",
        s, flags=re.IGNORECASE,
    )


def _parse_date_parts(text) -> Optional[_DateParts]:
    """Return the (year, month, day) components ``text`` states, or None.

    Never reads the clock. None means unparseable, or a parse that states
    neither a year nor a month (a bare day number or time is not a date).
    A missing component is ``None``: "18th day of August" is ``(None, 8, 18)``
    and "August 2014" is ``(2014, 8, None)``.

    Handles the forms that appear in CUAD ground truth: ISO, mm/dd/yyyy,
    "March 3, 2024", ordinal prose ("10th day of January 2000"), and stray
    trailing artifacts like "1st day of April, 2007 (". Also: spelled-out days and
    years ("this third day of March, two thousand twenty-four"), "in the year of our
    Lord 2024", "March the 3rd", "in March of 2024", year-first prose, compact
    ``20240303`` and a day written twice ("the 3rd (third) day of March": the day when
    both agree, no day when they do not). Numeric ``03/04/2024`` is month-first. A day range ("March 3-5,
    2024", "3 to 5 March 2024", "March 30-April 2, 2024") states its FIRST day only
    here: the reader of one value never invents a second date (the document scan
    reads both ends).
    """
    if not isinstance(text, str):
        return None
    s = _WS_RE.sub(" ", _ascii_digits(text).strip())
    if not s:
        return None
    # "in the year 2024", "in the year of our Lord 2024", "A.D. 2024": the year is the number.
    s = re.sub(
        r"\b(?:in\s+)?the\s+year(?:\s+of\s+(?:our|the)\s+Lord)?\s+", "", s, flags=re.IGNORECASE
    )
    s = re.sub(r"\bA\.?D\.?\s+(?=\d)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bthe\s+month\s+of\s+", "", s, flags=re.IGNORECASE)  # "3rd day of the month of March"
    s = _resolve_double_spelled_day(s)
    s = _digits_for_written_numbers(s)
    s = _ORDINAL_RE.sub(r"\1", s)
    # "this third day of March", "in March of 2024", "on 3 March": a leading word is noise.
    s = re.sub(r"^(?:(?:this|the|on|in)\s+)+", "", s, flags=re.IGNORECASE)
    # "March the 3rd, 2024", "the 3rd of March": the article before a day is noise.
    s = re.sub(r"\bthe\s+(?=\d)", "", s, flags=re.IGNORECASE)
    # "March 3rd, 2024)": a stray bracket or comma around the date is not part of it.
    s = re.sub(r"^[)\]}\s,;:]+", "", s)
    s = re.sub(r"[)\]},;:\s]+$", "", s)
    # "March 12,1999": dateutil drops a year glued to the comma and would
    # report it as unstated, so the stated year must get its space back.
    s = re.sub(r",(?=\d)", ", ", s)
    # A day range ("August 1-3, 2014", "1-3 August 2014") names its first day;
    # dateutil would read the second number as a year. ISO and numeric dates
    # (2014-08-18, 18-08-2014) are untouched: the range must sit next to a word
    # or a ", YYYY".
    # "March 3 to 5, 2024" and "March 30-April 2, 2024" name their first day too.
    _range = r"(?:[-\u2013\u2014]|\bto\b|\bthrough\b|\bthru\b)"
    s = re.sub(
        r"\b([A-Za-z]{3,}\.?\s+\d{1,2})\s*" + _range + r"\s*[A-Za-z]{3,}\.?\s+\d{1,2}(?=\s*(?:,\s*)?\d{4}\b|[\s,.;]*$)",
        r"\1", s,
    )
    s = re.sub(r"\b([A-Za-z]{3,}\.?\s+\d{1,2})\s*" + _range + r"\s*\d{1,2}\b(?![-/.]\d)", r"\1", s)
    s = re.sub(r"(?<![\d/.\-])(\d{1,2})\s*" + _range + r"\s*\d{1,2}(?=\s+[A-Za-z]{3,})", r"\1", s)
    # A weekday name is not a day of the month: dateutil would resolve "Monday
    # August 2014" to the first Monday after each probe default and invent a day.
    s = re.sub(
        r"\b(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b\.?,?",
        " ", s, flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(
        r"\b(\d{1,2})[a-z]*(?:\s+[a-z]+)*\s+day\s+of\b", r"\1 day of", s,
        flags=re.IGNORECASE,
    )
    # "16 day of August. 2012": a period before the year is OCR/typing noise.
    day_of_month = re.search(
        r"\b(\d{1,2})\s+day\s+of\s+([A-Za-z]+)[,.\s]*(\d{4})?", s, flags=re.IGNORECASE
    )
    if day_of_month:
        month, day, year = day_of_month.group(2), day_of_month.group(1), day_of_month.group(3)
        s = f"{month} {day}, {year}" if year else f"{month} {day}"
    s = re.sub(r"[(\[\{,]+$", "", s).strip()
    try:
        import datetime

        from dateutil import parser

        info = _date_parserinfo()
        a = parser.parse(s, parserinfo=info, default=datetime.datetime(*_DATE_PROBE_A))
        b = parser.parse(s, parserinfo=info, default=datetime.datetime(*_DATE_PROBE_B))
    except (ValueError, OverflowError):
        return None
    parts = _DateParts(
        a.year if a.year == b.year else None,
        a.month if a.month == b.month else None,
        a.day if a.day == b.day else None,
    )
    if parts.year is None and parts.month is None:
        return None
    return parts


def _parse_date(text) -> Optional[Any]:
    """Parse to a canonical datetime.date, or None.

    Returns a date only when the text states year, month AND day, so the
    result never depends on the current date. Partial dates ("18th day of
    August", "August 2014") return None here; use :func:`_parse_date_parts`
    for the components they do state.
    """
    parts = _parse_date_parts(text)
    if parts is None or not parts.is_full:
        return None
    import datetime

    try:
        return datetime.date(parts.year, parts.month, parts.day)
    except ValueError:
        return None


def parse_date(text) -> Optional[Any]:
    """Public alias of :func:`_parse_date` — canonical datetime.date for a
    CUAD-style date string that states year, month and day, or None when it is
    unparseable or only partly dated (no year or no day). Never reads the clock."""
    return _parse_date(text)


def _parse_money(text) -> Optional[float]:
    """Strip currency symbols/commas, expand K/M/B suffixes, parse to float."""
    if isinstance(text, (int, float)):
        return float(text)
    if not isinstance(text, str):
        return None
    s = text.strip().upper().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    # Currency words come off first, so "1.2M USD" and "USD 1.2M" reach the
    # K/M/B suffix check as "1.2M" (#133).
    for tail in (" USD", " DOLLARS", " DOLLAR", " EUROS", " EUR"):
        if s.endswith(tail):
            s = s[: -len(tail)].rstrip()
            break
    for head in ("USD ", "US ", "EUR "):
        if s.startswith(head):
            s = s[len(head):].lstrip()
            break
    multiplier = 1.0
    for suffix, m in (("M", 1e6), ("K", 1e3), ("B", 1e9)):
        if s.endswith(suffix):
            multiplier = m
            s = s[:-1].rstrip()
            break
    if not s:
        return None
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def parse_money(text) -> Optional[float]:
    """Public alias of :func:`_parse_money` — canonical USD float for any
    money-style string, or None when unparseable."""
    return _parse_money(text)


def score_id_field(pred, exp, embedding=None) -> float:
    """Normalize (upper, strip punctuation/whitespace), then exact match."""
    np_, ne = normalize_text(pred), normalize_text(exp)
    if not np_ and not ne:
        return 1.0
    if not np_ or not ne:
        return 0.0
    return 1.0 if np_ == ne else 0.0


def score_money_field(pred, exp, embedding=None) -> float:
    """Numeric parse + tolerance compare; unparseable prose falls back to
    fuzzy string matching instead of scoring 0."""
    pa, ea = _parse_money(pred), _parse_money(exp)
    if pa is not None and ea is not None:
        # One-cent absolute tolerance. Legal amounts are exact: "$250,001"
        # vs "$250,000" is a different value, not rounding noise.
        return 1.0 if abs(pa - ea) <= 0.01 else 0.0
    return score_name_field(pred, exp, embedding=embedding)


def _jaro_winkler(a: str, b: str) -> float:
    """Return Jaro-Winkler similarity, falling back to sequence matching on failure."""
    if not a or not b:
        return 0.0
    try:
        import jellyfish

        return float(jellyfish.jaro_winkler_similarity(a, b))
    except Exception:
        return _seq_ratio(a, b)


def _with_embedding_rescue(string_score: float, pred, exp, embedding) -> float:
    """Use embedding cosine as a second signal only when the string score is
    ambiguous (below the rescue threshold) — never overriding a confident
    string-level reject. Fetches the matcher lazily when not provided."""
    if string_score >= get_embedding_rescue_below():
        return string_score
    if not str(pred).strip() or not str(exp).strip():
        return string_score
    if embedding is None:
        embedding = _get_embedding()
    if embedding is None:
        return string_score
    try:
        sim = embedding.similarity(pred, exp)
    except Exception:
        logger.warning("embedding_similarity_failed", exc_info=True)
        return string_score
    if sim is None:
        return string_score
    return max(string_score, float(sim))


def score_name_field(pred, exp, embedding=None) -> float:
    """Normalized fuzzy matching: containment first, then max of Jaro-Winkler
    (only when the names share a token) and token-set ratio, with embedding
    rescue for lexically distant but semantically equal names."""
    np_, ne = normalize_text(pred), normalize_text(exp)
    if not np_ and not ne:
        return 1.0
    if not np_ or not ne:
        return 0.0
    if set(_tokenize(ne)) and set(_tokenize(ne)) <= set(_tokenize(np_)):
        return 1.0
    base = _token_set_ratio(np_, ne)
    if set(_tokenize(np_)) & set(_tokenize(ne)):
        base = max(base, _jaro_winkler(np_, ne))
    return _with_embedding_rescue(base, pred, exp, embedding)


def score_label_field(pred, exp, embedding=None) -> float:
    """Exact match on a controlled label: 1.0 when both sides compact
    (lowercase, alphanumerics only) to the same non-empty token, else 0.0.

    No partial credit — a wrong label is a miss, not a near-miss. Callers
    canonicalize aliases first (see ``score_extraction`` / ``intents``).
    """
    cp = re.sub(r"[^a-z0-9]", "", str(pred or "").lower())
    ce = re.sub(r"[^a-z0-9]", "", str(exp or "").lower())
    return 1.0 if cp and cp == ce else 0.0


def score_free_text_field(pred, exp, embedding=None) -> float:
    """SQuAD-style token F1, with embedding rescue for paraphrases."""
    if not isinstance(pred, str):
        pred = str(pred or "")
    if not isinstance(exp, str):
        exp = str(exp or "")
    f1 = _token_f1(pred, exp)
    return _with_embedding_rescue(f1, pred, exp, embedding)


def score_containment_field(pred, exp, embedding=None) -> float:
    """Share of the EXPECTED text's normalized tokens covered by the
    prediction (expected-within-predicted containment)."""
    if not isinstance(pred, str):
        pred = str(pred or "")
    if not isinstance(exp, str):
        exp = str(exp or "")
    te = _containment_tokens(exp)
    tp = _containment_tokens(pred)
    if not te:
        return 1.0 if not tp else 0.0
    if not tp:
        return 0.0
    return round(len(te & tp) / len(te), 4)


# A label that states no year cannot verify the year a prediction states, so the
# prediction never earns full credit for it (the owner's rule: the year is critical).
_UNVERIFIED_YEAR_CAP = 0.67


def score_date_field(pred, exp, embedding=None) -> float:
    """Score a date prediction; see :func:`_score_date_field_uncapped` for the rules.

    A prediction that states a year scores at most 0.67 against a label that
    states none: the year cannot be verified, so it is never a full match.
    """
    pred, exp = _integral_float_as_text(pred), _integral_float_as_text(exp)
    score = _score_date_field_uncapped(pred, exp, embedding=embedding)
    if score > _UNVERIFIED_YEAR_CAP and _date_year_unverified(pred, exp):
        return _UNVERIFIED_YEAR_CAP
    return score


def _date_year_unverified(pred, exp) -> bool:
    """True when the label cannot verify the year(s) the prediction states.

    A yearless label cannot verify any year the prediction states, in a parsed
    date or in prose ("dated August 18, 2015"). A prediction naming several
    years the label does not state ("August 1, 2014 and August 18, 2015") is
    ambiguous; a label that itself spans those years ("2014 to 2016") is not.
    """
    pred, exp = _integral_float_as_text(pred), _integral_float_as_text(exp)
    ps, es = _parse_date_parts(pred), _parse_date_parts(exp)
    pred_years = _stated_years(pred) | ({ps.year} if ps is not None and ps.year else set())
    if es is not None and es.year is None and pred_years:
        return True
    return len(pred_years) > 1 and not pred_years <= _stated_years(exp)


def _date_match_similarity(pred, exp, embedding=None) -> float:
    """Date similarity for MATCHING (list pairing, audits): an unverified year never matches.

    :func:`score_date_field` caps such a pair at 0.67 as a field score, which is
    above ``bipartite_match_threshold``; for pairing it counts as no match, so a
    dated prediction is never a true positive for a yearless label.
    """
    if _date_year_unverified(pred, exp):
        return 0.0
    return score_date_field(pred, exp, embedding=embedding)


def _stated_years(text) -> set:
    """Four-digit years (1900-2099) written in *text*."""
    return {int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(text))}


def _integral_float_as_text(value):
    """Render an integral float (a NaN-promoted year column: 2014.0) as "2014"."""
    if isinstance(value, float) and value == value and value.is_integer():
        return str(int(value))
    return value


def _score_date_field_uncapped(pred, exp, embedding=None) -> float:
    """Parse to canonical date, then exact match — with containment and
    partial-credit fallbacks. Never reads the clock.

    A date states some of (year, month, day); a yearless CUAD date such as
    "18th day of August" states month and day only, and "August 2014" states
    no day. A missing component is never invented: not from today's date and
    not from a placeholder. The year is critical information, and the year of
    a document is not the year the scorer runs in. Whether a yearless label
    fixes the year is therefore decided by the LABEL, not by the clock. A
    prediction that leaves out a year the label states never scores 1.0, and
    :func:`score_date_field` caps a prediction stating a year at 0.67 against
    a yearless label, because that label cannot verify the year.

    Rules, in order:

    1. Blank-template or label-only ground truth (no real date) -> 1.0 for a
       null prediction, else 0.0.
    2. Containment -> 1.0: the labeler's date phrase appears inside the
       prediction. The reverse (prediction inside the label) does not count
       when the prediction leaves out a component the label states.
    3. Both sides fully dated (year, month, day):

       * same date -> 1.0
       * same year+month, or within 45 days -> 0.67
       * same year or same month only -> 0.33
       * otherwise 0.0

    4. At least one side partly dated: compare only the components BOTH sides
       state (the 45-day window never applies).

       * every shared component agrees and the prediction states every
         component the label states -> 1.0 (a yearless label does not fix the
         year; the prediction agrees with all of it)
       * every shared component agrees but the prediction leaves out a
         component the label states -> 0.67 when two or more agree, 0.33 when
         only the year or only the month agrees, else 0.0; never 1.0
       * a shared component differs -> 0.33 when the shared year or month
         still agrees (e.g. same month, different day), else 0.0

    5. Unparseable values fall back to fuzzy string matching.
    """
    if not isinstance(pred, str):
        pred = str(pred or "")
    if not isinstance(exp, str):
        exp = str(exp or "")
    ps, es = _parse_date_parts(pred), _parse_date_parts(exp)
    # Blank-template and label-only ground truth (CUAD annotators select the
    # contract's literal date line: "_____ day of ________, 19____",
    # "Effective Date:") hold NO actual date. The model answering null is
    # CORRECT, and a fabricated date is not the labeled date.
    if es is None and _date_expected_is_null(exp):
        if not str(pred).strip():
            return 1.0
        # An exact copy of a non-date label ("Effective upon signing") is the
        # labelled value; a copied blank template or bare label is not a date.
        if not _date_is_blank_or_bare_label(exp) and normalize_text(pred) == normalize_text(exp):
            return 1.0
        return 0.0
    pred_omits_label_component = es is not None and (ps is None or bool(es.stated - ps.stated))
    if _date_phrase_contained(pred, exp) or (
        not pred_omits_label_component and _date_phrase_contained(exp, pred)
    ):
        return 1.0
    if ps is not None and es is not None:
        if ps.is_full and es.is_full:
            # Reuse the parsed components instead of parsing both sides again.
            # Full parts are always a real date: dateutil rejects "Feb 30".
            import datetime

            return _score_full_dates(datetime.date(*ps), datetime.date(*es))
        return _score_partial_dates(ps, es)
    if es is not None:
        # The label states a date but the prediction parses to no date. A bare
        # fragment ("12", "Tuesday") is not the date and gets nothing. A garbled
        # date that names a year ("Augus 18, 2014", "FY2014") keeps fuzzy credit,
        # but never above 0.33 unless it names the labelled year.
        pred_years = _stated_years(pred)
        if not pred_years:
            return 0.0
        score = score_name_field(pred, exp, embedding=embedding)
        if es.year is not None and es.year not in pred_years:
            score = min(score, 0.33)
        if not es.is_full:
            # Never more than the partial-date ceiling against a partial label.
            score = min(score, 0.67)
        return score
    return score_name_field(pred, exp, embedding=embedding)


def _score_full_dates(dp, de) -> float:
    """Score two fully dated values: exact, year+month or 45 days, year or month only."""
    if dp == de:
        return 1.0
    shared = sum(1 for a, b in ((dp.year, de.year), (dp.month, de.month)) if a == b)
    if shared == 2:
        return 0.67
    if abs((dp - de).days) <= 45:
        return 0.67
    if shared == 1:
        return 0.33
    return 0.0


def _score_partial_dates(ps: _DateParts, es: _DateParts) -> float:
    """Score when a side is missing year or day: compare only shared components."""
    common = ps.stated & es.stated
    agree = {i for i in common if ps[i] == es[i]}
    if agree == common and common:
        if es.stated <= ps.stated:
            return 1.0
        if len(agree) >= 2:
            return 0.67
        return 0.33 if agree & {0, 1} else 0.0
    return 0.33 if agree & {0, 1} else 0.0


def _date_expected_is_null(exp: str) -> bool:
    """True when the expected date text carries no real date: a blank
    template line or a bare label."""
    if "_" in exp or "blank" in exp.lower():
        return True
    low = exp.lower()
    if not any(m in low for m in _MONTH_NAMES):
        if not re.search(r"\b(19|20)\d{2}\b", low):
            return True
    return False


def _date_is_blank_or_bare_label(exp: str) -> bool:
    """True for a blank template line ("_____ day of ____") or a bare label ("Effective Date:")."""
    low = str(exp).strip().lower()
    return (
        "_" in low
        or "blank" in low
        or low.endswith(":")
        or bool(re.fullmatch(r"[a-z ]*\bdate\b[a-z ]*", low))
    )


def _date_phrase_contained(container: str, target: str) -> bool:
    """True when a date phrase stated in ``target`` appears in ``container``."""
    def norm(text: str) -> str:
        """Lowercase a date phrase and collapse non-alphanumeric separators to spaces."""
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text).lower())).strip()

    nc = norm(container)
    if not nc:
        return False
    target_norm = norm(target)
    if not target_norm:
        return False
    dt = _parse_date(target)
    explicit_month = (
        any(f" {month}" in target_norm for month in _MONTH_NAMES)
        or bool(re.search(r"\b\d{4}-\d{1,2}\b", target_norm))
    )
    # Match on word boundaries, so a date is never found inside a different one
    # ("august 1" in "august 18 2014", "1 august 2014" in "11 august 2014").
    found = _contains_phrase(nc, target_norm)
    if found and (len(target_norm.split()) >= 3 or explicit_month):
        return True
    if dt is None:
        return False
    month = _MONTH_NAMES[dt.month - 1]
    renderings = [
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}",
        f"{month} {dt.day} {dt.year}",
        f"{dt.day} {month} {dt.year}",
    ]
    return any(_contains_phrase(nc, norm(r)) for r in renderings)


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """True when *phrase* occurs in *haystack* bounded by non-alphanumerics."""
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", haystack))


# ---------------------------------------------------------------------------
# Entity LIST scoring — optimal bipartite matching (relaxed NER style)
# ---------------------------------------------------------------------------


@dataclass
class EntityListScore:
    """Entity-list matching counts and precision, recall, and F1 for one field."""
    field_name: str
    precision: float
    recall: float
    f1: float
    matched: int
    unmatched_predicted: int
    unmatched_expected: int
    partial_gt: bool = False

    @property
    def score(self) -> float:
        """Composite score: F1 normally; GROUND-TRUTH COVERAGE (recall) when
        the field's label set is a partial sample (partial_gt_fields)."""
        return self.recall if self.partial_gt else self.f1

    def to_dict(self) -> dict:
        """Serialize rounded list metrics and reconstruct predicted and expected counts."""
        return {
            "field": self.field_name,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "matched": self.matched,
            "n_predicted": self.unmatched_predicted + self.matched,
            "n_expected": self.unmatched_expected + self.matched,
            "partial_gt": self.partial_gt,
        }


def _as_list(value) -> list:
    """Parse a JSON container, then return a list or wrap a non-list value.

    ``None`` becomes ``[]``; existing lists are returned unchanged.
    """
    value = parse_json_container(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _element_scorer(element_type: str):
    """Scalar scorer for entity-list elements (entity_list:<element_type>)."""
    return FIELD_SCORERS.get(element_type, score_name_field)


# Party ROLE labels that CUAD ground truth uses INSTEAD of the actual entity
# name ("Shipper.", "Sponsor", "Seller", ...). A role word in the label set is
# matched whenever the prediction names at least one party.
_ROLE_WORDS = {
    "shipper", "sponsor", "seller", "buyer", "company", "producer", "reseller",
    "licensee", "licensor", "party", "parties", "transporter", "customer",
    "client", "vendor", "purchaser", "lender", "borrower", "guarantor",
    "manufacturer", "distributor", "owner", "operator",
}


def _is_role_word(text: str) -> bool:
    """Recognize short phrases consisting entirely of generic party-role words."""
    tokens = _tokenize(str(text))
    return 1 <= len(tokens) <= 3 and all(t in _ROLE_WORDS for t in tokens)


def _element_similarity(element_type: str, item: str, exp: str, embedding=None) -> float:
    """Similarity of one predicted list item against one ground-truth item.

    For ``free_text`` elements, when the item covers >= the verification
    coverage of the answer's plain tokens, that coverage is the similarity
    (the item IS the labeled clause, quoted at length)."""
    if element_type == "date":
        return _date_match_similarity(item, exp, embedding=embedding)
    base = _element_scorer(element_type)(item, exp, embedding=embedding)
    if element_type == "free_text":
        answer_tokens = set(_tokenize(str(exp)))
        item_tokens = set(_tokenize(str(item)))
        if answer_tokens:
            coverage = len(answer_tokens & item_tokens) / len(answer_tokens)
            if coverage >= get_verification_coverage():
                return max(float(base), coverage)
    return base


def score_entity_list(element_type: str, pred, exp, embedding=None,
                      partial_gt: bool = False) -> EntityListScore:
    """Pairwise similarity matrix + Hungarian assignment (scipy), thresholded,
    then precision/recall/F1 over the matched set.

    ``partial_gt=True`` (label sets that are QA-answer samples rather than
    exhaustive lists): role-word label items count as matched whenever the
    prediction names any party, and the reported score becomes ground-truth
    coverage (recall)."""
    pred_items = [str(item) for item in _as_list(pred)]
    exp_items = [str(item) for item in _as_list(exp)]
    if not pred_items and not exp_items:
        return EntityListScore("", 1.0, 1.0, 1.0, 0, 0, 0, partial_gt)
    if not pred_items:
        return EntityListScore("", 0.0, 0.0, 0.0, 0, 0, len(exp_items), partial_gt)
    if not exp_items:
        return EntityListScore("", 1.0, 0.0, 0.0, 0, len(pred_items), 0, partial_gt)

    scorer = _element_scorer(element_type)
    threshold = get_bipartite_match_threshold()
    n_pred, n_exp = len(pred_items), len(exp_items)

    if partial_gt:
        pred_token_lists = [_tokenize(str(p)) for p in pred_items]

        def _label_contained(label: str) -> bool:
            """Check whether a three-to-six-token label occurs contiguously in a prediction."""
            label_tokens = _tokenize(str(label))
            if not label_tokens:
                return False
            n = len(label_tokens)
            if n < 3 or n > 6:
                return False
            return any(
                label_tokens == tokens[i:i + n]
                for tokens in pred_token_lists
                for i in range(len(tokens) - n + 1)
            )

        real_exp = [e for e in exp_items if not (_is_role_word(e) or _label_contained(e))]
        role_items = sum(1 for e in exp_items if _is_role_word(e))
        contained_items = n_exp - len(real_exp) - role_items
        pred_has_party = any(not _is_role_word(p) for p in pred_items)
    else:
        real_exp = exp_items
        role_items = 0
        contained_items = 0
        pred_has_party = False

    # Skip the Hungarian machinery for trivially scored single-element lists.
    if len(pred_items) == 1 and len(real_exp) == 1:
        matched = 1 if _element_similarity(
            element_type, pred_items[0], real_exp[0], embedding
        ) >= threshold else 0
    else:
        try:
            import numpy as np
            from scipy.optimize import linear_sum_assignment

            sim = np.array([
                [_element_similarity(element_type, p, e, embedding) for e in real_exp]
                for p in pred_items
            ])
            row_idx, col_idx = linear_sum_assignment(1.0 - sim)
            matched = sum(1 for r, c in zip(row_idx, col_idx) if sim[r, c] >= threshold)
        except Exception:
            # scipy unavailable/failed: greedy one-to-one assignment fallback.
            logger.warning("bipartite_matching_failed", fallback="greedy", exc_info=True)
            matched = 0
            assigned_exp = set()
            for p_item in pred_items:
                best, best_e = threshold, None
                for ei, e_item in enumerate(real_exp):
                    if ei in assigned_exp:
                        continue
                    s = _element_similarity(element_type, p_item, e_item, embedding)
                    if s >= best:
                        best, best_e = s, ei
                if best_e is not None:
                    matched += 1
                    assigned_exp.add(best_e)

    if role_items and pred_has_party:
        matched += role_items
    if contained_items:
        matched += contained_items

    # Role-word/contained credits are a BOUNDED credit, not an unbounded
    # additive bonus: nothing tracks which distinct predicted items were
    # consumed, so without the clamp an all-role-word expected list vs a
    # single named party yields precision 2/1 = 2.0 (hub#38). The composite
    # may never exceed the smaller of the two list sizes.
    matched = min(matched, n_pred, n_exp)

    precision = matched / n_pred
    recall = matched / n_exp
    f1 = 2 * precision * recall / (precision + recall) if matched else 0.0
    return EntityListScore(
        field_name="",
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        unmatched_predicted=n_pred - matched,
        unmatched_expected=n_exp - matched,
        partial_gt=partial_gt,
    )


# ---------------------------------------------------------------------------
# Factuality audit — "everything the model reports must be TRUE"
# ---------------------------------------------------------------------------


def verify_list_items(items: list, doc_text: str, token_coverage: float | None = None) -> list[bool]:
    """Groundedness flags: is each item's content present in ``doc_text``?
    ``token_coverage`` is the minimum share of the item's normalized tokens
    found in the document (default from config)."""
    threshold = get_verification_coverage() if token_coverage is None else token_coverage
    dt_tokens = _containment_tokens(str(doc_text or ""))
    flags: list[bool] = []
    for item in items or []:
        it_tokens = _containment_tokens(str(item))
        if not it_tokens or not dt_tokens:
            flags.append(False)
            continue
        coverage = len(it_tokens & dt_tokens) / len(it_tokens)
        flags.append(coverage >= threshold)
    return flags


def audit_list_field(
    element_type: str,
    pred_items: list,
    exp_items: list,
    doc_text: str | None,
    token_coverage: float | None = None,
) -> dict:
    """Per-item truth audit for one list field: each predicted item is TRUE
    when it matches any ground-truth label OR its content is grounded in the
    source document. Returns counts plus verified_precision/hallucination_rate."""
    pred_items = [str(item) for item in _as_list(pred_items)]
    exp_items = [str(item) for item in _as_list(exp_items)]
    n_pred = len(pred_items)
    if n_pred == 0:
        return {"n_predicted": 0, "matched_gt": 0, "verified_in_doc": 0,
                "true_items": 0, "verified_precision": 0.0,
                "hallucinated": 0, "hallucination_rate": 0.0,
                "doc_verification": False}

    match_threshold = get_bipartite_match_threshold()
    dt_tokens = _containment_tokens(str(doc_text or ""))
    verify_threshold = get_verification_coverage() if token_coverage is None else token_coverage

    matched_gt = verified = true_items = 0
    for item in pred_items:
        hit_gt = any(
            _element_similarity(element_type, item, e) >= match_threshold
            for e in exp_items
        ) if exp_items else False
        it_tokens = _containment_tokens(item)
        in_doc = bool(it_tokens) and bool(dt_tokens) and (
            len(it_tokens & dt_tokens) / len(it_tokens) >= verify_threshold
        )
        if hit_gt:
            matched_gt += 1
        if in_doc:
            verified += 1
        if hit_gt or in_doc:
            true_items += 1

    return {
        "n_predicted": n_pred,
        "matched_gt": matched_gt,
        "verified_in_doc": verified,
        "true_items": true_items,
        "verified_precision": round(true_items / n_pred, 4),
        "hallucinated": n_pred - true_items,
        "hallucination_rate": round((n_pred - true_items) / n_pred, 4),
        "doc_verification": bool(doc_text),
    }


def _verification_tokens(value, field_type: str) -> set[str]:
    """Token set used to check a predicted VALUE against the source document.
    Dates are converted to prose BEFORE tokenizing so an ISO prediction
    matches the document's prose date."""
    text = str(value or "")
    if field_type == "date":
        parts = _parse_date_parts(text)
        if parts is not None:
            month = _MONTH_NAMES[parts.month - 1].capitalize() if parts.month else ""
            day = f" {parts.day}" if parts.day else ""
            year = f", {parts.year}" if parts.year and parts.day else (f" {parts.year}" if parts.year else "")
            text = f"{month}{day}{year}".strip()
    return _containment_tokens(text)


# Date spans in a document. Every common written form is found; each span is then
# read by ``_parse_date_parts``, the same reader the prediction and the label go
# through, so "stated" means the same thing on both sides of the comparison.
#
#   ISO / year-first numeric   2024-03-03  2024/03/03  2024.03.03  2024-Mar-03  20240303
#   US / day-first numeric     3/24/2006  04-01-06  13.04.2024  3.4.24  (month-first when ambiguous)
#   month-first prose          March 3, 2024  Mar. 3rd, 2024  March the 3rd, 2024  may 3, 2024
#   day-first prose            3 March 2024  3rd of March, 2024  03-Mar-2024
#                              the 3rd day of March, 2024 (also "18t h day of", "twenty-first
#                              of June", "this third day of March in the year of our Lord
#                              two thousand twenty-four")
#   year-first prose           2024 March 3  2024, March 3rd
#   month and year             March 2024  March of 2024  Mar-2024  2024-03  03/2024  3/2024
#   month and day, no year     March 3  3rd of March
#   day ranges                 March 3-5, 2024  3-5 March 2024  March 3 to 5, 2024
#                              March 30-April 2, 2024  (BOTH ends are read: the document states them)
#
# A weekday prefix ("Sunday, March 3, 2024") sits outside the span: the reader drops
# weekdays anyway. Two guard strengths keep a date-shaped string that is not a date out:
#
# * A COMPLETE date (day, month and a four-digit year, or a numeric two-digit year after
#   dashes or slashes) may touch punctuation, ``_``, ``@`` or a letter on either side, so
#   ranges ("01/01/2024-12/31/2024", "March 1, 2024/March 1, 2025") and file names
#   ("contract_3-1-2024.pdf") read. It may not touch a digit, which would make it part of
#   a longer number ("2024-03-0001").
# * Every other form (month and year, month and day, compact, dotted two-digit year) must
#   stand alone: never part of a longer alphanumeric, hyphen, slash or dotted run (ids like
#   ``INV-2024-0301``, ``2024-03-0001``, phone numbers, ``1.2.34``), and never after ``#``,
#   ``@``, a currency sign or ``+``.
#
# Other lookalike guards: numbers are a day, month or year only in their calendar range;
# a dotted two-digit year is not read after "v", "version", "release", "build" or "rev"
# (``3.4.24`` is a date, ``version 1.2.34`` is not; any other ``1.2.34`` is read as a
# date); "May" and "March" are months in a partial date only when capitalised ("you may 5
# times" is not May 5), and in a full date ("may 3, 2024") in any case; a decimal or
# thousands group after a day ("March 3,000", "March 3.50") is money, not a day. Every
# gap between the parts of a date is bounded (30 whitespace characters) so that a hostile
# document cannot make the scan quadratic.
_S = r"\s{1,30}"
_S0 = r"\s{0,30}"
_MON_ANY = _MONTH_ANY_WORD + r"\b\.?"
_MON_PART_WORD = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|(?-i:Mar(?:ch)?|MAR(?:CH)?)|apr(?:il)?|(?-i:May|MAY)"
    r"|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MON_PART = _MON_PART_WORD + r"\b\.?"
_DAY = r"(?:3[01]|[12]\d|0?[1-9])"
_DAY_ORD = _DAY + r"(?:st|nd|rd|th|d)?"  # "3d" is the legal 3rd
_DAY_OCR = r"\d{1,2}(?:\s?(?:s\s?t|n\s?d|r\s?d|t\s?h))?"  # "18t h day of"
_NUM_MONTH = r"(?:1[0-2]|0?[1-9])"
_PAD_MONTH = r"(?:1[0-2]|0[1-9])"
_YEAR = r"(?:18|19|20)\d{2}(?!\d)"  # 1800-2099: 1/1000 is a fraction
_YEAR_X = r"(?:" + _YEAR + "|" + _YEAR_WORDS + ")"
_YEAR_FILL = r"(?:in" + _S + r"the" + _S + r"year(?:" + _S + r"of" + _S + r"our" + _S + r"Lord)?" + _S + r")?(?:A\.?D\.?" + _S + r")?"
_SEP_DAY_YEAR = r"(?:" + _S0 + "," + _S0 + "|" + _S + ")"
_SEP_DAY_YEAR_OF = r"(?:" + _S0 + "," + _S0 + "|" + _S + r"(?:of" + _S + ")?)"  # "March 3rd of 2024"
_SEP_MONTH_YEAR = _S0 + r"(?:," + _S0 + ")?"
_THE_DAY = r"(?:" + _S + "the" + _S + "|" + _S0 + ")"
_THE_DAY_COMMA = r"(?:" + _S0 + "," + _S0 + "|" + _S + "the" + _S + "|" + _S0 + ")"  # "March, 3 2024"
#: "3rd day of March", "3rd of March", "3rd day of the month of March".
_DAY_OF = r"(?:(?:day" + _S + ")?of" + _S + r"(?:the" + _S + "month" + _S + "of" + _S + ")?)"
_RANGE_JOIN = r"(?:" + _S0 + r"[-–—]" + _S0 + "|" + _S + r"(?:to|through|thru|until)" + _S + ")"
_QUOTE = "['’]"

# A date may not start right after a letter ("HO3-12-2020", "A1-12-2020" are ids) unless a
# separator comes between: "contract_3-1-2024.pdf", "Filed 3/1/2024", "ref-3-1-2024".
_LEFT_STRICT = r"(?<![\w\-/#@$€£+])(?<!\d\.)(?<!\d,)"
_LEFT_NUMBER = r"(?<![\dA-Za-z])(?<!\d\.)"  # complete numeric date: not inside a longer number or id
_LEFT_WORD = r"(?<![A-Za-z\d])"  # prose date starting with a word: not inside a longer word
_RIGHT_STRICT = r"(?:(?=T\d{2}:\d{2})|(?![\w\-/@]))(?![.,]\d)"  # ISO datetime: 2024-03-03T10:30
_RIGHT_OPEN = r"(?!\d)(?!\.\d)"  # complete date: anything but a digit may follow
#: A two-digit year in prose must not be the start of a longer number ("4 March 15, 2024").
_RIGHT_TWO_DIGIT_YEAR = _RIGHT_STRICT + r"(?!" + _S0 + r"(?:," + _S0 + r")?\d)"
#: "the 3rd (third) day of March": the day written twice, as contracts do.
_PAREN_DAY = r"(?:\s{0,3}\(\s{0,3}(?:" + _DAY_ORD + "|" + _ORD_WORD + r")\s{0,3}\))?"
_DOTTED_NEXT = r"[-–]\d{1,2}\.\d{1,2}\.\d{2}(?!\d)"  # a dotted two-digit-year range


def _guarded(left: str, body: str, right: str) -> str:
    """One alternative of the scan: ``body`` with its own left and right guard."""
    return left + "(?:" + body + ")" + right


# The alternatives are split by what they start with, and each group sits behind a cheap
# lookahead on the shape of what follows the first number or word. A position that cannot start
# a date skips every alternative of the group on that one check, which keeps the scan of a long
# hostile document fast.
def _num(left: str, body: str, right: str) -> tuple[str, str]:
    """An alternative that starts with a number and a separator: 2024-03-03, 3/4/24, 3.4.24."""
    return "num", _guarded(left, body, right)


def _prose(left: str, body: str, right: str) -> tuple[str, str]:
    """An alternative that starts with a number and a space: 3 March 2024, 2024 March 3."""
    return "prose", _guarded(left, body, right)


def _misc(left: str, body: str, right: str) -> tuple[str, str]:
    """An alternative that starts with a number glued to a letter or eight digits: 03MAR2024."""
    return "misc", _guarded(left, body, right)


def _wmonth(left: str, body: str, right: str) -> tuple[str, str]:
    """An alternative that starts with a month name."""
    return "wmonth", _guarded(left, body, right)


def _word(left: str, body: str, right: str) -> tuple[str, str]:
    """An alternative that starts with an ordinal word: twenty-first of June."""
    return "word", _guarded(left, body, right)


_DATE_ALTERNATIVES = (
    [
        # --- complete dates: open guards ---
        # year-first numeric, one separator throughout: 2024-03-03, 2024/03/03, 2024.03.03
        _num(_LEFT_NUMBER, _YEAR + r"(?P<iso>[-/.])" + _NUM_MONTH + r"(?P=iso)" + _DAY, _RIGHT_OPEN),
        # day, month, year with dashes or slashes: 3/24/2006, 13-04-2024, 04-01-06
        _num(_LEFT_NUMBER, _DAY + r"(?P<num>[-/])" + _DAY + r"(?P=num)" + _YEAR, _RIGHT_OPEN),
        _num(_LEFT_NUMBER, _DAY + r"(?P<num2>[-/])" + _DAY + r"(?P=num2)\d{2}", _RIGHT_OPEN),
        # dotted: 13.04.2024 (a version or section number after its word is filtered out of the matches)
        _num(_LEFT_NUMBER, _DAY + r"\." + _DAY + r"\." + _YEAR, _RIGHT_OPEN),
        # month-first prose: March 3, 2024  Mar. 3rd 2024  March the 3rd, in the year 2024
        # March, 3 2024  March 3rd of 2024
        _wmonth(_LEFT_WORD, _MON_ANY + _THE_DAY_COMMA + _DAY_ORD + _SEP_DAY_YEAR_OF + _YEAR_FILL + _YEAR_X, _RIGHT_OPEN),
        # month first with the day spelled out: March third, 2024  May twenty-fourth, 2024
        _wmonth(
            _LEFT_WORD,
            _MON_ANY + r"(?:" + _S + "the" + _S + "|" + _S + ")" + _NOT_COMPOUND + _ORD_WORD + _SEP_DAY_YEAR
            + _YEAR_FILL + _YEAR_X,
            _RIGHT_OPEN,
        ),
        # day-first prose: 3 March 2024, 3rd of March, 2024, 3rd day of March, in the year 2024
        _prose(
            _LEFT_NUMBER,
            r"(?:" + _DAY_ORD + _PAREN_DAY + _S + _DAY_OF + "?|" + _DAY_OCR + _S + "day" + _S + "of" + _S + ")"
            + _MON_ANY + _SEP_MONTH_YEAR + _YEAR_FILL + _YEAR_X,
            _RIGHT_OPEN,
        ),
        # day-first with the day spelled out: twenty-first of June 2024, third day of March, 2024
        _word(
            _NOT_COMPOUND,
            _ORD_WORD + _PAREN_DAY + _S + _DAY_OF + _MON_ANY + _SEP_MONTH_YEAR + _YEAR_FILL + _YEAR_X,
            _RIGHT_OPEN,
        ),
        # 03-Mar-2024, 03-Mar-24, 3/Mar/2024, 3rd-March-2024
        _num(
            _LEFT_NUMBER,
            _DAY_ORD + r"(?P<dm>[-/])" + _MONTH_ANY_WORD + r"\b(?P=dm)(?:" + _YEAR + r"|\d{2}(?!\d))",
            _RIGHT_OPEN,
        ),
        # year-first prose: 2024 March 3, 2024, March 3rd, 2024-Mar-03
        _prose(_LEFT_NUMBER, _YEAR + _SEP_DAY_YEAR + _MON_ANY + _THE_DAY + _DAY_ORD, _RIGHT_OPEN),
        _num(_LEFT_NUMBER, _YEAR + "-" + _MONTH_ANY_WORD + r"\b-" + _DAY_ORD, _RIGHT_OPEN),
        # --- partial and ambiguous forms: strict guards ---
        # DDMONYYYY and DDMONYY, standing alone: 03MAR2024, 3MAR24
        _misc(_LEFT_STRICT, _DAY + _MONTH_ANY_WORD + r"(?:" + _YEAR + r"|\d{2}(?!\d))", _RIGHT_STRICT),
        # two-digit-year prose: Mar 3, 24  March 3rd, '24  31 Dec 23  3 Mar 24
        _wmonth(
            _LEFT_STRICT,
            _MON_ANY + _THE_DAY + _DAY_ORD + r"(?:" + _SEP_DAY_YEAR + _QUOTE + "|" + _S0 + "," + _S0 + r")\d{2}",
            _RIGHT_TWO_DIGIT_YEAR,
        ),
        _prose(
            _LEFT_STRICT,
            _DAY_ORD + _S + r"(?:of" + _S + ")?" + _MON_ANY + r"(?:" + _S0 + "," + _S0 + "|" + _S + ")" + _QUOTE + r"?\d{2}",
            _RIGHT_TWO_DIGIT_YEAR,
        ),
        # compact ISO, standing alone: 20240303 (years 1800-2099, like _YEAR)
        _misc(_LEFT_STRICT, r"(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", _RIGHT_STRICT),
        # dotted two-digit year: 03.04.24, 3.4.24
        # (both ends of a range 12.31.99-12.31.99 read; the version filter is in _document_dates)
        _num(
            r"(?:(?<=\.\d{2}[-–])|" + _LEFT_STRICT + ")",
            _DAY + r"\." + _DAY + r"\.\d{2}",
            r"(?:(?=" + _DOTTED_NEXT + ")|" + _RIGHT_STRICT + ")",
        ),
        # month and year: March 2024, March of 2024, Mar-2024, 03/2024, 3/2024, 2024-03, 2024/03
        _wmonth(_LEFT_STRICT, _MON_PART + r"(?:" + _S0 + "," + _S0 + "|" + _S + "of" + _S + "|" + _S0 + ")" + _YEAR, _RIGHT_STRICT),
        _wmonth(_LEFT_STRICT, _MON_PART_WORD + r"\b-" + _YEAR, _RIGHT_STRICT),
        _num(_LEFT_STRICT, _NUM_MONTH + "/" + _YEAR, _RIGHT_STRICT),
        _num(_LEFT_STRICT, _PAD_MONTH + "-" + _YEAR, _RIGHT_STRICT),
        _num(_LEFT_STRICT, _YEAR + r"[-/]" + _PAD_MONTH, _RIGHT_STRICT),
        # month and day, no year: March 3, 3rd of March, twenty-first of June
        _wmonth(_LEFT_STRICT, _MON_PART + _THE_DAY + _DAY_ORD, _RIGHT_STRICT),
        _prose(_LEFT_STRICT, _DAY_ORD + _PAREN_DAY + _S + _DAY_OF + "?" + _MON_PART, _RIGHT_STRICT),
        _word(_LEFT_STRICT + _NOT_COMPOUND, _ORD_WORD + _PAREN_DAY + _S + _DAY_OF + _MON_PART, _RIGHT_STRICT),
    ]
)
# Every start position is tried (a zero-width match that captures the span from a lookahead),
# not only the first one after the previous match: "Item 4 March 15, 2024" has a year-less
# "4 March" at the 4 and the full date at "March", and a non-overlapping scan loses the second.
# The scan runs on text with ASCII digits and spaces (see ``_ascii_digits``: NFKC folds no-break and
# other Unicode spaces), so the cheaper ASCII classes are exact and the scan is a fifth faster.
_SCAN_FLAGS = re.IGNORECASE | re.ASCII
_PRE_MONTH = r"(?=(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))"
_PRE_ORDINAL = r"(?=(?:fir|sec|thi|fou|fif|six|sev|eig|nin|ten|ele|twe))"
_DATE_CANDIDATE_RE = re.compile(
    r"(?<![\dA-Za-z])(?:"
    r"(?=\d{1,4}(?:st|nd|rd|th|d)?[-/.][\dA-Za-z])(?=(?P<g_num>"
    + "|".join(alt for kind, alt in _DATE_ALTERNATIVES if kind == "num") + "))"
    r"|(?=\d{1,4}[A-Za-z]{0,2}[\s,(]{1,30}(?:of\b|day\b|[a-z]\b|\(|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)))"
    r"(?=(?P<g_prose>" + "|".join(alt for kind, alt in _DATE_ALTERNATIVES if kind == "prose") + "))"
    r"|(?=\d{1,2}[A-Za-z]|\d{8})(?=(?P<g_misc>"
    + "|".join(alt for kind, alt in _DATE_ALTERNATIVES if kind == "misc") + "))"
    r"|" + _PRE_MONTH + r"(?=(?P<g_wmonth>" + "|".join(alt for kind, alt in _DATE_ALTERNATIVES if kind == "wmonth") + "))"
    r"|" + _PRE_ORDINAL + r"(?=(?P<g_word>" + "|".join(alt for kind, alt in _DATE_ALTERNATIVES if kind == "word") + "))"
    r")",
    flags=_SCAN_FLAGS,
)

# Day ranges. The document states every day a range names, so both ends are dates:
# "March 3-5, 2024" is March 3 and March 5, 2024; "March 30-April 2, 2024" is March 30 and
# April 2; "March 1 to June 30" is both days, year-less. (A range does not state the days
# between its ends.) A dated range may follow a letter or punctuation; a year-less one is a
# partial date and keeps the strict guards, and "May"/"March" need a capital there.
_ORD_SUFFIX = r"(?:st|nd|rd|th|d)?"
_RANGE_DATED = (
    # March 3-5, 2024 / March 3 to 5, 2024 / March 3rd through 5th, 2024
    r"(?P<m1>" + _MON_ANY + r")" + _THE_DAY + r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN
    + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX + _SEP_DAY_YEAR + r"(?P<y>" + _YEAR + ")",
    # 3-5 March 2024 / 3 to 5 March, 2024
    r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX
    + _S + r"(?:of" + _S + r")?(?P<m1>" + _MON_ANY + ")" + _SEP_MONTH_YEAR + r"(?P<y>" + _YEAR + ")",
    # March 30-April 2, 2024 / March 1 to April 5, 2024
    r"(?P<m1>" + _MON_ANY + r")" + _THE_DAY + r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN
    + r"(?P<m2>" + _MON_ANY + r")" + _THE_DAY + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX
    + _SEP_DAY_YEAR + r"(?P<y>" + _YEAR + ")",
)
_RANGE_YEARLESS = (
    r"(?P<m1>" + _MON_PART + r")" + _THE_DAY + r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN
    + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX,
    r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX
    + _S + r"(?:of" + _S + r")?(?P<m1>" + _MON_PART + ")",
    r"(?P<m1>" + _MON_PART + r")" + _THE_DAY + r"(?P<d1>" + _DAY + r")" + _ORD_SUFFIX + _RANGE_JOIN
    + r"(?P<m2>" + _MON_PART + r")" + _THE_DAY + r"(?P<d2>" + _DAY + r")" + _ORD_SUFFIX,
)
def _range_pattern(body: str, left: str, right: str) -> "re.Pattern[str]":
    """One range regex, tried at every start position behind a one-character lookahead."""
    first = r"(?=\d)" if body.startswith(r"(?P<d1>") else r"(?=[A-Za-z])"
    return re.compile(first + left + "(?=(?:" + body + ")" + right + ")", flags=_SCAN_FLAGS)


_DATE_RANGE_RES = tuple(_range_pattern(body, _LEFT_WORD, r"(?!\d)") for body in _RANGE_DATED) + tuple(
    _range_pattern(body, _LEFT_STRICT, _RIGHT_STRICT) for body in _RANGE_YEARLESS
)

# A range needs a number or month, a join and a number or month, close together: one cheap
# search decides whether the six range regexes can match anywhere in the document.
_RANGE_HINT_RE = re.compile(
    r"(?:\d" + _ORD_SUFFIX + "|" + _MONTH_ANY_WORD + r"\b\.?)" + _S0 + r"(?:[-\u2013\u2014]|" + r"\b(?:to|through|thru|until)\b)"
    + _S0 + r"(?:\d|" + _MONTH_ANY_WORD + ")",
    flags=_SCAN_FLAGS,
)

# Words that make a number a reference, not a date.
_VERSION_WORDS = r"v|ver(?:sion)?|release|build|rev(?:ision)?"
_SECTION_WORDS = (
    r"sec(?:tion)?s?|clauses?|articles?|art|paragraphs?|para|rules?|items?|parts?|schedules?|exhibits?"
)
_ID_WORDS = (
    r"case|nos?|numbers?|ordinances?|resolutions?|policy|policies|claims?|dockets?|ref(?:erence)?s?|rfc"
    r"|pub\.?\s{0,2}l|ext|rooms?|invoices?|inv"
)
_DOTTED_CHAIN = r"(?:\d{1,2}(?:\.\d{1,2}){2,}[-–])?"
#: A dotted span (3.4.24, 13.04.2024) right after one of these is a version or a section number
#: ("Version: 1.2.34", "Release notes 1.2.34", "Section 3.1.20", "§ 5.2.14", "see build 1.2.34-1.2.35").
_DOTTED_CONTEXT_RE = re.compile(
    r"(?:\b(?:" + _VERSION_WORDS + "|" + _SECTION_WORDS + r")\.?(?:\s{1,3}notes?)?|§§?|¶¶?)[\s:]{0,3}"
    + _DOTTED_CHAIN + r"\Z",
    flags=re.IGNORECASE,
)
#: A numeric month and year alone (03/2024, 3/2024, 03-2024, 2024-03) after one of these is a
#: reference number ("Case No. 03-2024", "Invoice #03/2024", "Section 3/2024").
_ID_CONTEXT_RE = re.compile(
    r"(?:\b(?:" + _ID_WORDS + "|" + _SECTION_WORDS + "|" + _VERSION_WORDS
    + r")\.?(?:\s{1,3}(?:no|number|nr)\.?)?|#)[\s:#]{0,3}\Z",
    flags=re.IGNORECASE,
)
_DOTTED_SPAN_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}\Z")
_MONTH_YEAR_NUMERIC_RE = re.compile(r"(?:\d{1,2}[-/]\d{4}|\d{4}[-/]\d{2})\Z")


@lru_cache(maxsize=8)
def _document_dates(doc_text: str) -> frozenset:
    """The :class:`_DateParts` of every date the document writes, scanned once per text."""
    text = _TENS_GAP_RE.sub(r"\1 ", _ascii_digits(doc_text))
    spans = set()
    blocked: dict[tuple[bool, str], bool] = {}  # (dotted?, the 40 characters before a span) -> verdict
    for match in _DATE_CANDIDATE_RE.finditer(text):
        span = match.group(match.lastgroup)
        if span in spans:
            continue
        dotted = _DOTTED_SPAN_RE.match(span) is not None
        if dotted or _MONTH_YEAR_NUMERIC_RE.match(span):
            before = text[max(0, match.start() - 40):match.start()]
            key = (dotted, before)
            if key not in blocked:
                pattern = _DOTTED_CONTEXT_RE if dotted else _ID_CONTEXT_RE
                blocked[key] = pattern.search(before) is not None
            if blocked[key]:
                continue
        spans.add(span)
    for pattern in _DATE_RANGE_RES if _RANGE_HINT_RE.search(text) else ():
        for match in pattern.finditer(text):
            ends = match.groupdict()
            year = f", {ends['y']}" if ends.get("y") else ""
            for month, day in ((ends["m1"], ends["d1"]), (ends.get("m2") or ends["m1"], ends["d2"])):
                spans.add(f"{month} {day}{year}")
    parsed = (_parse_date_parts(span) for span in spans)
    return frozenset(parts for parts in parsed if parts is not None)


def _date_grounded_in_doc(pred_date, doc_text: str) -> bool:
    """True when the document writes a date that agrees with ``pred_date``, in ANY
    common format: ISO and other year-first numeric, US numeric, month-first or
    day-first prose (ordinals, spelled-out days and years, "the 3rd day of March,
    2024", weekday prefixes), year-first prose, month and year, month and day, and
    day ranges (a range states both its ends). The scan is :data:`_DATE_CANDIDATE_RE`
    (every start position is tried) plus :data:`_DATE_RANGE_RES`; ids, section numbers and
    reference numbers are filtered out (see the contract, ``docs/contracts/GROUNDING.md``).

    ``pred_date`` is a ``datetime.date`` or the :class:`_DateParts` of a
    partial date. Every component the prediction states must be stated by the
    document's date and equal: a partial prediction ("August 18") is grounded by
    a document date that agrees on what it states, but a year-less document date
    ("on August 18") never grounds a prediction that states a year, and no
    component is invented. Numeric ``03/04/2024`` is month-first, as everywhere
    in this module. Never reads the clock.
    """
    if pred_date is None or not doc_text:
        return False
    if not isinstance(pred_date, _DateParts):
        pred_date = _DateParts(pred_date.year, pred_date.month, pred_date.day)
    return any(
        all(want is None or want == got for want, got in zip(pred_date, candidate))
        for candidate in _document_dates(doc_text)
    )


def audit_scalar_field(field_type: str, pred, exp, doc_text: str | None) -> dict:
    """Factuality audit for one SCALAR (non-list) field.

    The predicted value is TRUE when it matches the ground truth (element
    scorer above the match threshold) OR its content is grounded in the
    source document. Fields the model left empty are not audited."""
    pred = str(pred or "")
    if not pred.strip():
        return {"n_predicted": 0, "matched_gt": 0, "verified_in_doc": 0,
                "true_items": 0, "verified_precision": 0.0,
                "hallucinated": 0, "hallucination_rate": 0.0,
                "doc_verification": bool(doc_text)}
    scorer = _date_match_similarity if field_type == "date" else FIELD_SCORERS.get(field_type, score_name_field)
    threshold = get_bipartite_match_threshold()
    matched = exp not in (None, "") and scorer(pred, str(exp)) >= threshold
    in_doc = False
    if doc_text:
        if field_type == "date":
            in_doc = _date_grounded_in_doc(_parse_date_parts(pred), doc_text)
        else:
            it_tokens = _verification_tokens(pred, field_type)
            dt_tokens = _containment_tokens(doc_text)
            in_doc = bool(it_tokens) and bool(dt_tokens) and (
                len(it_tokens & dt_tokens) / len(it_tokens) >= get_verification_coverage()
            )
    true = bool(matched) or bool(in_doc)
    return {
        "n_predicted": 1,
        "matched_gt": int(bool(matched)),
        "verified_in_doc": int(bool(in_doc)),
        "true_items": int(true),
        "verified_precision": 1.0 if true else 0.0,
        "hallucinated": 0 if true else 1,
        "hallucination_rate": 0.0 if true else 1.0,
        "doc_verification": bool(doc_text),
    }


def _split_clause_spans(text: str) -> list[str]:
    """Split one predicted obligation string into discrete clause fragments.

    Contracts quote several distinct clauses inside a single array item,
    separated by newlines, semicolons, or sentence-final punctuation. Splitting
    there keeps each operative clause a self-contained span so the contained-
    label rule can fire on its own tokens instead of being diluted by the
    other clauses in the merged item (issue #21). Guards against splitting on
    decimals ("$5.00"), section refs ("1.2"), and abbreviations ("U.S.")."""
    parts = re.split(
        r"(?:\s*\n\s*|\s*;\s+|(?<=[A-Za-z)][.!?])\s+(?=[A-Z0-9\"(]))",
        str(text or ""),
    )
    return [p.strip() for p in parts if p.strip()]


def disaggregate_clause_spans(items, min_span_tokens: int = 4) -> list[str]:
    """Disaggregate multi-clause predicted list items into discrete,
    sentence-level spans for scoring.

    Each input item is split into clause fragments; fragments shorter than
    ``min_span_tokens`` are merged back into the preceding fragment so a short
    standalone clause is not atomized. Returns the flat, de-duplicated list of
    spans. When an item is already a single clause it passes through intact.
    """
    out: list[str] = []
    for raw in _as_list(items):
        merged: list[str] = []
        for piece in _split_clause_spans(str(raw)):
            if merged and len(_tokenize(piece)) < min_span_tokens:
                merged[-1] = f"{merged[-1]} {piece}".strip()
            else:
                merged.append(piece)
        out.extend(p for p in merged if p.strip())
    seen: set[str] = set()
    unique: list[str] = []
    for span in out:
        key = " ".join(_tokenize(span))
        if key not in seen:
            seen.add(key)
            unique.append(span)
    return unique


def _presence_candidates(predicted: dict, category: str, field: str) -> list[str]:
    """Candidate predicted spans for one CUAD YES/NO category.

    Prefers spans routed explicitly by the extractor's reasoning trace
    (``reasoning.entries[]`` whose ``field`` is the canonical CUAD category
    name — issue #21 retag), falling back to the category's mapped field
    (e.g. ``cuad_clauses``): both the disaggregated spans and the raw items,
    so a model that quotes a multi-sentence clause as one item is not lost to
    sentence-level splitting. Disable routing with
    ``trace_knobs.reasoning_routes_presence``.
    """
    if get_settings().trace_knobs.reasoning_routes_presence:
        entries = (predicted.get("reasoning") or {}).get("entries") or []
        routed = [
            str(e.get("evidence") or e.get("section_ref") or "")
            for e in entries
            if str(e.get("field") or "").strip() == category
        ]
        if routed:
            return [r for r in routed if r.strip()]
    items = disaggregate_clause_spans(predicted.get(field))
    seen = set(items)
    for raw in _as_list(predicted.get(field)):
        text = str(raw)
        if text.strip() and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def _presence_matched(item: str, answer: str) -> bool:
    """Whether one predicted span covers the category's labeled clause.

    Matched when the labeled clause text is token-contained in the span at the
    verification coverage (0.7), or the embedding rescue raises the semantic
    similarity at the presence embedding threshold (0.7) — issue #21 fix #3.
    """
    if not answer or not item:
        return False
    if score_containment_field(item, answer) >= get_verification_coverage():
        return True
    if not embedding_enabled():
        return False
    embedding = _get_embedding()
    if embedding is None:
        return False
    try:
        sim = embedding.similarity(item, answer)
    except Exception:
        logger.warning("presence_embedding_similarity_failed", exc_info=True)
        return False
    return sim is not None and float(sim) >= get_presence_embedding_threshold()


def score_category_presence(predicted: dict | None, presence_expectations: dict,
                            field_types: dict[str, str]) -> tuple[float, dict]:
    """Binary YES/NO presence scoring for CUAD's presence-type categories.

    ``presence_expectations``: ``{category: {"expected": bool, "answer": str,
    "field": str}}``. Returns ``(score, detail)`` where ``score`` is the share
    of expected-True categories whose clause text is matched by a predicted
    span. A category is matched when ANY candidate span — the disaggregated
    items of the category's mapped field, or the reasoning-trace entry tagged
    with the canonical category name — covers the labeled clause by token
    containment or embedding similarity at the 0.7 threshold (issue #21)."""
    predicted = predicted or {}
    matched = 0
    expected_true = 0
    detail: dict[str, dict] = {}
    for category, expectation in sorted((presence_expectations or {}).items()):
        field = expectation.get("field") or "cuad_clauses"
        if not expectation.get("expected"):
            detail[category] = {"expected": False, "matched": None, "field": field}
            continue
        expected_true += 1
        answer = str(expectation.get("answer") or "")
        items = _presence_candidates(predicted, category, field)
        hit = any(_presence_matched(item, answer) for item in items)
        if hit:
            matched += 1
        detail[category] = {"expected": True, "matched": hit, "field": field,
                            "answer": answer, "predicted_items": len(items)}
    score = round(matched / expected_true, 4) if expected_true else 1.0
    return score, detail


# ---------------------------------------------------------------------------
# Embedding second signal (local sentence-transformers, remote OpenRouter
# embeddings fallback, lazy)
# ---------------------------------------------------------------------------

_REMOTE_EMBEDDING_MODEL = "openai/text-embedding-3-small"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class _EmbeddingMatcher:
    """Lazy singleton embedding cache. similarity() returns None whenever no
    embedder is available — callers then keep the string-only score."""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "_EmbeddingMatcher":
        """Return the singleton matcher, creating it under the class lock."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        """Initialize unloaded local and remote backends and an empty vector cache."""
        self._model = None
        self._model_loaded = False
        self._client = None
        self._vectors: dict[str, object] = {}

    def _load_local(self) -> None:
        """Attempt local model loading once, retaining None when loading fails."""
        if self._model_loaded:
            return
        self._model_loaded = True
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(get_embedding_model())
        except Exception:
            self._model = None

    def _load_remote(self) -> None:
        """Initialize the remote embedding client when an API key is available."""
        if self._client is not None:
            return
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=os.environ.get("OPENROUTER_BASE_URL", _OPENROUTER_BASE_URL),
                api_key=api_key, timeout=120,
            )
        except Exception:
            self._client = None

    def _embed(self, text: str):
        """Produce a unit-normalized local or remote embedding, or None without a backend."""
        import numpy as np

        if self._model is not None:
            vector = self._model.encode([text], normalize_embeddings=True)[0]
        else:
            self._load_remote()
            if self._client is None:
                return None
            resp = self._client.embeddings.create(
                model=_REMOTE_EMBEDDING_MODEL, input=[text]
            )
            vector = np.asarray(resp.data[0].embedding, dtype=np.float64)
            norm = float(np.linalg.norm(vector))
            vector = vector / norm if norm else vector
        return vector

    def similarity(self, a: str, b: str) -> Optional[float]:
        """Return cached embedding cosine clipped to [0, 1], or None on unavailability."""
        if not embedding_enabled():
            return None
        try:
            self._load_local()  # idempotent; sets self._model if available
            import numpy as np

            va = self._vectors.get(a)
            if va is None:
                va = self._embed(a)
                if va is None:
                    return None
                self._vectors[a] = va
            vb = self._vectors.get(b)
            if vb is None:
                vb = self._embed(b)
                if vb is None:
                    return None
                self._vectors[b] = vb
            sim = float(np.dot(va, vb))
            return min(1.0, max(0.0, sim))
        except Exception:
            return None


def _get_embedding() -> Optional[_EmbeddingMatcher]:
    """Return the shared embedding matcher when enabled, or None on failure."""
    if not embedding_enabled():
        return None
    try:
        return _EmbeddingMatcher.get()
    except Exception:
        return None


def embed_texts(texts: list[str]) -> Optional[list[list[float]]]:
    """Embed ``texts`` with the scorer's own model (unit-normalized vectors).

    The public handle on the embedding backend that ``similarity`` uses:
    the local SentenceTransformer named by ``get_embedding_model()`` when it
    loads, else the remote fallback. Vectors are cached per text for the
    process. Returns ``None`` when embeddings are disabled or no backend is
    available, or if any text fails to embed (fail-soft — callers skip the
    cosine signal rather than score with a partial batch).
    """
    matcher = _get_embedding()
    if matcher is None:
        return None
    try:
        matcher._load_local()
        out: list[list[float]] = []
        for text in texts:
            vector = matcher._vectors.get(text)
            if vector is None:
                vector = matcher._embed(text)
                if vector is None:
                    return None
                matcher._vectors[text] = vector
            out.append([float(x) for x in vector])
        return out
    except Exception:
        return None


_CMS_FACILITY_RE = re.compile(
    r"\bfacility\s+provider\s*(?:\b(?:id|identifier|number|no)\b)?[\s:#.-]*([a-z0-9]*\d[a-z0-9]*)"
)
_CMS_NPI_RE = re.compile(r"(?<![a-z0-9])(\d{10})(?![a-z0-9])")
_CMS_NDC_RE = re.compile(r"(?<![a-z0-9])(\d{9,11})(?![a-z0-9])")
_CMS_NDC_SEGMENTS_RE = re.compile(r"(?<![a-z0-9-])(\d{4,5})-(\d{3,4})-(\d{1,2})(?![a-z0-9-])")


def _cms_doc_signature(text) -> tuple[str, str]:
    """Classify one CMS supporting-document item as ``(kind, value)``.

    Identifier items compare as exact tokens: ``npi`` (10 digits), ``ndc``
    (11-digit 5-4-2 form: a hyphenated labelled NDC pads each segment, an
    unhyphenated one is left-padded) and
    ``facility_provider`` (alphanumeric id). Anything else is a descriptor
    (``HCPCS detail (1 codes)``) reduced to its normalized type label: letters
    only, count and ``code(s)`` words dropped.
    """
    raw = str(text or "").strip().lower()
    facility = _CMS_FACILITY_RE.search(raw)
    if facility:
        return "facility_provider", facility.group(1)
    if re.search(r"\bndc\b", raw):
        # A hyphenated 10-digit NDC (4-4-2, 5-3-2, 5-4-1) pads the short
        # segment, not the whole number, to reach the 11-digit 5-4-2 form.
        segmented = _CMS_NDC_SEGMENTS_RE.search(raw)
        if segmented:
            labeler, product, package = segmented.groups()
            return "ndc", labeler.zfill(5) + product.zfill(4) + package.zfill(2)
    squeezed = re.sub(r"(?<=\d)-(?=\d)", "", raw)
    if re.search(r"\bndc\b", squeezed):
        match = _CMS_NDC_RE.search(squeezed)
        if match:
            return "ndc", match.group(1).zfill(11)
    npi = _CMS_NPI_RE.search(squeezed)
    if npi:
        return "npi", npi.group(1)
    ndc = re.search(r"(?<![a-z0-9])(\d{11})(?![a-z0-9])", squeezed)
    if ndc:
        return "ndc", ndc.group(1)
    words = [w for w in re.sub(r"[^a-z]+", " ", raw).split() if w not in ("code", "codes")]
    return "descriptor", " ".join(words)


def score_cms_doc_ref(pred, exp, embedding=None) -> float:
    """Identifier-aware match of one CMS supporting-document item (1.0 or 0.0).

    Identifiers (NPI, NDC, facility provider id) must match as exact tokens of
    the same kind; descriptor items match by normalized type label, so
    ``HCPCS detail (2 codes)`` matches ``HCPCS detail (1 codes)``. Prose
    similarity never earns credit: a near-miss identifier is a different
    provider or drug.
    """
    pk, pv = _cms_doc_signature(pred)
    ek, ev = _cms_doc_signature(exp)
    if not pv or not ev:
        return 0.0
    return 1.0 if (pk, pv) == (ek, ev) else 0.0


# ---------------------------------------------------------------------------
# Dispatch + composite scoring
# ---------------------------------------------------------------------------

FIELD_SCORERS = {
    "cms_doc_ref": score_cms_doc_ref,
    "id": score_id_field,
    "date": score_date_field,
    "money": score_money_field,
    "name": score_name_field,
    "label": score_label_field,
    "free_text": score_free_text_field,
    "containment": score_containment_field,
}

# List-valued field types whose element scorer is specified as a suffix:
# "entity_list:name", "entity_list:free_text", ...
LIST_PREFIX = "entity_list"


def is_entity_list(field_type: str) -> bool:
    """Recognize the entity-list field type and its element-type suffix variants."""
    return field_type == LIST_PREFIX or field_type.startswith(LIST_PREFIX + ":")


def score_field(field_type: str, pred, exp, embedding=None, partial_gt: bool = False):
    """Score one field. Returns a float, or an EntityListScore for list fields."""
    if is_entity_list(field_type):
        element_type = field_type.split(":", 1)[1] if ":" in field_type else "name"
        return score_entity_list(element_type, pred, exp, embedding=embedding,
                                 partial_gt=partial_gt)
    scorer = FIELD_SCORERS.get(field_type, score_name_field)
    return scorer(pred, exp, embedding=embedding)


def _heuristic_field_type(field_name: str, value) -> str:
    """Fallback type inference for fields not mapped in the taxonomy."""
    if isinstance(value, list):
        return LIST_PREFIX
    name = field_name.lower()
    if "date" in name:
        return "date"
    if any(k in name for k in ("value", "amount", "fee", "compensation", "price",
                               "cost", "salary", "consideration", "total")):
        return "money"
    if any(k in name for k in ("number", "id", "docket", "reference", "filing")):
        return "id"
    return "name"


def get_field_types(doc_class: str, taxonomy: dict | None = None) -> dict[str, str]:
    """Field->scoring-type mapping for a doc class.

    Resolution order:
    1. Explicit ``taxonomy`` dict (``{"doc_classes": [{"key", "field_types"}]}``)
       when passed — the caller's own taxonomy wins.
    2. The wired taxonomy captured by ``configure_from_taxonomy()``
       (``Settings.doc_class_field_types``) when the consuming project wired
       once at import.
    3. ``{}`` when neither is available (no taxonomy configured).

    Returns {} when the class is absent. Extract aliases (currently none)
    resolve to their canonical class; ``merger_agreement`` is its own map.
    """
    from ..pipeline.mailroom import EXTRACT_CLASS_ALIASES

    resolved = EXTRACT_CLASS_ALIASES.get(doc_class, doc_class)
    if taxonomy:
        for cls in taxonomy.get("doc_classes", []):
            if cls.get("key") == doc_class or cls.get("key") == resolved:
                return dict(cls.get("field_types") or {})
        return {}
    wired = get_settings().doc_class_field_types
    return dict(wired.get(resolved) or wired.get(doc_class) or {})


@dataclass
class ExtractionScoreResult:
    """Per-document field scores, judge-review candidates, and list factuality audits."""
    doc_class: str
    field_scores: dict[str, float]
    overall_score: Optional[float]
    ambiguous_fields: list[str]
    entity_list_scores: dict[str, EntityListScore] = field(default_factory=dict)
    # Factuality audit per list field: {field: audit dict} with
    # verified_precision / hallucination_rate (see audit_list_field).
    entity_list_audit: dict[str, dict] = field(default_factory=dict)
    #: Captured confidence / reasoning knobs (never in ``field_scores``).
    trace: dict[str, Any] | None = None

    @property
    def needs_judge_review(self) -> bool:
        """Return whether any field score requires judge review."""
        return bool(self.ambiguous_fields)

    @property
    def audit_support(self) -> dict:
        """Canonical field-count factuality support (additive; serialization unchanged)."""
        from .field_support import field_audit_support

        return field_audit_support(self.entity_list_audit)

    @property
    def overall_verified_precision(self) -> Optional[float]:
        """Mean verified_precision across the row's scored list fields
        (None when no list field was audited)."""
        values = [a["verified_precision"] for a in self.entity_list_audit.values()
                  if a.get("n_predicted")]
        return round(sum(values) / len(values), 4) if values else None

    def to_dict(self) -> dict:
        """Serializable form (for manifests / experiment logs)."""
        return {
            "doc_class": self.doc_class,
            "field_scores": self.field_scores,
            "overall_score": self.overall_score,
            "ambiguous_fields": self.ambiguous_fields,
            "entity_list_scores": {
                k: v.to_dict() for k, v in self.entity_list_scores.items()
            },
            "entity_list_audit": self.entity_list_audit,
            "trace": self.trace,
        }


def score_extraction(
    doc_class: str,
    field_types: dict[str, str],
    predicted: dict | None,
    expected: dict | None,
    doc_text: str | None = None,
    *,
    audit_predicted: dict | None = None,
    cms_aware: bool = True,
) -> ExtractionScoreResult:
    """Score one extraction deterministically.

    ``cms_aware=False`` disables the CMS-row rules (#93) — for callers whose
    ``expected`` is not ground truth (the auditor compares two model outputs).

    - Only expected fields with a non-null/non-empty value count toward the
      overall score (null expectations are not requirements). Stringified
      JSON containers are parsed on both sides; empty containers and
      case-insensitive ``null`` / ``none`` / ``n/a`` / ``n.a.`` expectations
      are skipped. Trace and annotation keys are never scored; retired
      prompt keys require an explicit entry in ``field_types``.
    - ``overall_score`` is the mean of the per-field scores (None when no
      field is scored).
    - ``ambiguous_fields`` collects fields landing in the ambiguous band —
      the signal that escalates to the LLM judge.
    - List fields also produce ``entity_list_scores`` with precision/recall.
    - When verification is enabled and ``doc_text`` is nonempty, populated
      fields in ``field_types`` produce ``entity_list_audit`` entries,
      including scalar fields and fields absent from GT. Trace and
      annotation keys are excluded. ``audit_predicted``, when supplied,
      preserves predictions omitted from GT scoring for this audit.
    """
    had_prediction = bool(predicted)
    predicted = predicted or {}
    expected = expected or {}
    partial_gt_fields = get_partial_gt_fields()
    containment_fields = get_containment_fields()
    needs_embedding = any(
        ft in ("name", "free_text") or (is_entity_list(ft) and (ft.split(":", 1)[1] if ":" in ft else "name") in ("name", "free_text"))
        for ft in field_types.values()
    )
    embedding = _get_embedding() if needs_embedding else None

    field_scores: dict[str, float] = {}
    ambiguous: list[str] = []
    entity_list_scores: dict[str, EntityListScore] = {}
    entity_list_audit: dict[str, dict] = {}
    # CMS rows (expected carries a valid ``cms_source_table``) get the CMS-aware
    # fields: documented-absent adjuster / denial_reasons and identifier-aware
    # supporting_documents. Non-CMS rows keep the generic behaviour.
    cms_table = expected_cms_source_table(doc_class, expected) if cms_aware else None

    expected_items = list(expected.items())
    if cms_table is not None:
        # A CMS row whose GT omits a documented-absent key still penalises a
        # stated value, as the field-micro counts already do (a false
        # positive). Silence on an omitted key earns no credit: it is not
        # scored, so partial GT does not inflate the mean.
        expected_items += [
            (key, "") for key in CMS_DOCUMENTED_ABSENT_FIELDS
            if key not in expected
            and (not field_types or key in field_types)
            and not is_empty_value(parse_json_container(predicted.get(key)))
        ]

    for key, exp_value in expected_items:
        if key in NEVER_SCORED_FIELDS:
            continue
        if key in RETIRED_PROMPT_KEYS and key not in field_types:
            continue
        if is_unstated_cms_marker(key, cms_table, predicted):
            continue
        exp_value = parse_json_container(exp_value)
        if is_empty_value(exp_value):
            if cms_table is not None and key in CMS_DOCUMENTED_ABSENT_FIELDS:
                # Documented-absent on a CMS row: saying nothing is correct,
                # a stated value is a false positive. Never skipped.
                # No parsed prediction earns nothing (a null row must not
                # collect free credit for staying silent).
                if had_prediction:
                    absent_pred = parse_json_container(predicted.get(key))
                    if isinstance(absent_pred, (list, tuple)):
                        absent_pred = [i for i in absent_pred if not is_empty_value(i)]
                    field_scores[key] = 1.0 if is_empty_value(absent_pred) else 0.0
            continue
        field_type = (field_types.get(key)
                      or (CMS_ROW_FIELD_TYPES["cms_source_table"] if key == "cms_source_table"
                          else _heuristic_field_type(key, exp_value)))
        if cms_table is not None and key in CMS_ROW_FIELD_TYPES:
            field_type = CMS_ROW_FIELD_TYPES[key]
        if (doc_class == "insurance_claim" and key == "claim_type"
                and str(parse_json_container(predicted.get(key)) or "").strip().lower() in CMS_CLAIM_TYPES):
            # A CMS table token is never a product line (#93): exact label
            # scoring, so it earns no fuzzy credit even when the row was not
            # detected as CMS (no expected_subclass passed).
            field_type = "label"
        # Judge escalation uses the configured type's band, not the
        # containment override applied for scoring below.
        original_field_type = field_type
        pred_value = predicted.get(key)
        if pred_value is not None:
            pred_value = parse_json_container(pred_value)
        if field_type == "label" and doc_class:
            # Closed labels (0.28.0): fold aliases onto the scored token first, then
            # exact match. An unfoldable value is kept as written: published v9 gold
            # still carries off-vocabulary labels (urgency "low", intent "inform"),
            # and a prediction that repeats the gold verbatim matches it.
            exp_value = canonical_label(doc_class, key, exp_value) or exp_value
            if pred_value is not None:
                pred_value = canonical_label(doc_class, key, pred_value) or pred_value
        if doc_class == "insurance_claim" and key == "cms_source_table" and is_empty_value(pred_value):
            # Compatibility with the frozen insurance prompt, which reports the
            # table on ``claim_type``: when ``cms_source_table`` itself is blank
            # the table token is read from there for THIS field only. It earns
            # nothing on ``claim_type``, which scores the product line alone.
            token = str(predicted.get("claim_type") or "").strip().lower()
            pred_value = token if token in CMS_CLAIM_TYPES else None
        if pred_value is None:
            # A null answer satisfies a null-expectation date (blank-template
            # or label-only GT holds no real date).
            if (field_type == "date"
                    and _parse_date_parts(str(exp_value)) is None
                    and _date_expected_is_null(str(exp_value))):
                score = 1.0
            else:
                score = 0.0
        else:
            if key in containment_fields and field_type in ("name", "free_text", "containment"):
                field_type = "containment"
            result = score_field(field_type, pred_value, exp_value, embedding=embedding,
                                 partial_gt=key in partial_gt_fields)
            if isinstance(result, EntityListScore):
                result.field_name = key
                entity_list_scores[key] = result
                score = result.score
            else:
                score = result
        score = round(score, 4)
        field_scores[key] = score
        if field_is_ambiguous(original_field_type, score):
            ambiguous.append(key)

    if verification_enabled() and doc_text:
        # Factuality audit for EVERY content field the model populated —
        # including fields the ground truth does not label.
        audit_source = predicted if audit_predicted is None else audit_predicted
        for key, field_type in sorted(field_types.items()):
            pred_value = parse_json_container(audit_source.get(key))
            if is_empty_value(pred_value) or key in entity_list_audit:
                continue
            if key in NEVER_SCORED_FIELDS:
                continue
            if is_entity_list(field_type):
                element_type = field_type.split(":", 1)[1] if ":" in field_type else "name"
                entity_list_audit[key] = audit_list_field(
                    element_type, pred_value, expected.get(key) or [], doc_text,
                )
            else:
                entity_list_audit[key] = audit_scalar_field(
                    field_type, pred_value, expected.get(key), doc_text,
                )

    scored = list(field_scores.values())
    overall = round(sum(scored) / len(scored), 4) if scored else None
    from .trace_knobs import capture_trace_knobs

    return ExtractionScoreResult(
        doc_class=doc_class,
        field_scores=field_scores,
        overall_score=overall,
        ambiguous_fields=ambiguous,
        entity_list_scores=entity_list_scores,
        entity_list_audit=entity_list_audit,
        trace=capture_trace_knobs(predicted, expected=expected, correctness=overall),
    )
