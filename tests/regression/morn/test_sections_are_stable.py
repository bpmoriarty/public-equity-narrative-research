"""Re-extract MORN's sections and prove not one character moved.

Run:     uv run python tests/regression/morn/test_sections_are_stable.py
Rebase:  uv run python tests/regression/morn/test_sections_are_stable.py --update

    SLOW BY DESIGN: about 16 seconds, parsing 202 cached filings. No network.

WHY THIS FILE EXISTS
--------------------
The question it answers is "are we over-fitting extraction to one company?", and
it answers the only part of that question a machine can.

`config/sections.toml` is global. Every pattern in it applies to every company.
So a boundary fixed for company B — one alternative appended to a `start_patterns`
list, one anchor phrase relaxed — can silently move company A's boundary too. That
coupling is real, it is invisible, and it fails in the worst possible direction:
an OVER-CAPTURED section looks exactly like a successful extraction. It is not an
error, not a warning, not a failed check. It is a larger bill and a worse answer.

Nothing else in the suite can see it. The unit tests use inline fixtures, so a
pattern change that wrecks MORN passes all of them. `test_reruns_change_nothing.py`
compares a stage against its own committed output, but `data/sections/` is
gitignored — derived, free to rebuild — so there are no committed bytes for it to
compare against, and section text is invisible to it.

WHY A COMMITTED BASELINE AND NOT RUN-TWICE
------------------------------------------
Running extraction twice and comparing the two runs catches nondeterminism, which
is not the risk here. Extraction is a pure function of the cached filings and the
config; two runs of the SAME code agree trivially. The failure this guards against
is a DELIBERATE change, made for a good reason, on a different company, whose
effect on this one nobody looked at. Only a baseline recorded before that change
can see it.

WHAT A FAILURE MEANS, AND WHY IT IS NOT AUTOMATICALLY A BUG
-----------------------------------------------------------
A red result here is a question, not a verdict: "you changed what MORN's filings
extract to — did you mean to?" Sometimes the answer is yes, and then `--update`
rebases the baseline and the diff shows a reviewer exactly which of the 231
sections moved, which is the whole point.

But it is never a cheap yes. `extract_facts` keys its cache on section SOURCE
TEXT, so any section whose text moves restales every fact drawn from it —
$11.33 to rebuild MORN's ledger, and CLAUDE.md rule 1 says that re-run buys *a*
valid answer, not *the* answer the committed deliverables cite. So this file is
also a cost tripwire, and `--update` should be a decision someone takes on
purpose rather than a way to make a red test green.

WHY HASHES AND NOT THE TEXT
---------------------------
231 sections run to roughly 5 MB. The baseline stores a sha256 and a character
count per section, which is 231 short lines, diffs legibly, and is exactly as
sensitive: a one-character change moves the hash.

WHY IT RE-RUNS THE STAGE INSTEAD OF HASHING WHAT IS ON DISK
------------------------------------------------------------
Hashing the existing `data/sections/` proves nothing. Those files were written by
whatever the code looked like when someone last ran it, which may be months ago
and several pattern edits back. The claim is about what the code produces TODAY
from the cached filings, so the stage has to actually run.

WHAT IT DOES TO THE WORKING TREE
--------------------------------
It rewrites `companies/MORN/data/sections/`, which is gitignored in full. If the
property holds those files are byte-identical to what was already there, so
nothing observable happens. If it does not hold, the new output is LEFT IN PLACE
deliberately — it is the evidence, and unlike `test_reruns_change_nothing.py`
there are no committed bytes here to restore.

THE CHECK COUNT IS A PROPERTY OF THIS FILE, NOT OF MORN'S WINDOW
-----------------------------------------------------------------
Every comparison below is aggregated into one check over all 231 sections rather
than one check per section. A per-section count would move with the fiscal-year
window, and a check count that varies by environment disarms the count gate in
`run_all.py` — in the direction that reads as "new checks were added", inviting a
re-record instead of an investigation. That defect has been found twice already
(Phase 4.6, Phase 5.1).
"""

from __future__ import annotations

import hashlib
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
UPDATE = "--update" in sys.argv[1:]

BASELINE = Path(__file__).with_name("section-baseline.json")


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


# ---------------------------------------------------------------------------
# Run the stage
# ---------------------------------------------------------------------------

require_artifacts(P.raw / "fetch-manifest.json", P.raw)
if not UPDATE:
    require_artifacts(BASELINE)

