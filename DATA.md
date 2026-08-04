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
| As-of date | *(set when discovery runs — the date the submissions index was pulled)* |
| Universe | One company at a time, per `config/company.toml` |
| Window | Five fiscal years, per `config/company.toml` `[window]` |

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

7. **Section extraction is lossy by design.** Only the sections in
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
the analysis, not just intermediates. For this pipeline that means the ledger
fields in SPEC.md §3 — for each fiscal year, record how many of
`strategic_priorities`, `segments`, `headcount`, `leadership`, `board`,
`incentive_metrics`, `risk_deltas`, and `events` were populated, and from which
source filing. A year with an empty `incentive_metrics` because the DEF 14A
extraction failed must be distinguishable from a year where the proxy genuinely
disclosed no metrics.
