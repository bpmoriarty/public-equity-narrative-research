"""Milestone 5e — the checks that decide whether an output document is publishable.

Run:  uv run python tests/test_generate_outputs.py

Two things are checked here and neither is about prose quality.

  1. `check_citations` — does every id in the document resolve to a fact?
  2. `check_quotes`    — is every quotation character-for-character the filing's text?

The second is the one that matters most, and the reason is the measurement that
produced it. On the first generation run the id check passed at 323/324 while the
quotation check found 8 defects in 118 quotations. Ids are opaque strings sitting
beside the fact and the model copies them accurately; quotations are reconstructed
from memory of something read 300,000 tokens earlier, and a quotation one word off
looks exactly like a correct one.

So a document can pass the id check completely and still put words in the company's
mouth — and it then reads as MORE sourced than an unsourced sentence would. Every
fixture below is a real string from the first run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import equity_research.generate_outputs as g  # noqa: E402

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


# ---------------------------------------------------------------------------
# A miniature index, using real text from the MORN pack
# ---------------------------------------------------------------------------

INDEX = {
    # The near-miss case. The filing says "low 20's percent range"; the first draft
    # quoted "low 20 percent range" and that single dropped apostrophe-s is the whole
    # difference between a quotation and a misquotation.
    "QA-FY2024-5e714350": {
        "field": "investor_qa", "fiscal_year": 2024, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "During his presentation at the Annual Shareholder Meeting, Jason noted "
                 "that our goal was to increase our adjusted operating margins to recent "
                 "historical peaks and higher. Recent peaks have been in the low 20's "
                 "percent range."},
    # "our most vulnerable segment" was quoted as "the most vulnerable segment".
    "QA-FY2023-2a54a3c6": {
        "field": "investor_qa", "fiscal_year": 2023, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "The company segment continues to be our most vulnerable segment in the "
                 "current market environment, with particular vulnerability with start-ups "
                 "and corporate development teams."},
    # Curly quotes inside the source; the document wrote them as straight singles.
    "QA-FY2025-e40e1959": {
        "field": "investor_qa", "fiscal_year": 2025, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "In order to maintain an aggregate bonus pool amount that is appropriately "
                 "aligned with profits, we monitor the “sharing ratio” expressed "
                 "as a projected bonus payout as a percentage of AOI each quarter."},
    # A risk delta: NO quote field at all, only a heading. Headings come from a
    # deterministic diff of Item 1A, so they are filing text and quoting them is fine.
    "RISK-FY2025-d7eff92c": {
        "field": "risk_deltas", "fiscal_year": 2025, "confidence": "high",
        "quote_verified": None, "source": {},
        "heading": "Our stock price may not reflect our assessment of intrinsic value and "
                   "future sales of our common stock by our significant shareholders and "
                   "fluctuations may affect it."},
    "QA-FY2023-1d4e7aca": {
        "field": "investor_qa", "fiscal_year": 2023, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "We corrected the calculation of adjusted diluted net income per share for "
                 "the quarter ended June 30, 2023, following the identification of a "
                 "clerical error in the calculation."},
    "BRD-FY2021-e7589d5c": {
        "field": "board", "fiscal_year": 2021, "confidence": "low",
        "quote_verified": True, "source": {},
        "quote": "Joe Mansueto has served as our chairman since 1984."},
    "LANG-FY2021-a0b1c2d3": {
        "field": "notable_language", "fiscal_year": 2021, "confidence": "high",
        "quote_verified": False, "source": {},
        "quote": "This quote could not be located in any source section."},
}


def q(text: str) -> dict:
    return g.check_quotes(text, INDEX)


print("\ncheck_quotes — verbatim, near-miss, and fabricated")

check("verbatim span in a fact cited in the same paragraph",
      q('Peaks have been in the "low 20\'s percent range" [QA-FY2024-5e714350].')["ok"], 1)

# THE REGRESSION CASE. One apostrophe-s. This is the defect the id check cannot see.
check("near-miss misquote is caught (low 20 vs low 20's)",
      [b["quote"] for b in
       q('Margins in the "low 20 percent range" [QA-FY2024-5e714350].')["bad"]],
      ["low 20 percent range"])

check("near-miss misquote is caught (the vs our)",
      len(q('its "the most vulnerable segment in the current market environment" '
            '[QA-FY2023-2a54a3c6].')["bad"]), 1)

check("a phrase in no filing text anywhere is caught",
      len(q('management called it "self-inflicted incompetence" [QA-FY2023-2a54a3c6].')
          ["bad"]), 1)

check("the failing quotation carries the text it SHOULD have used",
      q('Margins in the "low 20 percent range" [QA-FY2024-5e714350].')
      ["bad"][0]["permitted"][0]["id"], "QA-FY2024-5e714350")

print("\ncheck_quotes — conventions an honest writer uses")

check("US-style comma inside the closing quote mark is not part of the quotation",
      q('It is "our most vulnerable segment in the current market environment," they say '
        '[QA-FY2023-2a54a3c6].')["ok"], 1)

check("a bracketed editorial insertion still matches",
      q('costs are "in the low 20\'s percent range [for margins]" '
        '[QA-FY2024-5e714350].')["ok"], 1)

check("an ellipsis elides rather than breaks the match",
      q('"we monitor the \'sharing ratio\' … as a percentage of AOI each quarter" '
        '[QA-FY2025-e40e1959].')["ok"], 1)

check("curly quotes in the filing match straight quotes in the document",
      q('the "\'sharing ratio\' expressed as a projected bonus payout" '
        '[QA-FY2025-e40e1959].')["ok"], 1)

check("a risk-delta HEADING is quotable — it has no quote field but is filing text",
      q('One risk was added: "Our stock price may not reflect our assessment of intrinsic '
        'value" [RISK-FY2025-d7eff92c].')["ok"], 1)

print("\ncheck_quotes — the two bugs the first checker had")

# `"ready" rather than a "wish list"` must yield two quotations, not a phantom third
# made of the words between them. Left-to-right pairing is what fixes it.
r = q('clients that were "ready to buy today" rather than a "wish list of prospects" '
      '[QA-FY2024-5e714350].')
check("adjacent quotations pair left to right (no phantom quotation from the gap)",
      r["checked"], 2)
check("  and both of those are reported as defects, not the gap between them",
      sorted(b["quote"] for b in r["bad"]),
      ["ready to buy today", "wish list of prospects"])

# The floor was 12 and excused a real 10-character fabrication.
check("a short fabricated quotation is still checked (floor is 4, not 12)",
      [b["quote"] for b in q('a footnote that "was a typo" [QA-FY2023-1d4e7aca].')["bad"]],
      ["was a typo"])
check("  while the verbatim span in the same fact passes",
      q('corrected for "a clerical error in the calculation" [QA-FY2023-1d4e7aca].')["ok"], 1)

print("\ncheck_quotes — right words, wrong citation")

check("filing text cited in the wrong paragraph is 'elsewhere', not 'bad'",
      len(q('It is "our most vulnerable segment in the current market environment" '
            '[QA-FY2024-5e714350].')["elsewhere"]), 1)
check("  and 'elsewhere' is not counted as verbatim-where-cited",
      q('It is "our most vulnerable segment in the current market environment" '
        '[QA-FY2024-5e714350].')["ok"], 0)
check("a quotation with no citation at all in its paragraph is caught",
      len(q('Management called it "our most vulnerable segment in the current market '
            'environment" with no source.')["elsewhere"]), 1)

print("\ncheck_citations")

c = g.check_citations(
    "One [QA-FY2024-5e714350] two [BRD-FY2021-e7589d5c] three [LANG-FY2021-a0b1c2d3] "
    "four [QA-FY2024-deadbeef] five [QA-FY2024-5e714350].", INDEX)
check("counts every occurrence", c["citations"], 5)
check("counts distinct ids once", c["distinct"], 4)
check("an id not in the pack is unresolved", c["unknown"], ["QA-FY2024-deadbeef"])
check("a low-confidence fact is surfaced for the constraint-1 flag",
      c["low_confidence"], ["BRD-FY2021-e7589d5c"])
check("a fact whose quote was never verified is surfaced",
      c["unverified_quote"], ["LANG-FY2021-a0b1c2d3"])
# Distinct, so the id cited twice counts once, and the unresolvable one counts not at
# all -- `by_field` describes the evidence actually reached, not the citation traffic.
check("fields are tallied over distinct, resolvable ids",
      c["by_field"], {"board": 1, "investor_qa": 1, "notable_language": 1})

print("\nword_count")
# The leftover-bracket bug: stripping ids alone leaves `[, ]`, which str.split() counts
# as two more words. The count is what the document is held to against SPEC.md's
# 1,500-2,500, so it has to measure prose and nothing else.
check("a citation group counts as no words at all",
      g.word_count("Alpha beta gamma [QA-FY2024-5e714350, BRD-FY2021-e7589d5c] delta."), 4)
check("a single-id citation likewise",
      g.word_count("Alpha beta [QA-FY2024-5e714350] gamma."), 3)
check("brackets that are NOT citations still count as prose",
      g.word_count("Alpha [see note] beta."), 4)
check("an id outside brackets is still not prose",
      g.word_count("Alpha QA-FY2024-5e714350 beta."), 2)

print("\nthe id pattern tracks ledger_schema, so a new field cannot become uncheckable")
from equity_research.ledger_schema import FIELD_CODES  # noqa: E402
from equity_research.paths import paths  # noqa: E402

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()
check("every field code the ledger can mint is matched by ID_RE",
      sorted({code for code in FIELD_CODES.values()
              if not g.ID_RE.fullmatch(f"{code}-FY2023-0123abcd")}), [])
check("  including RISK, which is minted outside FIELD_CODES",
      bool(g.ID_RE.fullmatch("RISK-FY2023-0123abcd")), True)

print("\nthe real documents on disk")

# THE SKIP THAT HID ITSELF.
#
# This block used to `continue` when a generation record was missing, printing one
# dim "skipped" line and then a green "29 passed, 0 failed". Six of the 35 checks
# — every check that touches a document actually shipped — silently stopped
# running, and the summary line said nothing was wrong. That is precisely the
# false-assurance shape this file's own docstring warns about, one level up: a
# suite that passes because it did not run is worse than a suite that fails.
#
# It went unnoticed because data/pack/ was gitignored, so the records existed in
# the working tree and vanished in a clean checkout — the one place a green run
# gets believed. gen-*.json are committed now (see .gitignore), so absence means
# something is wrong rather than something is merely underived.
#
# The two causes are reported separately because they have different fixes:
#   record missing -> a committed file has been deleted; restore it.
#   index missing  -> the pack has not been built; one free, deterministic command.
# Folding them together would print the wrong instruction half the time.
n_docs = 0
idx_p = P.pack / "index.json"
idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else None

for slug, d in g.DOCS.items():
    rec_p = P.pack / f"gen-{slug}.json"
    if not rec_p.exists():
        FAIL += 1
        print(f"  FAIL  {d['file']}: generation record {rec_p.relative_to(ROOT)} is "
              f"MISSING.\n"
              f"          It is a committed file — model output, the only copy of "
              f"`text_before_repair`.\n"
              f"          Restore it (`git checkout -- {rec_p.relative_to(ROOT)}`) or "
              f"regenerate (~$3.50).\n"
              f"          Without it the three checks below do not run, and this suite "
              f"must not report green.")
        continue
    if idx is None:
        FAIL += 1
        print(f"  FAIL  {d['file']}: {idx_p.relative_to(ROOT)} is missing, so no id can "
              f"be resolved.\n"
              f"          The pack is derived and free to rebuild: "
              f"uv run python src/build_pack.py")
        continue

    n_docs += 1
    rec = json.loads(rec_p.read_text(encoding="utf-8"))
    # `shipped_text` is the body actually written to output/ — identical to `text`
    # unless a recorded correction was applied after generation. See
    # `apply_corrections` in src/generate_outputs.py: a correction is data in this
    # record, never a silent hand-edit of the document.
    shipped = rec.get("shipped_text") or rec["text"]
    check(f"{d['file']}: every id resolves",
          g.check_citations(shipped, idx)["unknown"], [])
    check(f"{d['file']}: every quotation is verbatim filing text",
          [b["quote"] for b in g.check_quotes(shipped, idx)["bad"]], [])
    check(f"{d['file']}: the rendered file matches the recorded body",
          shipped.strip() in (P.output / d["file"]).read_text(encoding="utf-8"),
          True)
    # A correction that is not in the record is a hand-edit, which is the thing the
    # check above exists to prevent. So the record must also be internally honest:
    # if it claims corrections, it must carry the pre-correction text to diff against.
    if rec.get("corrections"):
        check(f"{d['file']}: every correction is recorded with the text it replaced",
              bool(rec.get("text")) and shipped != rec["text"], True)

# The count itself is asserted, so a document dropped from DOCS — or a loop that
# quietly stops early — cannot pass by checking nothing.
check("every configured document was checked", n_docs, len(g.DOCS))

print(f"\n{PASS} passed, {FAIL} failed  ({n_docs} of {len(g.DOCS)} generated "
      f"document(s) checked)")
sys.exit(1 if FAIL else 0)
