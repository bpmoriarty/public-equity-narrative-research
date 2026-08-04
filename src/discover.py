"""Milestone 1 — Discovery.

Answers one question: what is actually available on EDGAR for this company
inside the fiscal-year window? Produces an inventory with dates and accession
numbers, and flags gaps.

DOWNLOADS NO FILING DOCUMENTS. Only two kinds of metadata are fetched:
  - the SEC ticker->CIK map (one small file)
  - the company's submissions index (one file, plus older-filing shards)
Fetching the documents themselves is milestone 2.

Run it:
    uv run python src/discover.py              # uses cache if present
    uv run python src/discover.py --refresh    # re-fetch the index from EDGAR

Writes:
    data/raw/_meta/                     cached metadata, with the as-of date
    data/discovery/inventory.json       machine source of truth for later stages
    data/discovery/discovery-report.md  the human-readable inventory

Idempotent: running it twice produces the same output and, with the cache warm,
makes zero network requests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
import os

# Use the Windows certificate store. Without this, corporate SSL inspection
# makes httpx fail to verify sec.gov's certificate.
truststore.inject_into_ssl()

# Force UTF-8 on stdout/stderr.
#
# WHY: the Windows console defaults to the cp1252 code page, which has no
# mapping for most non-Latin-1 characters. SEC filings and these reports are
# full of them (arrows, en/em dashes, curly quotes, accented names). Printing
# one raises UnicodeEncodeError and KILLS THE SCRIPT — after all the work is
# done, purely because of how the terminal displays text. The output FILES are
# written with encoding="utf-8" explicitly and were never affected.
#
# errors="replace" means an unmappable character degrades to a placeholder
# instead of crashing. Never let cosmetics abort a run.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# Paths are all relative to the project root (this file's parent's parent), so
# the script works no matter which directory it is invoked from.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
META_DIR = ROOT / "data" / "raw" / "_meta"
OUT_DIR = ROOT / "data" / "discovery"

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
# Older filings spill out of the main submissions file into shards served here.
SHARD_URL = "https://data.sec.gov/submissions/{name}"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Read the three config files. Read-only: this script never writes them."""
    cfg = {}
    for name in ("company", "forms", "sections"):
        with open(CONFIG_DIR / f"{name}.toml", "rb") as fh:  # "rb" — tomllib needs binary
            cfg[name] = tomllib.load(fh)
    return cfg


def get_identity() -> str:
    """The User-Agent the SEC requires. Fail loudly if it is missing."""
    load_dotenv(ROOT / ".env")
    ident = os.getenv("EDGAR_IDENTITY", "").strip()
    if not ident or "@" not in ident:
        sys.exit(
            "FATAL: EDGAR_IDENTITY is not set, or has no email address in it.\n"
            "The SEC blocks requests without a descriptive User-Agent.\n"
            "Copy .env.example to .env and set EDGAR_IDENTITY=\"Name email@host\"."
        )
    return ident


# ---------------------------------------------------------------------------
# Fetching — cache-first, rate-limited, one request at a time
# ---------------------------------------------------------------------------

class SecClient:
    """Minimal SEC client. Caches every response to disk on first fetch.

    CLAUDE.md: stay under 10 requests/second, add a deliberate delay, do not
    parallelize. This class is deliberately sequential — there is no threading
    here and there should not be.
    """

    def __init__(self, identity: str, delay: float, use_cache: bool):
        self.headers = {"User-Agent": identity, "Accept-Encoding": "gzip, deflate"}
        self.delay = delay
        self.use_cache = use_cache
        self.requests_made = 0
        self.cache_hits = 0
        META_DIR.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str, cache_name: str) -> dict:
        cache_path = META_DIR / cache_name

        if self.use_cache and cache_path.exists():
            self.cache_hits += 1
            with open(cache_path, encoding="utf-8") as fh:
                return json.load(fh)

        # Deliberate pause before each live request, not after, so back-to-back
        # calls from anywhere in the program are always spaced out.
        time.sleep(self.delay)
        resp = httpx.get(url, headers=self.headers, timeout=60, follow_redirects=True)
        self.requests_made += 1
        if resp.status_code == 403:
            sys.exit(
                f"FATAL: SEC returned 403 Forbidden for {url}\n"
                "This almost always means the User-Agent was rejected. Check EDGAR_IDENTITY."
            )
        resp.raise_for_status()
        data = resp.json()

        cache_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data


