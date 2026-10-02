*Scoping response recorded 2026-08-25. Nothing was built. Questions 2 and 3 were
answered by the user on the same day and their answers are recorded inline;
question 1 was answered by an observation that collapsed the item rather than
choosing between its options — see 5.3. The one open decision is at the end.*

---

I read the nine test files, `config/llm.toml`, the extraction and generation
config blocks, `README.md`, `DATA.md`, and the committed usage records on the 88
facts files, rather than working from the plan. The plan is right about the
*shape* of Phase 5 — tests, models, pack, docs — and wrong about the sizing of
three of its five items, in each case because it was written before Phases 3 and
4 changed the thing it was sizing.

---

# Phase 5 scope: tests, model knobs, docs

## What the plan says Phase 5 is

Five items, marked Sonnet-suitable: (1) test split `unit` vs `regression/morn`,
(2) fixture-based idempotency tests, (3) model mix with an `investor_qa` A/B,
(4) pack subsets plus timeline de-duplication, (5) docs.

Two plan corrections were already recorded from executing Phase 1 and must not be
re-derived: the `--collect-only` count gate is wrong and was deliberately not
done (it counts test *functions*, so a file falling from 63 checks to 3 still
passes — the exact D7 failure the gate exists to catch), and `suite_test.py`'s
per-file **check count** is the design to keep through the split.

---

## The measurement that reshaped the phase

Read off the `usage` blocks of the 88 committed facts files. The totals reconcile
to the committed `$11.33`, so these are the real numbers rather than a model of
them. Sonnet column priced at $3/$15 per 1M against Opus 5's $5/$25.

| task | calls | input tok | output tok | Opus | Sonnet |
|---|---:|---:|---:|---:|---:|
| **investor_qa** | 54 | 514,394 | 169,435 | **$6.81** | $4.08 |
| business | 5 | 155,951 | 7,706 | $0.97 | $0.58 |
| mdna | 5 | 134,658 | 13,978 | $1.02 | $0.61 |
| comp | 5 | 108,972 | 13,603 | $0.88 | $0.53 |
| events_8k | 5 | 51,953 | 6,762 | $0.43 | $0.26 |
| board | 5 | 51,236 | 7,913 | $0.45 | $0.27 |
| letter | 4 | 50,194 | 7,933 | $0.45 | $0.27 |
| votes | 5 | 18,700 | 8,511 | $0.31 | $0.18 |
| **TOTAL** | 88 | 1,086,058 | 235,841 | **$11.33** | $6.80 |

And `pack.json` by top-level key:

| key | chars | ~tokens | share |
|---|---:|---:|---:|
| years | 901,438 | 225,359 | 64% |
| **timeline** | **49,900** | **12,475** | **3.5%** |
| constraints, field_notes, how_to_use, subject, excluded | 5,875 | 1,466 | 0.4% |

The plan calls the timeline block "8,119 tokens of pure redundancy". It is
**12,475**, and it is 3.5% of the pack — about **$0.06 per call**, on the two
calls that carry the pack.

---

## 5.1 — Split the suite, and unify the one odd signature

**Where the artifact dependence actually is.** Nine files, 3,618 lines, 400
checks. The split is more tractable than "nine files, pick a bucket": in most
files the artifact-bound checks are a **tail**, so the boundary runs through
files rather than between them.

| file | checks | reads from disk | lands |
|---|---:|---|---|
| `test_verify_quote.py` | 13 | nothing | unit, whole |
| `test_merge_events.py` | 44 | nothing | unit, whole |
| `test_fact_id.py` | 19 | `P.ledger` (line 209 of 250) | unit + small tail |
| `test_extract_sections.py` | 17 | `P.config_dir`, `P.sections_manifest` (124 of 145) | unit + tail |
| `test_verify_outputs.py` | 63 | `P.output`, `P.pack` (357–363 of 384) | unit + tail |
| `test_generate_outputs.py` | 91 | `P.output`, `P.pack` (484–520 of 535) | unit + tail |
| `test_cli.py` | 112 | `P.company`, `P.inventory`, `P.facts` (498–500 of 570) | unit + tail |
| `test_discover.py` | 14 | `P.inventory`, `P.run_log` | mostly regression |
| `test_repo_hygiene.py` | 27 | ten different artifacts | regression, whole |

