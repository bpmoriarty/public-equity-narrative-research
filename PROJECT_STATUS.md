# Project: Public Equity Research — Five-Year Narrative History

## What This Is

A reusable pipeline that reads a public company's SEC filings and builds a
five-year narrative history of it: how strategy, leadership, governance, and
risk disclosure changed over time. Input is a ticker and a date range; output is
three Markdown documents (narrative brief, timeline, discussion points) plus a
structured per-year ledger they all derive from.

It is a **narrative and governance** tool, not a financial one. No XBRL, no
financial statement reconstruction, no ratio analysis. Numbers appear only where
they anchor a narrative claim.

**Current subject:** MORN / Morningstar, Inc. (CIK 0001289419), FY2021–FY2025.

---

## Current Status

**Phase:** Verified — build complete, independently reviewed, every finding
remediated. **Productionizing:** the plan at
`C:\Users\bmoriar\.claude\plans\modular-brewing-teapot.md` was approved
2026-08-08. **Phases 0 (hardening tripwires), 1 (packaging) and 2 (the MORN move
+ paths/settings) are complete and pushed** (commits `3c78496`, `a6010bb`,
`8a904df`, `fec3785`, `147a6ee`, `800a543`, `d6201dd`, `446ce88`). **Phase 3 is
two-thirds done** (`0facceb`, `15bd33e`). The repository has a GitHub remote:
https://github.com/bpmoriarty/public-equity-narrative-research

> **The seat-terms question is answered.** Headless Claude Code use fits the
> org's terms and Opus is available on the seat. The operating assumption, from
> the user: **API keys are unavailable in almost every case** for colleagues who
> will use this. That makes the Claude Code backend the only path most of them
> have, not merely the default — and it is why the budget check and the cost
> estimate were both rebuilt to work without an API key rather than degrading to
> "not checked".

> **Phase 3 remaining: `generate_outputs` only.** `model_client.py` exists and
> both `extract_facts` and `build_pack` route through it. `generate_outputs`
> does not, deliberately: its **id-repair** rounds assume a resumed session, and
> the probes showed `--resume` re-writes the whole conversation at 2x rather
> than reading it back. That is a redesign (self-contained, pack-free repair
> carrying an index excerpt), not a call-site swap. The **quote**-repair rounds
> are already pack-free one-shots and need nothing.

> **Colleagues reach Claude Code through VS Code, not the CLI.** The CLI is
> normally not installed; the extension *ships* it, at a version-stamped path
> that moves on every update. `model_client.find_binary` therefore resolves
> PATH → configured path → discovered extension binary (newest wins). This is
> the single point where the pipeline meets the outside world on someone else's
> machine, and it is the thing most likely to break for a colleague.

> **Paths changed in Phases 1 and 2.** Modules live in `src/equity_research/` and
> run as `uv run python -m equity_research.<stage>`; `uv run python
> src/<stage>.py` no longer works. MORN's data, output and two config files now
> live under `companies/MORN/` — `data/`, `output/`, `config/company.toml` and
> `config/corrections.toml` are no longer at the repository root.
> `config/forms.toml`, `sections.toml` and `outputs.toml` stay global.
> The **Important Files** table below is current. Earlier **Session Log** entries
> and the *What's Working* section still name the old paths — those are dated
> records of what was true when written, and are deliberately left as history
> rather than rewritten (26 such references, counted).

**Last Session:** 2026-08-14

**Overall Health:** 🟢 Working — milestones 1–5 complete. **The full verification suite has been run and all nine of its findings are fixed.** 1,329 ledger facts, 1,425 citable ids, three deliverables passing 13 hard checks each. Quote census re-earned after the repairs at **1,326/1,326**. $7.21 spent on generation; remediation cost $0.00 in API calls

### What's Working

- **Environment.** Python 3.13.14, 9 declared dependencies, `uv sync` rebuilds
  from `uv.lock`. API key verified against the Anthropic API at zero token cost
- **Config.** Three TOML files; all parse, all regexes compile, all section keys
  have matching validation bands
- **Milestone 1 — discovery** (`src/discover.py`). Resolves CIK from ticker,
  pulls the submissions index, assigns each filing to the fiscal year it
  *describes*, classifies it, and writes `data/discovery/inventory.json` +
  `discovery-report.md`. Verified idempotent: two consecutive runs produce
  byte-identical output apart from the as-of timestamp, and zero network requests
  once cached
- **Milestone 2 — fetch** (`src/fetch.py`). 201 documents across 127 filings,
  32.8 MB, **zero failures**. Verified: every filing got its primary document,
  every on-disk SHA-256 matches the manifest, no zero-byte or truncated files.
  Re-run downloads 0 — the cache holds
- **PDF extraction** (`src/pdf_text.py`). The FY2022 shareholder letter is
  PDF-only with a broken font encoding; the decoder derives the glyph offset
  from the document and validates the result. Self-test passes: 0 unmapped
  glyphs, 890 digits recovered. Verified it leaves well-behaved PDFs untouched
- **Milestone 3 — section extraction** (`src/extract_sections.py`). 226 of 226
  sections written, zero failures, 6.9 MB of targeted text from 36 MB of raw
  filings. Item 1A additionally split into individual risk factors
  (18/19/25/25/22 by year) so SPEC.md's year-over-year risk diff is possible
- **Boundary-verified:** all three 10-K sections across all five years (item map
  structurally identical each year: 21 items, 1→1A, 1A→1B, 7→7A), plus proxy
  CD&A (FY2022 checked end-to-end) and incentive tables
- **Shareholder letters located.** An ARS is the whole annual report, not the
  letter — 436k–621k chars including the entire 10-K. The letter is now bounded
  on its own conventions (salutation → sign-off, each verified unique per
  document), giving 30k–38k chars per year for four of the five years
- **Milestone 4 — risk deltas, deterministic** (`src/risk_diff.py`). `rapidfuzz`,
  no model calls, so the same inputs always give the same answer and it is
  auditable. One-to-one greedy matching, thresholds in config. Also removes the
  largest section in the filing (Item 1A, 62k–103k chars/yr) from the API budget
- **Milestone 4 — year ledger** (`src/extract_facts.py`, `src/build_ledger.py`).
  34 model calls, 0 failures, **479 facts across five years, 0 unverified
  quotes**. Every fact carries its source filing, an exact quote from it, and a
  confidence marker. 428 high / 51 low
- **Quote verification works, and is proven able to fail.** Confirmed to reject
  fabricated quotes, paraphrased tails, quotes stitched from two passages, an
  extra appended word, and fragments too short to be evidence
- **8-K triage complete** (`src/triage_8k.py`). All 75 conditional 7.01/8.01
  filings judged deterministically, with the evidence for every decision
  recorded: **60 read, 15 date_only**, and all 15 drops are quarterly dividend
  declarations. Config-driven patterns; no model calls
- **Reg FD investor Q&A is in the ledger for all five years** — 850 facts from
  54 filings, in its own `investor_qa` field. MORN publishes written answers to
  investor questions roughly monthly, and nothing else in the corpus carries
  management's voice on strategy at that frequency
- **Every fact and risk delta carries a stable, citable `id`** —
  `EVT-FY2021-23afc21f`, `QA-FY2023-67d4a8e7`. 1,428 of them, checked unique at
  build time, reproducible from the fact's own content. This is what makes an
  output's citations checkable instead of merely present: `(form, FY, accession)`
  identifies a filing, and for an 8-K holding 40 Q&A facts that means "somewhere in
  this document"
- **`output/timeline.md` exists** (`src/render_timeline.py`) — the first of the
  three deliverables. 76 rows: 40 material dated events, 10 routine governance, 26 the
  filings never dated. Rendered **deterministically, no model call**, and it asserts
  its own completeness before writing: every input id appears in exactly one table or
  the run fails
- **Every deliverable passes its constraint gates** (`src/verify_outputs.py`).
  12 hard checks per document — provenance matches the pack on disk, ids resolve,
  quotations are verbatim, low-confidence facts are flagged, vote claims are dated,
  the Reg FD register is established before first use, the shareholder-letter gap is
  named, required sections present, length in range
- **All three deliverables exist.** `output/narrative-brief.md` (2,007 words,
  125 citations) and `output/discussion-points.md` (3,527 words, 202 citations) join
  `timeline.md`. Every id resolves and every quotation is verbatim filing text
- **Outputs are checked, not trusted** (`src/generate_outputs.py`). Two mechanical
  gates — ids resolve, quotations are character-for-character the filing's text — each
  with its own repair pass, and both fatal if anything survives
- **Event records are resolved into timeline rows** (`src/merge_events.py`). 85
  ledger records → 76 rows: 50 dated, 26 period-unclear, 8 corroborated by more than
  one filing, 10 tagged routine. Nothing dropped — every input id lands in exactly
  one row
- **The citable pack is built** (`src/build_pack.py`). 1,428 ids, 332,747 tokens,
  six binding constraints all derived from the ledger rather than hardcoded.
  Byte-stable across rebuilds, which is what lets the prompt cache hit —
  `pack.json` deliberately contains no timestamp
- **The cache now verifies its input** (`--refresh-stale`). "A completed task is
  never re-run" is only safe while its input is unchanged, and a filename cannot
  know what it was computed from. Each cached result stores its `source_chars`,
  and a mismatch stops the run rather than passing as done
- **The quote verifier now has a committed test** (`tests/test_verify_quote.py`).
  Six pass-cases and six reject-cases, run with one command. It exists because
  the normalization has been loosened three times and each loosening is exactly
  when the rejections need re-proving
- **Coverage.** 10-K and DEF 14A complete for all five fiscal years
- **The verification suite has been run, and every finding is fixed**
  (`VERIFICATION.md`). Four dimensions: data-integrity, pipeline, claims-evidence,
  and statistical — the last **N/A and justified**, because the charter forbids the
  work that dimension audits. Nine findings D1–D9, all remediated across seven
  commits, none of which needed a model call
- **The evidence layer is verified against ground truth, twice.** Every quotation
  re-derived from the cached filings — a census, not a sample — at **1,326/1,326**
  before the repairs and again after 34 quotes changed. The pack rebuilds
  byte-identically from a clean checkout, all stage seams reconcile, and 415/415
  citations across the three deliverables resolve
- **Human corrections are data, not edits** (`config/corrections.toml`). Three
  mechanisms, each machine-checked and each fatal if it goes stale: `[[correction]]`
  fixes a ledger value the cited filing contradicts, `[[document_correction]]` fixes
  a sentence in a generated document, and `[[id_remap]]` re-points a citation whose
  fact was renumbered by a repair. `data/ledger/facts/` — the record of what the
  extraction model returned — is never edited
- **A generated document can be corrected without regenerating it.**
  `generate_outputs.py --apply-corrections` re-renders both deliverables from their
  generation records. No model call, $0.00, idempotent. `text` keeps the model's own
  words forever, `shipped_text` is what was published, and every correction prints in
  the document's own provenance — a correction the reader cannot see is a hand-edit
  with better paperwork
- **Figures in prose are now evidenced, not just cited** (`figures_evidenced`, a hard
  check). Three tiers: the figure is in a cited fact's quote, in its `claim` only, or
  in neither. Calibrated on the real documents before it was written and it found a
  real defect on its first run

### What's Broken or Incomplete

- **Two proxy sections have unverified boundaries.** `DEF14A_director_bios`
  (FY2025 known wrong — starts at the front-of-proxy voting summary, not the
  bios) and `DEF14A_proposals_and_votes` (FY2022 correct at 6,883 chars; the
  other four years at 21k–25k likely over-capture). Handled by confidence
  marking, not fixed — see Recent Decisions
- **FY2021 has no shareholder letter at all.** Verified absent, not a lookup
  failure: no ARS filed, and no EX-13 in any of the five 10-Ks
- **3 unverified quotes, and one is a real paraphrase** (0.23% of 1,329). The
  FY2022 case turned "we are gaining traction and seeing increased interest BUT
  have not yet seen significant adoption" into "WE have not yet seen significant
  adoption", dropping the offsetting half — the check earning its keep. The other
  two are false negatives left in place on purpose: recovering them would mean
  tolerating a 12-character tail or gaps in the source, and the second would
  dismantle the stitched-quote defence. See DATA.md, Quote verification.
  **All three are now excluded from the pack** (verification finding D5) — they stay
  in the ledger as the record of what the model returned, but nothing can cite a fact
  with no filing behind it
- **11 figures in `discussion-points.md` are traceable but not evidenced.** Their
  number is in the cited fact's `claim` and not in its `quote`, so resolving the id
  does not show a reader the figure. The vote-table class that produced 20 of these
  is fixed; the residue is incentive-metric and language facts with no uniform table
  to anchor on, and closing them needs per-fact judgment rather than a rule. Listed
  every run by the `figures traceable to a cited fact's claim but NOT to its quote`
  review check. **Not a fabrication risk** — every one was confirmed present in the
  cited filing — but the brief's provenance promise does not hold for them
- **The blind clean-room diff was never run.** The verification suite asks for a
  different model family on the independent passes; the same family reviewed and then
  repaired its own work. The ground-truth checks — census, byte-identical rebuild,
  seam reconciliation — do not depend on reviewer judgment and carry the weight, but
  this is the first gap to close if any deliverable becomes load-bearing
- **`investor_qa` counts are not a series.** FY2023's 231 against FY2021's 113
  reflects how many questions were asked and how long the answers ran, not
  anything about strategy that year. Use the field for what was said, never as a
  trend. See DATA.md limitation 15
- **The 15 dividend drops should be re-read by eye before publication.** The
  classifier is tuned to be wrong in the cheap direction, but the drop list is
  the actual safety net and reading it takes about a minute:
  `uv run python src/triage_8k.py --show date_only`
- **Investor Q&A topics recur across months and are not independent
  observations.** Six near-duplicate pairs in FY2025 — Morningstar Wealth's
  refocusing was answered in June, August and September. A count of Q&A facts is
  not a count of distinct findings. See DATA.md limitation 14
- **`segments` is not comparable across the whole window.** MORN's FY2021 and
  FY2022 10-Ks never say "reportable segment"; FY2023 onward do. So the field
  holds product areas for two years and reportable segments for three, and the
  counts (3 → 10 → 6) must not be read as a re-segmentation of that shape. Each
  year's record carries `data_quality.segments_basis`, detected from the filing
  text. See DATA.md limitation 10
- **Say-on-pay year alignment is a live trap.** `vote_results` for FY N comes
  from an 8-K filed in year N+1, while `events` for FY N may contain the vote
  held *during* FY N, which concerned FY N−1's pay. Both are correctly sourced;
  any output claim must name the meeting date, not just the fiscal year. See
  DATA.md limitation 11

---

## What We're Doing Now

The 8-K triage is done and FY2025's investor Q&A is extracted, at the review gate
the user set: one year first, then decide about the other four.