# ---------------------------------------------------------------------------
# CIK resolution
# ---------------------------------------------------------------------------

def resolve_cik(client: SecClient, ticker: str, expected_cik: str, expected_name: str) -> tuple[str, str]:
    """Resolve ticker -> (10-digit CIK, company name) from the SEC's own map.

    CLAUDE.md forbids hardcoded CIKs. If config supplies one, it is treated as a
    tripwire: a mismatch is fatal, because a wrong CIK does not error — it
    silently returns another company's filings.
    """
    data = client.get_json(TICKER_MAP_URL, "company_tickers.json")
    hits = [row for row in data.values() if row["ticker"].upper() == ticker.upper()]

    if not hits:
        sys.exit(f"FATAL: ticker {ticker!r} is not in the SEC ticker map.")
    if len(hits) > 1:
        detail = "\n".join(f"  {str(h['cik_str']).zfill(10)}  {h['title']}" for h in hits)
        sys.exit(f"FATAL: ticker {ticker!r} matched {len(hits)} companies — ambiguous:\n{detail}")

    cik = str(hits[0]["cik_str"]).zfill(10)
    name = hits[0]["title"]

    if expected_cik and expected_cik.strip() != cik:
        sys.exit(
            f"FATAL: CIK mismatch for {ticker}.\n"
            f"  config/company.toml says : {expected_cik}\n"
            f"  SEC ticker map resolves  : {cik} ({name})\n"
            "Refusing to continue — one of these is the wrong company."
        )
    if expected_name and expected_name.strip().lower() != name.strip().lower():
        print(f"  WARNING: resolved_name in config is {expected_name!r}, SEC says {name!r}")

    return cik, name


# ---------------------------------------------------------------------------
# Submissions index
# ---------------------------------------------------------------------------

def fetch_all_filings(client: SecClient, cik: str, need_back_to: date) -> tuple[list[dict], dict]:
    """Return every filing row for this company back to `need_back_to`.

    The submissions API puts only the most recent ~1,000 filings in the main
    file. An active filer blows through 1,000 in a couple of years (Form 4s
    alone), so older filings live in separate shard files listed under
    filings.files. Fetching only the main file is a silent-truncation bug: the
    early years of the window would just appear to have no filings.
    """
    sub = client.get_json(SUBMISSIONS_URL.format(cik=cik), f"submissions_CIK{cik}.json")

    rows = _flatten(sub["filings"]["recent"])
    earliest = min((r["filing_date"] for r in rows), default=None)

    # Pull shards until coverage reaches back past the start of the window.
    for shard in sub["filings"].get("files", []):
        if earliest and earliest <= need_back_to:
            break
        shard_to = date.fromisoformat(shard["filingTo"])
        shard_from = date.fromisoformat(shard["filingFrom"])
        # Skip shards entirely newer or entirely older than what we still need.
        if shard_from > (earliest or date.max):
            continue
        data = client.get_json(SHARD_URL.format(name=shard["name"]), f"submissions_CIK{cik}_{shard['name']}")
        rows.extend(_flatten(data))
        earliest = min(r["filing_date"] for r in rows)
        if shard_to < need_back_to:
            break

    rows.sort(key=lambda r: (r["filing_date"], r["accession"]))
    return rows, sub


def _flatten(block: dict) -> list[dict]:
    """The submissions API returns parallel arrays, not a list of records.

    i.e. {"form": ["10-K","8-K"], "filingDate": ["2024-02-21","2024-03-01"], ...}
    where index i of every array describes the same filing. Zip them back into
    one dict per filing so the rest of the code can read them normally.
    """
    n = len(block.get("accessionNumber", []))
    out = []
    for i in range(n):
        report_raw = (block.get("reportDate") or [""] * n)[i]
        out.append({
            "accession": block["accessionNumber"][i],
            "form": (block["form"][i] or "").strip(),
            "filing_date": date.fromisoformat(block["filingDate"][i]),
            # reportDate = period of report. Present on periodic filings, blank
            # on many 8-Ks. This is what maps a filing to a FISCAL year.
            "report_date": date.fromisoformat(report_raw) if report_raw else None,
            "items": _parse_items(block.get("items", [""] * n)[i]),
            "primary_doc": (block.get("primaryDocument") or [""] * n)[i],
            "description": (block.get("primaryDocDescription") or [""] * n)[i],
        })
    return out


def _parse_items(raw: str) -> list[str]:
    """8-K item numbers come as a loose comma-separated string. Extract N.NN."""
    return sorted(set(re.findall(r"\b\d{1,2}\.\d{2}\b", raw or "")))


