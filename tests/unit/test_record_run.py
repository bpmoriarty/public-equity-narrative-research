"""The one file five stages share, and the merge that keeps them from erasing it.

Run:  uv run python tests/unit/test_record_run.py

WHY THIS FILE EXISTS
--------------------
`settings.record_run` is the only shared-file writer in the pipeline. Five
deterministic stages — discover, risk_diff, triage_8k, build_ledger,
render_timeline — each append their own key to `data/_meta/run-log.json` at the
end of a run. That is the exact shape CLAUDE.md rule 4 was written about:

    "Writers merge, never clobber. Run twice, diff nothing."

Two stages have overwritten a manifest another stage owned in this repository's
history. A writer that replaced this file instead of merging into it would erase
the other four stages' entries on every run, in a file small enough that nobody
would look and gitignored so no diff would ever show it. That is why the merge is
tested here rather than trusted.

WHY THIS IS A UNIT TEST AND NEEDS NO COMPANY
--------------------------------------------
`CompanyPaths` takes its `root` as a field, so a complete synthetic company
exists wherever a temp directory does:

    CompanyPaths(ticker="ZZTEST", root=Path(tempfile.mkdtemp()))

Nothing is written under `companies/`, which matters for a reason found in Phase
4.6 and again in 5.1: a real company folder makes per-company checks multiply, so
the file's check COUNT starts depending on how many companies exist — and that
count is the tripwire the whole suite hangs on. A synthetic root has no such
effect, and it also means these checks run in a bare checkout with no data at all.

THE DEFECT THIS FILE FOUND, AND WHY IT COUNTS AS ONE
----------------------------------------------------
`record_run`'s docstring promised that a corrupt log "must never stop a pipeline
stage that had already done its real work" — the call happens last, after the
stage has written its real output. The guard was `except (json.JSONDecodeError,
OSError)`, which covers unparseable bytes and an unreadable file.

It does not cover valid JSON that is not an object. A log containing `5`, `"x"`,
`[]` or `null` parses fine and then raises TypeError on the item assignment
below it — uncaught, so the stage fails after doing its work, which is precisely
what the guard existed to prevent. Four of the five corruption shapes tried here
crashed before the fix in this commit; only unparseable bytes were handled.

Realistic? The file is gitignored and only this function writes it, so the
plausible corruptions are truncation and an empty file, both of which were
already caught. The point is narrower and worth keeping: the guard did not do
what its own docstring said, and it took writing input that fails it to find that
out (CLAUDE.md rule 3).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from equity_research import settings
from equity_research.paths import CompanyPaths

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


# A synthetic company per scenario, so no test can inherit another's log.
def fresh() -> CompanyPaths:
    return CompanyPaths(ticker="ZZTEST", root=Path(tempfile.mkdtemp()))


def read(P: CompanyPaths) -> dict:
    return json.loads(P.run_log.read_text(encoding="utf-8"))


# The five stages that actually share this file. Named here so the merge checks
# below describe the real situation rather than a two-writer toy.
SHARERS = ("build_ledger", "discover", "render_timeline", "risk_diff", "triage_8k")

# What `record_run` stamps. Deliberately second-precision and Z-suffixed.
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ---------------------------------------------------------------------------
print("THE FILE IT WRITES")
# ---------------------------------------------------------------------------
P = fresh()
check("the run log does not exist before the first call", P.run_log.exists(), False)

settings.record_run(P, "discover", sec_requests_made=0, filings=127)

check("  the call creates data/_meta/ and the file in it", P.run_log.exists(), True)
log = read(P)
check("  the stage is a top-level key", list(log), ["discover"])
check("  run_utc is stamped in the expected shape",
      bool(STAMP_RE.match(log["discover"]["run_utc"])), True)
check("  extra fields are carried through verbatim",
      {k: v for k, v in log["discover"].items() if k != "run_utc"},
      {"sec_requests_made": 0, "filings": 127})
# The clock belongs here and nowhere else (Phase 4.8). If this function ever
# wrote a second file, that file would be a candidate for carrying a timestamp
# into git.
check("  it writes exactly one file under data/",
      sorted(p.relative_to(P.data).as_posix()
             for p in P.data.rglob("*") if p.is_file()),
      ["_meta/run-log.json"])


# ---------------------------------------------------------------------------
print()
print("IT MERGES, NEVER CLOBBERS — CLAUDE.md rule 4")
# ---------------------------------------------------------------------------
P = fresh()
settings.record_run(P, "discover", filings=127)
settings.record_run(P, "risk_diff", deltas=99)

check("a second stage does not erase the first",
      sorted(read(P)), ["discover", "risk_diff"])
check("  and the first stage's own fields survive intact",
      read(P)["discover"]["filings"], 127)

settings.record_run(P, "discover", filings=128)
check("re-writing a stage does not erase the other",
      sorted(read(P)), ["discover", "risk_diff"])
check("  it replaces that stage's own fields",
      read(P)["discover"]["filings"], 128)
check("  and leaves the other stage's fields untouched",
      read(P)["risk_diff"]["deltas"], 99)

# The real case: five writers, one file, run in sequence as `pipeline` runs them.
P = fresh()
for stage in SHARERS:
    settings.record_run(P, stage)
check("all five sharing stages survive each other", sorted(read(P)), list(SHARERS))


# ---------------------------------------------------------------------------
print()
print("THE FILE'S SHAPE DOES NOT DEPEND ON THE ORDER THE STAGES RAN")
# ---------------------------------------------------------------------------
# `pipeline` runs the stages in a fixed order, but a stage re-run by hand appends
# out of order. Sorting means the file cannot record that history in its layout.
P = fresh()
for stage in reversed(SHARERS):
    settings.record_run(P, stage)
text = P.run_log.read_text(encoding="utf-8")
check("keys appear sorted in the text even when written in reverse",
      re.findall(r'^  "([a-z_0-9]+)":', text, re.M), list(SHARERS))
check("  the file ends in exactly one newline",
      (text.endswith("\n"), text.endswith("\n\n")), (True, False))

# Two write orders, one byte-identical result — with the clock normalised out,
# since run_utc is the one field that is *supposed* to move. This is "run twice,
# diff nothing" for the only part of this file that can hold still.
def normalised(P: CompanyPaths) -> str:
    return re.sub(r'"run_utc": "[^"]+"', '"run_utc": "<stamp>"',
                  P.run_log.read_text(encoding="utf-8"))

A, B = fresh(), fresh()
for stage in SHARERS:
    settings.record_run(A, stage, n=1)
for stage in reversed(SHARERS):
    settings.record_run(B, stage, n=1)
check("two different write orders produce byte-identical text",
      normalised(A) == normalised(B), True)


# ---------------------------------------------------------------------------
print()
print("A CORRUPT LOG MUST NOT FAIL A STAGE THAT ALREADY DID ITS WORK")
# ---------------------------------------------------------------------------
# record_run is called LAST in a stage, after the real output is on disk. An
# exception here loses a diagnostic file and fails a run that had succeeded.
#
# Aggregated into two checks rather than one per shape, so the count is a
# property of this file and not of how many corruptions anyone thought of.
CORRUPTIONS = {
    "unparseable bytes": "not json at all",
    "an empty file": "",
    "a bare number": "5",
    "a JSON string": '"text"',
    "a JSON list": "[]",
    "JSON null": "null",
}

raised: list[str] = []
recovered: list[str] = []
for label, content in CORRUPTIONS.items():
    P = fresh()
    P.run_log.parent.mkdir(parents=True, exist_ok=True)
    P.run_log.write_text(content, encoding="utf-8")
    try:
        settings.record_run(P, "discover", filings=1)
    except Exception as e:                                  # noqa: BLE001
        raised.append(f"{label}: {type(e).__name__}")
        continue
    if read(P).get("discover", {}).get("filings") == 1:
        recovered.append(label)

check("no corruption shape raises out of record_run", raised, [])
check("  every one is discarded and the new entry lands",
      sorted(recovered), sorted(CORRUPTIONS))


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
