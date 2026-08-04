"""Milestone 3 — Section extraction.

Locates the target sections defined in SPEC.md inside the cached filings and
writes cleaned text to data/sections/. Section-targeted, not linear: a 10-K runs
420,000 characters of text and the three in-scope items are a fraction of it.

Run it:
    uv run python src/extract_sections.py                  # everything
    uv run python src/extract_sections.py --form 10-K      # one form type
    uv run python src/extract_sections.py --fy 2021        # one fiscal year
    uv run python src/extract_sections.py --show 10-K_item1a_risk_factors --fy 2021

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
   disambiguated by span size — see find_proxy_sections.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import warnings
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Inline-XBRL filings are XHTML; parsing them with the HTML parser is correct and
# standard, so silence the advisory warning rather than switching parsers (the
# XML parser is stricter and chokes on real-world filing markup).
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
MANIFEST = ROOT / "data" / "raw" / "fetch-manifest.json"
OUT_DIR = ROOT / "data" / "sections"

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

def find_item_headings(doc: Doc) -> list[tuple[str, int]]:
    """Every real 10-K item heading as (item number, node index). Format fact 3."""
    found = []
    for i, t in enumerate(doc.texts):
        if not t or len(t) > MAX_HEADING_CHARS:
            continue
        m = ITEM_HEADING.match(t)
        if not m or doc.is_in_link(i):
            continue
        found.append((m.group(1).upper(), i))
    found.sort(key=lambda x: x[1])
    # Keep the FIRST occurrence of each item number: some filings repeat a
    # heading as a running page header further down.
    seen, out = set(), []
    for num, i in found:
        if num not in seen:
            seen.add(num)
            out.append((num, i))
    return out


def extract_10k(doc: Doc) -> dict[str, dict]:
    """Item 1, Item 1A and Item 7, each running to the next item heading."""
    heads = find_item_headings(doc)
    if not heads:
        return {}
    index = {num: i for num, i in heads}
    order = [i for _, i in heads]

    wanted = {
        "1":  "10-K_item1_business",
        "1A": "10-K_item1a_risk_factors",
        "7":  "10-K_item7_mdna",
    }
    out: dict[str, dict] = {}
    for num, key in wanted.items():
        if num not in index:
            out[key] = {"error": f"Item {num} heading not found among {sorted(index)}"}
            continue
        i0 = index[num]
        later = [i for i in order if i > i0]
        i1 = later[0] if later else len(doc.nodes)
        out[key] = {
            "text": doc.text_span(i0, i1),
            "node_range": [i0, i1],
            "boundary_basis": f"Item {num} heading -> next item heading",
            "items_found": len(heads),
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
    return factors


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
    for key, (start_pat, end_pats, _anchors) in PROXY_SECTIONS.items():
        starts = matches(start_pat)
        if not starts:
            out[key] = {"error": "no heading candidate found"}
            continue

        # RUNNING PAGE HEADERS. Donnelley proxies print the section title at the
        # top of every page, so "Compensation Discussion and Analysis" appears 14
        # times inside its own section in the FY2022 proxy. Group them: consecutive
        # matches separated by less than `gap` nodes are one section's page headers,
        # not separate sections. FY2021 and FY2025 have no running headers, which
        # is precisely why only those two looked right before this was handled and
        # the bug stayed invisible in aggregate.
        gap = 2500
        runs: list[list[int]] = [[starts[0]]]
        for i in starts[1:]:
            if i - runs[-1][-1] <= gap:
                runs[-1].append(i)
            else:
                runs.append([i])

        # For each run, the section starts at its FIRST header and ends at the first
        # of its OWN end patterns occurring after its LAST header. Searching after
        # the last header is what makes this robust: it steps over the section's own
        # running headers, and over the front-of-proxy summary where an end phrase
        # often appears long before the real section it names.
        ends = sorted({i for p in end_pats for i in matches(p)})
        cands = []
        for run in runs:
            after = [e for e in ends if e > run[-1]]
            i1 = after[0] if after else len(doc.nodes)
            cands.append((sum(len(doc.texts[k]) for k in range(run[0], i1)), run[0], i1, len(run)))
        cands.sort(reverse=True)
        chars, i0, i1, headers = cands[0]
        out[key] = {
            "text": doc.text_span(i0, i1),
            "node_range": [i0, i1],
            "boundary_basis": (f"nodes {i0}-{i1}: {len(starts)} heading match(es) grouped into "
                               f"{len(runs)} run(s); chosen run has {headers} page header(s), "
                               f"end from its own end-patterns"),
            "candidates": len(starts),
        }
    return out


# ---------------------------------------------------------------------------
# Whole-document forms
# ---------------------------------------------------------------------------

WHOLE_DOC_FORMS = {"8-K", "8-K/A", "ARS", "DEFA14A", "CORRESP", "UPLOAD"}


def extract_whole(path: Path) -> dict:
    """Short documents are taken entire — there is no section to locate."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        sys.path.insert(0, str(ROOT / "src"))
        from pdf_text import extract as pdf_extract
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
    cfg = {}
    for name in ("company", "forms", "sections"):
        with open(CONFIG_DIR / f"{name}.toml", "rb") as fh:
            cfg[name] = tomllib.load(fh)
    return cfg


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
    args = ap.parse_args()

    if not MANIFEST.exists():
        sys.exit(f"FATAL: {MANIFEST} not found. Run src/fetch.py first (milestone 2).")
    cfg = load_config()
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
    if args.limit:
        docs = docs[:args.limit]

    print(f"Section extraction — {len(docs)} document(s)")
    print()

    results: list[dict] = []
    for n, rec in enumerate(docs, 1):
        path = ROOT / rec["path"]
        form, fy, acc = rec["form"], rec["fiscal_year"], rec["accession"]
        dest_dir = OUT_DIR / f"FY{fy}" / form.replace(" ", "-").replace("/", "-") / acc
        base = {"accession": acc, "form": form, "fiscal_year": fy,
                "filing_date": rec["filing_date"], "doc_type": rec["doc_type"],
                "source": rec["path"], "items": rec.get("items", [])}

        try:
            if form == "10-K" and rec["doc_type"].upper() == "10-K":
                doc = Doc(path)
                sections = extract_10k(doc)
                # Risk factors additionally split into individual factors.
                rf = sections.get("10-K_item1a_risk_factors")
                if rf and "text" in rf:
                    a, b = rf["node_range"]
                    rf["factors"] = split_risk_factors(doc, a, b)
            elif form == "DEF 14A" and rec["doc_type"].upper().startswith("DEF"):
                sections = find_proxy_sections(Doc(path))
            elif form in WHOLE_DOC_FORMS or rec["doc_type"].upper().startswith("EX-"):
                # Keys become filenames, so strip anything the filesystem would
                # read as a path separator: form "8-K/A" produced the key
                # "8-K/A_8-K/A_whole", which Windows resolved as nested
                # directories that did not exist.
                # Keep the dot as a hyphen rather than deleting it: stripping it
                # made "EX-10.1" (a material contract, in scope) indistinguishable
                # from "EX-101" (XBRL taxonomy, excluded at fetch time) in the key.
                key = f"{slug(form)}_{slug(rec['doc_type'].upper()).replace('.', '-')}_whole"
                sections = {key: extract_whole(path)}
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
                row["out"] = str((dest_dir / f"{key}.txt").relative_to(ROOT)).replace("\\", "/")
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
    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_run_filter": {"form": args.form, "fy": args.fy, "limit": args.limit},
        "last_run_documents": len(docs),
        "sections_attempted": len(all_rows),
        "sections_written": ok_n, "sections_failed": len(all_rows) - ok_n,
        "sections": all_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"sections attempted : {len(results)}")
    print(f"  written          : {ok_n}")
    print(f"  failed           : {len(results) - ok_n}")
    if len(results) - ok_n:
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
        print((ROOT / hits[0]["out"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