# ---------------------------------------------------------------------------
# Fiscal year logic
# ---------------------------------------------------------------------------

def parse_fye(raw: str) -> tuple[int, int]:
    """Submissions gives fiscalYearEnd as 'MMDD' (e.g. '1231'). Return (12, 31)."""
    raw = (raw or "").strip()
    if not re.fullmatch(r"\d{4}", raw):
        return (12, 31)  # overwhelmingly the most common; flagged in the report
    return int(raw[:2]), int(raw[2:])


def fy_end_date(fy: int, fye: tuple[int, int]) -> date:
    """Last day of fiscal year `fy`. Guards Feb 29 in non-leap years."""
    month, day = fye
    try:
        return date(fy, month, day)
    except ValueError:
        return date(fy, month, 28)


def fy_start_date(fy: int, fye: tuple[int, int]) -> date:
    """First day of fiscal year `fy` — the day after the prior year ended."""
    prev_end = fy_end_date(fy - 1, fye)
    return date.fromordinal(prev_end.toordinal() + 1)


def fy_from_period(d: date | None, fye: tuple[int, int], tol_days: int = 10) -> int | None:
    """If `d` is (near) a fiscal year END, return that fiscal year. Else None.

    This is the guard that keeps `reportDate` from being trusted blindly. The
    submissions API calls that field "period of report", but filers use it
    differently by form type:

      10-K     reportDate = 2021-12-31  -> a real fiscal year end. Trustworthy.
      DEF 14A  reportDate = 2021-05-14  -> the ANNUAL MEETING date. Not a period
                                           at all, and 5 months off the year end.
      ARS      reportDate = 2024-03-28  -> sometimes just the filing date again.

    Taking `reportDate.year` at face value therefore misdates proxies and some
    annual reports by a full year. Requiring the date to actually land near the
    company's fiscal year end separates the real periods from the impostors.
    """
    if d is None:
        return None
    # Check neighbouring years too: a 2022-01-02 period end belongs to FY2021.
    for candidate in (d.year, d.year - 1, d.year + 1):
        if abs((d - fy_end_date(candidate, fye)).days) <= tol_days:
            return candidate
    return None


def assign_fiscal_year(row: dict, fye: tuple[int, int]) -> tuple[int | None, str]:
    """Map a filing to the fiscal year it DESCRIBES. Returns (fy, basis).

    The subtlest step in discovery, and the one most worth checking by hand,
    because each form relates to a fiscal year differently:

    10-K    reportDate IS the fiscal year end. FY = reportDate.year.
    DEF 14A A proxy filed in spring of year N solicits votes for the meeting
            held in N, but the compensation it discloses and the say-on-pay
            vote it seeks cover the fiscal year that just ENDED — FY N-1.
            Getting this backwards misattributes every incentive metric by a
            year, which would corrupt the single most valuable comparison this
            pipeline makes (stated priorities vs. paid-for priorities).
    ARS     Same off-by-one: the annual report filed in year N reports on FY N-1.
    8-K     Event-driven, no period. FY = the fiscal year containing filingDate.
    """
    form = base_form(row["form"])
    rd, fd = row["report_date"], row["filing_date"]

    # A reportDate that really is a period end is the best evidence available,
    # whatever the form type.
    period_fy = fy_from_period(rd, fye)

    if form in ("10-K", "10-Q"):
        if period_fy is not None:
            return period_fy, "reportDate (verified period end)"
        if rd:
            # Kept, but flagged downstream — an off-cycle period end is exactly
            # what a fiscal-year change or a stub period looks like.
            return rd.year, "reportDate.year (period end is OFF-CYCLE — check)"
        return fy_containing(fd, fye), "filingDate (no reportDate)"

    if form in ("DEF 14A", "ARS"):
        if period_fy is not None:
            return period_fy, "reportDate (verified period end)"
        # reportDate was a meeting date or a copy of the filing date — useless.
        # Fall back to the disclosure convention.
        return fd.year - 1, "filingDate.year - 1 (covers prior FY)"

    return fy_containing(fd, fye), "fiscal year containing filingDate"


def fy_containing(d: date, fye: tuple[int, int]) -> int:
    """Which fiscal year does calendar date `d` fall in?"""
    # If d is on or before the FY end in its own calendar year, it belongs to
    # that fiscal year; otherwise it belongs to the next one.
    return d.year if d <= fy_end_date(d.year, fye) else d.year + 1


