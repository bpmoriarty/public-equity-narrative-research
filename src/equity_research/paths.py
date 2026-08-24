"""Every filesystem path the pipeline uses, resolved per company.

WHY THIS MODULE EXISTS
----------------------
Before Phase 2 each of the 15 stage modules built its own paths out of `ROOT`,
spelled out join by join — a ledger directory was `ROOT`, then "data", then
"ledger", and an output directory was `ROOT` then "output".

That was 49 separate joins, all assuming exactly one company lived in the
repository. Supporting a second company means every one of those joins has to
grow a ticker segment, and 49 hand-edited joins is 49 chances to miss one — the
missed one does not crash, it silently reads or writes the wrong directory.

So the joins live here, once. A stage asks for `P.ledger` and never spells out
the segments itself, so the question "where does MORN's ledger live?" has
exactly one answer in the codebase.

`tests/test_repo_hygiene.py` enforces this with a path-literal lint: a `"data/`
or `"output/` string literal anywhere in `src/equity_research/` outside this
file fails the suite. That is the mechanical enforcer; prefer trusting it over
remembering the rule.

THE MANIFEST CONTRACT — why the MORN move did not rewrite a single manifest
--------------------------------------------------------------------------
`fetch-manifest.json`, `sections-manifest.json`, `inventory.json` and
`triage-8k.json` store paths as ROOT-relative forward-slash strings:

    "data/raw/FY2021/10-K/0001289419-22-000005/morn-20211231.htm"

Verified at migration time: 893 such strings across the four manifests, and
zero absolute paths. Every one of those relative paths still exists, unchanged,
under `companies/MORN/`. So the move needed no manifest edits at all — only the
*base* the relative path is joined onto changed:

    before:   ROOT / rec["path"]
    after:    P.resolve(rec["path"])

That is what lets `pack.json` keep the same sha256 across the migration, which
in turn keeps the hash stamped on every committed deliverable honest. If the
manifests had stored absolute paths, or if `resolve()` had been written to
rewrite them, that verification would have been impossible.

TICKER RESOLUTION, AND WHY IT PEEKS AT sys.argv
-----------------------------------------------
Stages declare module-level path constants (`LEDGER_DIR = P.ledger`), which
Python evaluates at *import* time — before `main()` runs and long before
argparse has seen `--ticker`. A `--ticker` parsed the normal way would arrive
too late to affect any of them.

Rather than convert 49 constants into lazily-evaluated function calls, this
module scans `sys.argv` for `--ticker` itself, at import time. Each stage still
declares the flag in its own argparse so `--help` documents it and a bad value
is caught — but the value that shapes the paths is read here, first.

Precedence, highest to lowest:

  1. `--ticker MORN` / `--ticker=MORN` on the command line
  2. `EQR_TICKER` in the environment (how the Phase 4 orchestrator will pass it
     to each stage subprocess)
  3. the single company under `companies/`, when there is exactly one

Rule 3 is what keeps every existing standalone invocation and all eight test
files working untouched while MORN is the only company. It is deliberately not
a "pick the first one" fallback: the moment a second company folder appears it
becomes ambiguous, and an ambiguous ticker raises rather than guessing. Reading
the wrong company's filings is the failure mode that produces a perfectly
clean-looking run over entirely wrong data.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from equity_research._bootstrap import ROOT

# Company folders live here. `_template` (added in Phase 4) and any other
# underscore-prefixed directory is scaffolding, not a company.
COMPANIES_DIR = ROOT / "companies"

# Prefixes a manifest-relative path is allowed to start with. Anything else is a
# bug in whatever wrote the manifest, and `resolve()` raises rather than quietly
# producing a path that points nowhere.
_RELATIVE_PREFIXES = ("data/", "output/")


# ---------------------------------------------------------------------------
# Ticker resolution
# ---------------------------------------------------------------------------

def _ticker_from_argv(argv: list[str] | None = None) -> str | None:
    """Find `--ticker VALUE` or `--ticker=VALUE` in argv. See module docstring.

    Kept separate from `resolve_ticker` so it can be unit-tested against a
    synthetic argv without touching the real process arguments.
    """
    args = sys.argv if argv is None else argv
    for i, a in enumerate(args):
        if a == "--ticker" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--ticker="):
            return a.split("=", 1)[1]
    return None


def known_tickers() -> list[str]:
    """Company folders present, excluding underscore-prefixed scaffolding."""
    if not COMPANIES_DIR.is_dir():
        return []
    return sorted(p.name for p in COMPANIES_DIR.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def resolve_ticker(explicit: str | None = None) -> str:
    """The company this process is operating on. Fails loudly when ambiguous."""
    candidate = explicit or _ticker_from_argv() or os.getenv("EQR_TICKER")
    if candidate and candidate.strip():
        return candidate.strip().upper()

    # No explicit ticker anywhere — fall back to the single company, if there is
    # exactly one. Both the zero case and the many case are hard errors.
    found = known_tickers()
    if len(found) == 1:
        return found[0]

    if not found:
        raise SystemExit(
            f"FATAL: no company folders found under {COMPANIES_DIR}.\n"
            "Each company lives in companies/<TICKER>/ with its own company.toml,\n"
            "corrections.toml, data/ and output/."
        )
    raise SystemExit(
        f"FATAL: {len(found)} companies exist ({', '.join(found)}) and no ticker "
        "was given,\nso which one to operate on is ambiguous.\n"
        "Pass --ticker <TICKER> or set EQR_TICKER in the environment.\n"
        "This is a hard error on purpose: silently picking one would run every\n"
        "stage perfectly against the wrong company's filings."
    )


# ---------------------------------------------------------------------------
# The paths themselves
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompanyPaths:
    """Every path for one company. Frozen: paths are facts, not state.

    Directories and named files are properties rather than fields so there is
    no constructor to keep in sync — adding a path is one property, and it
    cannot disagree with the others about where the company folder is.
    """

    ticker: str
    root: Path = ROOT

    # -- the company folder and its two human-authored config files ----------

    @property
    def company(self) -> Path:
        return self.root / "companies" / self.ticker

    @property
    def company_toml(self) -> Path:
        return self.company / "company.toml"

    @property
    def corrections_toml(self) -> Path:
        """Optional. A company with no corrections simply has no file here."""
        return self.company / "corrections.toml"

    @property
    def overrides_dir(self) -> Path:
        """Optional per-company config deltas; absent means global defaults."""
        return self.company / "overrides"

    # -- global, company-neutral config --------------------------------------

    @property
    def config_dir(self) -> Path:
        """forms.toml / sections.toml / outputs.toml — shared by all companies."""
        return self.root / "config"

    # -- data directories ----------------------------------------------------

    @property
    def data(self) -> Path:
        return self.company / "data"

    @property
    def raw(self) -> Path:
        """Cached EDGAR documents. Never delete, never re-fetch (CLAUDE.md)."""
        return self.data / "raw"

    @property
    def meta(self) -> Path:
        return self.raw / "_meta"

    @property
    def sections(self) -> Path:
        return self.data / "sections"

    @property
    def discovery(self) -> Path:
        return self.data / "discovery"

    @property
    def triage(self) -> Path:
        return self.data / "triage"

    @property
    def triage_text(self) -> Path:
        return self.triage / "text"

    @property
    def ledger(self) -> Path:
        return self.data / "ledger"

    @property
    def facts(self) -> Path:
        """Model output. Committed, and the one artifact no re-run reproduces."""
        return self.ledger / "facts"

    @property
    def pack(self) -> Path:
        return self.data / "pack"

    # -- output --------------------------------------------------------------

    @property
    def output(self) -> Path:
        return self.company / "output"

    @property
    def pdf(self) -> Path:
        return self.output / "pdf"

    # -- named files the stages hand to each other ---------------------------

    @property
    def inventory(self) -> Path:
        return self.discovery / "inventory.json"

    @property
    def fetch_manifest(self) -> Path:
        return self.raw / "fetch-manifest.json"

    @property
    def sections_manifest(self) -> Path:
        return self.sections / "sections-manifest.json"

    @property
    def triage_json(self) -> Path:
        return self.triage / "triage-8k.json"

    @property
    def fetch_log(self) -> Path:
        return self.meta / "fetch-log.json"

    # The four below were each spelled at their producing and consuming sites
    # rather than here — `LEDGER_DIR / "risk-deltas.json"` in build_ledger and
    # `OUT_DIR / "risk-deltas.json"` in risk_diff, for the same file. That is two
    # answers to "where does this live", which is the thing this module exists to
    # prevent, and it only stayed harmless because both spellings happened to
    # agree. Added when `pipeline status` needed to name them: the path-literal
    # lint in tests/test_repo_hygiene.py forbids cli.py from spelling them
    # itself, which is what surfaced the gap.

    @property
    def risk_deltas(self) -> Path:
        return self.ledger / "risk-deltas.json"

    @property
    def timeline_events(self) -> Path:
        return self.pack / "timeline-events.json"

    @property
    def timeline_md(self) -> Path:
        return self.output / "timeline.md"

    @property
    def verify_report(self) -> Path:
        return self.pack / "verify-report.md"

    # -- the manifest contract ----------------------------------------------

    def resolve(self, rel: str | Path) -> Path:
        """Re-root a manifest-relative path onto this company's folder.

        The manifests store `data/raw/FY2021/.../doc.htm`. This turns that into
        `<repo>/companies/<TICKER>/data/raw/FY2021/.../doc.htm` without touching
        the stored string — see THE MANIFEST CONTRACT in the module docstring.

        Raises on anything that is not a `data/` or `output/` relative path,
        including absolute paths: a manifest holding something else is a bug at
        the point it was written, and silently joining it would produce a path
        that simply does not exist.
        """
        text = str(rel).replace("\\", "/")
        if not text.startswith(_RELATIVE_PREFIXES):
            raise ValueError(
                f"manifest path {rel!r} does not start with "
                f"{' or '.join(_RELATIVE_PREFIXES)}.\n"
                "Manifests store paths relative to the company folder; an "
                "absolute path or an unexpected prefix means whatever wrote "
                "this record was not using CompanyPaths."
            )
        return self.company / text

    def relative(self, path: Path) -> str:
        """The inverse of `resolve`: the string a manifest should store.

        Always forward slashes, so a manifest written on Windows is byte-identical
        to one written on Linux — which is what makes "run twice, diff nothing"
        (CLAUDE.md rule 4) achievable at all.
        """
        return path.resolve().relative_to(self.company.resolve()).as_posix()


def paths(ticker: str | None = None) -> CompanyPaths:
    """The CompanyPaths for this process. Stage modules call this at import."""
    return CompanyPaths(ticker=resolve_ticker(ticker))


def add_ticker_arg(parser) -> None:
    """Declare `--ticker` on a stage's argparse parser.

    The flag's VALUE is not consumed here — `resolve_ticker` already read it
    straight from `sys.argv` at import time, because the module-level path
    constants needed it before argparse existed (see TICKER RESOLUTION above).

    It is still declared, for three reasons that are not cosmetic:
      - `--help` lists it, so the option is discoverable;
      - argparse rejects a typo like `--tickr MORN` instead of letting the run
        proceed against the fallback company;
      - without a declaration argparse fails the whole invocation with
        "unrecognized arguments: --ticker MORN", which is how this was caught.
    """
    parser.add_argument(
        "--ticker", metavar="TICKER", default=None,
        help="company to operate on. Defaults to $EQR_TICKER, or to the single "
             "company under companies/ when there is exactly one.")
