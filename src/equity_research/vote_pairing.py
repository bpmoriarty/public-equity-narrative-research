"""Which 8-K Item 5.07 reports the shareholder vote on a fiscal year's proxy.

ONE RULE, TWO CALLERS
---------------------
`extract_facts.gather_votes` needs this to choose what the `votes` task reads.
`fetch` needs it to make sure that filing is on disk. Before this module existed
only the first asked, and the two disagreed silently for the last year of every
window (docs/history/PHASE6_SCOPE.md, finding 4):

  - A DEF 14A for fiscal year N is filed after year N closes, and solicits votes
    at the annual meeting that follows. The 8-K Item 5.07 reporting the RESULT
    is filed days after that meeting — so it is dated in fiscal year N+1.
  - `discover` labels every filing with the fiscal year it falls in, so for the
    LAST year of the window that 8-K is labelled one year past the window and
    carries `in_window: false`.
  - `fetch` downloads in-window filings only. So the one filing the final year's
    `votes` task needs was never fetched, `extract_facts` reported
    `FY<last> votes: no source`, and the run otherwise succeeded. MORN looked
    complete only because a human had fetched its 8-K by hand.

The rule lives here, rather than in either stage, so that the downloader does not
depend on the paid extraction stage and the two can never apply different rules.

WHY PAIR ON THE PROXY'S FILING DATE
-----------------------------------
Pairing on the fiscal-year LABEL would attach every vote to the wrong year — the
same class of error as trusting a proxy's `reportDate`, which in milestone 1
misdated every proxy by a year. So the rule is: the first 8-K carrying item 5.07
filed AFTER the DEF 14A for year N — and BEFORE the next DEF 14A.

The upper bound was added with this module. Without it, a year whose vote 8-K
is missing from the inventory silently borrowed the NEXT year's: the first 5.07
after its proxy is then the following year's, so one vote was attributed to two
fiscal years. A vote reported after the next proxy cannot be the result of this
proxy's meeting. Bounded, that year reports "no vote filed" instead.

Measured on the real inventories before changing it: every year inside both
windows (MORN FY2021-25, MSFT FY2020-25) pairs identically under both rules, so
no shipped fact moves. Outside the windows the unbounded rule did misfire for
real — MSFT's FY2008 and FY2009 proxies were both paired with 0001193125-10-265243,
the 8-K reporting the vote on the FY2010 proxy, presumably because 8-K item 5.07
only began in 2010 and earlier votes were reported in 10-Qs. Three fiscal years,
one vote. Bounded, FY2008 and FY2009 have no vote filing, which is true.

This module reads only the inventory dict it is handed. It deliberately does not
call `paths()`, so importing it resolves no company — which is what lets `fetch`,
`extract_facts` and a unit test with no company data all share it.
"""

from __future__ import annotations


def is_vote_filing(row: dict) -> bool:
    """An 8-K (or 8-K/A) that reports item 5.07, a shareholder vote."""
    return row["form"].startswith("8-K") and "5.07" in row.get("items", [])


def paired_vote_filing(filings: list[dict], fy: int) -> tuple[dict | None, dict | None]:
    """Return (proxy, vote) inventory rows for fiscal year `fy`.

    `proxy` is None when the year has no in-scope DEF 14A. `vote` is None when
    there is a proxy but no item-5.07 8-K between it and the next proxy — for the
    last year of a window, usually because the meeting has not happened yet as
    of the inventory's as-of date.

    Note what is NOT checked on the vote row: `in_window` and `disposition`.
    Ignoring `in_window` is the entire point; see the module docstring.
    """
    proxy = next((r for r in filings
                  if r["form"] == "DEF 14A" and r["fiscal_year"] == fy
                  and r["disposition"] == "in_scope"), None)
    if proxy is None:
        return None, None

    # ISO dates ("2025-12-08") compare correctly as strings, so `>` is a date test.
    # The next proxy, of any year, bounds the search: see the module docstring.
    later_proxies = sorted(r["filing_date"] for r in filings
                           if r["form"] == "DEF 14A" and r["filing_date"] > proxy["filing_date"])
    bound = later_proxies[0] if later_proxies else None

    candidates = sorted((r for r in filings
                         if is_vote_filing(r) and r["filing_date"] > proxy["filing_date"]
                         and (bound is None or r["filing_date"] < bound)),
                        key=lambda r: r["filing_date"])
    return proxy, (candidates[0] if candidates else None)


def vote_filings_for_window(inv: dict) -> tuple[list[dict], list[str]]:
    """Every vote 8-K the window's `votes` tasks will read, plus notes for the gaps.

    Returns (vote_rows, notes). `vote_rows` holds one row per distinct accession,
    in fiscal-year order, INCLUDING the ones outside the window; `fetch` adds
    whichever of them its own work list does not already contain. `notes` names
    every year that has a proxy but no vote filed after it, so a missing vote is
    reported as a missing filing rather than discovered later as `no source`.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    notes: list[str] = []
    for fy in range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1):
        proxy, vote = paired_vote_filing(inv["filings"], fy)
        if proxy is None:
            continue           # no proxy: discover's gap analysis already reports it
        if vote is None:
            # Two different situations, worth telling apart for whoever reads it.
            if fy == inv["last_fiscal_year"]:
                why = ("If the annual meeting has not happened yet, that is expected; "
                       "re-run `discover` after the vote is reported.")
            else:
                why = ("This is not the final year, so the meeting should have happened; "
                       "check EDGAR for the vote 8-K.")
            notes.append(f"FY{fy}: no item-5.07 8-K follows the proxy filed "
                         f"{proxy['filing_date']} in the inventory (as of "
                         f"{inv.get('as_of_utc', '?')}). {why} FY{fy} `votes` will "
                         f"report no source.")
            continue
        if vote["accession"] not in seen:
            seen.add(vote["accession"])
            rows.append(vote)
    return rows, notes
