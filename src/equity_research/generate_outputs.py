"""Milestone 5e — write `narrative-brief.md` and `discussion-points.md` from the pack.

The first stage in milestone 5 that spends money. Two model calls, sharing one
cached prompt prefix.

Run it:
    uv run python -m equity_research.generate_outputs --estimate     # cost, no spend
    uv run python -m equity_research.generate_outputs                # both documents
    uv run python -m equity_research.generate_outputs --only brief   # one of them

Writes:
    output/narrative-brief.md      deliverable 2 of 3
    output/discussion-points.md    deliverable 3 of 3
    data/pack/gen-<slug>.json      the raw response, usage and provenance

---------------------------------------------------------------------------
WHY THESE TWO NEED A MODEL AND `timeline.md` DID NOT
---------------------------------------------------------------------------
`timeline.md` is a reordering of fields that already exist, so a renderer does it
without risk. These two are the opposite: SPEC.md §4a asks for "analysis, not
summary" and §4c for "patterns visible across the five years that aren't visible
in any single filing." Nothing in the ledger holds a cross-year pattern — the
ledger is per-year by construction. That reading is the work, and it is the one
thing here worth paying a model to do.

What the model is NOT trusted with is evidence. Every sentence has to carry ids
that resolve in the pack, quotations may only be copied from `quote` fields, and
`check_citations` below re-reads the finished document and resolves every id
against `index.json`. An unresolvable id is caught here, not by a reader.

---------------------------------------------------------------------------
THE CACHE, AND WHY THE ORDER OF THE PROMPT MATTERS
---------------------------------------------------------------------------
Prompt caching hits only on a byte-identical PREFIX. So the shared material — the
system prompt and the whole 353k-token pack — goes first and carries the cache
breakpoint; everything that differs between the two documents goes after it. The
two parts are handed to the backend as separate arguments for exactly that
reason: glue them together at the call site and the breakpoint has nowhere to go.

That is the only reason `pack.json` contains no timestamp (see src/equity_research/build_pack.py):
a single varying byte anywhere in the prefix turns a $0.18 read back into a $1.77
call, with nothing looking broken except the bill.

Measured break-evens for this payload: a 5-minute cache write costs 1.25x input
price and repays itself from 1.4 reads on; a 1-hour write costs 2.0x and repays
from 2.2. Two documents back to back is only 2 reads, so on paper the 5-minute
TTL wins — but a high-effort call over a pack this size can take longer than five
minutes to return, and when it does the second call pays a fresh write instead of
a read. `[llm] cache_ttl` is therefore "1h": paying 2.0x for a read that happens
beats paying 1.25x twice for one that does not.

ALL OF WHICH APPLIES TO THE API BACKEND ONLY. Claude Code cache-WRITES every
prompt at 1h TTL, bills it at 2x input, and never reads user content back — two
calls sending a byte-identical 60KB prefix seconds apart produced identical usage
and identical cost. No ordering avoids it, which is why `--estimate` prices the
two engines with different arithmetic rather than the same numbers under a
different heading.

---------------------------------------------------------------------------
NEITHER REPAIR PASS RESENDS THE PACK
---------------------------------------------------------------------------
Both documents are held to their evidence after they are written: every id must
resolve in the pack index, every quotation must be verbatim in a fact cited
beside it. Both repairs run as SELF-CONTAINED calls carrying the document plus
the specific evidence in question, and neither carries the pack.

The id repair used to be a second turn in the generation conversation, which is
the cheapest possible shape on the API and does not survive on a seat: `--resume`
re-writes the whole conversation at 2x and reads nothing back, so the resumed
turn cost MORE than the original. See the note above `repair_ids` for what
replaced it, and — the part worth reading before changing it — what that gives up.

---------------------------------------------------------------------------
THE SECOND CALL SEES THE FIRST DOCUMENT
---------------------------------------------------------------------------
`discussion-points.md` is given `narrative-brief.md` and told not to restate it.
Without that the two documents overlap heavily — they read the same evidence for
related purposes — and the analytical output is the one that suffers, because its
value is entirely in what is NOT already obvious from the brief.

The brief goes in as a PRIOR DRAFT, explicitly not as evidence: it may not be
cited, and any claim it makes has to be re-sourced from the pack to be repeated.
It is appended after the cache breakpoint, so it costs a few thousand tokens and
does not disturb the cached prefix.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from equity_research import model_client, settings
from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
#
# Bound HERE, above the path constants below, and not with the other
# equity_research imports further down: this module interleaves imports with
# module-level constants, so a binding placed after the last import would sit
# below the PACK_DIR/OUT_DIR lines that use it.
P = paths()

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ROOT comes from _bootstrap (imported above), which also injects the Windows
# cert store and loads .env — see that module for why both live in one place.
PACK_DIR = P.pack
OUT_DIR = P.output
CORRECTIONS = P.corrections_toml

# Prices live in settings.MODEL_PRICES, with a PRICES_AS_OF date. They describe
# the vendor's price list rather than this company, which is why they are in code
# and not config -- but they were spelled out here AND in extract_facts.py AND in
# six format strings in build_pack.py, so "in code" had come to mean "in three
# places". See `cost()` below.

# Any id the pack can mint: field code, fiscal year, 8 hex characters. Built from
# the same code table the ids are built from, so a new field cannot be minted in
# ledger_schema.py and silently become uncheckable here.
from equity_research.ledger_schema import FIELD_CODES, ID_HEX, canon

ID_RE = re.compile(
    r"\b(?:" + "|".join(sorted({*FIELD_CODES.values(), "RISK"})) + r")"
    r"-FY\d{4}-[0-9a-f]{" + str(ID_HEX) + r"}\b")


# ---------------------------------------------------------------------------
# The rules, shared by both documents — and therefore inside the cached prefix
# ---------------------------------------------------------------------------

SYSTEM = """\
You write research documents from a fixed evidence pack of SEC filing extractions, \
for an equity analyst who will use the document in a professional discussion about \
the company and who will check your citations against the pack.

Six rules, all absolute.

1. THE PACK IS THE ONLY SOURCE. Every statement must rest on a fact in the pack. You \
may know things about this company and its industry from elsewhere; none of it may \
appear, however obviously true. If the pack does not support a statement, the \
statement does not go in. A gap in the pack is a finding to report, never something \
to fill.

2. EVERY FACTUAL SENTENCE CARRIES ITS IDS in square brackets, copied character for \
character from the pack: [EVT-FY2023-3f9c1d2a]. Put several ids in one bracket pair \
when several facts support the sentence. An id you cannot see in the pack is a \
fabrication — drop the sentence rather than approximate the id. An analytical \
sentence that draws a conclusion from facts cited nearby does not need its own \
citation; a sentence asserting something about the company does.

3. QUOTE ONLY FROM `quote` FIELDS, AND ONLY CHARACTER FOR CHARACTER. Any text inside \
quotation marks must be copied from the `quote` field of a fact you cite in the same \
sentence. `claim` is a model-written summary that was never checked against the \
filing — reason from it, but never reproduce it as the company's words. Facts marked \
`quote_unverified` have no verified text at all and must not be quoted.

   Every quotation in your document will be checked character for character against \
the verified text of the facts you cite beside it. The two ways this fails are both \
easy to commit and impossible to see afterwards:

   - RECONSTRUCTING FROM MEMORY. You will remember the sense of a phrase read far \
back in the pack and write it out slightly differently. "low 20's percent range" \
becomes "low 20 percent range"; "our most vulnerable segment" becomes "the most \
vulnerable segment". One word is enough to make it a misquotation.
   - QUOTING A PHRASE THAT IS NOT THERE. A striking phrase that captures what a fact \
means is not thereby in the filing. If you cannot see the exact characters in a \
`quote` field, there is no quotation to make.

   So: go back and look at the `quote` field before you type the closing quotation \
mark. If the phrasing you want is not there verbatim, drop the quotation marks and \
paraphrase — an unquoted paraphrase with a citation is honest and costs the sentence \
almost nothing. A quotation that is one word off is worse than no quotation, because \
it reads as the company's words and is not.

4. THE `constraints` BLOCK IS BINDING, not advisory. Each constraint states the data \
it was derived from. Read it before you write and satisfy every one.

5. CALIBRATE LANGUAGE TO THE EVIDENCE. Write "the filings state", "is consistent \
with", "management describes" — not "proves", "drives", "clearly shows" — unless the \
pack genuinely establishes causation, which it almost never will. Scope claims to \
what was actually read: these are SEC filings across five fiscal years, not the \
company itself. Where filings contradict each other or leave something ambiguous, \
say so explicitly and give both readings; never pick one silently. Distinguish what \
management SAYS from what the filings SHOW.

6. NO FILLER. No preamble, no restating the assignment, no summary of the summary, \
no "in conclusion". Do not describe filings as filings — "in its FY2022 10-K the \
company stated that" is wasted words; the citation already says that. An analyst \
should learn something from every line."""


PACK_PREAMBLE = """\
The evidence pack follows as a single JSON object. Read `how_to_use` and \
`constraints` first; they govern everything below them.

=== EVIDENCE PACK ===
"""


# ---------------------------------------------------------------------------
# The two asks — after the cache breakpoint, because they differ
# ---------------------------------------------------------------------------

BRIEF_ASK = """\
=== END OF EVIDENCE PACK ===

Write `narrative-brief.md`: prose, {lo:,}-{hi:,} words excluding the bracketed \
citations. Read once, understand this company's arc across {first}-{last}.

Structure it with these four `##` headings, in this order:

## Where {ticker} stood at the start of the window
Position, stated strategy, leadership and segment structure as the earliest filings \
in the pack describe them. This is the baseline everything after is measured against, \
so be concrete and short.

## The arc
The substance of the document, and the reason it exists. How strategy, structure and \
leadership changed across the window, and what the filings themselves offer as the \
reason for each shift. Organise by THEME, not by year — a year-by-year walk is a \
summary, and this is not one. Where the filings give no reason for a change, say that \
the reason is not stated rather than supplying one.

