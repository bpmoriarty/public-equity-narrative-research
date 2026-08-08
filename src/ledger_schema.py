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

import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


# A model producing structured JSON sometimes emits a unicode escape as LITERAL
# TEXT — the six characters \ u 2 0 1 9 — where the character ’ belongs. Found on
# real output: three of the first four verification failures in this project were
# this and nothing else, on quotes that were otherwise word-for-word exact.
#
# Decoding these is safe in the way that matters: it changes how a single
# character is spelled and cannot turn a paraphrase into a match. It is the same
# class of difference as a curly versus straight apostrophe, which this check
# already ignores for the reason given in the module docstring.
_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")

# Bare image filenames left in the text by HTML-to-text conversion, e.g.
# "investorquestions9262025003.jpg". These sit INSIDE sentences in some filings —
# the Workiva-generated exhibits from FY2024 onward are full of them — so a quote
# that a human would call verbatim contains no such token and the source does.
#
# This one is a self-inflicted failure worth naming: src/triage_8k.py strips these
# before sending text to the model, while verification runs against the untrimmed
# section. Trimming cannot make a bad quote pass, but it can make a good one fail,
# and it did. Removing the artifact on both sides is the fix.
_IMG = re.compile(r"\S+\.(?:jpg|jpeg|png|gif)\b", re.I)


def canon(s: str) -> str:
    """Normalize text for quote comparison. See the module docstring.

    Order matters: escapes are decoded FIRST, so a literal \\u2019 becomes ’ and is
    then folded to ' by the translation table below. Doing it the other way round
    would leave the escape intact.
    """
    s = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_QUOTES).translate(_DASHES)
    s = _IMG.sub(" ", s)
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
    # `departure_announced` is separate from `departed` because collapsing them
    # produces a dated event on a date nothing happened. An 8-K saying an executive
    # "informed the CEO that she has decided to depart in August" reports a decision
    # on the filing's date; the departure is a later, often different, date — and
    # frequently a date only a later amendment supplies. Recorded as one enum value,
    # the two become a single event the filings appear to date inconsistently, which
    # is how this distinction was found. See VERIFICATION.md D1 and
    # config/corrections.toml.
    change: Literal["appointed", "departed", "departure_announced",
                    "promoted", "role_changed", "other"]
    date: str | None = Field(
        default=None,
        description="ISO date if stated, else null. The date of THIS change: for "
                    "`departure_announced` that is the date the decision was "
                    "announced or communicated, NOT the departure date it names.")
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


class InvestorQaTopic(BaseModel):
    """One exchange in a Reg FD investor Q&A filing.

    KEPT IN ITS OWN LEDGER FIELD, not folded into `strategic_priorities` or
    `events`. A 10-K statement and a Reg FD answer are both management's words, but
    they are not the same kind of evidence: the 10-K is a considered annual
    disclosure reviewed by counsel, and this is a monthly reply to whatever
    investors happened to ask. Mixing them would let an output cite an off-hand
    answer with the same authority as an audited filing, and nothing downstream
    could tell them apart. Separate field, so any output can weight or exclude
    this material as a class.
    """
    topic: str = Field(description="What the question was about, in the filing's own terms.")
    stated_position: str = Field(
        description="What management said, in its own phrasing. Not summarized into "
                    "neutral language — the wording is the point.")
    kind: Literal["strategy", "capital_allocation", "segment_or_product",
                  "acquisition_or_divestiture", "governance_or_management",
                  "competition_or_market", "other"]
    quote: str = QUOTE_FIELD


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


class InvestorQaFacts(BaseModel):
    """Deliberately has NO `events` list.

    These filings do announce transactions sometimes, and the temptation is to
    collect events here too. But src/triage_8k.py already routes any filing with a
    material signal to the events path, and the 10-K's MD&A independently covers
    every transaction in this window. Adding events here would produce a third
    account of the same acquisition, sourced to the weakest of the three
    documents, and someone would eventually cite it.
    """
    topics: list[InvestorQaTopic]
    notable_language: list[NotableLanguage]


# ---------------------------------------------------------------------------
# Fact identifiers
# ---------------------------------------------------------------------------
#
# WHY FACTS NEED IDS
# ------------------
# Without one, the most specific thing an output can cite is
# `(form, fiscal_year, accession)` — which identifies a FILING, not a fact. For an
# 8-K carrying 40 investor-Q&A facts, that citation means "somewhere in this
# document", and no automated check can tell whether the claim matches its source.
# An id makes the citation exact, so verifying an output becomes a lookup rather
# than a reading exercise. Same principle as `verify_quote`: measure traceability
# instead of asserting it.
#
# WHAT MAKES A FACT THE SAME FACT
# -------------------------------
# The id is a hash of the claim, the evidence, and where the evidence lives:
#
#   IN   field, fiscal_year, value, source form/accession/section_key, quote
#   OUT  confidence, confidence_reason, quote_verified, quote_check, filing_date
#
# The asymmetry is the whole design. JUDGMENTS ABOUT a fact do not change its
# identity; the fact's CONTENT and EVIDENCE do.
#
# Concretely: if the `DEF14A_director_bios` boundaries are fixed later, 51 board
# facts flip from `low` to `high` confidence. Were confidence in the hash, every
# one of those ids would change and every citation to them in an already-written
# brief would break — for a change that made those facts MORE trustworthy, not
# different. Conversely a changed `quote` SHOULD mint a new id, because the
# evidence moved and anything citing it needs re-checking.
#
# `filing_date` is excluded because it comes from the inventory rather than from
# the fact: correcting a filing date should not churn the ids of facts that did
# not change.
#
# `fiscal_year` is passed separately rather than read from `source` because a fact
# whose quote could not be verified has NO source, and two such facts with
# identical text in different years must not collide.

