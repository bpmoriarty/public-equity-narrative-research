"""Run each deterministic stage again and prove the committed bytes do not move.

Run:  uv run python tests/regression/morn/test_reruns_change_nothing.py

    SLOW BY DESIGN: about 28 seconds, of which ~20 are build_ledger re-verifying
    1,329 quotes against the section text. That is most of this suite's runtime.
    The cost is the point — it is the only automated proof of the property below,
    and the property broke silently for two weeks before anyone noticed.

WHY THIS FILE EXISTS
--------------------
CLAUDE.md rule 4: "Writers merge, never clobber. Run twice, diff nothing."

Five stages write thirteen committed artifacts and are pure functions of their
inputs: discover, risk_diff, triage_8k, build_ledger, render_timeline. Nothing
they read changes between two runs, so nothing they write should either.

That was false for eight of the thirteen until Phase 4.8, because each stage
stamped `datetime.now()` inside a file that was otherwise reproducible. Harmless
while stages were run by hand one at a time — which is why it sat open as Next
Steps 19 for two weeks — and structural the moment `pipeline` began touching all
five on every run: the tree was dirty after every orchestrated run, and Phase 4's
own gate claimed "verify green, git status clean afterward" while the second half
was not true.

Phase 4.8 fixed it and added a static lint (no wall clock in a committed
artifact). That lint catches the one way this has ever broken. It cannot prove
the property — a set iterated without sorting, a float formatted differently, a
dict built from `glob()` order would all pass the lint and still churn. Proving
it needs the stages actually run, which is what this file does.

WHY ONE RUN AND NOT TWO
-----------------------
The obvious shape is: run the stage, run it again, compare the two outputs. This
compares one run against the COMMITTED bytes instead, which is better on three
counts and cheaper on the fourth.

  - It tests reproducibility against the record a reviewer would see as a diff,
    which is what rule 4 and Phase 4's gate 3 actually assert. Two fresh runs
    agreeing with each other while both disagree with git is still a dirty tree.
  - It costs one execution per stage rather than two — 28 seconds, not 56.
  - The committed bytes were written by an earlier process with its own random
    PYTHONHASHSEED, and this run forces a different one (see below), so hash
    order is exercised for free rather than needing a third run.
  - The failure it cannot see is a stage that is broken in the same way twice.
    Nothing here is stateful enough for that to be plausible.

PYTHONHASHSEED IS SET DELIBERATELY
----------------------------------
Python randomises string hashing per process, so a set iterated without sorting
comes out in a different order in every run. That is the classic source of
"byte-identical on my machine" — and an in-process run-twice test cannot see it
at all, because both runs share one seed.

The seed is pinned to a fixed value here that the committed bytes were almost
certainly not written under. If a stage ever serialises an unsorted set, this
comparison is what catches it.

IT MUST NEVER TOUCH THE NETWORK
-------------------------------
`discover` is cache-first but will fetch if its submissions cache is absent, and
a test that quietly makes EDGAR requests violates the one rule CLAUDE.md states
unconditionally: EDGAR is hit once per document, ever. The cache is therefore a
declared requirement, and the last check reads the run log to confirm the stage
made zero requests. The cache path is derived from the CIK in inventory.json
rather than spelled out, so it cannot go stale against a different company.

WHAT IT DOES TO THE WORKING TREE
--------------------------------
It runs real stages, which write to `companies/MORN/`. If the property holds
nothing changes. If it does not, the difference is captured into the failure
message and the original bytes are then restored, so a red test leaves a clean
tree and the evidence in its output rather than a dirty tree and a puzzle.

Gitignored siblings (the manifests, `triage/text/`, `pack/timeline-report.md`)
DO churn on every run — they carry a `generated_utc` by design, because nothing
committed depends on them being reproducible. They are not compared and not
restored.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# fixture FIRST: it sets EQR_TICKER, which every later paths() call reads.
from fixture import FIXTURE_TICKER, P, require_artifacts  # noqa: E402

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


# ---------------------------------------------------------------------------
# Which stage writes which committed artifact
# ---------------------------------------------------------------------------
# Model output is excluded: `facts/` and `gen-*.json` are what a paid call
# returned, and the two prose deliverables are re-rendered from those records by
# `--apply-corrections`. None of them is a function of anything a re-run repeats,
# so "run twice, diff nothing" is not a claim that applies (CLAUDE.md rule 1).
MODEL_OUTPUT = (
    "data/ledger/facts/",
    "data/pack/gen-",
    "output/narrative-brief.md",
    "output/discussion-points.md",
)

# Deliberately a predicate per stage rather than a list of filenames: the ledger
# holds one FY*.json per fiscal year, so a filename list would make this file's
# check COUNT depend on the size of the window. That is the defect found twice
# already — a count that moves with the environment disarms the gate that the
# whole suite hangs on (Phase 4.6, Phase 5.1).
STAGES: dict[str, "callable"] = {
    "discover": lambda r: r.startswith("data/discovery/"),
    "risk_diff": lambda r: r.startswith("data/ledger/risk-"),
    "triage_8k": lambda r: r.startswith("data/triage/"),
    "build_ledger": lambda r: (r.startswith("data/ledger/FY")
                               or r == "data/ledger/ledger-report.md"),
    "render_timeline": lambda r: r == "output/timeline.md",
}


def committed_artifacts() -> list[str]:
    """Company-relative paths of every committed artifact, model output aside.

    Taken from git rather than from a hand-kept list, so an artifact added later
    is covered by this file the day it is committed instead of the day someone
    remembers to add it here.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", str(P.data.relative_to(P.root)),
         str(P.output.relative_to(P.root))],
        cwd=P.root, capture_output=True, text=True, check=True).stdout
    rows = [r.replace("\\", "/") for r in out.split("\0") if r]
    prefix = P.company.relative_to(P.root).as_posix() + "/"
    rel = [r[len(prefix):] for r in rows if r.startswith(prefix)]
    return sorted(r for r in rel if not r.startswith(MODEL_OUTPUT))


