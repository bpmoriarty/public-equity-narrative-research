"""The final year's vote 8-K, and the one rule that decides which 8-K a vote is in.

Run:  uv run python tests/unit/test_vote_pairing.py

WHY THIS FILE EXISTS
--------------------
docs/history/PHASE6_SCOPE.md finding 4. `votes` reads the 8-K Item 5.07 that reports the
vote held at the meeting a fiscal year's proxy called. That 8-K is filed in the
FOLLOWING fiscal year, so for the last year of a window it is labelled one year
past the window, `in_window: false` — and `fetch` downloaded in-window filings
only. Every company run through `pipeline` silently lost its final year's
say-on-pay and director-election votes. MORN looked complete because a human
had fetched its 8-K by hand, which is worse than untested: it left a passing
example behind.

The fix puts the pairing rule in `vote_pairing.py`, shared by `fetch` (to
download the filing) and `extract_facts.gather_votes` (to read it), so the two
can never disagree again. The checks below ask three things:

  1. Does the rule pair each proxy with the right 8-K — by FILING DATE, never
     by fiscal-year label, and never past the next proxy?
  2. Does `fetch`'s work list now include the final year's 8-K, and ONLY that —
     the window itself must not widen?
  3. Do `fetch` and `gather_votes` name the same filing for every year?

Every fixture is synthetic: a December filer, window FY2022-FY2024, built from
the shape of the real MORN and MSFT inventory rows. No company data is read and
no network is touched. `run_all` supplies EQR_TICKER, because importing a stage
module resolves a ticker at import time; nothing here reads that company.
"""

from __future__ import annotations

import copy
import sys

from equity_research import extract_facts as ef
from equity_research import fetch, vote_pairing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


def row(acc, form, filed, fy, *, items=(), in_window=True, disposition="in_scope"):
    """One inventory row, with only the fields these functions read."""
    return {"accession": acc, "form": form, "filing_date": filed, "fiscal_year": fy,
            "items": list(items), "in_window": in_window, "disposition": disposition}


# A December filer. Proxy for FY N is filed in March N+1; the vote 8-K follows in
# May N+1 — so it carries fiscal year N+1, and for FY2024 that is OUTSIDE the
# window. That last row is the whole of finding 4.
FILINGS = [
    row("V-2022-05", "8-K",     "2022-05-12", 2022, items=["5.07"]),     # vote on the FY2021 proxy
    row("P-FY2022",  "DEF 14A", "2023-03-30", 2022),
    row("V-2023-05", "8-K",     "2023-05-11", 2023, items=["5.02", "5.07"]),
    row("E-2023-05", "8-K",     "2023-05-20", 2023, items=["2.02"]),     # an 8-K, but not a vote
    row("P-FY2023",  "DEF 14A", "2024-03-29", 2023),
    row("V-2024-05", "8-K/A",   "2024-05-10", 2024, items=["5.07"]),     # an amendment still counts
    row("K-FY2024",  "10-K",    "2025-02-20", 2024),
    row("P-FY2024",  "DEF 14A", "2025-03-28", 2024),
    row("V-2025-05", "8-K",     "2025-05-09", 2025, items=["5.07"], in_window=False),
    row("Q-2025-08", "10-Q",    "2025-08-01", 2025, in_window=False),    # must NOT be swept in
]
INV = {"first_fiscal_year": 2022, "last_fiscal_year": 2024,
       "as_of_utc": "2025-09-01T00:00:00Z", "filings": FILINGS}


def without(inv: dict, *accessions: str) -> dict:
    out = copy.deepcopy(inv)
    out["filings"] = [r for r in out["filings"] if r["accession"] not in accessions]
    return out


def acc(r):
    return r["accession"] if r else None


# ---------------------------------------------------------------------------
print("\n1. the pairing rule")
# ---------------------------------------------------------------------------

pairs = {fy: acc(vote_pairing.paired_vote_filing(FILINGS, fy)[1]) for fy in (2022, 2023, 2024)}
check("each proxy pairs with the first vote 8-K filed after it",
      pairs, {2022: "V-2023-05", 2023: "V-2024-05", 2024: "V-2025-05"})

# The off-by-one the rule exists for: the vote reporting on FY N's proxy is
# labelled FY N+1, for every year. Pairing on the label would be wrong every time.
labels = {fy: vote_pairing.paired_vote_filing(FILINGS, fy)[1]["fiscal_year"]
          for fy in (2022, 2023, 2024)}
check("  every paired vote carries the NEXT fiscal year's label",
      labels, {2022: 2023, 2023: 2024, 2024: 2025})
check("  the vote 8-K filed before FY2022's proxy (last year's meeting) is not taken",
      "V-2022-05" in pairs.values(), False)
check("  an 8-K without item 5.07 is not a vote filing",
      vote_pairing.is_vote_filing(FILINGS[3]), False)

check("a year with no in-scope proxy pairs with nothing",
      vote_pairing.paired_vote_filing(FILINGS, 2021), (None, None))
