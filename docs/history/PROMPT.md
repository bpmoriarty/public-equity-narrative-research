# Kickoff Prompt

Paste the following into a fresh Claude Code session in the project directory
(with `CLAUDE.md` and `SPEC.md` present).

---

I want to build a reusable pipeline that constructs a five-year narrative
history of a public company from its SEC filings.

Read `CLAUDE.md` and `SPEC.md` first — they define the document scope,
extraction targets, intermediate data model, and the three final outputs.

The target company is **[TICKER]** (CIK: **[CIK, if known — otherwise resolve
it from the ticker]**). Cover fiscal years **[YYYY]–[YYYY]**.

Work in this order, and check in with me at each numbered milestone before
moving on:

1. **Discovery.** Resolve the CIK, pull the filing index, and show me an
   inventory of what's actually available across the five-year window: every
   10-K, DEF 14A, and material 8-K, with dates and accession numbers. Flag any
   gaps (missed years, fiscal-year changes, restatements, S-1/S-4 activity
   suggesting M&A). Do not download full documents yet.

2. **Fetch and cache.** Download the in-scope filings to `data/raw/`,
   organized by year and form type. Respect SEC rate limits and use a proper
   User-Agent. Cache everything — I will re-run downstream steps many times
   and should never re-hit EDGAR for a document already on disk.

3. **Section extraction.** Extract only the target sections defined in
   `SPEC.md` — not whole documents. Write cleaned section text to
   `data/sections/`. Show me one extracted section end-to-end so I can sanity
   check the boundaries before you process the rest.

4. **Year ledger.** Build the structured per-year records defined in `SPEC.md`
   into `data/ledger/`. This is the intermediate layer everything else is
   derived from. Every field must be traceable to a source filing.

5. **Outputs.** Generate the three deliverables described in `SPEC.md` into
   `output/`.

Build this as scripts I can re-run, not as one-off analysis in the session.
Assume I will point this at a different company later without modifying code —
ticker, CIK, and date range are configuration, not hardcoded values.