**All five years are extracted.** The Q&A material is substantive — management on
why PitchBook renewal rates fell ("We have not seen a material change in the
competitive environment"), on Addepar not being a competitor, on conceding that
basic reference data will be commoditized in an AI-first world, and on tying the
TAMP sale, the Morningstar Office wind-down and the CRSP acquisition into one
portfolio-realignment story that the 10-K does not tell in that form.

The ledger on disk represents 88 calls and **$11.33**; total outlay was ~$14,
because a boilerplate-stripping bug (DATA.md limitation 16) invalidated 24 cached
results that had to be re-run. That bug is the main lesson of the session: it
deleted the entire Q&A from eleven filings, and those filings then dropped out of
the extraction plan **without a message** — the run reported 32 successes out of
32 while being 11 short. Both halves are now guarded.

**What triage found that changes a documented assumption.** There are zero Item
2.01 filings in the entire window, despite two completed acquisitions, a
divestiture and two announcements. MORN furnishes deal news under 7.01/8.01. The
`include_items` filter contributed no transaction coverage at all — every
acquisition in the ledger came from the 10-K. Recorded as DATA.md limitation 4.

Milestones 1–4 are done. Both requirements set for milestone 4 were met: every
fact carries a `confidence` marker with its reason, and vote outcomes come from
the 8-K Item 5.07 filings rather than the proxy.

Next is **milestone 5, the three outputs** in `output/`. Everything they need is
in `data/ledger/`, and SPEC.md §3 is explicit that they derive from the ledger,
never from raw sections.

### Milestone 5 complete. 10a–10f done.

Scoped 2026-08-05, three design questions answered (see Recent Decisions), sizing
below measured rather than estimated.

**10a — fact ids — is done.** 1,428 ids (1,329 facts + 99 risk deltas), unique,
reproducible, and verified additive: strip the two new keys from the rebuilt ledger
and it is byte-identical to the pre-change snapshot in all five years. Rebuilds are
still byte-identical to each other. `tests/test_fact_id.py` locks the design in.

**10b — the citable pack — is done.** `data/pack/pack.json`, 1,428 citable ids,
332,747 tokens, byte-stable, plus `index.json` for the output checker and
`pack-report.md` for the run metadata.

**The finding that shaped it: only `quote` is verified text.** Of the 1,741 `value`
strings in the ledger longer than 40 characters, **just 3.1% appear verbatim in
their own fact's quote.** The other 96.9% are model-written summaries, and
`verify_quote` never ran on them — it only ever checked the `quote` field. So an
output that puts a `value` string in quotation marks is quoting the extraction
rather than the company, and nothing downstream would catch it. The pack therefore
carries every quote despite the cost, names the two things `claim` and `quote`, and
constraint 5 says only one of them may be reproduced as the company's words.

**The pack is bigger than scoped, and the milestone estimate still holds — for a
different reason than assumed.** Scoping assumed a 219K-token quote-free pack at
$1.10 a call; requiring quotes puts it at 332,747 tokens and $1.66. But only two of
the four generation calls need the whole pack (the brief, and the observations half
of discussion-points); the timeline and the stated-vs-paid-for-priorities call each
need a small subset. First pass ≈ **$3.53**, review rounds $1.00–$2.50, all-in
**$6–10** — the originally scoped range.

**Caching is not automatically cheaper**, and the pack report now prints the
break-even rather than assuming: a cached read is 0.1x input price, so a 5-minute
cache (1.25x write) pays from 1.4 reads and a 1-hour cache (2x write) from 2.3.
Below that, paying full price each time wins.

**10c — event merging — is done.** 85 records (`events` + `leadership`) → 76 rows:
50 dated, 26 period-unclear, 8 corroborated, 10 routine. All 85 input ids land in
exactly one row.

**The discriminator is "different filing", not similarity.** Similarity alone cannot
separate the two credit-agreement records that ARE one event (72.9) from the two
Bevin Desmond agreements that are NOT (61.7) — eleven points apart, and a threshold
between them would be luck. But a filing does not report the same event twice, so
requiring different filings excludes the second case by construction and the
threshold then lands in an eleven-point gap (59.6 → 48.5) rather than a three-point
one. Merging is transitive, which is how the three FY2025 refinancing records become
one row despite two of them sharing a filing.

**Routine governance is tagged, never dropped**, and the override list exists because
of a real near-miss: "Shareholders approved the ... Amended and Restated 2011 Stock
Incentive Plan" sits on the same date, in the same meeting, as four genuinely routine
votes — and an incentive plan change is a row type SPEC.md §4b names explicitly. An
earlier plan to drop "the annual-meeting vote outcomes" would have taken it too.

**10d — `output/timeline.md` — is done, and it needed no model call.** That is a
design decision, not a shortcut. SPEC.md §4b asks for a reference table where every row
carries a source, and every field it needs is already in the ledger: date, precision,
type, description, source ids, confidence, corroboration count. The only thing a model
could add is rewriting descriptions — and `claim` text is *itself* model-written and
unverified, so condensing it puts the reader two steps from the filing with no check
possible at either step. A deterministic render cannot fabricate a date, drop a row or
drift a description. The $0.30 saving is incidental; if the model added something
checkable it would be worth paying for.

**Reading the first draft surfaced four things**, which is exactly why the timeline was
scheduled before the prose:

1. **Undated rows must never be merged**, and not for the reason I first wrote. Among
   the 26, the two closest pairs are **1.5 points apart** and opposite: 98.9 is one
   SmartX impairment reported twice, 97.4 is two *different years* of dividend guidance
   whose wording is templated. Merging on text would have collapsed four years of
   distinct guidance into one row
2. **One event is dated inconsistently by the filings** — Bevin Desmond's departure is
   2022-05-06 in one 8-K and 2023-01-31 in another. Both kept, marked ‡, neither
   presented as correct. Detected from *structured fields*, not text: at a 100.0 text
   score the Desmond conflict is indistinguishable from two genuine Jason Dubinsky role
   changes, but the role strings differ so the structured key separates them
3. **Four dated rows predate FY2021** (a 2019 credit agreement, the 2020 Sustainalytics
   buy-in, 2020 senior notes, 2020 repurchase authorisation). Real and sourced from
   in-scope filings, so marked *(predates the window)* rather than dropped
4. A raw enum (`role_changed`) was leaking into prose descriptions

**10e is done: `narrative-brief.md` (2,007 words) and `discussion-points.md`
(3,527 words) both exist**, written from the pack in two calls sharing a cached
prefix. $7.00 all in, against a $2–3 estimate — the overrun is explained below and it
bought something.

**The finding: the id check gives false assurance.** Both documents are held to two
mechanical checks, and they disagree sharply about how sound the prose is:

| Check | First-run result |
|---|---|
| Every `[ID]` resolves to a fact in the pack | 323 of 324 |
| Every quotation is character-for-character the filing's text | **110 of 118** |

Ids are opaque strings sitting beside the fact and the model copies them accurately.
Quotations are reconstructed from memory of something read 300,000 tokens earlier, and
**a quotation one word off looks exactly like a correct one** — while a sentence
carrying a resolving id and a misquotation reads as *more* sourced than an unsourced
one. The filings say margins are in the "low 20's percent range"; the draft quoted
"low 20 percent range". The worst case was a verbatim phrase, "cannot be made", welded
into a claim about segment-level profitability — its only occurrence in the pack is a
fact about assessing the impact of tax legislation. That is a fabricated claim wearing
a real citation, and only the quotation check sees it.

All of it is repaired, by a targeted call that does **not** resend the pack (~$0.30 a
document instead of $2.22). Both documents now stand at zero defects — 44/44 and 65/65
quotations verbatim in a fact cited alongside, every id resolving — and the brief's
citation count *rose* 122 → 125, because three repairs added the id the phrase
genuinely came from rather than cutting the sentence. `tests/test_generate_outputs.py`
locks all of it, every fixture a real string from the first run.

**A cache lesson worth carrying.** The 5-minute cache expired *between* calls, because
the discussion-points call itself took longer than five minutes to produce 27,000
output tokens. Its repair round then paid a fresh $2.22 write instead of a $0.18 read.
The break-even table in `pack-report.md` assumes reads arrive promptly; when a single
call runs for minutes, the 1-hour cache is the right choice even below its nominal
2.3-read break-even.

**10f is done.** `src/verify_outputs.py` holds each deliverable to the pack's
binding constraints — **12 hard checks and 2 review lists per document**, deterministic
and free, non-zero exit on any hard failure. Both documents now pass every one.

**The design decision that matters here: a check that fires on correct documents is
worse than no check.** It trains whoever reads the report to skip that line, and it is
still firing on the day it is right. So checks are hard (decidable, gating) or review
(known false positives, listed for a human, gating nothing) and never a blend. Two
constraints could only be review lists, and measurement is why: "never compare segment
counts" first fired on 6 sentences of which **6 were false positives**, and Reg FD
labelling flagged **23 of 36 paragraphs** because the documents name the register once
and let the `QA-` id prefix carry it thereafter.

**It caught a real defect on its first run.** The brief cited shareholder letters for
FY2022–FY2025 and never said FY2021 has none — while discussion-points stated the gap
explicitly. That is exactly the risk constraint 6 names: an apparent change in
leadership voice at that boundary may be a missing document rather than a change in
tone. Repaired for $0.21.

Two things worth knowing before the verification suite:

- **The uniqueness check caught a real collision on its first run.** 46 reworded
  risk deltas shared ids because `risk_delta_id` read `item["heading"]`, which
  exists on `added`/`removed`/`unchanged` deltas but NOT on `reworded` ones — those
  carry `heading_now`/`heading_prior`. All 46 hashed a `None` heading. The fix
  inverted the logic: hash every key on the item EXCEPT the named measurements, so
  a forgotten key causes visible churn rather than a silent collision
- **`LedgerFact` gained `fiscal_year`.** The three facts whose quotes could not be
  verified have no `source`, so until now they had no way to say which year they
  belonged to — a latent gap the id work exposed rather than created

**Payload sizes, from `count_tokens` rather than chars/4:**

| Pack shape | chars | tokens | $ per call (in) |
|---|---|---|---|
| All fields except `investor_qa`, no quotes | 185,243 | 73,555 | $0.37 |
| All fields, no quote text — **the working pack** | 582,543 | **219,406** | $1.10 |
| All fields with quotes | 900,443 | 320,046 | $1.60 |

The whole ledger fits one context with room to spare, so **do not pre-summarize**
— a model-written digest between the filings and the outputs is the one layer this
pipeline exists to avoid. Send claim + source + confidence; hold quotes back until
a writer must reproduce one.

`investor_qa` is **64% of the ledger by volume** (850 of 1,329 facts, 769K of 1.14M
chars). Any document written from this pack drifts toward Reg FD material by
gravity alone. The user chose full weight with labels — so the labelling is what
holds the line, and it has to be enforced, not trusted.

**Cost, with a 1-hour prompt cache on the shared 219K-token prefix:** ~$3.50 first
pass (cache write $2.19 + 4 reads $0.44 + ~35K output $0.88), then ~$1.30 per
review round. **All-in $6–10** for two or three rounds; $13–20 uncached.

**Time:** ~2–3 hours of build (pack builder, fact IDs, event dedup, four prompts,
citation checker); ~15 min of API runtime per full regeneration round.

**Four calls, not three.** `discussion-points.md` splits: the stated-vs-paid-for
priorities section gets its own call on a tight payload (`incentive_metrics` ×
`strategic_priorities` × `notable_language`, ~15K tokens). SPEC.md §4c calls that
divergence "the single most useful thing this pipeline can surface" — it should not
be the third subsection of a call already juggling 1,329 facts.

**Generate `timeline.md` first.** It is the cheapest to check for correctness, and
it surfaces the dedup problems below before they propagate into prose.

### Six findings from the scoping that milestone 5 has to handle

Found by measuring the ledger, not by reading code:

1. **No fact IDs.** A fact carries `(form, fiscal_year, accession, section_key)` —
   which identifies a *filing*, not a fact. For an 8-K holding 40 Q&A facts a
   citation means "somewhere in this document," weaker than the standard this
   project set. Fix is deterministic: a content hash per fact in `build_ledger.py`
2. **20 duplicate event records** — the same event reported by two filings. The
   Shenzhen restructuring in FY2022 and FY2023; the $500M buyback in FY2022 and
   FY2023; the DBRS SEC settlement in FY2023 and FY2024; the Commodity & Energy
   divestiture in FY2024 and FY2025. The timeline must merge these — and the
   duplication is an **asset**: two independent filings corroborating one event
3. **26 of 74 events carry no date** and cannot enter a chronological table as-is
4. **Five FY2021 "events" are annual-meeting vote outcomes** — director elections,
   auditor ratification, say-on-pay. They belong to `vote_results` (61 facts
   already) and would pad the timeline with routine governance
5. **No FY2021 shareholder letter** — already DATA.md limitation 8, re-confirmed
   here against the submissions feed (MORN's first ARS filing is 2023-03-31) and
   now quantified: letter-voice evidence is 10–11 `notable_language` facts per
   year from `letter_full_text` in FY2022–FY2025 and **zero** in FY2021. Any
   sentence about "five years of shareholder letters" would be false
6. **`ledger-report.md` carries a misleading warning** about FY2021's missing
   `letter` task, because the check cannot tell "not extracted" from "no such
   section exists". A false alarm in an audit artifact trains you to ignore the
   real ones

### Five constraints the finished outputs must satisfy

Enforce in a `verify_outputs.py` pass rather than trusting the prose. Three of the
five become mechanical once facts have IDs:

1. **No claim rests on a `low` fact without saying so** — 54 of 1,329 (51 board
    facts with unverified proxy boundaries, 3 unverified quotes). If the board
    narrative turns out to matter, fix those boundaries first (Next Steps item 11)
2. **Never compare segment counts across FY2022/FY2023.** The basis changes from
   product areas to reportable segments. Use segment names and the filing's own
   language instead
3. **Name the meeting date for any say-on-pay claim**, because the vote on year
   N's pay happens in year N+1
4. **`investor_qa` is labelled Reg FD wherever it is leaned on**, and its counts
   are never presented as a series
5. **Every citation resolves to a fact that exists**

Actual cost of milestone 4: **$4.52** (571,664 input / 66,406 output tokens
across 34 calls). Milestones 1–3 cost nothing.

---

## Recent Decisions

| Date | Decision | Why |
|------|----------|-----|
| 2026-08-08 | **`as_of` is a property of the DATA; `run_utc` is a property of the artifact** | `discover.py` is cache-first and `as_of_utc` was `datetime.now()` unconditionally, so a run making zero EDGAR requests stamped its own clock on an index fetched days earlier — in a file that said `sec_requests_made: 0` on the next line. Wrong by twelve minutes when caught, and the error grows without bound. Both are reported now, and a vintage inferred from file mtime says so rather than passing as a record |
| 2026-08-08 | Corrections are **data with three distinct shapes**, never edits | A ledger value the filing contradicts, a sentence in a generated document, and a citation whose fact was renumbered are three different operations. Folding them into one channel would misdescribe all three — and the id remap is the one that can be *machine-checked* (old id gone, new id present, same claim on both sides), which a free-text find/replace never can |
| 2026-08-08 | `data/ledger/facts/` is **never edited**, whatever the defect | It is the record of what the extraction model actually returned, and it is what makes every quote checkable after the fact. A corrected file and a correct-in-the-first-place file are indistinguishable once you overwrite it. Corrections apply on the way into the ledger instead, and the fact carries both values |
| 2026-08-08 | A correction must be **visible in the document**, not only in the JSON | A correction the reader cannot see is a hand-edit with better paperwork. Each one prints in the provenance block with its reason and reviewer; renumberings print as a count, so the entries that actually change a claim stay legible |
| 2026-08-08 | The pack hash may be re-stamped **only if the document still verifies against it** | The hash is the reader's guarantee that the evidence has not moved underneath the prose. Re-stamping after a ledger repair would be a lie if any citation had gone stale — so the rewrite is refused unless every id resolves and every quotation is still verbatim, and both hashes are printed |
| 2026-08-08 | A fact with **no source is excluded from the pack**, not made fatal | Their existence is the pipeline working: `attribute()` correctly records that an ungrounded paraphrase has no filing. Crashing on that would be brittle. The defect was that they were citable anyway — so they stay in the ledger and leave the pack, which closes the class through a gate that already exists (an id absent from the index is an unresolvable citation) |
| 2026-08-08 | The extraction floor counts **words, not characters** | A character floor asks "did we get any bytes?", which a filing published as images passes — 163 characters of JPG filenames cleared it with `ok: true`. Threshold set from the measured distribution (12 for the defect, 82 for the next-shortest real document), so it is not load-bearing: anything from 15 to 80 separates them identically |
| 2026-08-08 | A vote quote is **the table row, not the sentence introducing the table** | Selection, not synthesis: the table renders one cell per line, so a director's row is itself a contiguous verbatim span containing exactly the claimed figures. Guarded three ways and it falls back to the original quote if any guard fails — a pipeline that constructs its own evidence should only do so where the rule is mechanical |
| 2026-08-07 | **`quote_verified: true` does not mean the value follows from the quote** | The Desmond fact stored `change: departed, date: 2022-05-06` with a genuinely verbatim quote that says she *informed the CEO she had decided to depart in August*. The quote contained its own disproof. Two independent things need checking and only one was: that the quote is real, and that the structured value is entailed by it |
| 2026-08-07 | A new check ships as **review for one commit**, then earns `hard` | `figures_evidenced` was calibrated on the real documents before it was written, shipped as a review list, fired on two real defects and nothing else, and only then was allowed to stop a build. The same doctrine as 10f: a check that fires on correct documents is worse than no check |
| 2026-08-07 | Detection is built **before** the defect it will find is fixed | D2(a)'s numeric gate was built first and then located D3 by itself, rather than D3 being fixed by hand and the check trusted on assertion. It also proved the check on a known positive |
| 2026-08-04 | Python 3.13, not 3.14/3.15 | Matches `sec-extraction-v3`; `tomllib` in stdlib, full wheel coverage |
| 2026-08-04 | Version floors (`>=`), not exact pins | Building now, not reproducing a validated run. Tighten `edgartools`/`beautifulsoup4`/`lxml` to `==` once hand-checked end-to-end |
| 2026-08-04 | `tomllib` for config, no TOML package | Only reading config, never writing it |
| 2026-08-04 | `rapidfuzz` for risk-factor diffing | SPEC.md §2 needs *materially reworded* factors — fuzzy matching, which `difflib` does poorly at scale |
| 2026-08-04 | Own cache in `data/raw/`, not `EDGAR_LOCAL_DATA_DIR` | Cache visible in the project layout, matching CLAUDE.md's structure |
| 2026-08-04 | Risk factors extracted as a **list**, not one blob | Diffing needs per-factor granularity; a blob can only be summarized |
| 2026-08-04 | **Config is read-only to the pipeline** | `tomllib` cannot write TOML, and writing it would strip every comment. `data/discovery/inventory.json` is the machine source of truth instead |
| 2026-08-04 | Config `cik` / `resolved_name` are **tripwires**, not inputs | Discovery always resolves from the ticker; a mismatch is a hard error. A wrong CIK doesn't fail, it silently returns another company's filings |
| 2026-08-04 | `reportDate` is trusted **only** when it lands near the fiscal year end | On a DEF 14A it's the annual meeting date; on some ARS filings it's the filing date. Trusting it misdated every proxy by a year |
| 2026-08-04 | Item 2.02 outranks 7.01/8.01 in 8-K classification | A routine earnings 8-K is filed as `2.02, 7.01, 9.01`; checking 7.01 first buried 19 releases in the triage queue |
| 2026-08-04 | **Scope extended** to `DEFA14A`, `UPLOAD`, `CORRESP` | Supplemental proxy material and SEC comment letters are governance evidence. Beyond SPEC.md's four forms — recorded in a reversible block in `config/forms.toml` |
| 2026-08-04 | Fetch **all 75** triage 8-Ks rather than sampling | User decision. Cheap (small documents), and avoids a second EDGAR pass later |
| 2026-08-04 | Document selection **errs toward keeping** | Re-fetching is what the cache exists to prevent. This retained EX-97 (clawback policy) and EX-19.1 (insider trading policy) — both governance-relevant |
| 2026-08-04 | Skip XBRL/rendering assets and compliance boilerplate | 2,693 of 2,894 documents. EX-21/23/24/31/32 are certifications and consents with no narrative content |
| 2026-08-04 | Document types come from submission SGML via `edgartools` | EDGAR's `index.json` `type` field is the *icon filename* (`text.gif`), not the document type — useless for identifying exhibits |
| 2026-08-04 | `pdfminer.six`, **not** `pypdf`, for PDF text | pypdf coerces unmapped glyphs toward whitespace, turning every digit in the FY2022 letter into a space — "fell 15%" became "fell". pdfminer preserves them as `(cid:N)`. Prefer the library that preserves what it can't interpret |
| 2026-08-04 | Glyph offset **derived**, not hardcoded | Taken from the space glyph's frequency and validated against English sentinel words, so the decoder isn't silently wrong on a different company's font |
| 2026-08-04 | The dual em-dash/minus glyph maps to ASCII `-` | One glyph serves both. A hyphen for an em dash is cosmetic; a lost minus sign inverts a fact |
| 2026-08-07 | **A check that fires on correct documents is worse than no check** | It trains the reader to skip that line, and it is still firing on the day it is right. So every check is hard (decidable, gates the run) or review (known false positives, listed for a human, gates nothing), never a blend. Measured: "never compare segment counts" fired on 6 sentences of which 6 were false positives; Reg FD labelling flagged 23 of 36 paragraphs. Both became review lists with tightened detectors |
| 2026-08-07 | Every hard check is tested against a document that **fails** it, not only one that passes | A check exercised only on passing input would still pass if its body were `return True`. That is the failure mode that makes a verification suite worse than none, because it reports success either way |
| 2026-08-07 | `verify_outputs.py` reads the **rendered Markdown**, and reuses the generator's own quote/citation functions | Two implementations of "is this quotation verbatim" would drift, and the one that drifted quietly would be the one that mattered. The independence that matters is the input, not a second opinion: reading the file on disk catches a hand-edited document, one written from a different pack, and one whose provenance no longer describes it |
| 2026-08-07 | **Quotations are checked separately from ids, and the quotation check is the one that finds defects** | Measured on the first run: 323/324 ids resolved but only 110/118 quotations were verbatim. An id is copied from beside the fact; a quotation is reconstructed from memory of text read 300,000 tokens earlier, and one word off looks identical to correct. A sentence with a resolving id and a misquotation reads as *more* sourced than an unsourced one, so the id check alone misleads |
| 2026-08-07 | A verbatim quotation attached to the wrong claim is **a fabricated claim, not a citation error** | The brief quoted "cannot be made" in a sentence about segment-level profitability; the phrase's only occurrence in the pack is a fact about assessing tax legislation. So the check records where each such phrase actually came from, and the repair is told to delete the claim unless that source genuinely supports the sentence |
| 2026-08-07 | The quotation repair **does not resend the pack** | It needs the document and the handful of quote fields in question — about 8,000 tokens against 354,000 — so it costs ~$0.30 a document instead of $2.22, and can repair documents already on disk rather than forcing a $6 regeneration to fix seven quotations |
| 2026-08-07 | `discussion-points.md` is **shown the brief, explicitly as a non-source** | The two documents read the same evidence for related purposes and overlap heavily without it. It is passed after the cache breakpoint, may not be cited, and any claim carried over must be re-sourced from the pack |
| 2026-08-06 | **`timeline.md` is rendered deterministically — no model call** | Every field the table needs is already in the ledger. The only thing a model could add is rewriting descriptions, and `claim` text is itself unverified model output (3.1% verbatim), so condensing it would put the reader two steps from the filing with no check at either step. A renderer cannot fabricate a date, drop a row or drift a description, and it asserts completeness before writing. The cost saving is incidental |
| 2026-08-06 | Date conflicts are detected from **structured fields, not text similarity** | At a text score of 100.0 this window holds one real conflict (a departure dated 2022-05-06 and 2023-01-31 by two filings) and one non-conflict (two genuine role changes a month apart). The structured key (name, change, role) separates them because the role strings differ; a similarity score reads both as identical. Both dates are kept and neither is presented as correct — CLAUDE.md on contradictory filings |
| 2026-08-06 | Rows predating the window are **marked, not dropped** | Four dated rows fall before FY2021 because in-scope filings describe them. They are real and sourced, so a five-year timeline marks them *(predates the window)* rather than silently opening two years early or silently discarding them |
| 2026-08-06 | Two records are one event only if they come from **different filings** | Similarity alone puts a true positive (72.9, the 2022 refinancing across two filings) three points from a true negative (61.7, one 8-K reporting two agreements with the same officer on one day). A filing does not report the same event twice, so requiring different filings excludes the negative by construction and moves the threshold into an eleven-point gap. 55 is the middle of that gap, measured |
| 2026-08-06 | Merging is **transitive**, and keeps every member's wording | Three records describe the FY2025 refinancing — the whole transaction, the entry, the termination — and two of the three share a filing, so they only join through the third. Pairwise merging would have left two rows for one event. The merged row keeps all source ids, all descriptions in `also_described_as`, and the LOWEST confidence across members, so merging cannot promote a `low` fact |
| 2026-08-06 | Routine governance is **tagged, not dropped** | Same reasoning as `src/triage_8k.py`: a silent drop loses real events undetectably. The material-override list exists because of a specific near-miss — the 2011 Stock Incentive Plan approval shares its date and meeting with four routine votes, and an incentive plan change is a timeline row type SPEC.md §4b names outright |
| 2026-08-06 | Timeline rows in the full pack **carry no quotes** | Every row's `ids` resolve to facts in the same payload that already hold those quotes; repeating them measured 8,119 tokens of pure redundancy, and two representations of one event is a way to get inconsistent output. `timeline_block(include_quotes=True)` is there for the standalone timeline payload, which does not carry the facts |
| 2026-08-06 | The pack carries **every quote**, at a third of its size | Measured: only 3.1% of `value` strings appear verbatim in their own quote, so `value` is a paraphrase and `quote` is the only verified text in the project. Dropping quotes would have saved ~100K tokens and left the pack with no quotable text at all, making every quotation in every output unverifiable by construction |
| 2026-08-06 | **`pack.json` contains no timestamp** | It is the shared cached prompt prefix, and prompt caching only hits on a byte-identical prefix. A `generated_utc` field would turn every $0.17 cached read into a $1.66 full-price call with nothing looking broken except the bill. Run metadata lives in `pack-report.md` |
| 2026-08-06 | The payload is **compact JSON**; the index stays readable | Compact separators measured 34,741 tokens cheaper (367,489 → 332,748) with no content removed. `pack.json` is model input so every byte is paid for on each call; `index.json` is a local lookup that is never sent anywhere, so its size is free |
| 2026-08-06 | Constraints are **derived on every build**, never written down | A constraint reading "54 facts are low confidence" when the number has become 61 is worse than no constraint, because it reads as though someone checked. All six recompute from the ledger — including which years use reportable segments and which years have a shareholder letter |
| 2026-08-06 | `data/pack/` is gitignored, and the **sha256 is what makes that safe** | It is the one artifact where "it regenerates" is true in the sense that matters: a pure deterministic function of the committed ledger. Committing it stores a second copy of 900 KB. The hash in `pack-report.md`, stamped onto every output, preserves the answer to "which payload was this written from" |
| 2026-08-06 | **`output/` is committed, not ignored** | Found by the preflight check before any output existed to lose. The old rule said "final deliverables regenerate from data/ledger/", which is false in the way that matters: they are model-written prose, cost ~$3.50 a pass, and will not reproduce byte-for-byte. Same reasoning that already put `data/ledger/` in git |
| 2026-08-06 | Ids are logged in `data_quality`, scoped to **within-year** | Also a preflight finding: ids became a load-bearing analysis variable and nothing in the artifact recorded that they were audited — only the build's stdout did. The block deliberately claims only within-year uniqueness, because it is written before the cross-year audit runs. Over-claiming in a data-quality block is worse than claiming less |
| 2026-08-06 | Fact ids hash **content and evidence, never judgments** | The id covers field, fiscal_year, value, source form/accession/section_key and quote. It excludes confidence, confidence_reason, quote_verified, quote_check and filing_date. If the director-bio boundaries are fixed later, 51 board facts flip `low` → `high`; were confidence in the hash, every citation to them in an already-written brief would break — for a change that made them *more* trustworthy. A changed quote, by contrast, *should* mint a new id, because the evidence moved |
| 2026-08-06 | Risk deltas get ids too, hashed by **exclusion** not inclusion | An output will say "the cybersecurity risk factor was reworded in FY2024", and a checker that cannot resolve that leaves a whole category of claim unverifiable — enough to make the check decorative. Naming the identity keys is what caused the 46-way collision, because the three delta categories have three different shapes. Naming the *measurements* to exclude fails toward visible churn instead of silent collision |
| 2026-08-06 | Ids are checked for collisions at build time, **fatally**, across every year on disk | Not just the years rebuilt — a partial `--fy 2023` run still audits all 1,428. Two facts sharing an id makes a citation ambiguous, and that is exactly the failure the id exists to prevent. It fired on the first run, which is the only reason the reworded-delta bug was found in minutes rather than in a written output |
| 2026-08-06 | Example ids in generated documents must be **real** | The first draft of the ledger-report header used a plausible invented id, and the DATA.md draft did it again. A citation-shaped string that resolves to nothing has no place in the document explaining how citations work. Both now carry ids pulled from the build |
| 2026-08-05 | **Reg FD Q&A carries full weight in the outputs, labelled** | User decision, against the recommendation of corroboration-only. It is 64% of the ledger and contains management's clearest strategy statements — material the 10-K never addresses. The cost is that the brief's centre of gravity sits on unaudited, unprompted disclosure, so the Reg FD label is load-bearing and must be enforced by the output checker rather than left to the prose |
| 2026-08-05 | Undated events get a **separate "period unclear" block**, not a guessed date | User decision. 26 of 74 events carry no date. Placing them at their filing's date would put them in the wrong place on the timeline — a February 10-K reports the prior year — and dropping them would silently lose a third of the events. A second table loses nothing and invents nothing |
| 2026-08-05 | Facts get **content-hashed IDs** and outputs get a citation checker | User decision. ~45 min of build, $0 in API cost. Every citation resolves to a specific fact or the build fails, which turns three of the five output constraints from trusted into mechanical. Same principle as `verify_quote`: measure traceability, do not assert it |
| 2026-08-05 | The boilerplate stripper **fails toward keeping text** | It previously assumed an unterminated forward-looking caution ran to the end of the document. In eleven filings the caution was terminated by the Q&A heading instead, so the stripper deleted ~8,700 of ~9,000 characters. Stripping boilerplate is a cost optimization and losing content is a correctness failure; when the two conflict, the optimization loses |
| 2026-08-05 | A filing routed to a task but yielding **no readable document is fatal**, not skipped | This is how the eleven went missing: `read_section_keys` came back empty, the loop moved on, and the run reported 32 of 32 successful while being 11 short. Nothing anywhere looked wrong. Triage saying "this carries content" and extraction finding none is a contradiction, and a contradiction has to stop the run |
| 2026-08-05 | The cache **verifies its input**, not just its filename | Fixing the stripper changed the source text under 24 already-cached results, silently. A cache keyed on a filename cannot know what it was computed from, so each result stores its `source_chars` and a mismatch is reported and refused rather than treated as done |
| 2026-08-05 | Near-miss tolerance stays at **3 characters** despite two known false negatives | Widening it to 12 would recover a `_PLACEHOLDER` artifact and also admit genuinely paraphrased endings. The real FY2022 paraphrase found this session is 96% character-exact — the margin between artifact and paraphrase is thin, and the conservative side of it is the useful one |
| 2026-08-05 | Triage is allowed to be confident **only about "read"** | The two errors do not cost the same. A false read costs a fraction of a cent; a false date_only deletes a corporate event from a five-year history and nothing downstream can detect it. So `date_only` needs positive evidence of a routine filing AND no material signal anywhere, and anything unrecognised is read |
| 2026-08-05 | Match **position** is recorded, not just match presence | A keyword scan flagged 42 of 75 filings as deal-related against roughly 6 that announce a transaction — because the investor Q&A discusses past acquisitions at length. A press release states its subject in the headline, so a match inside the first 1,200 chars scores `strong` and a later one `mention`. Only strong matches drive routing |
| 2026-08-05 | Triage routes **documents**, not filings | The Q&A text is inline in the 8-K body for FY2021–FY2023 and an EX-99.1 exhibit from FY2024 on. A filing-level decision plus the existing bodies-only rule would have read the early years and silently read nothing for the late ones, while reporting the same filings processed |
| 2026-08-05 | Investor Q&A gets **its own ledger field** | Same verification as everything else, but not the same kind of evidence: unaudited, required by no disclosure rule, and responsive to whatever investors happened to ask. Merged into `notable_language` it would be indistinguishable from the 10-K, and an output could cite an off-hand monthly reply with the authority of an audited filing |
| 2026-08-05 | `investor_qa` facts stay **`high` confidence**; register is recorded separately | Their boundaries are trivially correct and their quotes verify, so `low` would be false. Register is a different axis and lives in the field name and `data_quality.investor_qa_basis`. Folding two things into one flag makes both unreadable |
| 2026-08-05 | `InvestorQaFacts` deliberately has **no `events` list** | Triage already routes any filing with a material signal to the events path, and the 10-K independently covers every transaction in the window. A third account of the same acquisition, sourced to the weakest of the three documents, would eventually get cited |
| 2026-08-05 | Q&A extraction is **one call per filing**, not per year | FY2025's Q&A is ~93k input tokens across 12 filings and produced 37k output tokens. One call per year would have needed all of that in a single response against a 16k ceiling — a truncated structured output is a failed call, not a shorter one. Observed max per filing: 4,810 output tokens |
| 2026-08-05 | The trimmer marks its one **interior** deletion | Cutting a block out of the middle puts two separate passages side by side, and a model can then quote across the seam in good faith — manufacturing exactly the stitched quote the grounding check exists to catch. An explicit `[... omitted ...]` marker makes such a quote fail instead of reading as contiguous |
| 2026-08-05 | Triage **decisions** are committed; trimmed **text** is not | The text is a copy of public EDGAR documents and regenerates free. The decisions are the audit record `config/forms.toml` asks for, and 15 filings were dropped from the history on their strength — a record of what was excluded has to survive in the repository |
| 2026-08-05 | Risk deltas are **deterministic**, not a model call | `rapidfuzz` over the already-split factors gives the same answer every run and can be audited by hand. It also keeps the filing's largest section out of the API budget. SPEC.md §2 asks for a diff, and a diff is not a judgment task |
| 2026-08-05 | Matching is **one-to-one, greedy, best score first** | Otherwise two of this year's factors both claim the same prior-year factor, and that factor never appears as removed — silently losing a deletion, which is exactly the high-signal event the diff exists to find |
| 2026-08-05 | FY2021 risk deltas are **null with a reason**, not empty lists | Empty lists read as "nothing changed in FY2021". The prior year is outside the window, so nothing can be computed. CLAUDE.md: guard edge cases in code, not just prose |
| 2026-08-05 | **Every fact carries a verbatim quote, and the quote is checked** | A model asked for a citation always produces something citation-shaped. The dangerous failure is a plausible source for a claim the filing never made, and nothing downstream can detect it. The check turns traceability from an assertion into a test |
| 2026-08-05 | Source attribution is **measured, not asserted** | A task reading two sections resolves each fact by finding which section contains its quote, rather than asking the model where it looked. Verification and attribution become one operation, and a fact can only be attributed to a document that provably contains its evidence |
| 2026-08-05 | Near-miss tolerance is an **absolute 3-character tail**, not a percentage | At 99%, the same two stray characters are forgiven on a 260-char quote and rejected on a 64-char one — the same artifact passing or failing based on how much was quoted around it. A generation artifact is a fixed handful of characters either way |
| 2026-08-05 | `max_tokens` raised to **16000**, deviating from CLAUDE.md's 4096 | On Opus 5 thinking is on by default and shares one budget with the response. A 4096 ceiling does not produce a smaller answer, it truncates the JSON mid-structure — a failed call, not a cheaper one. The intent of the rule holds: responses are bounded fact lists, and stayed at 877–3,342 tokens |
| 2026-08-05 | One model call per **(year, source group)**, seven per year | A whole-year record does not fit in one response; each large section is sent exactly once; and the task is the unit of caching and retry, so a crash costs at most the tasks in flight |
| 2026-08-05 | **No prompt caching** | It pays off when a prefix is resent. Each section goes to exactly one task, so there is no repeated prefix and a cache write would be pure overhead |
| 2026-08-05 | `segments_basis` is **detected from the filing**, not hardcoded | FY2021–FY2022 never say "reportable segment" and FY2023+ do, so the field means different things across the window. Deriving the flag from the text keeps it correct for the next company |
| 2026-08-05 | The out-of-window vote 8-K is fetched **by name**, not by widening the window | The FY2025 say-on-pay result is in a filing dated 2026. Extending the window would sweep in a sixth year of 10-Qs and Form 4s and quietly change what every coverage claim means |
| 2026-08-04 | 10-K sections bounded by an **item map**, not end-patterns | A section runs from its heading to the next item heading, which is self-consistent and cannot over-capture into the financial statements. Headings are found structurally: text starting "Item N." and not inside an `<a>` (16 real vs 16 TOC links) |
| 2026-08-04 | Risk factors split on **bold + italic** styling | That is how individual factors are marked; category headings are bold alone and body text is weight 400. The non-bold summary list at the top of Item 1A is excluded automatically, which matters because it repeats every factor title |
| 2026-08-04 | Over-capture flagged by **count**, not presence | MD&A legitimately cites the balance sheet once. Presence alone produced five false positives on verifiably correct boundaries. Now: a marker 3+ times, or 2+ distinct markers |
| 2026-08-04 | Section validation is **form-aware** | The 2,000-char floor and over-capture check are section rules. Applied to whole documents they rejected six genuine SEC comment letters (612–1,885 chars) and flagged all four annual reports for containing the financial statements they are supposed to contain |
| 2026-08-04 | **Stopped tuning the proxy heuristic; recorded the limits instead** | Three global rules were tried and each fixed one section while breaking another — loosening the anchor threshold to admit FY2025 director bios made CD&A under-capture (FY2022: 43,123 → 32,577) and didn't fix FY2025 anyway. That is not a mis-set threshold, it is one rule being asked to do too much. Kept the value where CD&A is verified correct |
| 2026-08-04 | **Ledger fields carry a `confidence` marker** | Chosen over fixing the two proxy sections now, or dropping them. Affected content is board composition only, and the ledger is where per-field sourcing already lives — so "low confidence, unverified boundary" is recordable rather than invisible. Revisit if the board narrative turns out to matter |
| 2026-08-04 | Force UTF-8 on stdout in every script | Windows console cp1252 cannot encode characters common in filings; printing one killed a completed run |

---

## Next Steps

1. [x] Choose target company → `config/company.toml`
2. [x] Create `.env`, verify both credentials
3. [x] **Milestone 1 — Discovery.** Complete, committed `ba24893`
4. [x] **Milestone 2 — Fetch and cache.** 201 docs, 127 filings, verified
5. [x] **FY2022 PDF letter** — resolved. `pdfminer.six` + `src/pdf_text.py`,
       decode validated, 890 digits recovered
6. [x] **Milestone 3 — Section extraction.** 226/226 sections; 10-K and CD&A
       boundaries hand-verified
7. [x] **Milestone 4 — Year ledger.** 479 facts, 0 unverified quotes, per-fact
       confidence, vote outcomes from 8-K 5.07
8. [x] **8-K triage.** All 75 judged, 60 read / 15 date_only, decisions and
       evidence in `data/triage/`
9. [x] **Investor Q&A, all five years.** 850 facts from 54 filings
10. [ ] **Milestone 5 — Three outputs** to `output/`, derived only from the
        ledger. **Scoped and decided; build not started.** See "Milestone 5 is
        scoped" above for measured sizes, cost and the six findings. In order:
    - a. [x] Content-hashed fact ids — 1,428, unique, tested, additive
    - b. [x] `src/build_pack.py` — 1,428 ids, 332,747 tokens, byte-stable, 6 derived constraints
    - c. [x] Event merge + "period unclear" split — 85 records → 76 rows, 8 corroborated, 10 routine, nothing dropped
    - d. [x] `output/timeline.md` — 76 rows, deterministic, $0.00. Surfaced four data problems before any prose was written
    - e. [x] `narrative-brief.md` (2,007 words) and `discussion-points.md` (3,527 words), $7.00. Found an 8-defect quotation rate the id check could not see
    - f. [x] `src/verify_outputs.py` — 12 hard checks + 2 review lists per document, 44 tests. Caught the brief's undisclosed FY2021 letter gap
11. [ ] Optional, if the board narrative proves load-bearing: per-year verified
        boundaries for `DEF14A_director_bios` and `DEF14A_proposals_and_votes`.
        The verification suite raised its priority — 51 low-confidence director-bio
        facts, and whether board-composition claims are usable is still the reader's
        call
12. [x] **`preflight` and the full `verification-suite`, both run.** Preflight on
        2026-08-06 (verdict GO, two real findings). The verification suite on
        2026-08-07 in an isolated worktree with a fresh venv — four dimensions, nine
        findings, **all nine now fixed**. See `VERIFICATION.md` for the report and
        the remediation log
13. [ ] **Close the model-family gap.** The suite asks for a different model family
        on the independent passes and it was not achievable — the same family
        reviewed and then repaired its own work, and the blind clean-room diff of the
        analytical core was never run. Do this before treating any deliverable as
        load-bearing; it is the one item the ground-truth checks cannot substitute for
14. [ ] Optional: the 11 remaining thin figures in `discussion-points.md`. Needs
        per-fact judgment about widening each quote, not a rule. Listed every run by
        the review check, so nothing is lost by leaving them
15. [x] **Phase 0 of the productionization plan — hardening tripwires.** Done
        2026-08-08, commits `3c78496` and `a6010bb`. See the Session Log entry
        for what was built and how each piece was proven to fire
16. [x] **Phase 1 — packaging.** Done 2026-08-09, commit `fec3785`. Steps 1–4
        (the moves, `pyproject.toml`, imports, `_bootstrap.py`) were delegated to
        a Sonnet subagent; the test-harness step and the review were done on
        Opus. All 15 modules moved with history preserved, 15 `sys.path.insert`
        hacks removed (not the 11 the plan claimed). See the Session Log entry
17. [ ] **Phases 3–5**, in order: 3 Claude Code model seam (**two-thirds done**,
        `0facceb` + `15bd33e`; `generate_outputs` remains) → 4 `pipeline`
        orchestrator + `init` → 5 test split, model mix, pack subsets, docs.
        The seat-terms blocker is cleared: headless use fits the terms, Opus is
        on the seat, and API keys are unavailable for almost all colleagues.
        **Two plan corrections found by executing Phase 1 — do not re-derive:**
        (a) Phase 5's "count gate switches to `pytest --collect-only -q`" is
        wrong and was deliberately not done — `--collect-only` counts test
        *functions*, so one wrapper per file counts 8 forever and a file falling
        from 63 checks to 3 still passes, which is the exact D7 failure the gate
        exists to catch. `tests/suite_test.py` asserts the per-file check *count*
        instead; keep that design when Phase 5 splits the suite.
        (b) The plan's Phase 1 gate ("`verify_outputs` still 1,326 quotes") names
        a number that command does not print — 1,326 is the fact count from
        `data/pack/pack-report.md`. The usable Phase 1/2 gates are the pack
        sha256 reproducing and `extract_facts --estimate` reporting 88 cached
        (**confirmed in Phase 2**: the sha reproduced and the estimate held).
        (c) Phase 2 was done as **one commit, not the moves-only commit the plan
        specifies**. Split that way the first commit is broken by construction —
        data under `companies/MORN/` while the code still reads `data/`. Rename
        detection was never at risk, because the moved files and the edited files
        are disjoint sets, so splitting bought a broken commit and nothing else
18. [x] **Carry the Phase 0 and 1 additions through the Phase 2 move.** Done in
        `800a543`. `tests/test_repo_hygiene.py` keeps `ROOT` for the
        repo-wide model-output walk (a company added tomorrow with an ignored
        `facts/` must fail the suite too) and uses `P` only for the checks that
        name one company's artifacts. `run_all.py` and `tests/suite_test.py`
        needed no change — `tests/` did not move. The count gate did fire once,
        exactly as intended, when the new path-literal lint took
        `test_repo_hygiene.py` from 9 checks to 10; re-recorded to 216.
        **Already handled beforehand:** `tools/check_control_bytes.py` was blind
        to renames until `fec3785` (it filtered `--diff-filter=ACM`, which
        excludes `R`). Phase 2's migration commit was 107 renames out of 130
        files — it would have been almost entirely unscanned
19. [ ] **Idempotency: two committed artifacts change on every re-run.**
        Re-running `build_ledger` or `render_timeline` rewrites
        `ledger-report.md` and `output/timeline.md` with a new generation
        timestamp and *nothing else* — content, and `timeline.md`'s input sha,
        are otherwise identical. Found during Phase 2 and restored so the commits
        carry no churn, but it is the "run twice, diff nothing" case from
        CLAUDE.md rule 4. **Phase 5 already plans idempotency tests; fix it
        there**, either by dropping the timestamp or by moving it out of the
        committed file
20. [ ] **`DATA.md` still describes `data/` and `output/` as top-level.** Its
        `src/<module>.py` references were fixed in `d6201dd`, but the data-path
        narrative needs prose changes rather than a substitution. The plan puts
        it in Phase 5 with the README and CLAUDE.md updates
21. [ ] **Finish Phase 3: rewire `generate_outputs`.** The only remaining call
        site, and the only one needing a REDESIGN rather than a swap. Its
        **id-repair** rounds assume a resumed session; `--resume` re-writes the
        whole conversation at 2x instead of reading it back, so repairs must
        become self-contained and pack-free, carrying an index excerpt of
        ~15–25K tokens. The **quote**-repair rounds are already pack-free
        one-shots and need no change, which makes this smaller than it looks.
        **Test against a deliberately broken document** — an id that does not
        resolve — rather than by doing a full generation run: a real run costs
        ~$8 and produces deliverables that then need verifying, and unlike
        extraction there are no cached results to check against
22. [ ] **All eight probes are answered — do not re-run them.** V1–V8 are
        recorded in the Session Log entry for 2026-08-14 and, authoritatively,
        in the `model_client.py` module docstring. The five that contradicted
        the plan are the reason that docstring is long; read it before changing
        anything about how model calls are made

---

## Important Files

| File | What It Does |
|------|--------------|
| `CLAUDE.md` | Project rules — EDGAR access, extraction approach, traceability. Read first. Ends with **"Rules that have bitten us"**: the five doctrines whose violation recurred, each naming the check that now enforces it |
| `tools/check_control_bytes.py` | Blocks a commit containing raw control bytes in a text file — the signature of a regex escape mangled by a shell heredoc (`\b` → 0x08). Run via `.githooks/pre-commit`; enable per clone with `git config core.hooksPath .githooks`. `--all` scans the whole tree. Selects staged files with `--diff-filter=ACMRT`; **the `R` is load-bearing** — it filtered `ACM` until `fec3785` and was therefore blind to renames, silently skipping every modified file in a `git mv` commit |
| `tests/run_all.py` | Runs every test file and compares each one's own count against `tests/expected_counts.json`, **failing in either direction**. Fewer checks than recorded is the failure it exists for: a test that stops testing still reports green |
| `tests/suite_test.py` | The pytest front-end (`uv run pytest`). Asserts exit code, zero failures, **and the recorded check count** per file. Deliberately not `pytest --collect-only`, which counts test functions and so cannot see a file shrinking from 63 checks to 3. Named `suite_test.py`, not `test_suite.py`, because `run_all.py` globs `test_*.py` and would otherwise recurse |
| `src/equity_research/_bootstrap.py` | `ROOT`, the Windows cert store, and `.env` — imported first by every stage, for its side effects as much as its value. **Do not delete as unused.** Exists because each module used to compute its own `ROOT` two directories up, which the Phase 1 move made silently wrong by one level |
| `tests/test_repo_hygiene.py` | 10 checks. Every JSON carrying a top-level `usage.input_tokens` was paid for and must be tracked by git; `companies/MORN/output/*.md` likewise; and inversely, `.env` must not be. Also the **path-literal lint**: a `"data/…"` or `"output/…"` string in `src/equity_research/` outside `paths.py` resolves to the repo root instead of the company being run. Requires the literal to contain no whitespace, so prose *about* a path is not flagged |
| `src/equity_research/paths.py` | **Every filesystem path, resolved per company.** `CompanyPaths` owns the 49 joins that were spread across 15 modules. `resolve()` re-roots a manifest-relative string — the reason the MORN move rewrote no manifest and `pack.json` kept its sha256. Ticker order: `--ticker` → `EQR_TICKER` → the single company; two with no ticker is a **hard error**, never a first-match guess |
| `src/equity_research/settings.py` | Config layering (global `config/*.toml` + optional `companies/<T>/overrides/`), window validation at 1–10 years, and the **one pricing table** with `PRICES_AS_OF`. Arrays replace wholesale on merge, including arrays of tables — `sections.toml` pattern order is load-bearing and element-wise merging would produce an order neither file describes. Also `CHARS_PER_TOKEN = 2.66`, the calibrated fallback for backends that cannot count tokens |
| `src/equity_research/model_client.py` | **The model seam.** One interface, two backends: `claude_code` (default — needs a seat, no API key) and `api`. **Read its module docstring before changing anything about model calls** — it records eight measured findings, including that every headless call cache-*writes* its prompt at 2× input price, that an identical prompt does *not* cache, and that `--resume` preserves context while saving nothing. Several contradict the plan |
| `config/llm.toml` | Which engine model calls go through, and where the Claude Code binary is. `binary_path` is normally empty: discovery is PATH → this setting → the binary bundled inside the VS Code extension, newest version. Per-stage overrides let anyone holding an API key move just the token-heavy stage across |
| `VERIFICATION.md` | **The independent review and its remediation log.** Nine findings D1–D9, what each turned out to be, how each was fixed, and what was verified against ground truth. Read before trusting any deliverable |
| `companies/MORN/corrections.toml` | **Every human correction, as data.** `[[correction]]` (a ledger value), `[[document_correction]]` (a sentence), `[[id_remap]]` (a renumbered citation). Each carries its evidence and reviewer; each is fatal if it stops matching |
| `tests/test_extract_sections.py` | 17 checks on the extraction guards. Pins both directions: an image-only document must fail, the legitimately short SEC letters must pass |
| `tests/test_discover.py` | 12 checks on cache vintage — that an inferred as-of date labels itself, and that a zero-request run does not claim its own clock |
| `companies/MORN/data/raw/_meta/fetch-log.json` | When each cached metadata document was actually read from EDGAR. Written at fetch time, because that is the only moment that knows. **Not present for MORN** — every document was cached before this log existed, which is why `discover.vintage_of()` falls back to the cache file's mtime and labels that vintage *inferred, not recorded*. It appears the first time a document is fetched. The separate `companies/MORN/data/raw/fetch-log.jsonl` is `fetch.py`'s own per-document log and does exist |
| `src/equity_research/render_pdf.py` | Renders `companies/MORN/output/*.md` to `companies/MORN/output/pdf/*.pdf`. Deterministic, no model call. Reads each finished PDF back and fails if a word, fact id, heading or at-risk glyph did not survive |
| `companies/MORN/output/pdf/` | The three deliverables as PDF. **Gitignored** — a pure function of the committed Markdown, the script and the `[pdf]` config, rebuilt in seconds with `uv run python -m equity_research.render_pdf` |
| `SPEC.md` | Document scope, extraction targets, ledger schema, output specs |
| `DATA.md` | Provenance, as-of date, and 9 known limitations. Read before making any coverage claim |
| `PROMPT.md` | The original kickoff prompt and its milestone gates |
| `companies/MORN/company.toml` | Ticker, CIK, window, rate limits. **The only file to edit to retarget** |
| `config/forms.toml` | In-scope forms, 8-K item filter, gap signals, scope-extension block |
| `config/sections.toml` | Section boundary regexes, anchor phrases, validation rules |
| `src/equity_research/discover.py` | Milestone 1. Inventory and gap analysis. No documents downloaded |
| `src/equity_research/fetch.py` | Milestone 2. Cache-first document downloader. `--dry-run`, `--limit` |
| `src/equity_research/pdf_text.py` | PDF text extraction with subsetted-font glyph decoding. `--selftest` |
| `src/equity_research/extract_sections.py` | Milestone 3. Section location + validation. **Read its KNOWN LIMITS docstring** before trusting any proxy section |
| `companies/MORN/data/sections/sections-manifest.json` | Every section with char count, boundary basis, and validation result |
| `src/equity_research/risk_diff.py` | Deterministic year-over-year risk factor diff. No model calls |
| `src/equity_research/ledger_schema.py` | Ledger shape, confidence rules, and `verify_quote` — the grounding check |
| `src/equity_research/extract_facts.py` | Milestone 4a. The only stage that spends tokens. `--estimate` costs nothing |
| `src/equity_research/build_ledger.py` | Milestone 4b. Assembles, verifies every quote, validates, writes |
| `companies/MORN/data/ledger/FY*.json` | **The ledger.** Everything downstream derives from here, never from raw sections |
| `companies/MORN/data/ledger/ledger-report.md` | Cross-year coverage, confidence counts, and comparability warnings |
| `companies/MORN/data/ledger/facts/` | Cached per-task extraction results. A completed task is never re-run |
| `src/equity_research/render_timeline.py` | Milestone 5d. Renders `companies/MORN/output/timeline.md`. Deterministic, no model call; asserts completeness before writing |
| `companies/MORN/output/timeline.md` | **Deliverable 1 of 3.** Chronological reference table, every row carrying its fact id and filing |
| `src/equity_research/verify_outputs.py` | Milestone 5f. Holds the deliverables to the pack's binding constraints — **13 hard checks and 3 review lists** per document; deterministic, free, non-zero exit on failure |
| `tests/test_verify_outputs.py` | 63 checks. Every hard check tested against a document that fails it as well as one that passes |
| `src/equity_research/generate_outputs.py` | Milestone 5e. Writes both prose deliverables from the pack; checks and repairs ids and quotations |
| `companies/MORN/output/narrative-brief.md` | **Deliverable 2 of 3.** The five-year arc, 2,089 words, 126 citations |
| `companies/MORN/output/discussion-points.md` | **Deliverable 3 of 3.** Observations, open questions, and stated-vs-paid-for priorities |
| `tests/test_generate_outputs.py` | 38 checks on the citation and quotation gates; fixtures are real strings from the first generation run. Fails loudly if a committed generation record is missing rather than skipping itself |
| `src/equity_research/merge_events.py` | Milestone 5c. Merges duplicate event records, splits undated ones out, tags routine governance. Deterministic. `--show merged|unclear|possible|routine` |
| `config/outputs.toml` | Output-stage config: merge threshold, routine patterns and the material overrides. **Change behaviour here, not in code** |
| `tests/test_merge_events.py` | Proves same-filing records never merge and the incentive-plan row is not tagged routine. Run after any threshold change |
| `src/equity_research/build_pack.py` | Milestone 5a. Assembles the citable pack from the ledger. Deterministic, no model calls. `--show constraints` prints the binding rules |
| `companies/MORN/data/pack/pack.json` | The payload the writers read. Gitignored — reproducible from the ledger; its sha256 in `pack-report.md` is the audit link |
| `companies/MORN/data/pack/index.json` | `{id → fact}`. What `verify_outputs.py` resolves citations through |
| `src/equity_research/triage_8k.py` | Judges the 75 conditional 7.01/8.01 8-Ks. Deterministic, no model calls |
| `config/forms.toml` `[eight_k.triage]` | Triage patterns, headline window, size cap. Change behaviour here, not in code |
| `companies/MORN/data/triage/triage-8k.json` | Every triage decision with its evidence. Committed — it is the record of what was excluded |
| `companies/MORN/data/triage/triage-report.md` | The auditable log, including the full drop list |
| `tests/test_verify_quote.py` | Proves the grounding check can still reject. Run it after any change to `canon` |
| `tests/test_fact_id.py` | Proves ids are stable against judgments and sensitive to content. Run it after any change to `fact_id` or `risk_delta_id` |
| `../../.claude/skills/` | The `preflight`, `verification-suite` and other skills live TWO levels up, in the `Coding Projects` folder. Claude Code only auto-loads skills from the session's own directory and `~/.claude`, so they are **not** invocable as `/preflight` from this project — read `SKILL.md` by path and follow it |
| `companies/MORN/data/discovery/inventory.json` | **Machine source of truth** for what's in scope. Later stages read this, not config |
| `companies/MORN/data/discovery/discovery-report.md` | The human-readable inventory and gap analysis |
| `companies/MORN/data/raw/FY*/…` | Cached documents by fiscal year and form. Never delete — rebuilding means re-hitting EDGAR for all 201 |
| `companies/MORN/data/raw/fetch-manifest.json` | Every document with size, SHA-256, source URL |

---

## Things Claude Should Remember

- **I'm learning to code.** Explain in plain language, comment the code, warn me
  before anything risky, teach me the concept when it would help
- **Check in at each milestone** before moving on
- **Never re-hit EDGAR for a document already in `data/raw/`**
- **Every claim traces to `(form, fiscal year, accession number)`.** If it can't
  be sourced, it doesn't go in — no inference presented as fact, no filling gaps
  from general knowledge about the company
- **A silently empty or over-captured extraction is worse than a crash**
- **Don't trust clean-looking output.** Milestone 1's first run produced a
  plausible report with four substantive bugs in it, all found by reading the
  numbers rather than the code. Check the output against what it *should* say
- I'm a Morningstar employee analyzing Morningstar — good for validating
  extractions, and the strongest available source of the exact bias the
  traceability rule prevents. See DATA.md
- Config-driven, scripts over notebooks, no company-specific values in `src/`

---

## Session Log

### 2026-08-14 — Phase 3: the model seam, and eight probes that rewrote the plan

Commits `0facceb` (the seam) and `15bd33e` (two of three call sites), both
pushed. The plan insisted probes run **before** any wiring. That was right: five
of its assumptions turned out to be wrong, and two of the five would have
produced a design that works and quietly costs several times what it should.

#### What the probes found

| # | The plan assumed | Measured |
| --- | --- | --- |
| V2 | `--max-turns 1` bounds the call | **The flag does not exist** in 2.1.231. Denying tools gives `num_turns: 1` anyway |
| V1 | `--system-prompt` is available | Yes, and it **replaces** Claude Code's own — saving 4,525 tokens a call. A neutral cwd saves ~4,500 more by not loading both CLAUDE.md files |
| V3 | the JSON envelope carries usage | Yes: `session_id`, `total_cost_usd`, `usage`, `stop_reason`, `is_error`, `num_turns`, plus `--effort` |
| V4 | a schema may need prompt-embedding | Confirmed and it works — **16/17** valid first time, and **none** wrapped output in a markdown fence |
| V5 | truncation must stay visible | `stop_reason` distinguishes it. Largest real output 8,252 tokens against a 16,000 budget |
| V6 | one resumed session avoids re-sending the pack | **Does not work.** Fidelity holds, economics do not: `cache_read 0`, `cache_creation 34,316`, and turn 2 cost MORE than turn 1 |
| V7 | ~$0 marginal on a subscription | 2.0x the API path on real work — see below |
| V8 | Windows argv caps at 32K, use stdin | Correct; stdin carries ~180K-char prompts fine |

**The two that mattered most.** Every headless call **cache-writes its prompt at
1-hour TTL, billed at 2x input**, with no way to opt out — `input_tokens` comes
back as ~2 no matter how large the prompt is. And an **identical prompt does not
cache**: two fresh calls sending a byte-identical 60KB prefix seconds apart
produced byte-identical usage (22,691 written / 20,443 read) and identical cost
to the cent. Only Claude Code's own prefix is read back; user content never is.

Together those kill the plan's generation design and also kill the obvious
mitigation — there is no ordering of calls that makes the pack cheaper.

#### V7: a real fiscal year, measured both ways

FY2024's 17 extraction units, run through headless Claude Code (**not** written
to `data/ledger/facts/` — a probe must not be able to overwrite $11 of committed
model output):

- 16/17 succeeded; one returned malformed JSON, which is why
  `max_schema_retries` defaults to **1** rather than 0
- 11.9 minutes of call time at concurrency 2 → roughly an hour for five years
- **$4.68 against the API path's $2.28 for the same 17 units — 2.0x**
- Whole company ≈ $32 vs ≈ $18

**Those dollars are notional on a seat.** They are what the API would have
charged; the currency actually spent is seat allowance. For a colleague with no
API key the comparison is not "twice as expensive", it is "possible at all".

#### Batching was considered, and rejected on the measurements

A first reading blamed the ~20K harness preamble and proposed batching the 88
extraction calls into ~5. The measurements say otherwise: the **harness is the
cheap part** — a shared prefix, cache-read at 0.1x, about 18 cents across the
whole year. The 2x penalty falls on **content**, which batching does not reduce.
Recomputed from the measured split, batching FY2024 from 17 calls to 3 would cut
the bill about **13%**, while costing retry granularity, cache precision and
output headroom. Not done.

#### What was built

`model_client.py` — a `Backend` protocol, both backends, and `LLMResult`
carrying a `backend`/`model` stamp so a record written through Claude Code stays
distinguishable from one written through the API. Plus `config/llm.toml`, a
global config so it layers per company.

Three deliberate choices:

- **`count_tokens` returns `None` on the seat path rather than guessing.** There
  is no endpoint for it, and a confident wrong number in front of someone
  deciding whether to spend is worse than an admitted gap. The estimate is made
  at the call site, where it can be labelled.
- **`describe_cost` never presents notional seat usage as dollars spent.**
- **`find_binary` fails naming all three places it looked.** A missing binary
  must not surface three stages later as "extraction returned nothing".

#### The estimator, and distrusting it on purpose

`settings.CHARS_PER_TOKEN = 2.66`, calibrated on `pack.json` (936,868 chars =
352,194 tokens). Not chars/4, which under-counts JSON by about a third — and
under-counting is the wrong direction for a budget check, because it waves
through a payload that is over the ceiling.

Against the pack it was calibrated on it lands 12 tokens out, but that is
circular. Checked against a **second, unrelated payload**: FY2024's extraction
prompts are 203,422 tokens exactly and the ratio estimates 223,475 — **10%
high**, because filing prose runs nearer 2.92 chars/token than JSON's 2.66. One
ratio kept rather than two: splitting them buys 10% on a number already labelled
approximate, and erring high is the safe direction.

This is what keeps the pack budget check alive without an API key. Otherwise it
would have printed `BUDGET NOT CHECKED` on every run for every colleague — the
exact shape of a tripwire that has quietly stopped being one.

#### Verification

`extract_facts --estimate`: **88 cached, 0 to run**, `backend=claude_code`,
`concurrency=2` — the gate that catches a broken extraction path.
`pack.json` sha256 `fd320ce5…` unchanged. 216 checks, pytest 10 passed,
`verify_outputs` green on both documents, control-byte scan clean over 161
tracked files. `model_client` itself carries 26 assertions including two real
model calls, one schema-constrained and correctly parsed.

### 2026-08-13 — Phase 2: MORN into `companies/MORN/`, `paths.py`, `settings.py`

Commits `800a543` (the migration) and `d6201dd` (step 4, the hardcoding fixes),
both pushed. OneDrive sync was paused for the session, at the plan's instruction.

**Baseline recorded before anything moved**, and reconciled after: 805 files and
51,070,196 bytes under `data/ output/ config/`, 110 of them tracked; 215 checks;
88 cached extractions; `pack.json` sha256 `fd320ce5…`.

**The move.** `git mv` of `config/company.toml`, `config/corrections.toml`,
`data/` and `output/` into `companies/MORN/`. One correction to the plan's
method: `git mv` on a whole *directory* renames it in the working tree — carrying
untracked and ignored files along — and stages the tracked renames, so the
plan's separate "plain `mv` for the ~44 MB of untracked data" step was not
needed. Afterwards: 805 files, 51,070,196 bytes, unchanged; 107 renames + the 3
global tomls that stayed in `config/` = the 110 tracked files counted going in.

`output/` failed once with "Permission denied" — a background Acrobat process
held `output/pdf/discussion-points.pdf`, which blocked renaming `output/pdf/`,
which blocked renaming `output/`. Located by probing each item with an in-place
rename rather than guessing. It cleared on retry and the whole directory moved
intact. Worth knowing the shape: a single locked file blocks its whole ancestor
chain, and the lock was on the least valuable artifact in the repo.

**Why no manifest was rewritten — the load-bearing part.** The four manifests
store paths as ROOT-relative forward-slash strings. Measured before relying on
it: 893 such strings, **zero** absolute paths. Every one of those relative paths
still exists unchanged under `companies/MORN/`, so only the base they are joined
onto moved — `ROOT / rec["path"]` became `P.resolve(rec["path"])`. The manifests
are byte-identical, which is what lets `pack.json` keep its sha256, which is what
keeps the hash stamped on the committed deliverables honest.

**`paths.py`** — `CompanyPaths`, a frozen dataclass, owns all 49 joins that were
spread across 15 modules. `resolve()` re-roots a manifest string and *raises* on
an absolute path or an unexpected prefix rather than producing a path that points
nowhere. Ticker resolution is `--ticker` → `EQR_TICKER` → the single company when
there is exactly one; two or more with no ticker is a hard error, not a
first-match guess, because reading the wrong company's filings produces a
flawless-looking run over entirely wrong data. It reads `--ticker` from
`sys.argv` directly, since module-level path constants are evaluated at import,
before argparse runs; `add_ticker_arg()` still declares the flag on all 14 stages
so `--help` lists it and `--tickr` is rejected rather than silently falling back.

**`settings.py`** — config layering (global `config/*.toml` deep-merged with
optional `companies/<T>/overrides/`), window validation at 1–10 years, and one
pricing table with `PRICES_AS_OF`. The merge rule replaces arrays wholesale
including arrays of tables, because `sections.toml` holds ordered pattern lists
where first match wins and element-wise merging would produce an order neither
file describes.

**Config split:** `company.toml` and `corrections.toml` are company-owned and
moved; `forms.toml`, `sections.toml` and `outputs.toml` stay global and are now
overridable per company.

#### Step 4 — deriving what was hardcoded

- The investor_qa prompt said "in which **Morningstar** published written
  answers" — a company name inside a prompt, in a pipeline whose purpose is
  running against any ticker. Now `<COMPANY>` from `inventory.json`, not from
  `company.toml`, whose `resolved_name` that file documents as informational and
  a tripwire. Checked rather than assumed that this does not invalidate the 88
  cached results: `source_digest` hashes accession, section key and section
  text, never the prompt.
- `"A five-year read"` sat above a title that correctly templated FY2021–FY2025.
  Now formatted from the years the pack covers, and verified to render
  byte-identically for the current window.
- `WHOLE_DOC_FORMS` derived from `forms.toml`; verified to reproduce the previous
  six-form set exactly, and verified in the other direction (a form added to
  config is picked up).
- One `FIELDS` in `ledger_schema.py`, derived from `FIELD_CODES`, replacing
  identical copies in `build_ledger.py` and `build_pack.py`.
- One pricing table replacing 8 literals across 3 files.
- 112 stale `src/<stage>.py` references from the Phase 1 packaging: 92 in code
  and tests, 20 in config comments and `DATA.md`. `PROJECT_STATUS.md` (26) and
  `VERIFICATION.md` (3) left as dated history.

#### Three findings worth keeping

**A cost figure that disagreed with itself.** `build_pack.py` computed the
1-hour cache break-even as `2.0/0.9` and printed **2.2**, while a comment above
that line and a hardcoded markdown table below it both said **2.3**. One run put
2.2 on the terminal and 2.3 into `pack-report.md`. 2.2 is correct;
`settings.break_even_reads()` is now the only source. Every dollar figure in the
regenerated report is unchanged — only the break-even moved, to agree with the
number beside it. Contained: `pack-report.md` is gitignored and no committed
deliverable cites it.

**A latent `NameError` I introduced and nearly shipped.** Removing
`PRICE_IN`/`PRICE_OUT` from `extract_facts.py` left them referenced in the
estimate path. `--estimate` still reported clean, because with 0 tasks planned it
returns *before* reaching those lines — it would have fired on the first run with
something to price. The same shape as every checker bug in this project: green
because the code path was never reached.

**Timestamp churn in two committed artifacts.** Re-running `build_ledger` or
`render_timeline` rewrites `ledger-report.md` and `output/timeline.md` with a new
timestamp and nothing else. Good news about the migration — content and
`timeline.md`'s input sha are identical — but it is the "run twice, diff nothing"
case. Both restored so the commits carry no churn; recorded as Next Steps item 19
for Phase 5.

#### The path-literal lint, and why it is narrower than the plan said

The plan specifies a regex over `src/` for `"data/` and `"output/`. Written that
way it fires on two perfectly good error messages that mention `data/ledger/` and
`data/triage/text/` **in sentences**. A check that fires on correct code gets
dismissed, and is still being dismissed on the day it is right — the same
reasoning already recorded in `verify_outputs.py` about hard versus review
checks. It now also requires the literal to contain no whitespace, which is what
separates a path from prose about a path.

Proven against failing input before being trusted (doctrine 3): seven crafted
cases covering both directions, then a real violation planted in `render_pdf.py`,
which the suite caught by file, line and content; the file was restored
byte-identically afterwards. `test_repo_hygiene.py` went 9 → 10 checks and the
count gate caught the change itself, in the "more than recorded" direction.

#### Verification

| Gate | Result |
| --- | --- |
| `pack.json` sha256 | `fd320ce5…` — **regenerated**, then `cmp`'d byte-for-byte against a pre-move copy |
| `extract_facts --estimate` | 88 cached, 0 to run |
| `tests/run_all.py` | 215 → **216** checks (the new lint), all passing |
| `pytest` | 10 passed |
| `verify_outputs` | 2 documents, every hard check passed |
| control-byte scan | clean over 130 staged files, then all 159 tracked |
| `.gitignore` | 16 path classes checked with `git check-ignore -v` in both directions; untracked 695 → 0; zero tracked-but-ignored |
| `paths.py` / `settings.py` | 67 assertions, 24 of them exercising the guards |

The 88-cached line is the gate that catches a wrong path base. **The test suite
is not** — `tests/` did not move, so it passes either way. Same lesson as the
`ROOT` hazard in Phase 1: the gate that matters is the one that touches the moved
thing.

Also closed the two Phase 2 risks the plan listed: the stale permission rule in
`.claude/settings.local.json` (it named `src/verify_outputs.py`), and
`core.longpaths` is now set — the deepest path is 99 relative, ~194 absolute.

### 2026-08-09 — Phase 1: packaging, a pytest front-end, and a bug in a Phase 0 checker

Commit `fec3785`, pushed. Baseline measured before starting: 215 checks green,
`pack.json` sha256 `fd320ce5…`, 88 cached extractions.

**How the work was split.** Steps 1–4 (file moves, `pyproject.toml`, imports,
`_bootstrap.py`) went to a **Sonnet subagent**; the test-harness work and all
review stayed on Opus. The subagent was given the hazard below explicitly rather
than left to find it, and was told not to commit. Every number it reported was
re-run here rather than taken on trust — which mattered, see the gate correction.

**The hazard the refactor had to survive.** Every module computed
`ROOT = Path(__file__).resolve().parent.parent` — correct while the file lived in
`src/`, silently wrong by one directory once it lived in `src/equity_research/`.
Nothing would have raised. Every `data/` and `output/` path would have quietly
repointed into `src/`, and `extract_facts` would have offered to re-run all 88
cached extractions at roughly $12. Now computed once in `_bootstrap.py`.

Worth recording *which* check catches this, because it is not the obvious one:
the test suite passes either way, since `tests/` did not move. The gate that
would have failed is `extract_facts --estimate` reporting 88 cached / 0 to run.

**What was built**
- All 15 modules `git mv`'d into `src/equity_research/` (history preserved),
  plus `__init__.py`, `_bootstrap.py` (ROOT + truststore + dotenv, previously
  copy-pasted across four modules) and a `cli.py` stub for `[project.scripts]`
- `pyproject.toml`: `package = true`, hatchling, an explicit wheel target (the
  distribution is `public-equity-research` but the package dir is
  `equity_research`, which hatchling cannot infer), pytest in a dev group
- **15** `sys.path.insert` hacks removed — 8 in `src/`, 7 in `tests/`. The plan
  said 11. Same stale-baseline drift as the 186-vs-206 check count in Phase 0
- Restored `from pathlib import Path` in four modules where it had been dropped
  while `Path` was still used in annotations. No runtime bug — those files use
  `from __future__ import annotations` — but type checkers and
  `typing.get_type_hints()` would fail on them
- README: stage commands are now `python -m equity_research.<stage>`

**A deliberate deviation from the plan.** Phase 5 specifies that the count gate
switch to comparing `pytest --collect-only -q`. That would have *disarmed the
tripwire Phase 0 built*: `--collect-only` counts test functions, and the plan's
own design is one `def test_all()` per file, so it would report 8 forever. A file
falling from 63 checks to 3 would still pass — the exact D7 failure (35 checks in
the working tree vs 29 in a clean checkout, both green) the gate exists to catch.

Instead `tests/suite_test.py` runs each script-style test file and asserts three
things: exit 0, zero failed checks, and the recorded check **count**. It is named
`suite_test.py` and not `test_suite.py` because `run_all.py` globs `test_*.py`
and would otherwise discover a file that runs `run_all` — recursively. Proven
against failing input in all four directions before being trusted: fewer checks
than recorded, more checks, a recorded file missing from disk, and a file on disk
missing from the record.

**A bug found in a Phase 0 checker.** `tools/check_control_bytes.py` selected
staged files with `--diff-filter=ACM`, which excludes `R`. Git reports a rename
under its *destination* path, and that destination has a blob — often a modified
one, since `git mv` plus edits is one `R` entry, not `R` plus `M`. On this very
commit the scanner reported **"clean (14 files)" while skipping all 15 files
whose contents had actually changed.**

Now `ACMRT`; coverage on this commit went 14 → 30 files. Verified by planting a
real `0x08` byte in a renamed file and confirming the scanner names the file,
line, column and offset and exits 1 — that byte was invisible before the fix.
**Phase 2 is almost entirely renames**, so the scanner would have been nearly
blind through the whole MORN move. This is the third checker bug in the project's
tally and the failure mode the tool exists to prevent: a checker reporting green
because it is not looking.

**A correction to my own gate.** I had written the Phase 1 gate as
"`verify_outputs` still reports 1,326 quotes". The subagent pushed back that no
such line is printed, and it was right: `verify_outputs` reports per-document
hard checks, and 1,326 is the *fact* count from `data/pack/pack-report.md`. The
plan carries the same error. The usable gates are the pack sha256 and
`--estimate`; both are now recorded in Next Steps item 17.

**Verification, all re-run after the last change**

| Check | Result |
|---|---|
| `run_all.py` | 215 checks / 8 files, all passing — unchanged |
| `pytest` | 10 passed (8 files + 2 structural guards) |
| `verify_outputs` | 2 documents, every hard check passed |
| `build_pack` | `pack.json` sha256 `fd320ce5…` — byte-identical, **regenerated** not merely untouched |
| `extract_facts --estimate` | 88 cached, 0 to run |
| control-byte scan | clean over all 30 staged files |

Regenerating the pack rather than just hashing the existing file is the point:
it shows the moved modules *produce* identical output. `data/` and `output/`
stayed clean through the regeneration, which is rule 4 ("run twice, diff
nothing") holding.

**Left alone deliberately.** `build_pack.count_tokens` still repeats the
truststore/`load_dotenv` preamble locally. Redundant now but harmless, and
removing it shifts when a network-adjacent call runs — deferred to Phase 2.

**Environment note.** OneDrive locked the package's `dist-info` directory during
a `uv sync` twice today, once for the subagent and once here. Both cleared on
retry, but Phase 2 moves ~44 MB of untracked data and a lock mid-`git mv` is a
worse failure than one mid-install. Pause sync before starting it.

### 2026-08-08 (continued) — published to GitHub; Phase 0 built and verified

Two things happened: the repository got a remote, and Phase 0 of the
productionization plan was executed end to end. Run on Opus.

**Published.** Remote added at
`https://github.com/bpmoriarty/public-equity-narrative-research`, local branch
renamed `master` → `main`. Pre-flight before pushing: no API-key patterns in any
tracked file, `.env` untracked **and absent from every commit in the history**
(gitignore only protects files that were never added, so that second check is
the one that matters), 145 files / 737 KB. Flagged and left as the user's call:
the work email is on all 29 commit authors, so removing it from `.env.example`
does not remove it from GitHub — only a history rewrite would.

**Baseline recorded first**, as the plan requires: **206** test checks green
across 7 files, 1,326 of 1,329 quotes verified, `pack.json` sha256
`fd320ce531c4766f95feb4f3f0cf10d47127787706d6e3647a5281fcc65e6cf5` (matching the
value already recorded in `pack-report.md`). *The plan said 186 checks; the suite
had grown to 206. The measured number is the one recorded.*

**Built — every piece run against something that fails it before being trusted,
per doctrine 3:**

1. **Control-byte scan** — `tools/check_control_bytes.py` + `.githooks/pre-commit`,
   enabled with `git config core.hooksPath .githooks` (once per clone, now in the
   README). Scans **staged blobs**, not working-tree files. `.gitattributes` pins
   the hook to LF endings, scoped to `.githooks/` so the 98 committed ledger files
   are not renormalised — a CRLF shebang would make the hook fail to run, silently
   disabling the check. *Proven both ways: a corrupted file blocked with byte
   offsets and the likely escape named; a clean file with a real `\b`, a real
   backreference, a tab and unicode passed; all 145 tracked files scanned clean.*
   **It also caught a live corruption during its own test** — the "clean" fixture
   was first written through a shell double-quoted string, the shell ate the
   backslashes, and the scanner flagged the resulting 0x08. The bug reproduced
   itself by accident, which is the best evidence the tool works.
2. **Model-output-must-be-tracked** — `tests/test_repo_hygiene.py` finds every
   JSON carrying a top-level `usage.input_tokens` and requires it to be neither
   ignored nor untracked. 90 found (88 facts + 2 generation records). Also asserts
   `output/*.md` is tracked and, inversely, that `.env` is not. *Proven by planting
   a model-output-shaped file in a gitignored directory: named it, printed the fix.*
3. **Test-count gate** — `tests/run_all.py` vs `tests/expected_counts.json`, failing
   in **either** direction. Three files did not report a count, so each gained one
   at the point of the check; **no assertion was changed**. Scraping their prose was
   tried and rejected — a trial scraper counted a section header as a check, which is
   precisely the checker-bug class this project already has ~18 of. *Proven on four
   paths: fewer, more, a listed file that no longer exists, a file reporting no count.*
5. **Content-hash cache staleness** — `source_sha256` over each section's accession,
   key and text, replacing the length-only comparison. Records predating the field
   fall back to length, so **nothing was invalidated**: `--estimate` still reports
   88 cached / 0 to run. *Proven: a planted non-matching hash reports "content
   changed with NO change in length", which the old check could not say; the correct
   hash keeps the record cached; the digest moves on all four same-length mutations
   (substitution, reordering, different filing, different section) and is stable on
   identical input.*
6. **Pack budget check** — new `[pack]` block in `config/outputs.toml`:
   `warn_tokens = 400_000`, `max_tokens = 600_000`. The 1M context is not the
   binding constraint; quality is, and it fails invisibly as fluent prose that
   misquotes its own source. Current pack: 352,194 tokens, 59% of the ceiling.
   Over the ceiling the artifacts are still written for inspection but the stage
   exits non-zero. *Proven on all four paths — under, warn, fatal, and `--no-count`,
   which says the budget was NOT checked rather than passing silently. A
   misconfiguration with warn above max is refused at load.*
4. **Advisory heredoc guard** — `tools/hook_no_heredoc.py` + `.claude/settings.json`
   `PreToolUse` hook. Deliberately narrow and best-effort; the byte scan is the real
   gate because it reads bytes instead of guessing shell syntax. *Proven on 7 cases,
   including that `git commit -F -` stays allowed.*
7. **`CLAUDE.md` — "Rules that have bitten us."** The five costliest doctrines, each
   naming its mechanical enforcer, moved out of `.gitignore` comments and
   `VERIFICATION.md` findings where they read as history rather than instructions.
8. **Small fixes** — `build_pack` `MODEL` constant → config; failed extraction
   records now carry `request_id`; and `.env.example` carried a real email address
   five lines below its own instruction never to. Replaced with a placeholder, and
   `discover.py` / `fetch.py` now **refuse** that placeholder rather than sending a
   fake User-Agent to the SEC. *Proven both directions.*

**Deferred, with reasons stated rather than dropped:** `_bootstrap.py` extraction
(it lands in `src/equity_research/` in Phase 1; doing it now touches all 21 files
twice) and `PYTHONUTF8=1` (must be set before the interpreter starts, so its home
is the orchestrator's per-stage subprocess env in Phase 4; the scripts already
reconfigure stdout/stderr, which covers the console failures seen so far).

**Baseline held exactly after every change:** 215 checks green (206 pre-existing
+ 9 new), 1,326 of 1,329 quotes verified, every hard output check passing on both
documents, and `pack.json` sha256 still `fd320ce5…` — **byte-identical**. No
pipeline output changed.

### 2026-08-08 — planning session: productionization plan explored and approved

No code changes; a planning-only session (run on Fable — building is intended
for Opus, with Sonnet acceptable on the phases the plan marks as mechanical).

- **Explored two questions:** why the build had so many process failures, and
  how to productionize for any ticker / any window / colleagues as users. Two
  read-only audits swept the repo: one inventoried every documented mistake
  (the three recurring classes — gitignored model output ×3, heredoc corruption
  ×3, non-idempotent writes ×2 — plus ~18 checker bugs and the ~38 prose
  doctrines nothing enforces), the other mapped generalization readiness
  (one company-name hardcoding violation in `src/`, ~33 path constants across
  15 modules, no orchestrator, pack at 352K tokens for 5 years with 64% of
  facts from MORN's monthly investor Q&A).
- **Decisions made:** colleagues are in-scope users, and since they have Claude
  Enterprise seats but no API keys, **Claude Code headless becomes the primary
  LLM backend** (the API-key path stays as a secondary, config-selectable
  backend); everything company-specific moves under `companies/<TICKER>/`;
  MORN migrates in with git history; max window is ~10 fiscal years (quality
  binds before the 1M context — comfort zone ≤ ~450–500K pack tokens);
  balanced cost stance (~$12/company expected on the API path vs $21 measured,
  ~$0 marginal on subscription); process hardening ships as executable tasks.
- **The approved plan** — six phases, each with a hard verification gate — is at
  `C:\Users\bmoriar\.claude\plans\modular-brewing-teapot.md`. Phase 0 builds
  the tripwires that close the three recurring mistake classes; Phase 2's
  central check is that `pack.json`'s sha256 reproduces after the MORN move
  (manifest paths are relative, so the restructure must change zero bytes);
  Phase 3 runs eight probe scripts (V1–V8) before wiring the Claude Code
  backend, including the seat-allowance feasibility test.
- **Human items surfaced:** confirm with the org that headless pipeline use
  fits Enterprise-seat terms and Opus is available on colleagues' seats (gates
  the whole colleagues-can-run-this goal), and pause OneDrive sync during the
  Phase 2 file move.

### 2026-08-07 / 08 — the verification suite, and fixing everything it found

Seven commits, `400c789` → `a223c57`. **No model calls; the whole remediation cost
$0.00 in API spend.**

- **Ran the full verification suite** in an isolated worktree with a fresh venv, the
  original tree read-only throughout. Four dimensions; the statistical one is **N/A
  and that is a scope fact, not a skip** — the charter forbids the work it audits, and
  there is no estimator, test, CI or metric anywhere in `src/`
- **The evidence layer held.** Every quotation re-derived from the cached filings —
  a census, not a sample — **1,326/1,326** genuine filing text. Byte-identical pack
  rebuild from a clean checkout, all seams reconciling, 412/412 citations resolving
- **Nine findings, all now fixed.** The full account is in `VERIFICATION.md`; the
  ones that changed how I think about this pipeline:
  - **D1 — `quote_verified: true` does not mean the value follows from the quote.**
    The Desmond fact recorded a *departure* on the day she *announced* one, and its
    own verbatim quote contained the disproof. It reached two deliverables, and the
    brief told the reader "the filings do not settle" a question the 8-K/A settles
    explicitly. Root cause was a hardcoded template asserting ambiguity about evidence
    it had never read
  - **D7 — a test that skipped itself.** `data/pack/gen-*.json` are model output —
    the only copy of `text_before_repair` — sitting in a gitignored directory under a
    justification describing the *other* files beside them. Third instance of that
    reasoning in this repo, first not caught. The measured cost: the suite ran 29
    checks in a clean checkout instead of 35 and reported green
  - **D4 — the corruption was in what got stored, not what got compared.** `canon()`
    already saw through the literal `’` escapes; `verify_quote` then returned the
    *model's* string as the verified span, so the corrupt spelling was what got stored
    and cited — while its docstring claimed the opposite
  - **D9 — as-of described the run, not the data.** Found while fixing D8, because
    re-running `discover.py` to add a field would itself have falsified the timestamp
- **Two defects were found by a check rather than by reading.** D2(a)'s numeric-
  evidence gate was deliberately built *before* D3 was fixed, and it located D3 on its
  own — then reading the filing to fix it turned up a second error in the same six
  words that the suite had missed: the buyback figure was dated to 2022, before the
  programme was effective
- **I found bugs in my own checks repeatedly, and that is the recurring lesson.**
  Three of four initial seam failures and four of thirteen quote failures were my
  artifacts. The numeric gate's first version read `$200,000` as `000` (the lookbehind
  excluded `$`) and `Item 5.07` as a quantity — both reporting a defect in the document
  that was really a defect in the checker, which is the failure mode that teaches a
  reader to ignore a check. Every one is now a pinned regression case
- **Corrections became a first-class mechanism** rather than hand-edits:
  `config/corrections.toml` with three shapes, each machine-checked and each fatal if
  it goes stale. `data/ledger/facts/` is never touched. A generated document can now be
  corrected in place — `--apply-corrections`, $0.00, idempotent — with the model's own
  text preserved and every correction printed in the document's provenance
- **Phase 4 re-verification, because the census expired** when 34 quotes changed:
  1,326/1,326 again, 0 literal escapes, seam `1,329 − 3 + 99 = 1,425` exact, 415/415
  citations resolving, determinism confirmed twice at `fd320ce5…`, all seven test files
  passing, `verify_outputs` green on both documents
- Test suite grew 5 files → **7** (186 checks): `test_extract_sections.py` and
  `test_discover.py` are new, and `verify_outputs` went from 12 hard checks to 13
- **What is deliberately still open:** the blind clean-room diff was never run (same
  model family reviewed and repaired its own work), 11 figures remain traceable but
  not evidenced, and the human-judgment residue stands — whether 64% `investor_qa` is
  the right evidentiary mix, the May-2026 vote convention, the 51 low-confidence
  director bios, and the analyst-analysing-own-employer bias the traceability rule
  exists to control

### 2026-08-04

- Set up the subproject from scratch: structure, `uv` environment, dependencies,
  config scaffolding, provenance doc. Verified all imports and the API key
- Targeted MORN FY2021–FY2025; verified the CIK against the SEC ticker map
  rather than trusting the supplied value
- **Milestone 1 complete.** Built `src/discover.py`. Found and fixed four bugs
  in its own first output — the worst being that `reportDate` on a DEF 14A is
  the annual meeting date, which had misdated every proxy by a year and would
  have misattributed every incentive metric
- Extended scope to `DEFA14A`, `UPLOAD`, `CORRESP` at user request
- **Milestone 2 complete.** Built `src/fetch.py`. 201 documents, 127 filings,
  32.8 MB, zero failures. Verified hashes, primary-document coverage, and that a
  re-run downloads nothing
- Mapped the format landscape before writing the fetcher: found EDGAR's
  `index.json` type field is useless, that one ARS is PDF-only, and that the
  FY2021 shareholder letter does not exist on EDGAR at all
- Solved the FY2022 PDF letter. Added `pypdf`, found it destroys digits,
  removed it, and adopted `pdfminer.six` with a validated glyph decoder in
  `src/pdf_text.py`. All four available shareholder letters are now readable
- **Milestone 3 complete.** Built `src/extract_sections.py`; 226/226 sections.
  Probed real filing markup before writing the parser, which turned up that
  EDGAR proxies carry Windows-1252 numeric character references lxml does not
  remap (801 control characters in the FY2021 proxy alone)
- Found and fixed seven bugs, most in my own first attempt — the instructive one
  being that Donnelley proxies repeat the section title as a running page header
  14 times, so a "largest span" heuristic measured the gap between two page
  headers instead of the section
- Spot-checked two proxy outliers at the user's request. It corrected my read in
  both directions: FY2022 CD&A really was over-capturing (now fixed and
  verified), while FY2022 proposals at 6,883 chars turned out to be correct and
  the *other* four years are the suspect ones
- Decided to record the two weak proxy sections as low-confidence rather than
  keep tuning a global heuristic or drop them
- Next: milestone 4, the year ledger

### 2026-08-05

- **Milestone 4 complete.** Ledger built for all five years: 479 facts, 34 model
  calls, 0 failures, **0 unverified quotes**, $4.52
- Built the traceability check first and the extraction second. Every fact must
  carry an exact quote, which is then verified against the source — and the
  verifier was itself tested against fabricated, paraphrased, stitched and
  truncated quotes, because a 100% pass rate proves nothing unless the check can
  fail
- Kept the largest section out of the API entirely: risk deltas are `rapidfuzz`,
  not a model call, so they are reproducible and hand-auditable
- Found an ARS is the whole annual report, not the shareholder letter — sending
  one whole would have cost ~150k tokens a year of financial statements
- Found and fixed three bugs: a risk factor heading split across text nodes
  became a phantom deleted factor; `fetch.py` replaced the manifest instead of
  merging, so the first partial run cut 201 records to 1; and the quote checker
  called a 258-of-260-character match a paraphrase, which would have put a false
  "unreliable" label on a well-evidenced fact
- Surfaced two comparability traps and recorded both on the data rather than in
  prose: `segments` changes meaning at FY2022/FY2023, and say-on-pay votes for
  year N are held in year N+1
- Next: milestone 5, the three outputs

### 2026-08-05 (continued) — milestone 5 scoped, not started

- **Scoped milestone 5 at the user's request** and measured what it would take
  rather than estimating: three payload shapes token-counted (73,555 / 219,406 /
  320,046), cost with a 1-hour prompt cache (~$3.50 first pass, ~$1.30 per review
  round, **$6–10 all-in**), and time (~2–3 hours of build, ~15 min of API runtime
  per round). Full detail under "Milestone 5 is scoped" above
- **Six findings from measuring the ledger**, the two structural ones being: facts
  have no IDs, so a citation can only reach filing granularity — for an 8-K holding
  40 Q&A facts that means "somewhere in this document"; and 20 event records are
  cross-year duplicates of the same event, which the timeline must merge and which
  are corroboration rather than noise
- Re-confirmed DATA.md limitation 8 (no FY2021 shareholder letter) against the
  submissions feed and quantified its effect: zero letter-sourced facts in FY2021
  against 10–11 per year after. Separately, the `ledger-report.md` warning that
  FY2021's `letter` task "has no result file" is a false alarm — the check cannot
  distinguish "not extracted" from "no such section exists"
- **User answered the three design questions, then paused before any build.** Reg
  FD Q&A carries full weight with labels; undated events get their own block; facts
  get content-hashed IDs plus an output citation checker. Recorded in Recent
  Decisions and broken into ordered sub-steps under Next Steps item 10
- Nothing was built and nothing was spent. Next: begin milestone 5 item 10a when
  the user is ready

### 2026-08-06 — milestone 5, item 10a: fact ids

- **1,428 stable ids** (1,329 facts + 99 risk deltas), so an output can cite one
  fact rather than a whole filing. `EVT-FY2021-23afc21f`, `QA-FY2023-67d4a8e7`
- **The design decision, and the reason it is a test:** the id hashes the claim,
  the evidence and the source, and deliberately excludes confidence, the
  verification result and `filing_date`. Judgments about a fact do not change its
  identity; the fact's content and evidence do. Adding confidence to the hash would
  break nothing visibly today — it would surface only when fixing the director-bio
  boundaries flipped 51 board facts and silently invalidated every citation to them.
  `tests/test_fact_id.py` asserts the insensitivity so a future change cannot lose it
- **The build-time uniqueness check earned itself on its first run.** 46 reworded
  risk deltas collided: `risk_delta_id` read `item["heading"]`, which `reworded`
  deltas do not have — they carry `heading_now`/`heading_prior`. I had sampled the
  `unchanged` category and generalised from the wrong shape. Fixed by hashing every
  key except the named measurements, which fails toward churn rather than collision
- Also fixed the collision *message*, which printed "None" for the 46 items it
  caught — a diagnostic that names nothing is barely better than no message
- **Verified additive, not just working:** strip the two new keys from the rebuilt
  ledger and all five years are byte-identical to the pre-change snapshot. Rebuilds
  remain byte-identical to each other, and a partial `--fy 2023` run still audits
  all 1,428 ids
- `LedgerFact` gained `fiscal_year`: the three unverified facts have no `source`, so
  until now they could not say which year they belonged to
- Fixed a contradiction in DATA.md: it still claimed "no fabricated or paraphrased
  quote has yet been found" fifty lines below the paraphrase found last session
- **Ran the preflight checklist** (`.claude/skills/Preflight Check/SKILL.md`, two
  levels up in `Coding Projects`). Verdict GO, after two real findings:
  - **`output/` was gitignored.** The three deliverables would have been absent from
    a clean checkout. The stated reason — "regenerates from data/ledger/" — is false
    in the way that matters: they are model-written prose, cost ~$3.50 a pass, and do
    not reproduce byte-for-byte. Caught before any output existed to lose
  - **Ids were not logged in `data_quality`.** Every citation now resolves through an
    id, which makes it an analysis variable, and only the build's stdout knew whether
    they were all present and distinct. Added `data_quality.ids`, scoped honestly to
    within-year because the block is written before the cross-year audit runs
- Checked the prose against the data rather than by eye: all nine asserted counts in
  DATA.md and PROJECT_STATUS.md recompute correctly, and all five example ids quoted
  in the documents resolve to real records

### 2026-08-06 (continued) — item 10b: the citable pack

- **`data/pack/pack.json`: 1,428 citable ids, 332,747 tokens, byte-stable.** Plus
  `index.json` for the output checker and `pack-report.md` for run metadata
- **Measured before building, and it changed the design: only `quote` is verified
  text.** Of 1,741 `value` strings over 40 characters, just **3.1%** appear verbatim
  in their own fact's quote. The rest are model-written summaries that
  `verify_quote` never saw. So the pack carries every quote despite costing a third
  of its size in tokens — without them it would contain no quotable text at all
- **`pack.json` has no timestamp, on purpose.** It is the shared cached prompt
  prefix and caching only hits on a byte-identical prefix; a `generated_utc` field
  would silently turn $0.17 reads into $1.66 calls. Verified: 0 ISO timestamps in
  the payload, and byte-identical across rebuilds
- Compact JSON separators saved 34,741 tokens with nothing removed. The index stays
  indented — it is never sent anywhere, so its size is free
- **All six constraints are derived, not written down.** The build detects which
  years use reportable segments and which years have a shareholder letter, so a
  count can never go stale while reading as though someone checked
- Verified: ids resolve both ways between pack, index and ledger (0 discrepancies
  in any direction); all 1,329 quotes byte-identical to the ledger; the
  "absent means high" compaction correctly marks exactly the 54 low facts
- The pack is bigger than the 219K I scoped, but the **$6–10 milestone estimate
  holds** — only two of the four generation calls need the whole thing

### 2026-08-06 (continued) — item 10c: event merge and split

- **85 ledger records → 76 timeline rows.** 50 dated, 26 period-unclear, 8
  corroborated by more than one filing, 10 tagged routine. Every input id lands in
  exactly one row — verified, not assumed
- **Measured the merge rule instead of picking one.** Scored every different-filing
  pair sharing a date: the sorted similarities have their widest gap in the relevant
  range between 59.6 and 48.5, so the threshold is 55, the middle of it
- **The real discriminator turned out to be "different filing", not similarity.** On
  similarity alone a true positive (72.9 — the 2022 refinancing reported by two
  filings) sits three points from a true negative (61.7 — one 8-K reporting both a
  Contract Services Agreement and a Separation Agreement with the same officer on the
  same day). Requiring different filings excludes the negative by construction
- **Merging is transitive.** The FY2025 refinancing is described by three records and
  two of them share a filing, so they only join through the third; pairwise merging
  would have left two rows for one event
- **Corrected my own earlier claim.** I had said 20 records were cross-year
  duplicates; measured, it is 9 records folding into 8 rows. The 20 was the count of
  records merely sharing a date, most of which are different events that happened the
  same day — which is the problem this stage exists to solve
- **Routine governance is tagged, not dropped**, with a material-override list that
  exists because of a near-miss: the 2011 Stock Incentive Plan approval shares its
  date and its meeting with four routine votes, and an incentive plan change is a
  timeline row type SPEC.md §4b names explicitly
- 27 checks in `tests/test_merge_events.py`, fixtures drawn from the real filings
  including both sides of that 72.9/61.7 pair

### 2026-08-07 (continued) — item 10f: the constraint gates

- **`src/verify_outputs.py`.** 12 hard checks and 2 review lists per document,
  deterministic and free, non-zero exit on any hard failure. Both deliverables pass
- **It caught a real defect immediately.** `narrative-brief.md` cited shareholder
  letters for FY2022–FY2025 and never disclosed that FY2021 has none, while
  `discussion-points.md` stated it explicitly. Constraint 6 exists for exactly this —
  an apparent change in leadership voice at that boundary may be a missing document
  rather than a change in tone. Repaired for $0.21; the inserted sentence says there is
  "no FY2021 letter against which to baseline the tone or the admissions that follow"
- **Hard versus review is the design decision.** A check that fires on correct
  documents trains the reader to skip it. Measured before writing any thresholds:
  "never compare segment counts" fired on 6 sentences, **all 6 false positives** (the
  company's own "one reportable segment" quotation; PitchBook's "companies segment").
  Reg FD labelling flagged **23 of 36** paragraphs, because the documents name the
  register once and let the `QA-` prefix carry it — which is what the pack's own
  constraint says the prefix is for
- **Two bugs in my own checks, found by testing against failure.** The sentence
  splitter ran over the whole body and welded the last sentence of one paragraph to the
  next paragraph's heading — that artifact alone produced one segment-detector hit. And
  the "QA counts as a series" check ran on sentences, while such an enumeration is
  written with semicolons and a colon, which the splitter breaks on; it found nothing
  until moved to paragraphs
- **Checks carry a stable `tag`** alongside their prose name, so the constraint repair
  can skip the two provenance checks by tag rather than by matching a substring of a
  sentence that will get reworded
- `render_timeline.py` raised a bare `FileNotFoundError` on a clean rebuild instead of
  naming the stage that produces its input. Now fails loudly with the command to run
- Verified: pack rebuilds **byte-identically** from nothing (same sha256), timeline.md
  reproduces identically, all five test files pass (13 + 24 + 35 + 44 + 35 checks)
- Next: item 12 — `preflight`, then `verification-suite`, before treating any output
  as shareable

### 2026-08-07 — item 10e: the two prose deliverables

- **All three outputs now exist.** `narrative-brief.md` (2,007 words, 125 citations to
  118 distinct facts) and `discussion-points.md` (3,527 words, 202 citations to 179
  facts), from the pack in two calls sharing a cached prefix
- **The finding: the id check gives false assurance.** 323 of 324 ids resolved on the
  first run; only 110 of 118 quotations were verbatim filing text. Ids sit beside the
  fact and get copied; quotations are reconstructed from memory 300,000 tokens later,
  and one word off is invisible — "low 20's percent range" quoted as "low 20 percent
  range", "our most vulnerable segment" as "the most vulnerable segment"
- **The worst defect was a real quotation on a false claim.** "cannot be made" appears
  in the pack exactly once, in a fact about assessing the impact of tax legislation;
  the brief used it in a sentence about segment-level profitability. `elsewhere` is
  therefore not a benign category, and the check now records where each phrase
  actually came from
- **Repaired for $1.19 rather than $6.** The repair call carries the document and the
  disputed quote fields, not the 354,000-token pack. Both documents now show zero
  defects — 44/44 and 65/65 — and the brief's citations *rose* 122 → 125, because
  three repairs added the id the phrase genuinely came from
- **Two bugs in my own checker, found by reading its output.** It captured US-style
  punctuation inside the closing quote mark, and treated the gap between two adjacent
  quotations as a quotation. Both inflated the failure count; the second produced a
  phantom defect out of the words ` rather than a `. A third, `MIN_QUOTE_CHARS = 12`,
  was excusing a real ten-character fabrication — swept the threshold and 4 catches it
  with no false positives
- **`word_count` was over-counting by ~2%**: stripping ids left `[, ]` behind and
  `split()` counted the leftovers as words. It now removes whole citation groups
- **Cache lesson.** The 5-minute cache expired *between* calls, because the
  discussion-points call took longer than five minutes to produce 27,000 output tokens.
  Its repair then paid a $2.22 write instead of a $0.18 read. When one call runs for
  minutes, the 1-hour cache wins below its nominal 2.3-read break-even
- 35 checks in `tests/test_generate_outputs.py`, every fixture a real string from the
  first run; all four test files pass
- Next: 10f, `src/verify_outputs.py` — the constraint checks, mechanical and free

### 2026-08-06 (continued) — item 10d: output/timeline.md

- **The first deliverable is written.** 76 rows — 40 material dated events, 10 routine
  governance, 26 the filings never dated — each carrying its fact id and filing
- **It needed no model call, and that is the finding.** Every field the table requires
  is already in the ledger; the only thing a model could add is rewriting descriptions,
  which would be a paraphrase of a paraphrase with no check possible at either step. The
  renderer asserts its own completeness instead: every input id appears in exactly one
  table or the file is not written
- **Reading the first draft surfaced four data problems** — which is why the timeline
  was scheduled ahead of the prose:
  - **Undated rows must never be merged.** The two closest pairs are 1.5 points apart
    and opposite: 98.9 is one SmartX impairment reported twice, 97.4 is two different
    years of templated dividend guidance. Merging on text would have collapsed four
    years of distinct guidance into one row
  - **The filings date Bevin Desmond's departure two different ways** (2022-05-06 and
    2023-01-31). Both kept, marked ‡, neither presented as correct. Detected from
    structured fields because at a 100.0 text score it is indistinguishable from two
    genuine Dubinsky role changes — the role strings differ, so the structured key
    separates them and text cannot
  - **Four dated rows predate FY2021**, described by in-scope filings. Marked
    *(predates the window)* rather than dropped
  - A raw enum (`role_changed`) was leaking into prose descriptions