oos = copy.deepcopy(FILINGS)
next(r for r in oos if r["accession"] == "P-FY2023")["disposition"] = "out_of_scope"
check("  an out-of-scope proxy does not count as the year's proxy",
      vote_pairing.paired_vote_filing(oos, 2023), (None, None))

# THE BOUND. With FY2023's vote missing, the unbounded rule took the next 5.07
# after FY2023's proxy — FY2024's vote — and attributed one vote to two years.
# This happened for real, outside the window, on MSFT's FY2008/FY2009 proxies.
gap = without(INV, "V-2024-05")
check("a missing vote is NOT filled with the next year's vote 8-K",
      acc(vote_pairing.paired_vote_filing(gap["filings"], 2023)[1]), None)
check("  and the next year still gets its own",
      acc(vote_pairing.paired_vote_filing(gap["filings"], 2024)[1]), "V-2025-05")


# ---------------------------------------------------------------------------
print("\n2. the window's vote filings, and the notes for gaps")
# ---------------------------------------------------------------------------

rows, notes = vote_pairing.vote_filings_for_window(INV)
check("one vote filing per window year, in fiscal-year order",
      [acc(r) for r in rows], ["V-2023-05", "V-2024-05", "V-2025-05"])
# Guarded lookups here and below: a broken rule must FAIL these checks and let
# the rest of the file run, not crash and hide every check after it.
check("  the last one is the out-of-window filing",
      rows[-1]["in_window"] if rows else None, False)
check("  a complete inventory produces no notes", notes, [])

# The last year's meeting has not happened yet: a legitimate gap, and a named one.
_, early = vote_pairing.vote_filings_for_window(without(INV, "V-2025-05"))
check("final year with no vote yet: exactly one note", len(early), 1)
first = early[0] if early else ""
check("  it names the year and says the meeting may not have happened",
      ("FY2024" in first, "has not happened yet" in first), (True, True))

# A middle year with no vote is a different situation and must not be excused
# as "the meeting has not happened yet".
_, mid = vote_pairing.vote_filings_for_window(gap)
first = mid[0] if mid else ""
check("middle year with no vote: one note, NOT the not-happened-yet wording",
      (len(mid), "FY2023" in first, "has not happened yet" in first), (1, True, False))


# ---------------------------------------------------------------------------
print("\n3. fetch's work list")
# ---------------------------------------------------------------------------

work, added, wnotes = fetch.build_work_list(INV, None)
in_window = [r for r in FILINGS if r["in_window"]]
check("the final year's vote 8-K is in the work list",
      "V-2025-05" in {acc(r) for r in work}, True)
check("  and it is the ONLY filing added beyond the window",
      [acc(r) for r in added], ["V-2025-05"])
check("  the window is not widened: the out-of-window 10-Q is not swept in",
      "Q-2025-08" in {acc(r) for r in work}, False)
check("  counts reconcile: in-window filings + the look-ahead (rule 5)",
      len(work), len(in_window) + len(added))
check("  in-window votes are not added twice",
      len({acc(r) for r in work}), len(work))

# --accession is an exact override and must stay exact.
work, added, _ = fetch.build_work_list(INV, ["K-FY2024"])
check("--accession fetches exactly what is named, with no look-ahead",
      ([acc(r) for r in work], added), (["K-FY2024"], []))

# Nothing to add is not an error, and the note reaches the caller.
work, added, wnotes = fetch.build_work_list(without(INV, "V-2025-05"), None)
check("vote not yet filed: nothing added, one note returned",
      (added, len(wnotes)), ([], 1))


# ---------------------------------------------------------------------------
print("\n4. fetch and gather_votes agree on every year")
# ---------------------------------------------------------------------------
# gather_votes reads section text from disk; replace that one function so the
# check exercises the real selection logic against a synthetic sections list.

def sections_for(filings):
    return [{"key": "8-K_5.07", "accession": r["accession"], "form": r["form"],
             "filing_date": r["filing_date"], "fiscal_year": r["fiscal_year"],
             "doc_type": "8-K", "ok": True, "out": "x"}
            for r in filings if vote_pairing.is_vote_filing(r)]

real_read_section = ef.read_section
ef.read_section = lambda r: "TEXT"
try:
    read ={fy: [d["accession"] for d in ef.gather_votes(sections_for(FILINGS), INV, fy)]
            for fy in (2022, 2023, 2024)}
    check("gather_votes reads, for each year, the filing fetch downloads",
          read, {2022: ["V-2023-05"], 2023: ["V-2024-05"], 2024: ["V-2025-05"]})
    check("  every filing gather_votes reads is one fetch's work list contains",
          {a for v in read.values() for a in v} <= {acc(r) for r in fetch.build_work_list(INV, None)[0]},
          True)
    check("  gather_votes honours the bound too (no borrowed vote)",
          ef.gather_votes(sections_for(gap["filings"]), gap, 2023), [])
finally:
    ef.read_section = real_read_section


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
