# Public Equity Research — Five-Year Narrative History

Builds a five-year narrative history of a public company from its SEC filings.
Input: a ticker and a fiscal-year range. Output: three Markdown documents plus
the structured ledger they derive from.

Narrative and governance extraction — **not** financial statement extraction.

## Setup from a clean checkout

```bash
# 1. Build the environment (creates .venv from uv.lock — do not use pip)
uv sync

# 2. Create your secrets file, then fill in EDGAR_IDENTITY and ANTHROPIC_API_KEY
cp .env.example .env          # Git Bash
# Copy-Item .env.example .env # PowerShell

# 3. Point the pipeline at a company
#    Edit config/company.toml: set `ticker` and the [window] fiscal years.
```

Every command runs through uv, which activates the environment for you:

```bash
uv run python src/<stage>.py
```

## Layout

```
config/            company config, section patterns, 8-K item filters
  company.toml       ticker, CIK, fiscal-year window, rate limits  <- the file you edit
  forms.toml         in-scope forms, 8-K item filter, gap signals
  sections.toml      section boundary regexes + validation rules
src/                 pipeline modules
data/raw/            cached filings by year/form — never delete, never re-fetch
data/sections/       extracted target sections as cleaned text
data/ledger/         per-year structured JSON records
output/              the three deliverables
```

`data/` and `output/` subdirectories are created by the stage that writes them
(`mkdir(parents=True, exist_ok=True)`), so the pipeline rebuilds from nothing.

## Read these before working on it

| File | Why |
|---|---|
| `CLAUDE.md` | The rules: EDGAR access, extraction approach, traceability. **Read first** |
| `SPEC.md` | Scope, extraction targets, ledger schema, output specs, milestones |
| `PROJECT_STATUS.md` | Where the project currently stands and what's next |
| `DATA.md` | Provenance and the source's known limitations |
| `PROMPT.md` | The kickoff prompt that drives the build, milestone by milestone |

## The two rules most easily broken

1. **EDGAR gets hit once per document, ever.** Cache on first fetch, read from
   cache thereafter. Downstream stages get re-run constantly.
2. **Every claim traces to `(form, fiscal year, accession number)`.** If it
   can't be sourced, it doesn't go in the output.
