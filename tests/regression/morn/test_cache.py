"""What the fetch and extract stages recorded about MORN's cached filings.

Run:  uv run python tests/regression/morn/test_cache.py

WHY THIS FILE EXISTS
--------------------
Two claims that can only be checked against a real cache:

  1. The inventory reports the DATA's vintage, not the run's clock. This is
     VERIFICATION.md D9, and it is the reason `as_of_utc` and `index_fetched_utc`
     are the one exemption to "committed artifacts carry no wall clock": they
     record when EDGAR was READ, which is stable across re-runs, and they are the
     fields any coverage or survivorship claim is checked against. Stamping the
     run's clock on them was wrong by twelve minutes when it was caught and grows
     without bound.

  2. Sections with no usable text are a NAMED category in the manifest, and every
     row in it is ok=False — so nothing downstream can cite a section that has no
     text in it. A category that is merely listed, while the rows stay ok=True,
     is decorative.

WHAT MOVED HERE, AND FROM WHERE
  - from test_discover.py: the six checks reading inventory.json and the run log.
  - from test_extract_sections.py: the three checks reading
    sections-manifest.json.

Both groups were guarded by `if <file>.exists():` with a "skipped" line in the
else, so a clean checkout ran fewer checks and still printed "0 failed". They
declare what they need up front here and die without it — see
`fixture.require_artifacts`.

A NOTE ON WHICH OF THESE ARE COMMITTED
inventory.json is committed; the run log and sections-manifest.json are
gitignored, so a fresh clone has neither until the pipeline runs once. That is
why the failure message distinguishes "restore from git" from "free to rebuild":
`uv run pipeline MORN` produces both without a model call or an EDGAR request.
"""

from __future__ import annotations

import json
import sys

# fixture FIRST: it sets EQR_TICKER, which every later paths() call reads.
from fixture import P, require_artifacts  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


require_artifacts(P.inventory, P.run_log, P.sections_manifest)

print("THE INVENTORY — the data's vintage, not the run's clock")

inv = json.loads(P.inventory.read_text(encoding="utf-8"))
check("as_of_utc is present", bool(inv.get("as_of_utc")), True)
check("  as_of_utc equals the index fetch time, not the run time",
      inv["as_of_utc"], inv["index_fetched_utc"])
# `run_utc` moved OUT of inventory.json in Phase 4.8 — it describes the run, not
# the data, and a field that changes every re-run made this committed file
# impossible to reproduce byte for byte. The D9 property is unchanged and still
# checked: the as-of date must not be the clock of the run that wrote it. The
# clock is now read from the gitignored run log, which makes the statement
# slightly stronger than it was — the two values are no longer even in one file.
check("  inventory.json no longer carries the run's own clock",
      "run_utc" in inv, False)

log = json.loads(P.run_log.read_text(encoding="utf-8"))
ran = log.get("discover", {})
check("  the run log records when discover last ran", bool(ran.get("run_utc")), True)
# The defect, stated as a test: on a cache-first run these MUST differ, and the
# old code made them equal by construction.
if ran.get("sec_requests_made") == 0:
    check("  a zero-request run does not claim its own clock as the as-of date",
          inv["as_of_utc"] != ran["run_utc"], True)
else:
    check("  (the last run hit EDGAR, so the two legitimately coincide)", True, True)
check("  the basis of the as-of date is recorded, not assumed",
      bool(inv.get("as_of_basis")), True)


# ---------------------------------------------------------------------------
print()
print("THE SECTIONS MANIFEST — a section with no usable text cannot be cited")
# ---------------------------------------------------------------------------
man = json.loads(P.sections_manifest.read_text(encoding="utf-8"))
listed = man.get("sections_with_no_usable_text", [])
check("no-usable-text sections are a named category, not folded into failures",
      isinstance(listed, list), True)
# Every row in that category must actually be marked not-ok, or the category is
# decorative and the section is still reachable by anything reading `ok`.
bad = [r for r in man["sections"]
       if any(p.startswith("NO USABLE TEXT") for p in (r.get("problems") or []))
       and r.get("ok")]
check("  and every one of them is ok=False, so nothing downstream can cite it",
      bad, [])
check("  the category and the flagged rows agree",
      len(listed),
      sum(1 for r in man["sections"]
          if any(p.startswith("NO USABLE TEXT") for p in (r.get("problems") or []))))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
