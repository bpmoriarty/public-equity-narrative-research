# CLAUDE.md

## Project

A reusable pipeline that builds a five-year narrative history of a public
company from its SEC filings. Input: a ticker and a date range. Output: three
documents (narrative brief, structured timeline, discussion points) plus a
structured intermediate ledger.

This is a **narrative and governance** extraction project, not a financial
statement extraction project. Do not build XBRL parsing, financial statement
reconstruction, or ratio analysis. Numbers appear only where they anchor a
narrative claim (revenue trajectory, headcount, segment mix, comp figures).

## Repository layout

```
config/          # company config, section patterns, 8-K item filters
src/             # pipeline modules
data/raw/        # cached filings, by year/form — never delete, never re-fetch
data/sections/   # extracted target sections as cleaned text
data/ledger/     # per-year structured JSON records
output/          # the three final deliverables
```

## EDGAR access rules

- Resolve ticker → CIK via the SEC company tickers file; do not hardcode CIKs
  in source.
- Filing metadata comes from the submissions JSON API. Prefer it over scraping
  browse pages.
- Set a descriptive User-Agent header on every request. Requests without one
  get blocked.
- Stay under 10 requests/second. Add a deliberate delay; do not parallelize
  aggressively.
- **Cache on first fetch and read from cache thereafter.** Downstream steps get
  re-run constantly; EDGAR should be hit once per document, ever.

## Extraction approach

- **HTML-first.** Parse filing HTML with BeautifulSoup rather than the plain
  text renditions. Table structure and section boundaries survive; in the text
  versions they don't.
- **Section-targeted, not linear.** A 10-K may run 250+ pages; the in-scope
  sections are a fraction of that. Locate section boundaries first, extract the
  span, discard the rest. Never feed a whole filing into a model.
- **Format detection before extraction.** Filing HTML conventions vary by year
  and by filing agent. Detect the document's structural pattern, then dispatch
  to the matching extraction path. Assume the 2021 formatting differs from the
  2025 formatting for the same company.
- **Validate boundaries.** Every extracted section gets a sanity check: does it
  start and end where expected, is the length plausible, does it contain the
  expected anchor phrases. Log failures loudly rather than silently emitting a
  truncated or over-captured section.
- Preserve the accession number and filing date on every extracted artifact.

## Traceability

Every claim in every output must trace back to a specific filing. Carry
`(form type, fiscal year, accession number)` through the ledger and into the
outputs. If something can't be sourced, it doesn't go in — no inference
presented as fact, no filling gaps from general knowledge about the company or
its industry.

Where the filings are ambiguous or contradict each other across years, say so
explicitly rather than silently picking one reading.

## Style

- Scripts over notebooks. Config-driven; no company-specific values in source.
- Fail loudly with useful errors. A silently empty extraction is worse than a
  crash.
- Idempotent re-runs. Running any stage twice should not corrupt or duplicate.
