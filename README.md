# Public Equity Research — Five-Year Narrative History

Builds a five-year narrative history of a public company from its SEC filings.
Input: a ticker and a fiscal-year range. Output: three Markdown documents plus
the structured ledger they derive from, with every claim traceable to a filing.

Narrative and governance extraction — **not** financial statement extraction.

**You do not need an API key.** By default the model calls run on a Claude seat
through Claude Code, which is the path almost everyone here has. See
[Model calls](#model-calls).

## Setup from a clean checkout

```bash
# 1. Build the environment (creates .venv from uv.lock — do not use pip)
uv sync
# If that fails with a hardlink error, use:  uv sync --link-mode=copy   (see below)

# 2. Create your secrets file, then fill in EDGAR_IDENTITY
cp .env.example .env          # Git Bash
# Copy-Item .env.example .env # PowerShell

# 3. Enable the pre-commit checks (once per clone — git does not carry hooks)
git config core.hooksPath .githooks

# 4. Scaffold the company you want to research
uv run pipeline init TSLA
```

### If `uv sync` fails on a hardlink error

Found by doing exactly this, from a fresh clone, on a Windows machine with
OneDrive present:

```
error: Failed to install: pytest-9.1.1-py3-none-any.whl (pytest==9.1.1)
  Caused by: failed to hardlink file from <.venv> to <uv cache>:
  The cloud operation cannot be performed on a file with incompatible
  hardlinks. (os error 396)
```

`uv` populates `.venv` by hardlinking out of its own cache, and that fails when
either end sits on a cloud-backed filesystem. Use the mode `uv` itself suggests:

```bash
uv sync --link-mode=copy
```

or set it once, so every later `uv run` and `uv add` behaves the same way:

```powershell
$env:UV_LINK_MODE = "copy"        # this session
# or persist it:
[Environment]::SetEnvironmentVariable("UV_LINK_MODE", "copy", "User")
```

It costs disk (real copies rather than links) and nothing else. Note this can
happen **even with the checkout outside OneDrive**, because the *cache* end of
the link is under your user profile — so it is worth knowing about before you
conclude something is wrong with the project.

**`EDGAR_IDENTITY` is the only thing that belongs in `.env`** — the SEC blocks
requests without a descriptive User-Agent.

**Do not put an API key in `.env`.** Not a style rule: `_bootstrap` loads `.env`
on every import, so a key there is *ambient* — present in every run whether or
not that run wants it. The Claude Code CLI treats `ANTHROPIC_API_KEY` as an
authentication method, so on the default `claude_code` backend the calls would
bill the key while every record still said `backend: claude_code` and every
printed dollar was still labelled "notional". That is a false claim and a real
charge, and it was caught here on 2026-09-02 one commit before the first
large extraction run.

The `api` backend is still fully supported — it is **opt-in**. Put the key in
`.env.api`, which nothing loads automatically, and supply it for one invocation
only; `.env.example` carries the exact recipe. Two guards back this up, and
neither replaces keeping the key out of `.env`: `seat_only_env()` strips every
API credential from the CLI's environment, and every record carries
`billing: "seat" | "api_key"` so "these dollars are notional" is a fact on the
record rather than an inference from the config.

`pipeline init` copies `companies/_template/` to `companies/TSLA/` and prints
what to edit — the ticker and the fiscal-year window. **Leave `cik` and
`resolved_name` empty.** They are tripwires, not inputs: discovery resolves the
CIK from the ticker and stops if a value there disagrees with it. A CIK typed
from memory returns a different company's filings and every stage then runs
perfectly on the wrong data.

Step 3 is not optional housekeeping. The hook runs
`tools/check_control_bytes.py`, which blocks a commit containing raw control
bytes in a text file — the signature of a regex escape mangled by a shell
heredoc (`\b` arriving as byte 0x08). That has happened three times here, and
each time it silently disabled the check built on the affected pattern while
everything still reported green. Run it over the whole tree at any time with:

```bash
uv run python tools/check_control_bytes.py --all
```

### Where to put the checkout

Prefer a path **outside** OneDrive or any other syncing folder. The pipeline
writes tens of thousands of cached files under `companies/<TICKER>/data/raw/`,
and a sync client will either fight the writes or quietly upload 40 MB per
company. Keep the nesting shallow too: Windows' 260-character path limit is not
far off once accession numbers are in the path.

**One analyst per checkout.** Two people working on two companies in one
checkout is unsupported — take separate clones.

## Running the pipeline

```bash
uv run pipeline MORN            # all thirteen stages, in order
uv run pipeline MORN --yes      # ...without stopping to confirm spending
uv run pipeline status MORN     # what is on disk, per stage
uv run pipeline estimate MORN   # what the two spending stages would cost
uv run pipeline stages          # the registry, and which stages cost money
uv run pipeline init TSLA       # scaffold a new company
```

Two of the thirteen stages make model calls. Before either runs, `pipeline` asks
it whether it has any work, shows what that work would cost, and waits for a
yes. An unanswerable prompt — a piped or closed stdin — counts as **no**; it is
never read as consent.

**`--yes` approves *both* spending stages, not the next one.** To approve
extraction and still be asked about generation, scope it:

```bash
uv run pipeline run MSFT --only extract_facts --yes   # just this stage
uv run pipeline run MSFT --from build_ledger          # resumes; stops at generation
```

The stages still run only if they have work, so `--yes` on a finished company
spends nothing.

Everything else is deterministic and free, and every stage no-ops when its output
is already current, so re-running the whole pipeline over a finished company
costs nothing and takes about forty seconds.

A single stage can still be run on its own:

```bash
uv run python -m equity_research.<stage> --ticker MORN
```

## Model calls

Every model call goes through one seam (`src/equity_research/model_client.py`)
with two interchangeable backends, selected in `config/llm.toml`:

| Backend | Needs | Notes |
|---|---|---|
| `claude_code` (default) | a Claude seat | Runs the Claude Code CLI headlessly. No API key. |
| `api` | `ANTHROPIC_API_KEY` | The Anthropic SDK. Cheaper for extraction; see `config/llm.toml`. |

**Finding the CLI is the thing most likely to break on a new machine.** Most
people use Claude Code through the VS Code extension and never install the CLI —
but the extension *ships* it, at a path carrying the extension's version number,
which moves on every update. Resolution order is: the `binary_path` setting, then
`claude` on `PATH`, then the newest binary found inside an installed extension.
If a run cannot find it, set `binary_path` in `config/llm.toml`.

On a seat the dollar figures the pipeline prints are **notional** — what the API
would have charged. They are still the right number to compare against, and they
are what `estimate` reports.

Which model answers which extraction task is configurable per task in
`companies/<TICKER>/company.toml` under `[extraction.models]`. It ships empty:
every task uses one model unless you say otherwise. Read the comments there
before changing it — particularly the note on where a comparison run writes.

## Layout

```
config/                GLOBAL defaults, company-neutral
  forms.toml             in-scope forms, 8-K item filter, gap signals
  sections.toml          section boundary regexes + validation rules
  outputs.toml           pack budget, timeline rules, output constraint gates
  llm.toml               which backend model calls go through
companies/
  _template/             copied by `pipeline init`
  <TICKER>/
    company.toml         ticker, fiscal window, model settings  <- the file you edit
    corrections.toml     hand-verified corrections; optional
    overrides/           optional per-company deltas to the global config
    data/raw/            cached filings by year/form — never delete, never re-fetch
    data/discovery/      the filing inventory and the coverage report
    data/sections/       extracted target sections as cleaned text
    data/triage/         the judgment on every conditional 7.01/8.01 8-K
    data/ledger/         per-year structured JSON records, and the facts cache
    data/pack/           the citable pack the output writers read
    data/_meta/          the run log — gitignored, and where a stage's clock goes
    output/              the three deliverables
src/equity_research/     pipeline modules (an installable package; run with -m)
  _bootstrap.py            ROOT, the Windows cert store, and .env — imported first
  paths.py                 every path, resolved per company
tests/unit/              reads no company data; passes in a bare checkout
tests/regression/morn/   reads MORN's committed artifacts; fails loudly without them
```

A company's whole world is one folder: its config, its corrections, its cached
filings, its deliverables. `config/` holds only what is true for every company.

Data directories are created by the stage that writes them, so the pipeline
rebuilds from nothing.

**`raw/`, `sections/` and `_meta/` are gitignored; everything else is committed.**
That split is not about size. Anything that cost model tokens — the facts cache,
`data/pack/gen-*.json`, `output/*.md` — is irreplaceable, because a re-run buys
*a* valid answer and not *the* answer the committed documents cite. Cached
filings and extracted sections are free to rebuild from EDGAR, so they are not.

## Running the tests

```bash
uv run python tests/run_all.py                  # every test file, with the count gate
uv run python tests/unit/test_<name>.py         # one file
uv run pytest                                   # the same gate, via pytest
uv run pytest -k "unit/"                        # only the tests that need no data
```

`run_all.py` compares each file's own `N passed, M failed` line against
`tests/expected_counts.json` and fails if the number moved **in either
direction**. Fewer checks than recorded is the failure this exists for: a test
that stops testing still reports green. More checks means new ones were added
without recording them — re-record deliberately with `--update` and commit the
result alongside the tests that caused it.

`uv run pytest` enforces exactly the same three properties per file — exit code,
zero failed checks, and the recorded check *count*. It deliberately does not use
`pytest --collect-only` for counting: that counts test functions, not checks, so
a file falling from eighty checks to three would still collect as one test and
pass — which is not hypothetical, it is VERIFICATION.md D7. See
the docstring in `tests/suite_test.py`. Note that `pytest tests/unit` collects
nothing — `suite_test.py` is the only pytest-visible file — so select with
`-k "unit/"` instead.

**The split is by what a test reads, not by what it tests.** Everything in
`tests/unit/` runs against inline fixtures and passes in a checkout with no
company data at all. Everything in `tests/regression/morn/` reads MORN's
committed artifacts and **exits non-zero** if they are absent, naming what is
missing and whether it can be rebuilt for free. Neither ever skips: a regression
test with nothing to regress against is a failure, not a pass.

One file is slow on purpose. `tests/regression/morn/test_reruns_change_nothing.py`
re-runs the five deterministic stages and compares their output to the committed
bytes, which takes about 28 seconds and is most of the suite's runtime. It is the
only automated proof that a re-run leaves the tree clean.

## Known limitations, and the one that needs a manual step

**The final fiscal year's shareholder vote is not fetched automatically.** Check
this on every new company — it is silent, and the run reports success.

`votes` reads the 8-K Item 5.07 that reports the vote taken at the meeting
*following* a fiscal year's proxy. That filing is dated months after the year it
reports on, so for the **last** year in a window it carries the *next* fiscal
year's label and `in_window: false` — and `fetch` builds its work list from
in-window filings only. The section never exists, and `extract_facts` reports
`FY<last> votes: no source`, which reads like an absent disclosure rather than a
filing nobody asked for.

Fix it before the extraction spend, because the facts cache is keyed per
`(year, task, filing)` and adding it afterwards means a second paid call:

```bash
# The accession is already in the inventory discovery wrote — find the 5.07
# filed just after the last year's DEF 14A:
#   companies/MSFT/data/discovery/inventory.json  ->  "5.07" in items
uv run python -m equity_research.fetch --ticker MSFT --accession 0001193125-25-311196
uv run python -m equity_research.extract_sections --ticker MSFT
```

`--accession` is repeatable and adds exactly the filings named, nothing else. Do
**not** widen the window instead: an extra year sweeps in that year's 10-Qs, Form
4s and earnings 8-Ks and quietly changes what every coverage claim means.

Counts should move by exactly one filing, and `no source` should drop by one.

Two more worth knowing when reading the output:

- **Proxy director biographies are captured with unverified boundaries.** For
  some filing agents the span reaches the proxy voting card, so `board` facts can
  name a director with no tenure, committee or role. They carry
  `confidence: low` throughout for this reason, and the pack says so in its
  `field_notes`.
- **A shareholder letter exists only where the company filed an ARS.** Where it
  did not, those years have no letter and the deliverables are required to name
  the gap rather than pass over it.

## Read these before working on it

| File | Why |
|---|---|
| `CLAUDE.md` | The rules: EDGAR access, extraction approach, traceability, and the five doctrines whose violation recurred. **Read first** |
| `SPEC.md` | Scope, extraction targets, ledger schema, output specs, milestones |
| `PROJECT_STATUS.md` | Where the project stands, what is next, and the Session Log |
| `DATA.md` | Provenance and the source's known limitations |
| `VERIFICATION.md` | The verification suite's findings and how each was remediated |
| `PROMPT.md` | The kickoff prompt that drives the build, milestone by milestone |

## The two rules most easily broken

1. **EDGAR gets hit once per document, ever.** Cache on first fetch, read from
   cache thereafter. Downstream stages get re-run constantly.
2. **Every claim traces to `(form, fiscal year, accession number)`.** If it
   can't be sourced, it doesn't go in the output.