**The gate protects its own migration.** `run_all.py:72` globs
`HERE.glob("test_*.py")` — non-recursive — and `suite_test.py` reconciles
`expected_counts.json` against disk in **both** directions. So a half-finished
split fails loudly rather than silently dropping the files that moved. Both
runners need recursive discovery and the counts file needs relative keys; do
those first and the gate stays useful throughout the move instead of being
switched off for it.

**Fold in Next Steps 28.** `test_repo_hygiene.check()` is `(name, ok, detail)`
while the other eight are `(name, got, want)`. That mismatch produced three bugs
in one Phase 4 session, one of which **passed vacuously**. Both forms are
defensible; two forms in one directory are not. A shared `tests/check.py` is the
natural product of splitting anyway, so this is the cheapest moment it will ever
have.

**The conftest the plan asks for.** `tests/regression/morn/` sets
`EQR_TICKER=MORN` and **errors, never skips**, when the artifacts are absent —
the D7 lesson. Note that `tests/fixture.py` already performs the ticker pin and
**must be imported before any stage module**, because stage modules resolve their
path constants at import time. That ordering is load-bearing and commented as
such in six files; it has to survive the move or four of them break.

**Effort:** 2–3 commits, 3–4 h. **Pipeline spend $0.**

## 5.2 — Prove idempotency by running it, not by linting it

Next Steps 19 is closed for the half a static check can do: no wall clock in a
committed artifact, enforced, and verified directly by two consecutive
`pipeline MORN --yes` runs leaving eight files byte-identical. That check
explicitly **cannot prove idempotency** — it catches the one way the property has
ever broken here. Proving it needs the writers run twice, which needs fixtures.
This is the item that closes the clobber class, which recurred twice.

**One design constraint found in Phase 4.6 — do not re-derive it.** The fixture
company must live under `tests/`, **not** under `companies/`. A company folder
there makes the check count depend on how many companies exist, which already
broke the count gate once (20 → 21 checks) and was fixed by aggregating the
per-company checks into one. A synthetic company under `companies/` re-opens
that, and would additionally have to satisfy the template key-agreement check.

Scope: a small synthetic company (two fake filings, no EDGAR, no model call), the
four manifest writers plus `settings.record_run` each run twice against it,
byte-compared. `record_run` is the case that most needs it — five stages write
that one file, which is the exact shape CLAUDE.md rule 4 was written about.

**Effort:** 1–2 commits, 2–3 h. **Pipeline spend $0.**

## 5.3 — Build the per-task model knob; switch nothing; run no A/B

This is the item that changed most, and it changed because of something no
measurement in this repository could have told me.

**What the plan proposed:** `votes` and `board` to Sonnet unconditionally, repair
rounds to Sonnet, and an `investor_qa` A/B (~$1, accept if ≥95% of shipped facts
recover with matching quote-verify rates) before switching the big one.

**First correction, from the table above: the plan has the cheap change
unconditional and the valuable one behind a gate.** `votes` + `board` to Sonnet
saves **$0.31 per company** — 2.7% of extraction. `investor_qa` is **60% of
extraction spend** and would save **$2.73**.

**Second correction: those two tasks are also the two I would least want to
downgrade.** `votes`'s entire instruction is *"Copy the numbers exactly. Do not
round, total or recompute them"*, and the numeric-evidence checker the plan cites
as the safety net audits **documents**, not the ledger — nothing downstream
re-checks a vote count against the 8-K it came from. `board` is already the
low-confidence field (51 of the 54 low-confidence facts) reading a section whose
boundaries are known to be unreliable. Paying $0.31 to add noise to the two
weakest-audited fields in the ledger is the wrong trade at any price.

**Third, and this is the one that collapses the item — from the user, 2026-08-25:
MORN's written investor Q&A is idiosyncratic.** It publishes written answers to
investor questions under Reg FD roughly monthly; most issuers do not do this at
all. That is domain knowledge, not something measured here, and it is recorded as
such — but it is decisive, because everything that made `investor_qa` worth
optimising is downstream of a volume other companies will not have:

- **The $2.73 saving does not recur.** Strip `investor_qa` and a company's
  extraction is 34 calls and **$4.52** on Opus, $2.72 on Sonnet. The recurring
  saving from moving *everything else* to Sonnet is **$1.80** — and "everything
  else" is `business`, `mdna`, `comp` and `letter`, which are the narrative core.
  Those four are the product, and they come to $3.33 on Opus against $2.00 on
  Sonnet. They are the last place to spend a quality budget to save $1.33.
