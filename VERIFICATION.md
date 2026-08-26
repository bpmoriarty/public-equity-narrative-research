# Verification suite — public equity research (MORN, FY2021–FY2025)

Run 2026-08-07 against commit `0547c37`, in an isolated git worktree
(`%LOCALAPPDATA%\verify-copies\per-verify`) with a fresh `.venv` rebuilt from
`uv.lock`. The original tree was read-only throughout; every artifact written by
this review lives outside it.

> **Paths in this report are as they were on 2026-08-07 and are deliberately not
> rewritten.** This is a dated record of what was found where, so correcting it
> would misrepresent what was reviewed. Three moves have happened since, and the
> translation is mechanical: modules moved from `src/<name>.py` to
> `src/equity_research/<name>.py` (Phase 1); a company's `data/`, `output/`,
> `company.toml` and `corrections.toml` moved under `companies/<TICKER>/`
> (Phase 2); and test files moved from `tests/test_<name>.py` into
> `tests/unit/` or `tests/regression/morn/` by whether they read company data
> (Phase 5.1). Check counts quoted here are as-of the run and have since grown.
> `PROJECT_STATUS.md` and `README.md` carry the current layout.

**Headline.** The evidence layer is verified against ground truth and is sound:
**1,326 of 1,326 ledger quotations are genuine filing text** (a census against the
cached filings, not a sample), the pack rebuilds **byte-identically** from a clean
checkout, and every stage seam reconciles. Residual risk is **not** in the plumbing
— it is concentrated in the thin layer between a fact's *quote* and the *claim built
on it*: one confirmed factual error that reached two deliverables, one class of
citation that does not evidence the number it is cited for, and four latent defects
that today's gates cannot see.

Dimensions run: data-integrity **yes** · pipeline **yes** · statistical **N/A
(justified below)** · claims-evidence **yes**

> **Remediation status, 2026-08-08. Every finding D1–D9 is fixed**, and the
> numeric-evidence detector D2(a) is built, calibrated and enforced as a hard check.
> Nothing from this review is outstanding. See *Remediation log* at the end of this
> file for what changed and how each fix was verified; two measured residues and the
> human-judgment items below are carried forward deliberately, not closed.
>
> Everything below describes the state at commit `0547c37`, when the suite was run,
> and is left unedited so the finding and the fix can be read against each other.
> Since then the pack sha256 has moved `adb27b53…` → `41b0cabb…` → `fd320ce5…`, and
> 35 facts have been renumbered by quote and value repairs — `LEAD-FY2022-b99ce9e7`
> is now `LEAD-FY2022-9fd216a3`, and the nine renumbered ids that were cited are
> mapped in `config/corrections.toml` under `[[id_remap]]`.

---

## Per-dimension summaries

### 1. Data integrity — inputs

The as-of contract under test: *a fact tagged FY N must come from a document whose
coverage period includes FY N.* Falsifier: a fact whose only source covers a
different period.

| Probe | Result |
|---|---|
| Attribution lag (fact FY vs source filing date) | **Consistent.** 10-K, DEF 14A and ARS facts are always +1 (filed the year after the period). 879 8-K facts are +0; the 61 that are +1 are *exactly* the vote-results set. |
| Vote-results as-of basis, all five years | **One rule, five years.** FY2021←May 2022, FY2022←May 2023, FY2023←May 2024, FY2024←May 2025, FY2025←May 2026. No basis drift. |
| Amendments / vintage | 26 in-window amendments; 25 are Form 4/A or SC 13G/A, correctly `out_of_scope`. The one in-scope `8-K/A` is handled correctly — EDGAR's `report_date` for it (2022-05-06) is stale metadata inherited from the original, and the pipeline's filing-date basis lands on the right year for its actual content. |
| Same-event double-count | **None.** The Dec-2022 buyback appears in both the FY2022 and FY2023 ledgers and was correctly merged into one timeline row ("×2 filings"). |
| Shareholder-letter coverage | FY2021 has **no** letter (0 ARS facts); FY2022–FY2025 have 19/22/19/19. The gap is disclosed in both prose deliverables. |
| Low-confidence / unverified flags | 54 low-confidence facts (51 director-bio, 3 investor_qa); all 54 either excluded from prose or flagged inline. |

**Not a leak, but a documentation defect.** The 12 `VOTE-FY2025` facts come from an
8-K filed **2026-05-08**, which `inventory.json` itself marks `in_window=False`
(`in_window` is computed on *fiscal year*, and that 8-K is fy=2026). The attribution
is right — reaching forward is the only way to apply the same rule to FY2025 — but
the declared window (`window_end_date: 2025-12-31`) does not describe the documents
actually used, which run to May 2026. A reader told the window ends 2025-12-31 would
reasonably conclude FY2025 vote results were unavailable.

### 2. Pipeline — plumbing

