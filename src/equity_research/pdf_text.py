"""PDF text extraction, for the filings that were not filed as HTML.

Most of this pipeline is HTML-first (CLAUDE.md). This module exists for the
exceptions. In the MORN FY2021-FY2025 window there is exactly one:
the FY2022 shareholder letter, filed as `tm2310844d1_ars.pdf`. The six UPLOAD
comment letters are also PDFs, but the SEC files a `.txt` twin of each, so they
never come through here.

Self-test — extracts the FY2022 letter and reports quality:
    uv run python -m equity_research.pdf_text --selftest

---------------------------------------------------------------------------
WHY NOT pypdf
---------------------------------------------------------------------------
pypdf was added first and then removed, because it cannot read this document.

The PDF embeds a SUBSETTED font with no usable ToUnicode CMap. That means the
file records glyph *ids* with no table saying which characters they represent.
Every extractor sees the same raw ids; the difference is what it does with them.

  pypdf          silently coerces unmapped ids toward whitespace. The letters
                 came out shifted but recoverable — and every DIGIT came out as
                 a space. "the index fell 15% for the full year" became "fell
                 for the full year". Plausible prose with the facts deleted:
                 the single worst failure mode for this project, because nothing
                 downstream could detect it.

  pdfminer.six   preserves the ids losslessly as "(cid:N)" markers, so nothing
                 is destroyed and the mapping can be applied deliberately.

The lesson generalizes: prefer the library that preserves what it cannot
interpret over the one that guesses. A visible "(cid:21)" is recoverable; a
space that used to be a "2" is not.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from pdfminer.high_level import extract_text

from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CID_RE = re.compile(r"\(cid:(\d+)\)")

# Glyph ids whose shifted value lands outside printable ASCII. Derived by
# inspecting this font's actual output in context, not guessed:
#
#   cid:299  "bene<299>t"        -> fi ligature
#   cid:300  "cash <300>ow"      -> fl ligature
#   cid:301  "Di<301>erentiated" -> ff ligature
#   cid:338  "There<338>s"       -> right single quote
#   cid:348  "<348>5.2%"         -> MINUS SIGN
#
# cid:348 is deliberately mapped to ASCII "-" rather than an em dash. This font
# uses one glyph for both the em dash in prose ("Index—a benchmark") and the
# minus sign on negative figures ("-5.2%", "-38.1%"). Those two readings cannot
# both be right, so the tie breaks toward the numbers: an em dash rendered as a
# hyphen is cosmetically wrong but never changes meaning, whereas a minus sign
# rendered as an em dash silently strips the sign off a negative number.
GLYPH_OVERRIDES: dict[int, str] = {
    299: "fi",
    300: "fl",
    301: "ff",
    338: "’",   # ’
    348: "-",        # minus, NOT em dash — see above
}

# Words used to confirm the decode produced English rather than noise.
SENTINELS = ("the", "and", "our", "year", "that", "for", "with", "we")


def derive_offset(raw: str) -> tuple[int | None, str]:
    """Work out the glyph-id -> character offset for this font.

    Derived, not hardcoded, so this module is not silently wrong on a different
    company's PDF with a different font subset.

    The space character is by a wide margin the most frequent character in
    running prose, so the most frequent glyph id is the space glyph. Space is
    ASCII 32, which gives the offset directly.
    """
    ids = Counter(int(m) for m in CID_RE.findall(raw))
    if not ids:
        return None, "no (cid:N) markers — font has a usable ToUnicode map, no decode needed"
    space_cid, count = ids.most_common(1)[0]
    offset = 32 - space_cid
    share = count / sum(ids.values())
    return offset, (f"most frequent glyph cid:{space_cid} ({share:.0%} of all glyphs) "
                    f"assumed to be space -> offset {offset:+d}")


def decode_glyphs(raw: str, offset: int) -> tuple[str, dict]:
    """Replace every (cid:N) with its character. Returns (text, report)."""
    unmapped: Counter[int] = Counter()

    def repl(m: re.Match) -> str:
        cid = int(m.group(1))
        if cid in GLYPH_OVERRIDES:
            return GLYPH_OVERRIDES[cid]
        shifted = cid + offset
        if 0x20 <= shifted <= 0x7E:
            return chr(shifted)
        # Neither in range nor overridden: record it and leave a visible marker.
        # A visible marker is recoverable; a silent guess is not.
        unmapped[cid] += 1
        return f"�[cid:{cid}]"

    return CID_RE.sub(repl, raw), {"unmapped_glyphs": dict(unmapped)}


def validate(text: str) -> tuple[bool, dict]:
    """Confirm the decoded text is actually readable English.

    CLAUDE.md: fail loudly. A wrong offset would yield confident-looking garbage,
    so the result is checked rather than assumed.
    """
    lower = text.lower()
    hits = [w for w in SENTINELS if f" {w} " in lower]
    printable = sum(1 for c in text if c.isprintable() or c in "\n\t")
    ratio = printable / len(text) if text else 0.0
    residue = text.count("�")
    ok = len(hits) >= 5 and ratio > 0.95 and residue < len(text) * 0.001
    return ok, {
        "sentinel_words_found": hits,
        "printable_ratio": round(ratio, 4),
        "undecoded_markers": residue,
        "digits": sum(c.isdigit() for c in text),
        "chars": len(text),
    }


def extract(path: Path, pages: list[int] | None = None) -> tuple[str, dict]:
    """Extract text from a PDF, decoding subsetted-font glyph ids if present.

    `pages` is 0-indexed, matching pdfminer. Returns (text, report). Raises on a
    decode that fails validation rather than returning suspect text.
    """
    raw = extract_text(str(path), page_numbers=pages)
    report: dict = {"file": str(path), "pages": pages, "raw_chars": len(raw)}

    offset, note = derive_offset(raw)
    report["offset_note"] = note

    if offset is None:
        report["decoded"] = False
        ok, checks = validate(raw)
        report["validation"] = checks
        report["validation_passed"] = ok
        return raw, report

    report["decoded"] = True
    report["offset"] = offset
    text, dec = decode_glyphs(raw, offset)
    report.update(dec)

    ok, checks = validate(text)
    report["validation"] = checks
    report["validation_passed"] = ok
    if not ok:
        raise ValueError(
            f"PDF glyph decode failed validation for {path.name}.\n"
            f"  {note}\n  checks: {json.dumps(checks, indent=2)}\n"
            "Refusing to return text that may be silently wrong."
        )
    return text, report


# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Run against the one PDF this module exists for, and report quality."""
    manifest = P.fetch_manifest
    if not manifest.exists():
        sys.exit("FATAL: run `uv run python -m equity_research.fetch` first — no fetch-manifest.json.")
    recs = json.loads(manifest.read_text(encoding="utf-8"))["records"]
    pdfs = [r for r in recs if r["filename"].lower().endswith(".pdf") and r["form"] == "ARS"]
    if not pdfs:
        sys.exit("No ARS PDF in the manifest; nothing to self-test against.")

    rec = pdfs[0]
    path = P.resolve(rec["path"])
    print(f"self-test: {rec['form']} FY{rec['fiscal_year']}  {path.name}  ({rec['bytes']:,d} bytes)")
    print()

    text, report = extract(path, pages=list(range(0, 12)))
    print("decode report")
    for k in ("raw_chars", "decoded", "offset", "offset_note", "unmapped_glyphs",
              "validation_passed"):
        if k in report:
            print(f"  {k:20s} {report[k]}")
    for k, v in report["validation"].items():
        print(f"  {k:20s} {v}")
    print()

    # Locate the letter and show it, so the decode can be judged by eye.
    lines = [" ".join(l.split()) for l in text.split("\n")]
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("dear")), None)
    print("=== letter opening, decoded ===")
    if start is None:
        print("  (no 'Dear ...' line found in the first 12 pages)")
    else:
        shown = 0
        for l in lines[start:]:
            if not l:
                continue
            print("   ", l[:100])
            shown += 1
            if shown >= 16:
                break
    print()
    if report["validation_passed"]:
        print("PASS — decode validated. Digits recovered:", report["validation"]["digits"])
    else:
        print("FAIL")


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF text extraction with subsetted-font decoding.")
    ap.add_argument("--selftest", action="store_true", help="run against the FY2022 ARS and report quality")
    ap.add_argument("pdf", nargs="?", help="a PDF to extract")
    ap.add_argument("--pages", help="0-indexed page range, e.g. 0-11")
    add_ticker_arg(ap)

    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return
    if not args.pdf:
        ap.error("give a PDF path, or --selftest")

    pages = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        pages = list(range(int(a), int(b or a) + 1))
    text, report = extract(Path(args.pdf), pages)
    print(json.dumps(report, indent=2), file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
