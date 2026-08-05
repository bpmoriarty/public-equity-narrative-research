"""Milestone 4a — extract narrative facts from the located sections, via Claude.

The first stage in this pipeline that spends money. Everything before it is
deterministic parsing.

Run it:
    uv run python src/extract_facts.py --estimate         # token count + cost, no calls
    uv run python src/extract_facts.py --fy 2023          # one year
    uv run python src/extract_facts.py                    # all years
    uv run python src/extract_facts.py --fy 2023 --task comp --force

Writes one file per task:
    data/ledger/facts/FY<year>_<task>.json

---------------------------------------------------------------------------
WHAT THE MODEL IS AND IS NOT ASKED TO DO
---------------------------------------------------------------------------
Not asked: anything a computer can do exactly. Section boundaries are structural
HTML parsing (src/extract_sections.py). Risk factor deltas are string similarity
(src/risk_diff.py) — the largest section in the filing, and it never reaches an
API call. Filing dates, accession numbers and earnings cadence come from the
inventory.

Asked: the judgment calls. Which sentences in 100,000 characters of Item 1 state
a strategic priority. Which incentive metric carries what weighting. Which
phrasing shifted in a way worth noticing. These have no deterministic answer.

---------------------------------------------------------------------------
ONE CALL PER (YEAR, SOURCE GROUP)
---------------------------------------------------------------------------
Seven tasks per year, each seeing exactly the sections that can support its
fields. Three reasons this beats one call per year:

  - A whole-year record does not fit in one response, and structured output that
    hits max_tokens is a failed call rather than a shorter one.
  - Each large section is sent exactly once. Splitting `business` into three
    field-level tasks would send the same 100,000-character Item 1 three times.
  - A task is the unit of caching and of retry. Results are written per task, so
    a crash costs at most the tasks in flight, and a re-run costs nothing for
    work already done (CLAUDE.md: save results incrementally, per file).

---------------------------------------------------------------------------
COST CONTROL AND THE CACHE
---------------------------------------------------------------------------
A completed task is never re-run. `--force` is the only way to spend tokens on a
question already answered, and it takes an explicit task or year. This matters
more than it sounds: the downstream ledger builder is re-run constantly while
being developed, and it reads these files rather than the API.

Prompt caching is deliberately NOT used. It pays off when the same prefix is
resent; here each section is sent to exactly one task, so there is no repeated
prefix to cache and a cache write would be pure overhead.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import truststore
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_schema import TASK_MODELS  # noqa: E402

truststore.inject_into_ssl()           # use the Windows cert store (corporate SSL)
load_dotenv()

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SECTIONS_MANIFEST = ROOT / "data" / "sections" / "sections-manifest.json"
INVENTORY = ROOT / "data" / "discovery" / "inventory.json"
FACTS_DIR = ROOT / "data" / "ledger" / "facts"
TRIAGE = ROOT / "data" / "triage" / "triage-8k.json"

# Published Claude Opus 5 rates, per million tokens. Used only to print an
# estimate before spending anything; nothing depends on them being current.
PRICE_IN, PRICE_OUT = 5.00, 25.00

SYSTEM = """\
You extract facts from SEC filings for a narrative and governance history of a \
public company. You are given one span of one filing and asked for one category \
of fact.

Rules, in priority order:

1. ONLY what this document states. Not what you know about the company, not what \
is probably true, not what a similar company disclosed. If the document does not \
support an item, leave it out. An empty list is a correct and useful answer.

2. EVERY item carries a verbatim quote. The `quote` field must be an exact, \
contiguous span copied from the document text — no paraphrase, no stitching \
together separated passages, no ellipses, no corrected typos. Quotes are checked \
against the source automatically, and an item whose quote cannot be found is \
recorded as unreliable. Choose the span that most directly supports the item, and \
prefer one long enough to stand on its own (roughly one to three sentences).

3. MANAGEMENT'S OWN PHRASING for anything that captures how the company describes \
itself. The point of this extraction is to detect how language changes between \
years, which is destroyed by normalizing it into your own words.

4. NO INFERENCE PRESENTED AS FACT. If a departure is announced without a reason, \
`stated_reason` is null — "no reason given" is itself a finding. If a number is \
approximate, say so as stated rather than rounding to a clean figure.

5. DO NOT DEDUPLICATE ACROSS THE DOCUMENT. If a priority is stated in three \
places, extract the clearest statement once. But do not merge two genuinely \
different priorities into one item because they are related.

