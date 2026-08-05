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
| Extraction model | `claude-opus-5`, effort `medium` — 34 calls, 571,664 input / 66,406 output tokens |

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
   `config/forms.toml` `[eight_k].include_items` are processed. Item 2.02
   earnings releases are logged by date only. Anything outside both lists is
   never seen. Coverage claims must say "material 8-Ks as defined in
   `config/forms.toml`," never "all 8-Ks."

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

Result on the current run: **479 facts, 0 unverified quotes.** The check was
separately confirmed to reject fabricated quotes, paraphrased tails, quotes
stitched together from two passages, an extra appended word, and fragments too
short to be evidence. A 100% pass rate only means something alongside evidence
that the check can fail.

### Confidence

Every fact carries `high` or `low` with the reason recorded on it. `low` means
the source section's boundaries are unverified (limitation 9) or the quote could
not be verified. On the current run **51 of 479 facts are `low`**, all of them
board-composition facts from `DEF14A_director_bios`.

**Any claim in the outputs resting on a `low` fact must say so, or be dropped.**