def run_stage(stage: str) -> subprocess.CompletedProcess:
    """Run one stage in a child process with a pinned, unusual hash seed."""
    env = {**os.environ,
           "EQR_TICKER": FIXTURE_TICKER,
           "PYTHONUTF8": "1",
           # See PYTHONHASHSEED IS SET DELIBERATELY in the module docstring.
           "PYTHONHASHSEED": "1"}
    return subprocess.run(
        [sys.executable, "-m", f"equity_research.{stage}", "--ticker", FIXTURE_TICKER],
        cwd=P.root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env)


def compare_and_restore(before: dict[str, bytes]) -> list[str]:
    """Which snapshotted files moved. Puts every mover back before returning.

    A failing test should leave the tree as it found it and the evidence in its
    own output, not a dirty tree and a puzzle.
    """
    moved = []
    for r, original in before.items():
        now = P.resolve(r).read_bytes()
        if now == original:
            continue
        moved.append(f"{r} ({len(original)} -> {len(now)} bytes)")
        P.resolve(r).write_bytes(original)
    return moved


# ---------------------------------------------------------------------------
# What this needs on disk
# ---------------------------------------------------------------------------
# `sections/` and `pack/` are gitignored and free to rebuild; the ledger, the
# facts and the triage decisions are committed. require_artifacts says which is
# which in its failure message.
#
# TWO CALLS, AND THE ORDER MATTERS. The submissions-cache path is derived from
# the CIK in inventory.json rather than hardcoded, so inventory.json has to be
# read to build it — which means it must be required BEFORE that read, not
# alongside it. Written the other way round first, and a checkout with no
# artifacts died on `read_text` with a raw traceback: still exit 1, so it never
# passed vacuously, but the designed message naming every missing file and how to
# restore it was bypassed by the very first one. Found by running it in a bare
# worktree, which is the only place the difference shows.
require_artifacts(P.inventory)

inv = json.loads(P.inventory.read_text(encoding="utf-8"))
SUBMISSIONS = P.meta / f"submissions_CIK{inv['cik']}.json"

require_artifacts(
    SUBMISSIONS,             # discover: so the re-run stays offline
    P.sections_manifest,     # risk_diff, triage_8k: which sections exist
    P.triage_json,           # triage_8k: its own committed output
    P.risk_deltas,           # build_ledger: an input as well as risk_diff's output
    P.facts,                 # build_ledger: the paid extractions
    P.timeline_events,       # render_timeline: the merged rows
)


# ---------------------------------------------------------------------------
print("EVERY COMMITTED ARTIFACT BELONGS TO A STAGE")
# ---------------------------------------------------------------------------
artifacts = committed_artifacts()
owned = {stage: [r for r in artifacts if owns(r)] for stage, owns in STAGES.items()}
claimed = sorted(r for rows in owned.values() for r in rows)

# Anti-vacuous. If `git ls-files` returned nothing — wrong cwd, a submodule, a
# clone with no history — every per-stage check below would compare zero files
# and pass. Assert the list is real before trusting anything built on it.
check("the committed artifact list is non-empty", bool(artifacts), True)
# An artifact nobody claims is the interesting case: a new committed file that no
# stage in this table produces is either model output that belongs in
# MODEL_OUTPUT, or a sixth deterministic writer that nothing here is checking.
check("  every one is attributed to exactly one stage", claimed, artifacts)
print(f"        {len(artifacts)} artifact(s) across {len(STAGES)} stage(s): "
      + ", ".join(f"{s} {len(rows)}" for s, rows in owned.items()))


# ---------------------------------------------------------------------------
print()
print("RE-RUNNING A STAGE CHANGES NOTHING IT WROTE — CLAUDE.md rule 4")
# ---------------------------------------------------------------------------
# Exactly one check per stage on every path through this loop, so the file's
# check count does not depend on whether a stage passed, failed, or had nothing
# to compare. A count that moves with the outcome is a count nobody can gate on.
for stage, rel_paths in owned.items():
    # A stage with nothing to compare would pass silently, which is the same
    # vacuous-pass shape as the check above.
    if not rel_paths:
        check(f"{stage} has committed artifacts to compare", rel_paths, ["at least one"])
        continue

    before = {r: P.resolve(r).read_bytes() for r in rel_paths}
    proc = run_stage(stage)
    if proc.returncode != 0:
        # Reported as its own failure rather than as a byte comparison: a stage
        # that never ran wrote nothing, so "0 files differ" would be true and
        # would read as a pass.
        tail = " / ".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
        check(f"{stage} — the stage ran at all",
              f"exit {proc.returncode}: {tail}", "exit 0")
        continue

    check(f"{stage} — {len(rel_paths)} file(s) byte-identical after a re-run",
          compare_and_restore(before), [])


# ---------------------------------------------------------------------------
print()
print("AND IT DID IT WITHOUT TOUCHING EDGAR")
# ---------------------------------------------------------------------------
# CLAUDE.md is unconditional: EDGAR is hit once per document, ever. `discover`
# ran above, so the run log now describes THIS test's run of it.
ran = json.loads(P.run_log.read_text(encoding="utf-8")).get("discover", {})
check("the discover re-run above made zero SEC requests",
      ran.get("sec_requests_made"), 0)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