## Where it stands now
Current strategic position, the priorities management states most recently, and the \
risks management itself emphasises — use the `risk_deltas` for the last comparison in \
the window, since a risk factor management newly added is a risk management chose to \
start disclosing.

## What the filings raise but do not answer
Specific gaps. Not "the filings do not discuss competition" unless you checked; \
questions that arise from something the pack DOES contain and leaves hanging.

Write it as analysis. "Segment reporting changed and the new structure separates X \
from Y, which suggests Z" is analysis; "in 2023 the company changed its segments" is \
a summary. Say what changed and what it appears to indicate, with the evidence \
attached.

Return the finished Markdown and nothing else — no preamble, no commentary about \
your process, no closing note. Do not include a title line; one is added \
automatically. Start with the first `##` heading."""


DISCUSSION_ASK = """\
=== END OF EVIDENCE PACK ===

Write `discussion-points.md`: the analytical output of this pipeline, and the \
document that has to earn its place. It is read by someone preparing to talk to this \
company's management.

Three `##` sections, in this order.

## Observations
Patterns visible across {first}-{last} that are NOT visible in any single filing. \
Emphasis that shifted, language that changed meaningfully, themes that recur \
unresolved, gaps between what is stated in one place and what appears in another. \
Each observation is a `###` heading that states the observation itself — not a topic \
label — followed by the evidence and what it appears to indicate. A pattern needs at \
least two years of evidence to be a pattern; if it rests on one filing, it belongs in \
open questions instead.

## Open questions
Specific, substantive questions the filings raise and do not answer. The test each \
must pass: it should be answerable ONLY by someone inside the company, and it should \
be obvious from the question that the filings were read closely. "What is the \
strategy for AI?" fails both. Give each question the evidence that prompts it, with \
citations, so the reader can see why it is worth asking.

## What management appears to prioritise
The most useful section in the document. Infer priorities from three independent \
sources of evidence and name which one each inference rests on:
  - `incentive_metrics` — what specifically pays out, at what weighting, on what \
targets. This is what the company pays for.
  - repeated language across the shareholder letters and `notable_language` — what \
management chooses to emphasise in its own voice.
  - capital allocation visible in `events` and the timeline — acquisitions, \
divestitures, buybacks, financings. This is where the money went.

Then, explicitly: WHERE STATED PRIORITIES AND PAID-FOR PRIORITIES DIVERGE. Compare \
`strategic_priorities` against `incentive_metrics` year by year and name the \
divergences — a priority stated prominently that no metric pays for, or a metric \
carrying real weight that no stated priority mentions. State the divergence, the \
evidence on both sides, and what it may indicate. Be even-handed: a divergence can \
have an innocent explanation (a priority may be too long-horizon to pay annually), \
and where one is available from the pack, give it. If you find no divergence, say so \
and show the comparison you did — a null result stated with its evidence is worth \
more than a manufactured tension.

Depth over length. Every observation and every question should be one a well-briefed \
analyst could not have written without reading these filings.

Return the finished Markdown and nothing else — no preamble, no commentary about \
your process, no closing note. Do not include a title line; one is added \
automatically. Start with `## Observations`."""


PRIOR_DRAFT = """\
=== A PRIOR DOCUMENT, FOR DE-DUPLICATION ONLY ===

Below is `narrative-brief.md`, written from this same pack. It is NOT evidence: it is \
a draft, it may be wrong, and you may not cite it or treat any statement in it as \
established. Its only purpose here is that your document must not restate it. Where a \
point genuinely belongs in both, go further than the brief does or leave it out. Any \
claim you carry over must be re-sourced from the pack yourself.

{brief}

=== END OF PRIOR DOCUMENT ===

