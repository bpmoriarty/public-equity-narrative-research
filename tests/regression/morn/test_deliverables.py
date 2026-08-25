"""The shipped deliverables, held against the artifacts they were built from.

Run:  uv run python tests/regression/morn/test_deliverables.py

WHY THIS FILE EXISTS
--------------------
Everything here needs MORN's committed artifacts to mean anything: the two
generated documents, the generation records they came from, the pack their
citations resolve against, and the ledger those facts were built from. None of it
can be checked with an inline fixture, because the whole question is whether the
things actually on disk agree with each other.

Before Phase 5.1 these checks lived at the end of three files in tests/, each one
wrapped in `if <artifact>.exists():` with a "skipped" line in the else. That is
the exact shape of VERIFICATION.md D7 — `test_generate_outputs.py` ran 35 checks
in the working tree and 29 in a clean checkout and printed "0 failed" both times.
Moving them here lets them state their requirements once, up front, and DIE if
those are not met. A regression test with nothing to regress against is a
failure, not a pass and not a skip.

WHAT MOVED HERE, AND FROM WHERE
  - from test_generate_outputs.py: the per-document checks that every id
    resolves, every quotation is verbatim, and the rendered file matches the
    recorded body — plus the count assertion that catches a loop stopping early.
  - from test_verify_outputs.py: every hard check passing on each real document,
    and the brief's figures all evidenced in a cited fact's quote.
  - from test_fact_id.py: every id stored in the built ledger being reproducible
    from the fact's own content.

They are together because they are one question asked at four depths — ledger
ids, the pack index, the generation record, the file a reader opens — and a
break at any depth means a citation in a shipped document does not resolve.

WHAT DID NOT MOVE
The logic tests. `fact_id` sensitivity, `check_citations` and `check_quotes`
against documents built to fail them, and each of `verify_outputs`' gates
exercised in both directions all stayed in tests/unit/, where they read no
company data and need none.
"""

from __future__ import annotations

import hashlib
import json
import sys

# fixture FIRST, and the ordering is load-bearing: it sets EQR_TICKER, and the
# stage modules below resolve the ticker at IMPORT time. See fixture.py.
from fixture import P, require_artifacts  # noqa: E402
import equity_research.generate_outputs as g  # noqa: E402
import equity_research.verify_outputs as v  # noqa: E402
from equity_research.ledger_schema import FactSource, fact_id  # noqa: E402

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
# WHAT THIS FILE NEEDS, DECLARED BEFORE ANY OF IT IS READ.
#
# Named individually rather than checked as one directory, because the fixes
# differ and a message naming the wrong one wastes a run: the generation records
# and the documents are committed model output to be restored from git, while the
# pack is derived and free to rebuild. `require_artifacts` prints that
# distinction; see its docstring.
# ---------------------------------------------------------------------------
require_artifacts(
    P.ledger,
    P.pack / "pack.json",
    P.pack / "index.json",
    *[P.pack / f"gen-{slug}.json" for slug in g.DOCS],
    *[P.output / d["file"] for d in g.DOCS.values()],
)

print("THE BUILT LEDGER — every stored id must be reproducible from the fact itself")

# A glob cannot be declared above, so it is asserted here rather than assumed:
# an empty ledger directory would otherwise make the id check below pass by
# examining nothing, which is the failure this whole file exists to avoid.
ledger_files = sorted(P.ledger.glob("FY*.json"))
check("the ledger has per-year files to check", bool(ledger_files), True)

n = bad = 0
for p in ledger_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    for field, facts in d.items():
        if not isinstance(facts, list) or not facts or not isinstance(facts[0], dict):
            continue
        if "quote" not in facts[0]:
            continue
        for x in facts:
            n += 1
            src = FactSource(**x["source"]) if x.get("source") else None
            if fact_id(x["field"], x["fiscal_year"], x["value"],
                       src, x["quote"]) != x["id"]:
                bad += 1
                if bad <= 3:
                    print(f"        MISMATCH {p.name} {x['id']}")
