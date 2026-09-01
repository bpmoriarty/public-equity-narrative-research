"""Milestone 3 — Section extraction.

Locates the target sections defined in SPEC.md inside the cached filings and
writes cleaned text to data/sections/. Section-targeted, not linear: a 10-K runs
420,000 characters of text and the three in-scope items are a fraction of it.

Run it:
    uv run python -m equity_research.extract_sections                  # everything
    uv run python -m equity_research.extract_sections --form 10-K      # one form type
    uv run python -m equity_research.extract_sections --fy 2021        # one fiscal year
    uv run python -m equity_research.extract_sections --show 10-K_item1a_risk_factors --fy 2021

Writes:
    data/sections/FY<year>/<form>/<accession>/<key>.txt
    data/sections/FY<year>/<form>/<accession>/<key>.factors.json   (risk factors)
    data/sections/sections-manifest.json
    data/sections/extraction-report.md

No network access. No model calls. Pure local parsing, so it is cheap to re-run
and safe to iterate on.

===========================================================================
FORMAT FACTS, verified against real MORN filings before any of this was written
===========================================================================
1. All 194 cached text documents are valid UTF-8. No encoding guessing needed.

2. BUT the proxies carry NUMERIC CHARACTER REFERENCES in the Windows-1252 range
   (&#146; x278, &#151; x224, &#149; x213 in the FY2021 proxy alone). Those code
   points are C1 control characters in Unicode. The HTML5 spec says a parser must
   remap them to the characters the author meant; lxml does not. Unfixed, every
   apostrophe, bullet and em dash in every proxy arrives as a control character
   and ends up inside quoted passages. See CP1252_REMAP.

3. 10-K item headings are reliably identifiable: a text node whose content
   STARTS with "Item N." and which is NOT inside an <a> tag. In the FY2021 10-K
   that yields a clean 16 real headings / 16 table-of-contents links split.
   Two traps this avoids:
     - "take the last match" picks a mid-prose cross-reference ("...described in
       Item 1A-Risk Factors"), not the heading.
     - capping the heading length too tightly loses the real ones: "Item 7.
       Management's Discussion and Analysis of Financial Condition and Results of
       Operations" is 92 characters.

4. A 10-K section therefore needs NO end pattern. It runs from its own heading to
   the next heading in document order, which is self-consistent and cannot
   over-capture into the financial statements.

5. Inside Item 1A, individual risk factors are marked by
   font-weight:700 + font-style:italic, while the category headings ("Risks
   Related to Our Business and Industry") are font-weight:700 alone and the body
   is font-weight:400. That distinction is what makes SPEC.md's year-over-year
   risk factor diffing possible at all. The non-bold summary list at the top of
   Item 1A is naturally excluded, which matters: it repeats every factor title
   and would otherwise double-count them.

6. Proxies have no item numbering, so headings are matched on their text and
   selected by anchor-phrase content — see find_proxy_sections.

7. An ARS filing is NOT the shareholder letter. It is the complete annual report
   and it contains the entire 10-K: the four cached MORN filings run 436,000 to
   621,000 characters, of which the letter is 29,600 to 37,500. The letter has to
   be located inside it, and it is bounded by letter conventions rather than
   filing structure — a salutation opening and a sign-off closing, each verified
   to occur exactly once per document. See extract_letter.

===========================================================================
KNOWN LIMITS — what to trust and what not to
===========================================================================
TRUSTED, hand-verified against the source documents:
  - All three 10-K sections, all five years. Boundaries are structural (item
    heading to next item heading) and the item map is identical across years:
    21 items, 1->1A, 1A->1B, 7->7A. Risk factors split cleanly, 18-25 per year.
  - DEF14A_cdna: FY2022 checked end-to-end. Starts at the CD&A heading, ends on
    the compensation-consultant fee discussion immediately before the Summary
    Compensation Table. Sizes are consistent across years (34k-43k).
  - DEF14A_incentive_tables: consistent across all five years (13k-17k).

NOT VERIFIED — do not build load-bearing claims on these without checking:
  - DEF14A_director_bios. FY2025 is KNOWN WRONG: it starts at the
    front-of-proxy voting summary ("Proposal 1: Election of Directors  FOR the
    election of each of the 10 director nominees... Page 9") rather than at the
    bios, and ends inside the board-composition table. The real heading is a
    second, later "Election of Directors" at node 3525. The other four years are
    plausible in size but unverified.
  - DEF14A_proposals_and_votes. FY2022 (6,883 chars) was checked and is tight
    and correct: say-on-pay plus auditor ratification. The other four years are
    21k-25k, which suggests THEY over-capture rather than FY2022 being short.

Both remaining problems are the same shape: a proxy heading appears once in the
front-of-proxy summary and again at the real section, and no single global rule
separates them across all years and all four sections. Fixing them properly
means per-section, per-year boundary verification, not another global threshold —
three were tried (largest-span, run-grouped end search, anchor-scored selection)
and each fixed one section while breaking another.

Consequence for the ledger: board-composition and vote-outcome fields drawn from
these two sections are lower-confidence than everything else, and the say-on-pay
OUTCOMES are better taken from the 8-K item 5.07 filings anyway, which are
extracted whole and need no boundary detection at all.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from equity_research import settings
from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

# Inline-XBRL filings are XHTML; parsing them with the HTML parser is correct and
# standard, so silence the advisory warning rather than switching parsers (the
# XML parser is stricter and chokes on real-world filing markup).
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Config is resolved per file by `settings.load_config` — company.toml from the
# company folder, forms/sections from config/ — so there is no directory constant.
MANIFEST = P.fetch_manifest
OUT_DIR = P.sections

# HTML5's replacement table for numeric character references in the C1 range.
# Format fact 2 above: without this, proxies are full of control characters.
CP1252_REMAP = {
    0x80: "€", 0x82: "‚", 0x83: "ƒ", 0x84: "„", 0x85: "…",
    0x86: "†", 0x87: "‡", 0x88: "ˆ", 0x89: "‰", 0x8A: "Š",
    0x8B: "‹", 0x8C: "Œ", 0x8E: "Ž", 0x91: "‘", 0x92: "’",
    0x93: "“", 0x94: "”", 0x95: "•", 0x96: "–", 0x97: "—",
    0x98: "˜", 0x99: "™", 0x9A: "š", 0x9B: "›", 0x9C: "œ",
    0x9E: "ž", 0x9F: "Ÿ",
}

ITEM_HEADING = re.compile(r"^\s*item\s+(\d{1,2}[ab]?)\s*[\.\:\-—–]", re.I)
MAX_HEADING_CHARS = 250          # generous: real Item 7 titles run past 90
ANCHOR_FLOOR = 0.9               # proxy candidate selection; see find_proxy_sections
BLOCK_TAGS = {"p", "div", "tr", "li", "td", "th", "h1", "h2", "h3", "h4", "br", "table"}


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

def fix_chars(s: str) -> str:
    """Apply the HTML5 C1 remap. See format fact 2."""
    return s.translate(CP1252_REMAP)


def norm(s: str) -> str:
    """Collapse whitespace and repair C1 characters. For matching and output."""
    return " ".join(fix_chars(s).split())


def slug(s: str) -> str:
    """Make a form type or document type safe to use as a path component.

    'DEF 14A' -> 'DEF-14A', '8-K/A' -> '8-K-A'. The slash matters: form '8-K/A'
    produced the section key '8-K/A_8-K/A_whole', which the filesystem read as
    nested directories that did not exist.
    """
    return s.replace(" ", "-").replace("/", "-").strip("-")


class Doc:
    """A parsed filing, exposing its text nodes in document order.

    Text nodes are the unit of work because section boundaries are marked by
    individual strings, and positions have to be compared by IDENTITY: the same
    heading text appears in both the table of contents and the body, so
    list.index() (which compares by value) silently returns the wrong one.
    """

    def __init__(self, path: Path):
        self.path = path
        raw = path.read_bytes().decode("utf-8", errors="replace")
        self.soup = BeautifulSoup(raw, "lxml")
        root = self.soup.body or self.soup
        self.nodes = [n for n in root.descendants if isinstance(n, str)]
        self.pos = {id(n): i for i, n in enumerate(self.nodes)}
        self.texts = [norm(str(n)) for n in self.nodes]

    def is_in_link(self, i: int) -> bool:
        return any(getattr(a, "name", None) == "a" for a in self.nodes[i].parents)

    def style_of(self, i: int, depth: int = 4) -> str:
        """Concatenated inline styles of a node's nearest ancestors."""
        out = []
        for anc in list(self.nodes[i].parents)[:depth]:
            if getattr(anc, "name", None) in ("b", "strong"):
                out.append("font-weight:700")
            if hasattr(anc, "get"):
                out.append((anc.get("style") or ""))
        return ";".join(out)

    def is_bold(self, i: int) -> bool:
        return bool(re.search(r"font-weight:\s*(bold|[7-9]00)", self.style_of(i)))

    def is_italic(self, i: int) -> bool:
        return "font-style:italic" in self.style_of(i)

    def block_key(self, i: int) -> int:
        """Identity of the node's nearest block-level ancestor.

        Used to reinsert paragraph breaks: consecutive text nodes inside the same
        block belong to one paragraph, a change of block starts a new one.
        """
        for anc in self.nodes[i].parents:
            if getattr(anc, "name", None) in BLOCK_TAGS:
                return id(anc)
        return 0

    def text_span(self, i0: int, i1: int) -> str:
        """Reconstruct readable text for nodes [i0, i1), preserving paragraphs."""
        parts: list[str] = []
        last_block = None
        for i in range(i0, min(i1, len(self.nodes))):
            t = self.texts[i]
            if not t:
                continue
            blk = self.block_key(i)
            if last_block is not None and blk != last_block:
                parts.append("\n")
            parts.append(t if parts and parts[-1] == "\n" else (" " + t if parts else t))
            last_block = blk
        out = "".join(parts)
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


