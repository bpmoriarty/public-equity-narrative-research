"""The orchestrator: stage order, the cost gate, and counts that add up.

Run:  uv run python tests/test_cli.py

WHY THIS FILE EXISTS
--------------------
`cli.py` decides two things that nothing downstream can check afterwards.

The first is ORDER. Every stage reads files an earlier stage wrote, and the
registry is the only statement of that order anywhere in the codebase. Get it
wrong and a stage runs against a manifest from the previous run — which does not
crash, because the file is there and it parses. The pipeline completes, reports
success, and describes filings it did not read. That failure has no downstream
detector, so the order is pinned here as an explicit list of
producer-before-consumer edges.

The second is MONEY. Two stages spend it, one of them by overwriting documents
that a re-run does not reproduce (CLAUDE.md rule 1). The gate that stands in
front of them has one job — do not spend without an explicit yes — and its
dangerous direction is silent: a gate that wrongly approves is indistinguishable
from a gate working correctly until the bill arrives. So the checks below drive
it through every answer that is not yes, including the one nobody types: a closed
stdin.

WHAT THIS FILE CANNOT COVER, SAID OUT LOUD
`--yes` against a genuinely stale document. That path ends in a real generation
call and about eight dollars, and there is no way to exercise it for free. What
is tested is that the CHAIN handles an approval correctly, with a fake gate
returning GATE_APPROVED — which proves the plumbing, not the gate's judgment.
PROJECT_STATUS Next Steps 27 carries this as an open item rather than letting the
coverage look complete.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from equity_research import cli  # noqa: E402

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")
        print(f"          got  {got!r}")
        print(f"          want {want!r}")


def raises(fn) -> bool:
    """True if calling `fn` raises SystemExit. The stages' failure convention."""
    try:
        fn()
    except SystemExit:
        return True
    return False