"""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_pack() -> tuple[str, dict, dict]:
    """Returns (payload text, parsed pack, index).

    The payload is read as TEXT and sent byte for byte as it sits on disk. Parsing
    and re-serialising it here would produce a different byte string from the one
    the previous run cached — same content, no cache hit.
    """
    p, i = PACK_DIR / "pack.json", PACK_DIR / "index.json"
    for f in (p, i):
        if not f.exists():
            sys.exit(f"FATAL: {f} not found.\n  Build it: uv run python -m equity_research.build_pack")
    payload = p.read_text(encoding="utf-8")
    return payload, json.loads(payload), json.loads(i.read_text(encoding="utf-8"))


def load_gen_config() -> dict:
    """Generation settings from config/company.toml, with the reasons alongside them."""
    cfg = tomllib.loads(P.company_toml.read_text(encoding="utf-8"))
    if "generation" not in cfg:
        sys.exit("FATAL: config/company.toml has no [generation] block.")
    return cfg["generation"]


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def cache_prefix(payload: str) -> str:
    """The shared prefix both documents send: preamble + pack.

    Handed to the backend as its own argument rather than glued to the front of
    the ask, because on the API path this is where the cache breakpoint goes and
    a breakpoint has to fall between the shared part and the varying part. The
    backend decides what to do with it — the API marks it, Claude Code, which
    cannot read a cache back, simply concatenates.
    """
    return PACK_PREAMBLE + payload


def brief_ask(pack: dict, gen: dict) -> str:
    s = pack["subject"]
    fys = s["fiscal_years"]
    return BRIEF_ASK.format(ticker=s["ticker"], first=f"FY{min(fys)}", last=f"FY{max(fys)}",
                            lo=gen["brief_words_min"], hi=gen["brief_words_max"])


def discussion_ask(pack: dict, brief_md: str | None) -> str:
    fys = pack["subject"]["fiscal_years"]
    ask = DISCUSSION_ASK.format(first=f"FY{min(fys)}", last=f"FY{max(fys)}")
    # The prior draft goes BEFORE the ask so the instructions are the last thing read.
    return (PRIOR_DRAFT.format(brief=brief_md) if brief_md else "") + ask


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

def check_citations(md: str, index: dict) -> dict:
    """Resolve every id in the document against the pack index.

    This is the check that makes the rest of the pipeline mean anything. Everything
    upstream exists so a reader can get from a sentence to a filing; an id that
    resolves to nothing breaks that chain while still looking like a citation, which
    is worse than no citation at all.

    Returns counts plus the unresolved ids, which the repair round is given.
    """
    cited = ID_RE.findall(md)
    unknown = sorted({c for c in cited if c not in index})
    known = [c for c in cited if c in index]
    return {
        "citations": len(cited),
        "distinct": len(set(cited)),
        "unknown": unknown,
        "by_field": {f: sum(1 for c in set(known) if index[c]["field"] == f)
                     for f in sorted({index[c]["field"] for c in known})},
        "low_confidence": sorted({c for c in known if index[c]["confidence"] != "high"}),
        "unverified_quote": sorted({c for c in known
                                    if index[c]["quote_verified"] is False}),
    }


# ---------------------------------------------------------------------------
# Quotations — the check the id check gives false assurance about
# ---------------------------------------------------------------------------
#
# Ids are easy for a model to get right: they are opaque strings sitting next to the
# fact, and on the first run 323 of 324 resolved. Quotations are the opposite. They
# are reconstructed from memory of something read 300,000 tokens earlier, and a
# quotation that is one word off looks exactly like a correct one.
#
# Measured on the first run of this stage: 98 quotations, 7 defective — five phrases
# that appear in no filing text anywhere in the pack, and two near-misses where a
# single word moved ("low 20's percent range" quoted as "low 20 percent range",
# "our most vulnerable segment" as "the most vulnerable segment").
#
# That is the case for checking quotations separately and loudly. A sentence with a
# resolving id and a fabricated quotation reads as MORE sourced than an unsourced
# one, so the id check alone actively misleads.

_QCHARS = str.maketrans({"'": '"'})       # canon folds curly to straight; fold ' to " too


def verified_text(index: dict) -> dict[str, str]:
    """The text each id is allowed to be quoted from.

    Facts contribute their `quote`, which was checked to occur in the named section.
    Risk deltas contribute their `heading`: they have no quote field because they are
    not model output at all — the headings come out of a deterministic rapidfuzz diff
    of Item 1A, so they are filing text and quoting them is legitimate.
    """
    return {i: canon(v.get("quote") or v.get("heading") or "").translate(_QCHARS)
            for i, v in index.items()}


def q_variants(q: str):
    """The forms of a quotation that still count as verbatim.

    Three concessions, each for a convention an honest writer uses:
      - US style puts the comma or period INSIDE the closing quote mark, so it is
        not part of the quoted text.
      - `[to]` marks an editorial insertion; the source may read either with the
        bracketed word or without it, so both are tried.
      - `…` marks elision, so each segment is required separately rather than the
        whole span being required contiguously.
    """
    base = canon(q).translate(_QCHARS)
    forms = {base, canon(q.strip(" ,.;:")).translate(_QCHARS)}
    for sub in (r"\1", ""):                      # keep the bracket contents, or drop them
        forms.add(canon(re.sub(r"\[([^\]]*)\]", sub, q).strip(" ,.;:")).translate(_QCHARS))
    return {f for f in forms if f}


def q_found(q: str, hay: str) -> bool:
    for form in q_variants(q):
        parts = [p.strip() for p in re.split(r"…|\.\.\.", form) if p.strip()]
        if all(p in hay for p in parts):
            return True
    return False


# Pairs left to right, so `"ready" rather than a "wish list"` yields two quotations
# and not a phantom one made of the gap between them.
QUOTE_RE = re.compile(r'"([^"]+)"')
# A floor on quotation length, to avoid flagging scare quotes and terms of art.
#
# Set by sweeping it against the first pair of documents rather than by taste. The
# first guess, 12, was pure loss: it excused `"was a typo"` — ten characters, a real
# fabrication, attributed to the company and present in no filing text — while the
# four extra short quotations that a floor of 4 admits all passed. So the floor buys
# no false-positive protection here at any value above 4, and costs a real catch.
#
# 4 rather than 0 because a two- or three-character quotation is punctuation, not a
# citation. Re-sweep this if a future company's documents start flagging terms of art.
MIN_QUOTE_CHARS = 4


def check_quotes(md: str, index: dict) -> dict:
    """Every quotation in the document, against the text its citations permit.

    Three outcomes, in descending order of comfort:
      ok        — verbatim in a fact cited in the same paragraph
      elsewhere — verbatim in the pack, but not in anything cited nearby. Real
                  filing text, attributed to the wrong place.
      bad       — occurs in no verified text anywhere. Either invented or misquoted,
                  and the two are indistinguishable from here, so both are failures.

    `elsewhere` IS NOT A BENIGN CATEGORY, and calling it one would be the mistake this
    docstring exists to prevent. It holds two very different things. Most of its
    members are a term of art quoted a paragraph away from its citation — harmless.
    But the first run also put `"cannot be made"` into a sentence about segment-level
    profitability, and that phrase's only occurrence in the pack is a fact about
    assessing the impact of tax legislation. Real filing text, welded into a claim it
    has nothing to do with. That is a fabricated claim wearing a real quotation.

    So each `elsewhere` carries `actual_source` — the ids the phrase genuinely comes
    from — because the difference between the harmless case and the serious one is
    exactly whether that source has anything to do with the sentence.
    """
    text = verified_text(index)
    allq = "\n".join(text.values())
    ok, elsewhere, bad = 0, [], []
    for para in md.split("\n\n"):
        ids = ID_RE.findall(para)
        local = "\n".join(text.get(i, "") for i in ids)
        for m in QUOTE_RE.finditer(para):
            q = m.group(1)
            if len(q.strip()) < MIN_QUOTE_CHARS:
                continue
            if q_found(q, local):
                ok += 1
            elif q_found(q, allq):
                src = [i for i, t in text.items() if t and q_found(q, t)]
                elsewhere.append({
                    "quote": q, "cited": ids, "actual_source": src[:4],
                    "actual_text": [{"id": i, "text": index[i].get("quote")
                                     or index[i].get("heading") or ""} for i in src[:4]],
                    "permitted": [{"id": i, "text": index[i].get("quote")
                                   or index[i].get("heading") or ""}
                                  for i in ids if i in index]})
            else:
                bad.append({"quote": q, "cited": ids,
                            "permitted": [{"id": i, "text": index[i].get("quote")
                                           or index[i].get("heading") or ""}
                                          for i in ids if i in index]})
    return {"checked": ok + len(elsewhere) + len(bad), "ok": ok,
            "elsewhere": elsewhere, "bad": bad}


# A whole citation group: `[EVT-FY2024-1234abcd, QA-FY2023-5678ef90]`. Matched as a
# unit rather than id-by-id because stripping just the ids leaves `[, ]` behind, and
# `str.split()` counts those leftovers as two words. That inflated the measured length
# of the first brief by roughly 2% — small, but the word count is what the document is
# held to against SPEC.md's 1,500-2,500, so it has to measure prose and only prose.
CITE_GROUP_RE = re.compile(
    r"\[\s*(?:" + ID_RE.pattern + r")(?:\s*[,;]\s*(?:" + ID_RE.pattern + r"))*\s*\]")


def word_count(md: str) -> int:
    """Words excluding bracketed citations, which are not prose and should not
    count toward a word target the writer is being held to."""
    return len(ID_RE.sub("", CITE_GROUP_RE.sub(" ", md)).split())


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------

def call(backend: model_client.Backend, gen: dict, prompt: str, label: str, *,
         effort: str | None = None, cache_prefix: str | None = None) -> tuple[str, dict]:
    """One call through the seam. Returns (text, usage).

    Every model call in this module goes through here — both documents and all
    three repair kinds — so the rules below hold once rather than four times.
    They previously did not: the same twelve lines of usage-unpacking and
    stop_reason handling were copied at four call sites, and the copies had
    already drifted (one checked for a refusal, three did not).

    Streamed always. A high-effort call over a 353k-token pack can run past the
    non-streaming request timeout, and a request that dies at the timeout has
    still been paid for. The flag is inert on the Claude Code backend, which is
    a subprocess with its own timeout.

    `cache_prefix` is the pack, when the call needs it. Two of the four kinds of
    call here do not, which is the entire point of the repair design.
    """
    print(f"  calling ({label}) …", end="", flush=True)
    resp = backend.generate(
        model=gen["model"], system=SYSTEM, prompt=prompt,
        max_tokens=gen["max_tokens"], effort=effort or gen["effort"],
        cache_prefix=cache_prefix, stream=True,
    )
    usage = usage_dict(resp)
    read = usage["cache_read_input_tokens"]
    print(f" {usage['output_tokens']:,} out"
          + (f", {read:,} cached" if read else "")
          + f", {money(usage, backend)}")

    # A document cut off at the output cap is a failed call, not a shorter
    # document: the last section is missing and nothing in the file says so.
    if resp.truncated:
        sys.exit(f"FATAL: {label} hit max_tokens ({gen['max_tokens']}) — the document is "
                 f"truncated.\n  Raise max_tokens in config/company.toml [generation].")
    if resp.stop_reason == "refusal":
        sys.exit(f"FATAL: {label} — model declined: {resp.text[:300]}")
    if not resp.text:
        sys.exit(f"FATAL: {label} returned no text (stop_reason={resp.stop_reason}).")
    return resp.text, usage


def usage_dict(resp: model_client.LLMResult) -> dict:
    """The four token counts that carry cost, normalised across backends.

    Narrowed to four keys — unlike extract_facts, which stores each response's
    usage whole — because these get SUMMED across a document's rounds and a sum
    needs the same keys in every term. The backend-specific extras are not lost:
    `rounds` in the generation record keeps the backend, the cache TTL and the
    engine's own cost figure for each call.
    """
    u = resp.usage or {}
    return {k: int(u.get(k, 0) or 0) for k in settings.USAGE_KEYS}


# ---------------------------------------------------------------------------
# Repairing unresolvable ids — WITHOUT resending the pack
# ---------------------------------------------------------------------------
#
# This used to be a second turn in the same conversation: the pack went back as a
# cached prefix, the document as the assistant turn, the list of broken ids as a
# follow-up. That is the cheapest possible shape on the API — the pack is a cache
# READ at a tenth of input price — and it does not survive the move to a Claude
# seat. Measured on claude.exe 2.1.231: `--resume` re-writes the entire
# conversation at 2x input and reads nothing back, so turn 2 cost MORE than turn
# 1. The failure is invisible from outside: you get the right document at full
# price. (model_client.py module docstring, note 5.)
#
# So the repair is now SELF-CONTAINED and pack-free on both backends: the
# document, the broken ids, and a slice of the index. One shape to maintain and
# to test, and it is cheaper on the API too.
#
# WHICH SLICE, AND WHY IT IS A DEFENSIBLE ONE
# An id that does not resolve still tells you where it was aiming. ID_RE only
# matches KNOWN field codes, so a hallucinated id like QA-FY2023-deadbeef has a
# real field and a real fiscal year — only the content hash is invented. The
# slice is therefore (field, fiscal year), and it is a complete answer within
# its bounds: every real id the document could have meant, if it meant what it
# said about field and year.
#
# Measured on the MORN pack: 1,425 ids across 53 slices, largest 230. Rendered
# with full quotes the largest slice is ~23,200 estimated tokens, which is why
# the budget below is 25,000 and the quote length steps down rather than the
# slice being cut short. A slice shown in part is worse than a smaller quote:
# the model would conclude the id does not exist and delete a true claim.
#
# WHAT IT GIVES UP. If the model wrote QA-FY2023-… while meaning a real FY2024
# fact, the right id is not in front of it and the instruction is to delete the
# claim. That is the safe direction — deleting a supported claim costs a
# sentence, inventing support costs the document its credibility — and the slice
# census below tells the model when that is what happened, so it deletes
# knowingly rather than because the pack looked empty.

EXCERPT_TOKEN_BUDGET = 25_000

# Quote lengths tried in order until the excerpt fits the budget. 0 means ids and
# provenance only, which is a poor excerpt but an honest one; it is reported.
QUOTE_CHARS_LADDER = (240, 120, 60, 0)


def slice_of(fact_id: str) -> tuple[str, str]:
    """The (field code, fiscal year) an id belongs to — real or hallucinated."""
    code, fy, _ = fact_id.split("-", 2)
    return code, fy


def slice_census(index: dict) -> str:
    """How many real ids exist in every slice of the pack.

    Cheap (53 lines for MORN) and it does a specific job: it lets the model see
    that, say, QA-FY2024 holds 162 facts it has not been shown, so "the id I
    meant is not here" is distinguishable from "the pack has nothing".
    """
    counts: dict[tuple[str, str], int] = {}
    for i in index:
        counts[slice_of(i)] = counts.get(slice_of(i), 0) + 1
    return "\n".join(f"  {code}-{fy}   {n:>4} facts"
                     for (code, fy), n in sorted(counts.items()))


def _entry_line(fact_id: str, entry: dict, quote_chars: int) -> str:
    src = entry.get("source") or {}
    head = f"  {fact_id}  [{src.get('form', '?')} {src.get('filing_date', '?')}]"
    if entry.get("confidence") != "high":
        head += "  (low confidence)"
    if quote_chars == 0:
        return head + "\n"
    q = " ".join((entry.get("quote") or entry.get("heading") or "").split())
    if len(q) > quote_chars:
        q = q[:quote_chars] + " …[truncated]"
    return f"{head}\n      {q}\n"


def index_excerpt(index: dict, unknown: list[str]) -> tuple[str, dict]:
    """The slices the broken ids point at, rendered to fit a token budget.

    Returns (text, meta). `meta` is recorded in the generation record and printed,
    because a repair that was given less evidence than it asked for must not look
    like one that was given all of it.
    """
    wanted = sorted({slice_of(i) for i in unknown})
    members = {k: sorted(i for i in index if slice_of(i) == k) for k in wanted}

    for quote_chars in QUOTE_CHARS_LADDER:
        blocks = []
        for key in wanted:
            code, fy = key
            ids = members[key]
            body = "".join(_entry_line(i, index[i], quote_chars) for i in ids)
            blocks.append(f"--- every real {code} id in {fy} ({len(ids)} facts) ---\n"
                          + (body or "  (this slice is empty — the pack holds no "
                                      "fact of this field for this year)\n"))
        text = "\n".join(blocks)
        tokens = settings.estimate_tokens(text)
        if tokens <= EXCERPT_TOKEN_BUDGET or quote_chars == QUOTE_CHARS_LADDER[-1]:
            break

    return text, {
        "slices": [f"{c}-{fy}" for c, fy in wanted],
        "ids_offered": sum(len(v) for v in members.values()),
        "quote_chars": quote_chars,
        "estimated_tokens": tokens,
        "over_budget": tokens > EXCERPT_TOKEN_BUDGET,
    }


ID_FIX = """\
Ids in the document below do not exist in the evidence pack. Each one is a \
citation to nothing.

