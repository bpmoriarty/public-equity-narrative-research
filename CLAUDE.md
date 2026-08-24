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

## Rules that have bitten us

Each of these describes a mistake that was made **more than once** in this
repository, after the reasoning against it had already been written down
somewhere. They are collected here because they were previously scattered across
`.gitignore` comments, `VERIFICATION.md` findings and module docstrings — where
they read as history rather than as instructions.

Where a rule has a mechanical enforcer, it is named. Prefer trusting the
enforcer over remembering the rule; that is the entire point of building it.

**1. Model output is never "regenerable".** A re-run buys *a* valid answer, not
*the* answer the committed documents cite. Anything that cost tokens —
`data/ledger/facts/`, `data/pack/gen-*.json`, `output/*.md` — is committed,
whatever else in the same directory is derived and ignored. Applied wrongly
three times, each time to a different artifact, twice *after* the explanation
had been written into `.gitignore` directly above.
*Enforced by `tests/test_repo_hygiene.py`.*

**2. Never edit source through the shell — not a heredoc, not string
replacement, not any read-modify-write in PowerShell or bash.** Two distinct
corruptions, both silent, both seen here.

*Backslash escapes do not survive a heredoc*: `\b` has arrived on disk as byte
0x08 and `\1` as 0x01, three times. The file still imports, still lints, still
looks right in an editor — and the regex built on it silently matches nothing,
so the check it powers reports green forever.

*Encodings do not survive a round trip*: PowerShell 5.1's `Get-Content` reads
cp1252, so reading a UTF-8 file and writing it back turns every non-ASCII
character into two or three Latin-1 ones. Done to five test files in Phase 4.6,
producing 7–34 corrupted sequences each. The control-byte scan reported clean —
mojibake is not a control byte — and what broke was three fixtures containing an
ellipsis and curly quotes, which is to say the ability of those tests to detect a
misquotation.

Use Write/Edit. If a change really needs scripting, script it in Python with
`encoding="utf-8"` stated on both the read and the write.
*Enforced by `tools/check_control_bytes.py` via `.githooks/pre-commit`, with an
advisory `PreToolUse` hook in `.claude/settings.json`; the encoding half is
enforced by the mojibake check in `tests/test_repo_hygiene.py`.*

**3. Run every new hard check against something that fails it, before trusting
it.** A check that has only ever seen correct input is untested — you have
confirmed it does not fire, not that it can. Roughly eighteen bugs in this
project were in checkers rather than in what they checked. New checks that could
plausibly misfire ship as `review` for one commit and are promoted to `hard`
after their output has been read once.

**4. Writers merge, never clobber. Run twice, diff nothing.** Two stages have
overwritten a manifest another stage owned. If a stage writes a shared file, it
reads the existing content and merges; if it writes its own, running it twice
produces byte-identical output. Any run-to-run difference — a timestamp inside a
payload, unsorted keys — is a bug, not cosmetic: `pack.json` deliberately holds
no timestamp because prompt caching only hits on a byte-identical prefix.

**5. Counts must reconcile across every stage boundary.** A stage reporting
"32/32 succeeded" is describing what it attempted, not what arrived. Eleven
filings once vanished between stages while both ends reported complete success.
State the number in and the number out, and account for the difference —
explicitly dropped, explicitly empty — or fail. A silent drop is
indistinguishable from a clean run.
