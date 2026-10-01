"""Milestone 2 — Fetch and cache.

Downloads the in-scope filing documents identified by milestone 1 into
data/raw/, organized by fiscal year and form. Reads its work list from
data/discovery/inventory.json — never from config, and never by re-querying
EDGAR for metadata it already has.

THE CACHE RULE (CLAUDE.md): EDGAR gets hit once per document, ever. Downstream
stages are re-run constantly; this one should not be. A document already on disk
is never re-requested. Re-running this script with a warm cache makes zero
network requests and is safe at any time.

Run it:
    uv run python -m equity_research.fetch                 # fetch anything missing
    uv run python -m equity_research.fetch --dry-run       # list what WOULD be fetched
    uv run python -m equity_research.fetch --limit 5       # fetch 5 filings, for a first look

Writes:
    data/raw/FY<year>/<form>/<accession>/<filename>   the documents
    data/raw/_meta/attachments/<accession>.json       cached document manifests
    data/raw/fetch-log.jsonl                          append-only, one line per document
    data/raw/fetch-manifest.json                      final summary

Crash safety: every document is written to disk the moment it arrives and logged
to fetch-log.jsonl immediately, so an interrupted run loses nothing already done.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import os

from equity_research import vote_pairing
from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths
from equity_research.settings import IDENTITY_PLACEHOLDER_RE

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

# See src/equity_research/discover.py for why this is necessary on Windows: the
# console's cp1252 code page cannot encode many characters that appear in
# filing metadata, and printing one would otherwise kill the run.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ROOT comes from _bootstrap (imported above), which also injects the Windows
# cert store and loads .env — see that module for why both live in one place.
RAW_DIR = P.raw
ATTACH_CACHE = RAW_DIR / "_meta" / "attachments"
INVENTORY = P.inventory
LOG_PATH = RAW_DIR / "fetch-log.jsonl"

# The .env.example placeholder detector. One definition, in settings, shared with
# discover and `pipeline doctor` — this used to be a hand-copied duplicate.
PLACEHOLDER_RE = IDENTITY_PLACEHOLDER_RE

ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{filename}"

# ---------------------------------------------------------------------------
# Which documents inside a filing are worth keeping
# ---------------------------------------------------------------------------
# Verified empirically against real MORN filings before this list was written —
# index.json's `type` field turned out to be the ICON filename ("text.gif"), not
# the document type, so document types come from the submission SGML instead.

# Machine-generated XBRL plumbing and rendering assets. Never narrative.
NOISE_TYPE_PREFIXES = (
    "EX-101",   # XBRL taxonomy schema/linkbases
    "EX-96",    # mineral resource technical reports
    "GRAPHIC", "IMAGE",
    "JS", "CSS", "HTML",   # HTML here = R1.htm etc., the rendered-XBRL viewer
    "XML", "JSON", "ZIP", "EXCEL",
)

# Real exhibits, but pure compliance boilerplate with no narrative content.
# Skipped deliberately, and counted in the manifest so the choice is auditable.
BOILERPLATE_TYPE_PREFIXES = (
    "EX-21",    # list of subsidiaries
    "EX-23",    # auditor consent
    "EX-24",    # power of attorney
    "EX-31",    # SOX 302 certification
    "EX-32",    # SOX 906 certification
)


def keep_attachment(doc_type: str, filename: str) -> tuple[bool, str]:
    """Decide whether one document inside a filing gets downloaded.

    Errs toward keeping. Re-fetching is the thing this pipeline exists to avoid,
    so a borderline document is cheaper to store now than to re-request later.
    Notably EX-10 (material contracts) and EX-99 (press releases) are KEPT —
    for an 8-K reporting item 1.01 or 7.01, the substance is in the exhibit, and
    sometimes in the body instead. Both are needed.
    """
    t = (doc_type or "").upper().strip()
    if t.startswith(NOISE_TYPE_PREFIXES):
        return False, "xbrl/rendering asset"
    if t.startswith(BOILERPLATE_TYPE_PREFIXES):
        return False, "compliance boilerplate"
    if not filename:
        return False, "no filename"
    return True, "kept"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    # company.toml is company-scoped as of Phase 2; it is no longer in config/.
    with open(P.company_toml, "rb") as fh:
        return tomllib.load(fh)


def get_identity() -> str:
    ident = os.getenv("EDGAR_IDENTITY", "").strip()
    if not ident or "@" not in ident:
        sys.exit("FATAL: EDGAR_IDENTITY not set. See .env.example.")
    if PLACEHOLDER_RE.search(ident):
        sys.exit(f"FATAL: EDGAR_IDENTITY is still the .env.example placeholder "
                 f"({ident!r}). Put a real name and email in .env — the SEC uses it "
                 f"to contact you, and blocks requests carrying a fake one.")
    return ident


def slug(form: str) -> str:
    """'DEF 14A' -> 'DEF-14A'. Safe for a Windows directory name."""
    return form.replace(" ", "-").replace("/", "-")


# ---------------------------------------------------------------------------
# Attachment enumeration
# ---------------------------------------------------------------------------

def enumerate_attachments(row: dict, cik: str, company: str, identity: str,
                          delay: float, use_cache: bool) -> list[dict]:
    """List the documents inside one filing, with their real SGML types.

    Uses edgartools, which parses the submission SGML properly. The RESULT is
    cached as JSON so a re-run never calls edgartools or touches the network
    again — the enumeration is metadata, and metadata is exactly as expensive to
    re-fetch as anything else.
    """
    ATTACH_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = ATTACH_CACHE / f"{row['accession']}.json"

    if use_cache and cache_path.exists():
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)

    # Imported lazily so a fully cached run does not pay edgartools' import cost.
    from edgar import set_identity, Filing
    set_identity(identity)

    time.sleep(delay)
    filing = Filing(cik=int(cik), company=company, form=row["form"],
                    filing_date=row["filing_date"], accession_no=row["accession"])
    out = []
    for att in filing.attachments:
        out.append({
            "sequence": str(att.sequence_number) if att.sequence_number is not None else "",
            "type": str(att.document_type or ""),
            "filename": str(att.document or ""),
            "description": str(att.description or ""),
        })
    cache_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class Downloader:
    """Sequential, rate-limited, cache-first document downloader."""

    def __init__(self, identity: str, delay: float):
        self.headers = {"User-Agent": identity, "Accept-Encoding": "gzip, deflate"}
        self.delay = delay
        self.fetched = 0
        self.cached = 0
        self.failed: list[dict] = []
        self.bytes_new = 0

    def get(self, url: str, dest: Path) -> tuple[bool, int, str, str]:
        """Return (was_downloaded, size_bytes, sha256, status)."""
        if dest.exists() and dest.stat().st_size > 0:
            self.cached += 1
            data = dest.read_bytes()
            return False, len(data), hashlib.sha256(data).hexdigest(), "cached"

        time.sleep(self.delay)
        try:
            resp = httpx.get(url, headers=self.headers, timeout=120, follow_redirects=True)
        except Exception as exc:                     # network-level failure
            self.failed.append({"url": url, "error": repr(exc)})
            return False, 0, "", f"error: {exc!r}"

        if resp.status_code != 200:
            self.failed.append({"url": url, "error": f"HTTP {resp.status_code}"})
            return False, 0, "", f"HTTP {resp.status_code}"

        data = resp.content
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Written immediately, so an interrupted run keeps everything already done.
        dest.write_bytes(data)
        self.fetched += 1
        self.bytes_new += len(data)
        return True, len(data), hashlib.sha256(data).hexdigest(), "downloaded"


# ---------------------------------------------------------------------------
# The work list
# ---------------------------------------------------------------------------

def build_work_list(inv: dict, accessions: list[str] | None
                    ) -> tuple[list[dict], list[dict], list[str]]:
    """Which filings to fetch: (work, vote_added, vote_notes).

    `vote_added` is the part of `work` that sits outside the window, and
    `vote_notes` names any window year whose vote has not been filed yet. A
    function rather than inline in main() so the look-ahead is testable without
    a network (tests/unit/test_vote_pairing.py).

    The work list comes from the inventory, which is the single source of truth
    for what is in scope (CLAUDE.md: don't recompute what another stage owns).
    """
    vote_added: list[dict] = []
    vote_notes: list[str] = []
    if accessions:
        # EXPLICIT OVERRIDE: fetch exactly the accessions named, even outside the
        # window, and nothing else. It used to be the ONLY way to get the final
        # year's vote 8-K (see the look-ahead below, which now does that
        # automatically); it remains for any other one-off filing.
        #
        # Named accessions rather than a widened window on purpose. Extending the
        # window by a year would sweep in the 10-Qs, Form 4s and earnings 8-Ks of
        # an extra year and quietly change what every coverage claim means.
        want = set(accessions)
        work = [r for r in inv["filings"] if r["accession"] in want]
        missing = want - {r["accession"] for r in work}
        if missing:
            sys.exit(f"FATAL: accession(s) not in the inventory: {sorted(missing)}\n"
                     "Check the accession number, or re-run `uv run python -m equity_research.discover` if the "
                     "filing is newer than the inventory's as-of date.")
    else:
        work = [r for r in inv["filings"]
                if r["in_window"] and r["disposition"] in ("in_scope", "triage")]

        # THE VOTE LOOK-AHEAD (PHASE6_SCOPE.md, finding 4). The 8-K reporting the
        # vote on the LAST window year's proxy is filed after that year, so it is
        # labelled one year past the window and the line above never selects it.
        # Without this, every company run through `pipeline` silently lost its
        # final year's say-on-pay and director-election results.
        #
        # This asks the same rule `extract_facts.gather_votes` uses — one function
        # in vote_pairing.py — for the filings the window's `votes` tasks will
        # read, and adds whichever are not already listed. It adds exactly those
        # filings and nothing else, so the window itself is unchanged.
        have = {r["accession"] for r in work}
        vote_rows, vote_notes = vote_pairing.vote_filings_for_window(inv)
        vote_added = [r for r in vote_rows if r["accession"] not in have]
        work.extend(vote_added)
    work.sort(key=lambda r: (r["fiscal_year"], r["form"], r["filing_date"]))
    return work, vote_added, vote_notes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 2 — fetch and cache filing documents.")
    ap.add_argument("--dry-run", action="store_true", help="report what would be fetched, download nothing")
    ap.add_argument("--limit", type=int, default=None, help="process at most N filings (for a first look)")
    ap.add_argument("--accession", action="append", default=None, metavar="ACC",
                    help="fetch this accession even if it is outside the fiscal-year window "
                         "(repeatable). Deliberate, narrow override — see DATA.md.")
    add_ticker_arg(ap)

    args = ap.parse_args()

    if not INVENTORY.exists():
        sys.exit(f"FATAL: {INVENTORY} not found. Run `uv run python -m equity_research.discover` first (milestone 1).")

    settings = load_settings()
    edgar_cfg = settings["edgar"]
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))

    cik, company = inv["cik"], inv["company_name"]
    identity = get_identity()
    delay = edgar_cfg["request_delay_seconds"]
    use_cache = edgar_cfg["use_cache"]

    work, vote_added, vote_notes = build_work_list(inv, args.accession)
    if args.limit:
        work = work[:args.limit]

    print(f"Fetch — {inv['ticker']} ({company}), FY{inv['first_fiscal_year']}-FY{inv['last_fiscal_year']}")
    print(f"  inventory as of : {inv['as_of_utc']}")
    print(f"  filings to process: {len(work)}")
    # Rule 5: say where the number came from, so "in-window + N" is visible
    # rather than an unexplained count that differs from the inventory's.
    if vote_added:
        print(f"    of which outside the window: {len(vote_added)} vote 8-K(s) the window's "
              f"`votes` tasks read")
        for r in vote_added:
            print(f"      {r['accession']}  filed {r['filing_date']}, labelled "
                  f"FY{r['fiscal_year']}")
    for note in vote_notes:
        print(f"  NOTE: {note}")
    print(f"  rate limit      : {delay}s between requests ({1/delay:.1f}/sec)")
    print(f"  mode            : {'DRY RUN — nothing will be downloaded' if args.dry_run else 'fetching'}")
    print()

    dl = Downloader(identity, delay)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    skipped_counts: dict[str, int] = {}
    log_fh = None if args.dry_run else open(LOG_PATH, "a", encoding="utf-8")

    try:
        for n, row in enumerate(work, 1):
            fy, form, acc = row["fiscal_year"], row["form"], row["accession"]
            attachments = enumerate_attachments(row, cik, company, identity, delay, use_cache)

            wanted = []
            for att in attachments:
                keep, why = keep_attachment(att["type"], att["filename"])
                if keep:
                    wanted.append(att)
                else:
                    skipped_counts[why] = skipped_counts.get(why, 0) + 1

            dest_dir = RAW_DIR / f"FY{fy}" / slug(form) / acc
            print(f"[{n:3d}/{len(work)}] FY{fy} {form:8s} {row['filing_date']} {acc}  "
                  f"{len(wanted)} doc(s) of {len(attachments)}")

            for att in wanted:
                url = ARCHIVE_URL.format(cik=int(cik), nodash=acc.replace("-", ""),
                                         filename=att["filename"])
                dest = dest_dir / att["filename"]

                if args.dry_run:
                    print(f"          would fetch {att['type']:10s} {att['filename']}")
                    records.append({"accession": acc, "form": form, "fiscal_year": fy,
                                    "doc_type": att["type"], "filename": att["filename"],
                                    "url": url, "status": "dry-run"})
                    continue

                downloaded, size, digest, status = dl.get(url, dest)
                rec = {
                    "accession": acc, "form": form, "fiscal_year": fy,
                    "filing_date": row["filing_date"], "disposition": row["disposition"],
                    "items": row["items"],
                    "doc_type": att["type"], "description": att["description"],
                    "filename": att["filename"],
                    # P.relative, NOT relative_to(ROOT). See THE MANIFEST
                    # CONTRACT in paths.py: manifests store paths relative to
                    # the COMPANY folder ("data/raw/..."), and P.resolve() is
                    # what re-roots them. relative_to(ROOT) yields
                    # "companies/MORN/data/raw/..." — which P.resolve rejects,
                    # so every downstream stage dies on the first record.
                    "path": P.relative(dest),
                    "bytes": size, "sha256": digest, "url": url, "status": status,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                records.append(rec)
                # Flushed per document so a crash mid-run loses nothing.
                log_fh.write(json.dumps(rec) + "\n")
                log_fh.flush()

                flag = "" if status in ("downloaded", "cached") else f"  <- {status}"
                if status != "cached":
                    print(f"          {status:10s} {att['type']:10s} {size:>9,d}b  {att['filename']}{flag}")
    finally:
        if log_fh:
            log_fh.close()

    # --- summary -----------------------------------------------------------
    print()
    print("=" * 72)
    print(f"filings processed : {len(work)}")
    print(f"documents kept    : {len(records)}")
    print(f"  downloaded      : {dl.fetched}  ({dl.bytes_new/1_048_576:.1f} MB new)")
    print(f"  already cached  : {dl.cached}")
    print(f"documents skipped : {sum(skipped_counts.values())}")
    for why, c in sorted(skipped_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {why:24s} {c}")
    if dl.failed:
        print(f"FAILURES: {len(dl.failed)}")
        for f in dl.failed[:20]:
            print(f"  {f['error']}  {f['url']}")
    else:
        print("failures          : none")

    if args.dry_run:
        print("\nDRY RUN — nothing was written.")
        return

    # MERGE into any existing manifest rather than replacing it.
    #
    # This bit hard the first time a run covered only part of the work list: a
    # single `--accession` fetch rewrote a 201-record manifest as a 1-record file.
    # The cached documents were all still on disk — nothing was lost and no EDGAR
    # request was repeated — but the manifest is what every downstream stage reads
    # to find them, so section extraction saw one document and produced nothing.
    #
    # Keying on (accession, filename) rather than accession alone: one filing
    # contributes several documents, and a filing-level key would let the last
    # document silently evict its siblings.
    manifest_path = RAW_DIR / "fetch-manifest.json"
    merged: dict[tuple[str, str], dict] = {}
    if manifest_path.exists():
        for r in json.loads(manifest_path.read_text(encoding="utf-8")).get("records", []):
            merged[(r["accession"], r["filename"])] = r
    for r in records:                              # this run wins for what it covered
        merged[(r["accession"], r["filename"])] = r
    all_records = sorted(merged.values(),
                         key=lambda r: (r["fiscal_year"], r["form"], r["accession"], r["filename"]))

    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inventory_as_of": inv["as_of_utc"],
        "ticker": inv["ticker"], "cik": cik, "company_name": company,
        # Counts that describe THIS run are labelled as such; the totals describe
        # everything cached. Conflating the two produced nonsense on filtered runs.
        "last_run_filter": {"accession": args.accession, "limit": args.limit},
        "last_run_filings": len(work),
        # The filings in last_run_filings that sit outside the window, and why.
        "last_run_vote_lookahead": sorted(r["accession"] for r in vote_added),
        "last_run_documents": len(records),
        "documents": len(all_records),
        "downloaded_this_run": dl.fetched,
        "already_cached": dl.cached,
        "bytes_downloaded_this_run": dl.bytes_new,
        "skipped_by_reason": skipped_counts,
        "failures": dl.failed,
        "records": all_records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nwrote {manifest_path}  ({len(records)} record(s) this run, "
          f"{len(all_records)} total)")

    if dl.failed:
        sys.exit(f"\n{len(dl.failed)} document(s) failed. Re-run to retry only those "
                 "(everything already on disk is skipped).")


if __name__ == "__main__":
    main()
