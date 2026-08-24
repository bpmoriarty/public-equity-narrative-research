"""The `pipeline` command: run every stage for one company, in order.

WHAT THIS IS
------------
Thirteen stages turn a ticker into three documents. Run by hand that is thirteen
commands in an order you have to remember, and the order is not guessable — one
stage reads a manifest another wrote four stages earlier. This module holds that
order once, as data, and walks it.

    uv run pipeline MORN            # every stage, in order
    uv run pipeline stages          # what the stages are, without running them

WHY A SUBPROCESS PER STAGE
--------------------------
Each stage is already a working program with its own `main()`, its own argparse,
and its own idea of what counts as fatal. Importing them and calling `main()`
in-process would mean either rewriting thirteen `main()` signatures to return an
exit code, or catching `SystemExit` around each call and hoping none of them
left global state behind.

Running them as `python -m equity_research.<stage>` costs an interpreter start
(about a fifth of a second) and buys three things outright:

  1. **Failure reporting for free.** Every stage signals fatal errors with
     `sys.exit("message")`, which is exit code 1 with the message on stderr.
     A subprocess exit code is the whole contract; nothing here has to know how
     a particular stage decided to give up.
  2. **Real isolation.** A stage that leaves a module-level cache populated, or
     reconfigures `sys.stdout`, cannot affect the next one.
  3. **The stages stay runnable by hand.** Nothing in this file is a new entry
     point into them. `uv run python -m equity_research.build_pack` does exactly
     what this orchestrator does to `build_pack`, which means a stage can be
     debugged on its own and the orchestrated run is not a separate code path
     that can drift.

Child stdout and stderr are inherited rather than captured, so output appears
live and in the order the stage produced it. Capturing would buffer a
twelve-minute stage into silence and then a wall of text.

The child's working directory is inherited too, deliberately: a stage run
through here behaves identically to the same stage run by hand from the same
place. `ROOT` comes from `_bootstrap.py` (computed from `__file__`), so no path
depends on the working directory anyway — but the `claude_code` backend's cost
was *measured* against a particular working directory, and silently changing it
for the two stages that spend money would make the orchestrated run cost
something different from the hand run.

HOW THE ORDER WAS DERIVED
-------------------------
Not from the plan. Each stage's module-level path constants say what it reads
and what it writes, and the order below is a topological sort of that. Two
results are worth knowing because they are not obvious:

  - `build_pack` does NOT depend on `merge_events` having run. It imports
    `timeline_block()` and recomputes the merge in memory from the ledger. The
    chain is not a straight line, even though this list is.
  - `render_timeline` DOES depend on `merge_events`, because it reads the
    `pack/timeline-events.json` file that stage writes.

So the sequence below is *a* valid order, not the only one. What matters is that
every stage comes after the stages whose files it reads.

WHAT HAPPENS AT A STAGE THAT SPENDS MONEY
-----------------------------------------
Two stages make model calls: `extract_facts` and `generate_outputs`. Each goes
through a gate that asks the stage two questions, in this order, and spends
nothing to ask either:

  1. Have you anything to do?   `<stage> --check-fresh`  -> exit 0 or 4
  2. What would it cost?        `<stage> --estimate`     -> printed verbatim

Only then is anyone asked to approve it. Question 1 is what keeps the gate from
being a nuisance: on a cached re-run both stages answer "nothing", so a full
`pipeline MORN` neither prompts nor spends, which is the ordinary case. The
prompt appears only when something has actually changed.

Both questions are answered BY THE STAGE. The alternative was for this file to
read the stages' output looking for "nothing to do", which makes an orchestrator
depend on the wording of other programs' print statements.

The care here is aimed at `generate_outputs` specifically. It has no cache of
its own beyond that freshness check, it regenerates both prose documents at
roughly eight dollars, and those documents are the one artifact here that a
re-run does not reproduce (CLAUDE.md rule 1). An unattended run must not be able
to destroy them, so an unanswerable prompt — a closed or piped stdin — counts as
"no", never as consent.

`--yes` approves the gates in advance; the stages still run only if they have
work. `--skip-spending` steps over them without asking even when they do have
work, and they are reported as skipped and counted, never dropped silently.

EXIT CODES
----------
    0   every selected stage completed, or had nothing to do
    1   a stage failed; the chain stopped there
    3   a cost gate was not approved; the chain stopped there. Nothing spent.

3 rather than another 1 because "a stage is broken" and "there is a decision
for you to make" need different answers from whatever is reading the code.

This module writes no files. Every artifact is written by the stage that owns
it, which is what keeps `pipeline run` and thirteen hand-run commands the same
operation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field

from equity_research.paths import known_tickers, paths, resolve_ticker


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Stage:
    """One pipeline stage. Frozen: the registry is a fact, not state."""

    name: str

    # What the stage leaves behind, for the running commentary. Deliberately
    # phrased as an artifact rather than an action ("the filing inventory", not
    # "discovers filings"), because that is what the next stage needs and what
    # a reader is looking for when a stage fails.
    produces: str

    # True for the two stages that make model calls. Read by `run_chain`, and
    # the only thing standing between an unattended run and CLAUDE.md rule 1.
    spends: bool = False

    # Printed when this stage exits non-zero. Stages here fail for known,
    # actionable reasons, and a generic "stage failed" wastes the fact that we
    # know which stage it was.
    remedy: str = ""

    # What `pipeline status` looks at, as CompanyPaths ATTRIBUTE NAMES —
    # ("inventory",), not ("data/discovery/inventory.json",).
    #
    # Names rather than path strings for two reasons. A "data/..." literal here
    # would resolve against the repository root instead of the company being
    # run, which is the failure the path-literal lint in
    # tests/test_repo_hygiene.py exists to catch — and it does catch it, which is
    # how four missing CompanyPaths properties were found while writing `status`.
    # And it keeps the answer to "where does this live" in paths.py, where the
    # rest of the pipeline reads it from.
    artifacts: tuple[str, ...] = ()


# Dependency order. See HOW THE ORDER WAS DERIVED in the module docstring —
# every stage sits after the stages whose files it reads.
STAGES: tuple[Stage, ...] = (
    Stage("discover",
          "the filing inventory and gap analysis",
          artifacts=("inventory",)),
    Stage("fetch",
          "cached filing documents and the fetch manifest",
          artifacts=("fetch_manifest", "raw")),
    Stage("extract_sections",
          "the target sections as cleaned text, and their manifest",
          artifacts=("sections_manifest", "sections")),
    Stage("triage_8k",
          "a judgment on every conditional 7.01/8.01 8-K",
          artifacts=("triage_json",)),
    Stage("risk_diff",
          "year-over-year risk factor deltas",
          artifacts=("risk_deltas",)),
    Stage("extract_facts",
          "per-task extraction results in the facts cache",
          spends=True,
          artifacts=("facts",),
          remedy="A non-zero exit here is often NOT a crash. This stage stops "
                 "deliberately when a cached result's source text has changed "
                 "since it was extracted, because a stale result answers a "
                 "question about a document that no longer exists in that "
                 "form.\n"
                 "  Read the stage's own output above: if it listed stale "
                 "results, rebuild them with --refresh-stale (this COSTS "
                 "TOKENS), or leave them and accept the gap knowingly."),
    Stage("build_ledger",
          "the per-year ledger, every quote verified",
          artifacts=("ledger",)),
    Stage("merge_events",
          "merged timeline events, with duplicates and undated rows split out",
          artifacts=("timeline_events",)),
    Stage("render_timeline",
          "output/timeline.md — deliverable 1 of 3",
          artifacts=("timeline_md",)),
    Stage("build_pack",
          "the citable pack and its id index",
          artifacts=("pack",)),
    Stage("generate_outputs",
          "narrative-brief.md and discussion-points.md — deliverables 2 and 3",
          spends=True,
          # `output` also holds timeline.md, so the file count here is coarser
          # than this stage. That is fine: for a spending stage `status` reports
          # the stage's own --check-fresh verdict, which is exact.
          artifacts=("output",),
          remedy="If this failed part way, the documents on disk may be from "
                 "the previous run. It will not silently regenerate them — it "
                 "compares each document's stamped pack sha against the pack on "
                 "disk first — so re-run it and read what it says about each "
                 "one before trusting either."),
    Stage("verify_outputs",
          "verify-report.md, and a non-zero exit if any hard check failed",
          artifacts=("verify_report",),
          remedy="The deliverables did not pass their own checks. This gates "
                 "the PDF render on purpose — see the stage output above for "
                 "which check failed, and generate_outputs' --fix-* flags for "
                 "the repair passes."),
    Stage("render_pdf",
          "the three deliverables as PDF, each read back and verified",
          artifacts=("pdf",)),
)

BY_NAME = {s.name: s for s in STAGES}


# ---------------------------------------------------------------------------
# Running one stage
# ---------------------------------------------------------------------------

def child_env(ticker: str) -> dict[str, str]:
    """The environment a stage subprocess runs in.

    Inherits everything — the stages need `EDGAR_IDENTITY`, `ANTHROPIC_API_KEY`
    and `PATH`, and `.env` is loaded by each stage's own `_bootstrap` import —
    and adds two variables.

    `EQR_TICKER` is how the company reaches the child. It cannot be passed as
    `--ticker` from here, or rather it could, but the environment variable is
    the mechanism `paths.py` was built for: it reads the ticker at *import*
    time, before argparse runs, because the stages' module-level path constants
    need it by then.

    `PYTHONUTF8=1` is the last open item from Phase 0. Measured, it changes
    nothing observable in the stages as they stand: all fourteen already
    reconfigure their own stdout and stderr to UTF-8, and every `open()` in the
    package either passes `encoding="utf-8"` or opens in binary mode for
    tomllib. It is set anyway, because "nothing depends on the platform default
    encoding" is a property that has to be re-verified on every future edit,
    and this makes it true by construction instead.
    """
    env = dict(os.environ)
    env["EQR_TICKER"] = ticker
    env["PYTHONUTF8"] = "1"
    return env


def stage_command(stage: Stage, *flags: str) -> list[str]:
    """The argv for a stage. `sys.executable`, so the venv python is used."""
    return [sys.executable, "-m", f"equity_research.{stage.name}", *flags]


# ---------------------------------------------------------------------------
# The cost gate
# ---------------------------------------------------------------------------
#
# Two stages spend money. Neither is allowed to run unattended, and neither is
# allowed to be interrupted for nothing. That needs two questions answered in
# order, and both are answered BY THE STAGE, not by this file:
#
#   1. Is there anything to do?   `<stage> --check-fresh`  -> exit 0 or 4
#   2. What would it cost?        `<stage> --estimate`     -> printed verbatim
#
# The probe is an exit code rather than prose on purpose. The alternative was
# for this file to read the stage's output and look for "nothing to do", which
# makes an orchestrator depend on the wording of thirteen other programs'
# print statements.
#
# Question 1 is what stops the gate being a nuisance. On a cached re-run both
# stages answer "nothing", so a full `pipeline MORN` never prompts at all and
# never spends -- which is the ordinary case. The prompt appears only when
# something has actually changed.
#
# Neither probe nor estimate makes a model call, so reaching the prompt has
# already cost nothing.

CHECK_FRESH_NOTHING = 0    # the stage has nothing outstanding
CHECK_FRESH_WORK = 4       # the stage has work, and it costs money


def probe_stage(stage: Stage, ticker: str) -> int | None:
    """Ask a spending stage whether it has anything to do.

    Returns the raw exit code, or None if the stage could not answer -- which is
    treated as "assume there is work", never as "assume there is none".
    """
    sys.stdout.flush()
    proc = subprocess.run(stage_command(stage, "--check-fresh"),
                          env=child_env(ticker), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    # The probe's own words are worth showing: "3 task(s) outstanding" or "both
    # documents are written from the pack on disk" is the reason the gate is
    # about to appear, or not.
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.strip():
            print(f"         {line.rstrip()}")
    if proc.returncode in (CHECK_FRESH_NOTHING, CHECK_FRESH_WORK):
        return proc.returncode
    return None


def show_estimate(stage: Stage, ticker: str, *extra: str) -> None:
    """Print the stage's own cost estimate, verbatim and unparsed.

    `extra` exists for one case: `extract_facts --estimate` returns before
    pricing anything when every task is cached, so asking it what a forced
    re-run would cost needs `--force` as well. Without that, `pipeline estimate`
    printed "this is what a forced re-run would cost" above no figures at all.
    """
    sys.stdout.flush()
    subprocess.run(stage_command(stage, "--estimate", *extra),
                   env=child_env(ticker))
    sys.stdout.flush()


def confirm(question: str) -> bool:
    """Ask the operator. Anything but an explicit yes is a no.

    A closed or piped stdin raises EOFError rather than blocking, and that is
    read as "no" and said out loud. The alternative -- treating an unanswerable
    question as consent -- is how an unattended run spends money.
    """
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        print()
        print("         stdin is not interactive, so nothing approved it. "
              "Pass --yes to approve in advance.")
        return False
    return answer in ("y", "yes")


GATE_NOTHING = "nothing"     # the stage has no work; do not run it
GATE_APPROVED = "approved"   # run it
GATE_DECLINED = "declined"   # stop the chain, spend nothing


def cost_gate(stage: Stage, ticker: str, assume_yes: bool) -> str:
    """Decide whether a spending stage runs. Spends nothing itself.

    The order matters. The probe comes first so that an up-to-date pipeline is
    never interrupted to approve work that does not exist, and the estimate is
    only printed when there is something to price.

    A probe that cannot answer is treated as "there is work". The failure mode
    that direction is an unnecessary prompt; the other direction silently skips
    a stage that had something to do, which is the failure this whole gate is
    here to prevent.
    """
    verdict = probe_stage(stage, ticker)

    if verdict == CHECK_FRESH_NOTHING:
        return GATE_NOTHING

    if verdict is None:
        print(f"         (the stage could not say whether it has work; "
              f"assuming it does)")

    print()
    show_estimate(stage, ticker)
    print()

    if assume_yes:
        print(f"         --yes: approved without asking")
        return GATE_APPROVED

    return (GATE_APPROVED
            if confirm(f"         Run {stage.name} and spend the above?")
            else GATE_DECLINED)


def run_stage(stage: Stage, ticker: str) -> int:
    """Run one stage to completion; return its exit code.

    stdout and stderr are inherited, not captured — see the module docstring.

    THE FLUSH IS LOAD-BEARING. The child inherits this process's stdout handle
    and writes to it directly and immediately. Our own `print()` calls go
    through Python's buffer, which is line-buffered only when stdout is a
    terminal — redirect the run to a file (`pipeline MORN > run.log`) and the
    buffer switches to block mode, so every header we printed is still sitting
    in memory while the child writes underneath it. The log then reads as
    thirteen stages of output followed by thirteen headers, in an order that
    never happened.

    Found by piping a real run through `Select-Object`, which is exactly the
    shape of what a colleague saving a log would do.

    One flush, before the spawn, is enough: it is the only moment at which
    anything of ours is pending and something else is about to write. The
    stage's own "ok" line and the next stage's header are both flushed by the
    next spawn, and the final summary by interpreter exit.
    """
    sys.stdout.flush()
    proc = subprocess.run(stage_command(stage), env=child_env(ticker))
    return proc.returncode


# ---------------------------------------------------------------------------
# Running the chain
# ---------------------------------------------------------------------------

@dataclass
class ChainResult:
    """What a chain run did, in numbers that have to add up.

    CLAUDE.md rule 5: counts reconcile across every stage boundary. A summary
    saying "5 stages succeeded" describes what was attempted, not what a
    thirteen-stage pipeline did. Every selected stage lands in exactly one of
    these, and `reconciles()` is checked before the summary is believed.
    """

    selected: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # Spending stages the gate asked about and found nothing to do. Kept apart
    # from `skipped`, which means "you told me not to": one is the pipeline
    # being up to date, the other is an instruction. Reporting them together
    # would hide the ordinary case inside a flag.
    nothing_to_do: list[str] = field(default_factory=list)
    not_reached: list[str] = field(default_factory=list)
    failed_at: str | None = None
    declined_at: str | None = None

    @property
    def accounted(self) -> int:
        """How many selected stages have an outcome recorded."""
        return (len(self.ran) + len(self.skipped) + len(self.nothing_to_do)
                + len(self.not_reached)
                + (1 if self.failed_at else 0) + (1 if self.declined_at else 0))

    def reconciles(self) -> bool:
        return self.accounted == len(self.selected)

    def exit_code(self) -> int:
        if self.failed_at:
            return 1
        if self.declined_at:
            return 3
        return 0


def select(stages: tuple[Stage, ...], first: str | None,
           only: str | None) -> list[Stage]:
    """The stages to walk: all of them, one of them, or a suffix from `first`.

    `--from` exists so a chain that stopped can be resumed from where it
    stopped — a declined gate, or a stage that failed and has since been fixed —
    without re-walking the stages that already succeeded.
    """
    if only:
        if only not in BY_NAME:
            raise SystemExit(unknown_stage(only))
        return [BY_NAME[only]]
    if first:
        if first not in BY_NAME:
            raise SystemExit(unknown_stage(first))
        start = [s.name for s in stages].index(first)
        return list(stages[start:])
    return list(stages)


def unknown_stage(name: str) -> str:
    return (f"FATAL: no stage named {name!r}.\n"
            f"Known stages, in order:\n"
            + "\n".join(f"  {s.name}" for s in STAGES))


def run_chain(stages: list[Stage], ticker: str, *, runner=run_stage,
              skip_spending: bool = False, assume_yes: bool = False,
              gate=None, dry_run: bool = False) -> ChainResult:
    """Walk the stages in order. Stop at the first failure or declined gate.

    `runner` is injected so the chain's own logic — ordering, halting, counting
    — can be tested without launching thirteen subprocesses. It takes
    `(stage, ticker)` and returns an exit code, exactly like `run_stage`.

    `gate` is injected for the same reason: the real one launches two
    subprocesses and reads stdin, neither of which belongs in a test of whether
    the chain counted correctly. It takes `(stage, ticker, assume_yes)` and
    returns one of the GATE_* verdicts below.
    """
    result = ChainResult(selected=[s.name for s in stages])
    total = len(stages)
    gate = cost_gate if gate is None else gate

    for i, stage in enumerate(stages):
        remaining = [s.name for s in stages[i + 1:]]

        if stage.spends and skip_spending:
            print(f"[{i + 1:2d}/{total}] {stage.name} — SKIPPED "
                  f"(spends tokens; --skip-spending)")
            result.skipped.append(stage.name)
            continue

        if stage.spends and not dry_run:
            print()
            print("-" * 72)
            print(f"[{i + 1:2d}/{total}] {stage.name} — {stage.produces}")
            print(f"         This stage makes model calls. Checking whether it "
                  f"has anything to do.")
            print("-" * 72)
            verdict = gate(stage, ticker, assume_yes)

            if verdict == GATE_NOTHING:
                print(f"         nothing to do — not run, nothing spent")
                result.nothing_to_do.append(stage.name)
                continue

            if verdict == GATE_DECLINED:
                print()
                print(f"         not approved — stopping here. Nothing spent.")
                print(f"         Resume when you are ready:")
                print(f"           uv run pipeline {ticker} --from {stage.name}")
                if remaining:
                    print(f"         Or continue past it:")
                    print(f"           uv run pipeline {ticker} "
                          f"--from {remaining[0]}")
                result.declined_at = stage.name
                result.not_reached = remaining
                return result

            # Approved. Fall through to the ordinary run below.
            print()
            print(f"         approved — running {stage.name}")

        elif stage.spends and dry_run:
            # A dry run must not prompt, and must not pretend it would have been
            # approved either. It reports that the gate is where a decision
            # happens and counts the stage as reached.
            print()
            print(f"[{i + 1:2d}/{total}] {stage.name} — would ask before running "
                  f"(spends money)")
            result.ran.append(stage.name)
            continue

        print()
        print("-" * 72)
        print(f"[{i + 1:2d}/{total}] {stage.name} — {stage.produces}")
        print(f"         python -m equity_research.{stage.name}")
        print("-" * 72)

        if dry_run:
            print("         (--dry-run: not executed)")
            result.ran.append(stage.name)
            continue

        started = time.monotonic()
        code = runner(stage, ticker)
        took = time.monotonic() - started

        if code != 0:
            print()
            print(f"         FAILED — exit {code} after {took:,.1f}s")
            if stage.remedy:
                print(f"         {stage.remedy}")
            result.failed_at = stage.name
            result.not_reached = remaining
            return result

        print(f"         ok ({took:,.1f}s)")
        result.ran.append(stage.name)

    return result


def print_summary(result: ChainResult, ticker: str) -> None:
    """The reconciled count. See ChainResult for why it is spelled out."""
    print()
    print("=" * 72)
    print(f"pipeline — {ticker}")
    print(f"  registry        : {len(STAGES)} stages")
    print(f"  selected        : {len(result.selected)}")
    print(f"  ran             : {len(result.ran)}")
    if result.nothing_to_do:
        print(f"  nothing to do   : {len(result.nothing_to_do)}  "
              f"({', '.join(result.nothing_to_do)})")
    if result.skipped:
        print(f"  skipped         : {len(result.skipped)}  "
              f"({', '.join(result.skipped)})")
    if result.failed_at:
        print(f"  FAILED at       : {result.failed_at}")
    if result.declined_at:
        print(f"  not approved    : {result.declined_at}  (nothing spent)")
    if result.not_reached:
        print(f"  not reached     : {len(result.not_reached)}  "
              f"({', '.join(result.not_reached)})")

    if not result.reconciles():
        # An orchestrator whose own counts do not add up is reporting on a run
        # it did not actually track. Louder than the failure it is describing.
        print()
        print(f"  *** COUNTS DO NOT RECONCILE: {result.accounted} outcomes "
              f"recorded for {len(result.selected)} selected stages. This is a "
              f"bug in cli.py, not in the stages. ***")


# ---------------------------------------------------------------------------
# Ticker resolution
# ---------------------------------------------------------------------------

def resolve_company(explicit: str | None) -> str:
    """The company to operate on, verified to exist on disk.

    `resolve_ticker` handles precedence (argument, then `EQR_TICKER`, then the
    single company) and upper-cases the result, but it does not check that the
    folder exists — nothing before now needed it to, because a stage run by
    hand fails on its first missing file.

    Here it is worth checking up front. Without it, `pipeline MRON` launches
    thirteen subprocesses that each fail separately on a company folder that
    was never there, and the first useful line of output is thirteen stack
    traces down.
    """
    ticker = resolve_ticker(explicit)
    # Compared case-insensitively against the folder names, and the folder's
    # own spelling is what gets passed on: `resolve_ticker` upper-cases, and a
    # company directory is not required to be upper-case.
    known = {t.upper(): t for t in known_tickers()}
    if ticker.upper() not in known:
        raise SystemExit(
            f"FATAL: no company folder for {ticker!r}.\n"
            f"Looked for companies/{ticker}/ .\n"
            + (f"Known companies: {', '.join(sorted(known.values()))}"
               if known else
               "No company folders exist yet."))
    return known[ticker.upper()]


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_stages(args: argparse.Namespace) -> int:
    """Print the registry. Runs nothing, needs no company."""
    print(f"{len(STAGES)} stages, in dependency order:")
    print()
    for i, s in enumerate(STAGES, 1):
        flag = "  $$" if s.spends else "    "
        print(f"{flag} {i:2d}. {s.name:18s} {s.produces}")
    print()
    print("  $$ marks the stages that make model calls. `pipeline run` asks "
          "each of them\n     whether it has work, shows what it would cost, "
          "and asks before running it.")
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
#
# WHAT THIS COMMAND WILL NOT TELL YOU, AND WHY
# Whether a deterministic stage's output is up to date. It cannot: eleven of the
# thirteen stages have no way to answer that without doing their work, and the
# tempting substitute — comparing modification times — is wrong here. Every
# stage's own staleness logic is content-based (`extract_facts` fingerprints the
# source text; `generate_outputs` compares a stamped pack hash), precisely
# because an mtime says when a file was written and not what it was written
# from. A `status` that guessed from mtimes would contradict the stages on the
# cases that matter and agree with them everywhere else, which is the worst
# available combination.
#
# So: presence and size are reported as presence and size, the two stages that
# CAN answer are asked, and the header says which is which. `pipeline run` is
# what finds out; this is what you read first.

def describe(path) -> str:
    """One line about one artifact: what is there, not whether it is current."""
    if not path.exists():
        return "absent"
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        return f"{len(files):,} file(s), {size / 1_048_576:.1f} MB"
    return f"{path.stat().st_size / 1024:,.0f} KB"


def cmd_status(args: argparse.Namespace) -> int:
    ticker = resolve_company(args.ticker)
    P = paths(ticker)

    print(f"pipeline status — {ticker}")
    print(f"  {P.company.relative_to(P.root).as_posix()}")
    print()
    print("  Presence and size only. Whether a deterministic stage needs "
          "re-running is not")
    print("  something this can answer — see the note above `describe` in "
          "cli.py. The two")
    print("  stages that spend money answer for themselves, below.")
    print()

    for i, stage in enumerate(STAGES, 1):
        marks = []
        for name in stage.artifacts:
            path = getattr(P, name)
            marks.append(f"{path.relative_to(P.company).as_posix()}: "
                         f"{describe(path)}")
        flag = "$$" if stage.spends else "  "
        head = f"  {flag} {i:2d}. {stage.name:18s} "
        print(head + (marks[0] if marks else "—"))
        for extra in marks[1:]:
            # Indented to the width of the header rather than a hand-counted
            # string, which was one character out.
            print(" " * len(head) + extra)

    # The authoritative part. Asking costs nothing and constructs no backend.
    print()
    print("  The stages that spend money, in their own words:")
    for stage in (s for s in STAGES if s.spends):
        print(f"    {stage.name}")
        verdict = probe_stage(stage, ticker)
        if verdict == CHECK_FRESH_NOTHING:
            print(f"         -> nothing to do")
        elif verdict == CHECK_FRESH_WORK:
            print(f"         -> HAS WORK. `pipeline {ticker}` will show the "
                  f"cost and ask.")
        else:
            print(f"         -> could not say; `pipeline {ticker}` will treat "
                  f"that as work")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    """What the spending stages would cost, and whether they would run at all.

    Deliberately prints the price EVEN WHEN there is nothing to do — which is the
    opposite of what the gate does, for a reason. At the gate an unasked-for
    price reads as an imminent charge. Here the price is the question, so the
    honest answer is "this is what it would cost, and here is whether you would
    actually be charged it."

    Spends nothing: `--estimate` and `--check-fresh` both make no model call.
    """
    ticker = resolve_company(args.ticker)
    spenders = [s for s in STAGES if s.spends]

    print(f"pipeline estimate — {ticker}")
    print(f"  {len(spenders)} of {len(STAGES)} stages can spend money. "
          f"Nothing below makes a model call.")

    outstanding = []
    for stage in spenders:
        print()
        print("-" * 72)
        print(f"{stage.name} — {stage.produces}")
        print("-" * 72)
        verdict = probe_stage(stage, ticker)
        print()
        if verdict == CHECK_FRESH_WORK or verdict is None:
            outstanding.append(stage.name)
            # There is real work, so the stage's own estimate already describes
            # exactly it. Do not force: forcing would quote a bigger number than
            # the one about to be spent.
            show_estimate(stage, ticker)
        else:
            # Nothing outstanding, so an unforced estimate prices nothing. The
            # question this command answers is "what would it cost", so ask for
            # the whole job and label it as hypothetical in the summary.
            show_estimate(stage, ticker, "--force")

    print()
    print("=" * 72)
    if outstanding:
        print(f"  {len(outstanding)} stage(s) have work: "
              f"{', '.join(outstanding)}")
        print(f"  `uv run pipeline {ticker}` will show each cost again and ask "
              f"before spending it.")
    else:
        print(f"  Nothing outstanding. The figures above are what a forced "
              f"re-run would cost;")
        print(f"  `uv run pipeline {ticker}` would spend nothing.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ticker = resolve_company(args.ticker)
    stages = select(STAGES, args.start_from, args.only)

    print(f"pipeline run — {ticker}")
    print(f"  {len(stages)} of {len(STAGES)} stages"
          + (f", from {args.start_from}" if args.start_from else "")
          + (f", only {args.only}" if args.only else ""))
    if args.dry_run:
        print("  --dry-run: commands are printed, nothing is executed")

    result = run_chain(stages, ticker, skip_spending=args.skip_spending,
                       assume_yes=args.assume_yes, dry_run=args.dry_run)
    print_summary(result, ticker)
    return result.exit_code()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUBCOMMANDS = ("run", "stages", "status", "estimate")


def normalise_argv(argv: list[str]) -> list[str]:
    """Let `pipeline MORN` mean `pipeline run MORN`.

    The ticker is the thing anyone actually wants to type, and `run` is the
    only subcommand that takes one. Anything that is not a known subcommand and
    does not look like an option is treated as a ticker for `run`.
    """
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        return ["run", *argv]
    return argv


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="pipeline",
        description="Run the filing pipeline for one company.",
        epilog="exit codes: 0 complete, 1 a stage failed, 3 stopped at a "
               "stage that spends money (nothing spent)")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the stages in order")
    r.add_argument("ticker", nargs="?", default=None,
                   help="company to run. Defaults to $EQR_TICKER, or to the "
                        "single company under companies/ when there is one.")
    r.add_argument("--from", dest="start_from", metavar="STAGE",
                   help="start at this stage and continue to the end")
    r.add_argument("--only", metavar="STAGE", help="run just this one stage")
    r.add_argument("--yes", "-y", dest="assume_yes", action="store_true",
                   help="approve the cost gates in advance. The stages still "
                        "run only if they have work to do.")
    r.add_argument("--skip-spending", action="store_true",
                   help="step over the stages that make model calls without "
                        "asking, even if they have work to do")
    r.add_argument("--dry-run", action="store_true",
                   help="print the stage commands without executing any")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("stages", help="list the stages and exit")
    s.set_defaults(func=cmd_stages)

    st = sub.add_parser("status",
                        help="what exists on disk for a company, and what the "
                             "two spending stages say about themselves")
    st.add_argument("ticker", nargs="?", default=None,
                    help="company to report on")
    st.set_defaults(func=cmd_status)

    e = sub.add_parser("estimate",
                       help="what the two spending stages would cost, and "
                            "whether they have anything to do")
    e.add_argument("ticker", nargs="?", default=None,
                   help="company to price")
    e.set_defaults(func=cmd_estimate)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(normalise_argv(
        list(sys.argv[1:] if argv is None else argv)))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