THE IDS THAT DO NOT RESOLVE
{unknown}

You are NOT being shown the pack again. You are shown, in full, every real fact \
id in the same field and the same fiscal year as each broken id — which is where \
the fact you meant will be, if you meant the field and year you wrote.

{excerpt}
For orientation, the number of facts in every slice of the pack, including the \
ones you are not being shown:

{census}

For each broken id, do exactly one of these:

  (a) If you can see the fact you meant in the lists above, replace the broken id \
with its real id, copied CHARACTER FOR CHARACTER.
  (b) Otherwise, delete the claim the broken id supported. If its sentence has \
other citations that genuinely support what remains, you may keep the part they \
support and drop the rest.

Do not invent a replacement id. Do not move a citation from elsewhere in the \
document to cover the gap. Do not keep a sentence whose only support was a broken \
id. If the fact you meant is in a slice you were not shown, you cannot cite it \
from here — delete the claim.

The quotations above are for IDENTIFICATION ONLY and some are truncated. Do not \
copy them into the document as quotations; every quotation in the finished \
document is checked character for character against the fact cited beside it.

Return the complete corrected document in the same format. Change nothing else: \
same sections, same headings, same order, same citations everywhere they already \
resolved.

=== DOCUMENT ===
{doc}
=== END OF DOCUMENT ==="""


def repair_ids(backend: model_client.Backend, gen: dict, index: dict, md: str,
               label: str, max_rounds: int) -> tuple[str, list[dict], list[dict]]:
    """Hold the finished document to its citations, without the pack.

    Two rounds at most, as before: an id the model cannot resolve twice is one
    the pack does not contain, and the instruction for that case is to drop the
    sentence rather than keep looking.
    """
    usages, rounds = [], [{"round": 0, "checks": check_citations(md, index)}]
    for n in range(1, max_rounds + 1):
        unknown = rounds[-1]["checks"]["unknown"]
        if not unknown:
            break
        excerpt, meta = index_excerpt(index, unknown)
        print(f"  {len(unknown)} unresolvable id(s) — id repair round {n}: "
              + ", ".join(unknown[:6]) + (" …" if len(unknown) > 6 else ""))
        print(f"      excerpt: {meta['ids_offered']} real ids from "
              f"{len(meta['slices'])} slice(s) ({', '.join(meta['slices'])}), "
              f"quotes at {meta['quote_chars'] or 'no'} chars, "
              f"~{meta['estimated_tokens']:,} tokens"
              + ("  !! OVER BUDGET" if meta["over_budget"] else ""))
        prompt = ID_FIX.format(
            unknown="\n".join(f"  {c}" for c in unknown),
            excerpt=excerpt, census=slice_census(index), doc=md)
        fixed, usage = call(backend, gen, prompt, f"{label} id repair {n}",
                            effort=gen["repair_effort"])
        md = fixed
        usages.append(usage)
        rounds.append({"round": n, "usage": usage, "excerpt": meta,
                       "checks": check_citations(md, index)})
    return md, usages, rounds


QUOTE_FIX = """\
You wrote the document below. Every passage inside quotation marks in it is supposed \
to be copied verbatim from the `quote` field of a fact cited in the same paragraph. \
The ones listed below are not, in one of two ways.

GROUP A — THE WORDS ARE IN NO FILING TEXT ANYWHERE. Either invented, or misquoted by \
a word or two, which from here is the same thing. You are shown what you wrote and \
the actual verified text of every fact you cited beside it.

{group_a}

GROUP B — THE WORDS ARE REAL FILING TEXT, BUT NOT FROM ANYTHING YOU CITED THERE. You \
are shown what you wrote, the facts you cited, and the fact the phrase ACTUALLY comes \
from. Read that last one carefully before deciding. If it is about a different \
subject entirely, then you have built a claim out of a phrase that never supported \
it, and the claim has to go — a genuine quotation attached to the wrong proposition \
is a fabricated claim, not a citation error.

{group_b}

For each, do exactly one of these:

  (a) If the point is supported by the verified text of a fact cited there, replace \
your quotation with a span copied CHARACTER FOR CHARACTER from that text. Not the \
sense of it — the characters. A single changed word makes it a misquotation.
  (b) If the verified text supports the point but no clean span quotes well, remove \
the quotation marks and state the point in your own words. An unquoted paraphrase \
with a citation is honest; a quotation that is not verbatim is not.
  (c) If no verified text supports the point, delete the claim.

For group B only, one further option: if the fact the phrase actually comes from is \
genuinely about this subject and does support your sentence, add its id to the \
citation and keep the quotation.

Do not otherwise swap in a different id to justify a quotation you already wrote — \
the quotation follows the evidence, not the other way round. And do not repair a \
sentence by making it vaguer while keeping its shape; if the evidence is not there, \
the sentence goes.

Return the complete corrected document, identical to the original except for these \
fixes. Change nothing else: same sections, same headings, same order, same citations \
everywhere they were already correct.

=== DOCUMENT ===
{doc}
=== END OF DOCUMENT ==="""


def _problem_block(items: list[dict], with_source: bool) -> str:
    if not items:
        return "  (none)"
    out = []
    for i, b in enumerate(items, 1):
        lines = [f"{i}. YOU WROTE: \"{b['quote']}\""]
        lines.append("   VERIFIED TEXT OF THE FACTS YOU CITED THERE:" if b["permitted"]
                     else "   YOU CITED NO FACT IN THAT PARAGRAPH.")
        lines += [f"     [{p['id']}] {p['text']}" for p in b["permitted"]]
        if with_source:
            lines.append("   THE PHRASE ACTUALLY COMES FROM:")
            lines += [f"     [{p['id']}] {p['text']}" for p in b.get("actual_text", [])]
        out.append("\n".join(lines))
    return "\n\n".join(out)


def repair_quotes(backend: model_client.Backend, gen: dict, index: dict, md: str,
                  label: str, max_rounds: int) -> tuple[str, list[dict], list[dict]]:
    """Hold the finished document to its quotations.

    Deliberately does NOT resend the pack. The fix needs the document and the handful
    of quote fields in question — about 8,000 tokens against 354,000 — so this runs at
    roughly $0.20 a round instead of $2.22, and can be run against documents already
    on disk without regenerating them.

    This was the only repair round already built this way, which is why it needed
    nothing when the engine changed. `repair_ids` above is now its twin.
    """
    usages, rounds = [], [{"round": 0, "checks": check_quotes(md, index)}]
    for n in range(1, max_rounds + 1):
        chk = rounds[-1]["checks"]
        bad, elsew = chk["bad"], chk["elsewhere"]
        if not bad and not elsew:
            break
        print(f"  {len(bad)} quotation(s) matching no filing text, {len(elsew)} "
              f"attributed to a fact that does not contain them — quote repair round {n}")
        for b in bad:
            print(f"      A  “{b['quote'][:74]}”")
        for b in elsew:
            print(f"      B  “{b['quote'][:60]}” ← really {', '.join(b['actual_source'][:2])}")
        prompt = QUOTE_FIX.format(
            group_a=_problem_block(bad, with_source=False),
            group_b=_problem_block(elsew, with_source=True), doc=md)
        fixed, usage = call(backend, gen, prompt, f"{label} quote repair {n}",
                            effort=gen["repair_effort"])
        md = fixed
        usages.append(usage)
        rounds.append({"round": n, "usage": usage, "checks": check_quotes(md, index)})
    return md, usages, rounds


CONSTRAINT_FIX = """\
The document below fails a binding constraint from the evidence pack it was written \
from. The failures are listed with the data each was derived from.

{failures}

Fix each one, in the document's own voice and in the place it belongs — not as a \
footnote or a bracketed aside at the end. The correction has to be somewhere the \
reader meets it before they rely on the thing it qualifies.

Every rule you wrote under still applies. In particular: state only what the data \
below supports, do not add a citation you cannot see in the pack, and do not \
introduce a quotation.

Change nothing else. Same sections, same headings, same order, same claims, same \
citations. Return the complete corrected document.

