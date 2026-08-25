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

# 4. Enable the pre-commit checks (once per clone — git does not carry hooks)
git config core.hooksPath .githooks
```

Step 4 is not optional housekeeping. The hook runs
`tools/check_control_bytes.py`, which blocks a commit containing raw control
bytes in a text file — the signature of a regex escape mangled by a shell
heredoc (`\b` arriving as byte 0x08). That has happened three times here, and
each time it silently disabled the check built on the affected pattern while
everything still reported green. Run it over the whole tree at any time with:

```bash
uv run python tools/check_control_bytes.py --all
```

### Running the tests

```bash
uv run python tests/run_all.py               # every test file, with the count gate
uv run python tests/unit/test_<name>.py       # one file
uv run pytest                                # the same gate, via pytest
uv run pytest -k "unit/"                     # only the tests that need no company data
uv run pytest -k "regression/"               # only the tests that read MORN's artifacts
```

The suite is split by what a test reads, not by what it tests:

| | reads | fails when a company's data is absent? |
|---|---|---|
| `tests/unit/` | nothing under `companies/` — inline fixtures and the global `config/` | no, by design |
| `tests/regression/morn/` | MORN's committed ledger, documents, generation records and manifests | **yes, loudly** — see `require_artifacts` |

That second row is the point of the split. Those checks used to sit at the end of
the unit files behind `if artifact.exists():`, so a checkout without the
artifacts ran fewer checks and still printed `0 failed`. A regression test with
nothing to regress against is a failure, not a pass and not a skip.

Unit tests still need *a* company to be scaffolded — several of them import a
stage module, and a stage module resolves its ticker at import time — but they
read none of that company's data.

`run_all.py` compares each file's own `N passed, M failed` line against
`tests/expected_counts.json` and fails if the number moved **in either
direction**. Files are recorded under their path relative to `tests/`, so a file
that moves shows up as one MISSING plus one UNREGISTERED rather than vanishing. Fewer checks than recorded is the failure this exists for: a test
that stops testing still reports green. More checks means new ones were added
without recording them — re-record deliberately with `--update` and commit the
result alongside the tests that caused it.

`uv run pytest` enforces exactly the same three properties per file — exit code,
zero failed checks, and the recorded check *count*. It deliberately does not use
`pytest --collect-only` for counting: that counts test functions, not checks, so
a file falling from 63 checks to 3 would still collect as one test and pass. See
the docstring in `tests/suite_test.py`.

## Running a stage

The pipeline is an installable package (`src/equity_research/`), so stages run as
modules. Every command goes through uv, which activates the environment for you:

```bash
uv run python -m equity_research.<stage>     # e.g. ...equity_research.build_pack
```

## Layout

```
config/            company config, section patterns, 8-K item filters
  company.toml       ticker, CIK, fiscal-year window, rate limits  <- the file you edit
  forms.toml         in-scope forms, 8-K item filter, gap signals
  sections.toml      section boundary regexes + validation rules
src/equity_research/ pipeline modules (an installable package; run with -m)
  _bootstrap.py      ROOT, the Windows cert store, and .env — imported first by every stage
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
