*Scoping response recorded 2026-08-26. Nothing was built.*

*Updated 2026-09-01: **6.1 is done** (`bbad3d5`) and **decision 1 is made — the
company is Microsoft, MSFT, over FY2020–FY2025**. See "6.2 decided" at the foot of
this file for what was measured before accepting it, including a correction to a
claim about the shard loop that I committed earlier the same day and that the first
real run contradicted. Decision 3 is answered by the same measurement; decisions 2
and 4 remain open.*

---

I read `discover.fetch_all_filings`, `triage_8k.strip_boilerplate`, the fiscal-year
arithmetic in `discover`, `config/sections.toml`, `config/forms.toml`, the empty-input
branches in `verify_outputs`, and MORN's own inventory and fetch manifest, rather
than working from the plan. The plan and `PHASE5_SCOPE.md` both describe Phase 6 as
one thing — run a second real company — and that is right about the shape and
wrong about two of the numbers. It is also incomplete: **part of Phase 6's risk can
be retired for $0 before any company is chosen**, and that part should go first.

---

# Phase 6 scope: the paths only a real run exercises

## What Phase 6 is

Next Steps 27 and 29, which Phase 5 deliberately deferred here:

- **27** — `--yes` against a genuinely stale document. Declining the cost gate was
  proven four ways (closed stdin, `n`, `maybe`, `--skip-spending`) and all four
  stop the chain having spent nothing. The **approving** path ends in a real
  generation call and is covered only by injecting a fake gate into `run_chain`.
  "The gate approves correctly" is an untested claim.
- **29** — a first run for a **new** company. Every `pipeline MORN` run in Phase 4
  reported `sec_requests_made: 0`; the cache holds, exactly as CLAUDE.md requires.
  The opposite case has never been exercised.

Plus the productionization plan's own final verification, which has never been run
end to end: a clean checkout, `uv sync`, and a full pipeline from nothing.

## Correcting my own estimate first

`PHASE5_SCOPE.md` put this at **~$18–20**. That number is MORN's own bill
($11.33 extraction + $7.21 generation = $18.54) and it is the wrong reference for
almost any other company, for the reason the 5.3 measurement established:
`investor_qa` is 54 of MORN's 88 calls and $6.81 of its $11.33, and MORN's monthly
written Reg FD Q&A is idiosyncratic. Strip it and extraction is **34 calls and
$4.52**.

