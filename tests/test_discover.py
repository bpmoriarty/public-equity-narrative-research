"""Cache vintage — how current is the data, as distinct from when the script ran.

Run:  uv run python tests/test_discover.py

WHY THIS FILE EXISTS
--------------------
`discover.py` is cache-first: a run can make zero EDGAR requests and return an index
fetched days earlier. `as_of_utc` used to be `datetime.now()` unconditionally, so the
inventory stamped the run's own clock on data it had not fetched — in a file that
also said `sec_requests_made: 0`, which contradicted it.

It was wrong by twelve minutes when the verification suite caught it, which is why it
survived: the error is invisible until the cache is old, and then it is silent.
`as_of_utc` is exactly the field a coverage or survivorship claim gets checked
against. VERIFICATION.md D9.

The fix reports both — index as of X, artifact written Y — and this file pins the
part that can go wrong quietly: where the vintage comes from, and that an inferred
vintage says so instead of passing as a record.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import equity_research.discover as d  # noqa: E402
from equity_research.paths import paths  # noqa: E402

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


# A scratch metadata directory, so nothing here touches the real cache. The module
# holds META_DIR and FETCH_LOG at import time, so both are redirected together —
# redirecting one and not the other is how a test like this quietly writes to the
# real cache while appearing to pass.
TMP = Path(os.environ.get("TEMP", "/tmp")) / "morn-test-discover"
TMP.mkdir(parents=True, exist_ok=True)
for f in TMP.glob("*"):
    f.unlink()
d.META_DIR, d.FETCH_LOG = TMP, TMP / "fetch-log.json"

client = d.SecClient(identity="test", delay=0.0, use_cache=True)


print("vintage_of — three sources, each labelled honestly")

check("a document that is not cached has no vintage and says so",
      client.vintage_of("absent.json"), (None, "not cached"))

# Cached, but with no log entry: the pre-existing case this project is actually in.
(TMP / "legacy.json").write_text("{}", encoding="utf-8")
ts, how = client.vintage_of("legacy.json")
check("a cache file with no log entry still yields a vintage", bool(ts), True)
check("  and it is labelled INFERRED, not presented as a record",
      "mtime" in how and "inferred" in how, True)

# Recorded at fetch time. This is the path every future document takes.
client._record_vintage("recorded.json", "2026-01-15T09:30:00Z")
(TMP / "recorded.json").write_text("{}", encoding="utf-8")
check("a recorded vintage is returned verbatim",
      client.vintage_of("recorded.json"),
      ("2026-01-15T09:30:00Z", "recorded when the document was fetched"))
check("  and a recorded vintage BEATS the file mtime",
      client.vintage_of("recorded.json")[0] != client.vintage_of("legacy.json")[0],
      True)

print("\nthe log survives being written more than once")
client._record_vintage("second.json", "2026-02-02T00:00:00Z")
log = json.loads((TMP / "fetch-log.json").read_text(encoding="utf-8"))
check("both entries are present — recording one does not clobber the other",
      sorted(log), ["recorded.json", "second.json"])

print("\na corrupt log degrades to the mtime path rather than crashing the run")
(TMP / "fetch-log.json").write_text("{ this is not json", encoding="utf-8")
ts2, how2 = client.vintage_of("recorded.json")
check("a truncated log does not raise", bool(ts2), True)
check("  and the fallback labels itself as inferred", "mtime" in how2, True)

print("\nthe real inventory reports the data's vintage, not the run's clock")
inv_p = P.inventory
if inv_p.exists():
    inv = json.loads(inv_p.read_text(encoding="utf-8"))
    check("as_of_utc and run_utc are both present and distinct fields",
          bool(inv.get("as_of_utc")) and bool(inv.get("run_utc")), True)
    check("  as_of_utc equals the index fetch time, not the run time",
          inv["as_of_utc"], inv["index_fetched_utc"])
    # The defect, stated as a test: on a cache-first run these MUST differ, and the
    # old code made them equal by construction.
    if inv.get("sec_requests_made") == 0:
        check("  a zero-request run does not claim its own clock as the as-of date",
              inv["as_of_utc"] != inv["run_utc"], True)
    check("  the basis of the as-of date is recorded, not assumed",
          bool(inv.get("as_of_basis")), True)
else:
    print("  --    no inventory.json; skipped")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