env = {**os.environ, "EQR_TICKER": FIXTURE_TICKER, "PYTHONUTF8": "1"}
proc = subprocess.run(
    [sys.executable, "-m", "equity_research.extract_sections",
     "--ticker", FIXTURE_TICKER],
    cwd=P.root, env=env, capture_output=True, text=True,
    encoding="utf-8", errors="replace")

if proc.returncode != 0:
    print(proc.stdout[-3000:])
    print(proc.stderr[-3000:])
    sys.exit(f"FATAL: extract_sections exited {proc.returncode}; nothing to compare.")


def observed() -> dict:
    """The extraction's identity: per section, its verdict, length and text hash.

    Keyed on "<accession>|<key>" because that pair is what the stage's own
    manifest merges on — the same key, so a collision here would be the same
    defect the merge has (see choose_documents in extract_sections.py).
    """
    man = json.loads(
        (P.sections / "sections-manifest.json").read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for row in man["sections"]:
        rec = {"ok": bool(row["ok"]), "chars": row.get("chars")}
        out_rel = row.get("out")
        if out_rel:
            data = P.resolve(out_rel).read_bytes()
            rec["sha256"] = hashlib.sha256(data).hexdigest()
        out[f"{row['accession']}|{row['key']}"] = rec
    return {
        "note": ("sha256 and length of every section MORN's filings extract to. "
                 "Regenerate deliberately with --update; see the module docstring "
                 "for why that is never free."),
        "company": FIXTURE_TICKER,
        "documents": man["last_run_documents"],
        "sections_attempted": man["sections_attempted"],
        "sections_written": man["sections_written"],
        "sections": dict(sorted(out.items())),
    }


now = observed()

# ---------------------------------------------------------------------------
# --update: rebase the baseline
# ---------------------------------------------------------------------------
# No timestamp anywhere in the payload. This file is committed, and CLAUDE.md
# rule 4 exempts only a value that records when EDGAR was READ — a rebase clock
# would make the file churn on every regeneration and hide the real diff.
if UPDATE:
    BASELINE.write_text(json.dumps(now, indent=2, sort_keys=False) + "\n",
                        encoding="utf-8")
    print(f"wrote {BASELINE.name}: {now['sections_attempted']} section(s) from "
          f"{now['documents']} document(s), {now['sections_written']} written")
    print("REVIEW THE DIFF. Every changed hash is a section whose text moved, and "
          "every fact drawn from it is now stale.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------
base = json.loads(BASELINE.read_text(encoding="utf-8"))
b, n = base["sections"], now["sections"]

print(f"MORN section stability — {len(n)} section(s) from {now['documents']} "
      f"document(s)")
print()

missing = sorted(set(b) - set(n))
appeared = sorted(set(n) - set(b))
shared = sorted(set(b) & set(n))

moved = [k for k in shared if b[k].get("sha256") != n[k].get("sha256")]
resized = [k for k in shared if b[k].get("chars") != n[k].get("chars")]
flipped = [k for k in shared if b[k]["ok"] != n[k]["ok"]]


def sample(keys: list[str], limit: int = 6) -> list[str]:
    """Name the offenders in the failure message; a bare count is not a diagnosis."""
    return keys[:limit] + ([f"...and {len(keys) - limit} more"]
                           if len(keys) > limit else [])


check("every section in the baseline still extracts", sample(missing), [])
check("no section appeared that the baseline does not know about",
      sample(appeared), [])
check("not one section's text moved", sample(moved), [])
check("  nor its character count", sample(resized), [])
check("no section's verdict flipped between ok and failed", sample(flipped), [])
check("the stage still reads the same number of documents",
      now["documents"], base["documents"])
check("the same number of sections is attempted",
      now["sections_attempted"], base["sections_attempted"])
check("  and the same number written",
      now["sections_written"], base["sections_written"])

# The manifest and the filesystem must agree: a row marked ok whose text file is
# gone would hash as absent above, but a row marked ok that never had an `out`
# path would slip through every comparison, because None == None.
no_text = [k for k, v in n.items() if v["ok"] and "sha256" not in v]
check("every section recorded ok has text on disk behind it", sample(no_text), [])

print()
print(f"{PASS} passed, {FAIL} failed")
if FAIL:
    print()
    print("A failure here is a question, not a verdict: you changed what MORN's")
    print("filings extract to. If that was deliberate, rebase with --update — but")
    print("read the diff first, because every moved section restales the facts")
    print("drawn from it, and MORN's ledger costs $11.33 to rebuild.")
sys.exit(1 if FAIL else 0)