# ---------------------------------------------------------------------------
# 10-K
# ---------------------------------------------------------------------------

def find_item_heading_candidates(doc: Doc) -> list[tuple[str, int]]:
    """EVERY node that reads as a 10-K item heading, in document order.

    Deliberately unfiltered beyond two cheap structural rules — too long to be a
    heading, or sitting inside a hyperlink. Choosing among the survivors is
    `extract_10k`'s job, and it needs to see all of them to choose.

    The hyperlink rule is the older of the two table-of-contents defences and it
    is kept because it is free and correct where it applies: MORN's TOC is a list
    of anchors, so this removes it outright. It is not sufficient — MSFT's TOC is
    a plain table with no anchors at all — which is what span selection below is
    for. Format fact 3.
    """
    found = []
    for i, t in enumerate(doc.texts):
        if not t or len(t) > MAX_HEADING_CHARS:
            continue
        m = ITEM_HEADING.match(t)
        if not m or doc.is_in_link(i):
            continue
        found.append((m.group(1).upper(), i))
    found.sort(key=lambda x: x[1])
    return found


def find_item_headings(doc: Doc) -> list[tuple[str, int]]:
    """First surviving occurrence of each item number, in document order.

    Retained with its original contract. `extract_10k` no longer uses it: taking
    the first occurrence is precisely the table-of-contents bug (see below).
    """
    seen, out = set(), []
    for num, i in find_item_heading_candidates(doc):
        if num not in seen:
            seen.add(num)
            out.append((num, i))
    return out


