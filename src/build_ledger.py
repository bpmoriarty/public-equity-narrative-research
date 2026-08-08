"""Milestone 4b — assemble the year ledger.

Everything downstream derives from this layer (SPEC.md section 3: "Do not
generate outputs directly from raw sections"). No network, no model calls: it
reads the cached extraction results, the deterministic risk diff and the filing
inventory, verifies every quote, and writes one validated record per year.

Run it:
    uv run python src/build_ledger.py
    uv run python src/build_ledger.py --fy 2023 --show incentive_metrics

Writes:
    data/ledger/FY<year>.json
    data/ledger/ledger-report.md

---------------------------------------------------------------------------
SOURCE ATTRIBUTION IS MEASURED, NOT ASSERTED
---------------------------------------------------------------------------
A task can read more than one section — `comp` sees both the CD&A and the
compensation tables. Rather than ask the model which one a fact came from and
believe the answer, each fact's source is resolved by testing its quote against
each section the task actually saw. The section containing the quote IS the
source.

That makes verification and attribution one operation, and it means a fact can
only be attributed to a document that demonstrably contains its evidence. A fact
whose quote appears in none of them gets no source and is marked low-confidence,
because there is nothing to cite.

---------------------------------------------------------------------------
WHAT CONFIDENCE MEANS HERE
---------------------------------------------------------------------------
`high`  the source section's boundaries are hand-verified AND the quote was
        found verbatim in it.
`low`   one or both failed, with the reason recorded on the fact.

Per DATA.md limitation 9, anything from `DEF14A_director_bios` or
`DEF14A_proposals_and_votes` is `low` by construction — their boundaries are
unverified. Any claim in the outputs resting on a `low` fact must say so or be
dropped; that rule is only enforceable because the marker is on the fact itself.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_schema import (ID_HEX, FactSource, LedgerFact, YearLedger,  # noqa: E402
                           confidence_for, risk_delta_id, verify_quote)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "data" / "ledger"
FACTS_DIR = LEDGER_DIR / "facts"
SECTIONS_MANIFEST = ROOT / "data" / "sections" / "sections-manifest.json"
INVENTORY = ROOT / "data" / "discovery" / "inventory.json"
RISK_DELTAS = LEDGER_DIR / "risk-deltas.json"
CORRECTIONS = ROOT / "config" / "corrections.toml"

# Which task field feeds which ledger field. Several tasks feed the same ledger
# field on purpose: a strategic priority stated in the 10-K and one stated in the
# shareholder letter are both real and are worth having separately — the
# difference between the two voices is itself a finding.
FIELD_MAP: list[tuple[str, str, str]] = [
    # (task, key in that task's facts, ledger field)
    ("business",  "strategic_priorities", "strategic_priorities"),
    ("letter",    "strategic_priorities", "strategic_priorities"),
    ("business",  "segments",             "segments"),
    ("mdna",      "segment_changes",      "segments"),
    ("business",  "headcount",            "headcount"),
    ("events_8k", "leadership",           "leadership"),
    ("board",     "members",              "board"),
    ("comp",      "incentive_metrics",    "incentive_metrics"),
    ("votes",     "results",              "vote_results"),
    ("mdna",      "events",               "events"),
    ("events_8k", "events",               "events"),
    ("mdna",      "notable_language",     "notable_language"),
    ("comp",      "notable_language",     "notable_language"),
    ("letter",    "notable_language",     "notable_language"),
    # Reg FD investor Q&A. Note both of its keys land in `investor_qa` and NOT in
    # `notable_language`, unlike every other notable_language source above. That is
    # the point of the separate field: a phrase from a monthly investor reply and a
    # phrase from the 10-K are not interchangeable evidence, and once they are in
    # the same list nothing downstream can tell them apart. See InvestorQaTopic.
    ("investor_qa", "topics",             "investor_qa"),
    ("investor_qa", "notable_language",   "investor_qa"),
]

# Tasks that produce one result file PER FILING rather than one per year, so the
# ledger has to collect all of them. See gather_investor_qa in extract_facts.py.
PER_FILING_TASKS = {"investor_qa"}

LEDGER_FIELDS = ["strategic_priorities", "segments", "headcount", "leadership",
                 "board", "incentive_metrics", "vote_results", "events",
                 "notable_language", "investor_qa"]


def load_json(p: Path, what: str) -> dict:
    if not p.exists():
        sys.exit(f"FATAL: {p} not found. {what}")
    return json.loads(p.read_text(encoding="utf-8"))


def section_texts(manifest_rows: list[dict]) -> dict[tuple[str, str], str]:
    """{(accession, section_key): text} for every successfully extracted section."""
    out = {}
    for r in manifest_rows:
        if r.get("ok") and r.get("out"):
            out[(r["accession"], r["key"])] = (ROOT / r["out"]).read_text(encoding="utf-8")
    return out


def load_task_records(fy: int, task: str) -> list[dict]:
    """Cached extraction results for one (year, task). A list, because some tasks
    produce one file per filing rather than one per year.

    Two explicit patterns rather than one `FY{fy}_{task}*.json` glob: a prefix
    glob would silently pick up a different task's files the moment one task name
    becomes a prefix of another, and it would do so without any error.
    """
    paths = sorted(FACTS_DIR.glob(f"FY{fy}_{task}.json"))
    if task in PER_FILING_TASKS:
        paths += sorted(FACTS_DIR.glob(f"FY{fy}_{task}_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def audit_ids() -> tuple[int, int, list[str]]:
    """Every id in the ledger must resolve to exactly one thing.

    Reads the files on disk rather than only the years just built, so a partial
    rebuild (`--fy 2023`) still checks its ids against every other year. A
    cross-year collision that only appeared on a full rebuild would be a nasty
    thing to discover later.

    Returns (fact ids, risk-delta ids, collisions).
    """
    seen: dict[str, str] = {}
    collisions: list[str] = []
    unidentified: list[str] = []
    n_facts = n_risk = 0

    def claim(fid: str | None, where: str) -> None:
        # A file written before ids existed, or by a different id scheme, has no
        # `id` here. Reported as its own failure rather than raised as a KeyError:
        # the fix is "rebuild those years", which a stack trace does not say.
        if not fid:
            unidentified.append(where)
            return
        if fid in seen:
            collisions.append(f"{fid}: {seen[fid]} and {where}")
        seen[fid] = where

    for p in sorted(LEDGER_DIR.glob("FY*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for f in LEDGER_FIELDS:
            for x in d.get(f) or []:
                n_facts += 1
                claim(x.get("id"),
                      f"{p.name} {f} {json.dumps(x['value'], ensure_ascii=False)[:60]}")
        for category, items in ((d.get("risk_deltas") or {}).get("deltas") or {}).items():
            for it in items:
                n_risk += 1
                # `heading` or `heading_now` depending on the delta category. The
                # first version of this line printed only `heading`, so the 46
                # reworded collisions it caught all reported as "None" — a
                # diagnostic that names nothing is barely better than no message.
                label = it.get("heading") or it.get("heading_now") or "(no heading)"
                claim(it.get("id"), f"{p.name} risk_deltas.{category} {label[:60]}")

    # Two distinct failures, reported distinctly. Folding them into one list would
    # make a missing id report as a "collision", which is the misleading-diagnostic
    # problem this function already tripped over once.
    problems = []
    if collisions:
        problems.append(
            f"{len(collisions)} id COLLISION(S) — two different things share one id, so a "
            f"citation to it is ambiguous:\n"
            + "\n".join(f"    {c}" for c in collisions[:10])
            + f"\n  Raise ID_HEX in src/ledger_schema.py (currently {ID_HEX}) and rebuild. "
              f"Every id changes, so any output already written must be re-checked.")
    if unidentified:
        problems.append(
            f"{len(unidentified)} record(s) on disk carry NO id — those years were written "
            f"before ids existed, or by a different id scheme:\n"
            + "\n".join(f"    {u}" for u in unidentified[:5])
            + "\n  Rebuild every year: uv run python src/build_ledger.py")
    return n_facts, n_risk, problems


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------
# See config/corrections.toml for what a correction is allowed to be. The rules
# enforced here:
#
#   - The model's output in data/ledger/facts/ is never touched. A correction is
#     applied to the value on its way into the ledger, and both the old and the new
#     value are recorded on the fact.
#   - A correction is matched by CONTENT, not by id, because correcting a value
#     changes the id (`fact_id` hashes the value). Matching by id would be
#     self-defeating: the correction's own target would stop existing the moment it
#     was applied, and a re-run would silently no-op.
#   - Every declared correction must match EXACTLY ONE fact. Zero means the target
#     moved and the ledger has quietly reverted; more than one means the match keys
#     are too loose to say which fact was meant. Both are fatal.

REQUIRED_CORRECTION_KEYS = ("id", "field", "fiscal_year", "accession", "match",
                            "set", "evidence", "reason")


def load_corrections() -> list[dict]:
    """Read config/corrections.toml. Absent is fine; malformed is not."""
    if not CORRECTIONS.exists():
        return []
    entries = tomllib.loads(CORRECTIONS.read_text(encoding="utf-8")).get("correction", [])
    problems = []
    for i, c in enumerate(entries):
        missing = [k for k in REQUIRED_CORRECTION_KEYS if not c.get(k)]
        if missing:
            problems.append(f"correction #{i + 1} ({c.get('id', 'unnamed')}) is missing: "
                            f"{', '.join(missing)}")
        # `evidence` is the whole justification for overriding a model extraction, so
        # an empty or token one is a malformed correction rather than a lax one.
        if len(str(c.get("evidence", ""))) < 20:
            problems.append(f"correction #{i + 1} ({c.get('id', 'unnamed')}): `evidence` "
                            f"must quote the filing text that establishes the correction")
        c["_hits"] = 0
    dupes = [k for k, n in Counter(c.get("id") for c in entries).items() if n > 1]
    if dupes:
        problems.append(f"duplicate correction id(s): {', '.join(map(str, dupes))}")
    if problems:
        sys.exit(f"FATAL: {CORRECTIONS.relative_to(ROOT)} is not usable\n\n  "
                 + "\n  ".join(problems))
    return entries


def apply_corrections(corrections: list[dict], ledger_field: str, fy: int,
                      value: dict, src: FactSource | None) -> tuple[dict, dict | None]:
    """Patch `value` if a correction targets this fact. Returns (value, record)."""
    for c in corrections:
        if c["field"] != ledger_field or c["fiscal_year"] != fy:
            continue
        if not src or src.accession != c["accession"]:
            continue
        if any(value.get(k) != v for k, v in c["match"].items()):
            continue
        c["_hits"] += 1
        was = {k: value.get(k) for k in c["set"]}
        return ({**value, **c["set"]},
                {"correction_id": c["id"], "was": was, "now": dict(c["set"]),
                 "evidence": c["evidence"], "reason": " ".join(c["reason"].split()),
                 "verified_by": c.get("verified_by")})
    return value, None


def audit_corrections(corrections: list[dict], years_built: list[int]) -> list[str]:
    """Every correction for a year that was rebuilt must have matched exactly once.

    Scoped to `years_built` so a partial rebuild (`--fy 2023`) does not report the
    other years' corrections as unmatched — they were never offered a chance to match.
    """
    problems = []
    for c in corrections:
        if c["fiscal_year"] not in years_built:
            continue
        if c["_hits"] == 1:
            continue
        if c["_hits"] == 0:
            problems.append(
                f"'{c['id']}' matched NOTHING. The fact it corrects has moved or "
                f"changed, so the ledger has silently reverted to the uncorrected "
                f"value. Target: {c['field']} FY{c['fiscal_year']} {c['accession']} "
                f"{json.dumps(c['match'], ensure_ascii=False)}")
        else:
            problems.append(
                f"'{c['id']}' matched {c['_hits']} facts. Its `match` keys do not "
                f"identify one fact, so which one was meant is undecidable. Add a "
                f"distinguishing key to `match`.")
    return problems


def attribute(item: dict, sources: list[dict],
              texts: dict) -> tuple[FactSource | None, bool, str, str]:
    """Resolve which source contains this fact's quote. See module docstring.

    Returns (source, verified, check_reason, verified_span). The span is what the
    ledger stores as the citation, so it is always text the filing demonstrably
    contains rather than whatever the model emitted.
    """
    quote = item.get("quote") or ""
    misses = []
    for s in sources:
        text = texts.get((s["accession"], s["key"]))
        if text is None:
            misses.append(f"{s['key']}: section text unavailable")
            continue
        ok, why, span = verify_quote(quote, text)
        if ok:
            return (FactSource(form=s["form"], fiscal_year=s.get("fiscal_year", 0),
                               accession=s["accession"], section_key=s["key"],
                               filing_date=s["filing_date"]),
                    True, why, span)
        misses.append(f"{s['key']}: {why}")
    # Unverified: keep the model's quote so it can be inspected, but the fact is
    # marked low-confidence and carries no source.
    return None, False, "; ".join(misses) or "no sources to check against", quote


def build_year(fy: int, inv: dict, texts: dict, risk: dict,
               corrections: list[dict]) -> tuple[YearLedger, list[str]]:
    warnings: list[str] = []
    fields: dict[str, list[LedgerFact]] = {f: [] for f in LEDGER_FIELDS}

    # --- facts from the extraction tasks -----------------------------------
    task_cache: dict[str, list[dict]] = {}
    for task, fact_key, ledger_field in FIELD_MAP:
        if task not in task_cache:
            task_cache[task] = load_task_records(fy, task)
        for rec in task_cache[task]:
            raw = rec["facts"].get(fact_key)
            if raw is None:
                continue
            # `headcount` is a single object, not a list; normalize so one code
            # path handles both rather than special-casing it downstream.
            items = raw if isinstance(raw, list) else [raw]
            sources = [{**s, "fiscal_year": fy} for s in rec["sources"]]
            for item in items:
                if not isinstance(item, dict):
                    continue
                src, verified, check, span = attribute(item, sources, texts)
                conf, reason = confidence_for(src.section_key if src else "", verified)
                # Applied AFTER attribution, because a correction is keyed on the
                # accession attribution resolves — and before the fact is built,
                # because the id is derived from the value. See load_corrections.
                value, corr = apply_corrections(
                    corrections, ledger_field, fy,
                    {k: v for k, v in item.items() if k != "quote"}, src)
                # `id` is deliberately not passed: LedgerFact derives it from the
                # fact's own content, so it cannot be forgotten here or anywhere
                # else a fact is built. See `fact_id` in ledger_schema.py.
                fields[ledger_field].append(LedgerFact(
                    field=ledger_field, fiscal_year=fy, value=value,
                    source=src, confidence=conf, confidence_reason=reason,
                    quote=span, quote_verified=verified, quote_check=check,
                    correction=corr,
                ))
                if corr:
                    warnings.append(
                        f"FY{fy} {ledger_field}: value corrected by "
                        f"'{corr['correction_id']}' ({corr['was']} -> {corr['now']})")
                if not verified:
                    warnings.append(f"FY{fy} {ledger_field}: unverified quote ({check[:70]})")

    # --- board metadata (size, committees) ---------------------------------
    board_recs = task_cache.get("board") or []
    board_meta = {}
    if board_recs:
        board_meta = {"board_size": board_recs[0]["facts"].get("board_size"),
                      "committees": board_recs[0]["facts"].get("committees", [])}

    # --- filings and earnings cadence, straight from the inventory ---------
    filings = [{"form": r["form"], "accession": r["accession"], "filed": r["filing_date"],
                "report_date": r["report_date"], "items": r.get("items", []),
                "disposition": r["disposition"]}
               for r in inv["filings"]
               if r["fiscal_year"] == fy and r["disposition"] in ("in_scope", "date_only")]
    filings.sort(key=lambda r: r["filed"])
    earnings = sorted(r["filed"] for r in filings if "2.02" in r["items"])

    # --- risk deltas, from the deterministic diff --------------------------
    # Deep-copied before ids are attached, so building the same year twice in one
    # process cannot mutate the shared loaded diff and make the second pass differ
    # from the first. Idempotence has to hold within a run, not just across runs.
    risk_year = copy.deepcopy(risk["years"].get(str(fy)))
    if risk_year:
        for category, items in (risk_year.get("deltas") or {}).items():
            for it in items:
                it["id"] = risk_delta_id(fy, category, it, risk_year.get("source") or {})

    # --- data-quality log --------------------------------------------------
    # DATA.md: log quality on the variables that actually enter the analysis.
    # A field empty because extraction failed must be distinguishable from a
    # field empty because the filings genuinely disclosed nothing.
    dq: dict[str, dict] = {}
    for f in LEDGER_FIELDS:
        facts = fields[f]
        confs = Counter(x.confidence for x in facts)
        dq[f] = {
            "n": len(facts),
            "populated": bool(facts),
            "high_confidence": confs.get("high", 0),
            "low_confidence": confs.get("low", 0),
            "unverified_quotes": sum(1 for x in facts if not x.quote_verified),
            "sources": sorted({x.source.section_key for x in facts if x.source}),
        }
    dq["risk_deltas"] = {
        "populated": bool(risk_year and risk_year.get("deltas")),
        "counts": (risk_year or {}).get("counts"),
        "unavailable_reason": (risk_year or {}).get("unavailable_reason"),
    }
    # SEGMENT COMPARABILITY.
    #
    # `segments` does not mean the same thing in every year, and comparing the
    # counts across the window would be a false finding. Where a filing reports
    # segments, Item 1 names them; where it does not, the same question yields
    # whatever product areas the filing happens to describe. For MORN the FY2021
    # and FY2022 filings never use the phrase "reportable segment" in either
    # section, and the FY2023 filings onward do — so the field holds product areas
    # for the first two years and reportable segments after that.
    #
    # Detected from the filing text rather than hardcoded, so it stays true for
    # the next company this pipeline is pointed at.
    seg_texts = " ".join(texts.get((r["accession"], k), "")
                         for r in filings
                         for k in ("10-K_item1_business", "10-K_item7_mdna"))
    reports_segments = "reportable segment" in seg_texts.lower()
    dq["segments_basis"] = {
        "filing_uses_reportable_segment_language": reports_segments,
        "basis": "reportable segments as named by the filing" if reports_segments
                 else "product or business areas described in Item 1 — this filing does "
                      "not disclose reportable segments, so these are NOT segments and "
                      "must not be compared with a year that does",
    }

    # REGISTER, not reliability. `investor_qa` facts are boundary-clean (whole
    # documents) and quote-verified like any other, so they are `high` confidence
    # and that is correct. What makes them different is the KIND of document: a
    # monthly Reg FD reply to whatever investors happened to ask, not a considered
    # annual disclosure. Recorded on the data so an output can weight it, rather
    # than left to whoever reads the field name to remember.
    qa_facts = fields["investor_qa"]
    dq["investor_qa_basis"] = {
        "n": len(qa_facts),
        "source_register": "Regulation FD voluntary disclosure (8-K item 7.01)",
        "basis": "management's written answers to questions submitted by investors, "
                 "published roughly monthly. Same verification as every other fact — "
                 "whole-document boundaries and a checked quote — but a different kind "
                 "of evidence from a 10-K or proxy statement: unaudited, unprompted by "
                 "any disclosure requirement, and responsive to whatever was asked. "
                 "Corroborating; not a substitute for a filed disclosure.",
        "filings": sorted({f.source.accession for f in qa_facts if f.source}),
    }

    # IDS ARE AN ANALYSIS VARIABLE NOW, so their quality is logged like any other.
    # Every citation in every output resolves through an id, which makes "are they
    # all present and distinct" a property the artifact should record rather than
    # something only the build's stdout ever knew.
    #
    # Scoped honestly to WITHIN THIS YEAR: this block is written before the
    # cross-year audit runs, so it cannot truthfully assert global uniqueness. The
    # global check is `audit_ids` in this module, and it is fatal — a collision
    # anywhere means no ledger gets to claim it was built.
    fact_ids = [x.id for f in LEDGER_FIELDS for x in fields[f]]
    risk_ids = [it["id"] for items in ((risk_year or {}).get("deltas") or {}).values()
                for it in items]
    dq["ids"] = {
        "n_facts": len(fact_ids),
        "n_risk_deltas": len(risk_ids),
        "all_present": all(fact_ids) and all(risk_ids),
        "unique_within_year": len(set(fact_ids + risk_ids)) == len(fact_ids) + len(risk_ids),
        "basis": "content hash of the claim, its evidence and its source — see `fact_id` "
                 "in src/ledger_schema.py. Confidence and the verification result are NOT "
                 "hashed, so re-verifying a fact does not renumber it. Cross-year "
                 "uniqueness is enforced fatally at build time by `audit_ids`.",
    }

    # THE DOCUMENT WINDOW IS NOT THE FISCAL WINDOW, and conflating them is how a
    # reader concludes evidence is missing when it is present.
    #
    # `inventory.json` declares window_start_date/window_end_date, which bound the
    # FISCAL years in scope (FY2021-FY2025 -> 2021-01-01..2025-12-31). The documents
    # reporting on those years are filed later — a 10-K in February, a proxy in
    # March, and the annual-meeting vote on the prior year's pay the following May.
    # So the documents behind this ledger run well past the declared window end, and
    # nothing in the artifacts said so: the verification suite read
    # window_end_date: 2025-12-31 and reasonably asked why FY2025 vote results were
    # not out of scope. See VERIFICATION.md D8.
    #
    # Measured here rather than stated in prose, because a date typed into DATA.md is
    # wrong the moment this pipeline is re-run or pointed at another company
    # (CLAUDE.md: never hard-code a value another stage already computes).
    fy_range = range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1)
    inv_fy = {f["accession"]: f.get("fiscal_year") for f in inv["filings"]}
    src_facts = [x for f in LEDGER_FIELDS for x in fields[f] if x.source]
    filed = sorted({x.source.filing_date for x in src_facts if x.source.filing_date})
    outside = sorted({x.source.accession for x in src_facts
                      if inv_fy.get(x.source.accession) not in fy_range})
    dq["document_window"] = {
        "first_filing_date": filed[0] if filed else None,
        "last_filing_date": filed[-1] if filed else None,
        "n_source_filings": len({x.source.accession for x in src_facts}),
        "sourced_from_outside_the_fiscal_window": outside,
        "basis": "filing dates of the documents this year's facts are actually drawn "
                 "from — NOT the fiscal window in inventory.json, which bounds the "
                 "fiscal years in scope. Documents reporting on a fiscal year are "
                 "filed after it ends, so this range extends past window_end_date by "
                 "construction. Any accession listed above additionally belongs to a "
                 "fiscal year outside the window and is used deliberately: an "
                 "annual-meeting vote held in May of year N decides on year N-1.",
    }

    # CORRECTIONS ARE A DATA-QUALITY PROPERTY, so they are logged like any other
    # rather than living only in a config file nobody downstream reads. A consumer
    # of the ledger can ask "was any of this overridden by a human, and on what
    # evidence" without leaving the artifact.
    corrected = [x for f in LEDGER_FIELDS for x in fields[f] if x.correction]
    dq["corrections"] = {
        "n": len(corrected),
        "applied": [{"id": x.id, "field": x.field, **x.correction} for x in corrected],
        "basis": "config/corrections.toml — human corrections to model-extracted "
                 "values that the cited filing contradicts, each carrying the filing "
                 "text that establishes it. data/ledger/facts/ is never edited: the "
                 "record of what the model returned has to stay as it was.",
    }

    missing_tasks = [t for t in {t for t, _, _ in FIELD_MAP} if not task_cache.get(t)]
    dq["extraction_tasks_missing"] = sorted(missing_tasks)
    for t in missing_tasks:
        warnings.append(f"FY{fy}: extraction task '{t}' has no result file — "
                        f"run src/extract_facts.py --fy {fy} --task {t}")

    ledger = YearLedger(
        fiscal_year=fy,
        ticker=inv["ticker"], cik=inv["cik"], company_name=inv["company_name"],
        filings=filings, earnings_release_dates=earnings,
        risk_deltas=risk_year,
        data_quality={**dq, "board_metadata": board_meta},
        **{f: fields[f] for f in LEDGER_FIELDS},
    )
    return ledger, warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 4b — assemble the year ledger.")
    ap.add_argument("--fy", type=int, action="append", help="only this fiscal year (repeatable)")
    ap.add_argument("--show", help="print this ledger field for the selected year(s)")
    args = ap.parse_args()

    inv = load_json(INVENTORY, "Run src/discover.py first (milestone 1).")
    manifest = load_json(SECTIONS_MANIFEST, "Run src/extract_sections.py first (milestone 3).")
    risk = load_json(RISK_DELTAS, "Run src/risk_diff.py first.")
    texts = section_texts(manifest["sections"])
    corrections = load_corrections()

    years = args.fy or list(range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1))
    years = sorted(years)

    print(f"Ledger — {inv['ticker']} ({inv['company_name']}), "
          f"FY{years[0]}-FY{years[-1]}")
    if corrections:
        print(f"  {len(corrections)} correction(s) declared in "
              f"{CORRECTIONS.relative_to(ROOT)}")
    print()

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    built: list[YearLedger] = []
    built_years: list[int] = []
    all_warnings: list[str] = []

    for fy in years:
        if not any(load_task_records(fy, t) for t in {t for t, _, _ in FIELD_MAP}):
            print(f"FY{fy}  SKIPPED — no extraction results. "
                  f"Run: uv run python src/extract_facts.py --fy {fy}")
            continue
        ledger, warnings = build_year(fy, inv, texts, risk, corrections)
        all_warnings += warnings
        built_years.append(fy)
        built.append(ledger)

        dq = ledger.data_quality
        tot = sum(dq[f]["n"] for f in LEDGER_FIELDS)
        low = sum(dq[f]["low_confidence"] for f in LEDGER_FIELDS)
        unv = sum(dq[f]["unverified_quotes"] for f in LEDGER_FIELDS)
        print(f"FY{fy}  {tot:>3d} facts  ({tot-low} high / {low} low confidence)  "
              f"{unv} unverified quote(s)  {len(ledger.filings)} filing(s)")
        for f in LEDGER_FIELDS:
            d = dq[f]
            flag = "" if d["populated"] else "   <- EMPTY"
            print(f"       {f:22s} {d['n']:>3d}  "
                  f"{'high=' + str(d['high_confidence']):>8s} {'low=' + str(d['low_confidence']):>7s}"
                  f"{flag}")

    if not built:
        sys.exit("\nnothing built.")

    # --- every declared correction must have landed, BEFORE anything is written --
    # Fatal, because a silently unapplied correction puts the defective value back
    # into the ledger with nothing on the artifact to say so. That is worse than a
    # crash: the build succeeds, the outputs regenerate, and the only evidence
    # anything is wrong is a config file nobody re-reads.
    #
    # Checked before the write rather than after, which is why the years above are
    # built into memory first. The first version of this check ran after writing and
    # was caught by its own test: the build failed loudly AND left five uncorrected
    # year files on disk, so the next stage would have consumed the defective ledger
    # from a run that had already announced it was broken. A loud failure that still
    # ships the bad artifact is not a loud failure.
    corr_problems = audit_corrections(corrections, built_years)
    if corr_problems:
        sys.exit(f"FATAL: {len(corr_problems)} correction(s) in "
                 f"{CORRECTIONS.relative_to(ROOT)} did not apply cleanly. "
                 f"NOTHING WAS WRITTEN — the ledger on disk is unchanged.\n\n  "
                 + "\n\n  ".join(corr_problems))

    for ledger in built:
        (LEDGER_DIR / f"FY{ledger.fiscal_year}.json").write_text(
            json.dumps(ledger.model_dump(), indent=2), encoding="utf-8")
    n_applied = sum(c["_hits"] for c in corrections)
    if n_applied:
        print(f"\ncorrections: {n_applied} applied, each matching exactly one fact")

    # --- every id must resolve to exactly one thing -------------------------
    n_facts, n_risk, problems = audit_ids()
    print()
    if problems:
        sys.exit(f"FATAL: the ledger's ids are not usable as citations "
                 f"({n_facts} facts, {n_risk} risk deltas checked)\n\n  "
                 + "\n\n  ".join(problems))
    print(f"ids: {n_facts + n_risk} unique ({n_facts} facts, {n_risk} risk deltas), "
          f"no collisions at {ID_HEX} hex chars")

    # A real id from this build for the report's example. Falls through every field
    # rather than only `events`, because a year with no events is perfectly possible
    # for another company and an empty example would read as a broken citation.
    example_id = next((x.id for l in built for f in LEDGER_FIELDS
                       for x in getattr(l, f)), "(none)")

    # --- report ------------------------------------------------------------
    lines = ["# Year ledger", "",
             f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}. "
             f"{inv['ticker']} ({inv['company_name']}), CIK {inv['cik']}.", "",
             "Every fact carries its source filing, an exact quote from that filing, and a "
             "confidence marker. `low` means the source section's boundaries are unverified, "
             "or the quote could not be found verbatim — see `confidence_reason` on the fact. "
             "**Any claim in the outputs resting on a `low` fact must say so, or be dropped.**",
             "",
             # A real id from this build, not a plausible-looking invented one. An
             # example citation that resolves to nothing has no business in the
             # document that explains how citations work.
             f"Every fact and risk delta also carries a stable `id` — e.g. `{example_id}` — "
             f"hashed from its claim, its evidence and its source, so an output can cite one "
             f"fact rather than a whole filing. Confidence and the verification result are "
             f"deliberately NOT in the hash: a judgment about a fact is not the fact, so "
             f"re-verifying it later must not renumber it. {n_facts + n_risk} ids this build, "
             f"checked unique.",
             "", "## Coverage", "",
             "| Field | " + " | ".join(f"FY{l.fiscal_year}" for l in built) + " |",
             "|---|" + "---|" * len(built)]
    for f in LEDGER_FIELDS:
        cells = []
        for l in built:
            d = l.data_quality[f]
            cells.append(f"{d['n']}" + (f" ({d['low_confidence']} low)" if d["low_confidence"] else ""))
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    rd = []
    for l in built:
        d = l.data_quality["risk_deltas"]
        c = d.get("counts")
        rd.append(f"+{c['added']}/-{c['removed']}/~{c['reworded']}" if c else "baseline")
    lines.append("| risk_deltas (added/removed/reworded) | " + " | ".join(rd) + " |")
    basis = ["reportable" if l.data_quality["segments_basis"]
             ["filing_uses_reportable_segment_language"] else "**product areas**"
             for l in built]
    lines.append("| segments basis | " + " | ".join(basis) + " |")
    if not all(l.data_quality["segments_basis"]
               ["filing_uses_reportable_segment_language"] for l in built):
        lines += ["", "> **Segment counts are not comparable across the whole window.** In the "
                  "years marked *product areas* the filing does not disclose reportable "
                  "segments, so the `segments` field holds whatever product or business areas "
                  "Item 1 describes. A change in the count between such a year and a "
                  "reportable-segment year is a change in disclosure, not necessarily a "
                  "re-segmentation."]
    # --- document window vs fiscal window -----------------------------------
    dws = [l.data_quality["document_window"] for l in built]
    firsts = [d["first_filing_date"] for d in dws if d["first_filing_date"]]
    lasts = [d["last_filing_date"] for d in dws if d["last_filing_date"]]
    outside_all = sorted({a for d in dws
                          for a in d["sourced_from_outside_the_fiscal_window"]})
    if firsts:
        lines += ["", "## Document window", "",
                  f"The **fiscal window** is FY{inv['first_fiscal_year']}–"
                  f"FY{inv['last_fiscal_year']} "
                  f"(`{inv['window_start_date']}` .. `{inv['window_end_date']}` in "
                  f"calendar time). That bounds the fiscal years in scope, not the "
                  f"documents.",
                  "",
                  f"The **document window** — the filing dates of the documents these "
                  f"facts are actually drawn from — is **`{min(firsts)}` .. "
                  f"`{max(lasts)}`**, across "
                  f"{len({a for l in built for f in LEDGER_FIELDS for x in getattr(l, f) if x.source for a in [x.source.accession]})} "
                  f"filings. It extends past the fiscal window end by construction: a "
                  f"10-K, a proxy and an annual-meeting vote all report on a year "
                  f"after that year has closed.",
                  ""]
        if outside_all:
            one = len(outside_all) == 1
            lines += [f"{len(outside_all)} of those filings also "
                      f"{'belongs' if one else 'belong'} to a fiscal year outside the "
                      f"window, and {'is' if one else 'are'} used deliberately — an "
                      f"annual-meeting vote held in May of year N decides on year "
                      f"N−1's compensation:", ""]
            lines += [f"- `{a}`" for a in outside_all]
        lines += ["", "> A reader told only that the window ends "
                  f"`{inv['window_end_date']}` would reasonably conclude that "
                  "evidence dated after it is out of scope. It is not. This section "
                  "exists so that claim is measured rather than assumed."]

    applied = [(l.fiscal_year, a) for l in built
               for a in l.data_quality["corrections"]["applied"]]
    if applied:
        lines += ["", "## Corrections applied", "",
                  "Values the cited filing contradicts, overridden from "
                  "`config/corrections.toml`. `data/ledger/facts/` — the record of what "
                  "the extraction model returned — is not edited; the correction is a "
                  "separate versioned artifact and both values are kept on the fact. "
                  "Every correction must match exactly one fact or the build fails.", ""]
        for fy, a in applied:
            lines += [f"- **FY{fy} {a['field']}** `{a['id']}` — `{a['correction_id']}`: "
                      f"{a['was']} → {a['now']}",
                      f"    - *Evidence:* “{a['evidence']}”",
                      f"    - *Reason:* {a['reason']}",
                      f"    - *Verified by:* {a['verified_by']}"]

    lines += ["", "## Source sections used", ""]
    for l in built:
        used = sorted({x.source.section_key for f in LEDGER_FIELDS
                       for x in getattr(l, f) if x.source})
        lines.append(f"- **FY{l.fiscal_year}**: {', '.join(used)}")
    if all_warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in dict.fromkeys(all_warnings)]
    (LEDGER_DIR / "ledger-report.md").write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"{len(built)} year(s) written to {LEDGER_DIR.relative_to(ROOT)}")
    if all_warnings:
        print(f"\n{len(set(all_warnings))} warning(s):")
        for w in dict.fromkeys(all_warnings):
            print(f"  {w}")
    else:
        print("no warnings: every quote verified against its source section")
    print(f"wrote {LEDGER_DIR / 'ledger-report.md'}")

    if args.show:
        for l in built:
            print("\n" + "=" * 72)
            print(f"FY{l.fiscal_year} — {args.show}")
            for x in getattr(l, args.show, []):
                s = x.source
                print(f"\n  {x.id}  [{x.confidence}] "
                      f"{json.dumps(x.value, ensure_ascii=False)[:200]}")
                print(f"    source: {s.form} {s.accession} / {s.section_key}" if s
                      else "    source: NONE (quote unverified)")
                print(f"    quote : {x.quote[:160]}")


if __name__ == "__main__":
    main()
