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
The string would then appear in seven places counting run_all.py, and the point
of a fixture constant is that the answer to "which company do the regression
tests read?" has one home. Phase 5 moves these files to tests/regression/morn/,
where the directory name says it instead; until then, this does.

IMPORTABLE BOTH WAYS
`tests/` is on sys.path whether a file is run directly (sys.path[0] is the
script's own directory) or collected by pytest (default `prepend` import mode,
no __init__.py here) — the same mechanism that lets suite_test.py do
`from run_all import ...`. Not a revival of the sys.path hacks Phase 1 removed.

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
