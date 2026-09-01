"""The fiscal-year arithmetic, against fiscal years that do not end in December.

Run:  uv run python tests/unit/test_fiscal_year.py

WHY THIS FILE EXISTS
--------------------
MORN's fiscal year ends 12-31, and until now every fiscal-year assignment this
project has ever made was for a December filer. The arithmetic is written
generically, so it *looks* company-neutral — and one branch of it was not.

This is the failure mode the whole file is aimed at: **a fiscal-year error is
silent, consistent, and invisible in the output.** A June filer's "FY2024" is not
a calendar year. If the mapping is off by one, the ledger, the timeline, every
citation and every coverage claim are all wrong together, and all of them look
right. There is no ragged edge to notice.

THE BUG IT FOUND
----------------
`assign_fiscal_year`'s fallback for DEF 14A / DEFA14A / ARS was
`filing_date.year - 1`, with the reasoning: a proxy filed in year N discloses the
compensation of the fiscal year that just ended, N-1.

That reasoning is right and the arithmetic encodes only the December case.
`fd.year - 1` is correct exactly when the fiscal year end and the proxy filing
fall in **different calendar years** — which is always true for a December filer
(year ends 31 December, proxy goes out the following spring) and false for any
filer whose year ends mid-year, because the proxy then goes out later in the
*same* calendar year. Measured across six fiscal year ends, assuming a proxy
filed 105 days after the year closes:

    12-31   FY2024 ends 2024-12-31, proxy 2025-04-15  ->  fd.year-1 = 2024  ok
    09-30   FY2024 ends 2024-09-30, proxy 2025-01-13  ->  fd.year-1 = 2024  ok
    10-31   FY2024 ends 2024-10-31, proxy 2025-02-13  ->  fd.year-1 = 2024  ok
    01-31   FY2024 ends 2024-01-31, proxy 2024-05-15  ->  fd.year-1 = 2023  WRONG
    03-31   FY2024 ends 2024-03-31, proxy 2024-07-14  ->  fd.year-1 = 2023  WRONG
    06-30   FY2024 ends 2024-06-30, proxy 2024-10-13  ->  fd.year-1 = 2023  WRONG

The general rule is "the most recently completed fiscal year as of the filing
date" — `fy_containing(fd, fye) - 1` — which is right for all six and is
**provably identical to the old rule for a December filer**: zero disagreements
across all 366 days of a year, and zero of MORN's 1,000 indexed filings change
fiscal year. That property is what made the fix safe to make at all, because the
facts cache key is (fiscal year, task, filing): a filing that changed fiscal year
would change a cache key, restale the committed ledger, and cost $11.33 to rebuild.

AND A SECOND ONE, WHICH IS NOT ABOUT DECEMBER AT ALL
`assign_fiscal_year` consulted `fy_from_period` first for every form. For a proxy
that is unsound in principle: `reportDate` on a DEF 14A is the **annual meeting
date** by SEC convention, never a period end. It was harmless only because a
meeting normally falls months from the year end and so failed the 10-day
tolerance. A company that meets near its own fiscal year end had the meeting date
accepted as a period end and the proxy attributed to the fiscal year that had not
finished yet — for a December filer too. MORN meets in May, 130 days out, which is
why this never fired here.

WHAT IS NOT ASSERTED HERE
No check names a real company or reads any artifact. The fiscal calendar is a
property of a (month, day) pair, and testing it against MORN's inventory would
only re-confirm the one case that already worked.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from equity_research import discover as d

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


# Six real-world fiscal year ends. December first because it is the case that
# already worked and must keep working; the rest are the ones nobody has run.
#
# Loops over this list AGGREGATE into one check rather than one check per entry:
# the file's check count has to be a property of the file, not of how many fiscal
# year ends anyone thought of. Same reason as the per-company count in Phase 4.6.
FYES = [(12, 31), (1, 31), (3, 31), (6, 30), (9, 30), (10, 31)]
YEARS = [2021, 2022, 2023, 2024, 2025]


# ---------------------------------------------------------------------------
print("THE FISCAL CALENDAR TILES THE REAL ONE — no gap, no overlap")
# ---------------------------------------------------------------------------
# A fiscal year is named for the year it ENDS in, so FY2024 for a June filer runs
# 2023-07-01 to 2024-06-30. Everything else here depends on that.
check("a June fiscal year starts the day after the previous one ends",
      (d.fy_start_date(2024, (6, 30)), d.fy_end_date(2024, (6, 30))),
      (date(2023, 7, 1), date(2024, 6, 30)))
check("  and a December one still runs the calendar year",
      (d.fy_start_date(2024, (12, 31)), d.fy_end_date(2024, (12, 31))),
      (date(2024, 1, 1), date(2024, 12, 31)))

bad = [(fye, fy) for fye in FYES for fy in YEARS
       if d.fy_start_date(fy, fye) != d.fy_end_date(fy - 1, fye) + timedelta(days=1)]
check("every fiscal year begins the day after its predecessor ends", bad, [])

# The boundary triplet: the last day belongs to this year, the next day to the
# next one. An off-by-one anywhere in fy_containing shows up here.
bad = []
for fye in FYES:
    for fy in YEARS:
        end = d.fy_end_date(fy, fye)
        if d.fy_containing(end, fye) != fy:
            bad.append((fye, fy, "end day not in its own FY"))
        if d.fy_containing(end + timedelta(days=1), fye) != fy + 1:
            bad.append((fye, fy, "day after end not in the next FY"))
        if d.fy_containing(d.fy_start_date(fy, fye), fye) != fy:
            bad.append((fye, fy, "start day not in its own FY"))
check("the first and last day of each fiscal year map back to it", bad, [])

# Exhaustive rather than sampled: every day of FY2024 for every fiscal year end.
bad = []
for fye in FYES:
    start, end = d.fy_start_date(2024, fye), d.fy_end_date(2024, fye)
    day = start
    while day <= end:
        if d.fy_containing(day, fye) != 2024:
            bad.append((fye, day))
        day += timedelta(days=1)
check("every single day of FY2024 maps to FY2024, for all six year ends",
      bad, [])


# ---------------------------------------------------------------------------
print()
print("FEBRUARY 29 AND THE END-OF-MONTH GUARD")
# ---------------------------------------------------------------------------
check("a 02-29 fiscal year end lands on the 29th in a leap year",
      d.fy_end_date(2024, (2, 29)), date(2024, 2, 29))
check("  and falls back to the 28th when the year is not a leap year",
      d.fy_end_date(2023, (2, 29)), date(2023, 2, 28))
# The guard exists so fy_start_date does not explode either — it reaches back a
# year, which is exactly where a leap day disappears.
check("  fy_start_date across that boundary is still the day after",
      d.fy_start_date(2025, (2, 29)), date(2024, 3, 1))
check("a 31st-of-the-month year end is unaffected by the guard",
      [d.fy_end_date(y, (3, 31)) for y in (2023, 2024)],
      [date(2023, 3, 31), date(2024, 3, 31)])


# ---------------------------------------------------------------------------
print()
print("parse_fye — what the submissions API actually sends")
# ---------------------------------------------------------------------------
check("'1231' parses to December 31", d.parse_fye("1231"), (12, 31))
check("'0630' parses to June 30", d.parse_fye("0630"), (6, 30))
check("'0131' parses to January 31", d.parse_fye("0131"), (1, 31))
# Every malformed shape falls back to December, which is overwhelmingly the most
# common and is flagged in the discovery report rather than assumed correct.
check("malformed values fall back to December 31",
      [d.parse_fye(x) for x in ("", "   ", "abc", "630", "12310", None)],
      [(12, 31)] * 6)


# ---------------------------------------------------------------------------
print()
print("fy_from_period — separating real period ends from meeting dates")
# ---------------------------------------------------------------------------
# A 10-K's reportDate IS the fiscal year end, for any fiscal year end.
bad = [(fye, fy) for fye in FYES for fy in YEARS
       if d.fy_from_period(d.fy_end_date(fy, fye), fye) != fy]
check("a real period end resolves to its own fiscal year", bad, [])

# The tolerance exists because filers round to the nearest Friday, quarter end, or
# 52/53-week boundary. It must be a tolerance, not a licence.
check("a period end 10 days early is still accepted",
      d.fy_from_period(date(2024, 6, 20), (6, 30)), 2024)
check("  11 days is not", d.fy_from_period(date(2024, 6, 19), (6, 30)), None)
check("a proxy's meeting date months from the year end is rejected",
      d.fy_from_period(date(2024, 10, 15), (6, 30)), None)
check("None in, None out", d.fy_from_period(None, (6, 30)), None)
# The neighbouring-year search: a period ending just after New Year belongs to the
# fiscal year that has just closed, not the calendar year printed on it.
check("a 2025-01-02 period end belongs to FY2024 for a December filer",
      d.fy_from_period(date(2025, 1, 2), (12, 31)), 2024)


# ---------------------------------------------------------------------------
print()
print("THE PROXY CONVENTION — a proxy discloses the year that just CLOSED")
# ---------------------------------------------------------------------------
# This is the bug. A proxy filed some months after the year end solicits the
# say-on-pay vote on, and discloses the compensation of, the fiscal year that has
# just finished. Checked at three lags, because the gap between year end and
# proxy varies by company and the answer must not.
bad = []
for fye in FYES:
    for lag in (75, 105, 160):
        for fy in YEARS:
            filed = d.fy_end_date(fy, fye) + timedelta(days=lag)
            row = {"form": "DEF 14A", "report_date": None, "filing_date": filed}
            got, _ = d.assign_fiscal_year(row, fye)
            if got != fy:
                bad.append((fye, lag, fy, got))
check("a proxy is attributed to the fiscal year that closed before it was filed",
      bad, [])
check("  the same holds for an ARS", [
    d.assign_fiscal_year(
        {"form": "ARS", "report_date": None,
         "filing_date": d.fy_end_date(2024, fye) + timedelta(days=105)}, fye)[0]
    for fye in FYES], [2024] * len(FYES))
check("  and for a DEFA14A, which follows the proxy it supplements", [
    d.assign_fiscal_year(
        {"form": "DEFA14A", "report_date": None,
         "filing_date": d.fy_end_date(2024, fye) + timedelta(days=110)}, fye)[0]
    for fye in FYES], [2024] * len(FYES))

# The December case stated on its own, because it is the one with committed
# artifacts behind it and the fix had to leave it untouched.
check("a December filer's spring proxy still reads as the prior fiscal year",
      d.assign_fiscal_year({"form": "DEF 14A", "report_date": None,
                            "filing_date": date(2025, 4, 15)}, (12, 31))[0], 2024)

# A proxy's reportDate is the MEETING date, never a period end. Consulting the
# period branch for it was unsound in principle and fired for any company meeting
# near its own year end — a December filer included.
bad = []
for fye in FYES:
    end = d.fy_end_date(2024, fye)
    for offset in (-8, -3, 5):          # meetings inside the 10-day tolerance
        meeting = end + timedelta(days=offset)
        filed = meeting - timedelta(days=30)
        row = {"form": "DEF 14A", "report_date": meeting, "filing_date": filed}
        got, _ = d.assign_fiscal_year(row, fye)
        want = d.fy_containing(filed, fye) - 1
        if got != want:
            bad.append((fye, offset, got, want))
check("a meeting date near the year end is not mistaken for a period end",
      bad, [])


# ---------------------------------------------------------------------------
print()
print("THE PERIODIC FORMS ARE UNCHANGED")
# ---------------------------------------------------------------------------
# A 10-K's reportDate is authoritative wherever it verifies as a period end, and
# that must stay true for every fiscal year end.
bad = []
for fye in FYES:
    for fy in YEARS:
        end = d.fy_end_date(fy, fye)
        row = {"form": "10-K", "report_date": end,
               "filing_date": end + timedelta(days=55)}
        got, basis = d.assign_fiscal_year(row, fye)
        if got != fy or "verified period end" not in basis:
            bad.append((fye, fy, got, basis))
check("a 10-K is dated by its verified period end", bad, [])

# An off-cycle period end is kept but flagged: it is what a fiscal-year change or
# a stub period looks like, and silently normalising it would hide a real event.
got, basis = d.assign_fiscal_year(
    {"form": "10-K", "report_date": date(2024, 8, 15),
     "filing_date": date(2024, 10, 1)}, (6, 30))
check("an off-cycle 10-K period end is kept, and flagged for a human",
      (got, "OFF-CYCLE" in basis), (2024, True))
check("a 10-K with no reportDate falls back to the FY containing its filing",
      d.assign_fiscal_year({"form": "10-K", "report_date": None,
                            "filing_date": date(2024, 8, 15)}, (6, 30))[0], 2025)
# 8-Ks are event-driven: no period, so the fiscal year is simply the one the
# filing date falls in. Unchanged by any of this.
check("an 8-K is dated by the fiscal year containing its filing date",
      [d.assign_fiscal_year({"form": "8-K", "report_date": None,
                             "filing_date": date(2024, 8, 15)}, fye)[0]
       for fye in ((12, 31), (6, 30))], [2024, 2025])
check("'10-K/A' is treated as a 10-K", d.base_form("10-K/A"), "10-K")


# ---------------------------------------------------------------------------
print()
print("THE FIX IS A NO-OP FOR A DECEMBER FILER — the safety property")
# ---------------------------------------------------------------------------
# Stated as a test because it is the reason this change could be made without
# spending anything: the facts cache key is (fiscal year, task, filing), so one
# filing changing fiscal year would restale the committed ledger.
#
# Every day of a year, both rules, December: they must never disagree.
disagree = [day for day in (date(2024, 1, 1) + timedelta(days=i) for i in range(366))
            if (day.year - 1) != (d.fy_containing(day, (12, 31)) - 1)]
check("old rule and new rule agree on all 366 days for a December filer",
      disagree, [])
# And the two rules differ for exactly the fiscal year ends they should.
same_cal_year = {fye for fye in FYES
                 if d.fy_end_date(2024, fye).year
                 == (d.fy_end_date(2024, fye) + timedelta(days=105)).year}
check("  and differ only where year end and proxy share a calendar year",
      sorted(same_cal_year), [(1, 31), (3, 31), (6, 30)])


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
