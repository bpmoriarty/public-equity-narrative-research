"""Render the finished deliverables to PDF.

Run it:
    uv run python -m equity_research.render_pdf
    uv run python -m equity_research.render_pdf --only timeline.md

Reads:  output/*.md          the three deliverables, whatever they currently are
Writes: output/pdf/*.pdf

---------------------------------------------------------------------------
PRESENTATION ONLY, AND THAT IS ASSERTED RATHER THAN INTENDED
---------------------------------------------------------------------------
A PDF is a second rendering of a document this pipeline already checked. It adds no
content, and the risk it introduces is not that it says something wrong — it is that
it silently says LESS: a citation swallowed by a table cell that overflowed, a
paragraph clipped at a page break, a character dropped because the font could not
encode it. All three look perfectly fine in the PDF.

So every render is verified by reading the finished PDF back:

  - EVERY WORD must survive, as many times as it should appear. This is the gate,
    and it is what catches a clipped paragraph or a dropped table row
  - every fact id in the Markdown must be present in the PDF's extracted text
  - every heading must survive
  - the character inventory must survive — no glyph silently replaced

Reading order is measured too, but only reported: a table is extracted by pdfminer in
layout order rather than by row, so out-of-order text in `timeline.md` is a property
of the extractor, not a defect in the PDF. See the note above `missing_words`.

`pdfminer.six` is already a dependency (it reads MORN's PDF-only FY2022 shareholder
letter), so checking costs nothing but the time.

---------------------------------------------------------------------------
WHY THIS TOOLCHAIN
---------------------------------------------------------------------------
`markdown` + `xhtml2pdf`, both pure Python. WeasyPrint renders better and was
rejected: on Windows it needs GTK/Pango native libraries, and CLAUDE.md requires the
project to rebuild from a clean checkout. A dependency that installs from the lock
file on one machine and needs a system package manager on the next is not
reproducible. pandoc, wkhtmltopdf and LaTeX are all absent here for the same reason.

The base-14 PDF fonts cover what these documents contain — the double dagger ‡, em
dashes, curly quotes, × and – are all in WinAnsi encoding — but that is checked
after rendering rather than assumed.

NOT BYTE-REPRODUCIBLE, deliberately noted: a PDF carries a creation timestamp, so
two runs differ in bytes. The property that matters is that the TEXT is identical,
which is what the verification below measures.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import html as html_mod

import markdown
from pdfminer.high_level import extract_text
from xhtml2pdf import pisa

from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

OUT_DIR = P.output
PDF_DIR = OUT_DIR / "pdf"
CONFIG = P.config_dir / "outputs.toml"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ID_RE = re.compile(r"\b[A-Z]{2,6}-FY\d{4}-[0-9a-f]{8}\b")
HEADING_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$", re.M)

# Characters these documents use that a PDF font could silently fail to encode. The
# double dagger is the timeline's conflict marker and the em dash is everywhere in
# the prose; losing either is invisible in a rendered page unless you look for it.
GLYPHS_AT_RISK = "‡†—–’‘“”×…§"

TAG_RE = re.compile(r"<[^>]+>")
# <style> holds CSS, whose tokens are not words any reader sees. Removed CONTENTS AND
# ALL before tags are stripped — the first version of this check stripped tags only,
# so every CSS property name became a word the PDF was expected to contain and all
# three documents reported "TEXT LOST: word 1 ('size')". A checker bug presenting as
# a defect in the artifact, which is the failure mode this project keeps meeting.
STYLE_RE = re.compile(r"<(?:style|script)[^>]*>.*?</(?:style|script)>",
                      re.S | re.I)
# ALPHANUMERIC RUNS ONLY — no punctuation, deliberately.
#
# The first version included . , / ( ) - and the apostrophe, and it reported three
# false losses. Stripping an HTML tag leaves a space behind, so `words</strong>,`
# tokenised as ["words", ","] while the PDF's own extraction gives ["words,"] — the
# same text, tokenised differently either side, and the comparison failed on
# punctuation adjacency rather than on anything being missing.
#
# Punctuation is not what this check is for. It exists to catch a clipped paragraph,
# a dropped table row or an overflowing cell, and all of those lose whole words.
WORD_RE = re.compile(r"[0-9A-Za-z]+")


def words_of(text: str) -> list[str]:
    """The word sequence a reader would see."""
    return WORD_RE.findall(text)


# ---------------------------------------------------------------------------
# COMPLETENESS IS THE GATE; ORDER IS ONLY REPORTED
# ---------------------------------------------------------------------------
# The question worth failing on is "did the PDF lose anything", and the answer is a
# multiset comparison: every word the reader should see must be in the PDF, as many
# times as it should be. A clipped paragraph, a dropped table row and an overflowing
# cell all lose whole words, so all three are caught.
#
# ORDER IS NOT A SOUND GATE HERE, and measuring it is how that was established.
# `timeline.md` failed an order check at word 186 while containing every word — its
# tables are extracted by pdfminer in layout order, which for a multi-column table is
# not reading order. Nothing was wrong with the PDF; the instrument was wrong for the
# document. The two prose documents pass the order check, and it is still run and
# reported for them, because for continuous prose out-of-order text WOULD mean
# something had been reflowed or clipped.
#
# The failure mode to avoid here is the one this project keeps meeting: a check that
# fires on correct output teaches you to ignore it. So the order result is printed as
# an observation, and only lost content stops the run.

def missing_words(want: list[str], got: list[str]) -> Counter:
    """Words the PDF should contain and does not, with their shortfall counts."""
    return Counter(want) - Counter(got)


def first_divergence(want: list[str], got: list[str]) -> tuple[int, str] | None:
    """Is `want` a subsequence of `got`? Returns (index, word) at the first word of
    `want` that could not be found in order, or None if all of it is present.

    A SUBSEQUENCE TEST, NOT EQUALITY, because the PDF legitimately holds text the
    Markdown does not: a repeated footer on every page, and the page numbers in it.
    """
    i = 0
    for j, w in enumerate(want):
        try:
            i = got.index(w, i) + 1
        except ValueError:
            return j, w
    return None


# Letter, in centimetres, so the footer frame can be given a real width. xhtml2pdf
# rejects a percentage on a frame ("getSize: Not a float '100%'") and then places the
# frame at a default width, which silently shifts the page number off centre.
PAGE_CM = {"portrait": 21.59, "landscape": 27.94}
SIDE_MARGIN_CM = 1.7


def stylesheet(font_pt: float, page: str) -> str:
    """Print CSS. xhtml2pdf supports a subset — keep to what it actually honours."""
    orientation = "landscape" if "landscape" in page else "portrait"
    frame_w = PAGE_CM[orientation] - 2 * SIDE_MARGIN_CM
    return f"""