def extract_10k(doc: Doc, min_section_chars: int) -> dict[str, dict]:
    """Item 1, Item 1A and Item 7, each running to the next item heading.

    THE TABLE-OF-CONTENTS TRAP, and why "first occurrence" was the wrong rule.

    Every 10-K names each item at least twice: once in the table of contents and
    once where the section actually begins. This used to take the first surviving
    occurrence, which is right only when something else has already removed the
    TOC. For MORN something had — its TOC is a list of hyperlinks, and
    `find_item_heading_candidates` drops those — so the rule looked general for
    five years and one company.

    MSFT's TOC is a plain table with no anchors, so nothing removed it, and every
    10-K section for six years came back as a TOC row:

        'Item 1.\\nBusiness\\n3\\nExecutive Officers of the Registrant\\n17'

    58 characters, page numbers included. It failed loudly — `min_chars` in
    [validation] caught all eighteen — but failing loudly six times is not the
    same as working.

    WHAT REPLACED IT. Among the candidates for one item number, take the first
    whose span reaches `min_section_chars`. That is the same floor validation
    applies afterwards, moved to where it can DECIDE rather than only complain,
    and it asks the question that actually matters: which of these occurrences
    yields a real section? It needs no knowledge of what a TOC looks like, so it
    also handles running page headers, cross-references and a TOC that is neither
    a link nor a table. The separation it keys on is not marginal — in both
    companies the TOC span is under 100 characters and the body span is over
    55,000.

    A provisional end (the next candidate of ANY item number) is used while
    choosing, and the final end comes from the chosen set. The provisional span is
    never longer than the final one, so a candidate that clears the floor
    provisionally still clears it afterwards.

    IF NO CANDIDATE CLEARS THE FLOOR, the one with the LARGEST span is used, and
    that fallback is load-bearing rather than cosmetic. Most 10-K items are not
    extracted here but every one of them is a TERMINATOR for the item before it,
    and some are genuinely shorter than the floor — Item 7A is often a single
    sensitivity table. Falling back to the *first* candidate picks such an item's
    table-of-contents row, which sits before the preceding section's body heading
    and therefore fails to end it: MSFT's Item 7 swallowed Item 7A that way, and
    it was found by reading where the section stopped, not by any check. Largest
    span picks the body heading, which terminates correctly.

    Either way the chosen span is still validated afterwards, so a genuinely
    unrecognised layout produces the same loud failure it did before rather than a
    silent skip. CLAUDE.md: fail loudly, and never let a change to a boundary rule
    turn a visible failure into an invisible one.
    """
    cands = find_item_heading_candidates(doc)
    if not cands:
        return {}
    positions = [i for _, i in cands]

    by_num: dict[str, list[int]] = {}
    for num, i in cands:
        by_num.setdefault(num, []).append(i)

    def provisional_span(i0: int) -> int:
        nxt = next((j for j in positions if j > i0), len(doc.nodes))
        return len(doc.text_span(i0, nxt))

    # One heading per item number, chosen rather than assumed.
    chosen: dict[str, int] = {}
    basis: dict[str, str] = {}
    for num, occurrences in by_num.items():
        pick = next((i for i in occurrences if provisional_span(i) >= min_section_chars),
                    None)
        if pick is not None:
            chosen[num] = pick
            basis[num] = (f"first of {len(occurrences)} candidate(s) to reach "
                          f"{min_section_chars:,} chars"
                          if len(occurrences) > 1 else "sole candidate")
        else:
            # Largest, not first. See the docstring: a short item's TOC row would
            # otherwise be chosen and would fail to terminate the item before it.
            # max() with a key is stable on ties, so the earliest of equal spans
            # wins and a re-run picks the same node.
            chosen[num] = max(occurrences, key=provisional_span)
            basis[num] = (f"largest of {len(occurrences)} candidate(s); none "
                          f"reached {min_section_chars:,} chars")

    order = sorted(chosen.values())

    wanted = {
        "1":  "10-K_item1_business",
        "1A": "10-K_item1a_risk_factors",
        "7":  "10-K_item7_mdna",
    }
    out: dict[str, dict] = {}
    for num, key in wanted.items():
        if num not in chosen:
            out[key] = {"error": f"Item {num} heading not found among {sorted(by_num)}"}
            continue
        i0 = chosen[num]
        later = [i for i in order if i > i0]
        i1 = later[0] if later else len(doc.nodes)
        out[key] = {
            "text": doc.text_span(i0, i1),
            "node_range": [i0, i1],
            "boundary_basis": f"Item {num} heading -> next item heading "
                              f"({basis[num]})",
            "items_found": len(chosen),
        }
    return out


def split_risk_factors(doc: Doc, i0: int, i1: int) -> list[dict]:
    """Split Item 1A into individual risk factors. Format fact 5.

    bold + italic  -> an individual risk factor heading
    bold only      -> a category heading, recorded as context, not a factor
    """
    marks: list[tuple[int, str, str]] = []
    for i in range(i0, i1):
        t = doc.texts[i]
        if len(t) < 20 or not doc.is_bold(i):
            continue
        marks.append((i, "factor" if doc.is_italic(i) else "category", t))

    factors: list[dict] = []
    category = None
    for j, (i, kind, text) in enumerate(marks):
        if kind == "category":
            category = text
            continue
        nxt = marks[j + 1][0] if j + 1 < len(marks) else i1
        body = doc.text_span(i, nxt)
        # The heading is itself the risk statement; strip it off the body so the
        # two are not stored twice.
        body_only = body[len(text):].strip() if body.startswith(text) else body
        factors.append({
            "heading": text,
            "category": category,
            "body_chars": len(body_only),
            "body": body_only,
        })

    # HEADINGS SPLIT ACROSS TEXT NODES.
    #
    # A long risk statement is sometimes broken into two bold+italic text nodes
    # mid-sentence, and each looks like a separate factor. In the FY2024 10-K:
    #
    #   "...ultimately having an adverse effect on our operating results and"
    #   "our ability to deliver long-term value to our shareholders."
    #
    # That inflated the factor count by one and put a sentence fragment into the
    # year-over-year diff as a phantom deleted risk factor.
    #
    # The tell is unambiguous and needs no heuristic threshold: the first half has
    # a body of EXACTLY ZERO characters, because the only thing between it and the
    # next heading is that next heading. A genuine risk factor always has
    # paragraphs of discussion beneath it. So an empty-bodied factor is not a
    # factor at all — it is the first half of the one that follows it.
    merged: list[dict] = []
    for f in factors:
        if merged and merged[-1]["body_chars"] == 0:
            prev = merged.pop()
            f = {**f,
                 "heading": f"{prev['heading']} {f['heading']}",
                 "category": prev["category"] or f["category"],
                 "heading_was_split": True}
        merged.append(f)
    return merged


# ---------------------------------------------------------------------------
# DEF 14A
# ---------------------------------------------------------------------------

