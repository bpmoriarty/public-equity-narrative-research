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

**Phase:** Building

**Last Session:** 2026-08-05

**Overall Health:** 🟢 Working — milestones 1–4 complete; 1,329 facts, all individually citable. Milestone 5 in progress: 10a done, 10b next

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
- **The cache now verifies its input** (`--refresh-stale`). "A completed task is
  never re-run" is only safe while its input is unchanged, and a filename cannot
  know what it was computed from. Each cached result stores its `source_chars`,
  and a mismatch stops the run rather than passing as done
- **The quote verifier now has a committed test** (`tests/test_verify_quote.py`).
  Six pass-cases and six reject-cases, run with one command. It exists because
  the normalization has been loosened three times and each loosening is exactly
  when the rejections need re-proving
- **Coverage.** 10-K and DEF 14A complete for all five fiscal years

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
  dismantle the stitched-quote defence. See DATA.md, Quote verification
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

### Milestone 5 in progress. 10a done; 10b is next.

Scoped 2026-08-05, three design questions answered (see Recent Decisions), sizing
below measured rather than estimated.

**10a — fact ids — is done.** 1,428 ids (1,329 facts + 99 risk deltas), unique,
reproducible, and verified additive: strip the two new keys from the rebuilt ledger
and it is byte-identical to the pre-change snapshot in all five years. Rebuilds are
still byte-identical to each other. `tests/test_fact_id.py` locks the design in.

Two things worth knowing before 10b:

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
    - b. [ ] `src/build_pack.py` — the 219K-token citable pack (deterministic)
    - c. [ ] Event dedup/merge + the "period unclear" split (deterministic)
    - d. [ ] `timeline.md` first — cheapest to check, surfaces dedup problems
    - e. [ ] `narrative-brief.md`, then `discussion-points.md` as two calls
    - f. [ ] `src/verify_outputs.py` — the five output constraints, mechanical
11. [ ] Optional, if the board narrative proves load-bearing: per-year verified
        boundaries for `DEF14A_director_bios` and `DEF14A_proposals_and_votes`
12. [ ] Run `preflight`, then `verification-suite` before treating any output as
        shareable

---

## Important Files

| File | What It Does |
|------|--------------|
| `CLAUDE.md` | Project rules — EDGAR access, extraction approach, traceability. Read first |
| `SPEC.md` | Document scope, extraction targets, ledger schema, output specs |
| `DATA.md` | Provenance, as-of date, and 9 known limitations. Read before making any coverage claim |
| `PROMPT.md` | The original kickoff prompt and its milestone gates |
| `config/company.toml` | Ticker, CIK, window, rate limits. **The only file to edit to retarget** |
| `config/forms.toml` | In-scope forms, 8-K item filter, gap signals, scope-extension block |
| `config/sections.toml` | Section boundary regexes, anchor phrases, validation rules |
| `src/discover.py` | Milestone 1. Inventory and gap analysis. No documents downloaded |
| `src/fetch.py` | Milestone 2. Cache-first document downloader. `--dry-run`, `--limit` |
| `src/pdf_text.py` | PDF text extraction with subsetted-font glyph decoding. `--selftest` |
| `src/extract_sections.py` | Milestone 3. Section location + validation. **Read its KNOWN LIMITS docstring** before trusting any proxy section |
| `data/sections/sections-manifest.json` | Every section with char count, boundary basis, and validation result |
| `src/risk_diff.py` | Deterministic year-over-year risk factor diff. No model calls |
| `src/ledger_schema.py` | Ledger shape, confidence rules, and `verify_quote` — the grounding check |
| `src/extract_facts.py` | Milestone 4a. The only stage that spends tokens. `--estimate` costs nothing |
| `src/build_ledger.py` | Milestone 4b. Assembles, verifies every quote, validates, writes |
| `data/ledger/FY*.json` | **The ledger.** Everything downstream derives from here, never from raw sections |
| `data/ledger/ledger-report.md` | Cross-year coverage, confidence counts, and comparability warnings |
| `data/ledger/facts/` | Cached per-task extraction results. A completed task is never re-run |
| `src/triage_8k.py` | Judges the 75 conditional 7.01/8.01 8-Ks. Deterministic, no model calls |
| `config/forms.toml` `[eight_k.triage]` | Triage patterns, headline window, size cap. Change behaviour here, not in code |
| `data/triage/triage-8k.json` | Every triage decision with its evidence. Committed — it is the record of what was excluded |
| `data/triage/triage-report.md` | The auditable log, including the full drop list |
| `tests/test_verify_quote.py` | Proves the grounding check can still reject. Run it after any change to `canon` |
| `tests/test_fact_id.py` | Proves ids are stable against judgments and sensitive to content. Run it after any change to `fact_id` or `risk_delta_id` |
| `data/discovery/inventory.json` | **Machine source of truth** for what's in scope. Later stages read this, not config |
| `data/discovery/discovery-report.md` | The human-readable inventory and gap analysis |
| `data/raw/FY*/…` | Cached documents by fiscal year and form. Never delete — rebuilding means re-hitting EDGAR for all 201 |
| `data/raw/fetch-manifest.json` | Every document with size, SHA-256, source URL |

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
- Next: 10b, `src/build_pack.py` — the 219K-token citable pack

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
