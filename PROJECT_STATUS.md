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

---

## Current Status

**Phase:** Planning

**Last Session:** 2026-08-04

**Overall Health:** 🟢 Working — environment and scaffolding only; no pipeline code yet

### What's Working

- `uv` environment builds clean: Python 3.13.14, all 8 declared dependencies
  install and import (`uv sync` → verified)
- Repository structure created per CLAUDE.md: `config/ src/ data/{raw,sections,ledger}/ output/`
- Three config files written and validated — all TOML parses, all 20 regex
  patterns compile, all 8 section keys have matching validation bands
- Provenance recorded in `DATA.md` before any data was pulled

### What's Broken or Incomplete

- **No pipeline code exists yet.** `src/` is empty by design — the build is
  gated on the milestones in `PROMPT.md` and hasn't been started
- **No company selected.** `config/company.toml` has `ticker = "REPLACE_ME"`
  and an empty `cik`
- **`.env` not created.** Copy `.env.example` → `.env` and fill in
  `EDGAR_IDENTITY` and `ANTHROPIC_API_KEY`. Nothing can hit EDGAR until then
- Section patterns in `config/sections.toml` are informed but **unvalidated
  against a real filing** — they will need adjustment on first contact,
  especially the DEF 14A ones (proxies have no standardized item numbering)

---

## What We're Doing Now

Nothing in flight. The environment is ready and the kickoff prompt in
`PROMPT.md` has deliberately **not** been run.

To start: pick a ticker and fiscal-year window, put them in
`config/company.toml`, create `.env`, then run `PROMPT.md` milestone 1
(discovery) — which resolves the CIK and inventories available filings without
downloading any documents.

---

## Recent Decisions

| Date | Decision | Why |
|------|----------|-----|
| 2026-08-04 | Python 3.13, not 3.14/3.15 | Matches `sec-extraction-v3`; 3.13 has `tomllib` in stdlib and full wheel coverage for every dependency |
| 2026-08-04 | Version floors (`>=`) in `pyproject.toml`, not exact pins (`==`) | Project is being built now, not reproducing a validated run. Tighten `edgartools`/`beautifulsoup4`/`lxml` to `==` once the pipeline is hand-checked end-to-end, so a parser change can't silently move section boundaries |
| 2026-08-04 | `tomllib` (stdlib) for config, no TOML package | Only reading config, never writing it. One less dependency |
| 2026-08-04 | `rapidfuzz` for risk-factor diffing | SPEC.md §2 requires finding *materially reworded* risk factors year over year — needs fuzzy matching, which `difflib` does poorly at this scale |
| 2026-08-04 | Own cache in `data/raw/`, not `EDGAR_LOCAL_DATA_DIR` | Keeps the cache visible in the project layout instead of hidden in a home directory, and matches the structure CLAUDE.md specifies |
| 2026-08-04 | Risk factors extracted as a **list** of individual factors, not one text blob | Diffing needs per-factor granularity; a single blob can only be summarized, not diffed |
| 2026-08-04 | `data/raw/` gitignored despite "never delete" | It is a large local copy of public EDGAR documents. Precious locally, wrong to commit. Noted in `DATA.md` |
| 2026-08-04 | Wide validation bands in `config/sections.toml` | They exist to catch catastrophic failure (TOC match, runaway capture), not stylistic variation. Tighten once the real length distribution is known |

---

## Next Steps

1. [ ] Choose the target company — ticker and fiscal-year window → `config/company.toml`
2. [ ] Create `.env` from `.env.example` (`EDGAR_IDENTITY`, `ANTHROPIC_API_KEY`)
3. [ ] **Milestone 1 — Discovery.** Resolve CIK, pull filing index, inventory
       every 10-K / DEF 14A / material 8-K in the window with dates and
       accession numbers. Flag gaps: missed years, fiscal-year changes,
       restatements, S-1/S-4 activity. No document downloads. *Check in here.*
4. [ ] **Milestone 2 — Fetch and cache** to `data/raw/`, by year and form
5. [ ] **Milestone 3 — Section extraction** to `data/sections/`. Review one
       section end-to-end before processing the rest. *Check in here.*
6. [ ] **Milestone 4 — Year ledger** to `data/ledger/`
7. [ ] **Milestone 5 — Three outputs** to `output/`
8. [ ] Run `preflight`, then `verification-suite` before treating any output as
       shareable

---

## Important Files

| File | What It Does |
|------|--------------|
| `CLAUDE.md` | Project rules — EDGAR access, extraction approach, traceability. Read first |
| `SPEC.md` | Document scope, extraction targets, ledger schema, output specs, milestones |
| `PROMPT.md` | The kickoff prompt. **Not yet run** |
| `DATA.md` | Data provenance and the source's known limitations |
| `config/company.toml` | The only file to edit to point at a different company — ticker, CIK, window, rate limits |
| `config/forms.toml` | Which forms are in scope; the 8-K item filter; gap-analysis signals |
| `config/sections.toml` | Section start/end regex patterns, anchor phrases, boundary validation rules |
| `pyproject.toml` | Dependencies, each with a comment explaining why it's there |
| `.env.example` | Template for secrets. Copy to `.env` |
| `src/` | Pipeline modules — **empty, not built yet** |

---

## Things Claude Should Remember

- **I'm learning to code.** Explain in plain language, comment the code, warn me
  before anything risky, teach me the concept when it would help
- **Check in at each milestone** in `PROMPT.md` before moving on — don't run the
  whole pipeline in one go
- **Never re-hit EDGAR for a document already in `data/raw/`.** Cache on first
  fetch, read from cache forever after
- **Every claim in every output traces to `(form, fiscal year, accession
  number)`.** If it can't be sourced, it doesn't go in — no inference presented
  as fact, no filling gaps from general knowledge about the company
- **A silently empty or over-captured extraction is worse than a crash.** Fail
  loudly with useful errors
- Config-driven, scripts over notebooks, no company-specific values in `src/`
- Where filings are ambiguous or contradict each other across years, say so
  explicitly rather than picking a reading

---

## Session Log

### 2026-08-04

- Set up the subproject from scratch: folder structure, `uv` environment,
  dependencies, config scaffolding, provenance doc
- Verified the environment: Python 3.13.14, all dependencies import cleanly
- Wrote and validated the three config files — TOML parses, regexes compile,
  section keys and validation bands agree
- Deliberately did **not** run `PROMPT.md` — no company chosen, no EDGAR calls made
- Next: choose a ticker and fiscal-year window, create `.env`, then run
  milestone 1 (discovery)