# Each proxy section carries its OWN start and end patterns, mirroring
# config/sections.toml. A single global set of end markers does not work: an end
# phrase for one section legitimately appears inside another, and inside the
# proxy summary at the front. Making the markers global cut the director section
# from 61,643 characters to 13,951 by firing on the "Corporate Governance
# Highlights" line in the front-of-proxy summary.
PROXY_SECTIONS: dict[str, tuple[str, list[str], list[str]]] = {
    "DEF14A_cdna": (
        r"^compensation\s+discussion\s+and\s+analysis$",
        [r"^(\d{4}\s+)?summary\s+compensation\s+table$",
         r"^compensation\s+committee\s+report$",
         r"^potential\s+payments\s+upon\s+termination"],
        ["annual incentive", "performance", "compensation committee"],
    ),
    "DEF14A_incentive_tables": (
        r"^(\d{4}\s+)?summary\s+compensation\s+table$",
        [r"^(\d{4}\s+)?director\s+compensation( table)?$",
         r"^pay\s+(versus|vs\.?)\s+performance$",
         r"^equity\s+compensation\s+plan\s+information$",
         r"^security\s+ownership"],
        ["salary", "stock awards"],
    ),
    "DEF14A_director_bios": (
        r"^(proposal\s*\d*[\.\:\-\s]*)?election\s+of\s+directors$",
        [r"^compensation\s+discussion\s+and\s+analysis$",
         r"^(report of the )?audit\s+committee( report)?$",
         r"^(\d{4}\s+)?director\s+compensation( table)?$"],
        ["director since", "committee"],
    ),
    "DEF14A_proposals_and_votes": (
        r"^(advisory\s+vote\s+to\s+approve\s+executive\s+compensation"
        r"|(share|stock)holder\s+proposals?(\s+or\s+nominations)?)$",
        [r"^(report of the )?audit\s+committee( report)?$",
         r"^other\s+(business|matters)$",
         r"^additional\s+information$"],
        ["proposal", "vote"],
    ),
}



def find_proxy_sections(doc: Doc) -> dict[str, dict]:
    """Locate proxy sections by heading text, disambiguated by span size.

    Proxies have no item numbers, and a phrase like "Election of Directors"
    appears many times: in the table of contents, in the meeting-notice summary,
    as a running header, and as the real section heading. Two rules cut through:

      1. Drop anything inside an <a> (table of contents).
      2. Among the remaining candidates, the REAL section is the one followed by
         the most text before the next candidate heading of any kind. A
         notice-of-meeting mention is followed by a few hundred characters; the
         real section is followed by tens of thousands.

    Rule 2 is a heuristic, so every result is length- and anchor-validated
    afterwards and failures are reported rather than written.
    """
    def matches(pattern: str) -> list[int]:
        rx = re.compile(pattern, re.I)
        return [i for i, t in enumerate(doc.texts)
                if t and len(t) <= 90 and rx.match(t) and not doc.is_in_link(i)]

    out: dict[str, dict] = {}
    for key, (start_pat, end_pats, anchors) in PROXY_SECTIONS.items():
        starts = matches(start_pat)
        if not starts:
            out[key] = {"error": "no heading candidate found"}
            continue

        # ANCHOR-SCORED SELECTION.
        #
        # Two earlier rules both failed, in opposite directions:
        #
        #  - "largest following span" started at the front-of-proxy voting summary
        #    ("Proposal 1: Election of Directors  FOR the election of each of the 10
        #    director nominees... Page 9") instead of the real bios section.
        #  - ending the span after the run's LAST page header overshot, because the
        #    running header continues past the section's real end: FY2022 CD&A ran
        #    into the Option Exercises table, 56,457 chars against a true ~43,000.
        #
        # So: end each candidate at the first of its own end patterns after its OWN
        # start, then choose by CONTENT rather than by position or size. The
        # characteristic phrases of the section (config's anchor_phrases: "director
        # since", "annual incentive", ...) recur once per director or per pay
        # element, so the real section is dense with them and a summary mention is
        # not. Among candidates carrying essentially all that content, take the
        # SHORTEST — the tightest span that still contains the section. A span
        # starting at the summary also contains the real section, so it ties on
        # content and loses on tightness, which is exactly the discrimination the
        # earlier rules lacked.
        ends_all = sorted({i for p in end_pats for i in matches(p)})
        scored = []
        for i in starts:
            after = [e for e in ends_all if e > i]
            i1 = after[0] if after else len(doc.nodes)
            body = " ".join(doc.texts[i:i1]).lower()
            hits = sum(body.count(a.lower()) for a in anchors)
            scored.append({"start": i, "end": i1, "anchor_hits": hits,
                           "chars": sum(len(doc.texts[k]) for k in range(i, i1))})
        best_hits = max(s["anchor_hits"] for s in scored)
        # ANCHOR_FLOOR is 0.9 after measuring both directions. It was tried at 0.6
        # to admit the correct tighter span for FY2025 director bios (which misses
        # the 0.9 cut by a single anchor hit, 10 vs 10.8) — but that loosening made
        # CD&A UNDER-capture instead: FY2022 fell from a hand-verified 43,123 chars
        # to 32,577 and FY2023 from 37,364 to 26,018, while FY2025 director bios did
        # not improve at all. One global threshold cannot serve all four sections;
        # 0.9 is kept because it is the value at which CD&A is verified correct.
        # The two sections it does not fix need per-section boundaries, not another
        # global knob — see the KNOWN LIMITS note in the module docstring.
        keep = [s for s in scored if s["anchor_hits"] >= ANCHOR_FLOOR * best_hits and s["chars"] > 0]
        pick = min(keep, key=lambda s: s["chars"]) if keep else max(scored, key=lambda s: s["chars"])
        out[key] = {
            "text": doc.text_span(pick["start"], pick["end"]),
            "node_range": [pick["start"], pick["end"]],
            "boundary_basis": (f"nodes {pick['start']}-{pick['end']}: tightest of {len(starts)} "
                               f"candidate(s) carrying >=90% of peak anchor content "
                               f"({pick['anchor_hits']}/{best_hits} anchor hits)"),
            "candidates": len(starts),
            "anchor_hits": pick["anchor_hits"],
        }
    return out


