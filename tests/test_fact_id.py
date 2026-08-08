"""Tests for fact ids — the thing that makes a citation checkable.

Run:  uv run python tests/test_fact_id.py

WHY THIS FILE EXISTS
--------------------
An id is only useful if it is stable in the right way and unstable in the right
way, and neither property is visible by looking at a built ledger: 1,428 unique
ids look equally correct whether or not the hash includes the fields it should.

The rule being locked in here is the design decision:

    JUDGMENTS ABOUT a fact do not change its id.
    The fact's CONTENT and EVIDENCE do.

The insensitivity half is the fragile one. Adding `confidence` to the hash would
break nothing visibly today — the ledger would rebuild, the ids would all be
unique, every check would pass. It would only surface later, when fixing the
director-bio boundaries flipped 51 board facts from `low` to `high` and silently
invalidated every citation to them in an already-written brief.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from ledger_schema import (FactSource, LedgerFact,  # noqa: E402
                           fact_id, risk_delta_id)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SRC = FactSource(form="10-K", fiscal_year=2023, accession="0001289419-24-000010",
                 section_key="10-K_item1_business", filing_date="2024-02-29")
VALUE = {"text": "Our strategy is to deliver insights and experiences."}
QUOTE = "Our strategy is to deliver insights and experiences."


def base() -> str:
    return fact_id("strategic_priorities", 2023, VALUE, SRC, QUOTE)


# (label, id to compare against base) — these MUST equal base().
def unchanged_cases() -> list[tuple[str, str]]:
    return [
        ("same inputs twice", base()),
        # `filing_date` comes from the inventory rather than from the fact, so
        # correcting one must not renumber facts that did not change.
        ("filing_date corrected in the inventory",
         fact_id("strategic_priorities", 2023, VALUE,
                 SRC.model_copy(update={"filing_date": "2024-03-01"}), QUOTE)),
    ]


def key_order_case() -> tuple[str, bool]:
    """A dict built in a different insertion order holds the same value.

    Without `sort_keys=True` in the digest these two would hash differently, and
    the ledger would quietly stop being idempotent — the kind of bug that shows up
    as an unexplained diff months later.
    """
    forward = fact_id("segments", 2023, {"name": "PitchBook", "basis": "reportable"}, SRC, QUOTE)
    reverse = fact_id("segments", 2023, {"basis": "reportable", "name": "PitchBook"}, SRC, QUOTE)
    return "value dict built in a different key order", forward == reverse


# These MUST differ from base().
def changed_cases() -> list[tuple[str, str]]:
    return [
        ("the claim itself changed",
         fact_id("strategic_priorities", 2023, {"text": "Something else."}, SRC, QUOTE)),
        ("the evidence changed — a different quote for the same claim",
         fact_id("strategic_priorities", 2023, VALUE, SRC, QUOTE + " And more.")),
        ("a different fiscal year, identical content",
         fact_id("strategic_priorities", 2024, VALUE, SRC, QUOTE)),
        ("a different ledger field",
         fact_id("notable_language", 2023, VALUE, SRC, QUOTE)),
        ("a different filing",
         fact_id("strategic_priorities", 2023, VALUE,
                 SRC.model_copy(update={"accession": "0001289419-25-000041"}), QUOTE)),
        ("a different section of the same filing",
         fact_id("strategic_priorities", 2023, VALUE,
                 SRC.model_copy(update={"section_key": "10-K_item7_mdna"}), QUOTE)),
        ("no source at all — an unverified fact",
         fact_id("strategic_priorities", 2023, VALUE, None, QUOTE)),
    ]


def confidence_cases() -> list[tuple[str, str, str]]:
    """The insensitivity that matters most, tested through the model rather than
    the function, because the model is what build_ledger actually constructs."""
    def mk(**over) -> LedgerFact:
        kw = dict(field="strategic_priorities", fiscal_year=2023, value=VALUE,
                  source=SRC, confidence="high", confidence_reason=None,
                  quote=QUOTE, quote_verified=True, quote_check="verbatim match")
        kw.update(over)
        return LedgerFact(**kw)

    ref = mk().id
    return [
        ("confidence downgraded to low", ref,
         mk(confidence="low", confidence_reason="boundary unverified").id),
        ("quote_verified flipped to False", ref, mk(quote_verified=False).id),
        ("quote_check text rewritten", ref,
         mk(quote_check="near match, 2 trailing chars").id),
    ]


# --- risk deltas -----------------------------------------------------------
# The regression case. The first version of risk_delta_id read `item["heading"]`,
# which exists on `added`/`removed`/`unchanged` deltas but NOT on `reworded` ones —
# those carry `heading_now` / `heading_prior`. Every reworded delta therefore
# hashed a `None` heading, and 46 of them across the five years collided on one id.
# Caught by the build-time uniqueness check on its first run.
REWORDED = [
    {"heading_now": "Failing to innovate our product and service offerings.",
     "heading_prior": "Failing to differentiate our products and services.",
     "category_now": "Risks Related to Our Business", "category_prior": "Risks Related to Our Business",
     "changed": "heading and body", "heading_similarity": 62.0, "body_similarity": 71.3},
    {"heading_now": "Prolonged volatility affecting global financial markets.",
     "heading_prior": "Prolonged volatility affecting the financial sector.",
     "category_now": "Risks Related to Our Business", "category_prior": "Risks Related to Our Business",
     "changed": "body only", "heading_similarity": 100.0, "body_similarity": 90.4},
]
RISK_SRC = {"accession": "0001289419-25-000041", "prior_accession": "0001289419-24-000010"}


def main() -> int:
    failures = []
    counts = {"pass": 0, "fail": 0}

    def tally(ok: bool) -> bool:
        """Count a check, so tests/run_all.py can tell if the suite shrinks.

        A test that quietly runs fewer checks than it used to still reports
        green. Counting here, at the point of the check itself, is what makes
        that visible — see tests/expected_counts.json.
        """
        counts["pass" if ok else "fail"] += 1
        return ok

    print("MUST BE STABLE — the same fact keeps its id")
    ref = base()
    for label, got in unchanged_cases():
        ok = tally(got == ref)
        print(f"  {'STABLE' if ok else 'BROKEN':7s} {label}")
        if not ok:
            failures.append(f"id moved when it should not have: {label}")
    label, ok = key_order_case()
    tally(ok)
    print(f"  {'STABLE' if ok else 'BROKEN':7s} {label}")
    if not ok:
        failures.append(f"the digest is not order-stable: {label} — the ledger would "
                        f"stop being idempotent")

    print()
    print("MUST BE INSENSITIVE — a judgment about a fact is not the fact")
    for label, ref_id, got in confidence_cases():
        ok = tally(got == ref_id)
        print(f"  {'STABLE' if ok else 'BROKEN':7s} {label}")
        if not ok:
            failures.append(f"CONFIDENCE LEAKED INTO THE ID: {label}. Fixing the "
                            f"director-bio boundaries would renumber 51 board facts "
                            f"and invalidate every citation to them.")

    print()
    print("MUST CHANGE — a different fact is a different id")
    for label, got in changed_cases():
        ok = tally(got != ref)
        print(f"  {'CHANGED' if ok else 'BROKEN':8s} {label}")
        if not ok:
            failures.append(f"COLLISION: {label} produced the same id as the original")

    print()
    print("RISK DELTAS — the reworded shape that collided 46 times")
    a = risk_delta_id(2024, "reworded", REWORDED[0], RISK_SRC)
    b = risk_delta_id(2024, "reworded", REWORDED[1], RISK_SRC)
    checks = [
        ("two different reworded deltas get different ids", a != b),
        ("same delta, same id", a == risk_delta_id(2024, "reworded", REWORDED[0], RISK_SRC)),
        ("similarity scores do not affect the id",
         a == risk_delta_id(2024, "reworded",
                            {**REWORDED[0], "body_similarity": 71.4, "changed": "body only"},
                            RISK_SRC)),
        ("the delta category is part of the identity",
         a != risk_delta_id(2024, "unchanged", REWORDED[0], RISK_SRC)),
        ("a heading reworded from a different prior is a different delta",
         a != risk_delta_id(2024, "reworded",
                            {**REWORDED[0], "heading_prior": "Something else entirely."},
                            RISK_SRC)),
    ]
    for label, ok in checks:
        tally(ok)
        print(f"  {'PASS' if ok else 'BROKEN':7s} {label}")
        if not ok:
            failures.append(f"risk delta id: {label}")

    # --- against the real ledger, if it has been built ---------------------
    print()
    print("THE BUILT LEDGER — every stored id must be reproducible from the fact itself")
    paths = sorted((ROOT / "data" / "ledger").glob("FY*.json"))
    if not paths:
        print("  SKIPPED  no ledger on disk — run src/build_ledger.py")
    else:
        n = bad = 0
        for p in paths:
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
                            print(f"  MISMATCH {p.name} {x['id']}")
        tally(not bad)
        print(f"  {'PASS' if not bad else 'BROKEN':7s} {n} facts checked, {bad} id(s) "
              f"not reproducible from their own stored content")
        if bad:
            failures.append(f"{bad} stored id(s) cannot be recomputed — the output "
                            f"checker would reject valid citations")

    print()
    print("=" * 74)
    print(f"{counts['pass']} passed, {counts['fail']} failed")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ids are stable against judgments and sensitive to content and evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
