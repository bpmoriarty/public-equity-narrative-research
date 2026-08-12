"""Milestone 5f — the constraint gates on the finished deliverables.

Run:  uv run python tests/test_verify_outputs.py

Every hard check is exercised twice: on a document that should fail it and on one that
should pass. A check only tested against passing input tells you nothing — it would
still pass if its body were `return True`, which is the failure mode that makes a
verification suite worse than none.

The review detectors get the opposite treatment. Both were rewritten after measuring
them against the real documents, and the sentences they used to fire on wrongly are
kept here as regression cases:

  - "never compare segment counts" first fired on 6 sentences, all false positives —
    the company's own "we have one reportable segment" quotation, and PitchBook's
    "companies segment", a different sense of the word.
  - the sentence splitter first ran over the whole body at once, welding the last
    sentence of one paragraph to the first heading of the next, and that artifact
    alone produced one of those hits.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import equity_research.verify_outputs as v  # noqa: E402
from equity_research.paths import paths  # noqa: E402

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

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
# Fixtures
# ---------------------------------------------------------------------------

SHA = "a" * 64

PACK = {
    # FY2022 carries a `facts` block so the numeric-evidence tiers are reachable
    # end-to-end. `claim` is what the model was shown; `quote` is what a reader can
    # resolve. The vote fact below states 507,847 in BOTH (-> QUOTED) and 15,365 in
    # the claim only (-> THIN), which is the whole distinction under test.
    "years": {"FY2021": {},
              "FY2022": {"facts": {"vote_results": [{
                  "id": "VOTE-FY2022-44444444",
                  "claim": {"matter": "say-on-pay", "votes_against": 507847,
                            "abstentions": 15365},
                  "quote": "Say-on-pay was approved with 507,847 votes against.",
                  "src": "8-K|acc|8K_item507|2022-05-13"}]}},
              "FY2023": {}},
    "constraints": [{
        "rule": "Never compare segment counts across the whole window.",
        "scope": "product/business areas: FY2021, FY2022; reportable segments: FY2023. "
                 "Use the segment names and the filing's own language, never the count."}],
}

INDEX = {
    "SP-FY2021-11111111": {"field": "strategic_priorities", "fiscal_year": 2021,
                           "confidence": "high", "quote_verified": True,
                           "quote": "We aim to deliver insights essential to investing.",
                           "source": {"section_key": "10K_item1"}},
    # A letter-sourced fact. FY2021 has none, which is the whole point of constraint 6.
    "LANG-FY2022-22222222": {"field": "notable_language", "fiscal_year": 2022,
                             "confidence": "high", "quote_verified": True,
                             "quote": "There's no sugarcoating our results this year.",
                             "source": {"section_key": "letter_full_text"}},
    "BRD-FY2021-33333333": {"field": "board", "fiscal_year": 2021, "confidence": "low",
                            "quote_verified": True,
                            "quote": "Joe Mansueto has served as our chairman since 1984.",
                            "source": {"section_key": "DEF14A_director_bios"}},
    "VOTE-FY2022-44444444": {"field": "vote_results", "fiscal_year": 2022,
                             "confidence": "high", "quote_verified": True,
                             "quote": "Say-on-pay was approved with 507,847 votes against.",
                             "source": {"section_key": "8K_item507"}},
    "QA-FY2023-55555555": {"field": "investor_qa", "fiscal_year": 2023,
                           "confidence": "high", "quote_verified": True,
                           "quote": "We do not have business operating segments. "
                                    "We have one reportable segment.",
                           "source": {"section_key": "8K_qa"}},
    "LANG-FY2023-66666666": {"field": "notable_language", "fiscal_year": 2023,
                             "confidence": "high", "quote_verified": False,
                             "quote": "This quote was never located in a source section.",
                             "source": {"section_key": "letter_full_text"}},
}

CFG = {
    "documents": ["doc.md"],
    "low_confidence_flag_pattern":
        r"(?:low[- ]confidence|unverified|indicative|boundaries are unverified)",
    "date_pattern": r"(?:\b\d{1,2}\s+\w+\s+20\d\d\b|\b\w+\s+\d{1,2},\s+20\d\d\b|\b20\d\d\b)",
    "reg_fd_pattern": r"(?:regulation fd|reg fd|voluntary disclosure)",
    "qa_subject_pattern": r"(?:question|answer|investor q&a|reg fd|regulation fd)",
    "qa_majority_share": 0.5,
    "word_range": {"doc.md": [5, 5000]},
    "required_headings": {"doc.md": ["## Observations"]},
}

PF = v.pack_facts(PACK, INDEX)
PROV = f"\n\n### Provenance\n\n- **pack sha256** `{SHA}`\n"


def run(body: str, cfg: dict | None = None, sha: str = SHA) -> dict:
    """Verify a synthetic document; return {tag: ok}."""
    r = v.verify("doc.md", body + PROV, PACK, INDEX, PF, cfg or CFG, sha)
    return {row["tag"]: row["ok"] for row in r.rows if row["kind"] == "HARD"}


def reviews(body: str) -> dict:
    r = v.verify("doc.md", body + PROV, PACK, INDEX, PF, CFG, SHA)
    return {row["name"]: len(row["items"]) for row in r.rows if row["kind"] == "REVIEW"}


# A document that passes everything, used as the baseline each failing case perturbs.
GOOD = """## Observations

