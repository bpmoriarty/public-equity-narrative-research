*Scoping response recorded 2026-08-26. Nothing was built. The four decisions at
the end are open, and one of them — which company — blocks everything after 6.1.*

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
