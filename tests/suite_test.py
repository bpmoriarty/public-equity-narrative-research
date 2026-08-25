"""Pytest front-end for the script-style test files in this directory.

WHY THIS FILE IS `suite_test.py` AND NOT `test_suite.py`
-------------------------------------------------------
`run_all.py` discovers its work with `rglob("test_*.py")`. A file named
`test_suite.py` would be picked up by that glob *and* import `run_all`, so
run_all would run a file that runs run_all — recursively, once per test file.
Now that discovery descends into subdirectories, that trap applies at any depth,
so the `_test` suffix is the rule for this file wherever it sits.
pytest collects both `test_*.py` and `*_test.py`, so the `_test` suffix lets
pytest see this file while `run_all` stays blind to it.

WHAT THIS ENFORCES — AND WHY IT IS NOT `pytest --collect-only`
--------------------------------------------------------------
The obvious way to make this suite pytest-native is one `def test_all()` per
file, with the count gate comparing `pytest --collect-only -q`. That would be a
downgrade, and it is worth being explicit about why, because it looks like an
upgrade.

`--collect-only` counts *test functions*. One wrapper per file means it counts
eight, forever. It cannot see the number that actually matters: how many
individual checks ran *inside* each file. A file that quietly fell from 63
checks to 3 still collects as exactly one test, and the gate stays green.

That is not hypothetical here. It is the failure recorded as VERIFICATION.md
D7: 35 checks in the working tree versus 29 in a clean checkout, both reporting
success. The whole point of the count gate is to see that.

So each parametrized case below asserts three separate properties:

  1. the file exits 0,
  2. it reports zero failed checks,
  3. it ran the *number* of checks recorded in `expected_counts.json`.

Property 3 is the tripwire. Without it this file is decoration.

RELATIONSHIP TO run_all.py
--------------------------
`run_all.py` remains the authoritative gate and the thing to run by hand; it
gives a readable per-file table. This file exists so `uv run pytest` enforces
exactly the same three properties, for CI and across the tests/unit vs
tests/regression/morn split. Both call the same `discover`, `key` and `run_one`,
so they cannot drift apart in what they measure or in what they call things —
which matters more since the recorded key became a path rather than a filename.
"""

from __future__ import annotations

import pytest

# pytest prepends this file's directory to sys.path (default `prepend` import
# mode, no __init__.py in tests/), which is what makes `run_all` importable by
# name. That is documented pytest behaviour, not a revival of the sys.path
# hacks this phase removed.
from run_all import discover, key, load_expected, run_one

FILES = discover()
EXPECTED = load_expected()


def test_suite_is_not_empty() -> None:
    """Anti-vacuous guard.

    A parametrized test over an empty list reports success without running
    anything. If discovery ever breaks, every other test in this file would
    silently vanish while pytest still exited 0 — so assert the list is real
    before trusting anything built on it.
    """
    assert FILES, (
        "no test_*.py files found in tests/ — the suite has vanished, and "
        "every parametrized case below would have passed vacuously"
    )


def test_expected_counts_reconciles_with_disk() -> None:
    """The recorded file set and the on-disk file set must be identical.

    Checked in both directions on purpose. A file deleted without updating
    expected_counts.json means a test stopped running; a file added without
    recording it means a test is running unmeasured.
    """
    on_disk = {key(p) for p in FILES}
    recorded = set(EXPECTED)

    missing = sorted(recorded - on_disk)
    unrecorded = sorted(on_disk - recorded)

    # Reported together rather than as two sequential asserts: a rename shows up
    # as one of each, and stopping at the first would describe half of it.
    problems = []
    if missing:
        problems.append(
            f"recorded in expected_counts.json but not on disk: {missing} - a "
            f"test file was deleted or renamed, and its checks are no longer running"
        )
    if unrecorded:
        problems.append(
            f"on disk but not recorded in expected_counts.json: {unrecorded} - a "
            f"test file is running unmeasured, so the gate cannot protect it"
        )

    assert not problems, (
        "expected_counts.json and tests/ disagree:\n  "
        + "\n  ".join(problems)
        + "\nRe-record deliberately with `uv run python tests/run_all.py --update` "
        "and commit the result alongside the tests that caused it."
    )


@pytest.mark.parametrize("path", FILES, ids=key)
def test_file_passes_and_ran_every_recorded_check(path) -> None:
    """Run one test file and assert it passed *and* did not shrink."""
    passed, failed, code, out = run_one(path)
    name = key(path)

    assert passed is not None, (
        f"{name} printed no 'N passed, M failed' line, so its check count "
        f"cannot be measured. Every test file must print one — that is how the "
        f"count is taken at the point of the check rather than scraped from "
        f"prose.\n\n--- output ---\n{out[-2000:]}"
    )
    assert failed == 0, (
        f"{name} reported {failed} failed check(s).\n\n"
        f"--- output ---\n{out[-4000:]}"
    )
    assert code == 0, (
        f"{name} exited {code} despite reporting no failed checks - the "
        f"exit code and the summary line disagree, which means one of them is "
        f"lying.\n\n--- output ---\n{out[-2000:]}"
    )

    expected = EXPECTED[name]
    assert passed == expected, (
        f"{name} ran {passed} checks, expected {expected}. "
        + (
            "FEWER checks ran than recorded - this is the failure this gate "
            "exists for: a test that stops testing still reports green."
            if passed < expected
            else "MORE checks ran than recorded - new checks were added without "
            "recording them. Re-record deliberately with "
            "`uv run python tests/run_all.py --update`."
        )
    )
