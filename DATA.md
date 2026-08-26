# DATA.md — provenance

Recorded at intake so coverage and completeness claims are auditable rather than
asserted. Update this file when the source, universe, or as-of date changes.

> **Paths in this file are relative to the company folder.** Since Phase 2 each
> company owns one directory — `companies/<TICKER>/` — holding its config, its
> cached filings, its ledger and its deliverables. So `data/ledger/FY2023.json`
> below means `companies/MORN/data/ledger/FY2023.json`, and `output/timeline.md`
> means `companies/MORN/output/timeline.md`. They are written that way because
> that is how the manifests store them: relative to the company, so the same
> record reads correctly for any company. `config/forms.toml`, `sections.toml`,
> `outputs.toml` and `llm.toml` have no prefix — they are global defaults shared
> by every company, and a company overrides one by dropping a partial file in
> `companies/<TICKER>/overrides/`.

## Source

| Field | Value |
|---|---|
| Source | SEC EDGAR (public) |
| Ticker → CIK resolution | SEC `company_tickers.json` |
| Filing metadata | EDGAR submissions JSON API (`data.sec.gov/submissions/CIK##########.json`) |
| Documents | Filing HTML as filed, retrieved via `edgartools` |
| Access library | `edgartools` (version pinned in `uv.lock`) |
| As-of date (the **data**) | **2026-08-04T17:56:07Z** — when the submissions index was read from EDGAR. `inventory.json` `as_of_utc`. Documents fetched the same day |
| Run date (the **artifact**) | `data/_meta/run-log.json` → `discover.run_utc`, with `index_age_days_at_run` recording the gap. **Moved out of `inventory.json` in Phase 4.8**: a clock inside a file that is otherwise a pure function of its inputs made a committed artifact change on every run. The run log is gitignored. Only the as-of date bears on how current the coverage is, which is why the two live in different files now |
| Universe | One company at a time, per `companies/<TICKER>/company.toml` |
| **Fiscal window** | Up to ten fiscal years, per `companies/<TICKER>/company.toml` `[window]`; five for MORN. FY2021–FY2025 = `2021-01-01 .. 2025-12-31` in calendar time (`inventory.json` `window_start_date` / `window_end_date`). **This bounds the fiscal years in scope, not the documents.** |
| **Document window** | The filing dates of the documents the ledger is actually drawn from, which run **past** the fiscal window end by construction — a 10-K, a proxy and an annual-meeting vote all report on a year after it closes. Measured, not asserted: `data/ledger/ledger-report.md` § *Document window*, and per year in `FY*.json` `data_quality.document_window` |
| Subject | MORN / Morningstar, Inc., CIK 0001289419, FY2021–FY2025 |
| Retrieved | 202 documents across 128 filings — see `data/raw/fetch-manifest.json` |
| Extraction model | `claude-opus-5`, effort `medium`, **for all eight tasks** — `[extraction.models]` in `company.toml` can set a model per task and ships empty. The ledger as it stands represents **88 cached calls, 1,086,058 input / 235,841 output tokens ($11.33)** — 34 for the six core tasks, 54 for `investor_qa`. About $2.60 more was spent on 24 superseded first-pass results (see limitation 16) and one failed call, so total outlay was ~$14 |
| Which model answered what | Per record, in `data/ledger/facts/*.json` `model`. Read it there rather than from this table: the cache key is (fiscal year, task, filing) and does **not** include the model, so a mixed-model ledger is possible and this row would not show it. A model change never invalidates a cached result — staleness keys on the source text — so records can outlive the config that produced them |
| Backend | `claude_code` (default, needs a Claude seat and no API key) or `api`, per `config/llm.toml`. Recorded per record in `data/ledger/facts/*.json` `backend`; **absent means `api`**, which is what the 88 records committed before the seam existed carry |

### One filing outside the FISCAL window, by name

First, the distinction that makes this section readable, because getting it wrong
is the single easiest mistake to make about this dataset:

- **Outside the fiscal window** means the filing itself belongs to a fiscal year
  outside FY2021–FY2025. **Exactly one** filing does.
- **Filed after the fiscal window ends** means only that the document is dated
  after 2025-12-31. **Six** filings are, and five of them are ordinary FY2025
  documents — the 10-K, the proxy, two DEFA14As and the ARS — filed in early 2026
  because that is when a company reports on a year that has just closed. Nothing
  is unusual about them, and none of them is outside the window.

`0001289419-26-000028` (8-K, filed 2026-05-08) is the 202nd document and the only
one from outside FY2021–FY2025. It carries the Item 5.07 vote taken at the
2026-05-07 annual meeting, which is the vote on **FY2025** compensation — a
say-on-pay result for a year in the window is reported in a filing dated after
it, because the meeting happens the following spring.

It is also why `in_window` is `false` on that row in `inventory.json` while twelve
`VOTE-FY2025` facts nonetheless depend on it: `in_window` is computed on fiscal
year (`src/equity_research/discover.py`), and the filing's own fiscal year is 2026. The attribution
is correct — reaching forward is the only way to apply one consistent rule to all
five years — but the flag reads as an exclusion and is not one.

