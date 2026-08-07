"""Milestone 5e — write `narrative-brief.md` and `discussion-points.md` from the pack.

The first stage in milestone 5 that spends money. Two model calls, sharing one
cached prompt prefix.

Run it:
    uv run python src/generate_outputs.py --estimate     # cost, no spend
    uv run python src/generate_outputs.py                # both documents
    uv run python src/generate_outputs.py --only brief   # one of them

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
breakpoint; everything that differs between the two documents goes after it.

That is the only reason `pack.json` contains no timestamp (see src/build_pack.py):
a single varying byte anywhere in the prefix turns a $0.18 read back into a $1.77
call, with nothing looking broken except the bill.

Measured break-evens for this payload: a 5-minute cache write costs 1.25x input
price and repays itself from 1.4 reads on. Two documents back to back is 2 reads,
so the cache is worth writing — but only while the run is sequential and inside
the TTL. A re-run an hour later pays a fresh write. That is the real cost of
iterating on these prompts and it is printed by --estimate rather than hidden.

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
import hashlib
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()           # use the Windows cert store (corporate SSL)
load_dotenv()

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PACK_DIR = ROOT / "data" / "pack"
OUT_DIR = ROOT / "output"

# Prices per million tokens for the generation model, used only for the estimate
# and the run report. Kept here rather than in config because they describe the
# vendor's price list, not this company or this pipeline.
PRICE_IN = 5.00
PRICE_OUT = 25.00
CACHE_WRITE_MULT = 1.25                # 5-minute ephemeral cache
CACHE_READ_MULT = 0.10

# Any id the pack can mint: field code, fiscal year, 8 hex characters. Built from
# the same code table the ids are built from, so a new field cannot be minted in
# ledger_schema.py and silently become uncheckable here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_schema import FIELD_CODES, ID_HEX, canon  # noqa: E402

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
            sys.exit(f"FATAL: {f} not found.\n  Build it: uv run python src/build_pack.py")
    payload = p.read_text(encoding="utf-8")
    return payload, json.loads(payload), json.loads(i.read_text(encoding="utf-8"))


def load_gen_config() -> dict:
    """Generation settings from config/company.toml, with the reasons alongside them."""
    cfg = tomllib.loads((ROOT / "config" / "company.toml").read_text(encoding="utf-8"))
    if "generation" not in cfg:
        sys.exit("FATAL: config/company.toml has no [generation] block.")
    return cfg["generation"]


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def cached_blocks(payload: str) -> list[dict]:
    """The shared prefix: preamble + pack, with the cache breakpoint on it.

    One block, one breakpoint, identical for both calls. Everything document-specific
    is appended after it by the caller.
    """
    return [{"type": "text", "text": PACK_PREAMBLE + payload,
             "cache_control": {"type": "ephemeral"}}]


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

def run(client: anthropic.Anthropic, gen: dict, blocks: list[dict],
        label: str) -> tuple[str, dict]:
    """One streamed call. Returns (text, usage).

    Streamed because a high-effort call over a 353k-token pack can run past the
    non-streaming request timeout; a request that dies at the timeout has still been
    paid for. Streaming also means a stall is visible rather than looking like a hang.
    """
    print(f"  calling ({label}) …", end="", flush=True)
    with client.messages.stream(
        model=gen["model"],
        max_tokens=gen["max_tokens"],
        output_config={"effort": gen["effort"]},
        system=[{"type": "text", "text": SYSTEM}],
        messages=[{"role": "user", "content": blocks}],
    ) as stream:
        msg = stream.get_final_message()

    u = msg.usage
    usage = {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
    print(f" {usage['output_tokens']:,} out, "
          f"{usage['cache_read_input_tokens']:,} cached, ${cost(usage):.2f}")

    # A document cut off at max_tokens is a failed call, not a shorter document: the
    # last section is missing and nothing in the file says so.
    if msg.stop_reason == "max_tokens":
        sys.exit(f"FATAL: {label} hit max_tokens ({gen['max_tokens']}) — the document is "
                 f"truncated.\n  Raise max_tokens in config/company.toml [generation].")
    if msg.stop_reason == "refusal":
        sys.exit(f"FATAL: {label} — model declined: {msg.stop_details}")

    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not text:
        sys.exit(f"FATAL: {label} returned no text (stop_reason={msg.stop_reason}).")
    return text, usage


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


def repair_quotes(client: anthropic.Anthropic, gen: dict, index: dict, md: str,
                  label: str, max_rounds: int) -> tuple[str, list[dict], list[dict]]:
    """Hold the finished document to its quotations.

    Deliberately does NOT resend the pack. The fix needs the document and the handful
    of quote fields in question — about 8,000 tokens against 354,000 — so this runs at
    roughly $0.20 a round instead of $2.22, and can be run against documents already
    on disk without regenerating them.
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
        print(f"  calling ({label} quote repair {n}) …", end="", flush=True)
        with client.messages.stream(
            model=gen["model"], max_tokens=gen["max_tokens"],
            output_config={"effort": gen["repair_effort"]},
            system=[{"type": "text", "text": SYSTEM}],
            messages=[{"role": "user", "content": QUOTE_FIX.format(
                group_a=_problem_block(bad, with_source=False),
                group_b=_problem_block(elsew, with_source=True), doc=md)}],
        ) as stream:
            msg = stream.get_final_message()
        u = msg.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                 "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
        print(f" {usage['output_tokens']:,} out, ${cost(usage):.2f}")
        if msg.stop_reason == "max_tokens":
            sys.exit(f"FATAL: {label} quote repair {n} hit max_tokens — document truncated.")
        fixed = "".join(b.text for b in msg.content if b.type == "text").strip()
        if not fixed:
            sys.exit(f"FATAL: {label} quote repair {n} returned no text.")
        md = fixed
        usages.append(usage)
        rounds.append({"round": n, "usage": usage, "checks": check_quotes(md, index)})
    return md, usages, rounds