=== DOCUMENT ===
{doc}
=== END OF DOCUMENT ==="""


def repair_constraints(backend: model_client.Backend, gen: dict, md: str,
                       failures: list[dict], label: str) -> tuple[str, dict]:
    """One targeted call to fix constraint failures, without resending the pack.

    Same economics as the quotation repair and for the same reason: the fix needs the
    document and the handful of derived facts the failing check already computed, not
    354,000 tokens of evidence. Roughly $0.25 against $2.50 to regenerate.

    The alternative — hand-editing the Markdown — was rejected. Each document's
    provenance says it was written by the model from the pack and nothing else, and a
    hand-inserted sentence would make that false while leaving it looking true.
    """
    blocks = "\n\n".join(
        f"{i}. FAILED: {f['name']}\n   {f['detail']}" for i, f in enumerate(failures, 1))
    return call(backend, gen, CONSTRAINT_FIX.format(failures=blocks, doc=md),
                f"{label} constraint repair", effort=gen["repair_effort"])


@functools.lru_cache(maxsize=1)
def generation_model() -> str:
    """The model the generation calls use, for pricing a usage record.

    A usage dict records tokens but not which model produced them, so pricing
    has to come from somewhere. Every call in this module — both documents and
    both repair kinds — uses `gen["model"]`, so the configured generation model
    is the right answer for all of them. Cached because `cost()` is called from
    eleven places, several inside loops.

    If per-task models arrive (Phase 5 plans Sonnet for the repair rounds), this
    is the single place that has to learn to take the model as an argument.
    """
    return load_gen_config()["model"]


def cost(u: dict, model: str | None = None, *, ttl: str = "5m") -> float:
    """Dollar cost of one usage record, at the prices in settings.py.

    The four multipliers used to be module constants here (5.00, 25.00, 1.25,
    0.10), duplicating extract_facts.py and build_pack.py. They now come from
    one table with a recorded as-of date — see settings.PRICES_AS_OF.

    `ttl` decides the cache-write multiplier and defaults to the API's 5 minutes.
    Callers holding a backend pass its own — Claude Code always writes at 1 hour,
    which is 2.0x rather than 1.25x, and pricing its records at the default would
    under-report a headless run by more than a third.
    """
    return settings.usage_cost(u, model or generation_model(), ttl=ttl)


def money(usage: dict, backend: model_client.Backend) -> str:
    """A cost string that does not claim more than it knows.

    On a subscription seat there is no dollar spend at all — the figure is what
    the same tokens would have cost through the API. Printing a bare "$4.68"
    invites someone to put it in a budget, and the whole reason this backend
    exists is that the people using it have no API bill to put it in.
    """
    d = cost(usage, ttl=backend.cache_ttl)
    if backend.name == "claude_code":
        return f"${d:.2f} API-equivalent"
    return f"${d:.2f}"


def generate(backend: model_client.Backend, gen: dict, index: dict, payload: str,
             ask: str, label: str, max_repairs: int) -> tuple[str, dict, list[dict]]:
    """Generate one document, then hold it to its citations and its quotations.

    This is the only call here that carries the pack. Both repair passes are
    pack-free and self-contained — see the note above `repair_ids`.
    """
    text, usage = call(backend, gen, ask, label, cache_prefix=cache_prefix(payload))
    usages = [usage]
    rounds = [{"round": 0, "usage": usage, "checks": check_citations(text, index)}]

    text, id_usages, id_rounds = repair_ids(backend, gen, index, text, label, max_repairs)
    usages += id_usages
    rounds.append({"stage": "ids", "rounds": id_rounds})

    # Quotations are checked AFTER the ids, and separately, because fixing a
    # quotation may delete the claim it supported and therefore its citation — so the
    # id check has to run once more at the end, on the document that will be written.
    text, q_usages, q_rounds = repair_quotes(backend, gen, index, text, label, max_repairs)
    usages += q_usages
    rounds.append({"stage": "quotes", "rounds": q_rounds})

    return text, {k: sum(u[k] for u in usages) for k in usages[0]}, rounds


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def provenance(pack: dict, gen: dict, sha: str, usage: dict, checks: dict, q: dict,
               words: int, stamp: str, corrections: list[dict] | None = None,
               written_from_sha: str | None = None,
               remaps: list[dict] | None = None,
               backend: str = "api", cache_ttl: str = "5m") -> str:
    """The footer every generated document carries.

    Unlike `timeline.md` these are not reproducible — the same inputs give a
    different document each run. So the document records what it CAN be held to:
    which payload it was written from, which model wrote it, and how many of its
    citations resolved. `pack sha256` is the link back; re-running build_pack.py
    either reproduces that hash or proves the evidence moved underneath it.
    """
    s = pack["subject"]
    low = f"{len(checks['low_confidence'])} of them low-confidence" \
        if checks["low_confidence"] else "none low-confidence"

    # THE CORRECTION NOTICE GOES IN THE DOCUMENT, not only in the JSON record.
    #
    # A correction the reader cannot see is a hand-edit with better paperwork. If a
    # sentence in front of them was not written by the model that wrote the rest,
    # they are entitled to know which one and why, in the document itself.
    corr_block: list[str] = []
    if corrections:
        corr_block = ["",
                      f"**{len(corrections)} sentence-level correction"
                      f"{'' if len(corrections) == 1 else 's'} applied after "
                      f"generation.** The model's own text is preserved unedited in "
                      f"`data/pack/gen-*.json` under `text`; what is published here is "
                      f"`shipped_text`. Each correction below fixes a statement the "
                      f"cited filings contradict — see `config/corrections.toml`.", ""]
        for c in corrections:
            corr_block += [f"- **`{c['correction_id']}`** ({c['verified_by']}) — "
                           f"{c['reason']}",
                           f"    - *Replaced:* “{c['was'][:180]}"
                           f"{'…' if len(c['was']) > 180 else ''}”"]
    # Re-stamping the pack hash is only honest because it is conditional: the
    # --apply-corrections path refuses to write unless every id in the document
    # resolves and every quotation verifies against the pack now on disk. Both hashes
    # are printed, so "which payload did the model actually read" is still answerable.
    # Renumberings are disclosed as a COUNT, not enumerated like a correction.
    # Nothing the document says changed — only the identifier a citation points at —
    # so a nine-item list of hash pairs in a reader-facing document would bury the
    # corrections, which are the entries that do change a claim. The pairs are in
    # `config/corrections.toml` and on the generation record for anyone auditing.
    if remaps:
        n_occ = sum(r["occurrences"] for r in remaps)
        corr_block += ["",
                       f"**{n_occ} citation{'' if n_occ == 1 else 's'} renumbered** "
                       f"across {len(remaps)} fact(s). The claims are unchanged: "
                       f"repairing a fact's stored quote changes the content hash it "
                       f"is identified by, so the citation had to follow it. Each "
                       f"renumbering is checked to point at the same claim before it "
                       f"is applied — see `[[id_remap]]` in `config/corrections.toml`.",
                       ""]
    if written_from_sha and written_from_sha != sha:
        corr_block += ["",
                       f"The model wrote this from pack `{written_from_sha}`. The "
                       f"ledger has been corrected since, and every id and quotation "
                       f"above was re-resolved against the current pack — named at the "
                       f"top of this section — before this file was rewritten. The "
                       f"rewrite is refused if any of them fails.", ""]

    return "\n".join([
        "", "---", "",
        "### Provenance", "",
        f"Written by `{gen['model']}` at `{gen['effort']}` effort on {stamp}, from "
        f"`data/pack/pack.json` and nothing else — no general knowledge about "
        f"{s['company_name']} or its industry was used, and no source outside the "
        f"company's own SEC filings for {min(s['fiscal_years'])}–{max(s['fiscal_years'])}.",
        "",
        f"- **pack sha256** `{sha}`",
        f"- **{words:,} words**, **{checks['citations']} citations** to "
        f"**{checks['distinct']} distinct facts** ({low})",
        f"- Every id above was resolved against `data/pack/index.json` at generation "
        f"time; **{len(checks['unknown'])}** did not resolve.",
        f"- Every one of the **{q['checked']} quotations** was checked character for "
        f"character against the verified filing text of the facts cited beside it; "
        f"**{q['ok']}** matched there, **{len(q['elsewhere'])}** matched filing text "
        f"cited elsewhere in this document, **{len(q['bad'])}** did not match any.",
        f"- **{usage['input_tokens'] + usage['cache_read_input_tokens'] + usage['cache_creation_input_tokens']:,}** "
        f"input tokens, **{usage['output_tokens']:,}** output, "
        f"**${cost(usage, ttl=cache_ttl):.2f}**"
        # A seat is not billed in dollars. The figure is still worth printing —
        # it is the only unit in which two runs can be compared — but a reader
        # who takes it for an invoice line has been misled by this document.
        + (" (API-equivalent; written on a Claude subscription seat, which is "
           "not billed in dollars)" if backend == "claude_code" else "") + ".",
        "",
        "Ids resolve in `data/pack/index.json` to the exact quote, section and accession "
        "each claim rests on. `claim` text in the pack is a model-written summary and is "
        "not quoted here; every quotation is copied from a `quote` field verified to "
        "occur in the named filing section.",
        *corr_block,
    ])


# ---------------------------------------------------------------------------
# Corrections to a document already written
# ---------------------------------------------------------------------------
# A generated document is model-written prose that costs ~$3.50 a pass and does not
# reproduce byte-for-byte. So when one sentence turns out to be wrong, regenerating
# the whole document to fix it is the expensive option AND the worse one: it
# discards every other sentence that has already been verified, and hands back a new
# document that has to be verified again from nothing.
#
# The alternative — editing output/*.md by hand — is what this project's own checks
# exist to prevent, and rightly: a hand-edited deliverable is indistinguishable from
# a generated one, and the record of what the model actually wrote is gone.
#
# So a correction is DATA, in config/corrections.toml, applied here:
#
#   `text`         in gen-<slug>.json stays exactly as the model wrote it, forever.
#   `shipped_text` holds what was published, derived from `text` on every run.
#   `corrections`  records each edit with its reason and who verified it.
#
# tests/test_generate_outputs.py checks output/*.md against `shipped_text`, so a
# hand-edit is still caught. Applying is idempotent because every correction is
# applied to `text`, never to the previous `shipped_text`.
#
# See VERIFICATION.md D1 for the correction this was built for.

def load_document_corrections(slug: str) -> list[dict]:
    """Corrections declared for one document. Absent file is fine; malformed is not."""
    if not CORRECTIONS.exists():
        return []
    entries = [c for c in
               tomllib.loads(CORRECTIONS.read_text(encoding="utf-8"))
               .get("document_correction", [])
               if c.get("document") == slug]
    problems = [f"{c.get('id', 'unnamed')}: missing "
                + ", ".join(k for k in ("id", "find", "replace", "reason", "verified_by")
                            if not c.get(k))
                for c in entries
                if not all(c.get(k) for k in
                           ("id", "find", "replace", "reason", "verified_by"))]
    if problems:
        sys.exit(f"FATAL: {CORRECTIONS.relative_to(ROOT)} is not usable\n  "
                 + "\n  ".join(problems))
    return entries


def load_id_remaps() -> list[dict]:
    """`[[id_remap]]` entries: a fact's id changed, its claim did not.

    A SEPARATE MECHANISM FROM A CORRECTION, on purpose. A correction says the
    document was wrong. A remap says the document was right and the identifier moved
    underneath it — which is what happens every time a fact's quote or value is
    repaired, because `fact_id` hashes both. Recording "the buyback figure was cited
    to the wrong filing" and "this id was renumbered when we decoded an apostrophe"
    through the same channel would misdescribe both.

    The practical reason is stronger than the semantic one: a remap can be CHECKED,
    and free-text find/replace cannot. `apply_id_remaps` verifies that the old id is
    genuinely gone from the index, that the new one is present, and — the part that
    matters — that both denote the same claim. A typo'd remap fails loudly instead of
    silently re-pointing a sentence at a different fact.
    """
    if not CORRECTIONS.exists():
        return []
    entries = tomllib.loads(CORRECTIONS.read_text(encoding="utf-8")).get("id_remap", [])
    bad = [str(e) for e in entries
           if not all(e.get(k) for k in ("was", "now", "reason"))]
    if bad:
        sys.exit(f"FATAL: id_remap entries missing was/now/reason:\n  "
                 + "\n  ".join(bad))
    return entries


def apply_id_remaps(text: str, index: dict, ledger_claims: dict
                    ) -> tuple[str, list[dict]]:
    """Rewrite renumbered citations. Returns (text, records applied to this doc)."""
    applied, problems = [], []
    for e in load_id_remaps():
        was, now = e["was"], e["now"]
        if was in index:
            problems.append(f"{was} -> {now}: the OLD id is still in the index, so it "
                            f"was not renumbered and this remap is wrong or stale")
            continue
        if now not in index:
            problems.append(f"{was} -> {now}: the NEW id is not in the index")
            continue
        # The check a find/replace cannot make: same claim on both sides.
        if ledger_claims.get(was) and ledger_claims[was] != ledger_claims.get(now):
            problems.append(f"{was} -> {now}: these are DIFFERENT claims. A remap may "
                            f"only re-point a citation at the same fact under a new "
                            f"id, never at another fact.")
            continue
        n = len(re.findall(rf"\b{re.escape(was)}\b", text))
        if n:
            text = re.sub(rf"\b{re.escape(was)}\b", now, text)
            applied.append({"was": was, "now": now, "occurrences": n,
                            "reason": " ".join(e["reason"].split())})
    if problems:
        sys.exit(f"FATAL: {len(problems)} id_remap(s) are not usable. NOTHING WAS "
                 f"WRITTEN.\n\n  " + "\n\n  ".join(problems))
    return text, applied


def apply_document_corrections(slug: str, text: str) -> tuple[str, list[dict]]:
    """Apply every declared correction to the model's text. Returns (text, records).

    `find` must occur EXACTLY ONCE. Zero means the correction has gone stale and the
    document has silently reverted to the defective sentence — the failure this whole
    mechanism exists to make impossible. More than one means the anchor is ambiguous
    and which sentence was meant is undecidable. Both are fatal.
    """
    out, records, problems = text, [], []
    for c in load_document_corrections(slug):
        n = out.count(c["find"])
        if n != 1:
            problems.append(
                f"'{c['id']}' — `find` occurs {n} times in the generated text, "
                f"expected exactly 1. "
                + ("The document no longer contains the sentence this corrects, so it "
                   "has reverted to whatever is there now."
                   if n == 0 else "Extend `find` until it identifies one sentence."))
            continue
        out = out.replace(c["find"], c["replace"])
        records.append({"correction_id": c["id"], "was": c["find"], "now": c["replace"],
                        "reason": " ".join(c["reason"].split()),
                        "verified_by": c["verified_by"]})
    if problems:
        sys.exit(f"FATAL: {len(problems)} correction(s) for '{slug}' did not apply. "
                 f"NOTHING WAS WRITTEN.\n\n  " + "\n\n  ".join(problems))
    return out, records


# Spelled-out year counts for the document lede. A lookup table rather than a
# number-to-words library because `settings.MAX_WINDOW_YEARS` caps the window at
# 10, so this table is complete for every window the pipeline will accept — and
# `window()` refuses anything longer before generation is ever reached.
_YEAR_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
               6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def span_words(n_years: int) -> str:
    """"five-year", for the lede. Falls back to digits rather than failing."""
    return f"{_YEAR_WORDS.get(n_years, str(n_years))}-year"


DOCS = {
    # `lede` is .format()-ed exactly like `title`. "A five-year read" was
    # hardcoded here, which was true only for a five-year window: a three-year
    # run would have shipped a document whose own first sentence misdescribed
    # its scope, above a title that correctly said FY2023-FY2025.
    "brief": {"file": "narrative-brief.md", "title": "{name} ({ticker}) — Narrative brief, {span}",
              "lede": "A {span_words} read of what changed and what it appears to indicate, "
                      "drawn only from the company's own SEC filings."},
    "discussion": {"file": "discussion-points.md",
                   "title": "{name} ({ticker}) — Discussion points, {span}",
                   "lede": "Patterns across the window, the questions they raise, and where "
                           "stated priorities and paid-for priorities diverge."},
}


def write_doc(slug: str, body: str, pack: dict, gen: dict, sha: str, usage: dict,
              checks: dict, q: dict, stamp: str, corrections: list[dict] | None = None,
              written_from_sha: str | None = None,
              remaps: list[dict] | None = None,
              backend: str = "api", cache_ttl: str = "5m") -> Path:
    """Render one document and its provenance footer.

    `backend` and `cache_ttl` default to what every record written before the
    Claude Code seam implies — the API, at the 5-minute TTL that was the only one
    used then. That is the same convention extract_facts uses for its `backend`
    field, and it has the property that matters here: re-rendering an existing
    document produces the same footer it already has, byte for byte, rather than
    silently restating its cost under a different price.
    """
    s = pack["subject"]
    span = f"FY{min(s['fiscal_years'])}–FY{max(s['fiscal_years'])}"
    d = DOCS[slug]
    head = d["title"].format(name=s["company_name"], ticker=s["ticker"], span=span)
    # len(), not max-min+1: if a year is missing from the pack the document
    # covers fewer years than the span implies, and the lede should say what the
    # document actually reads, not what the window asked for.
    lede = d["lede"].format(span_words=span_words(len(s["fiscal_years"])))
    md = "\n".join([f"# {head}", "", lede, "", body.strip(),
                    provenance(pack, gen, sha, usage, checks, q, word_count(body), stamp,
                               corrections, written_from_sha, remaps,
                               backend, cache_ttl), ""])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / d["file"]
    p.write_text(md, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def rewrite_with_corrections(pack: dict, gen: dict, index: dict, sha: str) -> None:
    """Re-render both documents from their generation records. No model call, $0.00.

    Three things happen here, and the order is the safety property:

      1. Every declared correction is applied to the MODEL'S text (not to whatever is
         on disk), so the result depends only on committed inputs and re-running is
         idempotent.
      2. The result is re-checked against the pack ON DISK — every id must resolve and
         every quotation must still be verbatim. This is what makes step 3 honest.
      3. Only then is the document rewritten, carrying the current pack hash and, when
         it differs, the hash the model actually read.

    Step 2 is not a formality. The pack hash in a document is the reader's guarantee
    that the evidence has not moved underneath it, and re-stamping it after a ledger
    correction would be a lie if any citation had gone stale. It cannot: a stale
    citation stops the write.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_corrected = n_remapped = 0
    # {id -> a canonical description of the claim}, read from the LEDGER rather than
    # the pack, because a remapped id is by definition absent from the current pack
    # and the old side of the mapping has to be checkable too. Read from git is not
    # needed: the ledger keeps both facts only if both exist, so an unknown `was`
    # simply skips the same-claim assertion and the index checks still apply.
    ledger_claims: dict[str, str] = {}
    for p in sorted(P.ledger.glob("FY*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k, v in d.items():
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict) and it.get("id"):
                        ledger_claims[it["id"]] = json.dumps(
                            {"f": it.get("field"), "y": it.get("fiscal_year"),
                             "v": it.get("value")}, sort_keys=True, ensure_ascii=False)
    for slug, d in DOCS.items():
        rec_p = PACK_DIR / f"gen-{slug}.json"
        if not rec_p.exists():
            sys.exit(f"FATAL: {rec_p.relative_to(ROOT)} not found. It is a committed "
                     f"file; restore it rather than regenerating.")
        rec = json.loads(rec_p.read_text(encoding="utf-8"))
        # CORRECTIONS FIRST, REMAPS LAST, and the order is load-bearing both ways.
        #
        # A correction's `find` anchor is hand-written against the model's text and
        # may contain an id — D3's does. Remapping first would move that id out from
        # under the anchor and the correction would match nothing, which is fatal.
        #
        # Running remaps last also makes them a final normalisation: whatever ids a
        # correction's `replace` introduced are brought current too, so a correction
        # authored before a later ledger repair does not silently reintroduce a stale
        # citation.
        text, records = apply_document_corrections(slug, rec["text"])
        text, remaps = apply_id_remaps(text, index, ledger_claims)

        checks, qchecks = check_citations(text, index), check_quotes(text, index)
        if checks["unknown"] or qchecks["bad"] or qchecks["elsewhere"]:
            sys.exit(
                f"FATAL: {d['file']} does not verify against the pack on disk, so its "
                f"provenance hash must NOT be re-stamped. NOTHING WAS WRITTEN.\n"
                f"  unresolved ids : {checks['unknown']}\n"
                f"  bad quotations : {[b['quote'][:60] for b in qchecks['bad']]}\n"
                f"  mis-cited      : {[b['quote'][:60] for b in qchecks['elsewhere']]}\n"
                f"  Either add a document_correction for each, or regenerate the "
                f"document against the current pack.")

        written_from = rec.get("pack_sha256")
        rec["shipped_text"] = text
        rec["corrections"] = records
        rec["id_remaps"] = remaps
        rec["corrections_applied_utc"] = stamp
        rec["shipped_pack_sha256"] = sha
        rec["citations_shipped"], rec["quotations_shipped"] = checks, qchecks
        rec_p.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")

        p = write_doc(slug, text, pack, gen, sha, rec["usage"], checks, qchecks,
                      rec["generated_utc"], records, written_from, remaps,
                      rec.get("backend", "api"), rec.get("cache_ttl", "5m"))
        n_corrected += len(records)
        n_remapped += sum(r["occurrences"] for r in remaps)
        print(f"  {p.relative_to(ROOT)} — {len(records)} correction(s), "
              f"{sum(r['occurrences'] for r in remaps)} citation(s) renumbered, "
              f"{word_count(text):,} words, {checks['citations']} citations "
              f"({checks['distinct']} distinct), {qchecks['ok']}/{qchecks['checked']} "
              f"quotations verbatim where cited"
              + ("" if written_from == sha else f"\n     pack re-stamped "
                                                f"{str(written_from)[:16]}… -> {sha[:16]}…"))
    print(f"\n{n_corrected} correction(s) applied across {len(DOCS)} document(s). "
          f"No model call; $0.00")


def count_prompt(backend: model_client.Backend, gen: dict, text: str) -> tuple[int, str]:
    """(tokens, basis) for a prompt, asking the backend before estimating.

    Same contract as build_pack.count_tokens and for the same reason: the API can
    count exactly and for free, Claude Code cannot count at all, and the caller
    has to be able to say which it got. A colleague with no API key still gets a
    number — labelled — rather than "cost unknown", because an estimate that
    stops working for the people who most need it is not a cost gate.
    """
    try:
        n = backend.count_tokens(model=gen["model"], system=SYSTEM, prompt=text)
    except Exception as exc:                                        # noqa: BLE001
        print(f"  (exact count unavailable: {type(exc).__name__}: "
              f"{str(exc)[:120]})")
        n = None
    if n is not None:
        return n, "exact"
    return settings.estimate_tokens(SYSTEM + text), "estimated"


def estimate(backend: model_client.Backend, gen: dict, pack: dict, payload: str) -> None:
    """What both documents will cost, before spending anything.

    Output cannot be counted in advance and is bounded by max_tokens, which is a
    deliberate over-estimate and labelled as one.

    The two backends are priced by DIFFERENT arithmetic, not the same numbers
    with a different label, and the estimate says so. On the API the pack is
    written once and read back for the second document. Claude Code writes it
    twice: it cache-writes every prompt at 1h TTL, bills that at 2x input, and
    never reads user content back — measured, two calls with a byte-identical
    prefix produced identical usage. Showing the API's cache saving to someone on
    a seat would understate their run by about half.
    """
    n, basis = count_prompt(backend, gen, cache_prefix(payload) + brief_ask(pack, gen))
    approx = "~" if basis != "exact" else ""
    price = settings.price_for(gen["model"])
    full = n * price.input / 1e6
    out_max = 2 * gen["max_tokens"] * price.output / 1e6
    seat = backend.name == "claude_code"

    print(f"Estimate — {backend.name}, {gen['model']}, effort={gen['effort']}, "
          f"max_tokens={gen['max_tokens']:,}")
    print()
    print(f"  prompt: {approx}{n:,} tokens (system + pack + ask), {basis}")
    print()

    if seat:
        write = full * settings.CACHE_WRITE_MULTIPLIER["1h"]
        print(f"  call 1  narrative-brief      cache WRITE   {approx}${write:.2f}")
        print(f"  call 2  discussion-points    cache WRITE   {approx}${write:.2f}  "
              f"(+ the brief, a few thousand tokens)")
        print(f"  input, this run                            {approx}${2 * write:.2f}")
        print(f"  output, worst case                         {approx}${out_max:.2f}  "
              f"(2 x max_tokens; the real figure will be well under)")
        print()
        print(f"  TOTAL, worst case                          {approx}${2 * write + out_max:.2f}")
        print()
        print("  NOT A BILL. A Claude seat is not charged in dollars; these are what "
              "the same tokens would cost through the API, which is the only unit "
              "available for comparing one run against another.")
        print("  Both calls WRITE the pack because this engine never reads user "
              "content back from its cache. There is no ordering that avoids it.")
    else:
        write = full * settings.CACHE_WRITE_MULTIPLIER[backend.cache_ttl]
        read = full * settings.CACHE_READ_MULTIPLIER
        print(f"  call 1  narrative-brief      cache WRITE   {approx}${write:.2f}  "
              f"(TTL {backend.cache_ttl})")
        print(f"  call 2  discussion-points    cache READ    {approx}${read:.2f}  "
              f"(+ the brief, a few thousand tokens)")
        print(f"  input, this run                            {approx}${write + read:.2f}"
              f"   vs {approx}${2 * full:.2f} uncached")
        print(f"  output, worst case                         {approx}${out_max:.2f}  "
              f"(2 x max_tokens; the real figure will be well under)")
        print()
        print(f"  TOTAL, worst case                          "
              f"{approx}${write + read + out_max:.2f}")
        print()
        # Said out loud, because the flattering reading is available and wrong.
        # Both repair passes are pack-free now, so a clean run is only two calls
        # — below the 2.2 reads a 1-hour write needs to repay itself.
        if write + read > 2 * full:
            print(f"  On this run the cache COSTS {approx}${write + read - 2 * full:.2f} "
                  f"rather than saving: two calls is below the "
                  f"{settings.break_even_reads(backend.cache_ttl):.1f} reads a "
                  f"{backend.cache_ttl} write needs to repay itself. It pays from the "
                  f"third call inside the TTL on — a re-run, or a second "
                  f"--only pass.")
        print(f"  A RE-RUN after the {backend.cache_ttl} TTL expires pays a fresh cache "
              f"write ({approx}${write:.2f}), not a read.")

    print()
    print(f"  Repair rounds do NOT resend the pack — id repair carries an index "
          f"excerpt of up to ~{EXCERPT_TOKEN_BUDGET:,} tokens, quote and constraint "
          f"repair a few thousand. Budget a few tenths of a dollar each, not "
          f"{approx}${full:.2f}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 5e — generate the two prose outputs.")
    ap.add_argument("--estimate", action="store_true", help="print the cost and exit")
    ap.add_argument("--only", choices=["brief", "discussion"], help="one document only")
    ap.add_argument("--max-repairs", type=int, default=2,
                    help="citation repair rounds per document (default 2, 0 to disable)")
    ap.add_argument("--fix-quotes", action="store_true",
                    help="re-check and repair the quotations in the documents already on "
                         "disk, without regenerating them (~$0.20/doc, no pack resend)")
    ap.add_argument("--fix-ids", action="store_true",
                    help="re-check and repair unresolvable citations in the documents "
                         "already on disk (no pack resend; carries an index excerpt)")
    ap.add_argument("--fix-constraints", action="store_true",
                    help="repair the hard checks src/equity_research/verify_outputs.py reports, in the "
                         "documents already on disk (~$0.25/doc, no pack resend)")
    ap.add_argument("--apply-corrections", action="store_true",
                    help="re-render both documents from their generation records with "
                         "the corrections in config/corrections.toml applied. No model "
                         "call, $0.00, idempotent.")
    add_ticker_arg(ap)

    args = ap.parse_args()

    payload, pack, index = load_pack()
    gen = load_gen_config()
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # Before the backend is constructed, so this path works with neither an API
    # key nor a Claude Code install — it spends nothing and should not require
    # the ability to.
    if args.apply_corrections:
        print(f"Applying corrections — pack {sha[:16]}…")
        rewrite_with_corrections(pack, gen, index, sha)
        return

    backend = model_client.get_backend(
        settings.load_config("llm", P=P), stage="generate_outputs")

    if args.estimate:
        estimate(backend, gen, pack, payload)
        return

    if args.fix_quotes or args.fix_constraints or args.fix_ids:
        fix_on_disk(backend, gen, pack, index, sha, args)
        return

    s = pack["subject"]
    print(f"Generating — {s['ticker']} ({s['company_name']}), "
          f"FY{min(s['fiscal_years'])}-FY{max(s['fiscal_years'])}")
    print(f"  pack {len(index):,} ids, sha256 {sha[:16]}…")
    print(f"  {gen['model']}, effort={gen['effort']}, max_tokens={gen['max_tokens']:,}")
    print(f"  backend={backend.name}"
          + ("  (dollar figures are API-equivalent; a seat is not billed in dollars)"
             if backend.name == "claude_code" else ""))
    print()

    PACK_DIR.mkdir(parents=True, exist_ok=True)
    written, total = [], []
    brief_md = None

    # `brief` first even when only `discussion` was asked for: the second call is
    # given the brief for de-duplication, so it reads the one on disk if the call
    # was skipped. Order is not optional here.
    for slug in ("brief", "discussion"):
        if args.only and args.only != slug:
            if slug == "brief":
                p = OUT_DIR / DOCS["brief"]["file"]
                brief_md = p.read_text(encoding="utf-8") if p.exists() else None
                print(f"  (skipping brief; {'using' if brief_md else 'no'} "
                      f"existing {DOCS['brief']['file']} for de-duplication)")
            continue

        ask = brief_ask(pack, gen) if slug == "brief" else discussion_ask(pack, brief_md)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        text, usage, rounds = generate(backend, gen, index, payload, ask, slug,
                                       args.max_repairs)
        # Recomputed on the FINAL text rather than read off the last repair round:
        # a quotation fix can delete a claim and its citation with it, so the numbers
        # printed and recorded have to describe the document actually being written.
        checks, qchecks = check_citations(text, index), check_quotes(text, index)

        # Saved BEFORE the document is rendered: a crash in rendering must not
        # discard a response that has already been paid for.
        (PACK_DIR / f"gen-{slug}.json").write_text(json.dumps({
            "document": DOCS[slug]["file"], "generated_utc": stamp,
            "model": gen["model"], "effort": gen["effort"],
            # Which engine wrote this, and the cache TTL its usage is priced at.
            # Both are needed to read the record back: the same token counts cost
            # 1.25x or 2.0x depending on the engine, and no field in `usage` says
            # which one produced them.
            "backend": backend.name, "cache_ttl": backend.cache_ttl,
            "pack_sha256": sha, "pack_ids": len(index),
            "ask_sha256": hashlib.sha256(ask.encode("utf-8")).hexdigest(),
            "system_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
            "usage": usage,
            "cost_usd": round(cost(usage, ttl=backend.cache_ttl), 4),
            "rounds": rounds, "citations": checks, "quotations": qchecks, "text": text,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

        p = write_doc(slug, text, pack, gen, sha, usage, checks, qchecks, stamp,
                      backend=backend.name, cache_ttl=backend.cache_ttl)
        if slug == "brief":
            brief_md = text
        written.append((p, checks, qchecks, usage))
        total.append(usage)

        print(f"  {p.relative_to(ROOT)} — {word_count(text):,} words, "
              f"{checks['citations']} citations to {checks['distinct']} distinct facts, "
              f"{qchecks['checked']} quotations ({qchecks['ok']} verbatim in a fact cited "
              f"alongside)")
        if qchecks["bad"]:
            print(f"  !! {len(qchecks['bad'])} quotation(s) match no verified filing text")
        if qchecks["elsewhere"]:
            print(f"  -- {len(qchecks['elsewhere'])} quotation(s) are real filing text but "
                  f"are not in a fact cited in the same paragraph")
        if checks["unknown"]:
            print(f"  !! {len(checks['unknown'])} id(s) STILL do not resolve after "
                  f"{args.max_repairs} repair round(s): {', '.join(checks['unknown'])}")
        if checks["unverified_quote"]:
            print(f"  !! cites {len(checks['unverified_quote'])} fact(s) whose quote is "
                  f"unverified: {', '.join(checks['unverified_quote'])}")
        if checks["low_confidence"]:
            print(f"  -- cites {len(checks['low_confidence'])} low-confidence fact(s); "
                  f"each must be flagged in the text (constraint 1)")
        print(f"     fields cited: {checks['by_field']}")
        print()

    spent = {k: sum(u[k] for u in total) for k in settings.USAGE_KEYS}
    print("=" * 72)
    print(f"{len(written)} document(s), {money(spent, backend)}")
    report_failures(written)


def report_failures(written: list[tuple]) -> None:
    """Exit non-zero if anything unciteable or unquotable survived the repairs.

    Both are fatal and for the same reason: a claim carrying a citation that resolves
    to nothing, or quotation marks around words the filing does not contain, reads as
    MORE sourced than an unsourced sentence. A document that fails either check is
    not a shorter or rougher document, it is a misleading one.
    """
    bad_ids = sum(len(c["unknown"]) for _, c, _, _ in written)
    bad_q = sum(len(q["bad"]) for _, _, q, _ in written)
    if bad_ids or bad_q:
        sys.exit(f"\nFATAL: {bad_ids} unresolvable citation(s) and {bad_q} "
                 f"non-verbatim quotation(s) survived across the outputs. "
                 f"Listed above and in data/pack/gen-*.json.")


def constraint_failures(doc: str, body: str, pack: dict, index: dict, sha: str) -> list[dict]:
    """The hard checks `src/equity_research/verify_outputs.py` reports as failing, for one document.

    Imported inside the function because verify_outputs imports this module — at
    module level the two would form an import cycle. The checks live there and are
    called from here so there is exactly one definition of each constraint.
    """
    import equity_research.verify_outputs as v

    cfg = tomllib.loads((P.config_dir / "outputs.toml").read_text(encoding="utf-8"))
    r = v.verify(doc, body, pack, index, v.pack_facts(pack, index), cfg["verify"], sha)
    # The two provenance checks are dropped: this path is handed the BODY, which has no
    # footer yet, so they would fail on every call and the repair would be asked to
    # write a sha256 into the prose. `write_doc` adds the real footer afterwards.
    # Selected by tag rather than by a substring of the check's prose name, which gets
    # reworded.
    return [f for f in r.failures if f["tag"] not in ("prov_present", "prov_matches")]


def fix_on_disk(backend: model_client.Backend, gen: dict, pack: dict, index: dict,
                sha: str, args) -> None:
    """Re-check and repair documents that already exist.

    Exists because the quotation check was added AFTER the first pair of documents had
    been generated, and regenerating them to fix seven quotations would have cost
    $6 and thrown away analysis that was otherwise sound. The repair needs the
    document and the quote fields in question — not the 354,000-token pack — so this
    path runs at about a twentieth of the price.

    `--fix-ids` joined it for free when the id repair stopped needing the pack.
    That is worth noticing as a design signal rather than a convenience: a repair
    that can run against a document on disk is one whose inputs are all written
    down, which is also what makes it testable without a generation run.

    The body is read from `data/pack/gen-<slug>.json` rather than from the rendered
    Markdown, so the title, lede and provenance footer this script adds are never fed
    back in and re-emitted as if the model had written them.
    """
    written, total = [], []
    for slug, d in DOCS.items():
        if args.only and args.only != slug:
            continue
        rec_path = PACK_DIR / f"gen-{slug}.json"
        if not rec_path.exists():
            sys.exit(f"FATAL: {rec_path} not found — nothing to repair. "
                     f"Generate first: uv run python -m equity_research.generate_outputs")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        if rec.get("pack_sha256") != sha:
            sys.exit(f"FATAL: {d['file']} was written from pack {rec.get('pack_sha256','?')[:16]}…, "
                     f"but the pack on disk is {sha[:16]}…. The evidence moved under the "
                     f"document; regenerate rather than patch it.")

        text, usages, rounds = rec["text"], [], []

        if args.fix_ids:
            before = check_citations(text, index)
            print(f"{d['file']} — {before['citations']} citations to "
                  f"{before['distinct']} distinct facts, "
                  f"{len(before['unknown'])} unresolvable")
            text, id_usages, id_rounds = repair_ids(backend, gen, index, text, slug,
                                                    args.max_repairs)
            usages += id_usages
            rec["citations_before"] = before
            rec["id_repair_rounds"] = id_rounds

        if args.fix_quotes:
            before = check_quotes(text, index)
            print(f"{d['file']} — {before['checked']} quotations, {before['ok']} verbatim "
                  f"in a fact cited alongside, {len(before['elsewhere'])} elsewhere, "
                  f"{len(before['bad'])} matching nothing")
            # `usages +=`, not `usages =`. An id repair may have run first, and
            # rebinding here would drop its tokens from the record — the cost
            # would read as if only the quote repair had happened.
            text, q_usages, rounds = repair_quotes(backend, gen, index, text, slug,
                                                   args.max_repairs)
            usages += q_usages
            rec["quotations_before"] = before

        if args.fix_constraints:
            fails = constraint_failures(d["file"], text, pack, index, sha)
            print(f"{d['file']} — {len(fails)} hard constraint check(s) failing")
            for f in fails:
                print(f"      {f['name']}\n        {f['detail']}")
            if fails:
                text, u = repair_constraints(backend, gen, text, fails, slug)
                usages.append(u)
                rec["constraint_repair_before"] = [
                    {"name": f["name"], "detail": f["detail"]} for f in fails]
                rec["constraint_repair_after"] = [
                    {"name": f["name"], "detail": f["detail"]}
                    for f in constraint_failures(d["file"], text, pack, index, sha)]

        usage = {k: sum(u.get(k, 0) for u in usages) for k in settings.USAGE_KEYS}
        checks, qchecks = check_citations(text, index), check_quotes(text, index)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # The record keeps BOTH costs. The document was paid for twice and the
        # provenance should say so rather than quietly reporting only the repair.
        #
        # It also keeps the PRE-REPAIR TEXT. The first run of this path did not, and
        # the consequence was immediate: with `text` overwritten there was no way to
        # diff what the repair had actually changed, and "did it fix the quotation or
        # quietly delete the claim?" is precisely the question a repair pass has to be
        # auditable on. Never overwrite the only copy of something a model produced.
        rec.setdefault("text_before_repair", rec["text"])
        repair_cost = cost(usage, ttl=backend.cache_ttl)
        rec.update({"repair_utc": stamp, "quote_repair_rounds": rounds,
                    "repair_backend": backend.name,
                    "repair_cache_ttl": backend.cache_ttl,
                    "repair_usage": usage, "repair_cost_usd": round(repair_cost, 4),
                    "quotations": qchecks, "citations": checks, "text": text})
        rec["usage"] = {k: rec["usage"].get(k, 0) + usage[k] for k in usage}
        # The two halves of this sum may have been priced at different multipliers
        # — a document generated through the API and repaired on a seat is the
        # normal case now — so they are added as DOLLARS, already priced, rather
        # than by re-pricing the merged token counts at one TTL.
        rec["cost_usd"] = round(rec["cost_usd"] + repair_cost, 4)
        rec_path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")

        # The record's own backend, not the one doing the repair: the footer
        # describes how the DOCUMENT was produced, and most of its tokens are the
        # generation call's. `rec["cost_usd"]` above already adds the two halves
        # as dollars, each priced at its own multiplier.
        p = write_doc(slug, text, pack, gen, sha, rec["usage"], checks, qchecks, stamp,
                      backend=rec.get("backend", "api"),
                      cache_ttl=rec.get("cache_ttl", "5m"))
        written.append((p, checks, qchecks, usage))
        total.append(usage)
        print(f"  -> {p.relative_to(ROOT)} — {word_count(text):,} words, "
              f"{qchecks['ok']}/{qchecks['checked']} quotations verbatim in a fact cited "
              f"alongside, {len(qchecks['bad'])} matching nothing")
        print()

    spent = {k: sum(u[k] for u in total) for k in settings.USAGE_KEYS}
    print("=" * 72)
    print(f"{len(written)} document(s) repaired, {money(spent, backend)}")
    report_failures(written)


if __name__ == "__main__":
    main()
