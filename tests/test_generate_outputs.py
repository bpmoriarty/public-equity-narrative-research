"""Milestone 5e — the checks that decide whether an output document is publishable.

Run:  uv run python tests/test_generate_outputs.py

Two things are checked here and neither is about prose quality.

  1. `check_citations` — does every id in the document resolve to a fact?
  2. `check_quotes`    — is every quotation character-for-character the filing's text?

The second is the one that matters most, and the reason is the measurement that
produced it. On the first generation run the id check passed at 323/324 while the
quotation check found 8 defects in 118 quotations. Ids are opaque strings sitting
beside the fact and the model copies them accurately; quotations are reconstructed
from memory of something read 300,000 tokens earlier, and a quotation one word off
looks exactly like a correct one.

So a document can pass the id check completely and still put words in the company's
mouth — and it then reads as MORE sourced than an unsourced sentence would. Every
fixture below is a real string from the first run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# fixture FIRST, and that ordering is load-bearing: it sets EQR_TICKER, and the
# stage modules below resolve the ticker at IMPORT time. `P` used to be bound
# 220 lines further down, which worked only while MORN was the single company.
# See tests/fixture.py.
from fixture import P  # noqa: E402
import equity_research.generate_outputs as g  # noqa: E402
from equity_research import model_client  # noqa: E402

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
# A miniature index, using real text from the MORN pack
# ---------------------------------------------------------------------------

INDEX = {
    # The near-miss case. The filing says "low 20's percent range"; the first draft
    # quoted "low 20 percent range" and that single dropped apostrophe-s is the whole
    # difference between a quotation and a misquotation.
    "QA-FY2024-5e714350": {
        "field": "investor_qa", "fiscal_year": 2024, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "During his presentation at the Annual Shareholder Meeting, Jason noted "
                 "that our goal was to increase our adjusted operating margins to recent "
                 "historical peaks and higher. Recent peaks have been in the low 20's "
                 "percent range."},
    # "our most vulnerable segment" was quoted as "the most vulnerable segment".
    "QA-FY2023-2a54a3c6": {
        "field": "investor_qa", "fiscal_year": 2023, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "The company segment continues to be our most vulnerable segment in the "
                 "current market environment, with particular vulnerability with start-ups "
                 "and corporate development teams."},
    # Curly quotes inside the source; the document wrote them as straight singles.
    "QA-FY2025-e40e1959": {
        "field": "investor_qa", "fiscal_year": 2025, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "In order to maintain an aggregate bonus pool amount that is appropriately "
                 "aligned with profits, we monitor the “sharing ratio” expressed "
                 "as a projected bonus payout as a percentage of AOI each quarter."},
    # A risk delta: NO quote field at all, only a heading. Headings come from a
    # deterministic diff of Item 1A, so they are filing text and quoting them is fine.
    "RISK-FY2025-d7eff92c": {
        "field": "risk_deltas", "fiscal_year": 2025, "confidence": "high",
        "quote_verified": None, "source": {},
        "heading": "Our stock price may not reflect our assessment of intrinsic value and "
                   "future sales of our common stock by our significant shareholders and "
                   "fluctuations may affect it."},
    "QA-FY2023-1d4e7aca": {
        "field": "investor_qa", "fiscal_year": 2023, "confidence": "high",
        "quote_verified": True, "source": {},
        "quote": "We corrected the calculation of adjusted diluted net income per share for "
                 "the quarter ended June 30, 2023, following the identification of a "
                 "clerical error in the calculation."},
    "BRD-FY2021-e7589d5c": {
        "field": "board", "fiscal_year": 2021, "confidence": "low",
        "quote_verified": True, "source": {},
        "quote": "Joe Mansueto has served as our chairman since 1984."},
    "LANG-FY2021-a0b1c2d3": {
        "field": "notable_language", "fiscal_year": 2021, "confidence": "high",
        "quote_verified": False, "source": {},
        "quote": "This quote could not be located in any source section."},
}


def q(text: str) -> dict:
    return g.check_quotes(text, INDEX)


print("\ncheck_quotes — verbatim, near-miss, and fabricated")

check("verbatim span in a fact cited in the same paragraph",
      q('Peaks have been in the "low 20\'s percent range" [QA-FY2024-5e714350].')["ok"], 1)

# THE REGRESSION CASE. One apostrophe-s. This is the defect the id check cannot see.
check("near-miss misquote is caught (low 20 vs low 20's)",
      [b["quote"] for b in
       q('Margins in the "low 20 percent range" [QA-FY2024-5e714350].')["bad"]],
      ["low 20 percent range"])

check("near-miss misquote is caught (the vs our)",
      len(q('its "the most vulnerable segment in the current market environment" '
            '[QA-FY2023-2a54a3c6].')["bad"]), 1)

check("a phrase in no filing text anywhere is caught",
      len(q('management called it "self-inflicted incompetence" [QA-FY2023-2a54a3c6].')
          ["bad"]), 1)

check("the failing quotation carries the text it SHOULD have used",
      q('Margins in the "low 20 percent range" [QA-FY2024-5e714350].')
      ["bad"][0]["permitted"][0]["id"], "QA-FY2024-5e714350")

print("\ncheck_quotes — conventions an honest writer uses")

check("US-style comma inside the closing quote mark is not part of the quotation",
      q('It is "our most vulnerable segment in the current market environment," they say '
        '[QA-FY2023-2a54a3c6].')["ok"], 1)

check("a bracketed editorial insertion still matches",
      q('costs are "in the low 20\'s percent range [for margins]" '
        '[QA-FY2024-5e714350].')["ok"], 1)

check("an ellipsis elides rather than breaks the match",
      q('"we monitor the \'sharing ratio\' … as a percentage of AOI each quarter" '
        '[QA-FY2025-e40e1959].')["ok"], 1)

check("curly quotes in the filing match straight quotes in the document",
      q('the "\'sharing ratio\' expressed as a projected bonus payout" '
        '[QA-FY2025-e40e1959].')["ok"], 1)

check("a risk-delta HEADING is quotable — it has no quote field but is filing text",
      q('One risk was added: "Our stock price may not reflect our assessment of intrinsic '
        'value" [RISK-FY2025-d7eff92c].')["ok"], 1)

print("\ncheck_quotes — the two bugs the first checker had")

# `"ready" rather than a "wish list"` must yield two quotations, not a phantom third
# made of the words between them. Left-to-right pairing is what fixes it.
r = q('clients that were "ready to buy today" rather than a "wish list of prospects" '
      '[QA-FY2024-5e714350].')
check("adjacent quotations pair left to right (no phantom quotation from the gap)",
      r["checked"], 2)
check("  and both of those are reported as defects, not the gap between them",
      sorted(b["quote"] for b in r["bad"]),
      ["ready to buy today", "wish list of prospects"])

# The floor was 12 and excused a real 10-character fabrication.
check("a short fabricated quotation is still checked (floor is 4, not 12)",
      [b["quote"] for b in q('a footnote that "was a typo" [QA-FY2023-1d4e7aca].')["bad"]],
      ["was a typo"])
check("  while the verbatim span in the same fact passes",
      q('corrected for "a clerical error in the calculation" [QA-FY2023-1d4e7aca].')["ok"], 1)

print("\ncheck_quotes — right words, wrong citation")

check("filing text cited in the wrong paragraph is 'elsewhere', not 'bad'",
      len(q('It is "our most vulnerable segment in the current market environment" '
            '[QA-FY2024-5e714350].')["elsewhere"]), 1)
check("  and 'elsewhere' is not counted as verbatim-where-cited",
      q('It is "our most vulnerable segment in the current market environment" '
        '[QA-FY2024-5e714350].')["ok"], 0)
check("a quotation with no citation at all in its paragraph is caught",
      len(q('Management called it "our most vulnerable segment in the current market '
            'environment" with no source.')["elsewhere"]), 1)

print("\ncheck_citations")

c = g.check_citations(
    "One [QA-FY2024-5e714350] two [BRD-FY2021-e7589d5c] three [LANG-FY2021-a0b1c2d3] "
    "four [QA-FY2024-deadbeef] five [QA-FY2024-5e714350].", INDEX)
check("counts every occurrence", c["citations"], 5)
check("counts distinct ids once", c["distinct"], 4)
check("an id not in the pack is unresolved", c["unknown"], ["QA-FY2024-deadbeef"])
check("a low-confidence fact is surfaced for the constraint-1 flag",
      c["low_confidence"], ["BRD-FY2021-e7589d5c"])
check("a fact whose quote was never verified is surfaced",
      c["unverified_quote"], ["LANG-FY2021-a0b1c2d3"])
# Distinct, so the id cited twice counts once, and the unresolvable one counts not at
# all -- `by_field` describes the evidence actually reached, not the citation traffic.
check("fields are tallied over distinct, resolvable ids",
      c["by_field"], {"board": 1, "investor_qa": 1, "notable_language": 1})

print("\ncheck_citations — a field code that does not exist")

# THE HOLE. ID_RE is built from the real field codes, so before `malformed` existed
# a token like MDNA-FY2021-deadbeef was prose as far as every check was concerned:
# check_citations did not report it, the repair round never saw it, verify_outputs
# imported the same regex and passed it too. A reader sees a citation.
#
# Not a contrived example. `mdna` is a real task name in extract_facts — MD&A is a
# thing this pipeline has a word for. It is simply not a field code.
m = g.check_citations("Real [QA-FY2024-5e714350], invented field "
                      "[MDNA-FY2021-deadbeef].", INDEX)
check("a citation with an unreal field code is reported",
      m["malformed"], ["MDNA-FY2021-deadbeef"])
check("  and is NOT counted among the resolvable citations", m["citations"], 1)
check("  nor among the unresolvable ids, which have a real slice to search",
      m["unknown"], [])

# The other three directions, so the check is bounded on both sides. A regex that
# flags everything is as useless as one that flags nothing.
check("a real id is not flagged",
      g.check_citations("[QA-FY2024-5e714350]", INDEX)["malformed"], [])
check("a real code with an unknown hash is 'unknown', not 'malformed'",
      g.check_citations("[QA-FY2024-deadbeef]", INDEX)["malformed"], [])
check("RISK is a real code even though it is not in FIELD_CODES",
      g.check_citations("[RISK-FY2025-d7eff92c]", INDEX)["malformed"], [])
check("prose that merely contains capitals and a year is not flagged",
      g.check_citations("The FY2021 10-K and the FY2024 DEF 14A.", INDEX)["malformed"],
      [])
check("a hash of the wrong length is not an id at all",
      g.check_citations("[QQQ-FY2021-dead]", INDEX)["malformed"], [])
check("uppercase hex is not the id shape either",
      g.check_citations("[QQQ-FY2021-DEADBEEF]", INDEX)["malformed"], [])

# A REAL id, lower-cased. Ids are minted uppercase, so this resolves to nothing —
# and a model lower-casing an id it copied is likelier than one inventing a whole
# field code. Matching only [A-Z] in the shape regex would read this as prose,
# which is the same hole one step along.
check("a real code in lower case is malformed, not prose",
      g.check_citations("[qa-FY2024-5e714350]", INDEX)["malformed"],
      ["qa-FY2024-5e714350"])
check("  and is not silently counted as the real citation it resembles",
      g.check_citations("[qa-FY2024-5e714350]", INDEX)["citations"], 0)

print("\nword_count")
# The leftover-bracket bug: stripping ids alone leaves `[, ]`, which str.split() counts
# as two more words. The count is what the document is held to against SPEC.md's
# 1,500-2,500, so it has to measure prose and nothing else.
check("a citation group counts as no words at all",
      g.word_count("Alpha beta gamma [QA-FY2024-5e714350, BRD-FY2021-e7589d5c] delta."), 4)
check("a single-id citation likewise",
      g.word_count("Alpha beta [QA-FY2024-5e714350] gamma."), 3)
check("brackets that are NOT citations still count as prose",
      g.word_count("Alpha [see note] beta."), 4)
check("an id outside brackets is still not prose",
      g.word_count("Alpha QA-FY2024-5e714350 beta."), 2)

print("\nthe id pattern tracks ledger_schema, so a new field cannot become uncheckable")
from equity_research.ledger_schema import FIELD_CODES  # noqa: E402
check("every field code the ledger can mint is matched by ID_RE",
      sorted({code for code in FIELD_CODES.values()
              if not g.ID_RE.fullmatch(f"{code}-FY2023-0123abcd")}), [])
check("  including RISK, which is minted outside FIELD_CODES",
      bool(g.ID_RE.fullmatch("RISK-FY2023-0123abcd")), True)

print("\nindex_excerpt — what an id repair is given instead of the pack")

# The id repair stopped resending the 353,000-token pack when the engine moved to
# a Claude seat, because a resumed conversation there re-writes everything at 2x
# and reads nothing back. What replaced it is a slice of the index, and these
# checks are about the property that makes the slice defensible: a hallucinated id
# still names a REAL field and a REAL fiscal year, because ID_RE only matches
# known field codes. Only the content hash is invented.

check("a hallucinated id still names its slice", g.slice_of("QA-FY2024-deadbeef"),
      ("QA", "FY2024"))
check("  and so does a real one", g.slice_of("BRD-FY2021-e7589d5c"), ("BRD", "FY2021"))

ex, meta = g.index_excerpt(INDEX, ["QA-FY2024-deadbeef"])
check("the excerpt offers every real id in the broken id's slice",
      "QA-FY2024-5e714350" in ex, True)
check("  and counts what it offered", meta["ids_offered"], 1)
check("  from exactly one slice", meta["slices"], ["QA-FY2024"])

# THE RESTRICTION IS THE POINT, so it is checked rather than assumed. A repair
# shown facts from every year could "fix" a citation by reaching for a different
# year's fact that happens to fit the sentence — which is how a claim acquires
# support it never had.
check("ids from other years are NOT offered", "QA-FY2023-2a54a3c6" in ex, False)
check("ids from other fields are NOT offered", "BRD-FY2021-e7589d5c" in ex, False)

ex2, meta2 = g.index_excerpt(INDEX, ["QA-FY2023-deadbeef", "BRD-FY2021-deadbeef"])
check("two broken ids in different slices open both slices",
      meta2["slices"], ["BRD-FY2021", "QA-FY2023"])
check("  offering every id in both (2 in QA-FY2023, 1 in BRD-FY2021)",
      meta2["ids_offered"], 3)

# An id invented for a year the pack has nothing in at all. The excerpt must SAY
# the slice is empty. Rendering nothing would read as "the excerpt was cut short",
# and the model's next move — delete the claim or hunt for a substitute — differs
# between those two readings.
ex3, meta3 = g.index_excerpt(INDEX, ["MDNA-FY2019-deadbeef"])
check("an empty slice says so rather than rendering blank",
      "the pack holds no fact of this field for this year" in ex3, True)
check("  and reports zero ids offered", meta3["ids_offered"], 0)

check("a low-confidence fact is marked as one",
      "(low confidence)" in g.index_excerpt(INDEX, ["BRD-FY2021-x0000000"])[0], True)
check("a risk delta contributes its heading, having no quote field",
      "Our stock price may not reflect" in
      g.index_excerpt(INDEX, ["RISK-FY2025-x0000000"])[0], True)

print("\nindex_excerpt — the budget, proven against input that exceeds it")

# Built to overflow. The ladder must step the QUOTE length down and keep every id,
# never drop ids to fit: a slice shown in part would tell the model the fact it
# wants does not exist, and the instruction for that case is to delete the claim.
def fat_index(n: int, quote_len: int = 600) -> dict:
    return {f"QA-FY2030-{i:08x}": {
        "field": "investor_qa", "fiscal_year": 2030, "confidence": "high",
        "quote_verified": True, "source": {"form": "8-K", "filing_date": "2030-01-01"},
        "quote": f"fact {i} " + "x" * quote_len} for i in range(n)}


small = g.index_excerpt(fat_index(20), ["QA-FY2030-ffffffff"])[1]
check("a slice that fits keeps full-length quotes",
      small["quote_chars"], g.QUOTE_CHARS_LADDER[0])
check("  and is not flagged over budget", small["over_budget"], False)

big_ex, big = g.index_excerpt(fat_index(400), ["QA-FY2030-ffffffff"])
check("an oversized slice steps the quote length down",
      big["quote_chars"] < g.QUOTE_CHARS_LADDER[0], True)
check("  brings the excerpt inside the budget",
      big["estimated_tokens"] <= g.EXCERPT_TOKEN_BUDGET, True)
check("  and still offers every id in the slice", big["ids_offered"], 400)
check("  with the truncation marked, not silent", "…[truncated]" in big_ex, True)

huge_ex, huge = g.index_excerpt(fat_index(3000), ["QA-FY2030-ffffffff"])
check("a slice too big even without quotes drops to ids only",
      huge["quote_chars"], 0)
check("  admits it is over budget rather than trimming the slice",
      huge["over_budget"], True)
check("  and STILL offers every id", huge["ids_offered"], 3000)

print("\nslice_census — so 'not shown' is distinguishable from 'not in the pack'")

cen = g.slice_census(INDEX)
check("the census counts every slice, including ones not excerpted",
      sorted(line.split()[0] for line in cen.splitlines()),
      ["BRD-FY2021", "LANG-FY2021", "QA-FY2023", "QA-FY2024", "QA-FY2025",
       "RISK-FY2025"])
check("  with the right count on a slice holding two facts",
      "QA-FY2023      2 facts" in cen, True)

print("\nrepair_ids — the loop, without spending anything")


class FakeBackend:
    """Records what it was asked and returns a document with the ids removed.

    Exists so the repair LOOP is testable: how many calls it makes, when it stops,
    and — the one that costs money if it is wrong — that it makes none at all when
    there is nothing to repair.
    """

    name, cache_ttl = "fake", "5m"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def generate(self, *, model, system, prompt, max_tokens, effort,
                 schema=None, cache_prefix=None, stream=False):
        self.prompts.append(prompt)
        return model_client.LLMResult(
            text=self.reply(prompt), usage={}, backend=self.name, model=model,
            cache_ttl=self.cache_ttl, stop_reason="end_turn")

    def count_tokens(self, *, model, system, prompt):
        return None


GEN = {"model": "claude-opus-5", "max_tokens": 100, "effort": "high",
       "repair_effort": "medium"}
CLEAN = "Everything here resolves [QA-FY2024-5e714350]."
BROKEN = "A real one [QA-FY2024-5e714350] and an invented one [QA-FY2024-deadbeef]."

b = FakeBackend(lambda p: CLEAN)
out, usages, rounds = g.repair_ids(b, GEN, INDEX, CLEAN, "t", 2)
check("a document with no broken ids costs ZERO calls", len(b.prompts), 0)
check("  and comes back untouched", out, CLEAN)
check("  with round 0 recorded so the check is on the record", len(rounds), 1)

b = FakeBackend(lambda p: CLEAN)
out, usages, rounds = g.repair_ids(b, GEN, INDEX, BROKEN, "t", 2)
check("one broken id takes one call", len(b.prompts), 1)
check("  and stops as soon as it resolves", g.check_citations(out, INDEX)["unknown"], [])
check("  recording the excerpt it was given",
      rounds[1]["excerpt"]["ids_offered"] if len(rounds) > 1 else "NO ROUND RAN", 1)

# The model that cannot fix it. Two rounds, then it gives up and lets the caller's
# own report_failures exit non-zero -- it does not loop until it works.
b = FakeBackend(lambda p: BROKEN)
out, usages, rounds = g.repair_ids(b, GEN, INDEX, BROKEN, "t", 2)
check("an unfixable id stops at max_rounds", len(b.prompts), 2)
check("  and the still-broken id survives to be reported, not swallowed",
      g.check_citations(out, INDEX)["unknown"], ["QA-FY2024-deadbeef"])

b = FakeBackend(lambda p: CLEAN)
out, _, _ = g.repair_ids(b, GEN, INDEX, BROKEN, "t", 0)
check("max_rounds=0 disables repair entirely", len(b.prompts), 0)
check("  leaving the document exactly as it was", out, BROKEN)

# A citation whose FIELD CODE is not real. The repair loop must ACT on these, not
# merely report them — the gap this closes was that nothing acted, because nothing
# saw them.
def sent_prompt(fake: "FakeBackend") -> str:
    """The first prompt, or "" if no call was made.

    Guarded for the same reason as the round index above: when the subject of
    these checks regresses there IS no prompt, and `prompts[0]` would raise an
    IndexError that takes the rest of the file down with it. Proven — planting
    exactly that fault is how this helper came to exist.
    """
    return fake.prompts[0] if fake.prompts else ""


b = FakeBackend(lambda p: CLEAN)
out, _, rounds_m = g.repair_ids(b, GEN, INDEX, "Bad [MDNA-FY2021-deadbeef].", "t", 1)
check("a malformed citation triggers a repair round", len(b.prompts), 1)
check("  and the prompt says the field itself is not real",
      "NAME A FIELD THAT DOES NOT EXIST" in sent_prompt(b), True)
check("  and offers the census rather than a slice that cannot exist",
      "no slice to show" in sent_prompt(b), True)
# Guarded rather than indexed straight in: when this check's own subject regresses,
# no round runs and `rounds_m[1]` is an IndexError. A crash still stops the suite,
# but it stops it with a traceback instead of the name of what broke -- and the
# checks after it never run at all.
check("  recording that no ids were offered",
      rounds_m[1]["excerpt"]["ids_offered"] if len(rounds_m) > 1
      else "NO REPAIR ROUND RAN", 0)

# Mixed: one of each. Both must reach the prompt, under their own headings, and the
# well-formed one must still get its slice.
b = FakeBackend(lambda p: CLEAN)
g.repair_ids(b, GEN, INDEX, "One [QA-FY2024-deadbeef] two [MDNA-FY2021-deadbeef].",
             "t", 1)
check("an unresolvable id and a malformed one travel in the same round",
      sorted(s for s in ("QA-FY2024-deadbeef", "MDNA-FY2021-deadbeef",
                         "QA-FY2024-5e714350") if s not in sent_prompt(b)), [])

# THE PROMPT MUST NOT CARRY THE PACK. This is the whole reason the round was
# rebuilt, and it is the kind of regression that shows up only on the bill.
b = FakeBackend(lambda p: CLEAN)
g.repair_ids(b, GEN, INDEX, BROKEN, "t", 1)
sent = sent_prompt(b)
check("the repair prompt carries the document", BROKEN in sent, True)
check("  and names the broken id", "QA-FY2024-deadbeef" in sent, True)
check("  and is nowhere near pack-sized", len(sent) < 200_000, True)

print("\nthe real documents on disk")

# THE SKIP THAT HID ITSELF.
#
# This block used to `continue` when a generation record was missing, printing one
# dim "skipped" line and then a green "29 passed, 0 failed". Six of the 35 checks
# — every check that touches a document actually shipped — silently stopped
# running, and the summary line said nothing was wrong. That is precisely the
# false-assurance shape this file's own docstring warns about, one level up: a
# suite that passes because it did not run is worse than a suite that fails.
#
# It went unnoticed because data/pack/ was gitignored, so the records existed in
# the working tree and vanished in a clean checkout — the one place a green run
# gets believed. gen-*.json are committed now (see .gitignore), so absence means
# something is wrong rather than something is merely underived.
#
# The two causes are reported separately because they have different fixes:
#   record missing -> a committed file has been deleted; restore it.
#   index missing  -> the pack has not been built; one free, deterministic command.
# Folding them together would print the wrong instruction half the time.
n_docs = 0
idx_p = P.pack / "index.json"
idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else None

for slug, d in g.DOCS.items():
    rec_p = P.pack / f"gen-{slug}.json"
    if not rec_p.exists():
        FAIL += 1
        print(f"  FAIL  {d['file']}: generation record {rec_p.relative_to(ROOT)} is "
              f"MISSING.\n"
              f"          It is a committed file — model output, the only copy of "
              f"`text_before_repair`.\n"
              f"          Restore it (`git checkout -- {rec_p.relative_to(ROOT)}`) or "
              f"regenerate (~$3.50).\n"
              f"          Without it the three checks below do not run, and this suite "
              f"must not report green.")
        continue
    if idx is None:
        FAIL += 1
        print(f"  FAIL  {d['file']}: {idx_p.relative_to(ROOT)} is missing, so no id can "
              f"be resolved.\n"
              f"          The pack is derived and free to rebuild: "
              f"uv run python -m equity_research.build_pack")
        continue

    n_docs += 1
    rec = json.loads(rec_p.read_text(encoding="utf-8"))
    # `shipped_text` is the body actually written to output/ — identical to `text`
    # unless a recorded correction was applied after generation. See
    # `apply_corrections` in src/equity_research/generate_outputs.py: a correction is data in this
    # record, never a silent hand-edit of the document.
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

print(f"\n{PASS} passed, {FAIL} failed  ({n_docs} of {len(g.DOCS)} generated "
      f"document(s) checked)")
sys.exit(1 if FAIL else 0)