def cost(u: dict) -> float:
    return (u["input_tokens"] * PRICE_IN
            + u["cache_creation_input_tokens"] * PRICE_IN * CACHE_WRITE_MULT
            + u["cache_read_input_tokens"] * PRICE_IN * CACHE_READ_MULT
            + u["output_tokens"] * PRICE_OUT) / 1e6


def generate(client: anthropic.Anthropic, gen: dict, index: dict, payload: str,
             ask: str, label: str, max_repairs: int) -> tuple[str, dict, list[dict]]:
    """Generate one document, then hold it to its citations.

    If ids do not resolve, the model is shown exactly which ones and asked to fix
    them, in the same conversation so the pack is a cache read rather than a second
    full-price send. Two rounds at most: an id it cannot fix twice is one the pack
    does not contain, and the instruction is to drop the sentence.
    """
    blocks = cached_blocks(payload) + [{"type": "text", "text": ask}]
    text, usage = run(client, gen, blocks, label)
    usages = [usage]
    rounds = [{"round": 0, "usage": usage, "checks": check_citations(text, index)}]

    for n in range(1, max_repairs + 1):
        chk = rounds[-1]["checks"]
        if not chk["unknown"]:
            break
        print(f"  {len(chk['unknown'])} unresolvable id(s) — repair round {n}: "
              + ", ".join(chk["unknown"][:6])
              + (" …" if len(chk["unknown"]) > 6 else ""))
        repair = (
            "These ids in your document do not exist in the pack:\n\n"
            + "\n".join(f"  {c}" for c in chk["unknown"])
            + "\n\nEach one is a citation to nothing. For each, either find the fact you "
              "meant and copy its real id character for character, or delete the claim it "
              "supports. Do not invent a replacement id and do not keep a sentence whose "
              "only support was one of these.\n\n"
              "Return the complete corrected document in the same format. Change nothing "
              "else.")
        blocks2 = (cached_blocks(payload) + [{"type": "text", "text": ask}])
        msgs = [{"role": "user", "content": blocks2},
                {"role": "assistant", "content": [{"type": "text", "text": text}]},
                {"role": "user", "content": repair}]
        print(f"  calling ({label} repair {n}) …", end="", flush=True)
        with client.messages.stream(
            model=gen["model"], max_tokens=gen["max_tokens"],
            output_config={"effort": gen["effort"]},
            system=[{"type": "text", "text": SYSTEM}], messages=msgs,
        ) as stream:
            msg = stream.get_final_message()
        u = msg.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                 "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
        print(f" {usage['output_tokens']:,} out, ${cost(usage):.2f}")
        if msg.stop_reason == "max_tokens":
            sys.exit(f"FATAL: {label} repair {n} hit max_tokens — document truncated.")
        fixed = "".join(b.text for b in msg.content if b.type == "text").strip()
        if not fixed:
            sys.exit(f"FATAL: {label} repair {n} returned no text.")
        text = fixed
        usages.append(usage)
        rounds.append({"round": n, "usage": usage, "checks": check_citations(text, index)})

    # Quotations are checked AFTER the ids, and separately, because fixing a
    # quotation may delete the claim it supported and therefore its citation — so the
    # id check has to run once more at the end, on the document that will be written.
    text, q_usages, q_rounds = repair_quotes(client, gen, index, text, label, max_repairs)
    usages += q_usages
    rounds.append({"stage": "quotes", "rounds": q_rounds})

    return text, {k: sum(u[k] for u in usages) for k in usages[0]}, rounds


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def provenance(pack: dict, gen: dict, sha: str, usage: dict, checks: dict, q: dict,
               words: int, stamp: str) -> str:
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
        f"input tokens, **{usage['output_tokens']:,}** output, **${cost(usage):.2f}**.",
        "",
        "Ids resolve in `data/pack/index.json` to the exact quote, section and accession "
        "each claim rests on. `claim` text in the pack is a model-written summary and is "
        "not quoted here; every quotation is copied from a `quote` field verified to "
        "occur in the named filing section.",
    ])


