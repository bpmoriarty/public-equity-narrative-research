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

**Last Session:** 2026-08-04

**Overall Health:** 🟢 Working — milestones 1–3 complete; two proxy sections flagged low-confidence

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
- **Coverage.** 10-K and DEF 14A complete for all five fiscal years

### What's Broken or Incomplete

- **Two proxy sections have unverified boundaries.** `DEF14A_director_bios`
  (FY2025 known wrong — starts at the front-of-proxy voting summary, not the
  bios) and `DEF14A_proposals_and_votes` (FY2022 correct at 6,883 chars; the
  other four years at 21k–25k likely over-capture). Handled by confidence
  marking, not fixed — see Recent Decisions
- **FY2021 has no shareholder letter at all.** Verified absent, not a lookup
  failure: no ARS filed, and no EX-13 in any of the five 10-Ks
- **75 triage 8-Ks are extracted but unjudged on content.** Items 7.01/8.01;
  the text is in `data/sections/`, but nothing has yet decided which are
  strategic announcements and which are routine releases

---

## What We're Doing Now

Milestones 1–3 are done. Next is **milestone 4, the year ledger** — the
structured per-year records in `data/ledger/` that every output derives from.

Two things milestone 4 must carry, decided 2026-08-04:
1. **Every field gets a `confidence` marker** (`high` / `low`) plus its reason.
   Anything sourced from `DEF14A_director_bios` or `DEF14A_proposals_and_votes`
   is `low`, because those boundaries are unverified. SPEC.md §3 permits schema
   additions provided every field stays sourced, and this keeps the weakness
   recorded rather than hidden.
2. **Vote outcomes come from 8-K Item 5.07, not the proxy.** A DEF 14A solicits a
   vote; it does not report the result. The 5.07 filings are extracted whole, so
   they need no boundary detection and carry no boundary risk.

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
7. [ ] **Milestone 4 — Year ledger** to `data/ledger/`, with per-field
       `confidence` and vote outcomes taken from 8-K 5.07
8. [ ] Triage the 75 7.01/8.01 8-Ks on content (text already extracted)
9. [ ] **Milestone 5 — Three outputs** to `output/`
10. [ ] Optional, if the board narrative proves load-bearing: per-year verified
        boundaries for `DEF14A_director_bios` and `DEF14A_proposals_and_votes`
11. [ ] Run `preflight`, then `verification-suite` before treating any output as
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
