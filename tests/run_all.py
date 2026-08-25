"""Run every test script and refuse to accept a suite that has silently shrunk.

Run:  uv run python tests/run_all.py
      uv run python tests/run_all.py --update   (re-record the expected counts)

WHY THIS FILE EXISTS
--------------------
A failing test is easy: it is red, and somebody fixes it. The dangerous case is a
test that stops testing and stays green.

It happened here, measurably. `tests/test_generate_outputs.py` reads the
generation records in data/pack/, and those were gitignored at the time. In the
working tree it ran 35 checks and printed "35 passed, 0 failed". In a clean
checkout the records were absent, six checks quietly skipped, and it printed
"29 passed, 0 failed" — green, in both cases, with a sixth of the file not
running. Nothing was watching the number, so nothing noticed. (VERIFICATION.md D7.)

The lesson generalises past that one file. A suite can shrink from a missing
fixture, an early return, a renamed function that no longer matches a loop, a
try/except that swallows a case, or a test file that stops being discovered at
all. Every one of those reports success.

WHAT THIS DOES
--------------
Runs each `test_*.py` found anywhere under tests/ — at any depth, so the
tests/unit and tests/regression/morn split is visible to it — reads the
`N passed, M failed` line each one prints, and compares N against
tests/expected_counts.json. Files are recorded under their path relative to
tests/, so a file that moves reads as one MISSING plus one UNREGISTERED rather
than as silence. A mismatch fails **in either direction**:

  - FEWER checks than expected  — the shrink case above.
  - MORE checks than expected   — new checks were added and not recorded. Not a
                                  defect, but it must be a deliberate act, so
                                  that the number stays trustworthy as a
                                  tripwire. Re-record with --update.

It also fails if a test file exists that the expectations do not list, or if the
expectations list a file that no longer exists. Deleting a test should be a
visible decision, not a silent reduction in coverage.

NOTE ON CLEAN CHECKOUTS
-----------------------
Several tests read committed MORN artifacts and legitimately run fewer checks
without them. Today that makes this gate a working-tree check. Phase 5 of the
productionization plan splits tests/unit/ from tests/regression/morn/, at which
point the regression tests error rather than skip and the counts become
environment-independent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXPECTED = HERE / "expected_counts.json"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Every test file ends with a line in this shape. Trailing parenthetical detail
# — "(2 of 2 generated document(s) checked)" — is allowed after it.
COUNT_RE = re.compile(r"^(\d+) passed, (\d+) failed", re.MULTILINE)


def discover() -> list[Path]:
    """Every test file under tests/, at any depth.

    RECURSIVE, and that is the whole point of this function existing rather than
    a glob inline at the call site. Until Phase 5.1 this was
    `HERE.glob("test_*.py")` — non-recursive — so the moment a test file moved
    into tests/unit/ or tests/regression/morn/ it stopped being discovered.

    A file that stops being discovered is the exact failure the count gate exists
    to catch (VERIFICATION.md D7), so the gate has to be able to see the layout
    it is about to be pointed at BEFORE anything moves. That is why this change
    ships as its own commit, ahead of the split: with a flat tests/ directory
    `key()` returns the bare filename, so the recorded counts are unchanged and
    this commit is provably a capability change and nothing else.

    __pycache__ is excluded because rglob would otherwise return compiled
    artifacts on some layouts; they are not test files and cannot report a count.
    """
    return sorted(p for p in HERE.rglob("test_*.py")
                  if "__pycache__" not in p.parts)


def key(path: Path) -> str:
    """The name a file is recorded under in expected_counts.json.

    Relative to tests/ and always forward-slashed, so the recorded keys are
    identical on Windows and POSIX — a backslash here would make the expectations
    file platform-specific and every key would read as UNREGISTERED on the other
    platform.
    """
    return path.relative_to(HERE).as_posix()


def load_expected() -> dict[str, int]:
    if not EXPECTED.exists():
        print(f"FAIL  {EXPECTED.name} is missing — nothing to compare against.")
        print("      Create it with: uv run python tests/run_all.py --update")
        raise SystemExit(1)
    doc = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return dict(doc["counts"])


# The fixture company is named in tests/regression/morn/fixture.py, which the
# regression files import directly. One home for the answer to "which company do
# the regression tests read?".
#
# Passed to every child as EQR_TICKER, so a test file that resolves paths some
# other way still lands on the same company, and so does anything those files
# shell out to. Unit files get it too: they read no company data, but several of
# them import stage modules, and a stage module resolves the ticker at import
# time (module-level path constants), so importing one needs *a* company named.
#
# Loaded BY PATH, not by name. Phase 5.1 moved fixture.py out of tests/, and the
# alternative — putting tests/regression/morn on sys.path — would quietly make
# `fixture` importable from tests/unit/ as well, which is exactly the coupling
# the split exists to remove.
import importlib.util as _importlib_util  # noqa: E402

_FIXTURE_PY = HERE / "regression" / "morn" / "fixture.py"
if not _FIXTURE_PY.exists():
    raise SystemExit(
        f"FAIL  {_FIXTURE_PY.relative_to(ROOT).as_posix()} is missing. It names "
        f"the company the regression tests read, and every child process is "
        f"given that name — without it this runner cannot say which company it "
        f"is testing.")
_spec = _importlib_util.spec_from_file_location("eqr_test_fixture", _FIXTURE_PY)
_fixture = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
FIXTURE_TICKER = _fixture.FIXTURE_TICKER


def run_one(path: Path) -> tuple[int | None, int | None, int, str]:
    """Return (passed, failed, exit_code, output). passed is None if unparseable."""
    env = {**os.environ, "EQR_TICKER": FIXTURE_TICKER, "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    hits = COUNT_RE.findall(out)
    if not hits:
        return None, None, r.returncode, out
    # The last match is the file's own summary; earlier ones could only come
    # from quoted sample output inside the test.
    passed, failed = hits[-1]
    return int(passed), int(failed), r.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update", action="store_true",
                    help="re-record expected_counts.json from this run. Use only "
                         "when the change in counts is intended, and commit the "
                         "result alongside the tests that caused it.")
    args = ap.parse_args()

    files = discover()
    if not files:
        print("FAIL  no test_*.py files found anywhere under tests/ — the suite "
              "has vanished.")
        return 1

    expected = {} if args.update else load_expected()
    observed: dict[str, int] = {}
    problems: list[str] = []

    print(f"Running {len(files)} test file(s)")
    print("=" * 74)
    for path in files:
        name = key(path)
        passed, failed, code, out = run_one(path)

        if passed is None:
            problems.append(
                f"{name}: printed no 'N passed, M failed' line. Either it "
                f"crashed before finishing, or it no longer reports a count — "
                f"in which case this gate cannot protect it.")
            print(f"  NO COUNT  {name:40s} exit={code}")
            # Show the tail; a crash traceback is the usual cause.
            for line in out.strip().splitlines()[-6:]:
                print(f"            {line}")
            continue

        observed[name] = passed
        want = expected.get(name)
        marks = []
        if failed:
            problems.append(f"{name}: {failed} check(s) FAILED.")
            marks.append(f"{failed} FAILED")
        if code != 0 and not failed:
            problems.append(f"{name}: exited {code} while reporting no failed checks.")
            marks.append(f"exit={code}")
        if not args.update:
            if want is None:
                problems.append(
                    f"{name}: not listed in {EXPECTED.name}. A new test file must "
                    f"be recorded before the gate can protect it (--update).")
                marks.append("UNREGISTERED")
            elif passed != want:
                direction = "FEWER" if passed < want else "MORE"
                problems.append(
                    f"{name}: {passed} checks, expected {want} — {direction} than "
                    f"recorded." + (
                        "  Checks disappeared. Find out which before doing "
                        "anything else; a test that stops testing still reports "
                        "green." if passed < want else
                        "  If the new checks are intended, re-record with "
                        "--update and commit it with them."))
                marks.append(f"expected {want}")

        status = "ok  " if not marks else "FAIL"
        print(f"  {status}      {name:40s} {passed:3d} checks"
              + (f"   [{', '.join(marks)}]" if marks else ""))

    # A file listed in the expectations but no longer on disk. After the Phase 5.1
    # split this is also what a *half-finished move* looks like: the file is gone
    # from where it was recorded and its new path reads as UNREGISTERED above, so
    # one rename shows up as one of each rather than as silence.
    for name in sorted(set(expected) - {key(p) for p in files}):
        problems.append(f"{name}: listed in {EXPECTED.name} but no longer exists. "
                        f"If it was deleted on purpose, remove it with --update. "
                        f"If it MOVED, record it under its new path — the key is "
                        f"the path relative to tests/, not the bare filename.")
        print(f"  MISSING   {name:40s}   (expected {expected[name]} checks)")

    total = sum(observed.values())
    print("=" * 74)
    print(f"{total} checks across {len(observed)} file(s)")

    if args.update:
        doc = {
            "note": ("Expected check counts per test file. tests/run_all.py fails "
                     "if any file's count differs in EITHER direction — fewer means "
                     "checks silently disappeared (see VERIFICATION.md D7), more "
                     "means new checks were added without recording them. "
                     "Re-record with: uv run python tests/run_all.py --update"),
            "total": total,
            "counts": dict(sorted(observed.items())),
        }
        EXPECTED.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"\nRE-RECORDED {EXPECTED.name}: {total} checks across "
              f"{len(observed)} file(s).")
        print("Commit this alongside the test changes that caused it.")
        return 1 if any("FAILED" in p or "exited" in p for p in problems) else 0

    if problems:
        print()
        print(f"{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"every file ran the expected number of checks, all passing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
