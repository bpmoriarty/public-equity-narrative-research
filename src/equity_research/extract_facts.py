"""Milestone 4a — extract narrative facts from the located sections, via Claude.

The first stage in this pipeline that spends money. Everything before it is
deterministic parsing.

Run it:
    uv run python -m equity_research.extract_facts --estimate         # token count + cost, no calls
    uv run python -m equity_research.extract_facts --fy 2023          # one year
    uv run python -m equity_research.extract_facts                    # all years
    uv run python -m equity_research.extract_facts --fy 2023 --task comp --force

Writes one file per task:
    data/ledger/facts/FY<year>_<task>.json

---------------------------------------------------------------------------
WHAT THE MODEL IS AND IS NOT ASKED TO DO
---------------------------------------------------------------------------
Not asked: anything a computer can do exactly. Section boundaries are structural
HTML parsing (src/equity_research/extract_sections.py). Risk factor deltas are string similarity
(src/equity_research/risk_diff.py) — the largest section in the filing, and it never reaches an
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
import functools
import hashlib
import json
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from equity_research import model_client, settings
from equity_research._bootstrap import ROOT
from equity_research.ledger_schema import TASK_MODELS
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ROOT comes from _bootstrap (imported above), which also injects the Windows
# cert store and loads .env — see that module for why both live in one place.
SECTIONS_MANIFEST = P.sections_manifest
INVENTORY = P.inventory
FACTS_DIR = P.facts
TRIAGE = P.triage_json

# Placeholder for the company's name inside a prompt, substituted in
# `build_prompt` from the resolved name in inventory.json.
#
# A plain `str.replace` of a sentinel rather than `str.format`: several asks
# contain literal braces (JSON shapes, `{null}`), and format() would either
# choke on them or need every one escaped. A sentinel cannot collide with
# anything the asks actually say.
COMPANY_TOKEN = "<COMPANY>"

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
        "ask": "This is one Regulation FD filing in which " + COMPANY_TOKEN +
               " published written answers to questions submitted by investors.\n"
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
    with open(P.company_toml, "rb") as fh:
        return tomllib.load(fh)


def load_sections() -> list[dict]:
    if not SECTIONS_MANIFEST.exists():
        sys.exit(f"FATAL: {SECTIONS_MANIFEST} not found. Run `uv run python -m equity_research.extract_sections` first.")
    return json.loads(SECTIONS_MANIFEST.read_text(encoding="utf-8"))["sections"]


def load_inventory() -> dict:
    if not INVENTORY.exists():
        sys.exit(f"FATAL: {INVENTORY} not found. Run `uv run python -m equity_research.discover` first.")
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
    return P.resolve(row["out"]).read_text(encoding="utf-8")


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

    out, skipped = [], []
    for acc, keyed in want.items():
        srcs = []
        for s in sections:
            if not (s["accession"] == acc and s["key"] in keyed
                    and s.get("ok") and s.get("out")):
                continue
            tp = P.resolve(keyed[s["key"]])
            if not tp.exists():
                sys.exit(f"FATAL: trimmed text {tp} is missing but the triage log "
                         "names it. Re-run `uv run python -m equity_research.triage_8k`.")
            srcs.append({"key": s["key"], "accession": s["accession"], "form": s["form"],
                         "filing_date": s["filing_date"], "items": s.get("items", []),
                         "text": tp.read_text(encoding="utf-8")})
        if srcs:
            out.append(sorted(srcs, key=lambda s: s["key"]))
        else:
            skipped.append(acc)

    # A filing that triage routed here but that yields no readable document is a
    # PIPELINE FAULT, not an empty year. It has to stop the run.
    #
    # This is how eleven FY2021-FY2022 filings went missing: a boilerplate-stripping
    # bug reduced their bodies below the stub threshold, `read_section_keys` came
    # back empty, and this loop moved on. The extraction reported "32 tasks" and
    # succeeded on all 32, so nothing anywhere looked wrong — the count was simply
    # 11 lower than it should have been, and no output said so.
    if skipped:
        sys.exit(
            f"FATAL: FY{fy} — triage routed {len(skipped)} filing(s) to investor_qa but "
            f"none of their documents is readable:\n"
            + "\n".join(f"    {a}" for a in sorted(skipped))
            + "\n  Triage marked these as carrying Q&A content, so an empty result here "
              "means the content was lost between triage and extraction — most likely "
              "over-aggressive boilerplate stripping. Inspect "
              "data/triage/text/<accession>/ and re-run `uv run python -m equity_research.triage_8k`.")
    out.sort(key=lambda g: g[0]["filing_date"])
    return out


@functools.lru_cache(maxsize=1)
def company_name() -> str:
    """The resolved company name, for prompts that need to name the company.

    From inventory.json, not company.toml. company.toml's `resolved_name` is
    documented in that file as informational and a tripwire — discovery resolves
    the real name from the SEC's own mapping and writes it to the inventory,
    which every later stage treats as the source of truth. Reading the config
    value here would let a hand-typed name reach a prompt.

    Cached because `build_prompt` runs once per unit (88 of them for MORN) and
    the answer cannot change inside one process.
    """
    return load_inventory()["company_name"]


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
              TASKS[task]["ask"].replace(COMPANY_TOKEN, company_name()), "",
              "Extract only from the document text above."]
    return "\n".join(parts)


def source_digest(sources: list[dict]) -> str:
    """A sha256 over the exact text a unit would be extracted from.

    The cache key for a result is a filename, and a filename does not know what
    it was computed from. Something has to record the input, or a cached answer
    silently outlives the document it answered.

    `source_chars` was that record, and it caught the real incident it was built
    for — one over-aggressive stripping rule shortened the input of 24 of 54
    investor_qa units. But a length is a weak fingerprint. These edits change the
    text and not the count, and each would leave the length check reporting
    "unchanged":

        - a boilerplate phrase swapped for one of the same length
        - two sections gathered in a different order
        - a section replaced by a same-length section from a different filing
        - any correction that substitutes rather than removes

    So the identity of each section is hashed alongside its text: a unit built
    from different filings is a different question even when the characters
    happen to total the same.
    """
    h = hashlib.sha256()
    for s in sources:
        h.update(f"{s['accession']}\x00{s['key']}\x00".encode("utf-8"))
        h.update(s["text"].encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


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
                             "Run `uv run python -m equity_research.triage_8k` first.")
                for group in gather_investor_qa(sections, tri, fy):
                    plan.append({"fy": fy, "task": task, "unit": group[0]["accession"],
                                 "sources": group,
                                 "chars": sum(len(s["text"]) for s in group),
                                 "sha": source_digest(group)})
                continue
            if task == "events_8k":
                sources = gather_8k(sections, inv, fy)
            elif task == "votes":
                sources = gather_votes(sections, inv, fy)
            else:
                sources = gather_plain(sections, fy, spec["sections"])
            plan.append({"fy": fy, "task": task, "unit": None, "sources": sources,
                         "chars": sum(len(s["text"]) for s in sources),
                         "sha": source_digest(sources)})
    return plan


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def out_path(fy: int, task: str, unit: str | None = None) -> Path:
    """Cache path for one unit of work.

    Per-filing tasks get the accession in the filename, so each is cached and
    retried on its own. The accession is filesystem-safe as filed (digits and
    hyphens), so it is used verbatim — a sanitized name could collide.

    THE MODEL IS NOT IN THIS KEY. READ THIS BEFORE RUNNING ANY A/B.
    ---------------------------------------------------------------
    (fiscal year, task, filing) identifies a unit of work. It does not identify
    which model answered it. So the same unit re-run on a different model lands
    on the SAME path and overwrites what is there.

    What is there is irreplaceable. `data/ledger/facts/` is committed precisely
    because a re-run buys *a* valid answer, not *the* answer the committed
    documents cite (CLAUDE.md rule 1). An A/B comparison that forgets this
    destroys the control arm it was measuring against, and `git checkout` is the
    only way back.

    Putting the model in the filename is NOT the fix: it would rename all 88
    committed records, orphan every one of them, and present a $11.33 re-run as
    a cache miss. The fix is that a comparison run writes somewhere else — decide
    where BEFORE the first call, not after.

    Switching a task's model in `[extraction.models]` is safe on its own, and
    deliberately does nothing to existing results: staleness keys on the source
    TEXT, not on the model, so a cached answer stays cached. `main` reports how
    many cached records were produced by a different model than the one now
    configured, so the no-op is visible rather than surprising.
    """
    if unit:
        return FACTS_DIR / f"FY{fy}_{task}_{unit}.json"
    return FACTS_DIR / f"FY{fy}_{task}.json"


def model_for_task(ex: dict, task: str) -> str:
    """Which model answers this task. `[extraction.models]`, else `[extraction] model`.

    One model for all eight tasks was the only option until now, and it is still
    the default and still what MORN uses. The knob exists because the tasks are
    not one job: `comp` and `mdna` are cross-year reading, while `votes` is
    transcription of numbers off a table.

    MEASURED BEFORE BEING OFFERED, so the knob is not mistaken for advice.
    From the usage records of the 88 committed extractions, Opus against Sonnet:

        investor_qa   54 calls   $6.81 -> $4.08     60% of extraction spend
        business       5 calls   $0.97 -> $0.58
        mdna           5 calls   $1.02 -> $0.61
        comp           5 calls   $0.88 -> $0.53
        events_8k      5 calls   $0.43 -> $0.26
        board          5 calls   $0.45 -> $0.27
        letter         4 calls   $0.45 -> $0.27
        votes          5 calls   $0.31 -> $0.18
        TOTAL         88 calls  $11.33 -> $6.80

    Nothing is switched, and the reasons are worth keeping next to the knob:

      - `investor_qa` is the only task where the saving is real money, and MORN's
        volume there is IDIOSYNCRATIC — it publishes written Reg FD answers to
        investor questions roughly monthly and most issuers never do. Strip it
        and a company is 34 calls and $4.52. So the $2.73 does not recur, and an
        A/B on MORN's Q&A would only describe MORN's Q&A.
      - `votes` + `board` is what the productionization plan proposed switching.
        It saves $0.31 a company and lands on the two weakest-audited fields:
        `votes` is the one task told to copy numbers exactly and NOTHING
        downstream re-checks a vote count against its 8-K, while `board` already
        holds 51 of the 54 low-confidence facts in the ledger.
      - What is left is `business`, `mdna`, `comp` and `letter` — $3.33 against
        $2.00. They are the product.

    THE TRIGGER FOR REVISITING: a company whose own task mix puts one task above
    roughly half of extraction spend. `--estimate` prints the per-model split, so
    the answer is in front of whoever is about to spend the money. Run the A/B
    against that company's material, not against MORN's.
    """
    return (ex.get("models") or {}).get(task) or ex["model"]


def check_model_config(ex: dict) -> None:
    """Reject a `[extraction.models]` table that cannot do what it says.

    Both failures below are silent by default, which is why they are checked
    eagerly rather than at the point of use:

      - a misspelled task (`vote` for `votes`) simply never matches, so the run
        proceeds on the default model while the config claims otherwise. Nobody
        would see it: the header would print the default and look correct.
      - an unknown model id reaches the backend, which fails per call after the
        run has started — or worse, prices through `settings.price_for` and
        raises during `--estimate` only.
    """
    overrides = ex.get("models") or {}
    problems = []

    for task in sorted(overrides):
        if task not in TASKS:
            problems.append(
                f"  [extraction.models] {task!r} is not a task. "
                f"Known tasks: {', '.join(sorted(TASKS))}")

    # Membership rather than catching price_for's SystemExit: the same answer,
    # but it collects every offender into one message instead of exiting on the
    # first, and it does not nest one FATAL inside another.
    priced = sorted(settings.MODEL_PRICES)
    for label, model in ([(f"[extraction.models] {t}", m)
                          for t, m in sorted(overrides.items())]
                         # The default is checked too: it is the model most tasks
                         # actually use, and an unpriced one there breaks
                         # --estimate for every task at once.
                         + [("[extraction] model", ex["model"])]):
        if model not in settings.MODEL_PRICES:
            problems.append(
                f"  {label} = {model!r} has no price recorded. "
                f"Priced models (as of {settings.PRICES_AS_OF}): "
                f"{', '.join(priced)}")

    if problems:
        sys.exit("FATAL: the extraction model configuration is not usable:\n"
                 + "\n".join(problems)
                 + "\n\nAdd a model to MODEL_PRICES in "
                   "src/equity_research/settings.py rather than hardcoding a "
                   "number at a call site.")


def run_one(backend: model_client.Backend, cfg: dict, unit: dict) -> dict:
    """One extraction call. Returns a record; never raises.

    Takes a Backend rather than an anthropic client, so the same code runs on a
    Claude seat (no API key) or through the SDK. Which one produced a record is
    stamped into it as `backend`, because once both have run, "what engine wrote
    this?" has to stay answerable from the file itself.
    """
    fy, task, uk = unit["fy"], unit["task"], unit.get("unit")
    ex = cfg["extraction"]
    prompt = build_prompt(task, fy, unit["sources"])
    started = datetime.now(timezone.utc)

    try:
        resp = backend.generate(
            model=model_for_task(ex, task),
            system=SYSTEM,
            prompt=prompt,
            max_tokens=ex["max_tokens"],
            effort=ex["effort"],
            schema=TASK_MODELS[task],
        )
    except Exception as exc:
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                # The id Anthropic support needs to trace a failed call on their
                # side. Present on API errors, absent on local ones (a connection
                # that never left, a response that failed schema validation), so
                # it is read defensively rather than assumed.
                "request_id": getattr(exc, "request_id", None)}

    # A structured response cut off by the output cap is a failed call, not a
    # short answer: the JSON is incomplete. Surface it rather than storing a
    # partial. Measured on both backends — `stop_reason` distinguishes this
    # reliably, which is what lets the rule survive the engine change.
    if resp.truncated:
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"hit max_tokens ({ex['max_tokens']}) — response truncated. "
                         "Raise max_tokens in config/company.toml [extraction]."}
    if resp.stop_reason == "refusal":
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": f"model declined: {resp.text[:200]}"}
    if resp.parsed is None:
        return {"fiscal_year": fy, "task": task, "unit": uk, "ok": False,
                "error": "backend returned no parsed output for a schema-constrained "
                         "call — this should be unreachable; treat as a bug."}

    return {
        "fiscal_year": fy,
        "task": task,
        "unit": uk,
        "ok": True,
        "extracted_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": resp.model,
        # Which engine produced this record. Added when the Claude Code backend
        # arrived: the 88 files committed before it have no `backend` key, and
        # their absence means "api", which is what tests/test_repo_hygiene.py
        # relies on to keep recognising them as paid model output.
        "backend": resp.backend,
        # WHICH CREDENTIAL PAID, which `backend` above does not say. "seat" means
        # the dollars anyone derives from `usage` below are NOTIONAL — what the
        # API would have charged, not what was billed. "api_key" means they are
        # real. The two came apart once: with ANTHROPIC_API_KEY inherited by the
        # CLI subprocess, a record stamped backend=claude_code could have been
        # billed to a key. `credentials_withheld` is the evidence that the
        # stripping happened rather than the assertion that it did.
        "billing": resp.billing,
        "credentials_withheld": list(resp.credentials_withheld),
        "effort": ex["effort"],
        "stop_reason": resp.stop_reason,
        # Kept whole rather than picking two keys: the claude_code backend
        # reports cache_creation/cache_read, which is where its real cost lives,
        # and dropping them would make its usage records unreadable.
        "usage": dict(resp.usage),
        # Which filing and section each fact could have come from. The ledger
        # builder re-reads these to verify quotes, so it must be exact.
        "sources": [{k: s[k] for k in s if k != "text"} for s in unit["sources"]],
        "source_chars": unit["chars"],
        # The fingerprint the staleness check prefers. `source_chars` is kept
        # beside it: it still reads usefully in a report, and records written
        # before this field existed are compared on length alone.
        "source_sha256": unit["sha"],
        "facts": resp.parsed.model_dump(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 4a — extract narrative facts via Claude.")
    ap.add_argument("--fy", type=int, action="append", help="only this fiscal year (repeatable)")
    ap.add_argument("--task", choices=sorted(TASKS), help="only this task")
    ap.add_argument("--estimate", action="store_true",
                    help="count tokens and print a cost estimate; make no extraction calls")
    ap.add_argument("--force", action="store_true",
                    help="re-run tasks that already have a cached result (costs tokens)")
    ap.add_argument("--refresh-stale", action="store_true",
                    help="re-run only those cached results whose source text has changed "
                         "since they were extracted (costs tokens)")
    ap.add_argument("--check-fresh", action="store_true",
                    help="report whether there is any extraction to do and exit. "
                         "Makes no model call; exit 0 if nothing is outstanding, "
                         "4 if something is.")
    add_ticker_arg(ap)

    args = ap.parse_args()

    cfg = load_config()
    sections, inv = load_sections(), load_inventory()
    tri = load_triage()
    years = args.fy or list(range(inv["first_fiscal_year"], inv["last_fiscal_year"] + 1))

    plan = plan_tasks(sections, inv, tri, sorted(years), args.task)

    # Report missing sources rather than silently producing fewer tasks.
    empty = [u for u in plan if not u["sources"]]
    plan = [u for u in plan if u["sources"]]

    # --- staleness ---------------------------------------------------------
    # "A completed task is never re-run" is only safe while its INPUT is
    # unchanged. Upstream text can move under a cached result — a config pattern
    # is corrected, a boilerplate rule is fixed — and the result then answers a
    # question about a document that no longer exists in that form.
    #
    # This is not hypothetical. Fixing one over-aggressive stripping rule changed
    # the input of 24 of 54 cached investor_qa results, all silently, because the
    # cache key is a filename and a filename does not know what it was computed
    # from. Comparing the stored fingerprint against the current source text
    # catches exactly that, for every task, at no cost.
    #
    # The fingerprint is `source_sha256` (see source_digest). Records written
    # before that field existed fall back to `source_chars`, which is weaker —
    # it cannot see a substitution that preserves length — but it is what those
    # records have, and silently treating them as fresh would be worse.
    stale, cached = [], []
    answered_by: dict[tuple, str | None] = {}
    if not args.force:
        for u in list(plan):
            p = out_path(u["fy"], u["task"], u.get("unit"))
            if not p.exists():
                continue
            plan.remove(u)
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                rec = {}
            was_sha = rec.get("source_sha256")
            was_chars = rec.get("source_chars")
            if was_sha is not None:
                is_stale, basis = was_sha != u["sha"], "hash"
            elif was_chars is not None:
                is_stale, basis = was_chars != u["chars"], "length"
            else:
                # Nothing recorded at all — no basis on which to claim staleness.
                is_stale, basis = False, "none"
            (stale if is_stale else cached).append((u, was_chars, basis))
            # Which model actually answered this unit, for the drift report
            # below. Records written before the field existed report None.
            answered_by[(u["fy"], u["task"], u.get("unit"))] = rec.get("model")
        if args.refresh_stale:
            plan += [u for u, _, _ in stale]

    ex = cfg["extraction"]
    check_model_config(ex)

    # Resolved before the header prints, so the header states the concurrency
    # and engine that will ACTUALLY be used. It previously printed
    # [extraction].max_concurrent_requests unconditionally, which would have
    # claimed 5 on a backend that paces at 2.
    llm_cfg = settings.load_config("llm", P=P)["llm"]
    backend = model_client.get_backend(llm_cfg, stage="extract_facts")
    workers = int(ex["max_concurrent_requests"])
    if backend.name == "claude_code":
        # A seat meters on rolling usage windows rather than per-second rate
        # limits, so the seat path paces slower. Lower of the two wins, so
        # neither config can accidentally raise the other.
        workers = min(workers, int(llm_cfg.get("llm", {}).get(
            "max_concurrent_requests", 2)))
    workers = max(1, workers)

    print(f"Fact extraction — {ex['model']}, effort={ex['effort']}, "
          f"max_tokens={ex['max_tokens']}, concurrency={workers}, "
          f"backend={backend.name}")
    # Named per task rather than folded into the line above. A header that
    # printed only the default would be actively misleading on a mixed run, and
    # this is the line someone reads to check that a switch took effect.
    overrides = {t: m for t, m in sorted((ex.get("models") or {}).items())
                 if m != ex["model"]}
    if overrides:
        print("  model overrides : "
              + ", ".join(f"{t} -> {m}" for t, m in overrides.items()))
    print(f"  years           : {', '.join(f'FY{y}' for y in sorted(years))}")
    print(f"  tasks to run    : {len(plan)}")
    print(f"  already cached  : {len(cached)}" + ("  (use --force to redo)" if cached else ""))

    # A model switch deliberately does NOT invalidate a cached result: staleness
    # keys on the source text, so the answer stays cached and no money is spent.
    # Correct, and surprising enough to be worth stating — otherwise someone
    # switches a task, sees "already cached: 88", and concludes the config is
    # being ignored. Records written before the `model` field existed report
    # None and are not counted as drift, because nothing is known about them.
    drifted: dict[tuple[str, str], int] = {}
    for u, _, _ in cached:
        was = answered_by.get((u["fy"], u["task"], u.get("unit")))
        now = model_for_task(ex, u["task"])
        if was and was != now:
            drifted[(was, now)] = drifted.get((was, now), 0) + 1
    if drifted:
        total = sum(drifted.values())
        print(f"  different model : {total} cached result(s) were produced by a "
              f"model other than the one now configured")
        for (was, now), n in sorted(drifted.items()):
            print(f"      {n:>3d} answered by {was}, now configured as {now}")
        print("      Left alone on purpose — a cached answer is not wrong "
              "because the config changed.")
        print("      Re-running them costs tokens: --force, and read "
              "`out_path` first about where the output lands.")
    if empty:
        print(f"  no source       : {len(empty)}")
        for u in empty:
            print(f"      FY{u['fy']} {u['task']}"
                  + (f" [{u['unit']}]" if u.get("unit") else "")
                  + ": no section text found")
    if stale:
        print()
        print(f"  *** {len(stale)} CACHED RESULT(S) ARE STALE — their source text has changed "
              f"since extraction ***")
        for u, was, basis in sorted(stale, key=lambda t: (t[0]["fy"], t[0].get("unit") or "")):
            where = (f"      FY{u['fy']} {u['task']}"
                     + (f" [{u['unit']}]" if u.get("unit") else "") + ": ")
            if was is None:
                print(where + f"source text has changed (detected by {basis})")
            elif was == u["chars"]:
                # Only the hash can see this one, and it is the case the length
                # check was blind to: a substitution, a reordering, or a swap
                # for different text of the same size.
                print(where + f"content changed with NO change in length "
                              f"({u['chars']:,d} chars) — caught by the source hash")
            else:
                print(where + f"extracted against {was:,d} chars, source is now "
                              f"{u['chars']:,d} ({u['chars'] - was:+,d})")
        if not args.refresh_stale:
            print()
            print("  These were NOT re-run. A stale result answers a question about a "
                  "document that no longer exists in that form.")
            print("  Re-run them with:  --refresh-stale   (costs tokens)")
    print()

    # --- is there anything to do? ------------------------------------------
    # Answered with an exit code so the Phase 4 cost gate does not have to read
    # this stage's prose to find out. Above the `not plan` return below, so the
    # question is always answered rather than only when there is work.
    #
    # 4, not 1: nothing has failed. And stale-but-not-refreshed counts as
    # outstanding, because the run below would exit non-zero over it — a gate
    # told "nothing to do" and then handed a failure would be worse than one
    # told to look.
    if args.check_fresh:
        if plan:
            print(f"{len(plan)} task(s) outstanding.")
        elif stale and not args.refresh_stale:
            print(f"{len(stale)} cached result(s) are stale and were not "
                  f"rebuilt; --refresh-stale would cost tokens.")
        else:
            print("nothing to do.")
        sys.exit(4 if (plan or (stale and not args.refresh_stale)) else 0)

    if not plan:
        if stale and not args.refresh_stale:
            # Not "nothing to do": there is something to do and it costs money.
            sys.exit(f"{len(stale)} stale result(s) left in place. "
                     "Nothing was run. Pass --refresh-stale to rebuild them.")
        print("nothing to do.")
        return

    # --- estimate ----------------------------------------------------------
    # Exact where the backend can count, approximate where it cannot. Output
    # tokens cannot be counted in advance on either, so they are bounded by
    # max_tokens — a deliberate over-estimate, clearly labelled.
    if args.estimate:
        # Accumulated PER MODEL, not in one total. A mixed run priced at one
        # model's rates is wrong in whichever direction the mix goes, and the
        # comment that used to sit on `price_for` below predicted exactly this:
        # "a switch to Sonnet for some tasks would have left this estimate
        # quietly quoting Opus rates". Grouping is what makes that impossible
        # rather than merely noted.
        per_model: dict[str, dict[str, int]] = {}
        exact = True
        for u in plan:
            model = model_for_task(ex, u["task"])
            prompt = build_prompt(u["task"], u["fy"], u["sources"])
            n = backend.count_tokens(model=model, system=SYSTEM, prompt=prompt)
            if n is None:
                # The claude_code backend has no count-tokens endpoint. Fall back
                # to the calibrated ratio and say so, rather than printing a
                # number that looks measured.
                exact = False
                n = settings.estimate_tokens(prompt)
            bucket = per_model.setdefault(model, {"calls": 0, "tokens": 0})
            bucket["calls"] += 1
            bucket["tokens"] += n
            label = u['task'] + (f" {u['unit']}" if u.get('unit') else '')
            print(f"  FY{u['fy']} {label:34s} {u['chars']:>9,d} chars  "
                  f"{'' if exact else '~'}{n:>8,d} tokens")

        print()
        # HOW THE BACKEND CHARGES FOR ONE SEND OF AN UNSHARED PROMPT.
        #
        # This used to be `price.input`, flat — i.e. 1.0x — and that was wrong for
        # the default backend by a factor of two. The Claude Code CLI cache-WRITES
        # the whole prompt every call with no opt-out, at a 1-hour TTL, which
        # costs 2.0x input. MSFT's extraction estimate printed $3.24 of input
        # against a measured ~$7.13 (2026-09-02). Nothing was misreported as safe
        # — the run still landed inside the printed $3.24-$19.64 band — but the
        # headline figure is the one someone approves at the cost gate, so half
        # the truth is not good enough.
        #
        # Asked of the BACKEND rather than branched on its name: the backend knows
        # how it charges, and a name check here would have to be repeated wherever
        # else an estimate is printed. Defaults keep a third-party backend working.
        mult = getattr(backend, "unshared_input_multiplier", 1.0)
        scaffold = getattr(backend, "scaffolding_tokens", 0)

        low = high = 0.0
        for model, b in sorted(per_model.items()):
            # Priced via the one table in settings.py. PRICE_IN/PRICE_OUT were
            # once module constants of 5.00/25.00 here and again in
            # generate_outputs.py, so a price change had to be made twice.
            price = settings.price_for(model)
            worst_out = b["calls"] * ex["max_tokens"]
            in_cost = b["tokens"] / 1e6 * price.input * mult
            # Scaffolding is READ on every call (0.1x); the single cold WRITE is
            # added once below rather than per model, because it happens once per
            # run whatever the mix.
            scaffold_cost = (b["calls"] * scaffold / 1e6 * price.input
                             * settings.CACHE_READ_MULTIPLIER)
            out_cost = worst_out / 1e6 * price.output
            low += in_cost + scaffold_cost
            high += in_cost + scaffold_cost + out_cost
            head = f"{model} x{b['calls']}"
            print(f"  {head:34s} {b['tokens']:>9,d} in  ->  ${in_cost:,.2f}"
                  f"   + at most ${out_cost:,.2f} out")
            if scaffold:
                print(f"  {'':34s} {b['calls'] * scaffold:>9,d} "
                      f"{backend.name} scaffolding, read at "
                      f"{settings.CACHE_READ_MULTIPLIER:g}x  ->  "
                      f"${scaffold_cost:,.2f}")
        if scaffold:
            # One cold write per run: the first call finds the cache empty.
            cold = (scaffold / 1e6
                    * settings.price_for(ex["model"]).input * mult)
            low += cold
            high += cold
            print(f"  {'first call writes the scaffolding':34s} "
                  f"{scaffold:>9,d} at {mult:g}x  ->  ${cold:,.2f}")
        # Printed even when there is only one model, so the per-model line and
        # the total always agree and neither has to be trusted alone.
        print(f"\ntotal   : ${low:,.2f} to ${high:,.2f}"
              f"   ({len(plan)} call(s) across {len(per_model)} model(s))")
        if mult != 1.0:
            print(f"input is priced at {mult:g}x because {backend.name} "
                  f"cache-writes every prompt at a {backend.cache_ttl} TTL; a "
                  f"single-use prompt never earns that back.")
        print(f"output is bounded by max_tokens x calls, which is a deliberate "
              f"over-estimate — it cannot be counted in advance on either backend.")
        print(f"\nestimate only — no extraction calls were made. "
              f"Prices as of {settings.PRICES_AS_OF}.")
        if not exact:
            print(f"Token counts are ESTIMATED ({backend.name} cannot count "
                  f"exactly); dollars are what the API would charge, not what a "
                  f"seat is billed.")
        return

    # --- run ---------------------------------------------------------------
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    done, failed = 0, []
    # Each result is written the moment it arrives, so a crash costs only the
    # tasks in flight (CLAUDE.md: save incrementally, per file).
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, backend, cfg, u): u for u in plan}
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
