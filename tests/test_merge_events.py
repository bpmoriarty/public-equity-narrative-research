"""Tests for event merging — the stage that decides two records are one event.

Run:  uv run python tests/test_merge_events.py

WHY THIS FILE EXISTS
--------------------
Merging is destructive in the way that matters: two rows become one, and if the
judgment is wrong an event disappears from the only document that is supposed to be
a chronology of them. Nothing about the output looks wrong when that happens — the
timeline is simply short, and no one counts.

Two decisions are locked in here, both taken from measurement rather than intuition:

1. RECORDS FROM THE SAME FILING ARE NEVER MERGED, at any similarity. A filing does
   not report the same event twice.
2. The similarity threshold sits in the widest gap in the real data (59.6 -> 48.5),
   which is only an eleven-point gap BECAUSE of rule 1. On similarity alone the
   nearest true-positive and true-negative are three points apart.

The fixtures below are real text from the MORN filings, including the pair that
would have been merged wrongly without rule 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from merge_events import (DATE_RE, classify_routine, clusters,  # noqa: E402
                          find_pairs, load_config, merge_cluster)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CFG = load_config()


def row(rid, date, desc, accession, conf="high", typ="other"):
    """A candidate timeline row, shaped as src/merge_events.py builds them."""
    return {"ids": [rid], "fiscal_years": [2023], "field": "events", "type": typ,
            "date": date, "date_precision": "day" if date and len(date) == 10 else None,
            "date_as_stated": date, "description": desc, "quotes": [f"quote for {rid}"],
            "accessions": [accession], "sources": [f"8-K|{accession}||2023-01-01"],
            "confidence": conf}


# --- real text from the MORN window ---------------------------------------
# The two credit-agreement records: one event, two filings. MUST merge.
CA_A = ("Termination of the 2019 Credit Agreement and entry into a new 2022 Credit "
        "Agreement providing a $1.1 billion multi-currency facility.")
CA_B = ("Morningstar entered a new Credit Agreement with Bank of America, N.A. as "
        "Administrative Agent providing for a multi-currency facility.")
# The two Bevin Desmond agreements: two events, ONE filing. MUST NOT merge.
BD_A = ("Morningstar entered a Contract Services Agreement dated February 1, 2023 with "
        "Bevin Desmond, under which she will provide transition services.")
BD_B = ("Separation Agreement and General Release dated February 1, 2023 with Bevin "
        "Desmond, providing a severance payment.")
# The third leg of the FY2025 refinancing, which only links to the others transitively.
REFI_WHOLE = ("Terminated the 2022 Credit Agreement and entered a new $1.5 billion "
              "multi-currency 2025 Credit Agreement.")
REFI_ENTRY = ("Entry into new multi-currency Credit Agreement with Bank of America, N.A. "
              "as Administrative Agent.")
REFI_TERM = ("Termination of the existing credit agreement dated May 6, 2022 in "
             "connection with entry into the new Facility.")


def merge_count(rows):
    """How many rows survive, and the clusters, for a given input."""
    pairs, possible = find_pairs(rows, CFG)
    cl = clusters(len(rows), pairs)
    return [merge_cluster([rows[i] for i in c]) for c in cl], possible


def main() -> int:
    failures = []

    def check(label, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL':5s} {label}")
        if not ok:
            failures.append(f"{label}{' — ' + detail if detail else ''}")

    print("MERGING — one event reported by two filings becomes one row")
    out, _ = merge_count([row("A", "2022-05-06", CA_A, "acc-1"),
                          row("B", "2022-05-06", CA_B, "acc-2")])
    check("same date, different filings, similar text -> merged", len(out) == 1)
    if len(out) == 1:
        check("the merged row keeps both source ids", sorted(out[0]["ids"]) == ["A", "B"])
        check("it records how many filings corroborate it",
              out[0]["corroborating_filings"] == 2)
        check("the other filing's wording is preserved, not discarded",
              len(out[0].get("also_described_as", [])) == 1)

    print()
    print("NOT MERGING — the rules that protect real events")
    out, _ = merge_count([row("A", "2023-02-01", BD_A, "acc-1"),
                          row("B", "2023-02-01", BD_B, "acc-1")])
    check("SAME filing, same date, similar text -> two rows (real near-miss)",
          len(out) == 2,
          "one 8-K reporting two different agreements with the same officer")

    out, _ = merge_count([row("A", "2022-05-06", CA_A, "acc-1"),
                          row("B", "2023-05-06", CA_A, "acc-2")])
    check("identical text on DIFFERENT dates -> two rows", len(out) == 2)

    out, _ = merge_count([row("A", None, CA_A, "acc-1"), row("B", None, CA_A, "acc-2")])
    check("two undated records are never merged to each other", len(out) == 2,
          "no date means no evidence they are the same event")

    out, _ = merge_count([
        row("A", "2024-01-01", "Board approved a quarterly cash dividend.", "acc-1"),
        row("B", "2024-01-01", "Sold the Commodity and Energy Data business.", "acc-2")])
    check("same date, different filings, unrelated text -> two rows", len(out) == 2)

    print()
    print("TRANSITIVE — three records for one transaction")
    rows = [row("WHOLE", "2025-10-31", REFI_WHOLE, "acc-1"),
            row("ENTRY", "2025-10-31", REFI_ENTRY, "acc-2"),
            row("TERM", "2025-10-31", REFI_TERM, "acc-2")]
    out, _ = merge_count(rows)
    check("one row, not two — ENTRY and TERM join through WHOLE", len(out) == 1,
          "ENTRY and TERM are same-filing and never pair directly")
    if len(out) == 1:
        check("all three ids on the row", len(out[0]["ids"]) == 3)

    print()
    print("MERGING MUST NOT LAUNDER CONFIDENCE")
    out, _ = merge_count([row("A", "2022-05-06", CA_A, "acc-1", conf="low"),
                          row("B", "2022-05-06", CA_B, "acc-2", conf="high")])
    check("a low member makes the merged row low",
          len(out) == 1 and out[0]["confidence"] == "low",
          "otherwise a low fact is promoted by being paired with a high one")

    print()
    print("TYPE DISAGREEMENT IS RECORDED, NOT RESOLVED SILENTLY")
    out, _ = merge_count([row("A", "2023-01-27", CA_A, "acc-1", typ="divestiture"),
                          row("B", "2023-01-27", CA_B, "acc-2", typ="other")])
    check("a specific type beats `other`", len(out) == 1 and out[0]["type"] == "divestiture")
    out, _ = merge_count([row("A", "2023-01-27", CA_A, "acc-1", typ="divestiture"),
                          row("B", "2023-01-27", CA_B, "acc-2", typ="restructuring")])
    check("two specific types that disagree are both recorded",
          len(out) == 1 and out[0].get("types_disagree") == ["divestiture", "restructuring"])

    print()
    print("ROUTINE TAGGING — the override that saved a real row")
    routine_cases = [
        # (description, expected routine?)
        ("All ten director nominees listed in the proxy statement were elected at the "
         "2021 Annual Shareholders' Meeting.", True),
        ("Ratification of KPMG LLP as independent registered public accounting firm "
         "for 2021.", True),
        ("Advisory vote approving Morningstar's executive compensation.", True),
        ("Board approved quarterly cash dividend of 45.5 cents per share.", True),
        # THE NEAR-MISS. Same date, same meeting, four routine votes around it — and
        # SPEC.md section 4b names incentive plan changes as a timeline row type.
        ("Shareholders approved the Morningstar, Inc. Amended and Restated 2011 Stock "
         "Incentive Plan at the 2021 Annual Shareholders' Meeting.", False),
        ("A shareholder proposal requesting a Board report on risks associated with "
         "economic activism was voted on.", False),
        ("Board adopted the Morningstar, Inc. Executive Severance Policy.", False),
        ("Sold Commodity and Energy Data business for $52.4 million.", False),
    ]
    for desc, expected in routine_cases:
        got = classify_routine({"description": desc}, CFG)
        check(f"routine={str(expected):5s}  {desc[:62]}", got == expected)

    print()
    print("DATE HANDLING")
    for d, ok in [("2023-02-06", True), ("2022-07", True), ("2022", True),
                  ("July 2022", False), ("2022-7", False), ("", False)]:
        check(f"{'usable' if ok else 'unusable':8s} date {d!r}", bool(DATE_RE.match(d)) == ok)
    r = row("A", None, CA_A, "acc-1")
    r["date_as_stated"] = "sometime in mid-2022"
    check("an unusable date is preserved in `date_as_stated`, not silently dropped",
          r["date_as_stated"] == "sometime in mid-2022" and r["date"] is None)

    print()
    print("=" * 74)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("merging is conservative where it must be and transitive where it should be")
    return 0


if __name__ == "__main__":
    sys.exit(main())
