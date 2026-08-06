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


def build_year(fy: int, inv: dict, texts: dict, risk: dict) -> tuple[YearLedger, list[str]]:
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
                # `id` is deliberately not passed: LedgerFact derives it from the
                # fact's own content, so it cannot be forgotten here or anywhere
                # else a fact is built. See `fact_id` in ledger_schema.py.
                fields[ledger_field].append(LedgerFact(
                    field=ledger_field, fiscal_year=fy,
                    value={k: v for k, v in item.items() if k != "quote"},
                    source=src, confidence=conf, confidence_reason=reason,
                    quote=span, quote_verified=verified, quote_check=check,
                ))
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

    years = args.fy or list(range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1))
    years = sorted(years)

    print(f"Ledger — {inv['ticker']} ({inv['company_name']}), "
          f"FY{years[0]}-FY{years[-1]}")
    print()

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    built: list[YearLedger] = []
    all_warnings: list[str] = []

    for fy in years:
        if not any(load_task_records(fy, t) for t in {t for t, _, _ in FIELD_MAP}):
            print(f"FY{fy}  SKIPPED — no extraction results. "
                  f"Run: uv run python src/extract_facts.py --fy {fy}")
            continue
        ledger, warnings = build_year(fy, inv, texts, risk)
        all_warnings += warnings
        path = LEDGER_DIR / f"FY{fy}.json"
        path.write_text(json.dumps(ledger.model_dump(), indent=2), encoding="utf-8")
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
