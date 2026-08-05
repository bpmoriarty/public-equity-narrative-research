"""Ledger schema, and the grounding check that enforces traceability.

Two jobs:

1. DEFINE the shape of every extracted fact (SPEC.md section 3), as Pydantic
   models. The Anthropic SDK turns these into a JSON schema and constrains the
   model's response to it, so a malformed extraction fails at the API boundary
   instead of flowing into the ledger and being discovered three stages later.

2. ENFORCE the traceability rule mechanically. CLAUDE.md: "Every claim in every
   output must trace back to a specific filing... If something can't be sourced,
   it doesn't go in."

---------------------------------------------------------------------------
WHY EVERY EXTRACTED ITEM CARRIES A VERBATIM QUOTE
---------------------------------------------------------------------------
A model asked for a citation will always produce something citation-shaped. The
failure that matters is not a missing source, it is a *plausible* source for a
claim the filing never made — a paraphrase that drifted, a number attached to the
wrong year, a priority the model knows Morningstar has but this filing did not
state. Nothing downstream can distinguish that from a real extraction.

So every item must carry `quote`: an exact span of the section text it came from.
`verify_quote` then checks the quote actually occurs in that text. This converts
traceability from something the model asserts into something the pipeline tests.
A quote that does not appear is not evidence of a lie — it is usually a stitched
paraphrase — but it is exactly as unusable, and it gets marked as such rather
than silently trusted.

The check is whitespace-insensitive and quote-character-insensitive by design.
Filing HTML produces irregular spacing and curly punctuation that survives into
the section text, and a model reproducing a span will normalize it. Rejecting a
correct quote over a straight vs. curly apostrophe would train us to ignore the
check, which is worse than not having it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

Confidence = Literal["high", "low"]

# Which section a fact came from decides its starting confidence. Recorded here,
# in code, rather than left to prose in DATA.md, so the ledger cannot quietly
# disagree with the documented limitation.
#
# See the KNOWN LIMITS block in src/extract_sections.py: every 10-K section and
# the proxy CD&A and incentive tables have hand-verified boundaries; the two
# remaining proxy sections do not, and anything drawn from them is `low`.
LOW_CONFIDENCE_SECTIONS = {
    "DEF14A_director_bios":
        "boundary unverified: FY2025 is known to start at the front-of-proxy "
        "voting summary rather than the director biographies, and the other years "
        "are unchecked",
    "DEF14A_proposals_and_votes":
        "boundary unverified: FY2022 was checked and is correct at 6,883 chars, so "
        "the other years at 21k-25k are likely over-capturing",
}


def confidence_for(section_key: str, quote_verified: bool) -> tuple[Confidence, str | None]:
    """Confidence of a fact, and the reason when it is not `high`.

    Two independent ways to be low-confidence, and both are recorded:
      - the section it came from has an unverified boundary
      - its quote could not be found in the source text
    """
    reasons = []
    if section_key in LOW_CONFIDENCE_SECTIONS:
        reasons.append(LOW_CONFIDENCE_SECTIONS[section_key])
    if not quote_verified:
        reasons.append("quote not found verbatim in the source section, so this item "
                       "is a paraphrase rather than a traceable citation")
    if reasons:
        return "low", "; ".join(reasons)
    return "high", None


# ---------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("‚"): "'",
           ord("“"): '"', ord("”"): '"', ord("„"): '"',
           ord(" "): " "}


def canon(s: str) -> str:
    """Normalize text for quote comparison. See the module docstring."""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_QUOTES).translate(_DASHES)
    return re.sub(r"\s+", " ", s).strip().lower()


# A quote may pick up a stray character or two from the generator without ceasing
# to be a verbatim citation. Accept a near-miss when the ONLY difference is a
# trailing tail no longer than this.
#
# An ABSOLUTE character count, not a percentage. A percentage sounds more
# principled and behaves worse: at 99%, two stray characters are forgiven on a
# 260-character quote and rejected on a 64-character one, so the same artifact
# passes or fails depending on how much was quoted around it. The artifact is a
# fixed handful of characters either way.
#
# Three is safe rather than lenient, because a paraphrase does not diverge at the
# very end — it diverges the moment the wording changes. Measured against
# deliberately constructed near-misses, the unmatched tail was 31 characters for a
# paraphrased ending, 23 for a half-invented one, and 43 for a quote stitched
# together from two separate passages. The real artifact this exists for was 2.
NEAR_MISS_TAIL_CHARS = 3


def _longest_matching_prefix(q: str, hay: str) -> int:
    """Length of the longest prefix of `q` that occurs in `hay`. Binary search."""
    lo, hi = 0, len(q)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if q[:mid] in hay:
            lo = mid
        else:
            hi = mid - 1
    return lo


def verify_quote(quote: str, source_text: str,
                 min_chars: int = 25) -> tuple[bool, str, str]:
    """Does `quote` occur in `source_text`? Returns (ok, reason, verified_span).

    `verified_span` is the part of the quote actually found in the source — equal
    to the quote on an exact match, and the matching prefix on an accepted
    near-miss. The ledger stores that, so what it holds is always something the
    filing demonstrably contains.

    A very short quote is rejected outright: a six-word fragment occurs in almost
    any filing by chance, so it would pass while providing no real traceability.
    The floor is what makes a passing check mean something.
    """
    q, hay = canon(quote), canon(source_text)
    if len(q) < min_chars:
        return False, f"quote too short to be evidence ({len(q)} < {min_chars} chars)", ""
    if q in hay:
        return True, "verbatim match", quote

    # Not exact. Distinguish a generation artifact from a paraphrase by WHERE it
    # diverges, not by whether it diverges.
    n = _longest_matching_prefix(q, hay)
    tail, ratio = len(q) - n, n / len(q)
    if n >= min_chars and tail <= NEAR_MISS_TAIL_CHARS:
        # Recover the span from the RAW quote so the stored citation stays
        # readable. Indexing the raw string by the canonical prefix length would
        # be wrong — canon() collapses runs of whitespace, so the two indexes
        # drift apart. Trim raw characters off the end instead, and stop at the
        # first length whose canonical form the source actually contains.
        trimmed = quote
        while trimmed and canon(trimmed) not in hay:
            trimmed = trimmed[:-1]
        trimmed = trimmed.rstrip()
        return (True,
                f"verbatim after dropping {tail} trailing character(s) "
                f"({ratio:.1%} exact) — generation artifact, not a paraphrase",
                trimmed)
    if ratio >= 0.25:
        return (False,
                f"diverges after {n} of {len(q)} characters ({ratio:.0%}) — the opening "
                "is real but the rest is paraphrased or stitched from elsewhere", "")
    return False, "not found in the source section", ""


# ---------------------------------------------------------------------------
# Extracted facts.  Every one carries a quote; see the module docstring.
# ---------------------------------------------------------------------------

QUOTE_FIELD = Field(
    description="An EXACT, verbatim, contiguous span copied from the provided "
                "document text that supports this item. At least 25 characters. "
                "Do not paraphrase, join separated passages, fix typos, or add "
                "ellipses — this is checked against the source automatically and "
                "an item whose quote is not found is marked unreliable."
)


class Priority(BaseModel):
    text: str = Field(description="The stated strategic priority, in management's own phrasing.")
    quote: str = QUOTE_FIELD


class Segment(BaseModel):
    name: str = Field(description="Reportable segment or business line name, exactly as named.")
    note: str | None = Field(
        default=None,
        description="Only if the document states it: renamed from X, newly created, "
                    "combined with Y, discontinued. Null if the document says nothing.")
    quote: str = QUOTE_FIELD


class Headcount(BaseModel):
    value: int | None = Field(
        default=None,
        description="Total employees as a plain integer, if the document gives a "
                    "specific number. Null if it gives only an approximation or "
                    "no figure at all.")
    as_stated: str = Field(description="How the document expresses it, e.g. "
                                       "'approximately 11,000 employees worldwide'.")
    quote: str = QUOTE_FIELD


class LeadershipChange(BaseModel):
    name: str
    role: str = Field(description="The role involved.")
    change: Literal["appointed", "departed", "promoted", "role_changed", "other"]
    date: str | None = Field(default=None, description="ISO date if stated, else null.")
    stated_reason: str | None = Field(
        default=None,
        description="The reason the DOCUMENT gives. Null if it gives none — most "
                    "departures are announced without a reason, and 'none stated' "
                    "is a real and useful finding. Never infer one.")
    quote: str = QUOTE_FIELD


class BoardMember(BaseModel):
    name: str
    role: str | None = Field(default=None, description="e.g. Chair, Lead Independent Director.")
    director_since: str | None = Field(default=None, description="Year, if stated.")
    committees: list[str] = Field(default_factory=list)
    quote: str = QUOTE_FIELD


class IncentiveMetric(BaseModel):
    metric: str = Field(description="What is measured, e.g. 'consolidated revenue', "
                                    "'adjusted operating income'.")
    plan: str | None = Field(default=None, description="Which plan it belongs to, "
                                                       "e.g. annual bonus, long-term incentive.")
    weight: str | None = Field(default=None, description="Weighting as stated, e.g. '50%'. "
                                                          "Null if not stated.")
    target_or_range: str | None = Field(default=None, description="Target, threshold or "
                                                                   "payout range, if stated.")
    quote: str = QUOTE_FIELD


class Event(BaseModel):
    type: Literal["acquisition", "divestiture", "restructuring", "impairment",
                  "financing", "leadership_transition", "segment_change",
                  "guidance_change", "other"]
    description: str
    date: str | None = Field(default=None, description="ISO date if stated, else null.")
    quote: str = QUOTE_FIELD


class NotableLanguage(BaseModel):
    quote: str = QUOTE_FIELD
    why_notable: str = Field(description="Why this phrasing is worth attention: a shift "
                                          "in emphasis, an unusually direct admission, a "
                                          "hedge, a claim that recurs across years.")


class VoteResult(BaseModel):
    matter: str = Field(description="What was voted on, e.g. 'advisory vote on executive "
                                     "compensation', 'ratification of KPMG'.")
    votes_for: int | None = None
    votes_against: int | None = None
    abstentions: int | None = None
    broker_non_votes: int | None = None
    outcome: str = Field(description="What the document says the result was, e.g. "
                                      "'approved on an advisory basis'.")
    quote: str = QUOTE_FIELD


# ---------------------------------------------------------------------------
# Per-task response models.  One per extraction task in src/extract_facts.py.
#
# Deliberately narrow: each task sees one source and answers only what that
# source can support. A single all-fields model per year would invite the model
# to fill a field from the wrong document, and would not fit in one response.
# ---------------------------------------------------------------------------

class BusinessFacts(BaseModel):
    strategic_priorities: list[Priority]
    segments: list[Segment]
    headcount: Headcount | None = None


class MdnaFacts(BaseModel):
    events: list[Event]
    segment_changes: list[Segment]
    notable_language: list[NotableLanguage]


class CompFacts(BaseModel):
    incentive_metrics: list[IncentiveMetric]
    notable_language: list[NotableLanguage]


class BoardFacts(BaseModel):
    board_size: int | None = Field(default=None, description="Number of directors, if stated.")
    members: list[BoardMember]
    committees: list[str] = Field(default_factory=list,
                                  description="Standing committee names.")


class LetterFacts(BaseModel):
    strategic_priorities: list[Priority]
    notable_language: list[NotableLanguage]


class EightKFacts(BaseModel):
    leadership: list[LeadershipChange]
    events: list[Event]


class VoteFacts(BaseModel):
    results: list[VoteResult]


class FactSource(BaseModel):
    """Where a fact came from. Carried on every fact, per CLAUDE.md Traceability.

    The section key is resolved by finding which of the task's sources actually
    contains the fact's quote, not by asking the model where it looked — so the
    attribution is a measured property of the text rather than a claim about it.
    """
    form: str
    fiscal_year: int
    accession: str
    section_key: str
    filing_date: str


class LedgerFact(BaseModel):
    """One fact in the ledger: the payload, its source, and how far to trust it."""
    field: str
    value: dict
    source: FactSource | None = None
    confidence: Confidence
    confidence_reason: str | None = None
    quote: str
    quote_verified: bool
    quote_check: str


class YearLedger(BaseModel):
    """One fiscal year. SPEC.md section 3, plus per-fact confidence.

    SPEC.md invites adjustment — "adjust if the filings demand it, but keep every
    field sourced" — and confidence is exactly that: the two proxy sections with
    unverified boundaries would otherwise contribute facts indistinguishable from
    the hand-verified ones.
    """
    fiscal_year: int
    ticker: str
    cik: str
    company_name: str
    filings: list[dict]
    earnings_release_dates: list[str]
    strategic_priorities: list[LedgerFact]
    segments: list[LedgerFact]
    headcount: list[LedgerFact]
    leadership: list[LedgerFact]
    board: list[LedgerFact]
    incentive_metrics: list[LedgerFact]
    vote_results: list[LedgerFact]
    events: list[LedgerFact]
    notable_language: list[LedgerFact]
    # Null with a reason when it cannot be computed — never empty, which would
    # read as "nothing changed". See src/risk_diff.py.
    risk_deltas: dict | None
    data_quality: dict


TASK_MODELS: dict[str, type[BaseModel]] = {
    "business": BusinessFacts,
    "mdna": MdnaFacts,
    "comp": CompFacts,
    "board": BoardFacts,
    "letter": LetterFacts,
    "events_8k": EightKFacts,
    "votes": VoteFacts,
}