Generation scales with the pack, and MORN's pack is dense: 352,206 tokens for five
years, ~70K per fiscal year, against the plan's ~26K/year estimate for a typical
issuer. MORN's $7.21 also includes a **$2.22 cache-expiry loss** that `cache_ttl =
"1h"` now prevents.

So a typical issuer at five years is nearer **$6–10 all in**, and the honest answer
is that `pipeline estimate <TICKER>` prints the real figure before anything is
spent — which is the whole point of having built it. Budget **$15** to cover the
re-runs that boundary fixes will force (see 6.4), and expect to spend less.

## Eight code paths MORN has never exercised

This is the actual content of Phase 6. Each is real code, written and documented,
that has never executed — several of them guarding against failures the docstrings
name explicitly.

| # | Path | Why MORN never reached it |
|---|---|---|
| 1 | `fetch_all_filings`'s **shard loop** | MORN's recent-1000 index reaches back to **2019-07-26**, past the 2021 window start, so the loop breaks before its first fetch. No shard file exists in the cache. Its docstring: *"Fetching only the main file is a silent-truncation bug: the early years of the window would just appear to have no filings."* |
| 2 | **Non-December fiscal year end** | MORN's is `12-31`. `fy_end_date`, `fy_start_date`, `fy_from_period` and `assign_fiscal_year` are written generically and **no test covers a non-calendar FYE**. A June filer labels its fiscal years differently and an off-by-one here mislabels every downstream artifact. |
| 3 | **EDGAR under sustained load** | ~200 documents at `request_delay_seconds = 0.15`. Never run in one go by anyone watching. |
| 4 | Section boundaries against **a different filing agent** | Every pattern in `sections.toml` was calibrated on MORN's filings. CLAUDE.md already assumes the 2021 and 2025 formatting differ *for the same company*. |
| 5 | `strip_boilerplate`'s **conservative fallback** | `forward_looking_end` is `Item 9.01\|Investor Questions\|\b1\.\s+[A-Z]` — the second and third alternatives are MORN's Q&A heading and its numbered-question convention. On MORN one always matches now. |
| 6 | The letter's **uniqueness assumption** | The salutation and sign-off patterns were *"verified to match EXACTLY ONCE in each of the four documents"* — MORN's four. A company with a chairman's letter *and* a CEO's letter breaks that. |
| 7 | The cost gate's **approving** path | Item 27. |
| 8 | `pipeline init` followed by **a real run** | `init` was proven with `ZZZTEST`, which was then deleted. `resolve_ticker`'s two-company behaviour was proven with a throwaway. Neither has been followed by an actual pipeline. |

Two of these are **cost** risks rather than correctness risks, and knowing which is
which decides how much to worry. Path 5's fallback is *right*: when it cannot
locate the end of the caution block it does not strip at all, so an unrecognised
layout costs a few cents in duplicated boilerplate instead of deleting content —
which is what it did to eleven MORN filings before the fix. Path 4 is the opposite:
an over-captured section *looks* like a successful extraction and quietly costs a
fortune in tokens downstream.

---

## The items

### 6.1 — Retire the fiscal-year risk for $0, before choosing a company

Path 2 above needs no company, no EDGAR request and no model call. It is pure
arithmetic over a synthetic fiscal-year end, and it is the one item where being
wrong is both **likely** and **invisible**: a June filer's "FY2024" is not a
calendar year, and if the mapping is off by one, every artifact downstream is
mislabelled consistently — the ledger, the timeline, the citations, the coverage
claims. Nothing would look broken. This is exactly CLAUDE.md's "guard edge cases in
code, not just prose".

Scope: unit tests for `fy_end_date`, `fy_start_date`, `fy_from_period` and
`assign_fiscal_year` against several fiscal-year ends — 12-31 (the case that
works), 06-30, 09-30, 01-31, and 02-29 for the leap guard already written. Assert
the properties rather than golden values: fiscal years tile the calendar with no
gap and no overlap, `fy_start_date(fy)` is the day after `fy_end_date(fy-1)`, a
report date one day outside the tolerance is rejected, and a 10-K's period maps to
the fiscal year it *describes*.

Do this first. If it finds something, it is far cheaper to find it here than in a
ledger that already cost money.

**Effort:** 1 commit, 2–3 h. **Spend: $0.**

### 6.2 — Choose the company (a decision, not a task)

This blocks 6.3 onward, and the choice determines what Phase 6 actually tests.
Criteria, in the order I would weight them:

- **A non-December fiscal year end**, to exercise path 2 for real after 6.1 has
  pinned it in unit tests. This is the single most informative property.
- **A different filing agent from MORN's**, to exercise path 4. Visible from the
  filing HTML before committing to it.
- **High enough filing volume that the 1,000-filing index does not reach back five
  years**, to exercise path 1. A large board with many Form 4 filers does it.
- **Publishes a shareholder letter**, so path 6 is exercised rather than skipped.
- **No written Reg FD investor Q&A**, which is the normal case and keeps the bill
  near the $6–10 estimate. It also means `investor_qa` is empty for the first time,
  which is its own test — the empty-input branches in `verify_outputs` are written
  (`if first_qa is None: ... True, "no investor_qa facts cited"`) and have never
  fired.

A company satisfying the first three is worth more than a familiar one. The
temptation is to pick a company whose story is known so the output can be judged —
see 6.6 for why that is worth resisting, and what to do instead.

### 6.3 — The watched first run: `init`, `discover`, `fetch`

The first three stages, run deliberately and watched rather than left alone.

What to watch for, in order of how quietly it fails:

1. **Did the shard loop run?** Compare `index_earliest_filing` against
   `window_start_date` in the new inventory. If the earliest indexed filing is
   *after* the window start and no shard was fetched, the early years are silently
   empty — path 1's exact failure. A shard file appearing in
   `data/raw/_meta/` is the positive signal.
2. **Request count and pacing.** `sec_requests_made` in the run log, against the
   number of documents in the fetch manifest. Any 403 means the User-Agent was
   rejected; any 429 means the delay is too aggressive for sustained load, which is
   the thing 0.15 s has never been tested at.
3. **Counts reconciling across the two seams** (CLAUDE.md rule 5): filings indexed
   → filings in window → filings fetched → documents fetched. MORN's are 1,000 →
   712 → 127 → 202, and the 712 → 127 narrowing is the form filter doing its job.
   A number that does not account for its own difference is a defect.
4. **Fiscal-year assignment**, read by eye off `discovery-report.md`. This is where
   6.1's unit tests meet a real filer.

**Effort:** ~1 h of running, plus whatever it finds. **Spend: $0** — no model
calls in these three stages.

### 6.4 — Sections against a different filing agent, and the loop this creates

The stage with the most unpredictable outcome, and the reason Phase 6's schedule
cannot be promised.

`extract_sections` validates every boundary — a character floor, a word floor, a
ceiling, and anchor phrases — and logs failures loudly. So the *failure mode is
visible*, which is the good news. The bad news is that fixing a boundary means
editing patterns and re-running, and there are ten section keys across two forms
and five years.

**Expect the two known-weak sections to be worse.** `DEF14A_director_bios` is
already wrong on MORN's FY2025 (it starts at the front-of-proxy voting summary),
and `DEF14A_proposals_and_votes` over-captures in four of MORN's five years. Those
are the two whose patterns are most dependent on proxy house style.

**The rule to hold to here:** a pattern fix goes in `companies/<TICKER>/overrides/
sections.toml`, not in the global `config/sections.toml`, unless it is genuinely
more correct for every company. The override mechanism exists and has never been
used — arrays replace wholesale on merge, deliberately, because pattern *order* is
load-bearing. First real use of that path is itself a Phase 6 test.

**Effort:** unbounded in principle; **1–2 days is the honest estimate**, dominated
by reading extracted text to decide whether a boundary is right. **Spend: $0.**

### 6.5 — The spending stages, and the gate's approving path

Only reached once 6.4's boundaries are trusted, because extraction is priced per
character of source text and a 200,000-character over-capture is the expensive
mistake this project keeps guarding against.

Order, and the reason for it:

1. `pipeline estimate <TICKER>` **before** anything. It now prints a per-model
   split and labels its token counts as estimated. This is the number to compare
   the eventual bill against.
2. `extract_facts` through the cost gate, answering **yes** — the first time that
   path has run for real (item 27's first half). Watch that `--check-fresh` reports
   work outstanding, that the estimate matches step 1, and that the prompt appears
   at all.
3. `build_ledger`, and read the quote-verification census. MORN's is 1,326/1,326.
   A materially worse rate on the new company points at 6.4, not at the model.
4. `generate_outputs` through the gate. This is item 27's real target: a genuinely
   missing document rather than a stale one, which is the same code path.

**One thing to decide before starting:** whether to run the `investor_qa` A/B here
if the chosen company happens to publish Q&A. 5.3 recorded the trigger — one task
above roughly half of extraction spend — and the cache-key hazard that must be
settled *before the first call*: `out_path` is keyed on (fiscal year, task, filing)
with no model in it, so a comparison run overwrites its own control arm. If the A/B
is wanted, the side-output location is a design decision, not an afterthought.

**Effort:** 1–2 h of running. **Spend: the estimate from step 1**, expected $6–10.

### 6.6 — Judging deliverables for a company nobody in the room knows

The part with no mechanical answer, and worth being explicit about rather than
discovering at the end.

MORN's outputs were judged by someone who knows the company — DATA.md records that
as both an asset and a bias risk. For a new company that check is gone. What
remains is exactly what the pipeline was built to provide, and it is not nothing:
14 hard checks per document, a quote census against the cached filings, every
citation resolving, and figures traced to a cited fact's quote rather than its
claim.

**What those checks cannot tell you** is whether the narrative is *the* narrative —
whether the brief picked the three things that mattered or three things that were
merely well-documented. The honest procedure is to read the deliverables against
the filings for one fiscal year, chosen at random rather than chosen as the
interesting one, and record the disagreements in `VERIFICATION.md` alongside
MORN's. A finding of "the checks all pass and the brief is thin" is a real and
useful result for a productionization phase.

**Effort:** 2–3 h. **Spend: $0**, unless it prompts a re-generation.

### 6.7 — The clean-checkout run, which is the plan's actual final gate

Never done. Fresh clone, `uv sync`, `git config core.hooksPath .githooks`, restore
the untracked cached filings from a copy, then `pipeline <TICKER> --yes` for both
companies. Everything should no-op or rebuild deterministically, verify green, PDFs
render with read-back verification.

This is also the first honest test of the 5.5 README, since it is the only run
that follows it from step 1 without knowing the answers.

**Effort:** 1–2 h. **Spend: $0** if the caches are restored; the whole bill again
if they are not, which is why the restore step is explicit.

---

## Totals

| | commits | time | spend |
|---|---:|---:|---:|
| 6.1 fiscal-year unit tests | 1 | 2–3 h | $0 |
| 6.2 choose the company | — | a decision | — |
| 6.3 watched first run | 0–1 | 1 h + findings | $0 |
| 6.4 sections on a new agent | 1–3 | **1–2 days** | $0 |
| 6.5 the spending stages | 1 | 1–2 h | **$6–10** |
| 6.6 judging the deliverables | 1 | 2–3 h | $0 |
| 6.7 clean-checkout run | 0–1 | 1–2 h | $0 |
| **Phase 6** | **4–8** | **2–3 days** | **$6–10, budget $15** |

The shape differs from Phases 4 and 5: most of the *time* is in one item (6.4) and
all of the *money* is in another (6.5), and 6.4 has to succeed before 6.5 is safe
to start. Unlike Phase 5, the schedule genuinely cannot be promised, because the
work is responding to what another company's filings turn out to look like.

## Gates

1. 6.1's tests pass, and they fail against a deliberately broken fiscal-year
   mapping (rule 3).
2. The new company's counts reconcile across all four seams, with the shard
   question answered explicitly either way.
3. Every section either validates or is a *recorded, understood* failure — not a
   silent one. Over-capture is the case to hunt, because it looks like success.
4. `pipeline estimate` before spending, and the eventual bill accounted for against
   it.
5. Both deliverables pass all 14 hard checks, and the quote census is stated.
6. `pipeline <TICKER> --yes` twice in a row leaves `git status` clean — the same
   gate 5.2 automated for MORN, now for a company whose artifacts were written by
   this code rather than by an earlier version of it.
7. A clean checkout, followed from the README, reaches a green verify.

## Four decisions

**1. Which company.** The criteria are in 6.2, and the first three matter more than
familiarity. I would rather test a June-FYE, high-volume, different-agent filer
badly understood than a December-FYE peer understood well — but 6.6 is the cost of
that choice and it should be a deliberate one.

**2. Whether MORN's config becomes the global default or moves to an override.**
Right now `config/*.toml` *is* MORN's calibration, described as global defaults. The
moment a second company needs different patterns there are two defensible answers:
put the new company's deltas in its `overrides/` and leave the globals alone, or
demote the MORN-specific values into `companies/MORN/overrides/` and make the
globals genuinely neutral. The second is more honest and is a bigger change. It
does not need deciding until 6.4 produces the first real conflict, but it should
not be decided *by accident* at that moment.

**3. Whether the `investor_qa` A/B runs here.** Only if the chosen company has the
volume; the cache-key hazard needs settling before the first call either way.

**4. Whether item 13 is in scope.** I would say no — see below — but it is the
highest-value item remaining and it should be a decision rather than a drift.

## Item 13, and why it is not in this phase

**The model-family gap.** The verification suite asks for a different model family
on the independent passes; the same family reviewed and then repaired its own work,
and the blind clean-room diff of the analytical core was never run.

Phase 3 made this harder rather than easier: the default backend is a Claude seat,
so a non-Anthropic reviewer is not reachable through the seam at all and would need
separate access that the operating assumption — no API keys — says colleagues do
not have.

It is therefore not a task this phase can absorb; it needs access this project does
not currently have. Everything in Phase 6 makes the pipeline more *trustworthy in
operation* — a second company proves the code generalizes past its calibration
subject. None of it substitutes for an independent review of the analysis itself,
and that remains the first thing to close if any deliverable becomes load-bearing.

---

# 6.2 decided — Microsoft (MSFT), FY2020–FY2025

*Recorded 2026-09-01. The company was chosen by the user; the window was chosen
from the measurement in finding 2. What follows is what was established before
spending anything, and the three places it changes the plan above. All of it came
from read-only EDGAR metadata plus one discovery run — no document fetch, no model
call, $0.*

## The scorecard, measured rather than assumed

| 6.2 criterion | MSFT | Verdict |
|---|---|---|
| Non-December fiscal year end | `fiscalYearEnd` = `0630` | **Yes.** FY2020–FY2025 is Jul 2019 – Jun 2025 |
| Different filing agent | three prefixes: `0001564590` (FY20–22), `0000950170` (FY23–25), `0001193125` (8-Ks) vs MORN's dominant `0001289419` | **Better than asked.** The agent *changes mid-window*, so `sections.toml` meets two house styles inside one company |
| Volume defeats the 1,000-filing index | recent index reaches 2020-04-30 | **Yes, but only at a six-year window.** This decided the window — see finding 2 |
| Publishes a shareholder letter | ARS filed for FY2023, FY2024, FY2025 — **not** FY2020, FY2021 or FY2022 | **Partly**, and the gap is itself a test |
| No written Reg FD investor Q&A | none | **Yes.** `investor_qa` will be empty for the first time |

Counts: **3,001 filings indexed → 72 in scope and inside the FY2020–FY2025
window**, against MORN's 127 over five years. Fewer filings, larger ones.

## Three findings that change the plan above

### 1. 6.1 was not merely prudent — it was load-bearing, and this proves it

The rule 6.1 replaced was `filing_date.year - 1`. Run against MSFT's real proxies:

```
filed 2020-10-19  DEF 14A   old FY2019   new FY2020    <-- wrong by one year
filed 2021-10-14  DEF 14A   old FY2020   new FY2021    <-- wrong by one year
filed 2022-10-27  DEF 14A   old FY2021   new FY2022    <-- wrong by one year
filed 2023-10-19  DEF 14A   old FY2022   new FY2023    <-- wrong by one year
filed 2024-10-24  DEF 14A   old FY2023   new FY2024    <-- wrong by one year
filed 2025-10-21  DEF 14A   old FY2024   new FY2025    <-- wrong by one year
```

**15 of 15 proxies, DEF 14A and DEFA14A alike, moved by exactly one year.** Every
`comp` fact, every `board` fact and every proxy-sourced priority would have been
attributed to the wrong fiscal year — consistently, so nothing would have looked
broken — and the error would have been baked into a committed ledger that cost
real money before anyone read it. The scope above argued 6.1 should go first on
the grounds that the failure is "silent, consistent and invisible". That was a
prediction; this is the measurement.

### 2. The shard loop was not exercised at five years, and that chose the window

**This corrects my own claim, made and committed earlier the same day (`6a8716e`)
before the first real run contradicted it.** Recorded rather than quietly fixed,
because the mistake is instructive and the reasoning that replaced it is not
written down anywhere else.

I probed the shard question with `need_back_to = window_start − filing_date_
padding_days` and concluded the loop runs for MSFT. It does not. `discover` calls
`fetch_all_filings(client, cik, window_start)` with the **unpadded** window start
(`discover.py:637`), and the first real discovery run settled it: `sec_requests_
made: 2`, no shard on disk, `index_total_filings: 1001`, index reaching 2020-04-30
against a window starting 2020-07-01 — the loop broke before its first fetch,
exactly as it always has for MORN.

**The unpadded value is correct, and the asymmetry is the part worth keeping:** no
filing filed before the window start can be assigned a fiscal year *inside* the
window. A 10-K is dated by its period, which precedes its filing; a proxy by
`most_recent_completed_fy`, which is at most `first_fy - 1`; an 8-K by
`fy_containing(filing_date)`. So padding the *early* end could only ever fetch
shards whose every contribution is dropped. The padding exists for the *late* end,
where a 10-K lands 30–90 days after its year closes. Nothing said so, which is how
a plausible-looking probe got it backwards.

**So the window became a decision, and it was measured across every start year:**

```
          window   win start  loop  shards    idx  in-scope in window  from shard
   FY2020-FY2025  2019-07-01   ran       1   3001            72 (6y)           5
   FY2021-FY2025  2020-07-01  idle       0   1001            59 (5y)           0
   FY2022-FY2025  2021-07-01  idle       0   1001            41 (4y)           0
```

**FY2020–FY2025 was chosen.** Five of FY2020's thirteen in-scope filings exist only
in the shard: a 5.02 director change (2019-09-19), the FY2019 annual-meeting vote
results (2019-12-05), and three more. So a silent truncation would leave FY2020
visibly short of its own vote results rather than failing invisibly — which is the
difference between *executing* path 1 and *testing* it. Cost of the sixth year:
72 in-scope filings against 59, roughly +22%.

A five-year window would have left path 1 in the same never-executed state Phase 6
was written to clear, while a green discovery report said nothing was wrong —
because nothing was wrong. **The check 6.3 proposes (earliest indexed filing vs
window start) is right and would have passed; passing is not the same as covering.**

### 3. The window is bounded by disclosure, not by the calendar

On 2026-09-01 the most recently *completed* fiscal year is **FY2026** (closed
2026-06-30), and its 10-K was filed 2026-07-29. Its **proxy has not been filed** —
MSFT files in mid-October. FY2026 is therefore a half year to this pipeline:
`comp`, `board` and `votes` all read the proxy, and the brief's most valuable
comparison has nothing on the second side of it.

A December filer cannot show you this. Its proxy lands in April, so by the time
anyone runs a pipeline the newest completed year is fully disclosed. **A June filer
has a ~3.5-month window each year — late July to mid-October — in which the newest
fiscal year has a 10-K and no proxy, and we are sitting inside it.**

Hence the window **ends** at FY2025 — the start is finding 2's business. Both
halves of the decision are recorded in `companies/MSFT/company.toml` as well as
here, because that is the file whoever re-runs this will read. **A question for
6.3:** if someone set
`last_fiscal_year = 2026`, does discovery flag the missing proxy loudly, or does
it report a fiscal year that is quietly short one form? The gap-reporting code
exists; which way it falls has never been observed.

## Decision 3, answered

**No `investor_qa` A/B in this phase.** The trigger 5.3 recorded is one task
exceeding roughly half of extraction spend, and that was a fact about MORN's
filing habits. MSFT publishes no written Reg FD Q&A, so the task that would be
compared has no volume to compare. The cache-key hazard is unchanged and still
needs settling before any future A/B; nothing here spends against it.

## What this does to the cost estimate

The $6–10 in the table above assumed a typical issuer, and MSFT is not typical in
the direction that matters: **72 in-scope filings over six years against MORN's
127 over five, but a 10-K and a proxy several times the length.** Call count falls,
per-call input rises, the sixth year adds ~22%, and none of that obviously cancels.
No number is asserted here — `pipeline estimate MSFT` prints the real one after
6.4, from this company's own section lengths, and that is the figure to compare the
bill against. The $15 budget stands.

## Scaffolded

`pipeline init MSFT` ran clean and its two-company warning fired — the first time
`resolve_ticker`'s "pass `--ticker` or set `EQR_TICKER`" path has appeared for a
real second company rather than a throwaway. `companies/MSFT/company.toml` is
filled in: ticker, the window with its reasoning, and `fiscal_year_end_month_day
= "06-30"` as a tripwire. `cik` and `resolved_name` are **deliberately empty** —
discovery resolves them, and the probe confirming MSFT matches exactly one row in
`company_tickers.json` is recorded as provenance rather than typed in as a value.

Checked, not assumed: the file parses; `[extraction.models]` is still last in
`[extraction]` and still empty; the suite is **484 checks, unchanged** with a
second company present — the Phase 5.1 aggregation holding against exactly the
drift that bit Phase 4.6; and `git add --dry-run` confirms `data/pack/gen-*.json`
would be tracked for MSFT while `pack.json` is ignored, matching MORN, so rule 1's
enforcement generalizes to a new company.

---

# 6.5 — the spending stages

## Finding 4: the orchestrator cannot fetch the final year's vote 8-K

**This is the sharpest thing Phase 6 has found, because MORN looks complete and
is not — it was completed by hand.**

`extract_facts --check-fresh` reported `no source: 4` before the gate was
approved, and three of the four were expected (see below). The fourth, **FY2025
`votes`**, contradicted the disk: six proxy vote sections were sitting in
`data/sections/`. Both statements could not be true.

**What `votes` actually reads is not the proxy.** It reads the paired **8-K Item
5.07**. A DEF 14A for year N is filed months after that year closes and solicits
votes at the meeting that follows, so the *result* is a filing dated roughly a
year after the year it reports on. `gather_votes` therefore pairs on the
**proxy's filing date** and takes the first 5.07 filed after it — deliberately,
because pairing on the fiscal-year label would attach every vote to the wrong
year. That logic is correct, and it resolved all six MSFT years:

| fiscal year | proxy filed | paired 5.07 | section on disk |
|---|---|---|---|
| FY2020 | 2020-10-19 | 2020-12-04 | yes |
| FY2021 | 2021-10-14 | 2021-11-30 | yes |
| FY2022 | 2022-10-27 | 2022-12-16 | yes |
| FY2023 | 2023-10-19 | 2023-12-08 | yes |
| FY2024 | 2024-10-24 | 2024-12-11 | yes |
| **FY2025** | 2025-10-21 | **2025-12-08** | **no** |

The last one is `0001193125-25-311196`: filed 2025-12-08, labelled **FY2026**,
`in_window: false`. `fetch` builds its work list from `in_window` filings only
(`fetch.py:271`), so it was never downloaded and the section never existed.

**Why this is a pipeline gap and not a property of where the window was cut.**
MORN's structurally identical filing — `0001289419-26-000028`, also FY2026, also
`in_window: false`, also items 5.02 + 5.07 — **is** in MORN's cache, and MORN
shipped all five `votes` records including FY2025. It got there because a human
ran `fetch --accession` by hand during the pilot. The override is documented at
`fetch.py:254–262` and its reason is in `DATA.md`, but **nothing in `pipeline
<TICKER>` performs it.**

So the final fiscal year of every company run start-to-finish by the
orchestrator silently loses its say-on-pay and director-election vote, and the
only reason MORN looks complete is that the pilot was driven by hand. This is
exactly what 6.5 was scoped to expose — "the paths only a real run exercises" —
except the path in question is one MORN reached *manually*, which is worse than
untested, because it left a passing example behind.

**Closed for this run, not fixed in the pipeline.** MSFT's 8-K was fetched with
the documented override and `extract_sections` re-run; counts reconciled
(CLAUDE.md rule 5): fetch 132 → 133 documents, sections 147 → 148 rows and 145 →
146 ok with the 2 known image-only EX-99-2 failures unchanged, tasks 41 → 42,
`no source` 4 → 3. Nothing was committed because `data/raw/` and
`data/sections/` are gitignored by design.

**The decision this needs, and why it was not taken unilaterally.** Widening the
window is the wrong shape — `fetch.py:259–262` already argues this, and it is
right: a sixth year would sweep in 10-Qs, Form 4s and earnings 8-Ks and quietly
change what every coverage claim means. The candidate fix is a **narrow
look-ahead**: after building the work list, ask `gather_votes`'s own pairing rule
for each in-window year and add just the accessions it names. That puts one
function in charge of the question in both places instead of duplicating the
rule, but it makes `fetch` depend on an `extract_facts` helper, which is a
layering change worth deciding on rather than slipping in during a spend.

### The three remaining gaps are real, and fetching cannot fix them

FY2020, FY2021 and FY2022 `letter` have no source because **MSFT filed no ARS
before FY2023** — there is no shareholder-letter document in EDGAR to extract.
Confirmed against the inventory, not inferred from the failure. This is a
coverage limitation of the company's filing habits and belongs in the
deliverables as a stated gap, which is the outcome CLAUDE.md's traceability rule
requires: *"If something can't be sourced, it doesn't go in."*

Worth noting for 6.6: it also means the letter-signature fallback built in 6.4
is exercised by only three years, all of them ARS-form.

## The gate's approving path, exercised for the first time

`pipeline run MSFT --only extract_facts --yes` — `--only` scopes approval to the
one stage, so `generate_outputs` was never pre-approved. The probe reported 42
outstanding, the estimate printed, and `--yes: approved without asking` recorded
the decision in the log. Item 27's approving path had never run before this.

**Estimate at approval: $7.12 to $23.92 notional across 42 calls** — the 42nd
being the FY2025 `votes` task that finding 4 restored.

## What the run did

42 tasks, **0 failed**, 657.5s. Every record `stop_reason: end_turn` — no
truncation, which is the failure that matters, because a structured response cut
off at `max_tokens` is a failed call rather than a shorter one. All 42 stamped
`backend: claude_code`, `billing: seat`, `model: claude-opus-5`.

**Billing is the seat; $0 was charged.** Notional, at API rates:

| | tokens | notional |
|---|---|---|
| cache write (1h, 2.0x) | 906,344 | $9.06 |
| cache read (0.1x) | 805,680 | $0.40 |
| plain input | 84 | $0.00 |
| output (687 thinking) | 109,460 | $2.74 |
| **actual** | | **$12.20** |

Against the $15 budget, and inside the printed $7.12–$23.92 band.

`credentials_withheld` is empty on all 42 records, which is the **intended** end
state and not a regression: there is no API credential left in the environment
to withhold. That is the colleague case pinned in
`tests/unit/test_seat_billing.py`.

## Finding 5: the estimate's token count is low by ~25%, and this measures it

The run landed inside the band, but the **low end is the headline someone
approves at**, and its input side was $7.12 estimated against $9.47 actual.
`e28f57b` this morning fixed the *multiplier* (1.0x → 2.0x). The token **count**
is a second, independent error in the same place. 42 calls of ground truth
identify it exactly:

```
cache_creation = 0.36108 * source_chars + 6,959       per call
                 (2.77 chars/token)

predicted 906,344   vs   906,344 actual
```

**It is not the divisor.** The fitted 2.77 chars/token is slightly *less*
generous than the estimator's own ratio, so that half was already conservative
in the right direction. The entire error is the intercept: **~6,959 tokens per
call of prompt overhead** — system prompt, JSON schema, the task's `ask` text —
that the estimate never counts, because it prices `source_chars` and nothing
else. Across 42 calls, ~292,000 tokens, $2.92 at the 2x write rate.

**A second, smaller cause, and it is a concurrency effect.** The first two calls
carry residuals of +24,331 and +22,249, far above the 6,959 intercept. At
`concurrency = 2` both opened before either had written the scaffolding cache,
so the 19,631-token scaffolding was cache-**written twice**. The estimate prints
"first call writes the scaffolding" and charges it once; the honest rule is
`min(concurrency, calls)` cold writes.

**Deliberately not fixed in the same commit as the spend it mispriced.** Fixing
an estimator immediately after using it to approve a run, using that run as the
target, destroys the independence between the arithmetic and the thing it is
checked against — and that independence is the only reason this morning's
$7.12-against-$7.13 agreement carried any information. The constants above are
recorded so the fix can be written against them and then verified against this
run as held-out data.

## Paths a real run exercised for the first time

- **The cost gate's approving path** (item 27) — `--only extract_facts --yes`,
  which scopes approval to one stage so `generate_outputs` was never
  pre-approved.
- **The 6.4 letter-signature fallback**, on FY2023/24/25 — the only ARS years,
  so three of six.
- **FY2025 `votes`**, which exists only because finding 4 was closed first: 21
  vote results that `pipeline MSFT` would otherwise have dropped silently.

## The free stages, and the gate declining under a piped stdin

`build_ledger` → `merge_events` → `render_timeline` → `build_pack` all ran clean,
then `generate_outputs` **declined itself** because stdin was not interactive:
*"stdin is not interactive, so nothing approved it."* Exit 3, nothing spent,
resume commands printed. That is the other half of item 27 — the path that
treats an unanswerable question as **no** — and it now has a real run behind it
rather than a unit test.

| | |
|---|---|
| ledger | 769 facts over 6 years, 809 unique ids, no collisions at 8 hex |
| unverified quotes | **2 of 769**, both excluded from the pack as unsourceable |
| pack | 807 citable ids, 459,258 chars, **172,653 tokens** — 29% of the ceiling |
| pack sha256 | `8692a1d7a9c76734…` |
| timeline | `output/timeline.md`, 104 rows from 108 records (4 merged) |

The two unverified quotes were **kept in the ledger and dropped from the pack**,
which is the traceability rule behaving correctly: unsourceable means not
citable. One diverges after 558 of 581 characters (96% — almost certainly
punctuation), the other after 124 of 222 (56%, more substantive).

MSFT's pack is **172,653 tokens against MORN's ~353,000**, for six years rather
than five. The budget check's warning threshold was never approached, so the
Phase 0 pack-budget machinery remains unexercised by a real company.

## Finding 6: the proxy `director_bios` boundary does not survive a new filing agent

Every MSFT `board` fact is name-only. Measured across both companies:

| | `director_since` | `committees` | `role` | source size |
|---|---|---|---|---|
| **MSFT** | **0/12, all six years** | **0/12, all six years** | 0–4/12 | 16,137–57,761 ch |
| MORN | 9–10/10 | 7–8/10 | 3–11/10 | 20,736–31,968 ch |

Two independent signals that the span, not the model, is at fault:

1. **A 3.5x size spread** for the same section of the same company's proxy
   across six consecutive years. MORN's varies by 1.5x.
2. **1–4 quotes per year are lifted from the proxy VOTING CARD** — "1. Election
   of Directors: (The Board recommends a vote FOR each nominee) 01. Reid G.
   Hoffman 02. Hugh F. Johnston…" — so the span reaches the ballot instead of
   stopping at the bios.

Consequence: **72 pack facts, 9.4% of everything citable, name a director with
no tenure, no committee and usually no role.** Nothing is *wrong* — the names
and quotes verify — but the governance half of the brief has almost no substance
to draw on, and 6.6's judgment has to account for that rather than read it as a
model failure.

**This one cannot be fixed in config.** Per the 6.4 finding, `find_proxy_sections(doc)`
takes no `cfg` argument, so proxy boundaries are not reachable from
`sections.toml` — not globally and not in `companies/MSFT/overrides/`. It needs
code, which is why it is recorded here rather than patched mid-run.

`board` carrying `confidence: low` on all 72 is **not** part of this and not an
MSFT problem: the board member schema has no confidence field at all, for either
company (`None: 72` MSFT, `None: 51` MORN), so `low` is assigned downstream.
MORN's committed ledger shows the same `high=0 low=n`.

## Finding 7: `build_ledger` prescribes a paid command that has nothing to do

For each missing task it prints, e.g.:

> FY2020: extraction task 'investor_qa' has no result file — run
> `uv run python -m equity_research.extract_facts --fy 2020 --task investor_qa`

Run verbatim, that reports **`tasks to run: 0` … `nothing to do`** and exits 0.
FY2020 has no `investor_qa` unit because triage routed no filing to it — there
is nothing to extract, so the file's absence is correct and the instruction is a
dead end. It fired for four of the eight warnings (FY2020/2023/2024
`investor_qa`, and the three `letter` years are the same shape).

Harmless in dollars, because the stage refuses to spend on an empty plan. Still
worth fixing: it sends an operator to a **paid** stage to chase a non-problem,
and the warning cannot currently tell "extraction has not run yet" apart from
"there was never anything to run". The second case should say *no source in this
year's filings*, and say nothing about `extract_facts`.

## Finding 8 (FIXED): SPEC.md's word range is a five-year number, and no wider window could pass

The one hard check the repair could not clear. Fixed, because unlike findings 4,
6 and 7 the fix is a re-parameterization that leaves MORN provably untouched
rather than a judgement about extraction quality.

**The arithmetic that settles it:** `1,500 ÷ 5 = 300` and `2,500 ÷ 5 = 500`.
SPEC.md's "roughly 1,500–2,500 words" is **300–500 words per fiscal year**
multiplied by the only window that existed when it was written. Under a fixed
pair, `settings.MAX_WINDOW_YEARS = 10` would allow a window whose brief must fit
250 words a year — **half MORN's density, so no document could pass.** The check
was unsatisfiable by construction across most of the supported range.

MSFT is not verbose; it is wider. **496 naive words per fiscal year against
MORN's 518.**

| window | range | result |
|---|---|---|
| MORN, 5y | 1,500–2,500 — *identical* | passes, as before |
| MSFT, 6y | 1,800–3,000 | 2,690 passes |
| 10y | 3,000–5,000 | satisfiable at last |

**And it removed a duplicate that was one edit from lying.** The target lived in
`company.toml` as `brief_words_min`/`brief_words_max` while the check lived in
`config/outputs.toml` as `[verify.word_range]` — two copies agreeing at 1,500 /
2,500 only because neither had been changed. Scaling one and not the other would
have told the writer 1,500–2,500 while failing it at 1,800–3,000: asked for one
thing, failed for another. Both now come from
`verify_outputs.word_range(cfg, pack, doc)`, which `generate_outputs.brief_ask`
calls for the prompt and `verify` calls for the gate. `load_gen_config` **refuses**
a `company.toml` still carrying the old keys rather than ignoring them.

Rule 3, exercised: reinstating `brief_words_min` produced the FATAL with the
file path, the key and the remedy; a malformed pack raises rather than defaulting
to a one-year window (which would scale every range to 300–500 and fail
everything); and 13 new checks pin the arithmetic at 5, 6 and 10 years, including
`2,690 <= 2500 is False` so the original bug stays pinned. **589 checks.**

## Finding 9 (FIXED): a 188-character heading broke across a page, and the CSS to stop it does not exist

`render_pdf`'s read-back refused `discussion-points.pdf`: 1 heading "MISSING",
with **0 ids, 0 glyphs and 0 words lost, 6,549 words in order**. Those cannot
both be descriptions of lost content.

Measured rather than assumed: 145 of the heading's 154 flattened characters
matched, then the extracted text read `discussion-points.md·rendered2` — the
**running footer**. The heading split across a page boundary, leaving
"hardware?" alone on the next page. Every word was present.

**The pair of facts that identifies this class:** *words all present* + *heading
"missing"* means **interrupted, not lost**. Recorded at the check itself, because
its FATAL says "do not contain everything their Markdown does", which in this
case is untrue.

Fixed at the source rather than by loosening the check — a heading broken over a
page is a real defect even though nothing is missing. **And the obvious fix does
not exist:** `page-break-inside: avoid` was tried first and changed nothing.
xhtml2pdf's supported-CSS reference lists `page-break-after` and
`page-break-before` **only** — no `page-break-inside`, and no CSS3 `break-*`.
All of them parse, none is honoured, and the PDF re-rendered with the same
heading still broken. The working property is the vendor-specific
**`-pdf-keep-with-next: true`**, which moves a heading wholesale to the next
frame when it will not fit; there is no property making a block unbreakable on
its own. `print_css`'s own docstring already said "keep to what it actually
honours", which is the second time that warning has been earned.

Both companies re-rendered clean: MSFT 3 PDFs, all 35 headings; MORN 3 PDFs
unaffected.

## Finding 10 (FIXED): a set iteration made `ledger-report.md` dirty on every re-run

Caught by the full thirteen-stage run, from `git status` rather than from any
check: `ledger-report.md` came back **modified** after a re-run over identical
inputs. Two FY2020 warnings had swapped places. Rule 4 names this exactly —
*"Any run-to-run difference — a timestamp inside a payload, unsorted keys — is a
bug, not cosmetic."*

`build_ledger.py:616` read:

```python
missing_tasks = [t for t in {t for t, _, _ in FIELD_MAP} if not task_cache.get(t)]
dq["extraction_tasks_missing"] = sorted(missing_tasks)   # sorted HERE
for t in missing_tasks:                                  # and NOT here
    warnings.append(...)
```

It iterates a **set**, whose iteration order for strings differs between
processes under hash randomization. `sorted()` was applied to the JSON field and
not to the loop that writes the Markdown, so **the JSON was stable and the
Markdown was not** — which is why every check stayed green while the working tree
went dirty.

**MORN could not have caught this.** It needs *two* missing tasks in *one* fiscal
year to have anything to reorder, and MORN never had that;
`tests/regression/morn/test_reruns_change_nothing.py` re-runs the stages and
compares committed bytes, and would have passed forever. MSFT's FY2020 is missing
both `investor_qa` and `letter`.

Sorted once and used sorted. Verified across four values of `PYTHONHASHSEED`
(1, 2, 7, 99): one distinct sha256, and byte-identical to the committed file. The
failing case needed no construction — two consecutive real runs had already
produced different bytes.

## The full thirteen-stage run

```
registry : 13 stages     ran : 11     nothing to do : 2 (extract_facts, generate_outputs)
```

Exit 0. 13 selected = 11 ran + 2 no-ops, which reconciles. `verify_outputs`:
every hard check passed on both documents. `render_pdf`: 3 PDFs, every word,
fact id, heading and at-risk glyph present.

**This completes item 27's three gate paths with a real run behind each:**

| path | how it was reached |
|---|---|
| approved | `--only extract_facts --yes`, 42 calls |
| declined | a piped stdin, read as **no** — exit 3, nothing spent |
| nothing to do | the full run: both spending stages no-op, no prompt |

## Gate 6, closed properly

The full run that found finding 10 was also the run that would have *closed*
gate 6, so it could not do both. Re-run afterwards, as **separate invocations**:

```
PYTHONHASHSEED=''   (empty means randomized per process)

CHECK 1  baseline, before any run   CLEAN
CHECK 2  MSFT full run 1            CLEAN     ran: 11, nothing to do: 2
CHECK 3  MSFT full run 2            CLEAN     ran: 11, nothing to do: 2
CHECK 4  MORN full run 1            CLEAN     ran: 11, nothing to do: 2
CHECK 5  MORN full run 2            CLEAN     ran: 11, nothing to do: 2

5 tree checks, 0 dirty
```

Every run: both documents passed every hard check, 3 PDFs re-rendered and read
back. Cleanliness is checked with `git diff --quiet` as well as
`git status --porcelain`, because status can lean on stat info while `diff`
compares bytes.

**Separate invocations are the substance of this gate, not a detail.** `cli.py`
does not pin `PYTHONHASHSEED` and it is unset in the environment, so each of the
~14 stage subprocesses per run draws its own seed. An in-process "run the writer
twice and compare" test shares one seed and **structurally cannot** see
hash-order nondeterminism — which is precisely how finding 10 survived every
green suite until today. This is memory finding 16 restated by a second example:
`tests/regression/morn/test_reruns_change_nothing.py` compares one run against
the *committed* bytes for exactly this reason, and that is still the right
design.

*Two faults of my own in the harness for this gate, both worth recording because
each produced an answer that looked fine.* The first used a PowerShell function
that both `Write-Output`s and returns a boolean — a function returns everything
it writes, so the status strings joined the booleans in the results array: five
checks reported as "10 tree checks" and every per-check line swallowed. The
verdict was right and unevidenced, which is not good enough for a gate. The
second died on a parse error at the last line of the file: PowerShell 5.1 reads
a `.ps1` as cp1252 unless it has a BOM, and an em dash inside a double-quoted
string is UTF-8 `E2 80 94`, whose third byte decodes to a curly right double
quote — which PowerShell accepts as a string delimiter. CLAUDE.md rule 2 again,
in a scratchpad script rather than in source. The third attempt is ASCII-only and
was parser-checked before being run.

---

# 6.7 — the clean-checkout run

Done 2026-09-08. Fresh clone **from GitHub** (what a colleague actually does),
into a 27-character path outside OneDrive as the README instructs. Gate 7 met,
and with it all seven.

**One deliberate deviation from the plan's script.** It says
`pipeline <TICKER> --yes`; this used `--skip-spending` plus `--check-fresh` on
both paid stages instead. `sections/` is gitignored and *must* rebuild in a fresh
clone, and if it rebuilt one byte differently the committed facts cache would go
stale — where `--yes` would **approve ~$12 of real re-extraction**. The
substitute proves the same property and turns a possible bill into a finding.
Anyone re-running 6.7 should keep that substitution.

| check | result |
|---|---|
| `uv sync` (README step 1) | **FAILED** — see finding 11 |
| `tests/unit` in a bare checkout | 12 files, 548 checks, pass |
| regression tests with no derived data | **fail loudly**, all 4 named, exit 1 |
| sections rebuilt from `raw/` alone | MORN 231, MSFT 148 — counts unchanged |
| **pack sha256 reproduced** | `fd320ce5…`, `8692a1d7…` — **both match** |
| `extract_facts --check-fresh` | exit 0, 88 and 42 cached, 0 to run |
| `generate_outputs --check-fresh` | exit 0, both documents current |
| `verify_outputs` | every hard check passed, both companies |
| `render_pdf` | 3 + 3, read-back verified |
| **`git status` in the clone** | **CLEAN** |
| `sec_requests_made` | **0** for both companies |
| full suite in the clone | **589 checks**, all passing |

`git status` clean is the plan's central check, and it means more here than after
an in-place run: the clone rebuilt every derived artifact from `raw/` alone and
reproduced the committed bytes, **including both pack sha256s** — so the
provenance footer in each committed deliverable still resolves against a pack
built on a different machine path. `sec_requests_made: 0` is item 29's other
half: with `raw/` restored, a whole-company run makes no EDGAR request at all,
which is what CLAUDE.md's cache-once rule requires in its hardest case.

Two documented claims were tested rather than assumed, and both held:
`tests/unit` is genuinely self-contained, and `tests/regression/morn` **dies**
instead of skipping, naming each missing artifact and saying which are free to
rebuild and which are paid model output. That is VERIFICATION.md D7 working.

## Finding 11 (FIXED in the README): `uv sync` fails at step 1 on a hardlink error

The first command in the README, on a clean clone:

```
error: Failed to install: pytest-9.1.1-py3-none-any.whl (pytest==9.1.1)
  Caused by: failed to hardlink file from <.venv> to <uv cache>:
  The cloud operation cannot be performed on a file with incompatible
  hardlinks. (os error 396)
```

`uv` populates `.venv` by hardlinking out of its cache, and that fails when
either end is on a cloud-backed filesystem. `uv sync --link-mode=copy` —
the mode `uv`'s own warning suggests — works, and `UV_LINK_MODE=copy` makes it
stick.

**The non-obvious part, and why it belongs in the README rather than in
folklore:** this happened with the checkout **outside** OneDrive, exactly as the
README advises, because the *cache* end of the link is under the user profile.
Someone who had read the OneDrive warning and followed it would conclude the
project was broken. Documented with the verbatim error so it is searchable.

This is the whole justification for 6.7 as a separate item: nothing else in the
phase could have found it, because every other run reused an environment that
was already built.

## All seven gates, closed

| gate | how |
|---|---|
| 1 | 6.1's fiscal-year tests pass, and fail against a broken mapping |
| 2 | MSFT's counts reconcile across four seams; the shard question answered |
| 3 | every section validates or is a recorded failure (2 image-only exhibits) |
| 4 | `pipeline estimate` ran before spending; the bill accounted against it — and finding 5 came out of that reconciliation |
| 5 | both deliverables pass all 14 hard checks; 39/39 and 72/72 quotations verbatim |
| 6 | two consecutive full runs per company, 5 tree checks, 0 dirty |
| 7 | this section |

**Phase 6 is complete.** What it leaves behind is eleven findings, four of them
cases where MORN's committed artifacts look complete and the automated path does
not reproduce them — findings 4 and 6 still open by decision, 5 and 7 open and
recorded, the rest fixed.
