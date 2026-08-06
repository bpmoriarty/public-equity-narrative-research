"""Milestone 5c — resolve the event records into timeline rows.

Deterministic. No network, no model calls. Three jobs, all of them things the
timeline document cannot do for itself:

1. MERGE the same event where two filings both reported it. In the MORN window 9
   records are restatements of an event another filing already recorded, folding
   into 8 corroborated rows. (An earlier note here said 20, which was the count of
   records merely SHARING a date — most of those are genuinely different events that
   happened on the same day, which is the whole problem this stage solves.) The
   duplication is not noise: it is independent filings corroborating one event, so a
   merged row carries every source id and says how many filings reported it.
2. SPLIT dated rows from undated ones. A chronological table cannot hold a row with
   no date; 26 of 74 events have none. Per the user's decision these go to their own
   "period unclear" block rather than being given a guessed date or dropped.
3. TAG routine annual-meeting governance rather than dropping it, so the document
   stage decides what to render.

Run it:
    uv run python src/merge_events.py
    uv run python src/merge_events.py --show merged
    uv run python src/merge_events.py --show unclear
    uv run python src/merge_events.py --show possible

Writes:
    data/pack/timeline-events.json
    data/pack/timeline-report.md

`src/build_pack.py` imports `timeline_block` and embeds the result, so the ordering
is handled by the import rather than by remembering to run two scripts in sequence.

---------------------------------------------------------------------------
HOW TWO RECORDS ARE JUDGED TO BE ONE EVENT
---------------------------------------------------------------------------
Same date, DIFFERENT filing, and descriptions at least `merge_similarity` alike.

The different-filing requirement is doing most of the work, and it was chosen on
evidence rather than intuition. Similarity alone cannot separate these two pairs:

    72.9  same event, two filings   "Termination of the 2019 Credit Agreement and
                                     entry into a new 2022 Credit Agreement..."
                                    "Morningstar entered a new Credit Agreement
                                     with Bank of America, N.A...."
    61.7  two events, one filing    "...Contract Services Agreement dated
                                     February 1, 2023 with Bevin Desmond..."
                                    "Separation Agreement and General Release
                                     dated February 1, 2023 with Bevin Desmond..."

Eleven points apart, and a threshold between them would be luck. But a filing does
not report the same event twice, so the second pair is excluded by construction and
the remaining threshold lands in an eleven-point gap instead of a three-point one.

Merging is transitive: three records describing one refinancing (the whole
transaction, the entry, the termination) become one row even where two of the three
are same-filing, because each links to the third.

---------------------------------------------------------------------------
WHY UNDATED ROWS ARE NEVER MERGED, WHATEVER THEIR SIMILARITY
---------------------------------------------------------------------------
Not because "no date means no evidence" — the text is evidence. The real reason is
sharper, and it was measured: among the 26 undated rows the two highest-scoring
pairs are 98.9 and 97.4, and they fall on opposite sides of the truth.

    98.9  ONE event   "Recorded a $12.4 million impairment loss related to
                       investment in SmartX Advisory Solutions."
                      "$12.4 million impairment loss recorded in 2024 related to
                       the investment in SmartX Advisory Solutions."
    97.4  FOUR events "Company expects to make regular quarterly dividend payments
                       of 36 cents per share in 2022..."
                      "...of 37.5 cents per share in 2023..."

A margin of 1.5 points. These descriptions are TEMPLATED year over year and differ
only in an amount and a year, which is exactly what token-similarity is worst at: a
score dominated by the template rather than by the event. There is no threshold that
separates them, so undated pairs are reported for a human and never merged. Merging
them would have collapsed four years of distinct dividend guidance into one row.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_schema import canon  # noqa: E402

LEDGER_DIR = ROOT / "data" / "ledger"
PACK_DIR = ROOT / "data" / "pack"
CONFIG = ROOT / "config" / "outputs.toml"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# A date the timeline can sort on: a year, a year-month, or a full date. Anything
# else is treated as undated rather than being coerced — a malformed date that
# sorts wrongly is worse than an acknowledged gap.
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
PRECISION = {4: "year", 7: "month", 10: "day"}

# `other` is what the extractor emits when nothing more specific fits, so it loses
# to any specific type when merged records disagree.
VAGUE_TYPES = {"other", None, ""}


def load_config() -> dict:
    if not CONFIG.exists():
        sys.exit(f"FATAL: {CONFIG} not found.")
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["timeline"]
    cfg["routine"]["compiled"] = [re.compile(p) for p in cfg["routine"]["patterns"]]
    cfg["routine"]["compiled_overrides"] = [re.compile(p)
                                            for p in cfg["routine"]["material_overrides"]]
    return cfg


def load_rows() -> list[dict]:
    """Candidate timeline rows from the ledger: `events` plus `leadership`.

    SPEC.md section 4b wants leadership changes, M&A, restructurings, segment
    changes, incentive plan changes and major financings. `events` carries most of
    that; `leadership` is a separate ledger field and would otherwise be missing
    from the one document that is supposed to be a chronology of it.
    """
    rows = []
    for p in sorted(LEDGER_DIR.glob("FY*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        fy = d["fiscal_year"]
        for x in d["events"]:
            v = x["value"]
            rows.append(_row(x, fy, "events", v.get("type"), v.get("date"),
                             v.get("description", "")))
        for x in d["leadership"]:
            v = x["value"]
            # Composed rather than taken from a single field: the ledger stores
            # leadership as structured parts, and a timeline needs a sentence.
            # `change` is an enum (`role_changed`), so underscores are spaced out —
            # a raw enum value in a finished document reads like a leaked variable.
            change = (v.get("change") or "").replace("_", " ")
            bits = [b for b in (v.get("name"), change, v.get("role")) if b]
            desc = " — ".join([" ".join(bits[:2]), bits[2]]) if len(bits) > 2 else " ".join(bits)
            if v.get("stated_reason"):
                desc += f" (stated reason: {v['stated_reason']})"
            r = _row(x, fy, "leadership", "leadership_transition", v.get("date"), desc)
            # A structured identity for conflict detection. Only leadership gets one,
            # because only leadership has fields that identify the same real-world
            # change independently of how it was worded. See `find_date_conflicts`.
            r["identity"] = " | ".join(str(v.get(k) or "").strip().lower()
                                       for k in ("name", "change", "role"))
            rows.append(r)
    return rows


def _row(fact: dict, fy: int, field: str, typ: str | None,
         date: str | None, desc: str) -> dict:
    s = fact.get("source") or {}
    dt = date if date and DATE_RE.match(str(date)) else None
    return {
        "ids": [fact["id"]],
        "fiscal_years": [fy],
        "field": field,
        "type": typ,
        "date": dt,
        "date_precision": PRECISION.get(len(dt or ""), None),
        "date_as_stated": date,          # kept even when unusable, so nothing is lost
        "description": desc,
        "quotes": [fact["quote"]],
        "accessions": [s.get("accession")] if s.get("accession") else [],
        "sources": ["|".join([s.get("form", ""), s.get("accession", ""),
                              s.get("section_key", ""), s.get("filing_date", "")])]
                   if s else [],
        "confidence": fact["confidence"],
    }


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def find_date_conflicts(rows: list[dict]) -> list[dict]:
    """Rows the filings describe identically but date differently.

    Detected from STRUCTURED FIELDS, not text similarity, and only for leadership
    where those fields exist: same person, same change, same role, different date.

    Text similarity cannot do this job, which is why the key is structured. At a 100.0
    text score there are exactly two pairs in this window, and they are opposites:

        Bevin Desmond / departed / Chief Talent and Culture Officer
            dated 2022-05-06 in one filing and 2023-01-31 in another
            -> ONE departure, two dates. A real conflict, and it is reported.
        Jason Dubinsky / role changed / principal accounting officer
            dated 2024-02-23 and 2024-03-15
            -> TWO changes: he took the role on in February and gave it up in March
               when a Chief Accounting Officer was appointed.

    The structured key separates them where the text does not, because the role strings
    differ — "principal accounting officer (in addition to Chief Financial Officer)"
    against "principal accounting officer" — so only the Desmond pair is reported.
    That distinction is invisible to a similarity score, which reads both as identical.

    The note states what was found and does not assert which reading is right.
    CLAUDE.md: where the filings are ambiguous or contradict each other across years,
    say so rather than silently picking one.
    """
    by_identity: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("identity") and r["date"]:
            by_identity.setdefault(r["identity"], []).append(r)
    out = []
    for identity, group in sorted(by_identity.items()):
        dates = sorted({r["date"] for r in group})
        if len(dates) < 2:
            continue
        out.append({
            "identity": identity,
            "dates": dates,
            "ids": sorted(i for r in group for i in r["ids"]),
            "filings": sorted({a for r in group for a in r["accessions"]}),
            "description": group[0]["description"],
            "note": "The filings record this with more than one date. It may be an "
                    "announcement date against an effective date, or two genuinely "
                    "separate changes — the filings do not settle it, so both rows are "
                    "kept and neither date is presented as the right one.",
        })
    return out


def find_undated_pairs(rows: list[dict], cfg: dict) -> list[tuple]:
    """Undated rows whose text is nearly identical — REPORTED, never merged.

    The floor is deliberately high (95) so the list stays two or three entries and
    keeps being read. At 85 it fills with the dividend-guidance family and a reader
    learns to skip it, which is how a real duplicate survives.
    """
    out = []
    for i, j in combinations(range(len(rows)), 2):
        a, b = rows[i], rows[j]
        if a["date"] or b["date"]:
            continue
        if set(a["accessions"]) & set(b["accessions"]):
            continue
        s = fuzz.token_set_ratio(canon(a["description"]), canon(b["description"]))
        if s >= cfg["undated_report_floor"]:
            out.append((i, j, s))
    return out


def find_pairs(rows: list[dict], cfg: dict) -> tuple[list[tuple], list[tuple]]:
    """(to_merge, possible) — pairs above and below the similarity threshold.

    Only same-date, different-filing pairs are considered at all. Everything below
    the threshold is REPORTED rather than merged or forgotten: the judgment that two
    records are one event is exactly the kind that should be visible.
    """
    merge, possible = [], []
    for i, j in combinations(range(len(rows)), 2):
        a, b = rows[i], rows[j]
        if not a["date"] or a["date"] != b["date"]:
            continue
        if cfg["require_different_filing"] and set(a["accessions"]) & set(b["accessions"]):
            continue
        s = fuzz.token_set_ratio(canon(a["description"]), canon(b["description"]))
        if s >= cfg["merge_similarity"]:
            merge.append((i, j, s))
        elif (cfg["report_possible_duplicates"]
              and s >= cfg["possible_duplicate_floor"]):
            possible.append((i, j, s))
    return merge, possible


def clusters(n: int, pairs: list[tuple]) -> list[list[int]]:
    """Connected components by union-find.

    Transitive on purpose: the FY2025 refinancing is described by three records —
    the whole transaction, the entry, and the termination — and two of those three
    are same-filing, so they only join through the third. Pairwise merging would
    have left two rows for one event.
    """
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, _ in pairs:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    out: dict[int, list[int]] = {}
    for i in range(n):
        out.setdefault(find(i), []).append(i)
    return [sorted(v) for v in out.values()]


def merge_cluster(members: list[dict]) -> dict:
    """One row from several records describing the same event.

    Every description and every source id is kept. The longest description leads
    because it is the most detailed; the others sit in `also_described_as`, which is
    what makes the merge auditable — a reader can see what was folded together and
    disagree.
    """
    if len(members) == 1:
        m = dict(members[0])
        m["corroborating_filings"] = len(set(m["accessions"]))
        return m

    by_len = sorted(members, key=lambda m: -len(m["description"]))
    types = [m["type"] for m in members if m["type"] not in VAGUE_TYPES]
    merged = {
        "ids": sorted({i for m in members for i in m["ids"]}),
        "fiscal_years": sorted({y for m in members for y in m["fiscal_years"]}),
        "field": "events" if any(m["field"] == "events" for m in members) else "leadership",
        # A specific type beats `other`. Where two specific types disagree the
        # disagreement is recorded rather than resolved — the filings themselves
        # framed the event differently, and CLAUDE.md says to say so.
        "type": Counter(types).most_common(1)[0][0] if types else "other",
        "types_disagree": sorted(set(types)) if len(set(types)) > 1 else None,
        "date": members[0]["date"],
        "date_precision": members[0]["date_precision"],
        "date_as_stated": members[0]["date_as_stated"],
        "description": by_len[0]["description"],
        "also_described_as": [m["description"] for m in by_len[1:]],
        "quotes": [q for m in members for q in m["quotes"]],
        "accessions": sorted({a for m in members for a in m["accessions"]}),
        "sources": sorted({s for m in members for s in m["sources"]}),
        # The lowest confidence across the members: merging must not launder a low
        # fact by pairing it with a high one.
        "confidence": "low" if any(m["confidence"] != "high" for m in members) else "high",
    }
    merged["corroborating_filings"] = len(merged["accessions"])
    return {k: v for k, v in merged.items() if v is not None or k == "date"}


def classify_routine(row: dict, cfg: dict) -> bool:
    """Routine annual-meeting governance? Overrides win, for asymmetric-cost reasons.

    Mislabelling a real change as routine risks dropping it from the timeline;
    mislabelling routine governance as material adds a row someone skims past. So
    any material override beats every routine pattern.
    """
    text = row["description"]
    if any(p.search(text) for p in cfg["routine"]["compiled_overrides"]):
        return False
    return any(p.search(text) for p in cfg["routine"]["compiled"])


def timeline_block(include_quotes: bool = True) -> dict:
    """The whole stage, as data. Imported by src/build_pack.py.

    `include_quotes=False` strips the per-row quotes. Inside the full pack every
    row's `ids` resolve to facts that carry those same quotes in the same payload, so
    repeating them measured 26,858 tokens of pure redundancy — and two
    representations of one event is also a way to get inconsistent output. A
    standalone timeline payload, which does not carry the facts, needs them.
    """
    cfg = load_config()
    rows = load_rows()
    to_merge, possible = find_pairs(rows, cfg)
    undated_pairs = find_undated_pairs(rows, cfg)
    date_conflicts = find_date_conflicts(rows)

    # The window's first fiscal year, so rows describing earlier events can be marked.
    # In-scope filings legitimately describe pre-window events — the FY2021 10-K talks
    # about a 2019 credit agreement — and those facts are real and sourced. They are
    # marked rather than dropped, so a five-year timeline does not silently open with
    # an event from two years before it.
    first_fy = min((y for r in rows for y in r["fiscal_years"]), default=0)

    merged = [merge_cluster([rows[i] for i in c]) for c in clusters(len(rows), to_merge)]
    for r in merged:
        r["routine"] = classify_routine(r, cfg)
        r["predates_window"] = bool(r["date"] and r["date"][:4] < str(first_fy))

    dated = sorted((r for r in merged if r["date"]),
                   key=lambda r: (r["date"], r["description"]))
    unclear = sorted((r for r in merged if not r["date"]),
                     key=lambda r: (r["fiscal_years"][0], r["description"]))

    if not include_quotes:
        for r in merged:
            r.pop("quotes", None)

    return {
        "how_to_use": {
            "dated": "Chronological. `date_precision` is day, month or year — a "
                     "month-precision row must not be rendered as though the day were "
                     "known.",
            "period_unclear": "Real events whose filings gave no usable date. They are "
                              "NOT undated because nothing happened, and they must not be "
                              "given an inferred date. Render as a separate block.",
            "merged": "`corroborating_filings` > 1 means two or more filings independently "
                      "reported this event; `also_described_as` holds the other filings' "
                      "wording and `ids` every source. That is corroboration, not "
                      "duplication.",
            "routine": "`routine: true` marks annual-meeting governance — director "
                       "elections, auditor ratification, say-on-pay, regular dividend "
                       "declarations. Tagged rather than dropped; rendering is your call.",
            "types_disagree": "Present when the filings classified the same event "
                              "differently. Say so rather than picking one silently.",
            "quotes": "Each row's `ids` resolve to facts elsewhere in this payload, and "
                      "those facts carry the verified quotes. Quote from there, never "
                      "from a row's `description` — the description is extracted "
                      "summary, not filing text."
                      if not include_quotes else
                      "`quotes` holds the verified span behind each source id. Anything "
                      "reproduced as the company's words must come from here, not from "
                      "`description`.",
        },
        "merge_rule": f"same date, different filing, description similarity >= "
                      f"{cfg['merge_similarity']} (rapidfuzz token_set_ratio)",
        "counts": {
            "input_records": len(rows),
            "rows_after_merge": len(merged),
            "records_absorbed": len(rows) - len(merged),
            "dated": len(dated),
            "period_unclear": len(unclear),
            "routine": sum(1 for r in merged if r["routine"]),
            "corroborated": sum(1 for r in merged if r["corroborating_filings"] > 1),
            "predates_window": sum(1 for r in merged if r["predates_window"]),
            "date_conflicts": len(date_conflicts),
        },
        "date_conflicts": date_conflicts,
        "dated": dated,
        "period_unclear": unclear,
        "possible_duplicates_not_merged": [
            {"similarity": s, "date": rows[i]["date"],
             "a": {"id": rows[i]["ids"][0], "description": rows[i]["description"]},
             "b": {"id": rows[j]["ids"][0], "description": rows[j]["description"]},
             "note": "Same date, different filings, below the merge threshold. Left as "
                     "two rows. Check before treating them as separate events."}
            for i, j, s in sorted(possible, key=lambda p: -p[2])
        ],
        "undated_near_duplicates_not_merged": [
            {"similarity": s,
             "a": {"id": rows[i]["ids"][0], "description": rows[i]["description"]},
             "b": {"id": rows[j]["ids"][0], "description": rows[j]["description"]},
             "note": "Two undated rows with near-identical wording, from different "
                     "filings. NOT merged, and the score must not be read as evidence "
                     "they are one event: these descriptions are templated year over "
                     "year, so a 97 can be two different years of the same routine "
                     "guidance while a 99 is genuinely one event. Read both and decide."}
            for i, j, s in sorted(undated_pairs, key=lambda p: -p[2])
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 5c — merge and split event records.")
    ap.add_argument("--show", choices=["merged", "dated", "unclear", "possible", "routine"],
                    help="print a view and exit")
    args = ap.parse_args()

    block = timeline_block()
    c = block["counts"]

    if args.show:
        if args.show == "possible":
            for p in block["possible_duplicates_not_merged"]:
                print(f"{p['similarity']:5.1f}  {p['date']}")
                print(f"       A {p['a']['id']}  {p['a']['description'][:100]}")
                print(f"       B {p['b']['id']}  {p['b']['description'][:100]}")
            return
        rows = (block["period_unclear"] if args.show == "unclear" else block["dated"])
        if args.show == "merged":
            rows = [r for r in block["dated"] + block["period_unclear"]
                    if r["corroborating_filings"] > 1]
        if args.show == "routine":
            rows = [r for r in block["dated"] + block["period_unclear"] if r["routine"]]
        for r in rows:
            flags = []
            if r["corroborating_filings"] > 1:
                flags.append(f"{r['corroborating_filings']} filings")
            if r["routine"]:
                flags.append("routine")
            if r.get("types_disagree"):
                flags.append("types disagree: " + "/".join(r["types_disagree"]))
            if r["confidence"] != "high":
                flags.append(r["confidence"])
            print(f"{r['date'] or '(no date)':11s} {r['type'] or '':22s} "
                  f"{r['description'][:88]}")
            if flags:
                print(f"            [{'; '.join(flags)}]  {', '.join(r['ids'])}")
            for alt in r.get("also_described_as", []):
                print(f"            also: {alt[:84]}")
        return

    PACK_DIR.mkdir(parents=True, exist_ok=True)
    (PACK_DIR / "timeline-events.json").write_text(
        json.dumps(block, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    print("Timeline events")
    print()
    print(f"  {c['input_records']} ledger records -> {c['rows_after_merge']} rows "
          f"({c['records_absorbed']} absorbed by merging)")
    print(f"  {c['dated']} dated, {c['period_unclear']} period unclear")
    print(f"  {c['corroborated']} row(s) corroborated by more than one filing")
    print(f"  {c['routine']} row(s) tagged routine governance")
    print(f"  {len(block['possible_duplicates_not_merged'])} possible duplicate(s) "
          f"reported, not merged")
    print()
    prec = Counter(r["date_precision"] for r in block["dated"])
    print(f"  date precision: {dict(prec)}")

    lines = [
        "# Timeline events", "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}.", "",
        f"`{c['input_records']}` ledger records (events + leadership) resolved into "
        f"`{c['rows_after_merge']}` timeline rows. Merge rule: **{block['merge_rule']}**, "
        f"and records from the same filing are never merged at any similarity.", "",
        f"- **{c['dated']}** dated rows, **{c['period_unclear']}** with no usable date",
        f"- **{c['records_absorbed']}** records absorbed by merging into "
        f"**{c['corroborated']}** corroborated rows",
        f"- **{c['routine']}** tagged routine governance (tagged, never dropped)",
        f"- **{len(block['possible_duplicates_not_merged'])}** possible duplicates "
        f"reported for a human to check", "",
        "## Corroborated rows", "",
        "More than one filing independently reported these. That is the useful kind of "
        "duplication — and the reason the merge keeps every source id rather than "
        "picking a winner.", "",
        "| Date | Type | Filings | Description |", "|---|---|---|---|",
    ]
    for r in block["dated"] + block["period_unclear"]:
        if r["corroborating_filings"] > 1:
            lines.append(f"| {r['date'] or '—'} | {r['type']} | "
                         f"{r['corroborating_filings']} | {r['description'][:110]} |")
    lines += ["", "## Period unclear", "",
              "Real events whose filings gave no usable date. Not dropped, and not given "
              "an inferred one — a February 10-K reports things that happened the "
              "previous year, so its filing date would put them in the wrong place.", "",
              "| FY | Type | Description |", "|---|---|---|"]
    for r in block["period_unclear"]:
        lines.append(f"| {r['fiscal_years'][0]} | {r['type']} | {r['description'][:120]} |")
    if block["possible_duplicates_not_merged"]:
        lines += ["", "## Possible duplicates, not merged", "",
                  "Same date, different filings, below the similarity threshold. Left as "
                  "separate rows deliberately — worth an eye before the timeline is "
                  "treated as final.", ""]
        for p in block["possible_duplicates_not_merged"]:
            lines += [f"- **{p['similarity']:.1f}** on {p['date']}",
                      f"  - {p['a']['description'][:130]}",
                      f"  - {p['b']['description'][:130]}"]
    (PACK_DIR / "timeline-report.md").write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"wrote {(PACK_DIR / 'timeline-events.json').relative_to(ROOT)}, timeline-report.md")


if __name__ == "__main__":
    main()
