"""Triage the conditional 7.01/8.01 8-K filings. Deterministic, no model calls.

config/forms.toml puts items 7.01 and 8.01 in `conditional_items`: the item
number alone does not say whether the content is strategic, so these filings are
fetched and then judged on content. This is that judgment, and the thing it
mainly produces is a RECORD — forms.toml asks for it in as many words: "Log every
triage decision; a silent drop here loses real events."

Run it:
    uv run python src/triage_8k.py
    uv run python src/triage_8k.py --show read        # only the keep decisions
    uv run python src/triage_8k.py --show date_only   # audit the drops by eye

Writes:
    data/triage/triage-8k.json     one record per filing, with the evidence
    data/triage/triage-report.md   the human-auditable log

---------------------------------------------------------------------------
THE ASYMMETRY THIS STAGE IS BUILT AROUND
---------------------------------------------------------------------------
The two possible errors do not cost the same amount.

A false `read` sends a dividend announcement to a model. Cost: a fraction of a
cent, and a fact nobody uses.

A false `date_only` deletes a corporate event from a five-year history, and
NOTHING DOWNSTREAM CAN DETECT IT. The ledger will look complete. The timeline
will read as continuous. There is no later stage that notices the absence.

So this classifier is not trying to be accurate, it is trying to be accurate in
one direction. `date_only` requires positive evidence of a routine filing AND the
absence of every material signal. Anything unrecognised is read. The report prints
the drop list in full so it can be checked by eye, which for 15 documents is
about a minute of work and is the actual safety net.

---------------------------------------------------------------------------
WHY MATCH POSITION IS RECORDED, NOT JUST MATCH PRESENCE
---------------------------------------------------------------------------
Keyword matching over-fires badly on this corpus. Most of these filings are
Morningstar's Reg FD investor Q&A, where management discusses past acquisitions
at length — so a phrase like "acquisition of" appears in dozens of documents that
announce nothing at all. Measured on the real 75: a naive keyword scan flagged 42
filings as deal-related, against roughly 6 that actually announce a transaction.

A press release states its subject in the headline; a Q&A mentions things in
passing. So every match records its character offset, and a match inside the
headline window scores `strong` while a later one scores `mention`. Only strong
matches drive the material routing. Mentions are still written to the record,
because an observation that was made and then suppressed is not a clean one.

---------------------------------------------------------------------------
THE CONTENT MOVED MID-WINDOW
---------------------------------------------------------------------------
Where the Q&A text physically lives changes inside the five-year window:
FY2021-FY2023 it is inline in the 8-K body, and FY2024-FY2025 it is a
Workiva-generated EX-99.1 with the body reduced to a stub that just points at the
exhibit. FY2024 contains both shapes.

This is why triage routes DOCUMENTS and not filings. A filing-level decision
combined with the "bodies only, never exhibits" rule in src/extract_facts.py
would read the early years and silently read nothing at all for the late ones,
while reporting the same number of filings processed in both.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from equity_research._bootstrap import ROOT

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SECTIONS_MANIFEST = ROOT / "data" / "sections" / "sections-manifest.json"
INVENTORY = ROOT / "data" / "discovery" / "inventory.json"
TRIAGE_DIR = ROOT / "data" / "triage"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(ROOT / "config" / "forms.toml", "rb") as fh:
        forms = tomllib.load(fh)
    tri = forms["eight_k"]["triage"]
    # Compile once. A bad pattern in config should fail here, loudly, naming the
    # signal and the pattern — not silently match nothing for the whole run.
    compiled: dict[str, list[re.Pattern]] = {}
    for signal, pats in tri["patterns"].items():
        compiled[signal] = []
        for p in pats:
            try:
                compiled[signal].append(re.compile(p, re.I))
            except re.error as exc:
                sys.exit(f"FATAL: bad regex for signal '{signal}' in "
                         f"config/forms.toml: {p!r} — {exc}")
    bp = {k: re.compile(v) for k, v in tri["boilerplate"].items()}
    return {"tri": tri, "patterns": compiled, "bp": bp,
            "conditional_items": set(forms["eight_k"]["conditional_items"])}


def load_json(p: Path, what: str) -> dict:
    if not p.exists():
        sys.exit(f"FATAL: {p} not found. {what}")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Boilerplate
# ---------------------------------------------------------------------------

# Marker left where an interior span was removed. Its job is to make a quote that
# straddles the cut FAIL verification rather than pass it.
#
# Removing a block from the middle of a document puts two previously separate
# passages next to each other. A model reading the result can quote across that
# seam in good faith, producing a span that reads as contiguous and does not exist
# in the filing — precisely the stitched quote the grounding check is built to
# catch, manufactured by our own preprocessing. With the marker in between, such a
# quote either includes the marker text (and fails to verify) or stops at it.
ELISION = " [... standard forward-looking-statements caution omitted ...] "


def strip_boilerplate(text: str, is_body: bool, bp: dict) -> str:
    """Remove the parts that are identical across filings.

    Measured on the real 75: this removes about 40% of the raw volume. Every
    removed span is verbatim-repeated across documents, so nothing distinguishing
    is lost — but the cover page alone is ~2,270 characters, and paying to send it
    75 times while it pushes the actual content down the prompt is pure cost.

    Only the ends are truncated silently; the one interior removal is marked. See
    ELISION above.
    """
    t = re.sub(r"\s+", " ", text)
    if is_body:
        m = bp["body_starts_at_item"].search(t)
        if m:
            t = t[m.start():]
        m = bp["body_ends_at"].search(t)
        if m:
            t = t[:m.start()]
        m = bp["forward_looking_start"].search(t)
        if m:
            nxt = bp["forward_looking_end"].search(t, m.end())
            if nxt:
                t = t[:m.start()] + ELISION + t[nxt.start():]
            # CONSERVATIVE FALLBACK — do not strip at all when the end of the
            # caution block cannot be located.
            #
            # This branch previously did `t = t[:m.start()]`, on the reasoning that
            # an unterminated caution block must run to the end of the document.
            # That reasoning was wrong and expensive: in eleven FY2021-FY2022
            # filings the caution is followed directly by the Q&A, so the block WAS
            # terminated, just not by a pattern we had. Those filings were trimmed
            # from ~9,000 characters to ~330 — the entire Q&A deleted — and because
            # the remainder fell under the stub threshold they then dropped out of
            # the extraction plan without a word.
            #
            # Stripping boilerplate is a cost optimization. Losing content is a
            # correctness failure. When the two are in tension the optimization
            # loses, so an unrecognised layout now costs a few cents in duplicated
            # boilerplate instead of silently discarding a document.
    else:
        t = bp["exhibit_head"].sub("", t)
        t = bp["image_placeholder"].sub("", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def scan(raw: str, patterns: dict, headline_window: int) -> dict[str, dict]:
    """Which signals fire in this document, how strongly, and on what text.

    Scans the RAW text, deliberately. A classifier has to see everything the
    filing says; boilerplate stripping is a cost measure and must not be able to
    change a routing decision. (It can: an earlier version of this scan ran on
    stripped text and counted 40 Q&A filings where the raw text shows 53.)
    """
    found: dict[str, dict] = {}
    for signal, pats in patterns.items():
        hits = []
        for p in pats:
            for m in p.finditer(raw):
                hits.append({"at": m.start(), "matched": m.group(0)[:80],
                             "pattern": p.pattern})
                break                       # one hit per pattern is enough
        if not hits:
            continue
        first = min(h["at"] for h in hits)
        found[signal] = {
            "strength": "strong" if first < headline_window else "mention",
            "first_at": first,
            "n_patterns_matched": len(hits),
            "evidence": sorted(hits, key=lambda h: h["at"])[:3],
        }
    return found


def decide(docs: list[dict], tri: dict) -> tuple[str, str, list[str]]:
    """The filing-level decision, its reason, and the fields it routes to.

    Deliberately ordered so that every path to `date_only` is guarded.
    """
    material = set(tri["material_signals"])
    routine = set(tri["routine_signals"])
    narrative = set(tri["narrative_signals"])

    strong = {s for d in docs for s, v in d["signals"].items() if v["strength"] == "strong"}
    any_sig = {s for d in docs for s in d["signals"]}

    hit_material = sorted(strong & material)
    hit_narrative = sorted(any_sig & narrative)
    hit_routine = sorted(strong & routine)

    routes = []
    if hit_material:
        routes.append("events")
    if hit_narrative:
        routes.append("investor_qa")

    if hit_material and hit_narrative:
        return ("read", f"material signal ({', '.join(hit_material)}) in a document that also "
                        f"carries narrative content ({', '.join(hit_narrative)})", routes)
    if hit_material:
        return "read", f"strong material signal: {', '.join(hit_material)}", routes
    if hit_narrative:
        return "read", f"narrative content: {', '.join(hit_narrative)}", routes

    # Only now may a filing be dropped, and only on positive evidence.
    if hit_routine and not (any_sig & material):
        return ("date_only",
                f"routine filing ({', '.join(hit_routine)}) and no material signal anywhere "
                "in the document, not even a passing mention", [])
    if hit_routine:
        weak = sorted(any_sig & material)
        return ("read",
                f"looks routine ({', '.join(hit_routine)}) but a material signal is "
                f"mentioned ({', '.join(weak)}) — read rather than assume it is incidental",
                ["events"])

    # No strong match and nothing routine. Distinguish "a material phrase matched
    # outside the headline window" from "genuinely nothing matched": both are
    # read, but the log has to say which, or it misdescribes its own evidence.
    # The MJKK/SBI Japan unwind of 2023-01-31 lands here — its Termination
    # Agreement language sits past the headline window, so it is a mention, and a
    # log line reading "no signal matched" for that filing would be false.
    weak = sorted(any_sig & material)
    if weak:
        return ("read",
                f"material signal ({', '.join(weak)}) matched outside the headline window, "
                "so it is a mention rather than an announcement — read, because only a "
                "reader can tell those apart", ["events"])

    return ("read", "no signal matched at all — unrecognised filings are read, never "
                    "dropped, because a wrong drop is undetectable downstream", ["events"])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def triage(cfg: dict, inv: dict, manifest: dict) -> list[dict]:
    tri, patterns, bp = cfg["tri"], cfg["patterns"], cfg["bp"]
    hw, cap = tri["headline_window_chars"], tri["max_document_chars"]

    targets = {r["accession"]: r for r in inv["filings"]
               if r["in_window"] and r["disposition"] == "triage"}
    if not targets:
        sys.exit("FATAL: no filings with disposition 'triage' in the inventory. "
                 "Run src/discover.py first (milestone 1).")

    by_acc: dict[str, list[dict]] = {}
    for r in manifest["sections"]:
        if r["accession"] in targets and r.get("ok") and r.get("out"):
            by_acc.setdefault(r["accession"], []).append(r)

    missing = sorted(set(targets) - set(by_acc))
    if missing:
        print(f"WARNING: {len(missing)} triage filing(s) have no extracted section text; "
              f"they cannot be judged and are recorded as such: {missing[:4]}")

    records = []
    for acc, f in sorted(targets.items(), key=lambda kv: kv[1]["filing_date"]):
        rows = by_acc.get(acc, [])
        docs = []
        for r in sorted(rows, key=lambda r: r["doc_type"]):
            raw = re.sub(r"\s+", " ", (ROOT / r["out"]).read_text(encoding="utf-8"))
            is_body = r["doc_type"].upper().startswith("8-K")
            net = strip_boilerplate(raw, is_body, bp)
            over = len(net) > cap

            # Write the trimmed text, so the exact bytes an extraction call sees
            # are an artifact on disk rather than recomputed at call time.
            #
            # Note what is NOT done here: build_ledger.py keeps verifying quotes
            # against the FULL original section in data/sections/, not against
            # this file. So the model reads the trimmed text and its quotes are
            # checked against the untrimmed filing — the trimming cannot make a
            # bad quote pass, only make a straddling one fail.
            tp = TRIAGE_DIR / "text" / acc / f"{r['key']}.txt"
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(net, encoding="utf-8")

            docs.append({
                "doc_type": r["doc_type"], "section_key": r["key"],
                "is_body": is_body, "path": r["out"],
                "trimmed_path": str(tp.relative_to(ROOT)).replace("\\", "/"),
                "raw_chars": len(raw), "content_chars": len(net),
                # Over the cap is SKIPPED and RECORDED. Truncating would hand the
                # model a partial document that reads as a complete one.
                "over_size_cap": over,
                "size_cap_note": (f"content is {len(net):,d} chars, over the "
                                  f"{cap:,d} cap — not sent to a model") if over else None,
                "signals": scan(raw, patterns, hw),
            })

        if docs:
            decision, reason, routes = decide(docs, tri)
        else:
            decision, reason, routes = ("read",
                                        "no extracted text available to judge — cannot be "
                                        "dropped on no evidence", ["events"])

        # Which documents actually carry the content, so the extractor reads the
        # right ones. A document with no signal and a stub body carries nothing.
        readable = [d for d in docs if not d["over_size_cap"] and d["content_chars"] >= 400]
        stubs = [d["doc_type"] for d in docs if d["content_chars"] < 400]

        records.append({
            "accession": acc,
            "filing_date": f["filing_date"],
            "report_date": f.get("report_date"),
            "fiscal_year": f["fiscal_year"],
            "form": f["form"],
            "items": f.get("items", []),
            "decision": decision,
            "reason": reason,
            "routes_to": routes,
            "documents": docs,
            "read_section_keys": [d["section_key"] for d in readable] if decision == "read" else [],
            "stub_documents": stubs,
            "content_chars": sum(d["content_chars"] for d in readable),
        })
    return records


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(records: list[dict], cfg: dict, inv: dict) -> Path:
    tri = cfg["tri"]
    read = [r for r in records if r["decision"] == "read"]
    dropped = [r for r in records if r["decision"] == "date_only"]

    L = ["# 8-K triage log — conditional items 7.01 / 8.01", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}. "
         f"{inv['ticker']} ({inv['company_name']}), CIK {inv['cik']}.", "",
         "Deterministic: no model calls, so the same inputs always give the same decisions "
         "and every one can be checked by hand. `config/forms.toml` requires this log — "
         "\"Log every triage decision; a silent drop here loses real events.\"", "",
         "**A `date_only` decision requires positive evidence of a routine filing AND the "
         "absence of every material signal, including passing mentions.** Anything "
         "unrecognised is read. The full drop list is printed below so it can be audited by "
         "eye, which is the actual safety net here — the classifier is only the first pass.",
         "", "## Summary", "",
         f"- filings triaged: **{len(records)}**",
         f"- read: **{len(read)}**",
         f"- date_only: **{len(dropped)}**",
         f"- content to read, after stripping boilerplate: "
         f"**{sum(r['content_chars'] for r in read):,d}** chars"]

    over = [(r, d) for r in records for d in r["documents"] if d["over_size_cap"]]
    if over:
        L += ["", f"- documents over the {tri['max_document_chars']:,d}-char cap and therefore "
                  f"**not read**: **{len(over)}**"]
        for r, d in over:
            L.append(f"  - {r['filing_date']} {r['accession']} {d['doc_type']} — "
                     f"{d['content_chars']:,d} chars")

    # Decisions by year, so a year that lost everything is visible at a glance.
    L += ["", "## By fiscal year", "",
          "| FY | triaged | read | date_only | content chars |", "|---|---|---|---|---|"]
    for fy in sorted({r["fiscal_year"] for r in records}):
        yr = [r for r in records if r["fiscal_year"] == fy]
        yrd = [r for r in yr if r["decision"] == "read"]
        L.append(f"| FY{fy} | {len(yr)} | {len(yrd)} | {len(yr) - len(yrd)} | "
                 f"{sum(r['content_chars'] for r in yrd):,d} |")

    # Where the content lives. This is the format migration, made visible.
    L += ["", "## Where the content sits, by year", "",
          "The Reg FD investor Q&A moved from the 8-K body to an EX-99.1 exhibit inside the "
          "window. A bodies-only reader would silently return nothing for the later years.",
          "", "| FY | content in body | content in exhibit |", "|---|---|---|"]
    for fy in sorted({r["fiscal_year"] for r in records}):
        yr = [r for r in records if r["fiscal_year"] == fy and r["decision"] == "read"]
        b = sum(1 for r in yr if any(d["is_body"] and d["content_chars"] >= 2000
                                     for d in r["documents"]))
        e = sum(1 for r in yr if any(not d["is_body"] and d["content_chars"] >= 2000
                                     for d in r["documents"]))
        L.append(f"| FY{fy} | {b} | {e} |")

    L += ["", "## Signal counts", "",
          "`strong` = matched inside the first "
          f"{tri['headline_window_chars']:,d} characters, where a press release states its "
          "subject. `mention` = matched later, which on this corpus usually means management "
          "discussing something in a Q&A answer rather than announcing it. Only strong "
          "material matches drive routing.", "",
          "| signal | strong | mention |", "|---|---|---|"]
    sc: Counter = Counter()
    for r in records:
        for d in r["documents"]:
            for s, v in d["signals"].items():
                sc[(s, v["strength"])] += 1
    for s in sorted({k[0] for k in sc}):
        L.append(f"| {s} | {sc[(s, 'strong')]} | {sc[(s, 'mention')]} |")

    L += ["", "## date_only — the full drop list, for audit", ""]
    if dropped:
        L.append("| filed | accession | items | reason |")
        L.append("|---|---|---|---|")
        for r in dropped:
            L.append(f"| {r['filing_date']} | {r['accession']} | "
                     f"{', '.join(r['items'])} | {r['reason']} |")
    else:
        L.append("_Nothing was dropped._")

    L += ["", "## read — every kept filing", "",
          "| filed | FY | items | chars | routes to | reason |", "|---|---|---|---|---|---|"]
    for r in read:
        L.append(f"| {r['filing_date']} | FY{r['fiscal_year']} | {', '.join(r['items'])} | "
                 f"{r['content_chars']:,d} | {', '.join(r['routes_to']) or '—'} | {r['reason']} |")

    p = TRIAGE_DIR / "triage-report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Triage the conditional 7.01/8.01 8-Ks. Deterministic, no model calls.")
    ap.add_argument("--show", choices=["read", "date_only"],
                    help="print the filings with this decision, with their evidence")
    ap.add_argument("--fy", type=int, action="append", help="only this fiscal year (repeatable)")
    args = ap.parse_args()

    cfg = load_config()
    inv = load_json(INVENTORY, "Run src/discover.py first (milestone 1).")
    manifest = load_json(SECTIONS_MANIFEST, "Run src/extract_sections.py first (milestone 3).")

    records = triage(cfg, inv, manifest)

    TRIAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticker": inv["ticker"], "cik": inv["cik"],
        "headline_window_chars": cfg["tri"]["headline_window_chars"],
        "max_document_chars": cfg["tri"]["max_document_chars"],
        "filings_triaged": len(records),
        "read": sum(1 for r in records if r["decision"] == "read"),
        "date_only": sum(1 for r in records if r["decision"] == "date_only"),
        "records": records,
    }
    (TRIAGE_DIR / "triage-8k.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    report = write_report(records, cfg, inv)

    read = [r for r in records if r["decision"] == "read"]
    print(f"8-K triage — {len(records)} conditional filing(s), deterministic, no model calls")
    print()
    for fy in sorted({r["fiscal_year"] for r in records}):
        yr = [r for r in records if r["fiscal_year"] == fy]
        yrd = [r for r in yr if r["decision"] == "read"]
        print(f"  FY{fy}  {len(yr):>3d} triaged  ->  {len(yrd):>3d} read, "
              f"{len(yr) - len(yrd):>2d} date_only   "
              f"{sum(r['content_chars'] for r in yrd):>8,d} chars to read")
    print()
    print(f"  read      : {len(read)}")
    print(f"  date_only : {len(records) - len(read)}")
    print(f"  content   : {sum(r['content_chars'] for r in read):,d} chars "
          f"(raw was {sum(d['raw_chars'] for r in records for d in r['documents']):,d})")
    over = [(r, d) for r in records for d in r["documents"] if d["over_size_cap"]]
    if over:
        print(f"  OVER CAP  : {len(over)} document(s) not read — see the report")
    print()
    print(f"wrote {(TRIAGE_DIR / 'triage-8k.json').relative_to(ROOT)}")
    print(f"wrote {report.relative_to(ROOT)}")

    if args.show:
        sel = [r for r in records if r["decision"] == args.show
               and (not args.fy or r["fiscal_year"] in args.fy)]
        print()
        print("=" * 78)
        print(f"{args.show} — {len(sel)} filing(s)")
        for r in sel:
            print(f"\n  {r['filing_date']}  FY{r['fiscal_year']}  {', '.join(r['items'])}  "
                  f"{r['accession']}")
            print(f"    decision : {r['decision']} — {r['reason']}")
            print(f"    routes   : {', '.join(r['routes_to']) or '—'}")
            for d in r["documents"]:
                sig = ", ".join(f"{s}:{v['strength']}" for s, v in d["signals"].items()) or "none"
                print(f"    {d['doc_type']:<9s} {d['content_chars']:>7,d} chars  [{sig}]"
                      + ("  OVER CAP" if d["over_size_cap"] else ""))
                for s, v in d["signals"].items():
                    if v["strength"] == "strong":
                        print(f"        strong {s} @{v['first_at']}: "
                              f"{v['evidence'][0]['matched']!r}")


if __name__ == "__main__":
    main()