DOCS = {
    "brief": {"file": "narrative-brief.md", "title": "{name} ({ticker}) — Narrative brief, {span}",
              "lede": "A five-year read of what changed and what it appears to indicate, "
                      "drawn only from the company's own SEC filings."},
    "discussion": {"file": "discussion-points.md",
                   "title": "{name} ({ticker}) — Discussion points, {span}",
                   "lede": "Patterns across the window, the questions they raise, and where "
                           "stated priorities and paid-for priorities diverge."},
}


def write_doc(slug: str, body: str, pack: dict, gen: dict, sha: str, usage: dict,
              checks: dict, q: dict, stamp: str) -> Path:
    s = pack["subject"]
    span = f"FY{min(s['fiscal_years'])}–FY{max(s['fiscal_years'])}"
    d = DOCS[slug]
    head = d["title"].format(name=s["company_name"], ticker=s["ticker"], span=span)
    md = "\n".join([f"# {head}", "", d["lede"], "", body.strip(),
                    provenance(pack, gen, sha, usage, checks, q, word_count(body), stamp), ""])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / d["file"]
    p.write_text(md, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def estimate(client: anthropic.Anthropic, gen: dict, pack: dict, payload: str) -> None:
    """What both documents will cost, before spending anything.

    Input is counted exactly; output cannot be counted in advance and is bounded by
    max_tokens, which is a deliberate over-estimate and labelled as one.
    """
    n = client.messages.count_tokens(
        model=gen["model"], system=[{"type": "text", "text": SYSTEM}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PACK_PREAMBLE + payload},
            {"type": "text", "text": brief_ask(pack, gen)}]}]).input_tokens

    write = n * PRICE_IN * CACHE_WRITE_MULT / 1e6
    read = n * PRICE_IN * CACHE_READ_MULT / 1e6
    full = n * PRICE_IN / 1e6
    out_max = 2 * gen["max_tokens"] * PRICE_OUT / 1e6

    print(f"Estimate — {gen['model']}, effort={gen['effort']}, "
          f"max_tokens={gen['max_tokens']:,}")
    print()
    print(f"  prompt: {n:,} tokens (system + pack + ask)")
    print()
    print(f"  call 1  narrative-brief      cache WRITE   ${write:.2f}")
    print(f"  call 2  discussion-points    cache READ    ${read:.2f}  "
          f"(+ the brief, a few thousand tokens)")
    print(f"  input, this run                            ${write + read:.2f}"
          f"   vs ${2 * full:.2f} uncached")
    print(f"  output, worst case                         ${out_max:.2f}  "
          f"(2 x max_tokens; the real figure will be well under)")
    print()
    print(f"  TOTAL, worst case                          ${write + read + out_max:.2f}")
    print()
    print("  A repair round, if citations do not resolve, is a cache read plus one "
          "output: ~$0.30.")
    print(f"  A RE-RUN more than 5 minutes later pays a fresh cache write "
          f"(${write:.2f}), not a read.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 5e — generate the two prose outputs.")
    ap.add_argument("--estimate", action="store_true", help="print the cost and exit")
    ap.add_argument("--only", choices=["brief", "discussion"], help="one document only")
    ap.add_argument("--max-repairs", type=int, default=2,
                    help="citation repair rounds per document (default 2, 0 to disable)")
    ap.add_argument("--fix-quotes", action="store_true",
                    help="re-check and repair the quotations in the documents already on "
                         "disk, without regenerating them (~$0.20/doc, no pack resend)")
    args = ap.parse_args()

    payload, pack, index = load_pack()
    gen = load_gen_config()
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    client = anthropic.Anthropic()

    if args.estimate:
        estimate(client, gen, pack, payload)
        return

    if args.fix_quotes:
        fix_quotes_on_disk(client, gen, pack, index, sha, args)
        return

    s = pack["subject"]
    print(f"Generating — {s['ticker']} ({s['company_name']}), "
          f"FY{min(s['fiscal_years'])}-FY{max(s['fiscal_years'])}")
    print(f"  pack {len(index):,} ids, sha256 {sha[:16]}…")
    print(f"  {gen['model']}, effort={gen['effort']}, max_tokens={gen['max_tokens']:,}")
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
        text, usage, rounds = generate(client, gen, index, payload, ask, slug,
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
            "pack_sha256": sha, "pack_ids": len(index),
            "ask_sha256": hashlib.sha256(ask.encode("utf-8")).hexdigest(),
            "system_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
            "usage": usage, "cost_usd": round(cost(usage), 4),
            "rounds": rounds, "citations": checks, "quotations": qchecks, "text": text,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

        p = write_doc(slug, text, pack, gen, sha, usage, checks, qchecks, stamp)
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

    spent = sum(cost(u) for u in total)
    print("=" * 72)
    print(f"{len(written)} document(s), ${spent:.2f}")
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


def fix_quotes_on_disk(client: anthropic.Anthropic, gen: dict, pack: dict, index: dict,
                       sha: str, args) -> None:
    """Re-check and repair quotations in documents that already exist.

    Exists because the quotation check was added AFTER the first pair of documents had
    been generated, and regenerating them to fix seven quotations would have cost
    $6 and thrown away analysis that was otherwise sound. The repair needs the
    document and the quote fields in question — not the 354,000-token pack — so this
    path runs at about a twentieth of the price.

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
                     f"Generate first: uv run python src/generate_outputs.py")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        if rec.get("pack_sha256") != sha:
            sys.exit(f"FATAL: {d['file']} was written from pack {rec.get('pack_sha256','?')[:16]}…, "
                     f"but the pack on disk is {sha[:16]}…. The evidence moved under the "
                     f"document; regenerate rather than patch it.")

        before = check_quotes(rec["text"], index)
        print(f"{d['file']} — {before['checked']} quotations, {before['ok']} verbatim in a "
              f"fact cited alongside, {len(before['elsewhere'])} elsewhere, "
              f"{len(before['bad'])} matching nothing")
        text, usages, rounds = repair_quotes(client, gen, index, rec["text"], slug,
                                             args.max_repairs)
        usage = ({k: sum(u[k] for u in usages) for k in usages[0]} if usages else
                 {k: 0 for k in ("input_tokens", "output_tokens",
                                 "cache_creation_input_tokens", "cache_read_input_tokens")})
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
        rec.setdefault("text_before_quote_repair", rec["text"])
        rec.update({"quote_repair_utc": stamp, "quote_repair_rounds": rounds,
                    "quote_repair_usage": usage,
                    "quote_repair_cost_usd": round(cost(usage), 4),
                    "quotations_before": before, "quotations": qchecks,
                    "citations": checks, "text": text})
        rec["usage"] = {k: rec["usage"].get(k, 0) + usage[k] for k in usage}
        rec["cost_usd"] = round(rec["cost_usd"] + cost(usage), 4)
        rec_path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")

        p = write_doc(slug, text, pack, gen, sha, rec["usage"], checks, qchecks, stamp)
        written.append((p, checks, qchecks, usage))
        total.append(usage)
        print(f"  -> {p.relative_to(ROOT)} — {word_count(text):,} words, "
              f"{qchecks['ok']}/{qchecks['checked']} quotations verbatim in a fact cited "
              f"alongside, {len(qchecks['bad'])} matching nothing")
        print()

    print("=" * 72)
    print(f"{len(written)} document(s) repaired, ${sum(cost(u) for u in total):.2f}")
    report_failures(written)


if __name__ == "__main__":
    main()