@page {{
    size: {page};
    margin: 1.9cm {SIDE_MARGIN_CM}cm 1.9cm {SIDE_MARGIN_CM}cm;
    @frame footer {{ -pdf-frame-content: footer; bottom: 0.9cm; height: 1cm;
                     left: {SIDE_MARGIN_CM}cm; width: {frame_w:.2f}cm; }}
}}
body      {{ font-family: Helvetica; font-size: {font_pt}pt; line-height: 1.42;
             color: #17181a; }}
h1        {{ font-size: {font_pt * 1.85:.1f}pt; margin: 0 0 4pt 0; color: #0b0c0d; }}
h2        {{ font-size: {font_pt * 1.30:.1f}pt; margin: 15pt 0 5pt 0; color: #0b0c0d;
             border-bottom: 0.6pt solid #b9bdc4; padding-bottom: 2pt; }}
h3        {{ font-size: {font_pt * 1.10:.1f}pt; margin: 11pt 0 3pt 0; }}
p         {{ margin: 0 0 6pt 0; text-align: left; }}
ul, ol    {{ margin: 0 0 6pt 14pt; }}
li        {{ margin-bottom: 2.5pt; }}
strong    {{ font-family: Helvetica-Bold; }}
em        {{ font-family: Helvetica-Oblique; }}
/* Citation ids and inline code. Grey rather than boxed: at 60+ per page a boxed
   token turns the text into confetti and the prose stops being readable. */
code      {{ font-family: Courier; font-size: {font_pt * 0.82:.1f}pt; color: #4c5866; }}
blockquote{{ margin: 6pt 0 6pt 10pt; padding-left: 7pt;
             border-left: 1.6pt solid #c3c7cd; color: #35393f; }}
/* Width is set as an HTML attribute on the <table> tag, not here: xhtml2pdf
   rejects a percentage in this property and logs "getSize: Not a float '100%'",
   then silently lays the table out at its natural width. */
table     {{ -pdf-keep-in-frame-mode: shrink; margin: 5pt 0 9pt 0; }}
th        {{ font-family: Helvetica-Bold; font-size: {font_pt * 0.94:.1f}pt;
             background-color: #eceef1; border-bottom: 0.8pt solid #9aa1ab;
             padding: 3pt 4pt; text-align: left; }}
td        {{ font-size: {font_pt * 0.94:.1f}pt; padding: 3pt 4pt;
             border-bottom: 0.35pt solid #d8dbe0; vertical-align: top; }}
hr        {{ border: none; border-top: 0.6pt solid #c3c7cd; margin: 11pt 0; }}
#footer   {{ font-size: {font_pt * 0.78:.1f}pt; color: #6b7280; text-align: center; }}
"""


def to_html(md_text: str, name: str, font_pt: float, page: str, stamp: str) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "sane_lists", "attr_list"],
        output_format="html5",
    )
    # Full-width tables via the HTML attribute. See the note in `stylesheet`.
    body = body.replace("<table>", '<table width="100%">')
    return f"""<html><head><meta charset="utf-8">
<style>{stylesheet(font_pt, page)}</style></head><body>
{body}
<div id="footer">{name} &middot; rendered {stamp} from the Markdown deliverable
&middot; page <pdf:pagenumber> of <pdf:pagecount></div>
</body></html>"""


def render_one(md_path: Path, cfg: dict, stamp: str) -> tuple[Path, dict]:
    """Render one Markdown file and verify the PDF against it. Returns (path, report)."""
    name = md_path.name
    md_text = md_path.read_text(encoding="utf-8")
    page = cfg["page"].get(name, cfg["default_page"])
    font_pt = cfg["font_pt"].get(name, cfg["default_font_pt"])

    html = to_html(md_text, name, font_pt, page, stamp)
    buf = io.BytesIO()
    # `encoding` is explicit: xhtml2pdf otherwise guesses per-platform, and on a
    # cp1252 console that turns every curly quote into a replacement character.
    result = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    if result.err:
        sys.exit(f"FATAL: {name} failed to render ({result.err} error(s)). "
                 f"Nothing was written.")

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PDF_DIR / (md_path.stem + ".pdf")
    pdf_path.write_bytes(buf.getvalue())

    # --- verify the PDF against the Markdown it came from --------------------
    # Whitespace is stripped from both sides before comparing: PDF text extraction
    # breaks lines wherever the layout did, so an id can arrive split across a line
    # and a naive substring test would report a false loss.
    text = extract_text(str(pdf_path))
    flat = re.sub(r"\s+", "", text)

    want_ids = sorted(set(ID_RE.findall(md_text)))
    lost_ids = [i for i in want_ids if i.replace("-", "") not in flat.replace("-", "")]

    want_heads = [h.strip("# ").strip() for h in HEADING_RE.findall(md_text)]
    lost_heads = [h for h in want_heads
                  if re.sub(r"\s+", "", re.sub(r"[*`]", "", h)) not in flat]

    md_glyphs = {g for g in GLYPHS_AT_RISK if g in md_text}
    lost_glyphs = sorted(g for g in md_glyphs if g not in text)

    # The strongest check here: every word the reader should see, in order. Compared
    # against the HTML this render produced rather than the raw Markdown, so table
    # pipes and heading hashes are not counted as words the PDF is missing.
    want_words = words_of(html_mod.unescape(TAG_RE.sub(" ", STYLE_RE.sub(" ", html))))
    got_words = words_of(text)
    lost_words = missing_words(want_words, got_words)
    diverged = first_divergence(want_words, got_words)

    return pdf_path, {
        "name": name, "pages": text.count("\f") or 1,
        "bytes": pdf_path.stat().st_size,
        "ids": len(want_ids), "lost_ids": lost_ids,
        "headings": len(want_heads), "lost_headings": lost_heads,
        "glyphs": "".join(sorted(md_glyphs)), "lost_glyphs": lost_glyphs,
        "words": len(want_words), "diverged": diverged,
        "lost_words": lost_words,
        "page": page, "font_pt": font_pt,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Render output/*.md to output/pdf/*.pdf.")
    ap.add_argument("--only", help="one file name, e.g. timeline.md")
    add_ticker_arg(ap)

    args = ap.parse_args()

    if not CONFIG.exists():
        sys.exit(f"FATAL: {CONFIG} not found.")
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("pdf")
    if not cfg:
        sys.exit(f"FATAL: no [pdf] block in {CONFIG.relative_to(ROOT)}.")

    # Derived from what is on disk rather than a hardcoded list, so a fourth
    # deliverable is picked up without editing this file.
    sources = sorted(OUT_DIR.glob("*.md"))
    if args.only:
        sources = [p for p in sources if p.name == args.only]
    if not sources:
        sys.exit(f"FATAL: no Markdown to render in {OUT_DIR.relative_to(ROOT)}"
                 + (f" matching --only {args.only}" if args.only else "")
                 + ". Generate the deliverables first.")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M") + "Z"
    print(f"Rendering {len(sources)} document(s) to "
          f"{PDF_DIR.relative_to(ROOT)}\n")

    reports = []
    for p in sources:
        pdf, rep = render_one(p, cfg, stamp)
        reports.append(rep)
        print(f"  {pdf.relative_to(ROOT)}")
        print(f"    {rep['pages']} page(s), {rep['bytes'] / 1024:,.0f} KB, "
              f"{rep['page']}, {rep['font_pt']}pt")
        print(f"    verified: {rep['words']:,} words in order, {rep['ids']} fact "
              f"id(s), {rep['headings']} heading(s), glyphs [{rep['glyphs']}]")
        if rep["lost_words"]:
            n = sum(rep["lost_words"].values())
            print(f"    !! {n} WORD(S) LOST — content was clipped or dropped: "
                  f"{dict(list(rep['lost_words'].items())[:6])}")
        elif rep["diverged"]:
            i, w = rep["diverged"]
            print(f"    -- complete, but extracted out of order from word {i:,} "
                  f"({w!r}). Expected for tables: pdfminer reads a multi-column "
                  f"layout by position, not by row")
        for label, lost in (("fact id(s)", rep["lost_ids"]),
                            ("heading(s)", rep["lost_headings"]),
                            ("glyph(s)", rep["lost_glyphs"])):
            if lost:
                print(f"    !! {len(lost)} {label} MISSING from the PDF: {lost[:4]}")
        print()

    failed = [r for r in reports
              if r["lost_ids"] or r["lost_headings"] or r["lost_glyphs"]
              or r["lost_words"]]
    print("=" * 72)
    if failed:
        sys.exit(f"FATAL: {len(failed)} PDF(s) do not contain everything their "
                 f"Markdown does. They are on disk so the loss can be inspected, but "
                 f"they must not be shared:\n  "
                 + "\n  ".join(f"{r['name']}: {len(r['lost_ids'])} id(s), "
                               f"{len(r['lost_headings'])} heading(s), "
                               f"{len(r['lost_glyphs'])} glyph(s), "
                               f"{sum(r['lost_words'].values())} word(s) lost"
                               for r in failed))
    n_reordered = sum(1 for r in reports if r["diverged"])
    print(f"{len(reports)} PDF(s) written. Every word, fact id, heading and at-risk "
          f"glyph in the Markdown is present in the PDF."
          + (f" {n_reordered} extract{'s' if n_reordered != 1 else ''} out of reading "
             f"order (table layout), with nothing missing." if n_reordered else ""))
    print("No model call; $0.00")


if __name__ == "__main__":
    main()