These are Regulation FD voluntary disclosures, and the register is named here before
any of them is used. Shareholder letters are present for FY2022 onward and absent for
FY2021, so this is a shorter record than the window.

Management stated one reportable segment [QA-FY2023-55555555], and the letter conceded
the year had gone badly [LANG-FY2022-22222222].

Board facts here are low-confidence because the proxy biography boundaries are
unverified [BRD-FY2021-33333333].

Say-on-pay drew 507,847 against at the meeting held 13 May 2022 [VOTE-FY2022-44444444].

The stated aim is growth [SP-FY2021-11111111]."""

print("\nthe baseline document passes every hard check")
base = run(GOOD)
for tag, ok in sorted(base.items()):
    check(f"  {tag}", ok, True)

print("\nprovenance")
check("a document with no pack sha256 fails",
      v.verify("doc.md", GOOD, PACK, INDEX, PF, CFG, SHA).rows[0]["ok"], False)
check("a document written from a DIFFERENT pack fails",
      run(GOOD, sha="b" * 64)["prov_matches"], False)

print("\nconstraint 5 — citations and quotations")
check("an id that resolves to nothing fails",
      run(GOOD.replace("[SP-FY2021-11111111]", "[SP-FY2021-deadbeef]"))["ids_resolve"], False)
check("a quotation matching no filing text fails",
      run(GOOD + '\n\nManagement called it "a resounding triumph" '
                 '[SP-FY2021-11111111].')["quotes_verbatim"], False)
check("a verbatim quotation from a fact cited elsewhere ALSO fails",
      run(GOOD + '\n\nThe aim is "There\'s no sugarcoating our results this year" '
                 '[SP-FY2021-11111111].')["quotes_verbatim"], False)
check("quoting in a paragraph that cites a never-verified fact fails",
      run(GOOD + '\n\nThe letter said "something" [LANG-FY2023-66666666].')
      ["no_unverified_quoted"], False)
check("  but citing that fact WITHOUT quoting is allowed",
      run(GOOD + "\n\nThe letter made a similar point [LANG-FY2023-66666666].")
      ["no_unverified_quoted"], True)

print("\nconstraint 1 — low-confidence facts are flagged")
check("citing a low-confidence fact with no flag word fails",
      run(GOOD.replace("are low-confidence because the proxy biography boundaries are\n"
                       "unverified", "are solid"))["low_conf_flagged"], False)

print("\nconstraint 3 — a vote claim carries its date")
check("a vote sentence with no date fails",
      run(GOOD.replace("at the meeting held 13 May 2022", "at the annual meeting"))
      ["vote_dated"], False)
check("  a bare year is enough",
      run(GOOD.replace("held 13 May 2022", "held in 2022"))["vote_dated"], True)

print("\nconstraint 4 — the Regulation FD register")
check("citing QA facts without ever naming the register fails",
      run(GOOD.replace("These are Regulation FD voluntary disclosures, and the register "
                       "is named here before\nany of them is used. ", ""))
      ["reg_fd_established"], False)
check("naming the register only AFTER the first QA citation fails",
      run("## Observations\n\nManagement stated one reportable segment "
          "[QA-FY2023-55555555].\n\nThose were Regulation FD disclosures.\n\n"
          "Letters are absent for FY2021.")["reg_fd_established"], False)
check("a document citing no QA facts passes trivially",
      run("## Observations\n\nThe stated aim is growth [SP-FY2021-11111111].")
      ["reg_fd_established"], True)
check("laying QA counts out as a year-by-year series fails",
      run(GOOD + "\n\nInvestor questions answered: 2021, 113; 2022, 157; 2023, 231; "
                 "2024, 163.")["qa_not_a_series"], False)

print("\nconstraint 6 — the shareholder letter is not present for every year")
check("citing letter facts without naming the missing year fails",
      run(GOOD.replace("Shareholder letters are present for FY2022 onward and absent for\n"
                       "FY2021, so this is a shorter record than the window.", ""))
      ["letter_gap_named"], False)
check("  naming it passes",
      run(GOOD)["letter_gap_named"], True)
check("a document citing NO letter facts passes trivially",
      run("## Observations\n\nRegulation FD answers aside, the aim is growth "
          "[SP-FY2021-11111111].")["letter_gap_named"], True)

print("\nshape")
check("a missing required section fails",
      run(GOOD.replace("## Observations", "## Something else"))["sections_present"], False)
check("a document under the word floor fails",
      run("## Observations\n\nToo short.")["length"], False)

print("\nreview detectors — the regression cases they used to fire on wrongly")
FALSE_POSITIVES = [
    'Management insisted that "We do not have business operating segments. We have one '
    'reportable segment" [QA-FY2023-55555555].',
    "Effective December 31, 2023 the company concluded it had seven operating segments "
    "presented as five reportable ones [QA-FY2023-55555555].",
    "In 2021 and 2022 the methodology required three use cases for the companies "
    "segment [QA-FY2023-55555555].",
]
for i, s in enumerate(FALSE_POSITIVES, 1):
    n = reviews(GOOD + "\n\n" + s)["segment counts compared across the disclosure-basis change"]
    check(f"  false positive {i} no longer fires", n, 0)

check("a real cross-basis count comparison DOES fire",
      reviews(GOOD + "\n\nThe company reported one segment in 2021 and five segments in "
                     "2023 [QA-FY2023-55555555].")
      ["segment counts compared across the disclosure-basis change"], 1)

print("\nthe sentence splitter does not span paragraphs")
check("a sentence never welds across a blank line",
      any("Observations" in s and "Regulation" in s
          for s in v.sentences("## Observations\n\nRegulation FD applies here.")), False)
check("  and both paragraphs still yield their sentences",
      len(v.sentences("One. Two.\n\nThree.")), 3)

print("\nnumeric evidence — the three tiers (VERIFICATION.md D2)")
# A miniature index/pack pair mirroring the real shapes. The vote fact is the real
# defect: its quote is the sentence that INTRODUCES the table, so the figure the
# document states is nowhere in the evidence a reader can resolve.
NE_INDEX = {
    "VOTE-FY2023-aaaaaaaa": {
        "field": "vote_results", "fiscal_year": 2023, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "Each of the nominees for director, as listed in the proxy statement, "
                 "was elected with the number of votes set forth below:"},
    "LANG-FY2024-bbbbbbbb": {
        "field": "notable_language", "fiscal_year": 2024, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "Average revenue per employee increased to roughly $200,000 from "
                 "$170,000 in 2023."},
    "RISK-FY2025-cccccccc": {
        "field": "risk_deltas", "fiscal_year": 2025, "confidence": "high",
        "quote_verified": None, "source": {},
        "heading": "We depend on 1,200 data suppliers."},
}
NE_CLAIMS = {
    "VOTE-FY2023-aaaaaaaa": v.numbers_in('{"votes_against": 9935476}'),
    "LANG-FY2024-bbbbbbbb": set(),
    "RISK-FY2025-cccccccc": set(),
}
ne = lambda p: v.numeric_evidence([p], NE_INDEX, NE_CLAIMS)

check("a figure inside a cited fact's quote is QUOTED — reported nowhere",
      ne("Revenue per employee reached $200,000 [LANG-FY2024-bbbbbbbb]."),
      {"thin": [], "unsourced": []})
check("a figure in the claim but not the quote is THIN",
      len(ne("9,935,476 votes were cast against [VOTE-FY2023-aaaaaaaa].")["thin"]), 1)
check("  and is NOT reported as unsourced — it is traceable, just not evidenced",
      ne("9,935,476 votes were cast against [VOTE-FY2023-aaaaaaaa].")["unsourced"], [])
check("a figure in neither quote nor claim is UNSOURCED",
      len(ne("Some 8,484 shares were repurchased [VOTE-FY2023-aaaaaaaa].")
          ["unsourced"]), 1)
check("a figure in a risk delta's HEADING is quotable evidence like any quote",
      ne("It names 1,200 data suppliers [RISK-FY2025-cccccccc]."),
      {"thin": [], "unsourced": []})

print("\n  the two tokenizer bugs the first version of this check had")
# THE REGRESSION CASES. Both reported a defect in the document that was really a
# defect in the checker — the worst kind, because it trains a reader to ignore the
# check. Each is a real string from discussion-points.md.
check("a dollar amount is one figure, not its trailing zeros ($200,000 -> 200000)",
      sorted(v.NUM_RE.findall("increased to roughly $200,000 from $170,000")),
      ["170,000", "200,000"])
check("  so a correctly-evidenced dollar amount does not report as unsourced",
      ne('The letter says "$200,000" per employee [LANG-FY2024-bbbbbbbb].')
      ["unsourced"], [])
check("an SEC item number is a name, not a quantity (Item 5.07)",
      v.NUM_RE.findall(v.NOT_A_FIGURE.sub(" ", "the Item 5.07 vote disclosure")), [])
check("  likewise Item 1A, Rule 10b5-1 and a form number",
      v.NUM_RE.findall(v.NOT_A_FIGURE.sub(
          " ", "Item 1A of the 10-K, and Rule 10b5-1 plans, and DEF 14A")), [])
check("a four-digit year is not a figure to evidence",
      ne("Revenue grew through 2023 and 2024 [VOTE-FY2023-aaaaaaaa]."),
      {"thin": [], "unsourced": []})

print("\n  UNSOURCED is a HARD check — exercised on failing input, not just passing")
# This file's own rule: a check tested only against passing input would still pass
# if its body were `return True`. The failing fixture is the real defect, shortened —
# 8,484 shares for $1.4 million cited to a fact carrying only the authorisation.
# VERIFICATION.md D3, which this check found rather than was told about.
UNSOURCED_DOC = GOOD + ("\n\nThe successor buyback was dormant: 8,484 shares for "
                        "$1.4 million [VOTE-FY2022-44444444].")
check("a figure in neither the quote nor the claim FAILS the hard check",
      run(UNSOURCED_DOC)["figures_evidenced"], False)
check("  while the same document without it passes",
      run(GOOD)["figures_evidenced"], True)

# THIN must NOT fail the build. It is measured, recorded, and deferred to D2(b);
# a hard gate on it would block every build on a known class.
THIN_DOC = GOOD + ("\n\nThere were 15,365 abstentions on the matter "
                   "[VOTE-FY2022-44444444].")
check("a figure in the claim but not the quote does NOT fail the build",
      run(THIN_DOC)["figures_evidenced"], True)
check("  but it IS surfaced for review",
      reviews(THIN_DOC)["figures traceable to a cited fact's claim but NOT to its "
                        "quote"], 1)
check("a figure present in the quote is reported in neither tier",
      (run(GOOD)["figures_evidenced"],
       reviews(GOOD)["figures traceable to a cited fact's claim but NOT to its quote"]),
      (True, 0))

print("\n  scope is the PARAGRAPH, because that is the pack's citation granularity")
check("evidence cited one sentence earlier still counts",
      ne('The letter reports "$200,000" per employee [LANG-FY2024-bbbbbbbb]. '
         'That figure of $200,000 is the highest in the window.'),
      {"thin": [], "unsourced": []})
check("a paragraph citing nothing at all is not scanned",
      ne("Revenue per employee reached $200,000 last year."),
      {"thin": [], "unsourced": []})

print("\ncheck tags are unique and stable")
tags = [r["tag"] for r in
        v.verify("doc.md", GOOD + PROV, PACK, INDEX, PF, CFG, SHA).rows
        if r["kind"] == "HARD"]
check("no duplicate tags", len(tags), len(set(tags)))
check("the two provenance tags the repair path skips are present",
      sorted(t for t in tags if t.startswith("prov_")), ["prov_matches", "prov_present"])

print("\npack facts are derived, never named in source")
check("letter years read off the index", PF["letter_years"], [2022, 2023])
check("  so the missing year is derived too", PF["no_letter"], [2021])
check("segment bases read off the pack's own constraint",
      (PF["segment_product_years"], PF["segment_reportable_years"]),
      ([2021, 2022], [2023]))

print("\nthe real documents on disk, if they have been generated")
n_docs = 0
if (P.pack / "pack.json").exists():
    payload, pack, index, cfg, _gen = v.load()
    import hashlib
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    pf = v.pack_facts(pack, index)
    for doc in cfg["documents"]:
        p = P.output / doc
        if not p.exists():
            print(f"  --    {doc} not generated; skipped")
            continue
        n_docs += 1
        r = v.verify(doc, p.read_text(encoding="utf-8"), pack, index, pf, cfg, sha)
        check(f"{doc}: every hard check passes",
              [f["tag"] for f in r.failures], [])
        # The numeric-evidence calibration, held where it is STABLE. The brief is
        # asserted clean on both tiers — 19 figures, all in a cited fact's quote.
        # discussion-points.md is deliberately NOT asserted at a count: it currently
        # carries 2 unsourced (D3) and 17 thin (D2), and both numbers are supposed to
        # move as those are fixed. A test pinned to today's defect count has to be
        # edited every time a defect is fixed, which trains you to edit tests.
        if doc == "narrative-brief.md":
            ev = v.numeric_evidence(v.paragraphs(v.body_of(
                p.read_text(encoding="utf-8"))), index, v.claim_numbers(pack))
            check(f"  {doc}: every figure is in a cited fact's quote",
                  ev, {"thin": [], "unsourced": []})

print(f"\n{PASS} passed, {FAIL} failed  ({n_docs} generated document(s) checked)")
sys.exit(1 if FAIL else 0)
