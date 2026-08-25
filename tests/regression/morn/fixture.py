"""The company the regression tests are bound to, named once.

WHY THIS EXISTS
---------------
Six test files assert MORN's numbers — 88 cached extractions, 1,326 verified
quotes, pack sha256 fd320ce5, 231 sections. They used to reach those artifacts
with a bare `paths()`, which resolves the ticker from `--ticker`, then
`EQR_TICKER`, then "the single company under companies/".

That third fallback was doing the work, and it is a coincidence of the
repository rather than a statement of intent. `paths.resolve_ticker` hard-errors
the moment a second company exists — deliberately, because silently picking one
would run every stage perfectly against the wrong company's filings — so
`pipeline init TSLA` used to break all six files at import.

Naming the fixture company here fixes that and makes the tests honest about what
they are: they check MORN, so they should say MORN.

WHY NOT JUST `paths("MORN")` IN EACH FILE
The string would then appear in several places, and the point of a fixture
constant is that the answer to "which company do the regression tests read?" has
one home. Phase 5.1 moved this file into tests/regression/morn/, so the directory
name now says it too — but the constant still holds it, because the tests import
a value rather than parsing their own path.

IMPORTABLE BY ITS SIBLINGS, WHICH IS NOW ALL IT NEEDS TO BE
Every file that imports this one lives in this directory, so `from fixture
import ...` resolves whether a file is run directly (sys.path[0] is the script's
own directory) or run as a subprocess by run_all. Before the split this module
sat in tests/ and was imported from there; after it, nothing outside this
directory needs it — which is the point of the split, and is why no sys.path
manipulation appears anywhere in it. `run_all.py` still needs FIXTURE_TICKER for
the child environment and loads this file by path rather than by name.

Named `fixture.py` so neither `run_all.py`'s `test_*.py` glob nor pytest's
`*_test.py` pattern picks it up as a test file.

IMPORT THIS BEFORE ANY equity_research STAGE MODULE
---------------------------------------------------
Not a style preference — it is why setting `EQR_TICKER` below is the fix rather
than exporting `P`.

Every stage module resolves the ticker at IMPORT time, because its path
constants are module-level (`SECTIONS_MANIFEST = P.sections_manifest`) and
Python evaluates those when the module loads. So `import equity_research.discover`
is itself an ambiguous `paths()` call the moment two companies exist — and it
happens before any `from fixture import P` further down the file can help.

Exporting `P` alone therefore fixed nothing: four test files still died on the
import above it. Setting the environment variable does fix it, for every
`paths()` call in the process including the stage modules' own, but only if this
module is imported first.
"""

from __future__ import annotations

import os
import sys

# Forced rather than defaulted from the environment: a stray EQR_TICKER in
# someone's shell would otherwise point these assertions at a company whose
# artifacts they do not describe, and the failures would be baffling.
FIXTURE_TICKER = "MORN"

# Set BEFORE equity_research.paths is imported below, and before the importing
# test file pulls in any stage module. See the note above.
os.environ["EQR_TICKER"] = FIXTURE_TICKER

from equity_research.paths import paths  # noqa: E402

# Every data/ and output/ path for the fixture company.
P = paths(FIXTURE_TICKER)


def require_artifacts(*needed: "os.PathLike[str] | str") -> None:
    """Exit non-zero if any named artifact is absent. NEVER skip.

    THIS IS THE WHOLE REASON tests/regression/morn/ IS A SEPARATE DIRECTORY.

    Every check in here used to live at the end of a file in tests/, guarded by
    `if artifact.exists(): ... else: print("  --  skipped")`. That guard is
    VERIFICATION.md D7 in source form: test_generate_outputs.py ran 35 checks in
    the working tree and 29 in a clean checkout, printed "0 failed" both times,
    and nothing noticed a sixth of the file had stopped running.

    The count gate in run_all.py was built to catch that, and it does — but only
    because the counts happen to be recorded from a tree where the artifacts are
    present. Splitting the suite makes the counts environment-independent
    instead: tests/unit/ reads no company data at all, and everything in here
    declares what it needs up front and DIES if it is missing. A regression test
    with nothing to regress against is a failure, not a pass and not a skip.

    Fails on the first missing path with all of them listed, because a clean
    checkout is usually missing several and reporting one at a time turns one
    diagnosis into four runs.
    """
    from pathlib import Path

    missing = [Path(p) for p in needed if not Path(p).exists()]
    if not missing:
        return

    lines = [f"FATAL: {len(missing)} of {len(needed)} required "
             f"{FIXTURE_TICKER} artifact(s) are missing, so these regression "
             f"checks have nothing to verify:"]
    for p in missing:
        try:
            shown = p.relative_to(P.root)
        except ValueError:
            shown = p
        lines.append(f"  - {shown}")
    lines.append("")
    lines.append("This is a hard failure by design. Committed artifacts "
                 "(ledger/, facts/, output/*.md, gen-*.json) are model output "
                 "and cannot be regenerated for free — restore them with "
                 "`git checkout -- companies/`. Derived ones (pack/, sections/, "
                 "the manifests) are free to rebuild: `uv run pipeline "
                 f"{FIXTURE_TICKER}`.")
    sys.exit("\n".join(lines))
