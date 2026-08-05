# DATA.md — provenance

Recorded at intake so coverage and completeness claims are auditable rather than
asserted. Update this file when the source, universe, or as-of date changes.

## Source

| Field | Value |
|---|---|
| Source | SEC EDGAR (public) |
| Ticker → CIK resolution | SEC `company_tickers.json` |
| Filing metadata | EDGAR submissions JSON API (`data.sec.gov/submissions/CIK##########.json`) |
| Documents | Filing HTML as filed, retrieved via `edgartools` |
| Access library | `edgartools` (version pinned in `uv.lock`) |
| As-of date | **2026-08-04** — submissions index pulled 2026-08-04T18:08Z; documents fetched same day |
| Universe | One company at a time, per `config/company.toml` |
| Window | Five fiscal years, per `config/company.toml` `[window]` |
| Subject | MORN / Morningstar, Inc., CIK 0001289419, FY2021–FY2025 |
| Retrieved | 202 documents across 128 filings — see `data/raw/fetch-manifest.json` |
| Extraction model | `claude-opus-5`, effort `medium`. The ledger as it stands represents **88 cached calls, 1,086,058 input / 235,841 output tokens ($11.33)** — 34 for the six core tasks, 54 for `investor_qa`. About $2.60 more was spent on 24 superseded first-pass results (see limitation 16) and one failed call, so total outlay was ~$14 |

### One filing outside the window, by name

`0001289419-26-000028` (8-K, filed 2026-05-08) is the 202nd document and the only
one from outside FY2021–FY2025. It carries the Item 5.07 vote taken at the
2026-05-07 annual meeting, which is the vote on **FY2025** compensation — a
say-on-pay result for a year in the window is reported in a filing dated after
it, because the meeting happens the following spring.

Fetched by explicit accession (`src/fetch.py --accession`), not by widening the
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
   `src/pdf_text.py` recovers the text by deriving the glyph-to-character offset
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
   another). See the KNOWN LIMITS note in `src/extract_sections.py`.

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
   `src/triage_8k.py` judged them on content; the decisions and their evidence are
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
   - **The cache detects a changed input.** `src/extract_facts.py` compares each
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
(`verify_quote` in `src/ledger_schema.py`). This exists because a model asked for
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
`uv run python tests/test_verify_quote.py` asserts that the check still refuses a
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

The last of those was self-inflicted and is worth naming: `src/triage_8k.py`
strips those placeholders before sending text to a model, while verification runs
against the untrimmed section. Trimming the model's input cannot make a bad quote
pass — that direction is safe by construction — but it can make a good one fail,
and it did. For the same reason the trimmer marks its one interior deletion with
an explicit `[... omitted ...]` marker, so a quote written across the seam fails
verification instead of silently reading as contiguous text.

All four of those failures were false negatives. **No fabricated or paraphrased
quote has yet been found in any extraction run** — which is not the same as saying
none will be, and is the reason the check stays.

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