- **The A/B's result would not transfer either.** An A/B on MORN's Q&A tells you
  Sonnet handles *MORN's* Q&A. If the volume is idiosyncratic, so is the finding.
  Better to run that A/B on the company that actually triggers the cost, against
  its own material, when one appears.
- **The wall-clock argument collapses with it.** For a colleague on a seat the
  dollars are notional and what binds is time and rolling usage. `investor_qa` is
  54 of 88 calls at `max_concurrent_requests = 2` — measured at 11.9 minutes per
  fiscal year. A typical issuer's 34 calls are not the same problem.

**So: build the knob, switch nothing, spend nothing.** A `[extraction.models]`
table keyed by task, falling back to the existing single `model` when a task is
absent, plus the lookup at the call site. The seam already accepts `model=` per
call, so this is small. It leaves the decision available as a config edit for
whoever first hits a cost wall, and it costs nothing and risks nothing today.

**The hazard to build in before any A/B is ever run, on any company.** The facts
cache path is `FY<year>_<task>[_<accession>].json` (`extract_facts.py:546`) — the
**model is not in the key**. So an A/B run on a second model writes over the
committed results at the same paths. Those are irreplaceable paid model output
and CLAUDE.md rule 1 is unconditional about them. Any comparison run needs a
separate output location decided *before* the first call, not after. This is the
kind of thing that is obvious afterwards, which is why it is written down here.

Recording the trigger alongside the knob: **run the A/B on the first company
whose own task mix puts one task above roughly half of extraction spend, using
that company's material.** `extract_facts --estimate` already reports enough to
see it.

**Effort:** 1 commit, ~1.5 h. **Pipeline spend $0** — down from the $1–2 the A/B
would have cost, because the A/B is not the right experiment yet.

## 5.4 — Pack subsets: deferred (user decision, 2026-08-25)

Both halves of the plan's item were re-sized and the user chose to defer. The
reasoning is recorded because the trigger matters more than the decision.

**The de-dup half was a $8-to-save-$0.12 trade.** Removing the timeline block
saves 12,475 tokens (~$0.06 per call, on two calls) and changes `pack.json`,
which changes its sha256 — and the sha is a **hard** check on both committed
deliverables (`prov_present` and the provenance match in
`verify_outputs.py:330-336`) as well as the input to the freshness rule built in
Phase 4.3. So the saving costs a **~$8 regeneration of both documents**, or a
permanently red hard check. It is also not purely redundant: the block is the
*resolved* chronology (85 records → 76 rows, conflicting dates marked,
corroboration counted), so removing it is a quality change and not only a size
one.

**The `pack-comp.json` half would ship with zero consumers.** The plan sized it
for **four** generation calls, two of which needed only subsets. There are now
**two** pack-carrying calls: the timeline turned out to need no model at all, and
both repair passes were rebuilt pack-free in Phase 3.

**The trigger, recorded instead of built:** `warn_tokens = 400_000` firing on a
real company — which for MORN-density arrives somewhere around eight fiscal
years. That is the same trigger the plan already sets for era-chunked generation
and QA quote-tiering, and this item belongs in the same deferred group rather
than ahead of it.

**Effort:** ~0.5 h of prose, in `config/outputs.toml` next to the existing budget
check. **Pipeline spend $0.**

## 5.5 — Docs, which are wrong now rather than merely dated

`README.md` is the file a colleague opens first and it currently describes the
pre-Phase-1 project. Seven specific wrongs, each independently confirmed against
the code:

1. `config/company.toml` named as "the file you edit" — it is
   `companies/<TICKER>/company.toml`
2. `data/` and `output/` shown as top-level in the layout block
3. `ANTHROPIC_API_KEY` presented as a required setup step — the default backend
   needs no key, and almost no colleague has one
4. No mention of the five `pipeline` commands, which are now the interface
5. The layout block predates `companies/` entirely
6. Nothing about the VS Code-shipped CLI, which is the single point where this
   meets the outside world on someone else's machine and the thing most likely to
   break for them
7. Nothing about separate checkouts per analyst, or about preferring a
   non-OneDrive location

`DATA.md` is Next Steps 20 and needs prose changes rather than substitution:
about ten references, mostly `config/company.toml` and bare `data/...` paths that
are now company-relative and read correctly once the reader knows the prefix. One
header sentence plus the handful of genuine top-level claims.

`CLAUDE.md` gains the backend section the plan asks for. Worth adding at the same
time: the two Phase 4 doctrines that currently live only in `PROJECT_STATUS.md`
blockquotes — committed artifacts carry no wall clock, and what "already
generated" means (missing, or stamped with a pack that is not the pack on disk).

