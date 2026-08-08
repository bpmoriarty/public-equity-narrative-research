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
Runs each tests/test_*.py, reads the `N passed, M failed` line it prints, and
compares N against tests/expected_counts.json. A mismatch fails **in either
direction**:

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
    return sorted(HERE.glob("test_*.py"))


def load_expected() -> dict[str, int]:
    if not EXPECTED.exists():
        print(f"FAIL  {EXPECTED.name} is missing — nothing to compare against.")
        print("      Create it with: uv run python tests/run_all.py --update")
        raise SystemExit(1)
    doc = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return dict(doc["counts"])


def run_one(path: Path) -> tuple[int | None, int | None, int, str]:
    """Return (passed, failed, exit_code, output). passed is None if unparseable."""
    r = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
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
        print("FAIL  no test_*.py files found in tests/ — the suite has vanished.")
        return 1

    expected = {} if args.update else load_expected()
    observed: dict[str, int] = {}
    problems: list[str] = []

    print(f"Running {len(files)} test file(s)")
    print("=" * 74)
    for path in files:
        name = path.name
        passed, failed, code, out = run_one(path)

        if passed is None:
            problems.append(
                f"{name}: printed no 'N passed, M failed' line. Either it "
                f"crashed before finishing, or it no longer reports a count — "
                f"in which case this gate cannot protect it.")
            print(f"  NO COUNT  {name:32s} exit={code}")
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
        print(f"  {status}      {name:32s} {passed:3d} checks"
              + (f"   [{', '.join(marks)}]" if marks else ""))

    # A file listed in the expectations but no longer on disk.
    for name in sorted(set(expected) - {p.name for p in files}):
        problems.append(f"{name}: listed in {EXPECTED.name} but no longer exists. "
                        f"If it was deleted on purpose, remove it with --update.")
        print(f"  MISSING   {name:32s}   (expected {expected[name]} checks)")

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