# ---------------------------------------------------------------------------
# Shareholder letter, inside the annual report
# ---------------------------------------------------------------------------

def extract_letter(whole_text: str, cfg: dict) -> dict:
    """Locate the shareholder letter inside an annual report. Format fact 7.

    Bounded on the letter's own conventions — a salutation to a sign-off — because
    an ARS has no structural marker for where the letter ends and the 10-K begins.

    Works on the already-extracted document text rather than on HTML nodes: the
    two markers are plain prose, not styled headings, so there is nothing for a
    structural rule to grip. Both are verified unique per document before use, and
    a non-unique match is reported rather than guessed at.
    """
    spec = next((s for s in cfg["sections"]["sections"] if s["key"] == "letter_full_text"), None)
    if not spec:
        return {"error": "config/sections.toml has no letter_full_text section"}

    starts: list[re.Match] = []
    for pat in spec["start_patterns"]:
        starts += list(re.finditer(pat, whole_text, re.I))
    if not starts:
        return {"error": f"no salutation found (tried {spec['start_patterns']})"}
    starts.sort(key=lambda m: m.start())
    i0 = starts[0].start()

    ends: list[re.Match] = []
    for pat in spec["end_patterns"]:
        ends += [m for m in re.finditer(pat, whole_text, re.I) if m.start() > i0]
    if not ends:
        return {"error": f"salutation at {i0} but no sign-off after it "
                         f"(tried {spec['end_patterns']})"}
    ends.sort(key=lambda m: m.start())
    # Keep a short tail past the sign-off so the signer's name survives — it is
    # what identifies whose voice the letter is.
    tail = int(spec.get("signature_tail_chars", 100))
    i1 = min(ends[0].end() + tail, len(whole_text))

    return {
        "text": whole_text[i0:i1].strip(),
        "boundary_basis": (f"chars {i0}-{i1} of {len(whole_text):,d}: salutation "
                           f"{starts[0].group(0)!r} ({len(starts)} match(es) in document) "
                           f"-> sign-off {ends[0].group(0)!r} "
                           f"({len(ends)} match(es) after it) + {tail}-char signature tail"),
        "salutation_matches": len(starts),
        "signoff_matches_after_start": len(ends),
    }


# ---------------------------------------------------------------------------
# Whole-document forms
# ---------------------------------------------------------------------------

# Forms with a dedicated structural extractor above: `extract_10k` walks 10-K
# item boundaries, `find_proxy_sections` walks the proxy's. Everything else in
# forms.toml is taken entire, because there is no internal structure to locate.
#
# This is the ONLY hand-maintained half of the whole-document rule, and it is
# keyed to the existence of code in this file rather than to anything about a
# particular company — so adding a form to forms.toml does not require editing
# it. Adding a new structural extractor does.
STRUCTURED_FORMS = {"10-K", "DEF 14A"}


def whole_doc_forms(forms_cfg: list[dict]) -> set[str]:
    """Every form taken entire, derived from forms.toml.

    Was hardcoded as {"8-K", "8-K/A", "ARS", "DEFA14A", "CORRESP", "UPLOAD"},
    which meant adding a form to forms.toml silently produced a filing that
    reached the `else` branch and was skipped with no section extracted — a
    config change whose effect was a quiet omission three stages downstream.

    Amendments are included for the forms that declare `include_amendments`,
    which is where "8-K/A" came from. Verified at the time of the change to
    reproduce the previous hardcoded set exactly, form for form.

    ARS is here and ALSO has a section: the document is kept whole as the source
    of record, and `extract_letter` then locates the shareholder letter inside
    it. Whole-document is about how the text is obtained, not about whether
    anything is extracted from it afterwards.
    """
    out: set[str] = set()
    for entry in forms_cfg:
        form = entry["form"]
        if form in STRUCTURED_FORMS:
            continue
        out.add(form)
        if entry.get("include_amendments"):
            out.add(f"{form}/A")
    return out


# ---------------------------------------------------------------------------
# One document per role per filing
# ---------------------------------------------------------------------------

# Rendition preference. ONLY the HTML rule is a rule: CLAUDE.md's "HTML-first —
# parse filing HTML with BeautifulSoup rather than the plain text renditions.
# Table structure and section boundaries survive; in the text versions they
# don't." Everything else ranks equal, deliberately, so that among non-HTML
# candidates the manifest's own order decides and this function invents no
# ordering it has not been measured against. Today the only collision that exists
# anywhere is HTML vs PDF; a PDF-vs-text collision has never been observed, and
# guessing at its ranking would be exactly the untested branch CLAUDE.md rule 3
# warns about.
HTML_SUFFIXES = {".htm", ".html", ".xhtml"}


def rendition_rank(filename: str) -> int:
    """0 for an HTML rendition, 1 for anything else. Lower wins."""
    return 0 if Path(filename).suffix.lower() in HTML_SUFFIXES else 1


