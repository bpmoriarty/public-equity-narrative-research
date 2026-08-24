*Scoping response recorded verbatim, 2026-08-17. Nothing was built. The four
decisions at the end are open.*

---

I read the 13 stage modules' `main()`s, their path constants, and the two `--estimate` paths rather than working from the plan. The plan is broadly right about the *shape* of Phase 4 and wrong or silent about four things, one of which is an ~$8 hazard.

---

# Phase 4 scope: the `pipeline` orchestrator

## The stage graph, as the code actually has it

Derived from what each module reads and writes, not from the plan's ordering:

| # | Stage | Reads | Writes | Spends? |
|---|---|---|---|---|
| 1 | `discover` | EDGAR submissions (cached) | `discovery/inventory.json` | no |
| 2 | `fetch` | inventory | `raw/` + `fetch-manifest.json` | no |
| 3 | `extract_sections` | fetch-manifest | `sections/` + `sections-manifest.json` | no |
| 4 | `triage_8k` | sections-manifest, inventory | `triage/triage-8k.json` | no |
| 5 | `risk_diff` | sections-manifest | `ledger/risk-deltas.json` | no |
| 6 | **`extract_facts`** | sections-manifest, inventory, triage | `ledger/facts/` | **yes** |
| 7 | `build_ledger` | facts, risk-deltas, corrections | `ledger/FY*.json` | no |
| 8 | `merge_events` | ledger | `pack/timeline-events.json` | no |
| 9 | `render_timeline` | `pack/timeline-events.json` | `output/timeline.md` | no |
| 10 | `build_pack` | ledger (+ `timeline_block()` **in-process**) | `pack/pack.json`, `index.json` | no |
| 11 | **`generate_outputs`** | pack, index | `output/narrative-brief.md`, `discussion-points.md` | **yes** |
| 12 | `verify_outputs` | pack, index, output | `pack/verify-report.md` | no |
| 13 | `render_pdf` | output | `output/pdf/` | no |

Two structural notes: `build_pack` imports `timeline_block()` from `merge_events` and recomputes the merge in memory, so it does **not** depend on stage 8 having run — the graph isn't a straight line, and the registry shouldn't imply it is. And the three writers into `pack/` own disjoint files, so rule 4 is already satisfied there; no merge logic needed.

The plan's core choice — **subprocess per stage** — is confirmed correct. Every `main()` is `-> None` and signals failure with `sys.exit("message")`, which gives exit code 1 and the message on stderr for free. Zero refactor of the 13 mains, as promised.

---

## Four things the plan doesn't know

**1. `generate_outputs` has no cache path, and `run` would spend ~$8 overwriting committed deliverables.** This is the one that matters. Every other stage no-ops or rebuilds cheaply; generation goes straight from argument parsing to generating both documents. There is no "already written from this pack, skip" check. So the plan's gate — *"`pipeline MORN --yes` runs end-to-end from cache with zero LLM spend"* — is **not achievable against the current code**, and `--yes` on a naive implementation is a one-keystroke way to destroy the two documents that CLAUDE.md rule 1 exists to protect.