- Fixed a `config/outputs.toml` corruption of my own making: writing regex patterns
  through a shell heredoc into a non-raw Python string turned every `\b` into a literal
  0x08 backspace, ten of them. Repaired via a directly-written file, and swept all four
  config files for control characters
- 35 checks in `tests/test_merge_events.py`; timeline.md verified identical across
  rebuilds apart from its `Generated` line
- Next: 10e, `narrative-brief.md` then `discussion-points.md` — the steps that do spend
  tokens (~$2–3)

### 2026-08-05 (continued) — 8-K triage

- **Scoped the 75 unjudged 7.01/8.01 8-Ks before building anything**, and the
  scoping changed the plan. The six material events they appear to hold — the
  Praemium and LCD acquisitions, the Japan unwind, the AssetMark TAMP sale, CRSP,
  and a $500M repurchase authorization — turned out to be **already in the ledger
  from the 10-K**. Checked rather than assumed; the event-recovery case was much
  weaker than it looked
- What the filings genuinely add is the **Reg FD investor Q&A**: ~990,000 chars
  of management answering investor questions monthly, with no substitute anywhere
  else in the corpus
- **Built the triage log first** (`src/triage_8k.py`), because `config/forms.toml`
  asks for it in as many words and it costs nothing. 60 read / 15 date_only, all
  15 drops dividend declarations, every decision carrying its evidence
