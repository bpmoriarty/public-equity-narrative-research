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
    uv run python src/fetch.py                 # fetch anything missing
    uv run python src/fetch.py --dry-run       # list what WOULD be fetched
    uv run python src/fetch.py --limit 5       # fetch 5 filings, for a first look

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
import re
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import os

from equity_research._bootstrap import ROOT

# See src/equity_research/discover.py for why this is necessary on Windows: the
# console's cp1252 code page cannot encode many characters that appear in
# filing metadata, and printing one would otherwise kill the run.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ROOT comes from _bootstrap (imported above), which also injects the Windows
# cert store and loads .env — see that module for why both live in one place.
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "data" / "raw"
ATTACH_CACHE = RAW_DIR / "_meta" / "attachments"
INVENTORY = ROOT / "data" / "discovery" / "inventory.json"
LOG_PATH = RAW_DIR / "fetch-log.jsonl"

# See the note on the identical constant in src/discover.py.
PLACEHOLDER_RE = re.compile(r"(?i)\b(example\.(?:com|org|net)|your[._ ]?name|"
                            r"your[._ ]?email|name@host)\b")

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
    with open(CONFIG_DIR / "company.toml", "rb") as fh:
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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 2 — fetch and cache filing documents.")
    ap.add_argument("--dry-run", action="store_true", help="report what would be fetched, download nothing")
    ap.add_argument("--limit", type=int, default=None, help="process at most N filings (for a first look)")
    ap.add_argument("--accession", action="append", default=None, metavar="ACC",
                    help="fetch this accession even if it is outside the fiscal-year window "
                         "(repeatable). Deliberate, narrow override — see DATA.md.")
    args = ap.parse_args()

    if not INVENTORY.exists():
        sys.exit(f"FATAL: {INVENTORY} not found. Run src/discover.py first (milestone 1).")

    settings = load_settings()
    edgar_cfg = settings["edgar"]
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))

    cik, company = inv["cik"], inv["company_name"]
    identity = get_identity()
    delay = edgar_cfg["request_delay_seconds"]
    use_cache = edgar_cfg["use_cache"]

    # The work list comes from the inventory, which is the single source of truth
    # for what is in scope (CLAUDE.md: don't recompute what another stage owns).
    if args.accession:
        # EXPLICIT OVERRIDE for a filing that sits outside the window but reports on
        # a period inside it. The motivating case: an 8-K Item 5.07 reports the vote
        # taken at the annual meeting, which for the FY2025 proxy happened in May
        # 2026 — so the FY2025 say-on-pay result lives in a 2026-dated filing.
        #
        # Named accessions rather than a widened window on purpose. Extending the
        # window to 2026 would sweep in the 10-Qs, Form 4s and earnings 8-Ks of a
        # sixth year and quietly change what every coverage claim means. This adds
        # exactly the documents asked for, and the reason is recorded in DATA.md.
        want = set(args.accession)
        work = [r for r in inv["filings"] if r["accession"] in want]
        missing = want - {r["accession"] for r in work}
        if missing:
            sys.exit(f"FATAL: accession(s) not in the inventory: {sorted(missing)}\n"
                     "Check the accession number, or re-run src/discover.py if the "
                     "filing is newer than the inventory's as-of date.")
    else:
        work = [r for r in inv["filings"]
                if r["in_window"] and r["disposition"] in ("in_scope", "triage")]
    work.sort(key=lambda r: (r["fiscal_year"], r["form"], r["filing_date"]))
    if args.limit:
        work = work[:args.limit]

    print(f"Fetch — {inv['ticker']} ({company}), FY{inv['first_fiscal_year']}-FY{inv['last_fiscal_year']}")
    print(f"  inventory as of : {inv['as_of_utc']}")
    print(f"  filings to process: {len(work)}")
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
                    "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
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