def choose_documents(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep one document per (accession, doc_type). Returns (kept, dropped).

    WHY THIS EXISTS, and it is a bug that reached a real company.

    A filing can carry the SAME document twice in two renditions. Microsoft files
    every DEF 14A as both a ~2 MB `.htm` and a ~9 MB `.pdf`, both with
    `doc_type == "DEF 14A"`, both under one accession number. Morningstar never
    did — zero such pairs across its five years — so nothing here was ever
    exercised against one.

    What happened without this function, on MSFT's FY2020 proxy:

        [1/2] d31295ddef14a.htm    ok    DEF14A_cdna  73,566 chars   (+3 more)
        [2/2] d31295ddef14a1.pdf   FAIL  no heading candidate found  (x4)
        all stored: 4 sections, 0 ok, 4 failed

    Both documents produce the same section KEYS under the same ACCESSION, and the
    manifest merges on `(accession, key)` — so the PDF's four failures replaced the
    HTML's four successes. The `.txt` files stayed on disk holding the good
    extraction while the manifest recorded failure and named the PDF as the source.
    `extract_facts` reads the manifest, so `comp`, `board` and `votes` would have
    been empty for all six fiscal years, and any citation would have pointed at the
    wrong document. CLAUDE.md rule 4: writers merge, never clobber — this is its
    second recorded instance, and the first in a stage that had an explicit,
    correct merge and still lost data because its KEY was too coarse.

    PREFER, NEVER SKIP. The rule cannot be "ignore PDFs": MORN's FY2022 ARS is a
    PDF with no HTML sibling and it extracts fine. A rendition is only dropped when
    a better one exists for the same role in the same filing.

    Grouping on (accession, doc_type) rather than accession alone is what keeps
    the exhibits: a 10-K filing carries `10-K`, `EX-10.7` and `EX-10.8`, which are
    three different roles and all three are wanted. Likewise an UPLOAD carries a
    `LETTER` (PDF) and a `TEXT-EXTRACT` (TXT) — different doc_types, both kept,
    exactly as before.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in docs:
        groups.setdefault((r["accession"], r["doc_type"].upper().strip()), []).append(r)

    kept, dropped = [], []
    for _, members in groups.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        # Stable: equal ranks keep the order the manifest listed them in, so a
        # re-run picks the same document (CLAUDE.md rule 4, run twice diff nothing).
        ranked = sorted(members, key=lambda r: rendition_rank(r["filename"]))
        kept.append(ranked[0])
        dropped.extend(ranked[1:])

    # Restore the caller's ordering rather than the grouping's.
    order = {id(r): i for i, r in enumerate(docs)}
    kept.sort(key=lambda r: order[id(r)])
    dropped.sort(key=lambda r: order[id(r)])
    return kept, dropped


def extract_whole(path: Path) -> dict:
    """Short documents are taken entire — there is no section to locate."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from equity_research.pdf_text import extract as pdf_extract
        text, report = pdf_extract(path)
        return {"text": fix_chars(text).strip(),
                "boundary_basis": "whole document (PDF)",
                "pdf_decode": {k: report[k] for k in ("decoded", "offset", "validation_passed")
                               if k in report}}
    if suffix == ".txt":
        return {"text": fix_chars(path.read_text(encoding="utf-8", errors="replace")).strip(),
                "boundary_basis": "whole document (text)"}
    doc = Doc(path)
    return {"text": doc.text_span(0, len(doc.nodes)),
            "boundary_basis": "whole document (HTML)"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """See discover.load_config: company.toml is company-scoped, the other two
    are global defaults a company may override."""
    return settings.load_config("company", "forms", "sections", P=P)


# Image and asset filenames. Stripped before words are counted because they are
# precisely what inflates the character count of a document that has no text in it —
# a press release published as JPGs is mostly `something001.jpg`.
ASSET_FILENAME = re.compile(r"\S+\.(?:jpg|jpeg|png|gif|svg|webp|bmp|tif|tiff)\b", re.I)
WORDISH = re.compile(r"[A-Za-z]{2,}")


def substantive_words(text: str) -> int:
    """Word-like tokens, ignoring image filenames and single letters.

    The measure the character floor could not make: 163 characters of `EX-99.1 2
    dividendpr_031524v2.htm ... dividendpr_031524v2001.jpg ... 2 of 2` is a
    successful-looking extraction of a document that contains no readable text.
    See `min_substantive_words` in config/sections.toml. VERIFICATION.md D6.
    """
    return len(WORDISH.findall(ASSET_FILENAME.sub(" ", text)))


def validate(key: str, text: str, cfg: dict, whole_doc: bool = False) -> tuple[bool, list[str]]:
    """Length band, anchor phrases, and over-capture markers. CLAUDE.md: log
    failures loudly rather than emitting a truncated or over-captured section."""
    v = cfg["sections"]["validation"]
    checks = v["checks"]
    problems: list[str] = []

    # Whole-document extractions are a different kind of artifact and the
    # section-oriented rules do not apply to them:
    #
    #  - LENGTH. The 2,000-character floor is calibrated to 10-K sections. An SEC
    #    staff comment letter is legitimately 612 characters, and an 8-K press
    #    release can be shorter still. Judging them by that floor rejected six real
    #    documents. They get a floor that only catches a genuinely empty read.
    #
    #  - OVER-CAPTURE. The marker check asks "did this section run past its end?"
    #    A whole document has no end to overrun. The annual report legitimately
    #    CONTAINS the audit report and balance sheets, so the check flagged all
    #    four ARS filings for containing exactly what they are supposed to contain.
    n = len(text)
    floor = 120 if whole_doc else v["min_chars"]
    if n < floor:
        problems.append(f"below floor: {n:,d} < {floor:,d} chars"
                        + (" (whole-document floor)" if whole_doc else ""))

    # The word floor, which the character floor cannot substitute for. Applied to
    # every section, not just whole documents: a section extraction that lands on a
    # page of images fails the same way, and there is no kind of section for which
    # 25 readable words is a successful read.
    words = substantive_words(text)
    if words < v["min_substantive_words"]:
        assets = len(ASSET_FILENAME.findall(text))
        problems.append(
            f"NO USABLE TEXT: {words} substantive word(s) in {n:,d} chars"
            + (f", and {assets} image filename(s) — the document is published as "
               f"images, not text" if assets else
               " — the extraction produced markup or boilerplate, not prose"))
    band = None if whole_doc else v["expected_chars"].get(key)
    if band:
        if n < band["min"]:
            problems.append(f"shorter than expected: {n:,d} < {band['min']:,d}")
        elif n > band["max"]:
            problems.append(f"longer than expected: {n:,d} > {band['max']:,d}")

    spec = next((s for s in cfg["sections"]["sections"] if s["key"] == key), None)
    if spec:
        anchors = [a for a in spec.get("anchor_phrases", []) if a.lower() in text.lower()]
        need = checks["min_anchor_phrases"]
        if len(anchors) < need:
            problems.append(f"only {len(anchors)}/{need} anchor phrases present "
                            f"(found {anchors or 'none'})")

    # Over-capture detection, by COUNT rather than mere presence.
    #
    # The original rule flagged any occurrence of a financial-statement phrase.
    # That produced a false positive on all five Item 7 sections: MD&A legitimately
    # cross-references the statements once, in Critical Accounting Estimates
    # ("...liabilities presented in our Consolidated Balance Sheets..."), and the
    # boundaries were verifiably correct — Item 7 heading to Item 7A heading, which
    # cannot run into the financial statements at all.
    #
    # What real over-capture looks like is different in kind, not degree: if a span
    # actually swallowed the statements it would repeat these phrases many times
    # (as headings, column titles and note references) and would trip several
    # distinct markers at once. So: flag a marker seen 3+ times, or 2+ distinct
    # markers. One passing mention is a citation, not a boundary failure.
    hits = {}
    for pat in ([] if whole_doc else checks["overcapture_markers"]):
        c = len(re.findall(pat, text, re.I))
        if c:
            hits[pat] = c
    heavy = [f"/{p}/ x{c}" for p, c in hits.items() if c >= 3]
    if heavy or len(hits) >= 2:
        problems.append("OVER-CAPTURE: " + ", ".join(f"/{p}/ x{c}" for p, c in hits.items())
                        + " — the section appears to contain the financial statements")
    return (not problems), problems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 3 — extract target sections.")
    ap.add_argument("--form", help="only this form type, e.g. 10-K")
    ap.add_argument("--fy", type=int, help="only this fiscal year")
    ap.add_argument("--show", help="print this section key to stdout and exit")
    ap.add_argument("--limit", type=int, help="process at most N documents")
    add_ticker_arg(ap)

    args = ap.parse_args()

    if not MANIFEST.exists():
        sys.exit(f"FATAL: {MANIFEST} not found. Run `uv run python -m equity_research.fetch` first (milestone 2).")
    cfg = load_config()
    # Derived from forms.toml, not a literal set — see whole_doc_forms().
    whole_forms = whole_doc_forms(cfg["forms"]["forms"])
    recs = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]

    # Only primary documents carry the target sections; exhibits are separate
    # artifacts and are extracted whole under their own keys.
    NARRATIVE_EX = re.compile(r"^EX-(99|13|97|19|10)(?!\d)", re.I)

    def is_target_doc(r: dict) -> bool:
        dt = r["doc_type"].upper().strip()
        if r["form"] in ("UPLOAD", "CORRESP"):
            return True
        if dt.startswith(r["form"].upper().replace("/A", "")):
            return True
        # (?!\d) is what keeps EX-101 (XBRL taxonomy) out of the EX-10
        # (material contracts) bucket -- a plain startswith let it back in.
        return bool(NARRATIVE_EX.match(dt))

    docs = [r for r in recs if is_target_doc(r)]
    if args.form:
        docs = [r for r in docs if r["form"] == args.form]
    if args.fy:
        docs = [r for r in docs if r["fiscal_year"] == args.fy]
    docs.sort(key=lambda r: (r["fiscal_year"], r["form"], r["filing_date"]))

    # One rendition per role per filing. See choose_documents: a filing that
    # carries the same document as both HTML and PDF used to have the second one
    # overwrite the first's manifest record.
    targeted = len(docs)
    docs, superseded = choose_documents(docs)
    if args.limit:
        docs = docs[:args.limit]

    print(f"Section extraction — {len(docs)} document(s)")
    # Stated, not silent: CLAUDE.md rule 5 — a stage reporting what it attempted
    # must account for the difference between that and what it was given.
    if superseded:
        print(f"  {targeted} target document(s) -> {len(docs)} after choosing one "
              f"rendition per role, {len(superseded)} superseded:")
        for r in superseded:
            print(f"    FY{r['fiscal_year']} {r['form']:<8} {r['doc_type']:<10} "
                  f"{r['filename']}  ({r['bytes']/1e6:.1f} MB) — superseded by the "
                  f"HTML rendition of the same document")
    print()

    results: list[dict] = []
    for n, rec in enumerate(docs, 1):
        path = P.resolve(rec["path"])
        form, fy, acc = rec["form"], rec["fiscal_year"], rec["accession"]
        dest_dir = OUT_DIR / f"FY{fy}" / form.replace(" ", "-").replace("/", "-") / acc
        base = {"accession": acc, "form": form, "fiscal_year": fy,
                "filing_date": rec["filing_date"], "doc_type": rec["doc_type"],
                "source": rec["path"], "items": rec.get("items", [])}

        try:
            if form == "10-K" and rec["doc_type"].upper() == "10-K":
                doc = Doc(path)
                # The validation floor decides the boundary as well as judging it
                # afterwards -- see the docstring. One more key in sections.toml
                # that the code genuinely reads.
                sections = extract_10k(
                    doc, cfg["sections"]["validation"]["min_chars"])
                # Risk factors additionally split into individual factors.
                rf = sections.get("10-K_item1a_risk_factors")
                if rf and "text" in rf:
                    a, b = rf["node_range"]
                    rf["factors"] = split_risk_factors(doc, a, b)
            elif form == "DEF 14A" and rec["doc_type"].upper().startswith("DEF"):
                sections = find_proxy_sections(Doc(path))
            elif form in whole_forms or rec["doc_type"].upper().startswith("EX-"):
                # Keys become filenames, so strip anything the filesystem would
                # read as a path separator: form "8-K/A" produced the key
                # "8-K/A_8-K/A_whole", which Windows resolved as nested
                # directories that did not exist.
                # Keep the dot as a hyphen rather than deleting it: stripping it
                # made "EX-10.1" (a material contract, in scope) indistinguishable
                # from "EX-101" (XBRL taxonomy, excluded at fetch time) in the key.
                key = f"{slug(form)}_{slug(rec['doc_type'].upper()).replace('.', '-')}_whole"
                whole = extract_whole(path)
                sections = {key: whole}
                # An annual report yields TWO artifacts: the document itself (kept
                # as the source of record) and the shareholder letter located inside
                # it. Only the letter is in scope per SPEC.md; the rest of an ARS is
                # the 10-K, already extracted from the 10-K filing itself.
                if form == "ARS" and whole.get("text"):
                    sections["letter_full_text"] = extract_letter(whole["text"], cfg)
            else:
                sections = {}
        except Exception as exc:
            print(f"[{n:3d}/{len(docs)}] FY{fy} {form:8s} {path.name[:34]:34s}  ERROR {exc!r}")
            results.append({**base, "key": "(document)", "ok": False,
                            "problems": [f"exception: {exc!r}"]})
            continue

        print(f"[{n:3d}/{len(docs)}] FY{fy} {form:8s} {path.name[:34]:34s}  {len(sections)} section(s)")
        for key, sec in sections.items():
            if "error" in sec:
                print(f"          FAIL  {key:32s} {sec['error']}")
                results.append({**base, "key": key, "ok": False, "problems": [sec["error"]]})
                continue
            text = sec["text"]
            ok, problems = validate(key, text, cfg, whole_doc=key.endswith("_whole"))
            row = {**base, "key": key, "chars": len(text), "ok": ok, "problems": problems,
                   "boundary_basis": sec.get("boundary_basis", "")}
            if "factors" in sec:
                row["factor_count"] = len(sec["factors"])

            # CLAUDE.md: a failed boundary is logged and skipped, never written.
            if ok:
                dest_dir.mkdir(parents=True, exist_ok=True)
                (dest_dir / f"{key}.txt").write_text(text, encoding="utf-8")
                # P.relative, NOT relative_to(ROOT) — see THE MANIFEST CONTRACT
                # in paths.py. This path is what extract_facts, build_ledger,
                # risk_diff and triage_8k all read to find the section text.
                row["out"] = P.relative(dest_dir / f"{key}.txt")
                if "factors" in sec:
                    (dest_dir / f"{key}.factors.json").write_text(
                        json.dumps(sec["factors"], indent=2), encoding="utf-8")
                mark = "ok  "
            else:
                mark = "FAIL"
            extra = f"  {row.get('factor_count', '')} factors" if "factor_count" in row else ""
            print(f"          {mark}  {key:32s} {len(text):>8,d} chars{extra}")
            for p in problems:
                print(f"                {p}")
            results.append(row)

    # --- output ------------------------------------------------------------
    # MERGE into any existing manifest rather than replacing it. A filtered run
    # (--form / --fy) only touches some documents, and overwriting would silently
    # erase the record of every section extracted by an earlier run while leaving
    # its .txt files on disk — a manifest that disagrees with the filesystem.
    # CLAUDE.md: running a stage twice must not corrupt anything.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "sections-manifest.json"
    merged: dict[tuple[str, str], dict] = {}
    if manifest_path.exists():
        for r in json.loads(manifest_path.read_text(encoding="utf-8")).get("sections", []):
            merged[(r["accession"], r["key"])] = r
    for r in results:                              # this run wins for what it covered
        merged[(r["accession"], r["key"])] = r
    all_rows = sorted(merged.values(), key=lambda r: (r["fiscal_year"], r["form"], r["key"]))

    ok_n = sum(1 for r in all_rows if r["ok"])
    # Counted into the manifest as its own category rather than folded into
    # `sections_failed`. A boundary that missed and a document that has no text in it
    # are different problems with different fixes — the first is a pattern to correct,
    # the second is a filing that will never yield text and has to be got from
    # elsewhere or acknowledged as a gap. VERIFICATION.md D6.
    no_text = [r for r in all_rows
               if any(p.startswith("NO USABLE TEXT") for p in (r.get("problems") or []))]
    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_run_filter": {"form": args.form, "fy": args.fy, "limit": args.limit},
        "last_run_documents": len(docs),
        # Which renditions were NOT read, and in favour of what. Empty for a
        # company that files each document once (MORN's is empty). Recorded rather
        # than only printed, because "this section came from the HTML and not the
        # PDF of the same proxy" is a provenance fact a coverage claim rests on.
        "last_run_superseded": [
            {"accession": r["accession"], "form": r["form"], "doc_type": r["doc_type"],
             "fiscal_year": r["fiscal_year"], "filename": r["filename"],
             "bytes": r["bytes"], "reason": "an HTML rendition of the same document "
                                            "was read instead (CLAUDE.md: HTML-first)"}
            for r in superseded],
        "sections_attempted": len(all_rows),
        "sections_written": ok_n, "sections_failed": len(all_rows) - ok_n,
        "sections_with_no_usable_text": [
            {"accession": r["accession"], "form": r["form"], "key": r["key"],
             "fiscal_year": r["fiscal_year"], "chars": r.get("chars"),
             "problem": next(p for p in r["problems"] if p.startswith("NO USABLE TEXT"))}
            for r in no_text],
        "sections": all_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print("=" * 72)
    # Report this run and the merged total separately. Mixing them produced
    # "attempted 20 / written 226 / failed -206" on a filtered run.
    run_ok = sum(1 for r in results if r["ok"])
    print(f"this run  : {len(results)} attempted, {run_ok} written, {len(results)-run_ok} failed")
    print(f"all stored: {len(all_rows)} sections, {ok_n} ok, {len(all_rows)-ok_n} failed")
    # Printed as its own headline, not left to be found among 231 rows. This is the
    # class that previously read as a success.
    if no_text:
        print()
        print(f"!! {len(no_text)} DOCUMENT(S) YIELDED NO USABLE TEXT — extracted "
              f"cleanly, and contain nothing to extract:")
        for r in no_text:
            print(f"     FY{r['fiscal_year']} {r['form']:8s} {r['key']:28s} "
                  f"{r['accession']}")
            print(f"       {next(p for p in r['problems'] if p.startswith('NO USABLE'))}")
        print("   Nothing downstream can cite these. If any is a 7.01/8.01 strategic "
              "exhibit,\n   its content has to be sourced from the filing body or "
              "recorded as a gap.")
    # Compare against THIS RUN's success count, not the merged total: `ok_n`
    # counts every section ever stored, so on a filtered run `len(results) - ok_n`
    # goes negative, which is truthy, and printed an empty "failures:" header.
    if len(results) - run_ok:
        print()
        print("failures:")
        for r in results:
            if not r["ok"]:
                print(f"  FY{r['fiscal_year']} {r['form']:8s} {r['key']:32s} {'; '.join(r['problems'])[:90]}")
    print(f"\nwrote {OUT_DIR / 'sections-manifest.json'}")

    if args.show:
        hits = [r for r in results if r["key"] == args.show and r.get("out")]
        if not hits:
            sys.exit(f"\nno written section matching --show {args.show}")
        print("\n" + "=" * 72)
        print(P.resolve(hits[0]["out"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