ID_HEX = 8  # 32 bits. Collisions are checked for at build time, never assumed away.

# Short prefixes so a citation is legible in prose and an obviously wrong one — a
# QA id supporting a segment claim — is visible to a human reader, not just to the
# checker. Redundant with the hash by design.
FIELD_CODES: dict[str, str] = {
    "strategic_priorities": "SP",
    "segments": "SEG",
    "headcount": "HC",
    "leadership": "LEAD",
    "board": "BRD",
    "incentive_metrics": "INC",
    "vote_results": "VOTE",
    "events": "EVT",
    "notable_language": "LANG",
    "investor_qa": "QA",
}


def _digest(payload: dict) -> str:
    """Stable short hash of a payload.

    `sort_keys=True` is what makes it stable: without it, two runs that built the
    same dict in a different insertion order would produce different ids, and the
    ledger would stop being idempotent in a way that is very hard to see.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:ID_HEX]


def fact_id(field: str, fiscal_year: int, value: dict,
            source: FactSource | None, quote: str) -> str:
    """The citable id for one ledger fact, e.g. `EVT-FY2023-3f9c1d2a`."""
    return "{}-FY{}-{}".format(
        FIELD_CODES.get(field, field.upper()[:4]),
        fiscal_year,
        _digest({
            "field": field,
            "fiscal_year": fiscal_year,
            "value": value,
            "form": source.form if source else None,
            "accession": source.accession if source else None,
            "section_key": source.section_key if source else None,
            "quote": quote,
        }),
    )


# Keys on a risk delta that MEASURE it rather than identify it. Everything else on
# the item is identity and enters the hash.
#
# Named as an exclusion list rather than naming the identity keys, because the
# three delta categories have three different shapes: `added`/`removed` carry
# `heading` + `category`, `unchanged` carries `heading`, and `reworded` carries
# `heading_now` / `heading_prior` / `category_now` / `category_prior`. Enumerating
# identity keys means missing one — which is exactly the bug this list replaced,
# where naming `heading` alone gave every reworded delta a `None` heading and 46
# of them the same id.
#
# The exclusion direction is also the safer failure. A new MEASUREMENT key that
# nobody adds here makes ids churn on a re-run: annoying and immediately visible. A
# new IDENTITY key missing from an include-list makes two different deltas collide:
# silent, and the thing citations cannot survive.
RISK_DELTA_MEASUREMENT_KEYS = frozenset({
    "id",                  # the id itself, obviously
    "heading_similarity",  # rapidfuzz scores — a version bump must not renumber
    "body_similarity",     #   every citation in an already-written output
    "body_chars",
    "changed",             # derived from the two similarity scores above
})


def risk_delta_id(fiscal_year: int, category: str, item: dict, source: dict) -> str:
    """The citable id for one risk-factor delta, e.g. `RISK-FY2024-b1c07e4f`.

    Risk deltas are not `LedgerFact`s — they come from the deterministic diff in
    src/risk_diff.py and carry no quote. They still need ids, because an output
    will say "the cybersecurity risk factor was reworded in FY2024" and a checker
    that cannot resolve that claim leaves a whole category of statement
    unverifiable. One unverifiable category is enough to make the check
    decorative.

    Identity is the year, the delta category, the two filings compared, and every
    non-measurement key on the item itself.
    """
    return "RISK-FY{}-{}".format(
        fiscal_year,
        _digest({
            "kind": "risk_delta",
            "fiscal_year": fiscal_year,
            "delta_category": category,
            "item": {k: v for k, v in item.items()
                     if k not in RISK_DELTA_MEASUREMENT_KEYS},
            "accession": (source or {}).get("accession"),
            "prior_accession": (source or {}).get("prior_accession"),
        }),
    )


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
    # Assigned by the validator below, never by the caller. See `fact_id`.
    id: str = ""
    field: str
    # A fact's own year, carried here rather than read from `source`, because the
    # three facts whose quotes could not be verified have no source at all — and so
    # had no way to say which year they belonged to.
    fiscal_year: int
    value: dict
    source: FactSource | None = None
    confidence: Confidence
    confidence_reason: str | None = None
    quote: str
    quote_verified: bool
    quote_check: str
    # Set when config/corrections.toml changed this fact's value. Deliberately NOT
    # part of the id hash — see `fact_id`, which hashes the claim, its evidence and
    # its source. The correction changes the claim, so the id changes anyway; what
    # must not happen is the record of the correction becoming part of the identity,
    # because then rewording the `reason` would renumber the fact.
    correction: dict | None = None

    @model_validator(mode="after")
    def _assign_id(self) -> "LedgerFact":
        """Derive the id from the fact itself.

        Done here rather than at each call site so it cannot be forgotten: a
        `LedgerFact` that exists has an id, structurally. An id supplied by the
        caller is preserved, which is what lets a ledger be re-read from disk
        without every id being silently recomputed (and possibly changed) on load.
        """
        if not self.id:
            self.id = fact_id(self.field, self.fiscal_year, self.value,
                              self.source, self.quote)
        return self


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
    # Reg FD investor Q&A. Its own field on purpose — see InvestorQaTopic. Empty
    # for a year whose triage found no Q&A filings, which is a real possibility:
    # this is voluntary disclosure and a company can simply stop.
    investor_qa: list[LedgerFact]
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
    "investor_qa": InvestorQaFacts,
}