**Effort:** 1–2 commits, 2–3 h. **Pipeline spend $0.**

## 5.6 — The cheap open items, one commit

- **Next Steps 23** — promote the malformed-citation check in `verify_outputs`
  from `review` to `hard`. Its output has now been read once (0 on both
  documents), which is the bar CLAUDE.md rule 3 sets for promotion. It is already
  fatal in `generate_outputs.report_failures`, the gate that runs before a
  document is ever written. Expect the check count to move, and re-record it.
- **Next Steps 24** — re-check whether exact `count_tokens` has come back. On
  2026-08-16 it returned 500 for every request including a two-word control,
  while `messages.create` on the same key worked. Both callers already fall back
  to `settings.CHARS_PER_TOKEN` and **label the number estimated**, so nothing is
  broken — but that means the labelled-estimate path is the live one for API users
  too, not a courtesy to seat users. A five-minute probe either upgrades every
  estimate in the project or confirms a real limitation.

**Effort:** 1 commit, ~1 h. **Pipeline spend $0.**

---

## Totals

| | commits | time | pipeline spend |
|---|---:|---:|---:|
| 5.1 test split + signature unify | 2–3 | 3–4 h | $0 |
| 5.2 idempotency fixtures | 1–2 | 2–3 h | $0 |
| 5.3 per-task model knob (no switch, no A/B) | 1 | 1.5 h | $0 |
| 5.4 pack subsets — deferral + trigger | ½ | 0.5 h | $0 |
| 5.5 docs | 1–2 | 2–3 h | $0 |
| 5.6 small items | 1 | 1 h | $0 |
| **Phase 5** | **7–10** | **10–13 h** | **$0** |

**Phase 5 spends nothing.** That is an outcome of the scoping rather than a
target: the one item that would have spent money was the `investor_qa` A/B, and
it turned out to be the wrong experiment run against the wrong company. Nothing
in this phase changes what any document says, which is why the plan marks it
Sonnet-suitable — I agree, with two exceptions I would keep on Opus: 5.3's cache-
key hazard and 5.4's sha reasoning, both of which are quiet ways to destroy
something expensive.

## Phase 6, named here because Phase 5 is where it would otherwise leak in

The user's decision, 2026-08-25: **the two things only a real run can test are a
Phase 6, not Phase 5.** Recorded so they are not lost:

- **Next Steps 27** — `--yes` against a genuinely stale document. Declining was
  proven four ways (closed stdin, `n`, `maybe`, `--skip-spending`) and all four
  stop the chain having spent nothing. The *approving* path ends in a real ~$8
  generation call and is currently covered only by injecting a fake gate into
  `run_chain`. "The gate approves correctly" is an untested claim.
- **Next Steps 29** — a first run for a **new** company. Every `pipeline MORN`
  run in Phase 4 reported `sec_requests_made: 0`; the cache holds, exactly as
  CLAUDE.md requires. The opposite case has never been exercised: `discover` and
  `fetch` will make hundreds of EDGAR requests at the configured 0.15 s delay.

Both are exercised at once by scaffolding a second real company and watching it —
roughly **$18–20** of extraction plus generation, and the closest thing to the
plan's final end-to-end verification. It is also the right occasion for the
`investor_qa` A/B question to be asked again, against a company whose task mix is
its own.

## The one item that is out of reach, and should stay named

**Next Steps 13, the model-family gap.** The verification suite asks for a
different model family on the independent passes; the same family reviewed and
then repaired its own work, and the blind clean-room diff of the analytical core
was never run. Phase 3 made this **harder**, not easier: the default backend is a
Claude seat, so a non-Anthropic reviewer is not reachable through the seam at all
and would need separate access that the operating assumption (no API keys) says
colleagues do not have.

Everything in Phase 5 makes the pipeline easier and safer to operate. None of it
substitutes for this. It remains the first thing to close if any deliverable
becomes load-bearing.

---

## The one open decision

**5.3 as scoped builds a knob nobody uses today.** The alternative is to skip it
entirely and let the first person who needs a per-task model add the config table
then. Building it now costs about ninety minutes and means the decision is later
a config edit rather than a code change; skipping it means Phase 5 is five items
instead of six. I lean toward building it, mainly because writing the cache-key
hazard down next to the knob is worth more than the knob is — but it is the one
item here whose value I cannot demonstrate with a measurement.
