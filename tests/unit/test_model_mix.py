"""Which model answers which task, and the two ways that config fails silently.

Run:  uv run python tests/unit/test_model_mix.py

WHY THIS FILE EXISTS
--------------------
`[extraction.models]` lets one task run on a different model without a code
change. Nothing uses it today — MORN runs all eight tasks on the default — so
every check here is about the knob being trustworthy the first time somebody
reaches for it, which will be on a company whose numbers nobody has seen.

Two of its failure modes produce no error and no wrong answer, just a run that
quietly ignores the config:

  1. A misspelled task (`vote` for `votes`) matches nothing, so the run proceeds
     on the default model. The header would print the default and look right.
  2. An unknown model id is only noticed when something prices or sends it —
     after the run has started, or during `--estimate` alone.

Both are rejected before the first call instead, and both are checked below
against input that fails them (CLAUDE.md rule 3).

WHAT IS DELIBERATELY NOT TESTED HERE
No check asserts which model any task *should* use. That is a config decision
recorded with its measurements in `companies/MORN/company.toml` and in
`model_for_task`'s docstring; a test asserting it would turn a judgment that
should be revisited per company into a rule that fails when someone revisits it.
What is tested is that the mechanism reports honestly whatever it is told.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

from equity_research import extract_facts as ef
from equity_research import settings

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


# Two real, priced model ids, so nothing here depends on a made-up one being
# accepted. Taken from the price table rather than written out, so this file
# cannot disagree with settings.py about what exists.
PRICED = sorted(settings.MODEL_PRICES)
DEFAULT, OTHER = "claude-opus-5", "claude-sonnet-5"


def ex(models: dict | None = None, model: str = DEFAULT) -> dict:
    """A minimal `[extraction]` table. Only the model keys matter here."""
    out = {"model": model, "effort": "medium", "max_tokens": 16000,
           "max_concurrent_requests": 5}
    if models is not None:
        out["models"] = models
    return out


def rejects(table: dict, model: str = DEFAULT) -> str:
    """The message check_model_config exits with, or "" if it accepted."""
    try:
        with redirect_stdout(io.StringIO()):
            ef.check_model_config(ex(table, model))
    except SystemExit as exc:
        return str(exc)
    return ""


# ---------------------------------------------------------------------------
print("RESOLUTION — the override, else the default")
# ---------------------------------------------------------------------------
check("both real model ids are in the price table", [DEFAULT in PRICED, OTHER in PRICED],
      [True, True])
# The state MORN is in and the state a new company starts in: no table at all.
check("no models table at all falls back to [extraction] model",
      ef.model_for_task({"model": DEFAULT}, "votes"), DEFAULT)
check("an empty models table falls back too",
      ef.model_for_task(ex({}), "votes"), DEFAULT)
# TOML gives `models = {}` when the header is present with only comments under
# it, which is exactly how both company.toml files ship.
check("  every one of the eight tasks falls back",
      sorted({ef.model_for_task(ex({}), t) for t in ef.TASKS}), [DEFAULT])

check("a named task takes the override",
      ef.model_for_task(ex({"votes": OTHER}), "votes"), OTHER)
check("  and its neighbours are untouched",
      ef.model_for_task(ex({"votes": OTHER}), "mdna"), DEFAULT)
check("overrides can name several tasks",
      [ef.model_for_task(ex({"votes": OTHER, "board": OTHER}), t)
       for t in ("votes", "board", "comp")],
      [OTHER, OTHER, DEFAULT])
# An override equal to the default is not an error, just a no-op. Worth pinning:
# it is what a config looks like mid-experiment, and it must not be special.
check("an override equal to the default is a harmless no-op",
      ef.model_for_task(ex({"votes": DEFAULT}), "votes"), DEFAULT)
# `models = {}` is what TOML produces; `models` absent is what an older config
# has. Neither may raise, and a None (a key written with no value would not
# parse, but a programmatic caller could) must not either.
check("a None models table falls back rather than raising",
      ef.model_for_task(ex(None), "votes"), DEFAULT)


# ---------------------------------------------------------------------------
print()
print("A MISSPELLED TASK IS REJECTED, NOT SILENTLY IGNORED")
# ---------------------------------------------------------------------------
check("a valid table is accepted", rejects({"votes": OTHER}), "")
check("  an empty table is accepted", rejects({}), "")

msg = rejects({"vote": OTHER})
check("a misspelled task is rejected", bool(msg), True)
check("  the message names the offending key", "'vote'" in msg, True)
# Without the list, the reader has to go read TASKS in the source to find out
# what they meant to type. `investor_qa` in particular is not guessable.
check("  and lists every valid task name",
      all(t in msg for t in ef.TASKS), True)
# The eight names in the message are the eight the planner actually iterates, so
# a task added to TASKS without a config entry cannot make this message stale.
check("  the list is TASKS itself, not a copy that can drift",
      sorted(t for t in ef.TASKS if t in msg), sorted(ef.TASKS))


# ---------------------------------------------------------------------------
print()
print("AN UNPRICED MODEL IS REJECTED BEFORE THE FIRST CALL")
# ---------------------------------------------------------------------------
msg = rejects({"mdna": "claude-sonnet-9"})
check("an override naming an unpriced model is rejected", bool(msg), True)
check("  the message names the task and the model",
      ("mdna" in msg, "claude-sonnet-9" in msg), (True, True))
check("  and says which models are priced",
      all(m in msg for m in PRICED), True)

# The default is checked too. An unpriced default breaks --estimate for every
# task at once, so catching it only when an override exists would be backwards.
msg = rejects({}, model="claude-sonnet-9")
check("an unpriced DEFAULT model is rejected even with no overrides",
      bool(msg), True)
check("  and the message says it came from [extraction] model",
      "[extraction] model" in msg, True)

# Both problems at once are reported together. Exiting on the first turns one
# diagnosis into two runs, which is the same reasoning as require_artifacts.
msg = rejects({"vote": OTHER, "mdna": "claude-sonnet-9"})
check("several problems are reported in one message",
      ("'vote'" in msg, "claude-sonnet-9" in msg), (True, True))


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