- Verified the guard on the case that mattered: the 2022-12-09 filing is titled
  as a dividend declaration and also authorized a $500M buyback. It was kept
- **Auditing my own log found a pattern gap** — the Japan filing reads "entered
  into a (i) Termination Agreement", and the `(i)` defeated the pattern. It was
  read anyway via the unrecognised-defaults-to-read fallback, but logged as "no
  signal matched", which understated the evidence. Fixed the pattern and split
  the log message so a mention is never reported as nothing
- Extracted FY2025's Q&A: 11 calls, 0 failures, **186 facts, $1.53**
- **The first unverified quotes in the project — 4 of 186 — and all four were
  false negatives in my verifier.** Three were the model emitting the literal
  six characters `\u2019` instead of `’`; one was a Workiva image placeholder
  sitting inside a sentence in the source, which my own trimmer removes on the
  input side but not on the verification side. Fixed both in `canon()`
- **Wrote `tests/test_verify_quote.py`** because loosening the check three times
  without re-proving the rejections is how a verifier quietly becomes a rubber
  stamp. 6 pass-cases, 6 reject-cases, all correct
- Hand-checked 14 stored quotes against `data/raw/` re-parsed from scratch with
  BeautifulSoup, not trusting `data/sections/` at all: 14/14 found
- Found that **zero Item 2.01 filings exist in the window** despite two completed
  acquisitions and a divestiture — MORN furnishes deal news under 7.01. The
  configured item filter contributed no transaction coverage at all