@contextlib.contextmanager
def quiet():
    """Swallow the orchestrator's own output while exercising it.

    Two reasons, and the second is not cosmetic. A full `run_chain` prints
    seventy lines of stage banners, so without this the check results are
    unreadable inside the noise. And the halting checks deliberately make a stage
    fail, which makes `run_chain` print "FAILED — exit 1" — a line that anything
    scanning this file's output for failures will read as a failed CHECK. That
    already happened once, to the fault-prover written for this very file: it
    reported a green suite as having one failure.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeRunner:
    """Stands in for run_stage. Records what was asked to run, returns codes."""

    def __init__(self, codes: dict[str, int] | None = None):
        self.codes = codes or {}
        self.calls: list[str] = []

    def __call__(self, stage, ticker) -> int:
        self.calls.append(stage.name)
        return self.codes.get(stage.name, 0)


class FakeGate:
    """Stands in for cost_gate. Records what it was asked about."""

    def __init__(self, verdicts: dict[str, str] | None = None,
                 default: str = cli.GATE_APPROVED):
        self.verdicts = verdicts or {}
        self.default = default
        self.asked: list[str] = []

    def __call__(self, stage, ticker, assume_yes) -> str:
        self.asked.append(stage.name)
        return self.verdicts.get(stage.name, self.default)


def chain(**kw):
    """run_chain over the real registry with fakes, returning (result, runner)."""
    runner = kw.pop("runner", None) or FakeRunner()
    gate = kw.pop("gate", None) or FakeGate()
    stages = kw.pop("stages", None) or list(cli.STAGES)
    with quiet():
        result = cli.run_chain(stages, "MORN", runner=runner, gate=gate, **kw)
    return result, runner, gate


# ---------------------------------------------------------------------------
print("THE REGISTRY — the only statement of stage order in the codebase")
# ---------------------------------------------------------------------------

names = [s.name for s in cli.STAGES]
check("thirteen stages", len(cli.STAGES), 13)
check("no stage is listed twice", len(set(names)), 13)
check("BY_NAME covers every stage", sorted(cli.BY_NAME), sorted(names))

missing = [n for n in names
           if not (ROOT / "src" / "equity_research" / f"{n}.py").exists()]
check("every stage names a module that exists", missing, [])

# `python -m` needs the guard; without it the module imports and does nothing,
# which looks exactly like a stage that had no work.
no_guard = [n for n in names
            if 'if __name__ == "__main__":' not in
            (ROOT / "src" / "equity_research" / f"{n}.py").read_text(
                encoding="utf-8")]
check("every stage module can be run with -m", no_guard, [])

spenders = [s.name for s in cli.STAGES if s.spends]
check("exactly the two stages that call a model are marked as spending",
      spenders, ["extract_facts", "generate_outputs"])

check("every spending stage carries a remedy for a non-zero exit",
      [s.name for s in cli.STAGES if s.spends and not s.remedy], [])

# Artifacts are CompanyPaths ATTRIBUTE NAMES, so a typo is silent until someone
# runs `status` — getattr would raise on a name that does not exist, and a name
# that exists but means something else would report the wrong file forever.
from equity_research.paths import paths as _paths  # noqa: E402

_P = _paths("MORN")
check("every stage declares what it leaves behind",
      [s.name for s in cli.STAGES if not s.artifacts], [])
check("every declared artifact is a real CompanyPaths attribute",
      [f"{s.name}:{a}" for s in cli.STAGES for a in s.artifacts
       if not hasattr(_P, a)], [])
check("  and resolves inside the company folder",
      [f"{s.name}:{a}" for s in cli.STAGES for a in s.artifacts
       if not str(getattr(_P, a)).startswith(str(_P.company))], [])

# ---------------------------------------------------------------------------
print()
print("ORDER — every consumer runs after the stage that writes what it reads")
# ---------------------------------------------------------------------------

# (producer, consumer, the artifact that makes this an edge). Each is a fact
# about the pipeline read off the modules' own path constants, not a guess:
# reordering the registry has to break one of these.
EDGES = [
    ("discover", "fetch", "discovery/inventory.json"),
    ("discover", "extract_facts", "discovery/inventory.json"),
    ("fetch", "extract_sections", "raw/fetch-manifest.json"),
    ("extract_sections", "triage_8k", "sections/sections-manifest.json"),
    ("extract_sections", "risk_diff", "sections/sections-manifest.json"),
    ("extract_sections", "extract_facts", "sections/sections-manifest.json"),
    ("triage_8k", "extract_facts", "triage/triage-8k.json"),
    ("extract_facts", "build_ledger", "ledger/facts/"),
    ("risk_diff", "build_ledger", "ledger/risk-deltas.json"),
    ("build_ledger", "merge_events", "ledger/FY*.json"),
    ("build_ledger", "build_pack", "ledger/FY*.json"),
    ("merge_events", "render_timeline", "pack/timeline-events.json"),
    ("build_pack", "generate_outputs", "pack/pack.json + index.json"),
    ("build_pack", "verify_outputs", "pack/pack.json + index.json"),
    ("generate_outputs", "verify_outputs", "output/*.md"),
    ("render_timeline", "verify_outputs", "output/timeline.md"),
    ("verify_outputs", "render_pdf", "it gates the render on the checks"),
]

# Guards the table itself: a renamed stage must break this, not be skipped.
unknown = sorted({n for a, b, _ in EDGES for n in (a, b)} - set(names))
check("every edge names a real stage", unknown, [])

position = {n: i for i, n in enumerate(names)}
# `.get(n, -1)` rather than `position[n]`: a fault that REMOVES a stage from the
# registry used to make this a KeyError, which killed the file and took the
# remaining sixty checks with it. A crash still fails the suite, but it fails it
# with a traceback instead of the name of what broke. A missing stage sorts to
# -1, so its edges read as violated and get reported.
violations = [f"{a} must precede {b} ({why})" for a, b, why in EDGES
              if position.get(a, -1) >= position.get(b, -1)]
check(f"all {len(EDGES)} producer-before-consumer edges hold", violations, [])

# The surprising one, pinned so nobody "fixes" the order to match it. build_pack
# reads the LEDGER and recomputes the merge in memory, so it does not depend on
# merge_events having run — the graph is not the straight line the list implies.
bp = (ROOT / "src" / "equity_research" / "build_pack.py").read_text(
    encoding="utf-8")
check("build_pack recomputes the merge rather than reading merge_events' file",
      "from equity_research.merge_events import timeline_block" in bp, True)

# ---------------------------------------------------------------------------
print()
print("THE CHILD ENVIRONMENT — how the company reaches a subprocess")
# ---------------------------------------------------------------------------

env = cli.child_env("MORN")
# `.get`, not `[...]`. Planting "the PYTHONUTF8 line is deleted" as a fault made
# this a KeyError, which killed the file before any other check ran — so the one
# thing the fault proved was that this file crashes rather than reports.
check("EQR_TICKER carries the company", env.get("EQR_TICKER"), "MORN")
check("PYTHONUTF8 is set", env.get("PYTHONUTF8"), "1")
check("the parent environment is inherited",
      all(k in env for k in list(os.environ)[:5]), True)
check("os.environ itself is not modified",
      os.environ.get("EQR_TICKER_PROBE"), None)

before = dict(os.environ)
cli.child_env("ZZZ")
check("building a child env twice leaves the process env alone",
      dict(os.environ), before)

cmd = cli.stage_command(cli.BY_NAME["build_pack"], "--estimate")
check("a stage command runs the module with -m", cmd[1:3], ["-m", "equity_research.build_pack"])
check("extra flags are passed through", cmd[-1], "--estimate")
check("the command uses this interpreter", cmd[0], sys.executable)

# ---------------------------------------------------------------------------
print()
print("SELECTION — --only and --from")
# ---------------------------------------------------------------------------

check("no arguments selects every stage",
      [s.name for s in cli.select(cli.STAGES, None, None)], names)
check("--only selects one",
      [s.name for s in cli.select(cli.STAGES, None, "build_pack")],
      ["build_pack"])
check("--from selects a suffix",
      [s.name for s in cli.select(cli.STAGES, "verify_outputs", None)],
      ["verify_outputs", "render_pdf"])
check("--only wins over --from",
      [s.name for s in cli.select(cli.STAGES, "discover", "render_pdf")],
      ["render_pdf"])
check("an unknown --only is fatal",
      raises(lambda: cli.select(cli.STAGES, None, "bulid_pack")), True)
check("an unknown --from is fatal",
      raises(lambda: cli.select(cli.STAGES, "nope", None)), True)

# ---------------------------------------------------------------------------
print()
print("THE COMPANY — checked before thirteen subprocesses fail one at a time")
# ---------------------------------------------------------------------------

check("a known ticker resolves", cli.resolve_company("MORN"), "MORN")
check("a lower-cased ticker resolves to the folder's own spelling",
      cli.resolve_company("morn"), "MORN")
check("an unknown ticker is fatal before anything runs",
      raises(lambda: cli.resolve_company("MRON")), True)

# ---------------------------------------------------------------------------
print()
print("ARGV — `pipeline MORN` means `pipeline run MORN`")
# ---------------------------------------------------------------------------

check("a bare ticker becomes a run", cli.normalise_argv(["MORN"]),
      ["run", "MORN"])
check("a ticker with flags becomes a run",
      cli.normalise_argv(["MORN", "--yes"]), ["run", "MORN", "--yes"])
check("an explicit subcommand is left alone",
      cli.normalise_argv(["run", "MORN"]), ["run", "MORN"])
check("`stages` is left alone", cli.normalise_argv(["stages"]), ["stages"])
check("an option is left alone for argparse to handle",
      cli.normalise_argv(["--help"]), ["--help"])
check("no arguments is left alone", cli.normalise_argv([]), [])
# Every subcommand must be in SUBCOMMANDS, or `pipeline status MORN` is read as
# `pipeline run status MORN` and dies on a company called "status".
parser = cli.build_parser()
check("`status` is not mistaken for a ticker",
      cli.normalise_argv(["status", "MORN"]), ["status", "MORN"])
check("`estimate` is not mistaken for a ticker",
      cli.normalise_argv(["estimate", "MORN"]), ["estimate", "MORN"])
check("SUBCOMMANDS lists every subcommand the parser accepts",
      sorted(cli.SUBCOMMANDS),
      sorted(k for a in parser._subparsers._group_actions
             for k in getattr(a, "choices", {}) or {}))

# ---------------------------------------------------------------------------
print()
print("COUNTS RECONCILE — rule 5, applied to the orchestrator itself")
# ---------------------------------------------------------------------------

result, runner, gate = chain()
check("a clean run runs every stage", len(runner.calls), 13)
check("in registry order", runner.calls, names)
check("  and counts them", len(result.ran), 13)
check("  and reconciles", result.reconciles(), True)
check("  and exits 0", result.exit_code(), 0)

# The check has to be able to fail, or it is decoration. A result that lost a
# stage must not reconcile.
lost = cli.ChainResult(selected=names, ran=names[:5])
check("a result that lost eight stages does NOT reconcile",
      lost.reconciles(), False)
check("  and says how many it accounted for", lost.accounted, 5)

double = cli.ChainResult(selected=names[:2], ran=names[:2],
                         skipped=[names[0]])
check("a result that counted a stage twice does NOT reconcile",
      double.reconciles(), False)

# ---------------------------------------------------------------------------
print()
print("HALTING — a failed stage stops the chain and the rest do not run")
# ---------------------------------------------------------------------------

result, runner, gate = chain(runner=FakeRunner({"triage_8k": 1}))
check("the failing stage is named", result.failed_at, "triage_8k")
check("stages before it ran", result.ran, ["discover", "fetch", "extract_sections"])
check("stages after it are recorded as not reached",
      len(result.not_reached), 9)
check("  and were never invoked",
      [c for c in runner.calls if c in result.not_reached], [])
check("  and the gate was never consulted for them", gate.asked, [])
check("the counts still reconcile", result.reconciles(), True)
check("exit code is 1", result.exit_code(), 1)

# ---------------------------------------------------------------------------
print()
print("THE COST GATE — nothing spends without an explicit yes")
# ---------------------------------------------------------------------------

# Nothing to do: the ordinary case. Not run, not prompted, not counted as work.
result, runner, gate = chain(gate=FakeGate(default=cli.GATE_NOTHING))
check("both spending stages were asked", gate.asked, spenders)
check("neither was run", [c for c in runner.calls if c in spenders], [])
check("they are recorded as having nothing to do",
      result.nothing_to_do, spenders)
check("  kept separate from --skip-spending's `skipped`", result.skipped, [])
check("the other eleven stages ran", len(result.ran), 11)
check("counts reconcile", result.reconciles(), True)
check("a run where nothing needed doing exits 0", result.exit_code(), 0)

# Declined: stop, spend nothing, and do not run the stage.
result, runner, gate = chain(
    gate=FakeGate({"extract_facts": cli.GATE_DECLINED}))
check("the declined stage is named", result.declined_at, "extract_facts")
check("it was NOT run", "extract_facts" in runner.calls, False)
check("the chain stopped there", len(result.not_reached), 7)
check("nothing after it ran",
      [c for c in runner.calls if c in result.not_reached], [])
check("counts reconcile", result.reconciles(), True)
check("exit code is 3, not 1 — nothing failed", result.exit_code(), 3)

# Approved: the plumbing, not the judgment. See the docstring.
result, runner, gate = chain(gate=FakeGate(default=cli.GATE_APPROVED))
check("an approved spending stage is actually run",
      [c for c in runner.calls if c in spenders], spenders)
check("  and counted as having run",
      all(s in result.ran for s in spenders), True)

# --skip-spending must not even ask: the gate shells two subprocesses, and the
# point of the flag is to spend nothing and wait for nothing.
result, runner, gate = chain(skip_spending=True)
check("--skip-spending does not consult the gate at all", gate.asked, [])
check("  and does not run the spending stages",
      [c for c in runner.calls if c in spenders], [])
check("  and records them as skipped", result.skipped, spenders)
check("  and reconciles", result.reconciles(), True)

# A dry run must not prompt, and must not claim it would have been approved.
result, runner, gate = chain(dry_run=True)
check("--dry-run runs nothing", runner.calls, [])
check("  and asks nothing", gate.asked, [])
check("  and still accounts for all thirteen stages", result.reconciles(), True)

# ---------------------------------------------------------------------------
print()
print("CONFIRMATION — anything that is not yes is no")
# ---------------------------------------------------------------------------


def answer(text):
    """Patch input() to return `text`; a BaseException class to raise it."""
    real = builtins.input

    def fake(_prompt=""):
        if isinstance(text, type) and issubclass(text, BaseException):
            raise text()
        return text
    builtins.input = fake
    try:
        with quiet():
            return cli.confirm("spend?")
    finally:
        builtins.input = real


check("y approves", answer("y"), True)
check("yes approves", answer("yes"), True)
check("Y approves", answer("Y"), True)
check("  and surrounding whitespace does not matter", answer("  y  "), True)
check("n declines", answer("n"), False)
check("an empty answer declines", answer(""), False)
check("'maybe' declines", answer("maybe"), False)
# The one that matters. A piped or closed stdin raises EOFError, and reading that
# as consent is how an unattended run spends money.
check("a closed stdin declines rather than approving", answer(EOFError), False)

# ---------------------------------------------------------------------------
print()
print("GATE ORDER — the estimate is only priced when there is work")
# ---------------------------------------------------------------------------

shown: list[str] = []
real_probe, real_estimate = cli.probe_stage, cli.show_estimate
try:
    cli.show_estimate = lambda stage, ticker: shown.append(stage.name)

    cli.probe_stage = lambda stage, ticker: cli.CHECK_FRESH_NOTHING
    with quiet():
        verdict = cli.cost_gate(cli.BY_NAME["generate_outputs"], "MORN", False)
    check("a stage with nothing to do returns 'nothing'", verdict,
          cli.GATE_NOTHING)
    check("  and is never priced", shown, [])

    cli.probe_stage = lambda stage, ticker: cli.CHECK_FRESH_WORK
    with quiet():
        verdict = cli.cost_gate(cli.BY_NAME["generate_outputs"], "MORN", True)
    check("--yes approves without asking", verdict, cli.GATE_APPROVED)
    check("  but the estimate is still shown first", shown,
          ["generate_outputs"])

    # A probe that cannot answer must fall to "there is work". The other
    # direction silently skips a stage that had something to do.
    shown.clear()
    cli.probe_stage = lambda stage, ticker: None
    with quiet():
        verdict = cli.cost_gate(cli.BY_NAME["extract_facts"], "MORN", True)
    check("an unanswerable probe is treated as work, not as nothing",
          verdict, cli.GATE_APPROVED)
    check("  and is priced", shown, ["extract_facts"])
finally:
    cli.probe_stage, cli.show_estimate = real_probe, real_estimate

# ---------------------------------------------------------------------------
print()
print("THE FLUSH BEFORE EACH SPAWN — a redirected log must stay in order")
# ---------------------------------------------------------------------------

# The child inherits this process's stdout and writes to it immediately, while
# our own prints sit in a block buffer whenever stdout is not a terminal. Without
# a flush first, `pipeline MORN > run.log` records thirteen stages of output
# followed by thirteen headers. Found by piping a real run.
order: list[str] = []
real_run, real_flush = cli.subprocess.run, sys.stdout.flush
try:
    class Done:
        returncode = 0

    cli.subprocess.run = lambda *a, **k: order.append("spawn") or Done()
    sys.stdout.flush = lambda: order.append("flush")
    cli.run_stage(cli.BY_NAME["build_pack"], "MORN")
finally:
    cli.subprocess.run, sys.stdout.flush = real_run, real_flush

check("stdout is flushed before the child is spawned",
      order[:2], ["flush", "spawn"])

# ---------------------------------------------------------------------------
print()
print("STATUS — reports what is there, and does not guess at freshness")
# ---------------------------------------------------------------------------

check("a missing artifact is reported as absent",
      cli.describe(_P.company / "no-such-file.json"), "absent")
check("a real file is reported by size",
      cli.describe(_P.inventory).endswith("KB"), True)
check("a directory is reported by file count",
      "file(s)" in cli.describe(_P.facts), True)

# The two spending stages are the only ones that can answer for themselves, so
# they are the only ones `status` may speak for. If a third stage ever gains a
# --check-fresh, this is the check that says so.
probed = [s.name for s in cli.STAGES if s.spends]
check("only the spending stages are asked to report on themselves",
      probed, ["extract_facts", "generate_outputs"])

# `estimate` prices a stage with nothing outstanding by forcing it — otherwise
# extract_facts returns before printing any figure and the summary claims a
# number that is not on screen.
priced: list[tuple[str, tuple]] = []
real_probe, real_estimate = cli.probe_stage, cli.show_estimate
try:
    cli.show_estimate = lambda stage, ticker, *extra: priced.append(
        (stage.name, extra))
    cli.probe_stage = lambda stage, ticker: cli.CHECK_FRESH_NOTHING
    with quiet():
        cli.cmd_estimate(type("A", (), {"ticker": "MORN"})())
    check("with nothing outstanding, both stages are priced with --force",
          priced, [("extract_facts", ("--force",)),
                   ("generate_outputs", ("--force",))])

    priced.clear()
    cli.probe_stage = lambda stage, ticker: cli.CHECK_FRESH_WORK
    with quiet():
        cli.cmd_estimate(type("A", (), {"ticker": "MORN"})())
    check("with real work, the estimate is NOT forced — it must quote the "
          "amount about to be spent",
          priced, [("extract_facts", ()), ("generate_outputs", ())])
finally:
    cli.probe_stage, cli.show_estimate = real_probe, real_estimate

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
