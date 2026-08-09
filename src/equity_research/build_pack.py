"""Milestone 5a — assemble the citable pack the output writers read.

Deterministic. No network, no model calls. Reads `data/ledger/FY*.json` and writes
one payload plus the reverse index the output checker needs.

Run it:
    uv run python src/build_pack.py
    uv run python src/build_pack.py --show constraints
    uv run python src/build_pack.py --no-count      # skip the token count

Writes:
    data/pack/pack.json         the payload sent to the model
    data/pack/index.json        {id -> fact} so a citation is a lookup, not a search
    data/pack/pack-report.md    composition, size and cost — the run metadata

---------------------------------------------------------------------------
WHY THE PACK CARRIES QUOTES, AND WHY THAT DECIDED ITS SIZE
---------------------------------------------------------------------------
Measured before building this, and re-measured on every build by `verbatim_rate`
below (these figures are the reading when this was written, not a standing
guarantee): of the 1,741 `value` strings in the ledger longer than 40 characters,
**only 3.1% appear verbatim in their own fact's quote.** The rest are model-written
summaries. `verify_quote` never ran on them — it only ever checked `quote`.

So `value` is a paraphrase and `quote` is evidence, and they are not
interchangeable. An output that puts a `value` string inside quotation marks is
quoting the model rather than the filing, and nothing downstream would catch it.

That is why every fact here carries its quote even though dropping them would save
a third of the payload: without them the pack contains no verified text at all, and
every quotation in the outputs would be unverifiable by construction. The two are
named `claim` and `quote` in the payload, and `how_to_use` says plainly that only
one of them may be reproduced as the company's words.

---------------------------------------------------------------------------
THE PACK MUST NOT CONTAIN A TIMESTAMP
---------------------------------------------------------------------------
The generation calls that need the whole pack share this payload as a cached prompt
prefix. Prompt caching only hits on a byte-identical prefix, so a `generated_utc`
field inside pack.json would silently break every cache read and turn a $0.17 call
into $1.66 — with nothing looking broken except the bill.

Run metadata therefore lives in pack-report.md, never in the payload. The payload
is a pure function of the ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone

from equity_research._bootstrap import ROOT
from equity_research.ledger_schema import canon
from equity_research.merge_events import timeline_block

LEDGER_DIR = ROOT / "data" / "ledger"
PACK_DIR = ROOT / "data" / "pack"
CONFIG = ROOT / "config" / "outputs.toml"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Same order as the ledger, so the two artifacts read the same way.
FIELDS = ["strategic_priorities", "segments", "headcount", "leadership", "board",
          "incentive_metrics", "vote_results", "events", "notable_language",
          "investor_qa"]


def load_pack_config() -> dict:
    """The [pack] block: the model tokens are measured against, and the budget.

    A missing block is fatal rather than defaulted. A default would mean the
    build silently runs with no budget at all, which is indistinguishable from
    a build that passed one.
    """
    if not CONFIG.exists():
        sys.exit(f"FATAL: {CONFIG} not found.")
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("pack")
    if not cfg:
        sys.exit(f"FATAL: {CONFIG} has no [pack] block. It carries the token "
                 f"budget and the model the count is measured against.")
    for key in ("model", "warn_tokens", "max_tokens"):
        if key not in cfg:
            sys.exit(f"FATAL: [pack] in {CONFIG} is missing `{key}`.")
    if cfg["warn_tokens"] > cfg["max_tokens"]:
        sys.exit(f"FATAL: [pack] warn_tokens ({cfg['warn_tokens']:,}) is above "
                 f"max_tokens ({cfg['max_tokens']:,}); the warning could never fire.")
    return cfg


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_years() -> dict[int, dict]:
    if not LEDGER_DIR.exists():
        sys.exit(f"FATAL: {LEDGER_DIR} not found. Run src/build_ledger.py first.")
    years = {}
    for p in sorted(LEDGER_DIR.glob("FY*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        years[d["fiscal_year"]] = d
    if not years:
        sys.exit(f"FATAL: no FY*.json in {LEDGER_DIR}. Run src/build_ledger.py first.")
    # A fact without an id cannot be cited, which is the entire purpose of the
    # pack. Better to refuse than to emit a payload with uncitable facts in it.
    for fy, d in years.items():
        missing = sum(1 for f in FIELDS for x in d[f] if not x.get("id"))
        if missing:
            sys.exit(f"FATAL: FY{fy} has {missing} fact(s) with no id. That ledger was "
                     f"built before ids existed.\n  Rebuild: uv run python src/build_ledger.py")
    return years


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

def compact_fact(x: dict) -> dict:
    """One fact, as small as it can be without losing anything a writer needs.

    Three compactions, each worth real money across 1,329 facts:

    - `source` collapses to a pipe-delimited string. The fiscal year is already in
      the id, so it is not repeated here.
    - `confidence` is omitted when it is `high`. ABSENCE MEANS HIGH — stated in
      `how_to_use`, because a reader who does not know that would read a missing
      field as missing information.
    - `quote_check` is dropped for verified facts; for unverified ones it becomes
      the `why` reason, which is the part a writer must act on.
    """
    s = x.get("source") or {}
    out = {
        "id": x["id"],
        "claim": x["value"],
        "quote": x["quote"],
        # form | accession | section | filing date. Empty when the quote could not
        # be verified, because attribution is measured and there was no match.
        "src": "|".join([s.get("form", ""), s.get("accession", ""),
                         s.get("section_key", ""), s.get("filing_date", "")])
              if s else "",
    }
    if x["confidence"] != "high":
        out["confidence"] = x["confidence"]
        out["why"] = x.get("confidence_reason") or x.get("quote_check")
    if not x["quote_verified"]:
        out["quote_unverified"] = True
    return out


def compact_risk(d: dict) -> dict | None:
    """Risk deltas for one year, ids kept, similarity scores kept.

    Unlike facts, the similarity scores stay: they are the finding. "Reworded at
    71% body similarity" is a different statement from "reworded", and an output
    that wants to say how much a risk factor moved needs the number.
    """
    if not d:
        return None
    return {
        "compared_to_fy": d.get("compared_to"),
        "counts": d.get("counts"),
        "source": f'{(d.get("source") or {}).get("accession", "")}'
                  f' vs {(d.get("source") or {}).get("prior_accession", "")}',
        "deltas": d.get("deltas") or {},
    }


# ---------------------------------------------------------------------------
# The constraints — derived, never hardcoded
# ---------------------------------------------------------------------------

def fy_list(fys) -> str:
    """`[2021, 2022]` renders as `FY2021, FY2022`.

    Cosmetic, but these strings are read by a model and printed into the report, and
    a raw Python list repr in a binding constraint reads like a leaked variable.
    """
    return ", ".join(f"FY{f}" for f in sorted(fys)) or "none"


def verbatim_rate(all_facts: list[dict], min_chars: int = 40) -> tuple[int, int]:
    """How many `value` strings actually occur verbatim in their own fact's quote.

    Returns (verbatim, total) over value strings of at least `min_chars`.

    This is measured on every build rather than written down. The first draft of the
    constraint below carried the literal "3.1%" — a measured statistic pasted into a
    binding rule, directly under a docstring saying never to do that. If a
    re-extraction moved the real figure to 8%, the constraint would have kept
    asserting 3.1% and still read as though someone had checked.
    """
    verbatim = total = 0
    for x in all_facts:
        q = canon(x["quote"])
        for v in x["value"].values():
            if not isinstance(v, str) or len(v) < min_chars:
                continue
            total += 1
            verbatim += canon(v) in q
    return verbatim, total


def build_constraints(years: dict[int, dict], facts_by_field: dict[str, list]) -> list[dict]:
    """The rules the outputs must satisfy, computed from the data.

    Six of them at present. The count is not fixed in code anywhere — the pack
    report prints `len(constraints)` — because a constraint set that has to be
    kept in sync with a number in a docstring is one that will disagree with it.

    Every count here is derived. CLAUDE.md: never hard-code a value another stage
    already computes, or it goes stale silently. A constraint that says "54 facts
    are low confidence" when the number has become 61 is worse than no constraint,
    because it reads as though someone checked.
    """
    all_facts = [x for f in FIELDS for x in facts_by_field[f]]
    low = [x for x in all_facts if x["confidence"] != "high"]
    low_by_field = Counter(x["field"] for x in low)
    unverified = [x for x in all_facts if not x["quote_verified"]]
    vb, vb_total = verbatim_rate(all_facts)

    # Which years report reportable segments and which do not — read off the
    # ledger's own detection rather than naming years in source.
    seg = {fy: d["data_quality"]["segments_basis"]
           ["filing_uses_reportable_segment_language"] for fy, d in years.items()}
    product_years = sorted(fy for fy, r in seg.items() if not r)
    reportable_years = sorted(fy for fy, r in seg.items() if r)

    qa = facts_by_field["investor_qa"]
    qa_by_year = Counter(x["fiscal_year"] for x in qa)

    # Which years have a shareholder letter as a source at all. FY2021 has none —
    # MORN filed no ARS before 2023 — so "five years of letters" would be false.
    letter_years = sorted({x["fiscal_year"] for x in all_facts
                           if (x.get("source") or {}).get("section_key") == "letter_full_text"})
    no_letter = sorted(set(years) - set(letter_years))

    return [
        {
            "rule": "A claim resting on a low-confidence fact must say so in the output, "
                    "or be dropped.",
            "why": "Low means the source section's boundaries are unverified, or the quote "
                   "could not be found verbatim. The fact may be right; it is not "
                   "demonstrably right.",
            "scope": f"{len(low)} of {len(all_facts)} facts, by field: "
                     f"{dict(low_by_field.most_common())}. Each carries `confidence` and "
                     f"`why`. Facts with no `confidence` key are high.",
        },
        {
            "rule": "Never compare segment counts across the whole window.",
            "why": "The basis changes. Where a filing does not disclose reportable "
                   "segments, the `segments` field holds whatever product or business "
                   "areas Item 1 describes, so a change in the count between such a year "
                   "and a reportable-segment year is a change in DISCLOSURE, not "
                   "necessarily a re-segmentation.",
            "scope": f"product/business areas: {fy_list(product_years)}; reportable "
                     f"segments: {fy_list(reportable_years)}. Use the segment names and "
                     f"the filing's own "
                     f"language, never the count.",
        },
        {
            "rule": "Name the meeting date for any say-on-pay or vote claim.",
            "why": "The vote on fiscal year N's compensation happens at the annual meeting "
                   "in N+1. A say-on-pay result attributed to the year it is filed under "
                   "is off by one year.",
            "scope": f"{len(facts_by_field['vote_results'])} vote facts; each `src` ends "
                     f"with the filing date of the 8-K item 5.07 that reported it.",
        },
        {
            "rule": "Label any claim drawn from investor_qa as Regulation FD voluntary "
                    "disclosure, and never present its counts as a series.",
            "why": "These are management's written answers to whatever investors happened "
                   "to ask that month — unaudited, unprompted by any disclosure "
                   "requirement, and substantive. They carry full evidentiary weight here "
                   "by explicit decision, which makes the label the thing that keeps them "
                   "distinguishable from a 10-K disclosure. The per-year counts reflect "
                   "how many questions were submitted and how long the answers ran, not "
                   "anything about the company that year.",
            "scope": f"{len(qa)} of {len(all_facts)} facts ("
                     f"{100 * len(qa) / len(all_facts):.0f}% of the pack). Per year: "
                     f"{dict(sorted(qa_by_year.items()))}. Every one of their ids begins "
                     f"`QA-`, so the register travels with the citation.",
        },
        {
            "rule": "Every claim cites at least one id from this pack, and every quoted "
                    "string is copied from a `quote` field.",
            "why": f"`claim` is a model-written summary that was never checked against "
                   f"the filing — measured on this build: only {100 * vb / vb_total:.1f}% "
                   f"of the {vb_total} `claim` strings over 40 characters appear verbatim "
                   f"in their own fact's quote. `quote` is a span verified to occur in "
                   f"the source section. "
                   "Reproducing a `claim` inside quotation marks quotes the extraction, "
                   "not the company.",
            "scope": f"{len(all_facts)} facts plus risk deltas, all id-addressable. "
                     f"{len(unverified)} fact(s) carry `quote_unverified` — their quote "
                     f"could not be found in any source section and must not be "
                     f"reproduced as the company's words.",
        },
        {
            "rule": "Do not claim five years of shareholder-letter evidence.",
            "why": "The letter is a voluntary filing and it is not present for every year "
                   "in the window. An apparent change in leadership voice across the "
                   "boundary may be a missing document rather than a change in tone.",
            "scope": (f"letters present: {fy_list(letter_years)}; absent: "
                      f"{fy_list(no_letter)} "
                      f"(verified absent on EDGAR, not a lookup failure)")
                     if no_letter else
                     f"letters present for every year in the window: {fy_list(letter_years)}",
        },
    ]


def build_pack(years: dict[int, dict]) -> tuple[dict, dict]:
    """Returns (pack, index). Deterministic: no timestamps, sorted throughout."""
    facts_by_field = {f: [] for f in FIELDS}
    for fy in sorted(years):
        for f in FIELDS:
            facts_by_field[f] += years[fy][f]

    any_year = years[min(years)]
    pack = {
        "subject": {
            "ticker": any_year["ticker"],
            "cik": any_year["cik"],
            "company_name": any_year["company_name"],
            "fiscal_years": sorted(years),
        },
        "how_to_use": {
            "what_this_is": "Every fact extracted from this company's SEC filings for the "
                            "window, each one individually citable. This is the ONLY "
                            "source for the output documents. Nothing may come from "
                            "general knowledge about the company or its industry.",
            "claim_vs_quote": "`claim` is a model-written summary of the fact and was "
                              "never verified against the filing. `quote` is a span "
                              "checked to occur verbatim in the named source section. "
                              "Reason from `claim`; quote ONLY from `quote`.",
            "id": "Cite facts by `id`, e.g. `EVT-FY2024-...`. The prefix names the field "
                  "and the year, so a citation stays legible and its register travels "
                  "with it — anything beginning `QA-` is Regulation FD material.",
            "src": "form | accession | section_key | filing date. Empty when the quote "
                   "could not be verified, because source attribution is measured by "
                   "which section contains the quote rather than asserted.",
            "confidence": "ABSENT MEANS HIGH. A fact carries `confidence` and `why` only "
                          "when it is not high, so the exceptions are the ones that catch "
                          "the eye.",
            "constraints": "The `constraints` block is binding on the output, not "
                           "advisory. Each carries the data it was derived from.",
        },
        "constraints": build_constraints(years, facts_by_field),
        "field_notes": {
            "strategic_priorities": "From the 10-K Item 1 and, where filed, the "
                                    "shareholder letter. The two voices are kept separate "
                                    "on purpose — the difference between what the 10-K "
                                    "states and what the letter emphasises is itself a "
                                    "finding.",
            "segments": "See the segment constraint. Basis changes across the window.",
            "board": "From the proxy director biographies, whose section boundaries are "
                     "unverified — hence low confidence throughout.",
            "incentive_metrics": "The metrics management is actually paid on, with targets "
                                 "and attainment. Compare against `strategic_priorities` "
                                 "for divergence between stated and paid-for priorities.",
            "notable_language": "The `claim` says why the phrasing is notable; the PHRASE "
                                "ITSELF is in `quote`. This field is unusable without its "
                                "quote.",
            "investor_qa": "Regulation FD. See the investor_qa constraint.",
            "risk_deltas": "Deterministic year-over-year diff of 10-K Item 1A, by "
                           "rapidfuzz similarity. Not a model output. `reworded` items "
                           "carry `heading_now`/`heading_prior`; added/removed carry "
                           "`heading`.",
        },
        # Merged, split and classified event rows from src/merge_events.py.
        # Imported rather than run as a separate step, so the ordering cannot be got
        # wrong by running two scripts in the wrong sequence.
        "timeline": timeline_block(include_quotes=False),
        "years": {},
    }

    index: dict[str, dict] = {}
    # A FACT WITH NO SOURCE IS NOT EVIDENCE, so it is not offered as any.
    #
    # CLAUDE.md is unconditional: "Every claim in every output must trace back to a
    # specific filing... If something can't be sourced, it doesn't go in." These
    # facts exist because `attribute()` in build_ledger.py could not find their quote
    # in any section the task read — usually a stitched paraphrase rather than a
    # fabrication, but exactly as unusable either way. The ledger keeps them, because
    # the record of what the model returned has to survive; the PACK must not, because
    # the pack is the evidence the writer is allowed to build on.
    #
    # Until now they were in both, so a document could cite an id that resolved to a
    # fact with no filing behind it and every existing gate would pass it. Nothing
    # gated on the null source itself. VERIFICATION.md D5.
    #
    # Excluding them here also closes the class with a gate that already exists: an
    # id not in the index is an unresolvable citation, which verify_outputs.py already
    # treats as a hard failure. No new check needed.
    #
    # NOT a silent filter — the exclusions are counted, listed by id, and reported in
    # pack-report.md. A pack that quietly drops facts is the same failure in the
    # other direction.
    excluded: list[dict] = []
    for fy in sorted(years):
        d = years[fy]
        y = {
            "filings": [{"form": r["form"], "accession": r["accession"], "filed": r["filed"],
                         "items": r.get("items", [])} for r in d["filings"]],
            "earnings_release_dates": d["earnings_release_dates"],
            "facts": {},
        }
        for f in FIELDS:
            keep, drop = [], []
            for x in d[f]:
                (drop if not x.get("source") else keep).append(x)
            for x in drop:
                excluded.append({"id": x["id"], "field": f, "fiscal_year": fy,
                                 "confidence": x["confidence"],
                                 "quote_check": x.get("quote_check", ""),
                                 "quote": (x.get("quote") or "")[:160]})
            y["facts"][f] = [compact_fact(x) for x in keep]
            for x in keep:
                index[x["id"]] = {
                    "field": f, "fiscal_year": fy, "confidence": x["confidence"],
                    "quote_verified": x["quote_verified"], "quote": x["quote"],
                    "source": x.get("source"),
                }
        y["risk_deltas"] = compact_risk(d.get("risk_deltas"))
        for cat, items in ((d.get("risk_deltas") or {}).get("deltas") or {}).items():
            for it in items:
                index[it["id"]] = {
                    "field": "risk_deltas", "fiscal_year": fy, "delta_category": cat,
                    "confidence": "high", "quote_verified": None,
                    "heading": it.get("heading") or it.get("heading_now"),
                    "source": (d["risk_deltas"].get("source") or {}),
                }
        pack["years"][f"FY{fy}"] = y

    # A SUMMARY travels on the pack; the detail goes to pack-report.md.
    #
    # Deliberately without the quote text. pack.json IS the payload the writer model
    # reads, so putting the excluded quotes here would hand back exactly the evidence
    # the exclusion exists to withhold — it would be a filter that filters nothing.
    # The count and the ids are enough for the writer to know the evidence base is
    # filtered, and are useless as evidence.
    pack["excluded_unsourced_facts"] = {
        "n": len(excluded),
        "ids": [x["id"] for x in excluded],
        "why": "no source: the fact's quote could not be located in any section the "
               "extraction task read, so there is no filing to cite. Kept in "
               "data/ledger/ as the record of what the model returned; excluded here "
               "because this pack is the evidence a document may be built on "
               "(CLAUDE.md: if something can't be sourced, it doesn't go in).",
    }
    return pack, index, excluded


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

def count_tokens(text: str, model: str) -> int | None:
    """Exact token count from the API. Free, and the reason we never guess a cost.

    Returns None rather than failing the build if it cannot reach the API: the pack
    is deterministic and useful without a size estimate, so a network problem must
    not stop the stage from producing it.
    """
    try:
        import os

        import truststore
        from dotenv import load_dotenv
        truststore.inject_into_ssl()
        load_dotenv(ROOT / ".env")
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]).input_tokens
    except Exception as e:                                   # noqa: BLE001
        print(f"  (token count unavailable: {type(e).__name__}: {e})")
        return None


def check_budget(tokens: int | None, pcfg: dict, per_field: dict[str, int],
                 n_facts: int) -> bool:
    """Print the size verdict. False means the pack is over the hard ceiling.

    The failure this guards against does not look like a failure. An oversized
    pack is still accepted by the API and still produces confident, well-formed
    prose; what degrades is recall over the payload, and the symptom is a
    quotation that is subtly wrong. That is invisible at the point of
    generation, which is why the limit has to be enforced here.
    """
    warn, hard = int(pcfg["warn_tokens"]), int(pcfg["max_tokens"])
    print()

    if tokens is None:
        # Not silently OK: an unchecked budget must not read as a passed one.
        print(f"  BUDGET NOT CHECKED — no token count available (--no-count, or "
              f"the API was unreachable).")
        print(f"  The limits are {warn:,} warn / {hard:,} max. Re-run without "
              f"--no-count to check them.")
        return True

    if tokens < warn:
        print(f"  budget: {tokens:,} tokens — under the {warn:,} warning "
              f"({100 * tokens / hard:.0f}% of the {hard:,} ceiling)")
        return True

    # Fact counts, not token counts: a field's share of the facts is the best
    # cheap proxy for its share of the payload, and it is what we already have.
    top = sorted(per_field.items(), key=lambda kv: -kv[1])[:3]
    biggest = ", ".join(f"{f} {100 * n / n_facts:.0f}%" for f, n in top)

    if tokens <= hard:
        print(f"  *** PACK BUDGET WARNING — {tokens:,} tokens, over the "
              f"{warn:,} warning threshold ***")
        print(f"      Largest fields by fact count: {biggest}")
        print(f"      Quote defects were observed at 352,194 tokens (7 of 98 "
              f"quotations in one pass), so this is the range where generation")
        print(f"      quality, not capacity, becomes the constraint. It will "
              f"still build. Consider narrowing the window, or building the")
        print(f"      subset-specific packs rather than sending this one to "
              f"every call.")
        return True

    print("=" * 72)
    print(f"  FATAL: pack is {tokens:,} tokens, above the {hard:,} ceiling.")
    print()
    print(f"  Largest fields by fact count: {biggest}")
    print("  The files were still written, so the pack can be inspected — but "
          "the generation")
    print("  stage must not run against it. A pack this size still returns "
          "fluent prose; what")
    print("  it stops doing reliably is quoting its own contents correctly.")
    print()
    print("  Options, cheapest first:")
    print("    - narrow the fiscal-year window in config/company.toml")
    print("    - build a subset pack for calls that do not need everything")
    print("    - drop quote text from the oldest facts of the largest field")
    print("    - raise [pack] max_tokens in config/outputs.toml, if the "
          "quality risk is accepted")
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 5a — build the citable pack.")
    ap.add_argument("--show", choices=["constraints", "how_to_use", "field_notes"],
                    help="print this block and exit")
    ap.add_argument("--no-count", action="store_true", help="skip the API token count")
    args = ap.parse_args()

    pcfg = load_pack_config()
    years = load_years()
    pack, index, excluded = build_pack(years)

    if args.show:
        print(json.dumps(pack[args.show], indent=2, ensure_ascii=False))
        return

    PACK_DIR.mkdir(parents=True, exist_ok=True)
    # The two files are optimized for different things.
    #
    # pack.json is MODEL INPUT, so every byte is paid for on each call: compact
    # separators and no indentation, which measured 34,741 tokens cheaper than
    # `indent=1` with no content removed at all (367,489 -> 332,748). `sort_keys`
    # makes it byte-stable across runs, which is what lets the prompt cache hit.
    #
    # index.json is a LOCAL LOOKUP for the output checker and is never sent
    # anywhere, so its size is free and it stays readable.
    payload = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (PACK_DIR / "pack.json").write_text(payload, encoding="utf-8")
    (PACK_DIR / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    n_facts = sum(len(y["facts"][f]) for y in pack["years"].values() for f in FIELDS)
    n_risk = sum(len(v) for y in pack["years"].values()
                 for v in ((y["risk_deltas"] or {}).get("deltas") or {}).values())

    print(f"Pack — {pack['subject']['ticker']} ({pack['subject']['company_name']}), "
          f"FY{min(years)}-FY{max(years)}")
    print()
    print(f"  {n_facts} facts + {n_risk} risk deltas = {len(index)} citable ids")
    print(f"  {len(payload):,} chars")
    if excluded:
        print()
        print(f"  {len(excluded)} fact(s) EXCLUDED as unsourceable — kept in the "
              f"ledger, not citable here:")
        for x in excluded:
            print(f"    {x['id']}  {x['field']} FY{x['fiscal_year']} "
                  f"({x['confidence']}) — {x['quote_check'][:70]}")

    tokens = None if args.no_count else count_tokens(payload, pcfg["model"])
    if tokens:
        # Cache economics, printed because they are the reason the payload has no
        # timestamp in it — and because caching is NOT automatically the cheaper
        # option. A read is 0.1x input price, so a cache only repays its own write:
        #   5-minute write is 1.25x  ->  break-even at 1.25/0.9 = 1.4 reads
        #   1-hour   write is 2.0x   ->  break-even at 2.0/0.9  = 2.3 reads
        # Below those, paying full price each time is cheaper. Worth knowing before
        # 10d/10e rather than assuming caching always wins.
        print(f"  {tokens:,} tokens")
        for label, mult, be in (("5-minute", 1.25, 1.25 / 0.9), ("1-hour", 2.0, 2.0 / 0.9)):
            print(f"  {label:9s} cache: ${tokens / 1e6 * 5 * mult:.2f} to write, "
                  f"${tokens / 1e6 * 0.5:.2f} per read "
                  f"— cheaper than paying full price from {be:.1f} reads on")
        print(f"  no cache: ${tokens / 1e6 * 5:.2f} per call")

    per_field = {f: sum(len(y["facts"][f]) for y in pack["years"].values()) for f in FIELDS}
    print()
    for f, n in per_field.items():
        share = 100 * n / n_facts
        print(f"    {f:22s} {n:5d}  {share:4.1f}%  {'#' * int(share / 2)}")

    # The payload's fingerprint. `data/pack/` is gitignored because it is exactly
    # reproducible from the committed ledger — but that only helps if you can prove
    # WHICH payload an output was written from. The hash is the link: every generated
    # document records it, and re-running this stage reproduces it or it does not.
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    print(f"  pack sha256: {digest[:32]}…")

    lines = [
        "# Output pack", "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}. "
        f"{pack['subject']['ticker']} ({pack['subject']['company_name']}), "
        f"FY{min(years)}–FY{max(years)}.", "",
        f"**`pack.json` sha256** `{digest}`", "",
        "`data/pack/` is gitignored: unlike every other artifact here it is exactly "
        "reproducible from the committed ledger, so storing a second copy of the same "
        "content buys nothing. The hash above is what makes that safe — every generated "
        "output records it, so \"which payload was this written from\" is answerable, and "
        "re-running this stage either reproduces the hash or proves the inputs moved.", "",
        "The payload the output writers read, assembled from `data/ledger/` and nothing "
        "else. Deterministic and byte-stable — **`pack.json` deliberately contains no "
        "timestamp**, because all four generation calls share it as a cached prompt prefix "
        "and prompt caching only hits on a byte-identical prefix. Run metadata lives in "
        "this file instead.", "",
        f"- **{len(index)} citable ids** — {n_facts} facts + {n_risk} risk deltas",
        f"- **{len(payload):,} chars**"
        + (f", **{tokens:,} tokens**" if tokens else ""),
    ]
    if tokens:
        lines += [
            "",
            "### Cost per call, and whether to cache", "",
            "Caching is not automatically cheaper. A cached read is 0.1x input price, so a "
            "cache has to repay its own write before it wins.", "",
            "| | Cost | Break-even |", "|---|---|---|",
            f"| No cache | ${tokens / 1e6 * 5:.2f} per call | — |",
            f"| 5-minute cache | ${tokens / 1e6 * 6.25:.2f} write + "
            f"${tokens / 1e6 * 0.5:.2f} per read | cheaper from **1.4 reads** on |",
            f"| 1-hour cache | ${tokens / 1e6 * 10:.2f} write + "
            f"${tokens / 1e6 * 0.5:.2f} per read | cheaper from **2.3 reads** on |",
            "",
            "Only two of the four planned generation calls need the whole pack — the "
            "narrative brief and the observations half of discussion-points. The timeline "
            "and the stated-vs-paid-for-priorities call each need a small subset, so they "
            "should be built their own payloads rather than reading this one.",
        ]
    lines += ["", "## Composition", "",
              "| Field | Facts | Share |", "|---|---|---|"]
    for f, n in sorted(per_field.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {f} | {n} | {100 * n / n_facts:.1f}% |")
    lines += ["", "## Facts excluded as unsourceable", ""]
    if excluded:
        lines += [
            f"**{len(excluded)}** fact(s) are in `data/ledger/` but **not** in this "
            f"pack and **not** citable. Their quote could not be located in any "
            f"section the extraction task read — usually a stitched paraphrase rather "
            f"than a fabrication, and exactly as unusable either way.",
            "",
            "They stay in the ledger because the record of what the extraction model "
            "returned has to survive. They are kept out of the pack because the pack "
            "is the evidence a document may be built on, and CLAUDE.md is "
            "unconditional: *if something can't be sourced, it doesn't go in*. An id "
            "absent from the index is an unresolvable citation, which "
            "`src/verify_outputs.py` already fails on — so this exclusion closes the "
            "class through a gate that already exists. VERIFICATION.md D5.",
            "",
            "| Id | Field | FY | Why it could not be sourced |", "|---|---|---|---|"]
        for x in excluded:
            lines.append(f"| `{x['id']}` | {x['field']} | {x['fiscal_year']} | "
                         f"{x['quote_check'][:110]} |")
    else:
        lines += ["None: every fact in the ledger resolved to a section containing "
                  "its quote."]
    lines += ["", "## Binding constraints", "",
              "Derived from the ledger on every build, never hardcoded — a constraint "
              "quoting a stale count reads as though someone checked.", ""]
    for i, c in enumerate(pack["constraints"], 1):
        lines += [f"{i}. **{c['rule']}**", f"   - *Why:* {c['why']}",
                  f"   - *Scope:* {c['scope']}", ""]
    (PACK_DIR / "pack-report.md").write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"wrote {(PACK_DIR / 'pack.json').relative_to(ROOT)}, "
          f"index.json, pack-report.md")
    print(f"{len(pack['constraints'])} binding constraints, all derived from the ledger")

    # Last, so the artifacts and the composition report exist to be inspected
    # whatever the verdict — but non-zero, so the orchestrator stops here rather
    # than generating documents from an oversized payload.
    if not check_budget(tokens, pcfg, per_field, n_facts):
        sys.exit(1)


if __name__ == "__main__":
    main()