- Next: user's call on the remaining four years of Q&A (~$4), then milestone 5

### 2026-08-05 (continued) — investor Q&A, all five years

- **850 Q&A facts from 54 filings across FY2021–FY2025.** Ledger now 1,329 facts,
  3 unverified quotes, 54 low
- **Found a bug that had silently deleted eleven filings.** The boilerplate
  stripper assumed an unterminated forward-looking caution ran to the end of the
  document; in FY2021–FY2022 the caution is followed directly by the Q&A heading,
  so it discarded ~8,700 of ~9,000 characters. Those filings then fell below the
  stub threshold and dropped out of the extraction plan **with no message** — the
  run reported 32 of 32 successful while being 11 short. FY2022's readable content
  went from 85,502 to 230,221 chars once fixed
- Fixed both halves, because either alone would have left the fault silent: the
  stripper now keeps everything when it cannot locate the end of a block, and a
  filing that triage routed to a task but that yields no readable document is now
  a fatal error
- **Discovered the cache had gone stale under 24 results.** Fixing the stripper
  changed their input text without changing their filenames. Added an input check:
  each result stores its `source_chars`, a mismatch stops the run, and
  `--refresh-stale` rebuilds only those. Re-ran the 24; one failed on a genuine
  generation degeneration (`of.of.of.of…`, unclosed JSON) and succeeded on retry
- **Found the project's first genuine paraphrase.** A FY2022 quote turned "we are
  gaining traction and seeing increased interest BUT have not yet seen significant
  adoption" into "WE have not yet seen significant adoption" — subordinate clause
  promoted to a sentence, offsetting half dropped, and the fact then called it "a
  direct admission... hedging a growth narrative." Two words, and the claim got
  stronger than the filing supports. It is 96% character-exact, which is why the
  3-character tolerance stays where it is. Added to the test file as a regression
  case drawn from real output
- Left two false negatives in place deliberately and recorded why: recovering them
  would mean tolerating a 12-character tail or gaps in the source, and the latter
  would dismantle the defence against stitched quotes
- Next: milestone 5, the three outputs