| Stage | Result |
|---|---|
| Clean-checkout rebuild | **PASS.** `uv sync` from the lockfile, then `build_pack.py` → `pack.json` sha256 `adb27b53…149867c6`, matching the recorded hash exactly. |
| Determinism (run twice, diff all) | **PASS.** `pack.json`, `index.json`, `timeline-events.json` byte-identical. Only `Generated` timestamps differ — benign. |
| `timeline.md` reproduction | **PASS.** Identical to the committed file apart from its `Generated` line. |
| Seam A: inventory → fetch | **PASS.** 127/127 in-scope-or-triage accessions present; no unexplained extras. |
| Seam B: fetch → sections | **PASS.** 231/231 written, 0 failed, 0 problem notes. |
| Seam C: sections → 8-K triage | **PASS.** 75 triage-disposition 8-Ks = 75 triage records exactly; the 17 `in_scope` 8-Ks bypass triage by design (clean partition). |
| Seam D: ledger internal | **PASS.** No id duplicated across 1,329 facts. |
| Seam E: ledger → pack index | **PASS.** 1,329 fact ids + 99 `RISK-` ids = 1,428 index entries; the 99 reconcile exactly with the delta records in `risk-deltas.json` (unchanged 25 / reworded 50 / added 14 / removed 10). |
| Seam F: ledger → timeline | **PASS.** All 85 event+leadership facts placed in exactly one row; none placed twice; corroborated by the producer's own counts block. |
| Seam G: outputs → index | **PASS.** 412 citations across three documents, **all** resolve. |
| Test suite, clean worktree | **PASS, but smaller than in the working tree** — 145 checks vs 151, because `test_generate_outputs.py` silently skips 6 when the gitignored generation records are absent. See D7. |
| `verify_outputs.py`, clean worktree | **PASS.** 12/12 hard checks on both prose documents. |

**Source re-derivation (the biggest lever).** Rather than sample, every quotation was
re-derived from the cached filing text: **1,326/1,326 are genuine filing text.** Zero
misquotations, zero fabrications, zero mis-sectioned quotes.

*A trap worth recording:* the first pass reported 13 failures. Four were artifacts of
comparing against `data/sections/`, which retains image filenames interleaved
**mid-sentence** (`…we are competitive with investorquestions826002.jpg Preqin when…`).
The trimmed copies in `data/triage/text/` — the text actually sent to the model —
strip them, and all four match there exactly. Any future check that verifies quotes
against `data/sections/` rather than the trimmed copy will produce the same false
failures.

### 3. Statistical — **not applicable, and this is a scope fact, not a skip**

The project charter forbids exactly the work this dimension audits: *"Do not build
XBRL parsing, financial statement reconstruction, or ratio analysis."* There is no
estimator, no hypothesis test, no confidence interval, no p-value, no ML metric, no
backtest, and no weighted aggregation anywhere in `src/`. The only counting is
census-style (how many risk factors were added; how many facts a year holds), and
those reconcile exactly against their sources (verified in Seam E).

The one place statistical reasoning *does* enter is `merge_events.py`'s rapidfuzz
similarity threshold (55 for same-date pairs, 95/60/90 for risk-factor diffs). These
are classification thresholds, not estimators. They are tested (`test_merge_events.py`,
24 checks), and their borderline cases are **disclosed in the output itself** —
`timeline.md` names the two same-date pairs left unmerged and the two undated
near-duplicates, including one it identifies as "a single impairment reported twice."
That is the correct treatment.

### 4. Claims–evidence — the words

Traced mechanically: every number in both prose deliverables against the facts cited
beside it. **74 numeric claims checked; `narrative-brief.md` had zero unmatched.**
All 15 unmatched sat in `discussion-points.md`, and triage against the filings
resolved 14 of them as real filing text (see the finding below) and 1 as my own
mis-mapping.

Language calibration is generally careful and deliberately hedged — "aligns with,"
"appears to indicate," "the pack does not contain confirmation." Causal-sounding
headings are backed by management's own stated sequence (the segment-disclosure
change cites the SEC's objection verbatim). The register caveat, the letter gap, and
the low-confidence director-bio caveat are all stated in the body, not buried.

---

## Consolidated defects

Ordered by severity. Every one carries the artifact that demonstrates it.

### D1 — CONFIRMED FACTUAL ERROR. A departure recorded on a date it did not happen, and a deliverable that claims the filings are silent when they are explicit

**Ground truth**, re-derived from the two filings:

- 8-K, filed 2022-05-12: *"On May 6, 2022, Bevin Desmond … **informed** Morningstar's
  Chief Executive Officer that she **has decided to depart** Morningstar **in August
  2022** …"* — an announcement, with a planned date.
- 8-K/A, filed 2023-02-02: *"**As previously reported on the Original Form 8-K**, Bevin
  Desmond has decided to depart … Ms. Desmond's **last day of employment** … **was
  January 31, 2023**."*

