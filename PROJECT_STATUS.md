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

**Overall Health:** 🟢 Working — milestones 1 and 2 complete and verified

### What's Working

- **Environment.** Python 3.13.14, 8 declared dependencies, `uv sync` rebuilds
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
- **Coverage.** 10-K and DEF 14A complete for all five fiscal years

### What's Broken or Incomplete

- **No section extraction yet.** Milestone 3 not started. `data/sections/` empty
- **FY2022 shareholder letter is a PDF** — `tm2310844d1_ars.pdf`. HTML-first
  parsing cannot read it. Needs a decision: add a PDF text library, or handle
  manually, or accept the gap. FY2023–FY2025 are HTML
- **FY2021 has no shareholder letter at all.** Verified absent, not a lookup
  failure: no ARS filed, and no EX-13 in any of the five 10-Ks
- **Section patterns are unvalidated against real filings.** Written from
  knowledge of 10-K/proxy conventions, never yet run against a MORN document.
  The DEF 14A patterns are the likeliest to need work — proxies have no
  standardized item numbering
- **75 triage 8-Ks are fetched but unjudged.** Items 7.01/8.01; content decides
  whether each is a strategic announcement or a routine release

---

## What We're Doing Now

Milestones 1 and 2 are done and verified. Next is **milestone 3, section
extraction** — the first stage where the config's regex patterns meet real
filing HTML, and the first place `config/sections.toml` will need real revision.

Per `PROMPT.md`, one extracted section gets reviewed end-to-end before the rest
are processed.

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
| 2026-08-04 | Force UTF-8 on stdout in every script | Windows console cp1252 cannot encode characters common in filings; printing one killed a completed run |

---

## Next Steps

1. [x] Choose target company → `config/company.toml`
2. [x] Create `.env`, verify both credentials
3. [x] **Milestone 1 — Discovery.** Complete, committed `ba24893`
4. [x] **Milestone 2 — Fetch and cache.** 201 docs, 127 filings, verified
5. [ ] **Decide on the FY2022 PDF letter** — add a PDF text library, handle
       manually, or accept and document the gap
6. [ ] **Milestone 3 — Section extraction** to `data/sections/`. Validate the
       `config/sections.toml` patterns against real MORN HTML; expect the
       DEF 14A patterns to need revision. *Review one section end-to-end before
       processing the rest.*
7. [ ] Triage the 75 unjudged 7.01/8.01 8-Ks on content
8. [ ] **Milestone 4 — Year ledger** to `data/ledger/`
9. [ ] **Milestone 5 — Three outputs** to `output/`
10. [ ] Run `preflight`, then `verification-suite` before treating any output as
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
- Next: decide how to handle the FY2022 PDF letter, then milestone 3 (section
  extraction) — where `config/sections.toml` meets real filing HTML for the
  first time