Prefer a shorter list of well-evidenced items over a long list of weak ones."""

# Each task: which section keys it reads, and what it is being asked for.
# The `ask` text is appended to the document, after the source, so the volatile
# part of the prompt is last.
TASKS: dict[str, dict] = {
    "business": {
        "sections": ["10-K_item1_business"],
        "ask": "From this Item 1 (Business):\n"
               "- strategic_priorities: what management says it is trying to do, and where "
               "it says it is investing or focusing. Stated priorities and strategy, not "
               "descriptions of what the business currently sells.\n"
               "- segments: the reportable segments or business lines as named here, with a "
               "note ONLY where this document states a change (renamed, created, combined, "
               "discontinued).\n"
               "- headcount: total employees if stated. Null if this document gives no figure.",
    },
    "mdna": {
        "sections": ["10-K_item7_mdna"],
        "ask": "From this Item 7 (MD&A):\n"
               "- events: discrete, dated corporate events this section describes — "
               "acquisitions, divestitures, restructurings, impairments, financings, segment "
               "changes, guidance changes. Not ongoing operations, and not routine "
               "period-over-period revenue movement.\n"
               "- segment_changes: any re-segmentation or change in how results are reported. "
               "Empty list if there is none — a re-segmentation is a strategic signal and a "
               "false one is worse than none.\n"
               "- notable_language: phrasing worth attention — an unusually direct admission, "
               "a shift in how a business is characterised, a hedge on something previously "
               "stated plainly. Not routine accounting or boilerplate.",
    },
    "comp": {
        "sections": ["DEF14A_cdna", "DEF14A_incentive_tables"],
        "ask": "From this Compensation Discussion & Analysis and the compensation tables:\n"
               "- incentive_metrics: what specifically pays out. For each metric, which plan "
               "it belongs to, its weighting, and its target or payout range where stated. "
               "This is the most important output of this task: it is what the company "
               "actually pays for, as against what it says it prioritises.\n"
               "- notable_language: how the committee justifies its choices, especially any "
               "explanation of why metrics changed, or of a discretionary adjustment.",
    },
    "board": {
        "sections": ["DEF14A_director_bios"],
        "ask": "From this section on the board of directors:\n"
               "- board_size, members (name, role, year they joined, committees), and the "
               "standing committee names.\n"
               "NOTE: this section's boundaries are known to be unreliable, so it may begin "
               "or end mid-topic and may not contain every director. Extract what is "
               "actually present and do not fill gaps — a partial list is expected and will "
               "be recorded as such.",
    },
    "letter": {
        "sections": ["letter_full_text"],
        "ask": "From this shareholder letter:\n"
               "- strategic_priorities: what leadership says matters, in its own voice. A "
               "letter states priorities more plainly than a 10-K does; this is the point of "
               "reading it.\n"
               "- notable_language: the passages that carry tone and emphasis — what is "
               "claimed as a success, what is acknowledged as a problem, what recurs.",
    },
    "events_8k": {
        "sections": ["8-K"],          # special: material 8-K bodies, see gather_8k
        "ask": "These are the bodies of the material 8-K filings for this fiscal year, in "
               "date order, each headed by its filing date, accession number and SEC item "
               "numbers.\n"
               "- leadership: every director or officer appointment, departure, promotion or "
               "role change, with the date and the reason THE FILING GIVES (null if none — "
               "most give none, and that is a finding).\n"
               "- events: the material events — agreements entered or terminated, "
               "acquisitions completed, restructurings, financings.\n"
               "Attribute each item to the filing it came from by quoting that filing.",
    },
    "investor_qa": {
        # Special: one call PER FILING, sources resolved from the triage log.
        # See gather_investor_qa and the PER-FILING note in its docstring.
        "sections": ["triage:investor_qa"],
        "per_filing": True,
        "ask": "This is one Regulation FD filing in which Morningstar published written "
               "answers to questions submitted by investors.\n"
               "- topics: the exchanges that bear on STRATEGY, CAPITAL ALLOCATION, "
               "PORTFOLIO CHANGES, GOVERNANCE, or COMPETITIVE POSITION. For each, what was "
               "asked about and what management said, in management's own phrasing.\n"
               "- notable_language: passages that carry tone or emphasis — an unusually "
               "direct admission, a claim that recurs, a hedge on something previously "
               "stated plainly, a shift in how a business is characterised.\n"
               "\n"
               "SCOPE — this matters more here than in any other task. Much of this "
               "document is commentary on quarterly financial results: revenue movement, "
               "margin drivers, expense timing, foreign exchange effects, comparisons to "
               "the prior quarter. THAT IS OUT OF SCOPE. This is a narrative and "
               "governance history, not a financial one. Leave out any exchange whose "
               "substance is the explanation of a reported number.\n"
               "Include an exchange about the same business only where management states "
               "an intention, a priority, a change of direction, a reason for a decision, "
               "or a characterisation of its competitive position. The test is whether the "
               "answer would still be worth reading five years from now.\n"
               "An empty list is a correct answer for a filing that is all results "
               "commentary.",
    },
    "votes": {
        "sections": ["8-K_5.07"],     # special: the paired vote 8-K, see gather_votes
        "ask": "This is the 8-K Item 5.07 reporting the shareholder vote held at the annual "
               "meeting that followed this fiscal year's proxy statement.\n"
               "- results: every matter voted on, with the vote counts exactly as reported "
               "and the stated outcome. Report the director election as one item per "
               "nominee only if counts are given per nominee.\n"
               "Copy the numbers exactly. Do not round, total or recompute them.",
    },
}


# ---------------------------------------------------------------------------
# Gathering source text
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(ROOT / "config" / "company.toml", "rb") as fh:
        return tomllib.load(fh)


def load_sections() -> list[dict]:
    if not SECTIONS_MANIFEST.exists():
        sys.exit(f"FATAL: {SECTIONS_MANIFEST} not found. Run src/extract_sections.py first.")
    return json.loads(SECTIONS_MANIFEST.read_text(encoding="utf-8"))["sections"]


def load_inventory() -> dict:
    if not INVENTORY.exists():
        sys.exit(f"FATAL: {INVENTORY} not found. Run src/discover.py first.")
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def load_triage() -> dict | None:
    """The 8-K triage decisions, if triage has been run. None if it has not.

    Optional rather than required, so the six original tasks still run in a
    checkout where triage has never been run. Any task that actually needs it
    fails loudly in plan_tasks rather than quietly planning zero units.
    """
    if not TRIAGE.exists():
        return None
    return json.loads(TRIAGE.read_text(encoding="utf-8"))


def read_section(row: dict) -> str:
    return (ROOT / row["out"]).read_text(encoding="utf-8")


def gather_plain(sections: list[dict], fy: int, keys: list[str]) -> list[dict]:
    """Sections for one year, by key. Returns [{key, accession, form, text}]."""
    out = []
    for key in keys:
        for r in sections:
            if r["fiscal_year"] == fy and r["key"] == key and r.get("ok") and r.get("out"):
                out.append({"key": key, "accession": r["accession"], "form": r["form"],
                            "filing_date": r["filing_date"], "text": read_section(r)})
    return out


def gather_8k(sections: list[dict], inv: dict, fy: int) -> list[dict]:
    """Bodies of the material 8-K filings for one fiscal year.

    BODIES ONLY, never the exhibits. The 8-K body is where the item narrative
    lives — "the Board appointed X effective Y" — and it runs 3,000-10,000
    characters. The exhibits attached to the same filings are a different scale
    entirely: the FY2025 credit-agreement 8-K carries a 622,000-character EX-10.1.
    Sending that to extract a leadership change would cost more than the rest of
    this stage combined and would bury the two sentences that matter.

    Exhibits are still recorded as sources on the filing, so an output can cite
    them; they are simply not read by the model.
    """
    material = {r["accession"] for r in inv["filings"]
                if r["in_window"] and r["disposition"] == "in_scope"
                and r["form"].startswith("8-K")}
    items_by_acc = {r["accession"]: r.get("items", []) for r in inv["filings"]}

    out = []
    for r in sections:
        if (r["fiscal_year"] == fy and r["accession"] in material
                and r.get("ok") and r.get("out")
                # the body document, not an exhibit
                and r["doc_type"].upper().startswith("8-K")):
            out.append({"key": r["key"], "accession": r["accession"], "form": r["form"],
                        "filing_date": r["filing_date"],
                        "items": items_by_acc.get(r["accession"], []),
                        "text": read_section(r)})
    out.sort(key=lambda d: d["filing_date"])
    return out


def gather_votes(sections: list[dict], inv: dict, fy: int) -> list[dict]:
    """The 8-K Item 5.07 reporting the vote on THIS fiscal year's proxy.

    THE OFF-BY-ONE THAT MAKES THIS NECESSARY. A DEF 14A for fiscal year N is
    filed the following spring and solicits votes at that spring's annual
    meeting; the 8-K Item 5.07 reporting the result is filed days after that
    meeting. So the vote on FY2021 compensation is in an 8-K filed May 2022, and
    the vote on FY2025 compensation is in an 8-K filed May 2026.

    Pairing on fiscal-year label would therefore attach every vote to the wrong
    year — the same class of error as trusting `reportDate` on a proxy, which in
    milestone 1 misdated every proxy by a year. So the pairing is done on the
    PROXY'S FILING DATE: take the first 5.07 filed after the DEF 14A for year N.
    """
    proxy = next((r for r in inv["filings"]
                  if r["form"] == "DEF 14A" and r["fiscal_year"] == fy
                  and r["disposition"] == "in_scope"), None)
    if not proxy:
        return []

    candidates = sorted(
        (r for r in inv["filings"]
         if r["form"].startswith("8-K") and "5.07" in r.get("items", [])
         and r["filing_date"] > proxy["filing_date"]),
        key=lambda r: r["filing_date"])
    if not candidates:
        return []
    vote_acc = candidates[0]["accession"]

    out = []
    for r in sections:
        if (r["accession"] == vote_acc and r.get("ok") and r.get("out")
                and r["doc_type"].upper().startswith("8-K")):
            out.append({"key": r["key"], "accession": r["accession"], "form": r["form"],
                        "filing_date": r["filing_date"],
                        "proxy_accession": proxy["accession"],
                        "proxy_filed": proxy["filing_date"],
                        "text": read_section(r)})
    return out


def gather_investor_qa(sections: list[dict], tri: dict, fy: int) -> list[list[dict]]:
    """Q&A documents for one year, grouped ONE LIST PER FILING.

    PER-FILING, not per-year, unlike every other task. Three reasons, and the
    first is a correctness issue rather than a preference:

      - FY2025's Q&A runs to 306,000 characters across twelve filings, about
        93,000 tokens. Asking for every topic across all twelve in one response
        would plausibly exceed max_tokens, and a structured response that hits
        max_tokens is a failed call, not a shorter one. Splitting bounds each
        response to one document's worth of topics.
      - These filings are monthly. The unit that a reader cares about is "what
        management said in May", so the filing is the natural unit of the answer
        as well as of the cost.
      - Retry granularity: one bad call costs one month, not a year.

    Which documents to read comes from data/triage/triage-8k.json rather than from
    a rule here, because the answer changes across the window — the Q&A text is
    inline in the 8-K body for FY2021-FY2023 and an EX-99.1 exhibit for
    FY2024-FY2025. `read_section_keys` already encodes that per filing.
    """
    want: dict[str, dict[str, str]] = {}
    for r in tri["records"]:
        if (r["fiscal_year"] == fy and r["decision"] == "read"
                and "investor_qa" in r["routes_to"]):
            # Read the TRIMMED text triage wrote, not the raw section: the cover
            # page and the forward-looking-statements block are verbatim-identical
            # across these filings, so sending them once per filing is paying
            # eleven times for the same paragraphs and pushing the content that
            # matters further down the prompt. Quotes are still verified against
            # the untrimmed section, so nothing is weakened by this.
            want[r["accession"]] = {d["section_key"]: d["trimmed_path"]
                                    for d in r["documents"]
                                    if d["section_key"] in set(r["read_section_keys"])
                                    and d.get("trimmed_path")}

    out = []
    for acc, keyed in want.items():
        srcs = []
        for s in sections:
            if not (s["accession"] == acc and s["key"] in keyed
                    and s.get("ok") and s.get("out")):
                continue
            tp = ROOT / keyed[s["key"]]
            if not tp.exists():
                sys.exit(f"FATAL: trimmed text {tp} is missing but the triage log "
                         "names it. Re-run src/triage_8k.py.")
            srcs.append({"key": s["key"], "accession": s["accession"], "form": s["form"],
                         "filing_date": s["filing_date"], "items": s.get("items", []),
                         "text": tp.read_text(encoding="utf-8")})
        if srcs:
            out.append(sorted(srcs, key=lambda s: s["key"]))
    out.sort(key=lambda g: g[0]["filing_date"])
    return out


def build_prompt(task: str, fy: int, sources: list[dict]) -> str:
    """Assemble the user message: sources first, then the ask."""
    parts = [f"Company fiscal year: FY{fy}", ""]
    for s in sources:
        head = f"=== {s['form']} filed {s['filing_date']}, accession {s['accession']}"
        if s.get("items"):
            head += f", items {', '.join(s['items'])}"
        head += f" — section {s['key']} ==="
        parts += [head, s["text"], ""]
    parts += ["=== END OF DOCUMENT TEXT ===", "",
              TASKS[task]["ask"], "",
              "Extract only from the document text above."]
    return "\n".join(parts)


def plan_tasks(sections: list[dict], inv: dict, tri: dict | None, years: list[int],
               only_task: str | None) -> list[dict]:
    """Every unit of work, with its sources resolved.

    A unit is normally one (year, task). A task marked `per_filing` fans out into
    one unit per filing instead, each with its own `unit` key so it caches and
    retries independently.
    """
    plan = []
    for fy in years:
        for task, spec in TASKS.items():
            if only_task and task != only_task:
                continue
            if spec.get("per_filing"):
                if tri is None:
                    # Loudly, not silently: this task cannot be planned without
                    # the triage log, and producing zero units would look like
                    # "this year has no Q&A filings".
                    sys.exit(f"FATAL: task '{task}' needs data/triage/triage-8k.json. "
                             "Run src/triage_8k.py first.")
                for group in gather_investor_qa(sections, tri, fy):
                    plan.append({"fy": fy, "task": task, "unit": group[0]["accession"],
                                 "sources": group,
                                 "chars": sum(len(s["text"]) for s in group)})
                continue
            if task == "events_8k":
                sources = gather_8k(sections, inv, fy)
            elif task == "votes":
                sources = gather_votes(sections, inv, fy)
            else:
                sources = gather_plain(sections, fy, spec["sections"])
            plan.append({"fy": fy, "task": task, "unit": None, "sources": sources,
                         "chars": sum(len(s["text"]) for s in sources)})
    return plan


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def out_path(fy: int, task: str, unit: str | None = None) -> Path:
    """Cache path for one unit of work.

    Per-filing tasks get the accession in the filename, so each is cached and
    retried on its own. The accession is filesystem-safe as filed (digits and
    hyphens), so it is used verbatim — a sanitized name could collide.
    """
    if unit:
        return FACTS_DIR / f"FY{fy}_{task}_{unit}.json"
    return FACTS_DIR / f"FY{fy}_{task}.json"


def run_one(client: anthropic.Anthropic, cfg: dict, unit: dict) -> dict:
    """One extraction call. Returns a record; never raises."""
    fy, task, uk = unit["fy"], unit["task"], unit.get("unit")
    ex = cfg["extraction"]
    prompt = build_prompt(task, fy, unit["sources"])
    started = datetime.now(timezone.utc)

    try:
        resp = client.messages.parse(
            model=ex["model"],
            max_tokens=ex["max_tokens"],
            output_config={"effort": ex["effort"]},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=TASK_MODELS[task],
        )
    except Exception as exc:
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}

    # A structured response cut off by max_tokens is a failed call, not a short
    # answer: the JSON is incomplete. Surface it rather than storing a partial.
    if resp.stop_reason == "max_tokens":
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"hit max_tokens ({ex['max_tokens']}) — response truncated. "
                         "Raise max_tokens in config/company.toml [extraction]."}
    if resp.stop_reason == "refusal":
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"model declined: {resp.stop_details}"}

    return {
        "fiscal_year": fy,
        "task": task,
        "unit": uk,
        "ok": True,
        "extracted_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": resp.model,
        "effort": ex["effort"],
        "stop_reason": resp.stop_reason,
        "usage": {"input_tokens": resp.usage.input_tokens,
                  "output_tokens": resp.usage.output_tokens},
        # Which filing and section each fact could have come from. The ledger
        # builder re-reads these to verify quotes, so it must be exact.
        "sources": [{k: s[k] for k in s if k != "text"} for s in unit["sources"]],
        "source_chars": unit["chars"],
        "facts": resp.parsed_output.model_dump(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 4a — extract narrative facts via Claude.")
    ap.add_argument("--fy", type=int, action="append", help="only this fiscal year (repeatable)")
    ap.add_argument("--task", choices=sorted(TASKS), help="only this task")
    ap.add_argument("--estimate", action="store_true",
                    help="count tokens and print a cost estimate; make no extraction calls")
    ap.add_argument("--force", action="store_true",
                    help="re-run tasks that already have a cached result (costs tokens)")
    args = ap.parse_args()

    cfg = load_config()
    sections, inv = load_sections(), load_inventory()
    tri = load_triage()
    years = args.fy or list(range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1))

    plan = plan_tasks(sections, inv, tri, sorted(years), args.task)

    # Report missing sources rather than silently producing fewer tasks.
    empty = [u for u in plan if not u["sources"]]
    plan = [u for u in plan if u["sources"]]
    if not args.force:
        cached = [u for u in plan if out_path(u["fy"], u["task"], u.get("unit")).exists()]
        plan = [u for u in plan if not out_path(u["fy"], u["task"], u.get("unit")).exists()]
    else:
        cached = []

    ex = cfg["extraction"]
    print(f"Fact extraction — {ex['model']}, effort={ex['effort']}, "
          f"max_tokens={ex['max_tokens']}, concurrency={ex['max_concurrent_requests']}")
    print(f"  years           : {', '.join(f'FY{y}' for y in sorted(years))}")
    print(f"  tasks to run    : {len(plan)}")
    print(f"  already cached  : {len(cached)}" + ("  (use --force to redo)" if cached else ""))
    if empty:
        print(f"  no source       : {len(empty)}")
        for u in empty:
            print(f"      FY{u['fy']} {u['task']}"
                  + (f" [{u['unit']}]" if u.get("unit") else "")
                  + ": no section text found")
    print()

    if not plan:
        print("nothing to do.")
        return

    client = anthropic.Anthropic()

    # --- estimate ----------------------------------------------------------
    # count_tokens is free and exact for the model in question, which beats a
    # chars/4 guess. Output tokens cannot be counted in advance, so they are
    # bounded by max_tokens — a deliberate over-estimate, clearly labelled.
    if args.estimate:
        total_in = 0
        for u in plan:
            n = client.messages.count_tokens(
                model=ex["model"], system=SYSTEM,
                messages=[{"role": "user", "content": build_prompt(u["task"], u["fy"], u["sources"])}],
            ).input_tokens
            total_in += n
            label = u['task'] + (f" {u['unit']}" if u.get('unit') else '')
            print(f"  FY{u['fy']} {label:34s} {u['chars']:>9,d} chars  {n:>8,d} tokens")
        worst_out = len(plan) * ex["max_tokens"]
        print()
        print(f"input   : {total_in:,d} tokens  ->  ${total_in / 1e6 * PRICE_IN:,.2f}")
        print(f"output  : at most {worst_out:,d} tokens (max_tokens x {len(plan)} calls)  ->  "
              f"${worst_out / 1e6 * PRICE_OUT:,.2f} worst case")
        print(f"total   : ${total_in / 1e6 * PRICE_IN:,.2f} to "
              f"${(total_in / 1e6 * PRICE_IN) + (worst_out / 1e6 * PRICE_OUT):,.2f}")
        print("\nestimate only — no extraction calls were made.")
        return

    # --- run ---------------------------------------------------------------
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    done, failed = 0, []
    # Each result is written the moment it arrives, so a crash costs only the
    # tasks in flight (CLAUDE.md: save incrementally, per file).
    with ThreadPoolExecutor(max_workers=ex["max_concurrent_requests"]) as pool:
        futures = {pool.submit(run_one, client, cfg, u): u for u in plan}
        for fut in as_completed(futures):
            rec = fut.result()
            fy, task, uk = rec["fiscal_year"], rec["task"], rec.get("unit")
            label = task + (f" {uk[-8:]}" if uk else "")
            if rec["ok"]:
                out_path(fy, task, uk).write_text(json.dumps(rec, indent=2), encoding="utf-8")
                counts = {k: (len(v) if isinstance(v, list) else ("1" if v else "0"))
                          for k, v in rec["facts"].items()}
                done += 1
                print(f"  ok    FY{fy} {label:20s} "
                      f"in={rec['usage']['input_tokens']:>7,d} "
                      f"out={rec['usage']['output_tokens']:>6,d}  "
                      + ", ".join(f"{k}={v}" for k, v in counts.items()))
            else:
                failed.append(rec)
                print(f"  FAIL  FY{fy} {label:20s} {rec['error'][:110]}")

    print()
    print("=" * 72)
    print(f"{done} task(s) written to {FACTS_DIR.relative_to(ROOT)}, {len(failed)} failed")
    if failed:
        print("\nfailures (re-run to retry only these — successes are cached):")
        for r in failed:
            print(f"  FY{r['fiscal_year']} {r['task']}"
                  + (f" [{r['unit']}]" if r.get("unit") else "")
                  + f": {r['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