One departure: announced 6 May 2022, effective 31 January 2023.

**Three consequences, each independently wrong:**

1. `LEAD-FY2022-b99ce9e7` stores `{"change": "departed", "date": "2022-05-06"}`. She had
   not departed. Note the fact's own `quote` field contains the disproof, and
   `quote_verified: true` — the quote is genuinely verbatim. **`quote_verified` does not
   mean the structured value is entailed by the quote**, and nothing currently checks
   the second thing.
2. `timeline.md` line 29 lists *"6 May 2022 | leadership transition | Bevin Desmond
   departed"* — a dated event on a date it did not occur, in a document SPEC defines as
   "concrete, dated events."
3. `narrative-brief.md` ¶27 states *"the filings do not settle whether these are
   announcement versus effective dates or separate events."* **The filings settle it
   explicitly** — the amendment cross-references the original and gives the last day.
   This is an unsupported claim *about the evidence*, in the direction of false
   ambiguity, and it is the one sentence in the brief a reader could check and find wrong.

**Root cause is a hardcoded template**, not a judgment: [merge_events.py:231](src/merge_events.py#L231)
and [render_timeline.py:264](src/render_timeline.py#L264) emit "…the filings do not
settle it" for *every* date conflict, whether or not they do.

*Generalised probe run:* 6 of 59 dated facts use announcement language while asserting
a completed act. **Five of the six are correct** — they took the stated effective date
(McGarry 2024-01-19, Dubinsky 2024-12-31, Holt 2025-01-01, Dunn 2025-11-21). Desmond is
the outlier precisely because her filing gave only a vague "in August 2022," so the
extractor fell back to the announcement date — and she then left in January 2023 anyway.

### D2 — A whole class of citation that does not evidence its number

**21 facts** carry a `quote` that is a table *lead-in* rather than the data:
*"Each of the nominees for director … was elected with the number of votes set forth
below:"*. 20 are `vote_results`, 1 is an event. **Five are cited in shipped
deliverables.**

The numbers themselves are real — 9 of the 11 disputed figures were confirmed present
in the cited section of the cited filing. The defect is traceability, and it lands
squarely on the project's own promise, stated in the brief's provenance:

> *"Ids resolve in `data/pack/index.json` to the exact quote, section and accession each
> claim rests on."*

For `discussion-points.md`'s director-dissent sentence, resolving `VOTE-FY2023-76c7ae52`
yields the lead-in sentence, **not** `9,935,476`. The reader must go back to the filing
and read the table. `verify_outputs.py` cannot catch this: the figures are stated as
numbers, not quotations, so the verbatim check never inspects them.

### D3 — One mis-citation: right number, wrong id

`discussion-points.md`: *"8,484 shares for $1.4 million by end-2022
[EVT-FY2022-5d620550]"*. That fact comes from the **FY2022** 10-K and contains only the
buyback authorisation. `8,484` appears in the **FY2023** 10-K, captured as
`EVT-FY2023-fc8f78b1` — whose description reads *"only 8,484 shares for $1.4 million
repurchased as of year-end."* The correct id exists and the two were merged in the
timeline; only the prose citation is wrong.

### D4 — LATENT: 9 quotes stored double-encoded

Nine `investor_qa` quotes hold the **literal six-character sequence** `’` where an
apostrophe belongs. Decoded, all nine match the filing exactly, so the text is real and
the storage is corrupt. Contained today: no deliverable contains a literal escape, and
the one affected fact cited in the brief (`QA-FY2025-cef14118`) is paraphrased, not
quoted.

**Why it matters anyway:** if a future generation *quoted* one of these, the corrupted
text would ship **and the verbatim check would pass** — because that check compares the
deliverable against the fact's quote, and both would be corrupt. This is the same
false-assurance shape the project already identified in 10e, one layer deeper.

### D5 — LATENT: 3 facts with `source: null`

`QA-FY2022-e05f5978`, `QA-FY2023-711ef15f`, `QA-FY2024-1e4260bd` have no source block at
all — an id that resolves to a fact with no filing behind it, against a charter rule that
every claim trace to a specific filing. None is cited today, and all three are
`confidence: low` + `quote_verified: false`, so the existing low-confidence gate would
likely catch them. Nothing gates on the null source itself.

### D6 — LATENT: an image-only exhibit reported as a successful extraction

`data/sections/FY2024/8-K/0001289419-24-000014/8-K_EX-99-1_whole.txt` is 163 characters
of filenames and filer boilerplate — a press release published as JPGs. It is recorded
`ok: True` with `problems: []`. One of 231, and it cost nothing (the same content was
captured from the 8-K body). But SPEC puts 7.01/8.01 strategic-announcement exhibits
**in scope**, and CLAUDE.md requires that a silently empty extraction fail loudly. An
image-only *strategic* exhibit would vanish without a trace.

### D7 — The generation records are gitignored, unrecoverable, and 6 tests silently stop running without them

`data/pack/gen-brief.json` and `gen-discussion.json` are the audit record of what the
model actually returned — including `text_before_repair`, the only copy of each
document as first written. They live in `data/pack/`, which is gitignored on this
stated reasoning:

> *"data/pack/ is ignored, and it is the ONE artifact where 'it regenerates' is actually
> true in the sense that matters: it is a pure, deterministic function of
> data/ledger/…"*

That is true of `pack.json` and `index.json`. It is **false of `gen-*.json`**, which are
model output costing ~$3.50 a pass and which no re-run reproduces byte-for-byte. They
are in the same ignored directory as the artifacts the reasoning actually covers.

This is the **third instance of the same reasoning error**, and the first not caught:
`data/ledger/facts/` and `output/` were both rescued from exactly this argument, each
time on the grounds that model output is not regenerable. The gitignore comments record
both rescues.

**Measured consequence:** `tests/test_generate_outputs.py` runs **35 checks in the
working tree and 29 in a clean checkout** — six checks silently dropped, reported as
`29 passed, 0 failed  (0 generated document(s) checked)`. Nothing warns that a third of
the suite's document-level coverage did not run. A clean CI checkout would report green
while testing less.

### D8 — The declared window does not describe the documents used

Covered under Data integrity above. `DATA.md`'s coverage statement should say the
document window runs to **2026-05-08**, and that FY2025 vote results are sourced from
outside the fiscal window by design.

---

## Remediation order

Cheapest and highest-impact first.

1. **D1, the brief sentence and the timeline row.** Correct `LEAD-FY2022-b99ce9e7` to
   record the announcement (or split announcement/effective), and replace the blanket
   template with one that fires only where the filings genuinely conflict. An amendment
   that says "as previously reported on the Original Form 8-K" is a *resolution*, not a
   conflict — detectable mechanically. This is the only defect a reader can catch.
2. **D2, thin quotes.** Either capture the table rows into the `quote` for
   `vote_results`, or have `verify_outputs.py` gate on it: *a sentence stating a figure
   must cite at least one fact whose quote contains that figure.* That check is
   mechanical and would have caught D3 too.
3. **D3**, one-line citation fix.
4. **D4**, repair the 9 stored quotes and add an assertion that no `quote` contains a
   literal `\uXXXX`.
5. **D5**, make `source: null` a hard failure at ledger-build time.
6. **D6**, flag a section whose text is <25 substantive words as a problem rather than
   a success.
7. **D7**, commit `gen-*.json` (or move them out of `data/pack/`), and make the test
   suite **fail loudly** when the generation records are absent instead of quietly
   running 29 checks instead of 35. The data-loss half is urgent — those files are the
   only copy of `text_before_repair`; the silent-skip half is what let it go unnoticed.
8. **D8**, documentation only.

Items 2, 4, 5, 6 and the skip-guard half of 7 are each a few lines, and each closes a
*class*, not an instance.

---

## Human-judgment residue

What no test settles:

1. **Model-family independence was not achievable.** The suite specifies a different
   model family for the independent passes; the same family reviewed its own work here.
   The ground-truth checks (census re-derivation, byte-identical rebuild, seam
   reconciliation) do not depend on reviewer judgment and carry the weight. **The blind
   clean-room diff of the analytical core was not run**, and the skill is explicit that a
   same-family pass is the weakest signal, not a substitute. If any deliverable becomes
   load-bearing, this is the gap to close first.
2. **Is `investor_qa` over-weighted?** 850 of 1,329 facts (64%) come from voluntary
   Reg FD investor Q&A — unaudited, self-selected, and answering questions management
   chose to answer. The documents label the register, but a narrative built 64% on it
   inherits management's framing. Whether that is the right evidentiary mix for an
   investment conclusion is a judgment call.
3. **Is attributing May-2026 votes to FY2025 the right convention?** Internally
   consistent and defensible (say-on-pay in May 2026 votes on FY2025 pay). A reader
   expecting a strict fiscal window may disagree.
4. **Director-bio boundaries remain unverified** — 51 low-confidence board facts. The
   brief flags them; whether board composition claims are usable is the reader's call.
5. **The author is a Morningstar employee analysing Morningstar** (recorded in
   `DATA.md`). The traceability rule is the control for this; nothing in this review
   found a claim sourced from insider knowledge. Worth restating because it is the
   strongest source of the exact bias the rule exists to prevent.

---

## What was verified against ground truth, precisely

- **1,326/1,326** ledger quotations occur verbatim in the filing text they cite (census).
- `pack.json` sha256 `adb27b53…149867c6` reproduced from a clean checkout and a fresh
  environment.
- All substantive artifacts byte-identical across two runs.
- **412/412** citations in three deliverables resolve to indexed facts.
- **85/85** event and leadership facts placed in exactly one timeline row.
- **99/99** risk-delta records reconcile to indexed `RISK-` ids.
- **151** project tests pass in the working tree; **145** in a clean checkout (D7);
  **12/12** hard output checks pass on both prose documents in both.

Not verified: the blind clean-room diff (residue item 1), and the substance of any claim
resting on the 51 low-confidence director-bio facts.

---

## Remediation log

### D1 — fixed 2026-08-07

Four changes, because the defect had a root cause, an instance, and two documents
downstream of it.

**The value.** `config/corrections.toml` is new: human corrections to model-extracted
values, applied by `build_ledger.py` between loading the extraction and building the
fact. `data/ledger/facts/` is not touched — editing the record of what the model
returned would destroy the property that makes the ledger checkable at all. Each
correction carries the filing text that establishes it, and the fact keeps both
values under a `correction` key plus a `data_quality.corrections` entry.

The Desmond fact is now `change: "departure_announced"`, dated 2022-05-06 — an
announcement on the day it was announced. `LeadershipChange.change` gained
`departure_announced` as a distinct enum value, because collapsing it into
`departed` is what put a departure on the timeline on a date it did not happen.

**The id moved, which is the mechanism working.** `fact_id` hashes the value, so the
correction renumbered `LEAD-FY2022-b99ce9e7` → `LEAD-FY2022-9fd216a3` and the brief's
citation stopped resolving. A corrected fact cannot be silently cited under its old,
wrong identity.

**The root cause.** `find_date_conflicts` emitted one hardcoded sentence for every
multi-date group — "the filings do not settle it" — asserted about evidence it had
never read. It now distinguishes **settled** from **unsettled**: an amendment that
back-references the original (`as previously reported`, `the Original Form 8-K`)
supersedes it, and the note says which date is operative. Deliberately conservative —
two amendments, no back-reference, or no date on the amendment all fall through to the
original caveat, which is the right treatment when the filings genuinely disagree.
`render_timeline.py` no longer restates that sentence in its own words; it prints the
note the conflict record carries. Eight tests in `test_merge_events.py` pin both
branches, and they matter more than usual: **the corrected ledger produces no such
group at all**, so the fix has no live data to exercise it.

**The documents.** `generate_outputs.py --apply-corrections` re-renders both
deliverables from their generation records with `[[document_correction]]` entries
applied. No model call, $0.00, idempotent. `text` in `gen-*.json` keeps the model's
own words forever; `shipped_text` is what was published; the correction, its reason
and its reviewer are printed **in the document's own provenance block**, because a
correction the reader cannot see is a hand-edit with better paperwork.

The pack hash is re-stamped — and that is only honest because it is conditional: the
rewrite is refused unless every id resolves and every quotation still verifies against
the pack on disk. Both hashes are printed, so "which payload did the model read" stays
answerable.

¶27 now reads that Desmond announced her departure on 6 May 2022, that the amendment
records her last day as 31 January 2023, and cites the Contract Services Agreement the
original sentence omitted. `timeline.md` shows *departure announced* on 6 May 2022 and
*departed* on 31 Jan 2023, and its legend no longer explains a ‡ marker that appears
nowhere.

*Verified:* both guards fire and write nothing — a ledger correction matching zero
facts is fatal **before** any year file is written (the first version wrote all five
first, and its own test caught it); a document correction whose `find` misses is fatal
with the document unchanged on disk. Re-applying twice is byte-identical. `build_pack`
is still deterministic (`41b0cabb…` twice). All five test files pass; `verify_outputs`
passes every hard check on both documents; `test_fact_id` confirms all 1,329 facts
still reproduce their ids from their own stored content.

### D7 — fixed 2026-08-07

`data/pack/gen-*.json` are committed (`data/pack/*` plus a negation). The `.gitignore`
comment now records all three instances of the reasoning error rather than two.

`test_generate_outputs.py` fails instead of skipping, reporting the two causes
separately — a committed record deleted, versus a pack not yet built — and asserts
that every configured document was checked, so a loop that quietly stops early cannot
pass by checking nothing. *Verified:* exit 1 with a record absent, exit 0 with it
present. 37 checks, up from 35 in the working tree and 29 in a clean checkout.

### D8 — fixed 2026-08-07

Narrower than this report originally framed it. `DATA.md` **already** named the
May-2026 8-K, with the reasoning, in its own section — so the "coverage statement
should say so" half was already satisfied. Re-measuring found the real gap and one
misreading of my own:

| Claim | Measured |
|---|---|
| Filings **outside the fiscal window** (own FY ∉ FY2021–25) | **1** — the named 8-K. `DATA.md` was right. |
| Filings **filed after** `window_end_date` | **6** — the other five are the FY2025 10-K, proxy, two DEFA14As and the ARS, filed in early 2026 because that is when a company reports on a closed year. Ordinary. |
| Document window behind the ledger | **2021-03-12 .. 2026-05-08**, 86 source filings |
| Facts from filings dated after the window end | 95 of 1,326 sourced facts (7.2%) |

So the defect was never a coverage error — it was that **no artifact recorded the
document window at all**, only the fiscal one. The suite read
`window_end_date: 2025-12-31` and reasonably inferred FY2025 votes were out of scope.

Fixed by measuring it rather than writing the date into prose, per CLAUDE.md's rule
against hard-coding a value another stage computes: `build_ledger.py` now emits
`data_quality.document_window` per year and a *Document window* section in
`ledger-report.md`, both derived from the filings that actually sourced facts.
`DATA.md`'s table splits **fiscal window** from **document window** and points at the
computed values; its named-filing section now leads with the
outside-the-window vs. filed-after-the-window distinction, and states why `in_window`
is `false` on a row twelve `VOTE-FY2025` facts depend on.

`discover.py` was deliberately **not** re-run — see D9.

### D2(a) — detector built and calibrated 2026-08-07

The gate proposed in the remediation order — *a sentence stating a figure must cite at
least one fact whose quote contains that figure* — is now in `verify_outputs.py`, as
**three tiers** rather than pass/fail, because the binary throws away the distinction
that decides what to do about a hit:

| Tier | Meaning |
|---|---|
| **QUOTED** | the figure is in a cited fact's `quote` (or a risk delta's `heading`). The provenance promise holds. Not reported. |
| **THIN** | it is in the cited fact's pack `claim` but **not** its quote. Real and traceable — the model read it — but resolving the id shows the reader a table lead-in instead of the number. The D2 class. |
| **UNSOURCED** | it is in no cited fact at all, either way. The serious tier. |

The `claim`/`quote` split is the mechanism: `pack.json` carries `claim`
(`votes_against: 9935476` — what the model was shown), `index.json` deliberately
carries only the evidence. Every checker reads the index, which is why
`check_quotes` could never see this class: the figures are bare numbers, not
quotations, so nothing inspected them.

**Calibrated before it was written**, per 10f's rule that a check firing on correct
documents is worse than no check:

| | figures | QUOTED | THIN | UNSOURCED |
|---|---|---|---|---|
| `narrative-brief.md` | 19 | **19** | 0 | 0 |
| `discussion-points.md` | 65 | 46 | **17** | **2** |

**Zero false positives** — but only after two bugs in the first version of the
tokenizer, both of which reported a defect in the document that was really a defect in
the checker, which is the failure mode that teaches a reader to ignore a check:

1. The lookbehind excluded `$`, so `$200,000` failed to match at the `2` and matched
   the trailing `000` instead — inventing a figure the document never states. Dollar
   amounts are the most common figure in these documents; the first run reported only
   6 figures in the brief, against 19 once fixed.
2. `Item 5.07` — the SEC item number for a shareholder vote — was read as the quantity
   5.07. Asking which filing evidences 5.07 is a category error.

Both are pinned as regression cases in `test_verify_outputs.py` (13 new checks, suite
now 57).

**The 2 UNSOURCED are exactly D3**, found by the check rather than by being told:
`8,484` and `$1.4 million` cited to `EVT-FY2022-5d620550`, which contains neither.

**Left as `review`, deliberately.** UNSOURCED should be promoted to a **hard** check
once D3 clears it to zero — a figure supported by nothing a reader can resolve is not
a style matter. THIN stays review until D2(b) decides whether to capture table rows
into the vote quotes; making it hard today would block every build on a known,
accepted class. The brief's clean 19/19 is asserted in the test suite; the
discussion-points counts deliberately are **not**, because a test pinned to today's
defect count has to be edited every time a defect is fixed.

### D3 — fixed 2026-08-07, and it was two errors, not one

This report recorded D3 as "right number, wrong id." Reading the filing to fix it
found a **second error in the same six words**, which the suite had missed:

- **Wrong id.** `EVT-FY2022-5d620550` is the FY2022 10-K and carries only the
  authorisation — *"approved a new share repurchase program … up to $500.0 million …
  effective January 1, 2023."* No shares, no dollars. The figures are in the FY2023
  10-K as `EVT-FY2023-fc8f78b1`.
- **Wrong date.** The document said the buyback took 8,484 shares *"by end-2022"*.
  The programme was **effective 2023-01-01** — nothing could be repurchased under it
  in 2022. The FY2023 10-K states *"As of December 31, 2023, we repurchased a total of
  8,484 shares for $1.4 million under this authorization"*, and the FY2024 10-K
  corroborates it arithmetically: cumulative **41,784 = 8,484 (2023) + 33,300 (2024)**.

The date error also inverted the sentence's own argument. "Dormant" is demonstrated by
8,484 shares in the programme's *first full year*; dated to 2022 it describes a
programme that had not started, which evidences nothing.

Fixed as a `[[document_correction]]`, so the model's text is preserved and the
correction is disclosed in the document's provenance. No model call, $0.00.

**The detector found this, not a reader.** Those two figures were the only ones in
either deliverable appearing in no cited fact at all. That is the argument for having
built D2(a) first.

*Verified:* UNSOURCED went **2 → 0** across both documents. THIN went **17 → 19** —
correctly, because `EVT-FY2023-fc8f78b1`'s quote stops two sentences before the
repurchase total, so the figure is now traceable but still not evidenced. That is a
D2(b) case and is deliberately left for D2(b) rather than pre-empted for one fact.

**UNSOURCED promoted to a hard check** (`figures_evidenced`). It shipped as `review`
for exactly one commit — long enough to prove it fired on real defects and nothing
else — and is now exercised on failing input as well as passing, per this suite's own
rule. `test_verify_outputs` is at 63.

### Phase 3 — D6, D5, D4 and D2(b), fixed 2026-08-07 in one rebuild

Batched deliberately: all four change a stored quote or a source, `fact_id` hashes
both, so each would otherwise have forced its own pack rebuild and re-citation pass.

#### D6 — a document with no text in it, recorded as a success

The character floor asks *did we get any bytes?*, which a filing published as images
passes. The FY2024 dividend press release is 163 characters — two JPG filenames and a
Workiva stamp — and cleared the 120-character whole-document floor with `ok: true`
and `problems: []`.

A second floor now counts **word-like tokens after stripping image filenames**, which
are exactly what inflates the character count in this failure. Threshold chosen from
the measured distribution, not by feel: **12** substantive words for the defect, **82**
for the next-shortest document (a real SEC comment letter), **354** for the shortest
section any fact cites, 1,437 median. A 70-point gap, so the threshold is not
load-bearing — anything from 15 to 80 separates them identically. Set at 25.

`sections_with_no_usable_text` is its own manifest category and its own headline in
the run output, because a boundary that missed and a document that has nothing in it
are different problems with different fixes. New `tests/test_extract_sections.py`,
17 checks, pinning both directions — the defect must fail, the legitimately short
filings must pass.

*Measured before the fix, which decided the sequencing:* **no fact was attributed to
that exhibit**, so D6 could not manufacture D5 cases and the two were independent.

#### D5 — three facts with no filing behind them, offered as evidence

Not "fatal at build time" as this report proposed. Their existence is the pipeline
working correctly — `attribute()` could not find their quote in any section, so it
recorded no source and marked them low-confidence. Crashing on an ungrounded model
paraphrase would be brittle.

The defect was that they were **citable anyway**: all three sat in `pack.json` (which
the model reads) and in `index.json` (which resolves citations). CLAUDE.md is
unconditional — *if something can't be sourced, it doesn't go in*.

So they are excluded from the pack and kept in the ledger, which closes the class
through a gate that already exists: an id absent from the index is an unresolvable
citation, which `verify_outputs.py` already fails on. Not a silent filter — the
exclusions are counted, listed by id in `pack-report.md`, and summarised on the pack
itself. **The summary carries ids and a count but deliberately no quote text**, since
`pack.json` is the payload the writer reads and including the quotes would hand back
the very evidence the exclusion withholds.

#### D4 — the corruption was in what got stored, not in what got compared

`canon()` **already** decoded literal `\uXXXX` escapes, deliberately and with a
comment explaining why it is safe. The comparison was never fooled. What no one
noticed is that `verify_quote` returned **the model's own string** as the verified
span on an exact match — so the corrupt spelling is what the ledger stored, the pack
indexed, and a document would quote. The function's docstring claimed the opposite:
*"what it holds is always something the filing demonstrably contains."*

Fixed by repairing what is stored, not what is compared. Plus a **fatal** assertion at
ledger build: no stored quote may hold a literal escape. Fatal rather than a warning
because the failure is silent by construction — a document quoting a corrupt fact
passes the verbatim check, since that check compares the document against the same
corrupt string. Blast radius exactly **9 facts**, one of them cited.

#### D2(b) — quote the row, not the sentence introducing the table

The extraction model, asked for a verbatim span supporting a vote result, returned
*"Each of the nominees for director … was elected with the number of votes set forth
below:"* — verbatim, correctly attributed, and containing none of the numbers the
fact asserts. 20 of the 21 thin quotes were that one sentence, repeated per director.

The fix is **selection, not synthesis**. The table renders one cell per line, so a
director's row is itself a contiguous verbatim span containing exactly the claimed
figures. `build_ledger.py` re-anchors onto it, guarded three ways: only for
`vote_results`, only when the current quote lacks the numbers, and the candidate must
still pass `verify_quote` and contain every figure — otherwise the original is kept
and the fact stays reported as thin. **25 facts re-anchored.**

**Residue, stated plainly.** THIN went **19 → 11**. The one remaining lead-in quote is
the FY2021 *event* fact whose claim is "all nominees were elected", which the lead-in
genuinely does evidence. The other 11 are a different class — figures inside
incentive-metric and notable-language facts with no uniform table structure to anchor
on. Closing those needs per-fact judgment rather than a rule, and was deliberately not
attempted: a pipeline that constructs its own evidence should do so only where the
rule is mechanical.

#### `[[id_remap]]` — a third mechanism, and why it is not a correction

Repairing 34 quotes renumbered 34 facts and orphaned **9 citations**. That is the
mechanism working — a repaired fact must not keep being cited under its old identity —
but the documents had to follow.

A correction says the document was wrong. A remap says it was right and the identifier
moved underneath it. Recording both through one channel would misdescribe both. The
practical reason is stronger than the semantic one: **a remap can be checked and a
find/replace cannot.** Every remap asserts the old id is genuinely gone from the index,
the new one is present, and both denote the same claim (same field, fiscal year,
value). A mistyped remap fails the build instead of silently re-pointing a sentence at
a different fact.

Corrections run first, remaps last — a correction's hand-written anchor may contain an
id (D3's does), so remapping first would move it out from under the anchor. Running
remaps last also makes them a final normalisation of every id the corrections wrote.
Disclosed in each document as a count rather than nine hash pairs, so the corrections —
the entries that do change a claim — stay legible.

#### Phase 4 re-verification

The 1,326/1,326 census in this report was measured against the old ledger and expired
the moment 34 quotes changed. Re-earned, not assumed:

| Check | Result |
|---|---|
| Quote census, re-derived from cached filings | **1,326 / 1,326** genuine filing text |
| Stored quotes holding a literal escape | **0** |
| Seam: ledger → pack index | 1,329 − 3 excluded + 99 risk = **1,425**, exact |
| Excluded ids absent from the index | **clean**, no leak |
| Citations resolving across three deliverables | **415 / 415** |
| `build_pack` determinism (twice) | `fd320ce5…` both times |
| `--apply-corrections` idempotence | byte-identical |
| Test suite | 5 files, all pass (`test_extract_sections` new, 17 checks) |
| `verify_outputs` | every hard check passes on both documents |

Pack sha256 moved `41b0cabb…` → `fd320ce5…`.

### D9 — fixed 2026-08-08

Found while fixing D8. `src/discover.py:531` sets `as_of = datetime.now(timezone.utc)`
unconditionally, but the run is cache-first and `sec_requests_made` is `0` — so
`inventory.json` stamps an as-of date on an index it did not fetch.

Contained today, and measurably so: the cached index was written `2026-08-04T17:56:07Z`
and `as_of_utc` says `2026-08-04T18:08:03Z`. Twelve minutes, same day, so every as-of
claim currently in `DATA.md` is sound.

**Why it matters anyway:** the divergence grows without bound. Re-run `discover.py`
from cache a month from now and `inventory.json` will claim a month-fresh index that is
a month stale, with nothing anywhere to contradict it — and `as_of_utc` is exactly the
field a coverage or survivorship claim would be checked against. This is also why D8
was fixed in `build_ledger.py` rather than by regenerating the inventory: re-running
`discover.py` to add a field would itself have falsified the as-of date.

**Fixed, with the contract decided: report both.** `as_of_utc` is now a property of
the DATA — when the submissions index was read from EDGAR — and `run_utc` is when the
artifact was written. They answer different questions, and collapsing them into one
field is what made the first question unanswerable.

A `_meta/fetch-log.json` records each cached document's vintage at the moment of the
live request, which is the only moment that knows it. Documents cached before the log
existed fall back to file mtime and **say so** — `as_of_basis` carries the wording
"inferred, not recorded" — rather than presenting a guess as a record.
`index_age_days_at_run` states the gap, and a run reading an index 7+ days old prints
a warning naming the age and the `--refresh` fix.

Corrected in place: `as_of_utc` moved `2026-08-04T18:08:03Z` → `2026-08-04T17:56:07Z`,
the true fetch time. `discover.py` was re-run from cache with **0 EDGAR requests**, and
all **1,000** inventory rows are byte-identical — only `as_of_utc` changed and five
fields were added.

New `tests/test_discover.py`, 12 checks, pinning the part that fails quietly: that an
inferred vintage labels itself, that a recorded vintage beats mtime, that a corrupt
log degrades instead of crashing, and — the defect stated as a test — that a
zero-request run does not claim its own clock as the as-of date.

### Still open

No findings from this review remain open.

Two measured residues are recorded rather than closed: **11 THIN figures** in
`discussion-points.md` whose facts have no uniform table to anchor on (D2(b)), and
residue item 1 below — the blind clean-room diff, still not run.

Residue item 1 is unchanged: the blind clean-room diff has still not been run, and
these fixes were written by the same model family that wrote the code they correct.
