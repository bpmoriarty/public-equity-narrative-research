"""Tests that the repository keeps the things it cannot regenerate.

Run:  uv run python tests/test_repo_hygiene.py

WHY THIS FILE EXISTS
--------------------
Three separate times, output that had been paid for and could never be
reproduced byte-for-byte was placed in a gitignored directory, each time under
the same reasoning: "it regenerates from what we already commit."

    data/ledger/facts/   88 files, $4.52 of extraction   — rescued
    output/*.md          the three deliverables, ~$3.50  — rescued
    data/pack/gen-*.json the only copy of each document
                         as first written, before repair — rescued last,
                         and only because the verification suite measured the
                         consequence

For derived files the reasoning is sound, and .gitignore uses it correctly for
data/sections/, pack.json and the PDFs. For model output it is simply false: a
re-run produces *a* valid answer, not *the* answer that the committed documents
cite. Losing it does not cost a rebuild, it costs the audit trail — the ability
to ask "what did the model actually return?" after the fact.

The rule cannot live in a comment, because it already did. .gitignore carried a
full written explanation of why model output must be committed, and the same
mistake was then made again in the block directly below it.

WHAT COUNTS AS MODEL OUTPUT
---------------------------
A JSON file with a top-level `usage` object carrying `input_tokens`. That is the
shape the Anthropic SDK returns and this pipeline stores, and it is present in
both kinds of record the project keeps:

    data/ledger/facts/FY2021_board.json   fiscal_year, task, model, usage, facts
    data/pack/gen-brief.json              document, model, usage, rounds, text

Anything matching that shape was paid for. It must be tracked by git.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from equity_research.paths import paths  # noqa: E402

# ROOT stays: this file walks the WHOLE repository looking for paid model output,
# which is a repo-level question, not a per-company one — a company folder added
# tomorrow with ignored facts/ must fail this suite too. `P` is only for the
# checks that name a specific company's artifacts.
P = paths()

PASS = FAIL = 0

# Directories with nothing git could ever be expected to track.
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
             "node_modules"}

# The byte sequence every paid response contains. Used as a cheap pre-filter so
# the walk does not JSON-parse ~940 KB pack files it has no interest in.
MARKER = b'"input_tokens"'


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")
        if detail:
            for line in detail.splitlines():
                print(f"          {line}")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def tracked_files() -> set[str]:
    """Every path git currently tracks, as forward-slash strings."""
    r = git("ls-files", "-z")
    if r.returncode != 0:
        print("  FAIL  cannot run git — this test needs a git repository")
        raise SystemExit(1)
    return {p for p in r.stdout.split("\0") if p}


def is_ignored(rel: str) -> bool:
    """True if .gitignore would exclude this path.

    Checked separately from tracked-ness because the two failures need different
    fixes: an ignored file needs a .gitignore change, an untracked-but-not-ignored
    file just needs `git add`.
    """
    return git("check-ignore", "-q", "--", rel).returncode == 0


def is_model_output(path: Path) -> bool:
    """A top-level `usage` object with `input_tokens` means a model was paid."""
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if MARKER not in raw:
        return False
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return (isinstance(doc, dict)
            and isinstance(doc.get("usage"), dict)
            and "input_tokens" in doc["usage"])


def walk_json() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.json"):
        if SKIP_DIRS & set(p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return out


def main() -> int:
    tracked = tracked_files()

    print("MODEL OUTPUT MUST BE TRACKED — it cannot be regenerated, only re-bought")
    candidates = walk_json()
    found = [p for p in candidates if is_model_output(p)]
    rels = sorted(p.relative_to(ROOT).as_posix() for p in found)

    # An empty result would make every check below vacuously pass, which is the
    # failure shape this whole file is about. Assert the detector found the
    # records we know exist.
    check(f"the detector found model-output files at all "
          f"({len(found)} of {len(candidates)} json files scanned)",
          len(found) > 0,
          "No file carried a top-level usage.input_tokens. Either the records "
          "are missing from disk, or the storage shape changed and this "
          "detector now matches nothing — in which case it is no longer "
          "protecting anything.")

    if found:
        ignored = [r for r in rels if is_ignored(r)]
        check(f"none of the {len(rels)} model-output file(s) are gitignored",
              not ignored,
              "GITIGNORED MODEL OUTPUT — this is the mistake that has been made "
              "three times:\n" + "\n".join(f"  {r}" for r in ignored) +
              "\nA re-run buys a different answer, not this one. Add a negation "
              "to .gitignore (see the data/pack/ block for the pattern).")

        untracked = [r for r in rels if r not in tracked]
        check(f"all {len(rels)} model-output file(s) are tracked by git",
              not untracked,
              "UNTRACKED MODEL OUTPUT — not ignored, just never added:\n" +
              "\n".join(f"  {r}" for r in untracked) +
              "\nRun: git add " + " ".join(untracked[:5]))

    print()
    print("THE DELIVERABLES MUST BE TRACKED — model-written prose, ~$3.50 a pass")
    docs = sorted(P.output.glob("*.md"))
    check("output/ contains generated documents", bool(docs),
          "No .md files in output/. If the pipeline has not been run this is "
          "expected; if it has, the deliverables are missing.")
    for d in docs:
        rel = d.relative_to(ROOT).as_posix()
        check(f"tracked: {rel}", rel in tracked,
              f"{rel} is not tracked. It is the only artifact anyone outside "
              f"this repo reads, and every citation check runs against it.")

    print()
    print("SECRETS MUST NOT BE TRACKED — the inverse of the rule above")
    # .env holds EDGAR_IDENTITY and ANTHROPIC_API_KEY. gitignore only protects
    # files that were never added; once committed, a file stays tracked and the
    # ignore rule is silently irrelevant. That is worth asserting, not assuming.
    check(".env is not tracked", ".env" not in tracked,
          ".env is TRACKED. It holds ANTHROPIC_API_KEY. Untrack it now "
          "(git rm --cached .env) and rotate the key — it is in the history.")
    check(".env is ignored", is_ignored(".env") or not (ROOT / ".env").exists(),
          ".env exists but .gitignore does not cover it.")

    print()
    print("=" * 74)
    print(f"{PASS} passed, {FAIL} failed")
    if FAIL:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