Fetched by explicit accession (`uv run python -m equity_research.fetch --accession`), not by widening the
window: extending the window into 2026 would have swept in a sixth year of 10-Qs,
Form 4s and earnings 8-Ks and quietly changed what every coverage claim in this
file means. Coverage claims therefore remain "FY2021–FY2025, plus one named 8-K
reporting the FY2025 vote".

The manifest records a SHA-256 for every document, so the cache can be verified
against what was actually downloaded rather than assumed intact.

### Scope extension beyond SPEC.md

SPEC.md §1 names four in-scope forms. Three more were added on 2026-08-04:
`DEFA14A` (supplemental proxy material), and `UPLOAD` / `CORRESP` (SEC staff
comment letters and the company's replies). Recorded in `config/forms.toml`
under an explicit scope-extension block.

Coverage claims must therefore say "the seven form types in `config/forms.toml`",
not "the forms in SPEC.md".

## Subject relationship (current run: MORN)

The analyst is an employee of the subject company, Morningstar, Inc.

This is not a compliance concern — every input is a public SEC filing, and no
non-public information enters the pipeline at any stage. It is recorded because
it cuts both ways analytically, and the second direction is the one this project
is built to resist:

- **An asset for validation.** Familiarity with the company makes it possible to
  catch a subtly wrong extraction that would pass unnoticed for an unfamiliar
  company — a misattributed leadership change, a segment renamed in fact but not
  in the filings, a boundary failure that produced plausible-looking nonsense.

- **A source of exactly the bias the traceability rule exists to prevent.**
  Knowing the answer makes it easy to read a gap in the filings as though the
  filings had addressed it. CLAUDE.md's rule is absolute here and its cost is
  highest on a company the analyst knows well: if a claim cannot be traced to
  `(form, fiscal year, accession number)`, it does not go in the output — no
  matter how confident the analyst is that it is true.

Practical consequence: where the filings are silent or ambiguous, the outputs
must say so. "The filings do not address X" is a valid and useful finding.
Substituting internal knowledge for a citation is not, and would make the
outputs indefensible to any reader who cannot see what the analyst knows.

## Known limitations

These are properties of the source, not bugs to fix. Any claim the outputs make
has to survive them.

1. **EDGAR is not the complete narrative record.** Earnings call transcripts are
   not filed with the SEC and are out of scope (SPEC.md §1). Investor days,
   press releases not furnished on an 8-K, and analyst-day decks are absent. The
   outputs describe *what management disclosed to the SEC*, which is narrower
   than *what management said*.

2. **Shareholder letters are inconsistently filed.** Some companies file an ARS,
   some attach the letter as an EX-13 exhibit to the 10-K, some furnish it on an
   8-K, and some never file it to EDGAR at all. Where a letter is missing for a
   year, the gap must be stated in the outputs, not silently absorbed — an
   apparent change in leadership voice may just be a missing document.

3. **Fiscal ≠ calendar year.** A FY2024 10-K is typically filed in early 2025.
   Companies also change their fiscal year end, which makes one "year" a stub
   period of a few months. Discovery must report the fiscal-to-filing-date
   mapping and flag any fiscal-year-end change.

4. **8-K coverage is deliberately partial.** Only the items in
   `config/forms.toml` `[eight_k].include_items` are processed, plus the
   conditional 7.01/8.01 filings that survive triage (limitation 13). Item 2.02
   earnings releases are logged by date only. Anything outside those lists is
   never seen. Coverage claims must say "material 8-Ks as defined in
   `config/forms.toml`," never "all 8-Ks."

   **The item filter did not catch a single transaction in this window, and that
   is a finding about the filter rather than about the company.** There are ZERO
   Item 2.01 filings ("completion of acquisition or disposition of assets") and
   zero Item 2.05 filings across FY2021–FY2025, although MORN completed the
   Leveraged Commentary & Data and Praemium acquisitions, sold its US TAMP assets
   to AssetMark, unwound its Morningstar Japan holding, and announced the CRSP
   acquisition inside that period. Every one of those was furnished under Item
   7.01 or 8.01 instead. `include_items` is not wrong, but for this filer it
   contributed no transaction coverage at all — the acquisitions in the ledger
   come from the 10-K's Item 1 and MD&A, which independently captured all of
   them. Do not describe the 8-K stream as the source of the deal record.

5. **Restatements and amendments.** A 10-K/A supersedes parts of the original
   but does not replace it on EDGAR. Both are in the window. Where an amendment
   changes a narrative fact, the pipeline must carry both readings rather than
   silently preferring one (CLAUDE.md, Traceability).

6. **Survivorship is not a concern here, but selection is.** The company is
   chosen, not sampled, so nothing generalizes beyond it. No cross-company
   comparison in the outputs is supported by this data.

7. **The FY2022 shareholder letter text is a RECONSTRUCTION, not a direct read.**
   That letter (`ARS`, accession 0001104659-23-039633) was filed as a PDF;
   FY2023–FY2025 are HTML. The PDF embeds a subsetted font with no ToUnicode
   CMap — it records glyph *ids* with no table saying which characters they are.
   `src/equity_research/pdf_text.py` recovers the text by deriving the glyph-to-character offset
   from the document itself (+29 for this font, derived from the space glyph's
   frequency, not hardcoded) and validating the result against English sentinel
   words. The decode reported 0 unmapped glyphs, 0 undecoded markers, and a
   99.93% printable ratio.

   Two residual imperfections, both deliberate and neither affecting meaning:
   - **Ligatures** `fi`, `fl`, `ff` are reconstructed from single glyphs.
   - **One glyph serves as both em dash and minus sign** in this font. It is
     mapped to ASCII `-`, so a negative figure like `-38.1%` reads correctly
     while an em dash in prose renders as a hyphen (`Index-a benchmark`). The
     tie was broken toward the numbers on purpose: a hyphen for an em dash is
     cosmetic, whereas a lost minus sign silently inverts a fact.

   Consequence for the outputs: any FY2022 letter passage quoted verbatim has
   passed through this decode. It is faithful and validated, but it is not a
   byte-for-byte read of the filing the way the HTML sources are. Flag it if a
   quotation from that letter carries analytical weight.

   The six `UPLOAD` PDFs are unaffected — the SEC files a `.txt` twin of each,
   and those PDFs have proper font encoding anyway (verified: the decoder
   correctly detects it and passes them through untouched).

   **`pypdf` was tried first and rejected.** It coerces unmapped glyphs toward
   whitespace, which turned every digit in the letter into a space: "the index
   fell 15% for the full year" came out as "fell for the full year". Plausible
   prose with the facts silently deleted — the worst possible failure here,
   because nothing downstream could have detected it. `pdfminer.six` preserves
   unmapped ids as `(cid:N)` markers instead, so nothing is destroyed. Prefer a
   library that preserves what it cannot interpret over one that guesses.

8. **The FY2021 shareholder letter does not exist on EDGAR.** Verified, not
   assumed: no `ARS` was filed for FY2021, and no `EX-13` exhibit appears in any
   of the five 10-Ks. So FY2021 has no leadership-voice source. An apparent shift
   in tone between FY2021 and FY2022 must not be read as a real change — the
   FY2021 baseline is simply missing.

9. **Two proxy sections have unverified boundaries.** Everything extracted from
   the 10-Ks is boundary-verified (structural item map, identical across all five
   years), as are the proxy CD&A and incentive tables. Two are not:

   - **`DEF14A_director_bios`** — FY2025 is known wrong: it begins at the
     front-of-proxy voting summary rather than at the director biographies. The
     other four years are plausible in size but unchecked.
   - **`DEF14A_proposals_and_votes`** — FY2022 was checked and is correct at
     6,883 characters; the other four years run 21k–25k, which suggests those
     over-capture rather than FY2022 being short.

   Both fail the same way: a heading appears once in the front-of-proxy summary
   and again at the real section, and no single global rule separated them across
   all sections and years (three were tried; each fixed one section and broke
   another). See the KNOWN LIMITS note in `src/equity_research/extract_sections.py`.

   **Consequence, and how it is handled:** every ledger field carries a
   `confidence` marker, and anything sourced from these two sections is recorded
   as `low` with the reason attached. Affected content is board composition and
   tenure only. Vote OUTCOMES are not affected, because the proxy is the wrong
   source for them regardless — a DEF 14A solicits a vote, it does not report the
   result. Say-on-pay and proposal tallies come from the **8-K Item 5.07**
   filings, which are extracted whole and need no boundary detection.

   Any claim in the outputs that rests on a `low`-confidence field must say so,
   or be dropped.

10. **`segments` does not mean the same thing in every year.** MORN's FY2021 and
   FY2022 10-Ks never use the phrase "reportable segment" in Item 1 or Item 7;
   the FY2023, FY2024 and FY2025 filings do. So for the first two years the
   ledger's `segments` field holds whatever product or business areas Item 1
   happens to describe, and from FY2023 it holds the reportable segments the
   filing names.

   Consequence: **the segment counts must not be compared across that boundary.**
   Going from 3 items in FY2021 to 10 in FY2022 to 6 from FY2023 is not a
   re-segmentation of that shape — it is a change in what the filing discloses,
   plus the extraction answering a different question in each regime. A real,
   traceable re-segmentation does sit inside this window (five reportable
   segments first appear in the FY2023 10-K, and "Morningstar Data and Analytics"
   is reported as "Morningstar Direct Platform" in FY2025), but it has to be
   stated from the segment *names and the filing's own language*, never from the
   counts.

   Each year's ledger record carries this in
   `data_quality.segments_basis`, detected from the filing text rather than
   hardcoded, so the flag stays correct for the next company.

11. **Vote results are keyed to the year whose pay was voted on, and the events
   list is not.** A DEF 14A for fiscal year N is filed the following spring and
   voted at that spring's meeting, so `vote_results` for FY N comes from an 8-K
   filed in year N+1. Meanwhile the `events` list for FY N may contain the vote
   held *during* FY N — which concerned FY N−1's compensation.

   Both are correctly sourced and dated, but they are about different years. The
   FY2021 record shows the shape: `vote_results` holds the May 2022 vote on
   FY2021 pay, while `events` includes the May 2021 vote on FY2020 pay. Any
   say-on-pay claim in the outputs must name the meeting date, not just the
   fiscal year, or the two collapse into one another.

12. **Section extraction is lossy by design.** Only the sections in
   `config/sections.toml` are extracted; the rest of each filing is discarded.
   A fact stated only in, say, Item 3 (Legal Proceedings) will not appear in the
   outputs. Where a boundary validation fails, that section is skipped for that
   year — see the extraction log before reading a year's thin coverage as a real
   absence of disclosure.

13. **15 of the 75 conditional 7.01/8.01 8-Ks were dropped from the history.**
   `src/equity_research/triage_8k.py` judged them on content; the decisions and their evidence are
   in `data/triage/triage-8k.json`, and the full drop list is printed in
   `data/triage/triage-report.md` for audit. All 15 are quarterly dividend
   declarations. Nothing else was dropped: a `date_only` decision requires
   positive evidence of a routine filing AND the absence of every material signal
   including passing mentions, and anything unrecognised is read.

   The asymmetry is deliberate and worth restating, because it is the reason to
   trust the drop list: a false "read" costs a fraction of a cent, while a false
   "date_only" removes a corporate event from a five-year history in a way no
   downstream stage can detect. The classifier is tuned to be wrong in the
   cheap direction. The 15 drops should still be re-read by eye before publication
   — it takes about a minute and it is the real safety net.

   One case shows why title-based filtering would not have been safe: the
   2022-12-09 filing is titled as a dividend declaration and also authorized a
   $500 million share repurchase program. It was kept, on the capital-allocation
   signal.

14. **The Reg FD investor Q&A is a different kind of evidence, and lives in its
   own ledger field.** MORN publishes written answers to investor questions
   roughly monthly under Item 7.01. These are management's own words and they are
   in scope, but they are not equivalent to a 10-K or proxy statement: unaudited,
   not required by any disclosure rule, and responsive to whatever investors
   happened to ask that month. They are therefore kept in `investor_qa` and never
   merged into `strategic_priorities`, `notable_language`, or `events` — once
   merged, nothing downstream could tell an off-hand monthly reply from an audited
   annual disclosure. Each year's record carries
   `data_quality.investor_qa_basis`. Treat this material as corroborating, and
   name it as Reg FD material wherever an output leans on it.

   Two further cautions on this field:

   - **Where the text lives changes inside the window.** The Q&A is inline in the
     8-K body for FY2021–FY2023 and a separate EX-99.1 exhibit from FY2024 on,
     with FY2024 containing both shapes. Any code that reads 8-K bodies only
     silently returns nothing for the later years while reporting the same number
     of filings processed. The triage log records which document carries the
     content per filing.
   - **Topics recur across months and are not independent observations.** In
     FY2025 six pairs of topics across different filings are near-duplicates —
     the Morningstar Wealth refocusing was asked and answered in June, August and
     September, and the James Rhodes departure twice. That recurrence is itself
     informative, and it means a count of Q&A facts is not a count of distinct
     findings. Do not treat repetition as corroboration.

15. **`investor_qa` counts are not a measure of how much management said.**
   All five years are now extracted — 850 facts from 54 filings (FY2021 113,
   FY2022 157, FY2023 231, FY2024 163, FY2025 186) — but the spread across years
   reflects how many questions were submitted and answered, and how long the
   answers ran, not any property of the company's strategy that year. FY2023 has
   twice FY2021's count largely because the FY2021 filings are shorter. Use this
   field for *what was said*, never as a series.

16. **24 of the 54 `investor_qa` results were extracted twice, and the first
   answers were discarded.** A boilerplate-stripping rule was too aggressive: when
   it could not locate the end of the forward-looking-statements caution it
   discarded everything from the caution to the end of the document. In eleven
   FY2021–FY2022 filings that deleted the entire Q&A, reducing ~9,000-character
   bodies to ~330 characters, and those filings then dropped out of the extraction
   plan without a message. Fixing the rule changed the input text of 24 already-
   cached results, which were re-run.

   Two guards now exist so this class of fault cannot be silent again, and both
   matter more than the bug did:

   - **The stripper fails toward keeping text.** An unrecognised layout costs a
     few cents in duplicated boilerplate rather than discarding a document.
     Removing boilerplate is a cost optimization; losing content is a correctness
     failure, and when they conflict the optimization loses.
   - **The cache detects a changed input.** `src/equity_research/extract_facts.py` compares each
     cached result's stored `source_chars` against the current source text and
     refuses to treat a mismatch as done. "A completed task is never re-run" is
     only safe while its input is unchanged, and a filename cannot know what it
     was computed from. Run `--refresh-stale` to rebuild only those.

## Cache policy

`data/raw/` is written once per document and read thereafter (CLAUDE.md: EDGAR
should be hit once per document, ever). It is gitignored — it is a large local
copy of public documents — but it must never be deleted casually, because
rebuilding it means re-hitting EDGAR for every filing.

Downstream stages are free to be re-run at will; only `data/raw/` is expensive.

## Data-quality logging

Per the top-level CLAUDE.md: log quality on the variables that actually enter
the analysis, not just intermediates. **Implemented** — every
`data/ledger/FY*.json` carries a `data_quality` block recording, per field: how
many facts, how many at each confidence level, how many failed quote
verification, and which source sections they came from.
`data/ledger/ledger-report.md` is the cross-year view.

A year with an empty `incentive_metrics` because extraction failed is therefore
distinguishable from a year where the proxy genuinely disclosed none:
`extraction_tasks_missing` names any task with no result file, so a gap in the
pipeline never reads as a gap in the disclosure.

### Quote verification — traceability as a test, not a promise

Every fact in the ledger carries an exact quote from its source section, and the
builder checks that the quote actually occurs in that section before storing it
(`verify_quote` in `src/equity_research/ledger_schema.py`). This exists because a model asked for
a citation always produces something citation-shaped. The failure that matters is
not a missing source, it is a *plausible* source for a claim the filing never
made — and nothing downstream can distinguish that from a real extraction.

Two consequences worth knowing when reading the ledger:

- **The stored quote is the verified span, not whatever the model emitted.**
  Where a generation artifact left a stray character or two on the end, the
  citation is trimmed back to what the filing demonstrably contains. A tail
  longer than three characters is treated as a paraphrase and fails.
- **Source attribution is measured, not asserted.** A task that reads two
  sections resolves each fact to a section by finding which one contains its
  quote, rather than asking the model where it looked. So a fact can only be
  attributed to a document that provably contains its evidence.
- **`value` IS NOT VERIFIED TEXT — only `quote` is.** Measured while building the
  output pack: of the 1,741 `value` strings longer than 40 characters, **just 3.1%
  appear verbatim in their own fact's quote.** The other 96.9% are model-written
  summaries, and `verify_quote` never ran on them — it only ever checked the
  `quote` field, which is exactly what it was designed to do.

  This is not a defect, but it is a sharp edge. `value` is for reasoning about;
  `quote` is for reproducing. **Anything placed inside quotation marks in an output
  must be copied from a `quote` field**, or it quotes the extraction rather than
  the company — and no check in this pipeline would catch it. The constraint is
  carried into `data/pack/pack.json` so the writers see it, not just this file.

Result on the current run: **1,329 facts, 3 unverified quotes (0.23%).**

**One of those three is a genuine paraphrase, and it is the first the project has
found.** In a FY2022 investor-Q&A extraction the filing reads "we are gaining
traction and seeing increased interest *but* have not yet seen significant
adoption of managed accounts as a default option in the plans we work with"; the
quote came back as "*We* have not yet seen significant adoption of managed
accounts as a default option in the plans we work with", promoting a subordinate
clause to a standalone sentence and dropping the offsetting positive half. The
fact then characterised it as "a direct admission... hedging a growth narrative."

Two words changed and the claim became stronger than the filing supports. That is
exactly the failure this check exists for, it is 96% character-exact, and it is
now a regression case in the test file. It is also the reason the near-miss
tolerance stays at three trailing characters rather than being widened to
accommodate the two artifacts below.

The other two are false negatives, both left in place deliberately:

- A 205-character verbatim quote with the literal text `_PLACEHOLDER` appended —
  a 12-character tail, over the threshold. Widening the threshold to 12 would
  admit real paraphrased endings.
- A quote whose source sentence contains a stray page number mid-clause ("tied to
  both **7** revenue and profit") in the filed document itself, confirmed by
  re-parsing the raw HTML independently. The model quoted the sentence as a human
  reads it. Tolerating gaps in the *source* would dismantle the defence against
  stitched quotes, which is a far more valuable property than three recovered
  facts.

Both are marked `low` with the reason on the fact, and their quotes are preserved
for inspection.

The rejection cases are a committed test rather than a claim:
`uv run python tests/unit/test_verify_quote.py` asserts that the check still refuses a
fabricated quote, a paraphrased ending, a quote stitched from two passages, an
inserted word, and a fragment too short to be evidence. A 100% pass rate means
nothing on its own — a checker that returns `True` unconditionally produces the
same number. The test exists because the normalization has been loosened three
times, and each loosening is exactly when the rejections need re-proving.

**What the three loosenings were, all triggered by real output, none by theory:**

| Symptom | Real cause | Fix |
|---|---|---|
| A 258-of-260-character match called a paraphrase | two stray characters after the closing full stop | accept a trailing tail of ≤3 characters — an absolute count, because a 99% ratio forgives the same artifact on a long quote and rejects it on a short one |
| 3 of the first 4 investor-Q&A failures | the model emitted a unicode escape as literal text — the six characters `\u2019` — where the character `’` belongs | decode literal `\uXXXX` escapes before comparing |
| 1 investor-Q&A failure | a Workiva image placeholder (`…9262025003.jpg`) sits *inside* a sentence in the extracted text | drop bare image filenames on both sides |

The last of those was self-inflicted and is worth naming: `src/equity_research/triage_8k.py`
strips those placeholders before sending text to a model, while verification runs
against the untrimmed section. Trimming the model's input cannot make a bad quote
pass — that direction is safe by construction — but it can make a good one fail,
and it did. For the same reason the trimmer marks its one interior deletion with
an explicit `[... omitted ...]` marker, so a quote written across the seam fails
verification instead of silently reading as contiguous text.

All four of those failures were false negatives — the check rejecting a good
quote, not catching a bad one. **The check has caught exactly one real
paraphrase** (the FY2022 case above) and **no fabricated quote** across 1,329
facts. One in 1,329 is not a reason to relax: it is the rate at which this failure
mode occurs when nothing is looking for it, and it took two changed words to turn
a hedged statement into "a direct admission."

### Event merging — what the timeline counts as one event

The 85 dated-event records in the ledger (`events` plus `leadership`) resolve into
**76 timeline rows: 50 dated and 26 with no usable date.** Nine records are
restatements of an event another filing already recorded, folding into **8
corroborated rows**.

Two records are judged to be one event when they share a date, come from
**different filings**, and their descriptions score at least 55 on `rapidfuzz`
`token_set_ratio`. Both halves matter, and the first is doing most of the work:

| | Similarity | Same event? |
|---|---|---|
| "Termination of the 2019 Credit Agreement and entry into a new 2022 Credit Agreement…" vs "Morningstar entered a new Credit Agreement with Bank of America…" — **two filings** | 72.9 | yes |
| "…Contract Services Agreement dated February 1, 2023 with Bevin Desmond…" vs "Separation Agreement and General Release dated February 1, 2023 with Bevin Desmond…" — **one filing** | 61.7 | **no** — two agreements, same officer, same day |

Eleven points apart, so a similarity-only threshold between them would be luck. A
filing does not report the same event twice, so the second pair is excluded by
construction — and the threshold then lands in an eleven-point gap (59.6 → 48.5)
instead of a three-point one. Merging is transitive, which is how the three records
describing the FY2025 refinancing become one row even though two of them share a
filing and never pair directly.

**Nothing is dropped by this stage.** All 85 input records appear in exactly one row;
the merged rows keep every source id, every filing's wording in
`also_described_as`, and the *lowest* confidence across their members, so merging
cannot promote a `low` fact by pairing it with a `high` one. Where two filings
classified the same event differently, `types_disagree` records the disagreement
rather than resolving it silently. Same-date pairs from different filings that fall
below the threshold are listed as possible duplicates for a human to check.

Ten rows are tagged **routine** annual-meeting governance — director elections,
auditor ratification, say-on-pay, regular dividend declarations — and *tagged, not
dropped*, so the rendering decision belongs to the document stage. That tag has a
material-override list, which exists because of a specific near-miss: "Shareholders
approved the Morningstar, Inc. Amended and Restated 2011 Stock Incentive Plan" sits
on the same date, in the same meeting, as four genuinely routine votes — and an
incentive plan change is a row type SPEC.md §4b names explicitly.

**Undated rows are never merged, whatever their wording**, and the reason is sharper
than "no date, no evidence". Among the 26 undated rows the two closest pairs are 1.5
points apart and fall on opposite sides of the truth: **98.9** is one $12.4m SmartX
impairment reported by two filings, and **97.4** is two *different years* of dividend
guidance whose wording is templated and differs only in an amount and a year. No
threshold separates them, so both are reported for a human and neither is merged.
Merging on text would have collapsed four years of distinct dividend guidance into
one row.

**One event is dated inconsistently by the filings.** Bevin Desmond's departure as
Chief Talent and Culture Officer is dated **2022-05-06** in one 8-K and **2023-01-31**
in another. Both rows are kept, marked ‡ in `output/timeline.md`, and neither date is
presented as correct — it may be an announcement date against an effective date, or
two separate changes; the filings do not settle it.

That conflict is detected from **structured fields** (name, change, role), not text
similarity, and the difference matters. At a text score of 100.0 there are two pairs
in this window: the Desmond departure, which is a real conflict, and two Jason
Dubinsky role changes a month apart, which are two genuine events. The structured key
separates them because the role strings differ ("principal accounting officer (in
addition to Chief Financial Officer)" against "principal accounting officer") — a
distinction a similarity score cannot see.

**Four dated rows predate FY2021** (a 2019 credit agreement, the 2020 Sustainalytics
buy-in, the 2020 senior notes, the 2020 repurchase authorisation). In-scope filings
describe them, so they are real and sourced; they are marked *(predates the window)*
rather than dropped.

Locked in by `uv run python tests/unit/test_merge_events.py` — 44 checks, fixtures drawn
from the real filings including every pair named above.

### Verifying the deliverables — what a check may and may not gate on

`src/equity_research/verify_outputs.py` reads the rendered Markdown in `output/` and holds each
document to the pack's binding constraints. Deterministic, free, and it exits non-zero
on any hard failure. **12 hard checks and 2 review lists per document.**

It reads the *rendered file*, not the generation record, and reuses the generator's own
`check_citations`/`check_quotes` rather than reimplementing them. Two implementations
of "is this quotation verbatim" would drift, and the one that drifted quietly would be
the one that mattered. What differs is the input: this catches a document edited by
hand after generation, one written from a different pack, and one whose provenance
footer no longer describes it.

**Hard versus review, and why the line is where it is.** A check that fires on correct
documents is worse than no check: it trains whoever reads the report to skip that line,
and it is still firing on the day it is right. So each check is one kind or the other,
never a blend — hard checks are decidable with no judgment and gate the run; review
lists are detectors with known false positives, printed with the sentence attached and
gating nothing.

Two constraints could only be review lists, and measurement is why:

- **"Never compare segment counts"** first fired on 6 sentences, **all 6 false
  positives** — the company's own "we have one reportable segment" quotation, and
  PitchBook's "companies segment", a different sense of the word entirely. Tightened to
  require years from *both* disclosure bases in the same sentence, it fires 0 times on
  the real documents and still catches a synthetic cross-basis comparison.
- **Regulation FD labelling** first flagged 23 of 36 paragraphs, because the documents
  establish the register once and then rely on the `QA-` id prefix to carry it — which
  is exactly what the pack's own constraint says that prefix is for. The hard check is
  therefore that the register is named *before the first `QA-` citation*; the
  paragraph-level list is review only.

**It caught a real defect on its first run.** `narrative-brief.md` cited
letter-sourced facts for FY2022–FY2025 and never said FY2021 has no letter — while
`discussion-points.md` stated the gap explicitly. That is precisely the risk
constraint 6 names: an apparent change in leadership voice across the FY2021/FY2022
boundary may be a missing document rather than a change in tone. Repaired for $0.21 by
a targeted call, and the inserted disclosure says so directly: *"there is no FY2021
letter against which to baseline the tone or the admissions that follow."*

**Two bugs in the checks themselves, both found by testing against failure.** The
sentence splitter ran over the whole body at once and welded the last sentence of one
paragraph to the first heading of the next — that artifact alone produced one of the
segment detector's hits. And the "investor_qa counts as a series" check ran on
sentences while a year-by-year enumeration is written with semicolons and a colon, on
which the splitter breaks; it found nothing until it was moved to paragraphs.

`uv run python tests/unit/test_verify_outputs.py` — 60 checks. Every hard check is exercised
against a document that should fail it *and* one that should pass; a check tested only
against passing input would still pass if its body were `return True`.

### Quotations in the outputs — the check the id check gives false assurance about

Every generated document is held to two mechanical checks, and **the second one is
where the defects are.**

| Check | First-run result |
|---|---|
| Every `[ID]` resolves to a fact in the pack | 323 of 324 — one bad id, repaired |
| Every quotation is character-for-character the filing's text | **110 of 118** — 8 defects |

The two are not redundant, and the gap between them is the point. An id is an opaque
string sitting beside the fact, and the model copies it accurately. A quotation is
reconstructed from memory of something read 300,000 tokens earlier, and **a quotation
one word off looks exactly like a correct one.** A sentence with a resolving id and a
misquotation reads as *more* sourced than an unsourced sentence would, so the id check
alone actively misleads.

The eight, all real, in three kinds:

- **Near-miss misquotation (2).** The filing says margins are in the "low 20's percent
  range"; the draft quoted "low 20 percent range". The filing says "our most vulnerable
  segment"; the draft quoted "the most vulnerable segment". One word, and the words are
  no longer the company's.
- **Phrase in no filing text anywhere (5).** "meaningfully lagged our expectations",
  "to pursue other interests", "was a typo", "the highest churn rate in PitchBook's
  business", "largely outside of the control or discretion of our segment leaders".
  Each captures what a fact *means*; none is in a filing. Two of these were the more
  damaging kind — the departure of the Direct Platform president was described as
  "later described as 'to pursue other interests'" when the follow-up filing gives no
  reason at all, so the repaired sentence is **more accurate than the original**.
- **Real filing text welded to an unrelated claim (7).** These matter more than the
  count suggests and are the reason `elsewhere` is not treated as a benign category.
  The brief wrote that the FY2024 10-K disclosed segment-level profit "cannot be
  made" — a verbatim phrase whose only occurrence in the pack is a fact about
  *assessing the impact of tax legislation*. A genuine quotation attached to the wrong
  proposition is a fabricated claim wearing a real citation. The check therefore
  records, for each of these, the id the phrase actually came from, because the whole
  difference between the harmless case (a term of art quoted a paragraph from its
  citation) and the serious one is whether that source has anything to do with the
  sentence.

Both are repaired by a targeted second call that is shown each defective quotation
beside the verified text of the facts cited with it, and must either copy the real
characters, drop the quotation marks and paraphrase, or delete the claim. It does
**not** resend the pack — the repair needs the document and a handful of quote fields,
about 8,000 tokens against 354,000 — so it runs at roughly $0.30 a document rather
than $2.22, and can repair documents already on disk without regenerating them.

After repair both documents stand at **zero defects**: 44/44 and 65/65 quotations
verbatim in a fact cited in the same paragraph, and every id resolving. The brief's
citation count *rose* 122 → 125, because three repairs added the id the phrase
genuinely came from rather than deleting the sentence.

**What this does not establish.** The check proves a quotation is the filing's text
and that its citation resolves. It cannot prove the sentence around the quotation is a
fair reading of it, and no mechanical check can. `claim` text remains unverified
paraphrase throughout — see the quote-verification section above.

### Fact identifiers — what an output is allowed to cite

Every fact and every risk delta carries a stable `id`. **1,428 ids on the current
run** (1,329 facts, 99 risk deltas), checked unique at build time. Two real ones,
both resolvable in `data/ledger/`: `EVT-FY2021-23afc21f` (the 364-day revolving
credit facility that expired unrenewed) and `QA-FY2023-67d4a8e7` (management on the
shift to cloud delivery for Data, Direct and Advisor Workstation).

This exists because `(form, fiscal_year, accession)` identifies a *filing*, not a
fact. For an 8-K carrying 40 investor-Q&A facts, a citation at that granularity
means "somewhere in this document" — which cannot be checked mechanically, and so
returns traceability to being a promise rather than a test.

The id is a truncated SHA-256 of the fact's claim, its evidence, and where the
evidence lives:

| In the hash | Deliberately out |
|---|---|
| `field`, `fiscal_year`, `value`, `quote` | `confidence`, `confidence_reason` |
| source `form`, `accession`, `section_key` | `quote_verified`, `quote_check`, `filing_date` |

**The asymmetry is the design: judgments about a fact do not change its identity;
the fact's content and evidence do.** If the `DEF14A_director_bios` boundaries are
fixed later (limitation 9), 51 board facts flip from `low` to `high`. Were
confidence in the hash, every one of those ids would change and every citation to
them in an already-written output would break — for a change that made those facts
*more* trustworthy, not different. A changed `quote`, by contrast, *should* mint a
new id, because the evidence moved and anything citing it needs re-checking.
`filing_date` is excluded because it comes from the inventory rather than from the
fact.

Two properties are enforced rather than assumed:

- **Uniqueness is checked, not trusted.** `build_ledger.py` audits every id on
  disk — including years not rebuilt in a partial run — and exits fatally on a
  collision rather than letting two facts share a citation. This fired on its first
  run: 46 reworded risk deltas collided because the id read `item["heading"]`,
  which exists on `added`/`removed` deltas but not on `reworded` ones, so all of
  them hashed a `None` heading. The delta id now hashes every non-measurement key
  on the item, an exclusion list rather than an include list, because a forgotten
  measurement key only causes visible churn while a forgotten identity key causes
  a silent collision.
- **Reproducibility is tested.** `uv run python tests/unit/test_fact_id.py` recomputes
  all 1,329 ids from the facts' own stored content and asserts they match, then
  asserts the id moves for a changed claim, quote, section, filing or year — and
  does *not* move when confidence is downgraded or a quote is re-verified.

Similarity scores on risk deltas (`heading_similarity`, `body_similarity`,
`body_chars`, `changed`) are excluded for the same reason as confidence: they are
measurements about the delta, and a `rapidfuzz` version bump that moves a score by
0.1 must not renumber every citation.

### Confidence

Every fact carries `high` or `low` with the reason recorded on it. `low` means
the source section's boundaries are unverified (limitation 9) or the quote could
not be verified. On the current run **54 of 1,329 facts are `low`**: 51
board-composition facts from `DEF14A_director_bios`, plus the 3 unverified quotes
above.

**Any claim in the outputs resting on a `low` fact must say so, or be dropped.**

Confidence deliberately does **not** encode *register*. Every `investor_qa` fact
is `high`, and that is correct: those documents have trivially correct boundaries
(whole documents) and their quotes verify. But a Reg FD investor reply is a weaker
kind of evidence than an audited annual filing, and that is recorded separately —
in the field name and in `data_quality.investor_qa_basis` (limitation 14) — rather
than by degrading the confidence marker. Folding two different things into one
flag would make both unreadable.