The fix is groundable in what's already there: `gen-*.json` records `pack_sha256`, and line 1776 already compares it against the current pack for the corrections path. A freshness no-op is ~50 lines. I'd put it **inside `generate_outputs`**, not in `cli.py`, because stages owning their own staleness is the existing pattern (that's exactly what `extract_facts` does) and it protects a bare stage invocation too, not just the orchestrated one.

**2. `extract_facts` exits 1 by design when cached results are stale.** Not a crash — a deliberate refusal, because re-running costs tokens and leaving stale facts is worse. The orchestrator must recognize this specific halt and print the remedy (`--refresh-stale`, and that it spends) instead of a generic "stage failed, chain halted".

**3. `pipeline init ZZZTEST` breaks the 269-check suite while the folder exists.** Five test files call `paths()` with no ticker and depend on MORN being the *only* company — `resolve_ticker` hard-errors on two. So the plan's gate sequence has a trap: init must be verified and removed before the suite is trustworthy again. The clean fix is pinning `EQR_TICKER=MORN` in the test runner, which is Phase 5 work pulled forward by one item.

**4. A full `run` dirties the git tree every time.** `discovery-report.md`, `ledger-report.md` and `output/timeline.md` rewrite themselves with only a changed timestamp (open item 19). Today that's cosmetic because you run stages selectively. An orchestrator that touches all 13 makes it structural — every `pipeline run` produces a fake diff on committed files, which is precisely the "run twice, diff nothing" rule the project already has an enforcer for.

Also still open from Phase 0 and belonging here: `PYTHONUTF8=1` in the per-stage subprocess environment.

---

## Work breakdown and time

| | Item | Est. |
|---|---|---|
| 4.1 | Stage registry + `run`: subprocess runner, env (`EQR_TICKER`, `PYTHONUTF8=1`), streamed output, halt on non-zero | 45–60 min |
| 4.2 | Cost gates: shell each spending stage's `--estimate`, echo verbatim, prompt y/N, `--yes` skips | 20–30 min |
| 4.3 | **Generation freshness no-op** (new — not in the plan) | 45–60 min |
| 4.4 | `status`: per-stage output presence, counts, freshness. Scoped honestly — most stages can't dry-run, so it reports what exists and lets the two self-reporting stages speak for themselves | 40–50 min |
| 4.5 | `estimate`: shell both `--estimate`s, sum, label the backend | 15 min |
| 4.6 | `init` + `companies/_template/`: hand-authored template (Python can't write TOML without destroying 161 lines of comments), dirs, next-steps print, plus a hygiene check that template keys match MORN's | 40–50 min |
| 4.7 | `tests/test_cli.py` (~40 checks), each proven against a planted fault per rule 3 | 60–90 min |
| 4.8 | Item 19 timestamp churn — recommended, see #4 above | 30–40 min |
| 4.9 | README, PROJECT_STATUS, `expected_counts.json`, 2–3 commits | 40–50 min |

**~6–8 hours of focused work**, one long session or two shorter ones. Caveat worth stating plainly: Phase 3 was scoped as a call-site swap and turned into a redesign because five measured facts contradicted the plan. The mechanical phases have held closer to estimate, and this is a mechanical phase — but 4.7 is where the overrun would come from, since this project's rule-3 discipline means every check gets built twice.

New code: roughly **600 lines of `cli.py`** (the house style is heavily commented) plus **~450 lines of tests**.

---

## Cost and tokens

**Pipeline spend: $0, and that's a design target rather than an accident.** Eleven of thirteen stages make no model call. `extract_facts` reports 88 cached / 0 to run. `generate_outputs` is skipped by item 4.3. The `--estimate` paths make no model calls on either backend. The only route to real spend is an accidental generation run at **~$8** (measured $7.21), which is exactly what 4.3 prevents — so 4.3 is not a nice-to-have, it's the item that makes the gate honest.

**Wall clock for the gate run:** single-digit minutes from cache, dominated by `extract_sections` re-parsing 201 HTML documents.

**My token spend building it:** on your seat, $0 marginal — that's the whole point of Phase 3. Metered at Opus 5 rates it would be roughly **$6–15** (~400–700K input, much of it cache reads at 0.1×; 80–150K output). That's extrapolated from the shape of prior phases, not measured — a seat produces no dollar figure to check it against.

---

## Gates

1. `uv run pytest` green at 269 before starting, and at its new number after.
2. `pipeline estimate MORN` reports both spending stages with $0 to spend.
3. `pipeline MORN --yes` end to end, **$0 spent**, verify green, `git status` clean afterward (this last clause is what 4.8 buys).
4. A planted non-zero exit mid-chain halts it and the later stages provably don't run.
5. The cost gate declines by default — proven by a stage that *would* spend, without letting it.
6. `pipeline init ZZZTEST` scaffolds correctly; suite re-run after removing it.

---

## Four decisions before I build

1. **Should `run` include `generate_outputs` at all**, with a freshness no-op — or should generation stay a deliberate manual act outside the orchestrator? I lean toward including it with the no-op, since "one command" is the phase's whole value.
2. **Freshness check inside `generate_outputs`** (my recommendation) **or only in `cli.py`?**
3. **Pull item 19 into this phase?** I recommend yes — otherwise gate #3 can't include a clean tree.
4. **Pin `EQR_TICKER=MORN` in the test runner now?** It's required the moment a second company folder exists, even briefly.

And a flag on the plan's own wording: its gate says `ZZZTEST` "then is deleted." I won't delete anything without asking, so that'll be a checkpoint, not a step.