check(f"all {n} stored ids recompute from their own content", bad, 0)


# ---------------------------------------------------------------------------
print()
print("THE GENERATION RECORDS — what shipped matches what the model returned")
# ---------------------------------------------------------------------------
#
# THE SKIP THAT HID ITSELF (kept verbatim from test_generate_outputs.py, because
# it is the reason this file exists).
#
# This block used to `continue` when a generation record was missing, printing one
# dim "skipped" line and then a green "29 passed, 0 failed". Six of the 35 checks
# — every check that touches a document actually shipped — silently stopped
# running, and the summary line said nothing was wrong. That is precisely the
# false-assurance shape a suite must not have: a suite that passes because it did
# not run is worse than a suite that fails.
#
# It went unnoticed because data/pack/ was gitignored, so the records existed in
# the working tree and vanished in a clean checkout — the one place a green run
# gets believed. gen-*.json are committed now (see .gitignore), so absence means
# something is wrong rather than something is merely underived. `require_artifacts`
# above now says so before a single check runs.

idx = json.loads((P.pack / "index.json").read_text(encoding="utf-8"))

n_docs = 0
for slug, d in g.DOCS.items():
    rec = json.loads((P.pack / f"gen-{slug}.json").read_text(encoding="utf-8"))
    n_docs += 1
    # `shipped_text` is the body actually written to output/ — identical to `text`
    # unless a recorded correction was applied after generation. See
    # `apply_corrections` in src/equity_research/generate_outputs.py: a correction
    # is data in this record, never a silent hand-edit of the document.
    shipped = rec.get("shipped_text") or rec["text"]
    check(f"{d['file']}: every id resolves",
          g.check_citations(shipped, idx)["unknown"], [])
    check(f"{d['file']}: every quotation is verbatim filing text",
          [b["quote"] for b in g.check_quotes(shipped, idx)["bad"]], [])
    check(f"{d['file']}: the rendered file matches the recorded body",
          shipped.strip() in (P.output / d["file"]).read_text(encoding="utf-8"),
          True)
    # A correction that is not in the record is a hand-edit, which is the thing the
    # check above exists to prevent. So the record must also be internally honest:
    # if it claims corrections, it must carry the pre-correction text to diff against.
    if rec.get("corrections"):
        check(f"{d['file']}: every correction is recorded with the text it replaced",
              bool(rec.get("text")) and shipped != rec["text"], True)

# The count itself is asserted, so a document dropped from DOCS — or a loop that
# quietly stops early — cannot pass by checking nothing.
check("every configured document was checked", n_docs, len(g.DOCS))


# ---------------------------------------------------------------------------
print()
print("THE CONSTRAINT GATES — every hard check, on the documents as shipped")
# ---------------------------------------------------------------------------
payload, pack, index, cfg, _gen = v.load()
sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
pf = v.pack_facts(pack, index)

n_verified = 0
for doc in cfg["documents"]:
    p = P.output / doc
    n_verified += 1
    body = p.read_text(encoding="utf-8")
    r = v.verify(doc, body, pack, index, pf, cfg, sha)
    check(f"{doc}: every hard check passes", [f["tag"] for f in r.failures], [])
    # The numeric-evidence calibration, held where it is STABLE. The brief is
    # asserted clean on both tiers — 19 figures, all in a cited fact's quote.
    # discussion-points.md is deliberately NOT asserted at a count: it currently
    # carries 2 unsourced (D3) and 17 thin (D2), and both numbers are supposed to
    # move as those are fixed. A test pinned to today's defect count has to be
    # edited every time a defect is fixed, which trains you to edit tests.
    if doc == "narrative-brief.md":
        ev = v.numeric_evidence(v.paragraphs(v.body_of(body)), index,
                                v.claim_numbers(pack))
        check(f"  {doc}: every figure is in a cited fact's quote",
              ev, {"thin": [], "unsourced": []})

# Same reasoning as the DOCS count above: the loop must be shown to have run.
check("every configured document was verified", n_verified, len(cfg["documents"]))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
