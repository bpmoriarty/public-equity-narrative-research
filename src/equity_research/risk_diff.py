"""Year-over-year risk factor diffing — deterministic, no model calls.

SPEC.md section 2 asks for risk factors "added, removed, or materially reworded
year over year", and is explicit about the method: "Diff rather than summarizing
each year independently." This module does exactly that, with `rapidfuzz`.

Run it:
    uv run python -m equity_research.risk_diff                # all year pairs + report
    uv run python -m equity_research.risk_diff --fy 2023      # one year's deltas, verbose

Writes:
    data/ledger/risk-deltas.json
    data/ledger/risk-diff-report.md

WHY THIS IS NOT A MODEL CALL
---------------------------------------------------------------------------
Item 1A is the largest section in the filing — 62,000 to 102,000 characters per
year, more than the other two 10-K sections combined. Asking a model to compare
two of them would be the single most expensive call in the pipeline and the
least verifiable: a summary of "what changed" cannot be audited without redoing
the comparison by hand.

The comparison is also not a judgment task. Milestone 3 already split Item 1A
into individually delimited factors (18-25 per year) using the filing's own bold
+ italic styling. Matching this year's list against last year's is string
similarity, which `rapidfuzz` does exactly, cheaply and identically on every
run. The model is then only asked about things a model is actually needed for.

WHAT "MATERIALLY REWORDED" MEANS HERE
---------------------------------------------------------------------------
Two thresholds, both in config/sections.toml [risk_diff], both applied to the
factor HEADING (which is itself the risk statement) and separately to the BODY:

    heading >= unchanged_at (95)        same risk, same words   -> unchanged
    reworded_at (60) <= heading < 95    same risk, new words    -> reworded
    heading <  reworded_at (60)         no counterpart          -> added/removed

A pair can also be reworded on the body alone: the headline risk is untouched
while the substance beneath it is rewritten. That is a real disclosure change and
it would be invisible if only headings were compared.

MATCHING IS ONE-TO-ONE, GREEDILY, BEST SCORE FIRST
---------------------------------------------------------------------------
Without this, two of this year's factors can both claim the same prior-year
factor, and that factor then never appears as removed — the diff silently loses a
deletion, which is precisely the high-signal event SPEC.md cares about. So pairs
are taken in descending similarity and each factor is consumed once.

FY2021 HAS NO PRIOR YEAR IN THE WINDOW
---------------------------------------------------------------------------
Its deltas are recorded as null with a stated reason, NOT as empty lists. Empty
lists would read as "nothing changed in FY2021", which is a different and false
claim. Per the top-level CLAUDE.md: guard edge cases in code, not just prose —
a missing baseline must never render as a confident zero.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone

from rapidfuzz import fuzz

from equity_research import settings
from equity_research._bootstrap import ROOT
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SECTIONS_MANIFEST = P.sections_manifest
OUT_DIR = P.ledger

RISK_KEY = "10-K_item1a_risk_factors"


def load_thresholds() -> dict:
    with open(P.config_dir / "sections.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    if "risk_diff" not in cfg:
        sys.exit("FATAL: config/sections.toml has no [risk_diff] table.")
    return cfg["risk_diff"]


def load_factors() -> dict[int, dict]:
    """{fiscal_year: {"accession":..., "filing_date":..., "factors":[...]}}"""
    if not SECTIONS_MANIFEST.exists():
        sys.exit(f"FATAL: {SECTIONS_MANIFEST} not found. Run `uv run python -m equity_research.extract_sections` first.")
    rows = json.loads(SECTIONS_MANIFEST.read_text(encoding="utf-8"))["sections"]

    out: dict[int, dict] = {}
    for r in rows:
        if r["key"] != RISK_KEY or not r.get("ok"):
            continue
        path = P.resolve(r["out"].replace(".txt", ".factors.json"))
        if not path.exists():
            print(f"  WARNING: FY{r['fiscal_year']} risk section has no factors file at {path}")
            continue
        factors = json.loads(path.read_text(encoding="utf-8"))
        out[r["fiscal_year"]] = {
            "accession": r["accession"],
            "filing_date": r["filing_date"],
            "factors": factors,
        }
    return out


def score(a: str, b: str) -> float:
    """Similarity of two risk statements, 0-100.

    token_sort_ratio, not plain ratio: filers reorder clauses within a risk
    statement between years without changing its meaning ("Our business and
    reputation may be harmed by X" -> "X may harm our business and reputation"),
    and a positional comparison reports that as a wholesale rewrite.
    """
    return fuzz.token_sort_ratio(a.lower(), b.lower())


def diff_years(prior: list[dict], current: list[dict], th: dict) -> dict:
    """Match current-year factors against prior-year factors. One-to-one, greedy."""
    # Score every candidate pair, then consume pairs best-first.
    pairs = []
    for ci, c in enumerate(current):
        for pi, p in enumerate(prior):
            pairs.append((score(c["heading"], p["heading"]), ci, pi))
    pairs.sort(reverse=True)

    matched_c: dict[int, tuple[int, float]] = {}
    used_p: set[int] = set()
    for s, ci, pi in pairs:
        if s < th["reworded_at"]:
            break                       # everything below the floor is a non-match
        if ci in matched_c or pi in used_p:
            continue
        matched_c[ci] = (pi, s)
        used_p.add(pi)

    unchanged, reworded, added, removed = [], [], [], []

    for ci, c in enumerate(current):
        if ci not in matched_c:
            added.append({"heading": c["heading"], "category": c.get("category"),
                          "body_chars": c.get("body_chars")})
            continue
        pi, s = matched_c[ci]
        p = prior[pi]
        body_s = score(c.get("body", ""), p.get("body", ""))
        if s >= th["unchanged_at"] and body_s >= th["body_reworded_at"]:
            unchanged.append({"heading": c["heading"],
                              "heading_similarity": round(s, 1),
                              "body_similarity": round(body_s, 1)})
        else:
            reworded.append({
                "heading_now": c["heading"],
                "heading_prior": p["heading"],
                "heading_similarity": round(s, 1),
                "body_similarity": round(body_s, 1),
                # Which half actually moved. A heading-identical pair with a
                # rewritten body is a different kind of finding from a retitled
                # risk, and the outputs should be able to tell them apart.
                "changed": ("body only" if s >= th["unchanged_at"]
                            else "heading only" if body_s >= th["body_reworded_at"]
                            else "heading and body"),
                "category_now": c.get("category"),
                "category_prior": p.get("category"),
            })

    for pi, p in enumerate(prior):
        if pi not in used_p:
            removed.append({"heading": p["heading"], "category": p.get("category"),
                            "body_chars": p.get("body_chars")})

    return {"unchanged": unchanged, "reworded": reworded,
            "added": added, "removed": removed}


def sanity_check(fy: int, prior_n: int, current_n: int, d: dict) -> list[str]:
    """Catch a broken match rather than reporting its output as a finding.

    Companies revise risk factors incrementally; a year in which nothing matched
    anything means the matcher failed, not that the company rewrote its entire
    risk disclosure. Reporting that as "22 added, 25 removed" would be a
    confident wrong number, which CLAUDE.md rules out explicitly.
    """
    problems = []
    n_matched = len(d["unchanged"]) + len(d["reworded"])
    if current_n and n_matched == 0:
        problems.append(f"FY{fy}: ZERO of {current_n} factors matched the prior year — "
                        "the matcher is probably broken, not the disclosure")
    if current_n and n_matched / current_n < 0.4:
        problems.append(f"FY{fy}: only {n_matched}/{current_n} factors matched "
                        f"({n_matched/current_n:.0%}) — verify before using these deltas")
    # Arithmetic must close: every current factor is matched or added, every prior
    # factor is matched or removed.
    if n_matched + len(d["added"]) != current_n:
        problems.append(f"FY{fy}: accounting error — {n_matched} matched + "
                        f"{len(d['added'])} added != {current_n} current factors")
    if n_matched + len(d["removed"]) != prior_n:
        problems.append(f"FY{fy}: accounting error — {n_matched} matched + "
                        f"{len(d['removed'])} removed != {prior_n} prior factors")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic year-over-year risk factor diff.")
    ap.add_argument("--fy", type=int, help="print this year's deltas in full")
    add_ticker_arg(ap)

    args = ap.parse_args()

    th = load_thresholds()
    data = load_factors()
    if not data:
        sys.exit("FATAL: no risk factor files found. Run `uv run python -m equity_research.extract_sections` --form 10-K.")

    years = sorted(data)
    print(f"Risk factor diff — FY{years[0]}-FY{years[-1]}")
    print(f"  thresholds: unchanged >={th['unchanged_at']}, reworded >={th['reworded_at']}, "
          f"body reworded <{th['body_reworded_at']}")
    print(f"  factors per year: " + ", ".join(f"FY{y}={len(data[y]['factors'])}" for y in years))
    print()

    results: dict[str, dict] = {}
    all_problems: list[str] = []

    for y in years:
        prior_y = y - 1
        if prior_y not in data:
            # No baseline. Null, with the reason — not empty lists. See docstring.
            results[str(y)] = {
                "fiscal_year": y,
                "compared_to": None,
                "deltas": None,
                "unavailable_reason": (
                    f"FY{prior_y} is outside the extraction window, so FY{y} has no "
                    "prior-year risk factor list to diff against. FY{y} is the "
                    "baseline year; its factors are recorded but no change can be "
                    "computed. This is a gap, not an absence of change."
                ).replace("{y}", str(y)),
                "source": {"form": "10-K", "fiscal_year": y,
                           "accession": data[y]["accession"]},
            }
            print(f"FY{y}  baseline — no FY{prior_y} in window, deltas recorded as unavailable")
            continue

        d = diff_years(data[prior_y]["factors"], data[y]["factors"], th)
        problems = sanity_check(y, len(data[prior_y]["factors"]), len(data[y]["factors"]), d)
        all_problems += problems

        results[str(y)] = {
            "fiscal_year": y,
            "compared_to": prior_y,
            "deltas": d,
            "counts": {k: len(v) for k, v in d.items()},
            "problems": problems,
            # Both accessions, because a delta is a claim about two filings.
            "source": {"form": "10-K", "fiscal_year": y,
                       "accession": data[y]["accession"],
                       "prior_accession": data[prior_y]["accession"]},
        }
        c = results[str(y)]["counts"]
        print(f"FY{y}  vs FY{prior_y}:  {c['unchanged']:>3d} unchanged  "
              f"{c['reworded']:>3d} reworded  {c['added']:>3d} added  {c['removed']:>3d} removed")
        for p in problems:
            print(f"      PROBLEM: {p}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        # No generated_utc: this file is committed and is a pure function of the
        # sections and the thresholds, so a clock in it made every re-run produce
        # a diff (CLAUDE.md rule 4). When it last ran is in the gitignored
        # data/_meta/run-log.json.
        "method": "rapidfuzz token_sort_ratio, one-to-one greedy matching, best score first",
        "thresholds": th,
        "factor_counts": {str(y): len(data[y]["factors"]) for y in years},
        "years": results,
    }
    P.risk_deltas.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # --- human-readable report --------------------------------------------
    lines = ["# Risk factor deltas", "",
             "Deterministic — `rapidfuzz`, no model calls. Re-running reproduces "
             "this file byte for byte; when it last ran is in "
             "`data/_meta/run-log.json`.",
             "", f"Thresholds (config/sections.toml `[risk_diff]`): unchanged at "
             f"{th['unchanged_at']}, reworded at {th['reworded_at']}, "
             f"body reworded below {th['body_reworded_at']}.", ""]
    lines += ["| Fiscal year | Factors | Unchanged | Reworded | Added | Removed |",
              "|---|---|---|---|---|---|"]
    for y in years:
        r = results[str(y)]
        if r["deltas"] is None:
            lines.append(f"| FY{y} | {len(data[y]['factors'])} | — | — | — | — |")
        else:
            c = r["counts"]
            lines.append(f"| FY{y} | {len(data[y]['factors'])} | {c['unchanged']} | "
                         f"{c['reworded']} | {c['added']} | {c['removed']} |")
    lines.append("")
    lines.append(f"FY{years[0]} is the baseline year: FY{years[0]-1} is outside the window, so "
                 "no delta can be computed. That is a gap, not an absence of change.")
    lines.append("")

    for y in years:
        r = results[str(y)]
        if r["deltas"] is None:
            continue
        d = r["deltas"]
        lines.append(f"## FY{y} vs FY{y-1}")
        lines.append("")
        lines.append(f"Sources: {r['source']['accession']} (FY{y}), "
                     f"{r['source']['prior_accession']} (FY{y-1})")
        lines.append("")
        for label, items in (("Added", d["added"]), ("Removed", d["removed"])):
            lines.append(f"**{label} ({len(items)})**")
            lines.append("")
            if not items:
                lines.append("_none_")
            for it in items:
                lines.append(f"- {it['heading']}")
                if it.get("category"):
                    lines.append(f"  - category: {it['category']}")
            lines.append("")
        lines.append(f"**Materially reworded ({len(d['reworded'])})**")
        lines.append("")
        if not d["reworded"]:
            lines.append("_none_")
        for it in d["reworded"]:
            lines.append(f"- _{it['changed']}_ (heading {it['heading_similarity']}, "
                         f"body {it['body_similarity']})")
            lines.append(f"  - FY{y-1}: {it['heading_prior']}")
            lines.append(f"  - FY{y}: {it['heading_now']}")
        lines.append("")
    (OUT_DIR / "risk-diff-report.md").write_text("\n".join(lines), encoding="utf-8")
    settings.record_run(P, "risk_diff", years=[str(y) for y in years])

    print()
    print("=" * 72)
    if all_problems:
        print(f"{len(all_problems)} problem(s) — do not use these deltas until resolved:")
        for p in all_problems:
            print(f"  {p}")
    else:
        print("all year pairs passed the match-rate and arithmetic checks")
    print(f"\nwrote {OUT_DIR / 'risk-deltas.json'}")
    print(f"wrote {OUT_DIR / 'risk-diff-report.md'}")

    if args.fy:
        r = results.get(str(args.fy))
        if not r:
            sys.exit(f"\nno results for FY{args.fy}")
        print("\n" + "=" * 72)
        print(json.dumps(r, indent=2)[:6000])


if __name__ == "__main__":
    main()