def base_form(form: str) -> str:
    """'10-K/A' -> '10-K'. Leaves distinct forms like '8-K12B' alone."""
    return form[:-2].strip() if form.endswith("/A") else form.strip()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(row: dict, forms_cfg: dict) -> tuple[str, str]:
    """Decide what happens to a filing. Returns (disposition, reason).

    Dispositions:
      in_scope      — fetch and extract in later milestones
      triage        — fetch, then judge on content (8-K 7.01/8.01)
      date_only     — never fetched; the date alone is timeline context
      gap_signal    — not processed, but its existence must be surfaced
      out_of_scope  — ignored
    """
    form = row["form"]
    bform = base_form(form)

    scoped = {f["form"]: f for f in forms_cfg["forms"]}
    ek = forms_cfg["eight_k"]

    if form in forms_cfg["gap_signals"]["flag_forms"] or bform in forms_cfg["gap_signals"]["flag_forms"]:
        return "gap_signal", f"{form} in gap_signals.flag_forms"

    if bform not in scoped:
        return "out_of_scope", f"{form} not an in-scope form"

    spec = scoped[bform]
    if form != bform and not spec.get("include_amendments", False):
        return "out_of_scope", f"{form} is an amendment and include_amendments is false"

    if not spec.get("requires_item_filter"):
        return "in_scope", f"{form} in scope"

    # 8-K: the item filter decides.
    items = row["items"]
    if not items:
        return "out_of_scope", "8-K with no items reported in the index"

    hits = [i for i in items if i in ek["include_items"]]
    if hits:
        return "in_scope", "items " + ", ".join(hits)

    # ORDER MATTERS: earnings releases must be checked BEFORE the conditional
    # items. A routine quarterly earnings 8-K is filed as "2.02, 7.01, 9.01" —
    # the 7.01 merely furnishes the press release as an exhibit. Checking 7.01
    # first routes every earnings release into the triage queue, which both
    # buries the real strategic announcements and empties the earnings-cadence
    # timeline that SPEC.md asks for.
    date_only = [i for i in items if i in ek["date_only_items"]]
    if date_only:
        return "date_only", "items " + ", ".join(date_only) + " (earnings; 7.01/8.01 is the exhibit)"

    cond = [i for i in items if i in ek["conditional_items"]]
    if cond:
        return "triage", "conditional items " + ", ".join(cond)

    return "out_of_scope", "items " + ", ".join(items) + " not in any filter list"


