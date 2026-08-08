"""Tests for the grounding check — the thing that makes traceability a test.

Run:  uv run python tests/test_verify_quote.py

WHY THIS FILE EXISTS
--------------------
`verify_quote` is the only reason a quote in the ledger means anything. A 100%
pass rate across 665 facts proves nothing on its own: a checker that returns True
unconditionally produces exactly the same result. So the negative cases matter
more than the positive ones, and they have to be re-run every time the
normalization is loosened.

It has been loosened three times, each after a real false negative on real
output — a stray trailing character, a literal \\u2019 escape, an image
placeholder mid-sentence. Every one of those changes made the check more
permissive, which is precisely when the rejection cases need re-proving.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from ledger_schema import verify_quote  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# A stand-in for a filing section, with the real artifacts embedded: a curly
# apostrophe, irregular whitespace, and a Workiva image placeholder mid-sentence.
SOURCE = """
Item 7.01. Regulation FD Disclosure. We recently announced that we will be
retiring Morningstar Office after 20 years and providing a streamlined
transition for interested clients to SS&C’s Black Diamond Wealth Platform.

In   general,  we seek to continuously enhance the value of products and
services to meet our clients’ needs. We review our pricing strategy
annually to ensure that it reflects investorquestions9262025003.jpg the value we
deliver to customers.

We continue to see a wide spectrum of client needs across our target market
and expect long-term demand for specialized sustainability research.
"""

MUST_PASS = [
    ("exact span",
     "We review our pricing strategy annually to ensure that it reflects"),
    ("collapsed irregular whitespace",
     "In general, we seek to continuously enhance the value of products and services"),
    ("straight apostrophe where the source is curly",
     "providing a streamlined transition for interested clients to SS&C's Black Diamond"),
    # The three real-output failures this check has been widened for.
    ("literal \\u2019 escape emitted instead of the character",
     "transition for interested clients to SS&C\\u2019s Black Diamond Wealth Platform"),
    ("image placeholder sits mid-sentence in the source, not in the quote",
     "We review our pricing strategy annually to ensure that it reflects the value we "
     "deliver to customers"),
    ("two stray trailing characters — a generation artifact",
     "We continue to see a wide spectrum of client needs across our target marketmm"),
]

MUST_FAIL = [
    ("fabricated but entirely plausible",
     "We expect to retire several legacy products over the coming three years as part "
     "of our platform consolidation strategy."),
    ("real opening, paraphrased ending",
     "We recently announced that we will be retiring Morningstar Office after two "
     "decades and moving clients onto a partner platform instead."),
    ("stitched from two separate passages",
     "We review our pricing strategy annually to ensure that it reflects long-term "
     "demand for specialized sustainability research."),
    ("one extra word inserted mid-quote",
     "We continue to see a very wide spectrum of client needs across our target market "
     "and expect long-term demand"),
    ("too short to be evidence",
     "our pricing strategy"),
    # Guards the image-placeholder normalization: dropping the token must not let a
    # quote span the text on either side of a DIFFERENT removed token.
    ("spans a real gap that only the placeholder removal could bridge",
     "annually to ensure that it reflects investorquestions9262025003.jpg and expect "
     "long-term demand for specialized sustainability research"),
    # FROM REAL OUTPUT — the first genuine paraphrase this project found, in a
    # FY2022 investor-Q&A extraction. The filing reads "...we are gaining traction
    # and seeing increased interest BUT have not yet seen significant adoption...";
    # the model emitted "WE have not yet seen significant adoption...", promoting a
    # subordinate clause to a standalone sentence and dropping the offsetting
    # positive half. It then characterised the result as "a direct admission...
    # hedging a growth narrative".
    #
    # Two words changed, and the claim got stronger than the filing supports. This
    # is the failure the whole check exists for, and it is why the near-miss
    # tolerance stays at three trailing characters: this quote is 96% exact.
    ("real output: subordinate clause promoted to a sentence, offsetting half dropped",
     "We have not yet seen significant adoption of managed accounts as a default "
     "option in the plans we work with"),
]

# The paraphrase above is checked against this, its real surrounding sentence.
PARAPHRASE_SOURCE = (
    "10. Has the selection of your managed accounts as a default option accelerated? "
    "We are gaining traction and seeing increased interest but have not yet seen "
    "significant adoption of managed accounts as a default option in the plans we work "
    "with, especially when distributed by recordkeepers that have proprietary "
    "target-date funds."
)


def main() -> int:
    failures = []
    # Counted as well as printed, so tests/run_all.py can tell whether this file
    # still runs as many cases as it used to. A suite that silently shrinks —
    # by losing a fixture, or by an early `return` — still reports green.
    counts = {"pass": 0, "fail": 0}

    print("MUST PASS — a legitimate citation must not be rejected")
    for label, quote in MUST_PASS:
        ok, why, span = verify_quote(quote, SOURCE)
        # An accepted quote with an empty span is a failure too: the caller uses
        # the span to show where the match landed.
        counts["pass" if (ok and span) else "fail"] += 1
        print(f"  {'PASS' if ok else 'BROKEN':7s} {label}")
        if not ok:
            print(f"          -> {why}")
            failures.append(f"false negative: {label} — {why}")
        elif not span:
            failures.append(f"passed but returned an empty span: {label}")

    print()
    print("MUST FAIL — the check is worthless if it cannot reject")
    for label, quote in MUST_FAIL:
        # The real-output paraphrase is checked against its own sentence; every
        # other case is checked against SOURCE.
        hay = PARAPHRASE_SOURCE if label.startswith("real output") else SOURCE
        ok, why, span = verify_quote(quote, hay)
        # Inverted: for these cases, rejection IS the passing outcome.
        counts["fail" if ok else "pass"] += 1
        print(f"  {'BROKEN' if ok else 'REJECTED':9s} {label}")
        if ok:
            print(f"          -> accepted as: {why}")
            failures.append(f"FALSE POSITIVE: {label} — accepted as {why!r}")
        else:
            print(f"            {why[:88]}")

    print()
    print("=" * 74)
    print(f"{counts['pass']} passed, {counts['fail']} failed")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(MUST_PASS)} pass-cases and {len(MUST_FAIL)} reject-cases behaved correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