def cadence_profile(rows: list[dict]) -> list[dict]:
    """Group filings by item signature and measure the interval between them.

    A tight recurring interval is strong evidence that a signature represents a
    ROUTINE recurring release — monthly asset-flow reports, quarterly dividend
    declarations — rather than the discrete strategic events SPEC.md is after.

    This produces EVIDENCE FOR A HUMAN DECISION, not an automatic exclusion.
    Nothing is dropped on the strength of a cadence: a company can perfectly
    well announce an acquisition under the same item number it uses for routine
    releases. The exhibit's content still decides. The cadence only tells you
    where to look first, and which groups are worth sampling before committing
    to fetch all of them.
    """
    from statistics import median

    groups: dict[str, list[date]] = {}
    for r in rows:
        groups.setdefault(", ".join(r["items"]) or "(no items)", []).append(r["filing_date"])

    out = []
    for sig, dates in groups.items():
        dates.sort()
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        med = median(gaps) if gaps else None
        if med is None:
            label = "single filing"
        elif 21 <= med <= 40:
            label = "~monthly"
        elif 75 <= med <= 105:
            label = "~quarterly"
        elif 160 <= med <= 200:
            label = "~semi-annual"
        elif med < 21:
            label = "clustered"
        else:
            label = "irregular"
        out.append({
            "signature": sig, "count": len(dates), "median_gap_days": med,
            "cadence": label, "first": dates[0].isoformat(), "last": dates[-1].isoformat(),
        })
    out.sort(key=lambda x: -x["count"])
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 1 — discover available filings.")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the metadata cache and re-fetch the index from EDGAR")
    args = ap.parse_args()

    cfg = load_config()
    company, window, edgar = cfg["company"]["company"], cfg["company"]["window"], cfg["company"]["edgar"]
    forms_cfg = cfg["forms"]

    ticker = company["ticker"]
    if ticker == "REPLACE_ME":
        sys.exit("FATAL: set `ticker` in config/company.toml before running discovery.")

    first_fy, last_fy = window["first_fiscal_year"], window["last_fiscal_year"]
    fy_range = list(range(first_fy, last_fy + 1))

    identity = get_identity()
    client = SecClient(
        identity=identity,
        delay=edgar["request_delay_seconds"],
        use_cache=edgar["use_cache"] and not args.refresh,
    )

    print(f"Discovery — {ticker}, FY{first_fy}-FY{last_fy}")
    print(f"  identity: {identity}")
    print(f"  cache   : {'refresh (ignoring cache)' if args.refresh else 'enabled'}")
    print()

    # --- resolve CIK -------------------------------------------------------
    cik, name = resolve_cik(client, ticker, company.get("cik", ""), company.get("resolved_name", ""))
    print(f"  CIK {cik} -> {name}")

    # --- fiscal year end ---------------------------------------------------
    # Fetch the index first so the FYE is known before computing the window.
    probe = client.get_json(SUBMISSIONS_URL.format(cik=cik), f"submissions_CIK{cik}.json")
    fye = parse_fye(probe.get("fiscalYearEnd", ""))
    fye_str = f"{fye[0]:02d}-{fye[1]:02d}"
    print(f"  fiscal year end: {fye_str} (from submissions API)")

    expected_fye = (window.get("fiscal_year_end_month_day") or "").strip()
    if expected_fye and expected_fye != fye_str:
        print(f"  WARNING: config expected fiscal year end {expected_fye}, SEC reports {fye_str}")

    window_start = fy_start_date(first_fy, fye)
    window_end = fy_end_date(last_fy, fye)
    print(f"  window in calendar time: {window_start} .. {window_end}")

    # --- fetch every filing back to the window start -----------------------
    rows, sub = fetch_all_filings(client, cik, window_start)
    print(f"  submissions index: {len(rows)} total filings, "
          f"{rows[0]['filing_date']} .. {rows[-1]['filing_date']}")
    print(f"  requests made: {client.requests_made}, cache hits: {client.cache_hits}")
    print()

    if rows[0]["filing_date"] > window_start:
        print(f"  WARNING: index only reaches back to {rows[0]['filing_date']}, "
              f"but the window starts {window_start}. Early years may be incomplete.")

    # --- classify ----------------------------------------------------------
    catalogued = []
    for row in rows:
        fy, how = assign_fiscal_year(row, fye)
        disposition, reason = classify(row, forms_cfg)
        # A filing is in the window if the fiscal year it describes is in range.
        in_window = fy in fy_range if fy is not None else False
        catalogued.append({**row, "fiscal_year": fy, "fy_basis": how,
                           "disposition": disposition, "reason": reason,
                           "in_window": in_window})

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    inventory = {
        "as_of_utc": as_of,
        "ticker": ticker,
        "cik": cik,
        "company_name": name,
        "fiscal_year_end_month_day": fye_str,
        "first_fiscal_year": first_fy,
        "last_fiscal_year": last_fy,
        "window_start_date": window_start.isoformat(),
        "window_end_date": window_end.isoformat(),
        "index_earliest_filing": rows[0]["filing_date"].isoformat(),
        "index_total_filings": len(rows),
        "sec_requests_made": client.requests_made,
        # Carried so the report can derive fetch-time estimates from the real
        # configured value instead of restating a literal (CLAUDE.md: never
        # hard-code a value another stage already computes).
        "request_delay_seconds": edgar["request_delay_seconds"],
        "filings": [_serialize(r) for r in catalogued],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    report = build_report(inventory, catalogued, fy_range, fye)
    (OUT_DIR / "discovery-report.md").write_text(report, encoding="utf-8")

    print(report)
    print()
    print(f"wrote {OUT_DIR / 'inventory.json'}")
    print(f"wrote {OUT_DIR / 'discovery-report.md'}")


def _serialize(row: dict) -> dict:
    out = dict(row)
    out["filing_date"] = row["filing_date"].isoformat()
    out["report_date"] = row["report_date"].isoformat() if row["report_date"] else None
    return out


def build_report(inv: dict, rows: list[dict], fy_range: list[int], fye) -> str:
    """Human-readable inventory — this is the milestone 1 deliverable to review."""
    L: list[str] = []
    add = L.append

    add(f"# Discovery report — {inv['ticker']} ({inv['company_name']})")
    add("")
    add(f"- CIK: `{inv['cik']}` (resolved from the SEC ticker map, not hardcoded)")
    add(f"- Fiscal year end: **{inv['fiscal_year_end_month_day']}**")
    add(f"- Window: **FY{inv['first_fiscal_year']}–FY{inv['last_fiscal_year']}** "
        f"= {inv['window_start_date']} .. {inv['window_end_date']}")
    add(f"- Submissions index as of: {inv['as_of_utc']}")
    add(f"- Total filings in index: {inv['index_total_filings']} "
        f"(reaching back to {inv['index_earliest_filing']})")
    add("")
    add("No filing documents were downloaded. This is metadata only.")
    add("")

    inw = [r for r in rows if r["in_window"]]

    # --- coverage matrix ---------------------------------------------------
    add("## Coverage by fiscal year")
    add("")
    add("| Fiscal year | 10-K | DEF 14A | ARS / letter | Material 8-K | Needs triage | Earnings 8-K |")
    add("|---|---|---|---|---|---|---|")
    for fy in fy_range:
        yr = [r for r in inw if r["fiscal_year"] == fy]
        def count(bf, disp=("in_scope",)):
            return sum(1 for r in yr if base_form(r["form"]) == bf and r["disposition"] in disp)
        tenk = count("10-K")
        proxy = count("DEF 14A")
        ars = count("ARS")
        eightk = sum(1 for r in yr if base_form(r["form"]) == "8-K" and r["disposition"] == "in_scope")
        triage = sum(1 for r in yr if r["disposition"] == "triage")
        # By item presence, matching the earnings-cadence section below. Counting
        # by disposition would undercount any quarter whose earnings 8-K also
        # carried a material item, and the two tables would disagree.
        earn = sum(1 for r in yr if "2.02" in r["items"])
        mark = lambda n: str(n) if n else "**MISSING**"
        add(f"| FY{fy} | {mark(tenk)} | {mark(proxy)} | {ars or '—'} | {eightk} | {triage} | {earn} |")
    add("")

    # --- annual filings detail --------------------------------------------
    for bf, title in (("10-K", "10-K filings"), ("DEF 14A", "DEF 14A filings"), ("ARS", "Shareholder / annual reports")):
        sel = [r for r in inw if base_form(r["form"]) == bf and r["disposition"] in ("in_scope",)]
        add(f"## {title}")
        add("")
        if not sel:
            add(f"None found in the window. See the gap analysis below.")
            add("")
            continue
        add("| FY | Form | Filed | Period | Accession | FY assigned from |")
        add("|---|---|---|---|---|---|")
        for r in sorted(sel, key=lambda x: x["filing_date"]):
            add(f"| FY{r['fiscal_year']} | {r['form']} | {r['filing_date']} | "
                f"{r['report_date'] or '—'} | `{r['accession']}` | {r['fy_basis']} |")
        add("")

    # --- material 8-Ks ----------------------------------------------------
    eightks = [r for r in inw if base_form(r["form"]) == "8-K" and r["disposition"] == "in_scope"]
    add(f"## Material 8-K filings ({len(eightks)})")
    add("")
    add("Filtered per `config/forms.toml` `[eight_k].include_items`.")
    add("")
    if eightks:
        add("| FY | Filed | Items | Accession |")
        add("|---|---|---|---|")
        for r in sorted(eightks, key=lambda x: x["filing_date"]):
            add(f"| FY{r['fiscal_year']} | {r['filing_date']} | {', '.join(r['items'])} | `{r['accession']}` |")
        add("")
        # Item frequency, so the shape of the event history is visible at a glance.
        freq: dict[str, int] = {}
        for r in eightks:
            for i in r["items"]:
                freq[i] = freq.get(i, 0) + 1
        add("Item frequency across the window:")
        add("")
        for i, c in sorted(freq.items()):
            add(f"- `{i}` — {c}")
        add("")

    # --- triage queue -----------------------------------------------------
    triage = [r for r in inw if r["disposition"] == "triage"]
    add(f"## 8-Ks needing content triage ({len(triage)})")
    add("")
    add("Items 7.01 / 8.01 carry both major strategic announcements and wholly "
        "routine press releases. The item number cannot decide; the exhibit's "
        "content must.")
    add("")
    if triage:
        add("**Cadence profile.** Grouped by item signature, with the median gap "
            "between consecutive filings. A tight recurring interval is evidence "
            "of a routine recurring release, not a discrete event — but it is "
            "only evidence. Nothing here has been excluded automatically.")
        add("")
        add("| Items | Count | Median gap | Reads as | First | Last |")
        add("|---|---|---|---|---|---|")
        for g in cadence_profile(triage):
            gap = f"{g['median_gap_days']:.0f}d" if g["median_gap_days"] is not None else "—"
            add(f"| {g['signature']} | {g['count']} | {gap} | {g['cadence']} | {g['first']} | {g['last']} |")
        add("")
        add(f"Full row-level detail for all {len(triage)} is in `data/discovery/inventory.json` "
            "(`disposition == \"triage\"`); it is omitted here to keep this report readable.")
        add("")

    # --- earnings cadence -------------------------------------------------
    # Derived from the PRESENCE of item 2.02, not from disposition. An 8-K that
    # reports earnings AND a leadership change ("2.02, 5.02, 7.01") is correctly
    # classified in_scope, but it is still an earnings release and still part of
    # the cadence. Reading the cadence off `disposition == "date_only"` would
    # silently drop those quarters and invent gaps that do not exist.
    earn = [r for r in inw if "2.02" in r["items"]]
    add(f"## Earnings release cadence ({len(earn)} filings)")
    add("")
    add("Item 2.02 filings are not fetched for content — the releases are financial, "
        "not narrative. The cadence itself is timeline context: a gap or a delay is "
        "a signal. Dates marked `+` also report a material item and ARE fetched.")
    add("")
    for fy in fy_range:
        yr = sorted((r for r in earn if r["fiscal_year"] == fy), key=lambda r: r["filing_date"])
        if not yr:
            add(f"- FY{fy}: **none found**")
            continue
        marks = [f"{r['filing_date']}{'+' if r['disposition'] == 'in_scope' else ''}" for r in yr]
        flag = "" if len(yr) == 4 else f"  <- **{len(yr)}, not 4**"
        add(f"- FY{fy}: {', '.join(marks)}{flag}")
    add("")

    # --- gap signals ------------------------------------------------------
    signals = [r for r in rows if r["disposition"] == "gap_signal"
               and inv["window_start_date"] <= r["filing_date"].isoformat() <= inv["window_end_date"]]
    add(f"## Gap-analysis signals ({len(signals)})")
    add("")
    add("Not processed for content, but their presence reframes the narrative — "
        "an S-4 means M&A, an NT 10-K means a missed deadline, a SC 13D means an activist.")
    add("")
    if signals:
        add("| Filed | Form | Accession |")
        add("|---|---|---|")
        for r in sorted(signals, key=lambda x: x["filing_date"]):
            add(f"| {r['filing_date']} | {r['form']} | `{r['accession']}` |")
    else:
        add("None found in the window. Specifically: no S-1, S-3, S-4, NT 10-K, "
            "or SC 13D. No registration statement suggesting major M&A, no missed "
            "filing deadline, and no activist 13D stake across the five years.")
    add("")

    # --- everything else in the index -------------------------------------
    # Stated explicitly so "out of scope" is a visible, auditable decision
    # rather than a silent omission the reader has to take on trust.
    from collections import Counter
    add("## Other forms in the window, not processed")
    add("")
    add("Listed so every exclusion is visible. None of these are in SPEC.md's scope.")
    add("")
    add("| Form | Count | What it is |")
    add("|---|---|---|")
    known = {
        "4": "insider transaction report",
        "4/A": "insider transaction report, amended",
        "3": "initial insider holdings",
        "5": "annual insider holdings",
        "144": "notice of proposed sale by an affiliate",
        "10-Q": "quarterly report — out of scope, this is an annual-narrative project",
        "SC 13G": "passive institutional stake (index funds); 13D would be the activist form",
        "SC 13G/A": "passive institutional stake, amended",
        "SCHEDULE 13G/A": "passive institutional stake, amended",
        "DEFA14A": "additional proxy soliciting material",
        "CORRESP": "correspondence with SEC staff",
        "UPLOAD": "SEC staff comment letter to the company",
        "S-8": "employee benefit plan share registration",
    }
    for form, n in Counter(r["form"] for r in inw if r["disposition"] == "out_of_scope").most_common():
        add(f"| `{form}` | {n} | {known.get(form, '—')} |")
    add("")
    add("Two of these are worth a decision rather than a shrug:")
    add("")
    add("- **`DEFA14A`** — additional proxy soliciting material. Sometimes carries "
        "supplemental compensation disclosure or vote-related communication that "
        "does not appear in the DEF 14A itself. Currently out of scope.")
    add("- **`UPLOAD` / `CORRESP`** — SEC staff comment letters and the company's "
        "replies. Directly relevant to a governance narrative (the SEC questioning "
        "a disclosure is a real signal) but not in SPEC.md's scope. Currently out of scope.")
    add("")

    # --- warnings ---------------------------------------------------------
    add("## Gaps and warnings")
    add("")
    warnings: list[str] = []

    for fy in fy_range:
        yr = [r for r in inw if r["fiscal_year"] == fy]
        if not any(base_form(r["form"]) == "10-K" and r["disposition"] == "in_scope" for r in yr):
            warnings.append(f"FY{fy}: no 10-K found.")
        if not any(base_form(r["form"]) == "DEF 14A" and r["disposition"] == "in_scope" for r in yr):
            warnings.append(f"FY{fy}: no DEF 14A found.")

    # Per-year, not just "are there any at all". An all-or-nothing check passes
    # silently when four of five years have an ARS, which is exactly the case
    # that needs flagging: a missing letter in one year can look like a change in
    # leadership voice when it is really a missing document.
    ars_years = {r["fiscal_year"] for r in inw if base_form(r["form"]) == "ARS"}
    missing_ars = [fy for fy in fy_range if fy not in ars_years]
    if missing_ars:
        warnings.append(
            f"No ARS for {', '.join('FY' + str(y) for y in missing_ars)}. The shareholder "
            "letter for those years is likely an EX-13 exhibit to the 10-K, or was never "
            "filed to EDGAR — see the `fallback` key in `config/forms.toml`. Milestone 2 "
            "must check the 10-K exhibit list before the gap is reported as real. "
            "SPEC.md marks this form optional, so this is a coverage note, not a failure."
        )

    # An off-rhythm number of earnings releases is worth a look: an extra 2.02
    # outside the quarterly cadence often marks a restatement, a guidance
    # revision, or a supplemental disclosure.
    for fy in fy_range:
        n = sum(1 for r in inw if "2.02" in r["items"] and r["fiscal_year"] == fy)
        if n and n != 4:
            warnings.append(
                f"FY{fy} has {n} earnings 8-Ks, not the usual 4. Worth checking why — "
                "an extra one can mark a restatement or a guidance revision."
            )

    amendments = [r for r in inw if r["form"].endswith("/A") and r["disposition"] == "in_scope"]
    for r in amendments:
        warnings.append(f"Amendment in window: {r['form']} filed {r['filing_date']} (`{r['accession']}`). "
                        "Carry both readings — do not silently prefer one.")

    # Fiscal-year-end drift: a 10-K whose period does not land on the expected
    # month/day means the company moved its year end, producing a stub period.
    for r in inw:
        if base_form(r["form"]) == "10-K" and r["report_date"]:
            rd = r["report_date"]
            if abs((rd - fy_end_date(rd.year, fye)).days) > 7:
                warnings.append(
                    f"FY{r['fiscal_year']} 10-K period ends {rd}, more than a week from the "
                    f"expected year end {fy_end_date(rd.year, fye)} — possible fiscal-year change or stub period."
                )

    if rows[0]["filing_date"].isoformat() > inv["window_start_date"]:
        warnings.append(
            f"Submissions index reaches back only to {rows[0]['filing_date']}, but the window "
            f"starts {inv['window_start_date']}. Early-year coverage may be incomplete."
        )

    if warnings:
        for w in warnings:
            add(f"- {w}")
    else:
        add("None. Every fiscal year has a 10-K and a DEF 14A, and no anomalies were detected.")
    add("")

    # --- what milestone 2 would fetch -------------------------------------
    to_fetch = [r for r in inw if r["disposition"] in ("in_scope", "triage")]
    add("## What milestone 2 would fetch")
    add("")
    delay = inv["request_delay_seconds"]
    add(f"**{len(to_fetch)} documents.** At the configured {delay}s delay between "
        f"requests ({1 / delay:.1f}/sec, inside the SEC's 10/sec limit), that is at "
        f"least {len(to_fetch) * delay:.0f}s of deliberate waiting, plus download time.")
    add("")
    by_form: dict[str, int] = {}
    for r in to_fetch:
        by_form[base_form(r["form"])] = by_form.get(base_form(r["form"]), 0) + 1
    for f, c in sorted(by_form.items()):
        add(f"- {f}: {c}")
    add("")

    return "\n".join(L)


if __name__ == "__main__":
    main()
