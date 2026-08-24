"""Milestone 5f — hold the finished deliverables to the pack's binding constraints.

Deterministic. No network, no model calls, free to run as often as you like.

Run it:
    uv run python -m equity_research.verify_outputs
    uv run python -m equity_research.verify_outputs --only narrative-brief.md
    uv run python -m equity_research.verify_outputs --review        # also print the review lists

Reads `output/*.md` and `data/pack/`, writes `data/pack/verify-report.md`, and exits
non-zero if any hard check fails.

---------------------------------------------------------------------------
WHY THIS RUNS AGAINST THE RENDERED MARKDOWN, NOT THE GENERATION RECORD
---------------------------------------------------------------------------
`generate_outputs.py` already checks ids and quotations, and this module reuses those
same functions rather than writing a second opinion of them — two implementations of
"is this quotation verbatim" would drift, and the one that drifted quietly would be
the one that mattered.

What differs is the INPUT. The generator checks the text it just produced; this reads
the file on disk. So it catches a document edited by hand after generation, a document
written from a different pack, and a document whose provenance footer no longer
describes it. Those are the failure modes that survive a clean generation run, and
they are the reason this exists as a separate stage rather than a flag on the other.

---------------------------------------------------------------------------
HARD CHECKS AND REVIEW CHECKS, AND WHY THE LINE IS WHERE IT IS
---------------------------------------------------------------------------
A check that fires on correct documents is worse than no check, because it trains
whoever reads the report to skip that line — and then it is still firing on the day it
is right. So every check here is one of two kinds, and never a blend:

  HARD    Decidable with no judgment. Failing one means the document is wrong, and
          the run exits non-zero.
  REVIEW  A detector with known false positives. Listed for a human with the sentence
          attached, never gating anything, and each one's measured hit rate on the
          current documents is printed beside it so nobody mistakes a list for a
          failure.

Two constraints could only be enforced as review checks, and the measurements say why.
A first attempt at "never compare segment counts" fired on 6 sentences of which 6 were
false positives — the company's own "we have one reportable segment" quotation, and
PitchBook's "companies segment", a different sense of the word entirely. Tightened to
require years from BOTH disclosure bases in the same sentence, it fires 0 times. A
first attempt at Regulation FD labelling flagged 23 of 36 paragraphs, because the
documents establish the register once and then rely on the `QA-` id prefix to carry
it — which is exactly what the pack's own constraint says that prefix is for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import datetime, timezone

from equity_research._bootstrap import ROOT
from equity_research.generate_outputs import (ID_RE, PACK_SHA_RE, check_citations,
                                              check_quotes, stamped_pack_sha,
                                              verified_text, word_count)
from equity_research.paths import add_ticker_arg, paths

# Every data/ and output/ path for the company this run operates on.
# `paths()` resolves the ticker from --ticker, then EQR_TICKER, then the
# single company under companies/ -- see equity_research/paths.py.
P = paths()

PACK_DIR = P.pack
OUT_DIR = P.output

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load() -> tuple[str, dict, dict, dict, dict]:
    for f in ("pack.json", "index.json"):
        if not (PACK_DIR / f).exists():
            sys.exit(f"FATAL: data/pack/{f} not found.\n"
                     f"  Build it: uv run python -m equity_research.build_pack")
    payload = (PACK_DIR / "pack.json").read_text(encoding="utf-8")
    cfg = tomllib.loads((P.config_dir / "outputs.toml").read_text(encoding="utf-8"))
    gen = tomllib.loads(P.company_toml.read_text(encoding="utf-8"))
    if "verify" not in cfg:
        sys.exit("FATAL: config/outputs.toml has no [verify] block.")
    return (payload, json.loads(payload),
            json.loads((PACK_DIR / "index.json").read_text(encoding="utf-8")),
            cfg["verify"], gen["generation"])


# ---------------------------------------------------------------------------
# Numeric evidence — does the citation beside a figure actually show that figure?
# ---------------------------------------------------------------------------
# The gap this closes, from VERIFICATION.md D2: `check_quotes` only inspects text
# in quotation marks. A figure stated as a bare number — "9,935,476 votes against"
# — is never looked at, so a sentence can carry a precise figure, cite an id, and
# have that id resolve to a sentence which does not contain the figure. The brief
# promises the opposite: "Ids resolve to the exact quote each claim rests on."
#
# Three tiers, because pass/fail throws away the distinction that decides what to do:
#
#   QUOTED     the figure is in a cited fact's quote (or a risk delta's heading).
#              The promise holds. Nothing to report.
#   THIN       the figure is in the cited fact's pack `claim` but NOT its quote. The
#              number is real and traceable to the fact — the model read it in the
#              pack — but a reader resolving the id is shown a table lead-in
#              ("...with the number of votes set forth below:") instead of the
#              number. This is the D2 class: 21 vote facts carry a lead-in as their
#              quote.
#   UNSOURCED  the figure is in no cited fact at all, either way. The serious tier.
#
# CALIBRATED BEFORE IT WAS WRITTEN, per the rule from 10f that a check firing on
# correct documents is worse than no check. Measured on both deliverables:
#
#            narrative-brief.md   19 numbers  QUOTED=19  THIN= 0  UNSOURCED=0
#            discussion-points.md 65 numbers  QUOTED=46  THIN=17  UNSOURCED=2
#
# Zero false positives — but only after two bugs in the FIRST version of the
# tokenizer were found and fixed, both of which reported a defect in the document
# that was really a defect in the checker:
#
#   1. The lookbehind excluded `$`, so "$200,000" failed to match at the digit `2`
#      and matched the trailing "000" instead, inventing a figure the document never
#      states. Dollar amounts are the most common figure here.
#   2. "Item 5.07" — the SEC item number for a shareholder vote — was read as the
#      quantity 5.07. Asking which filing evidences 5.07 is a category error.
#
# Both are pinned in tests/test_verify_outputs.py.
#
# UNSOURCED IS NOW A HARD CHECK; THIN REMAINS REVIEW.
#
# The 2 UNSOURCED this check found on its first run were both D3 — 8,484 shares and
# $1.4 million cited to the FY2022 10-K, which carries only the buyback
# authorisation. Reading the filing to fix it turned up a second error in the same
# six words that the verification suite had missed: the programme was effective
# 2023-01-01, so the document's "by end-2022" was not merely mis-cited but
# impossible. Both corrected, tier went to zero, check promoted.
#
# That sequence is the argument for the promotion. The check shipped as `review` for
# one commit, fired on two real defects and nothing else, and only then was allowed
# to stop a build.
#
# THIN stays review. It stands at 19 and every one is a known instance of D2 —
# making it hard would block every build on a class that has been measured,
# recorded, and deliberately deferred to D2(b).

# Figures worth checking: money, thousands-separated counts, decimals. Bare 1-2
# digit numbers are excluded — "two of the three segments" is prose, not a filing
# figure, and chasing it buries the signal under noise.
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})(?![\w])")

# Digit strings that NAME something rather than counting it. Stripped before
# scanning rather than filtered afterwards, so they cannot re-enter by another path.
NOT_A_FIGURE = re.compile(
    r"\bItems?\s+\d+(?:\.\d+)?[A-Z]?"
    r"|\bRule\s+\d+[a-z]?-?\d*"
    r"|\bSection\s+\d+(?:\.\d+)?"
    r"|\b(?:Form\s+)?(?:10-[KQ]|8-K(?:/A)?|DEF\s*14A|DEFA\s*14A|SC\s*13[GD])",
    re.I)

YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def num_norm(n: str) -> str:
    """Thousands separators and a trailing .0 are formatting, not magnitude."""
    n = n.replace(",", "")
    return n[:-2] if n.endswith(".0") else n


def numbers_in(text: str) -> set[str]:
    """Every number appearing anywhere in a blob, normalised for comparison."""
    return {num_norm(m) for m in re.findall(r"\d[\d,]*\.?\d*", text or "")}


def claim_numbers(pack: dict) -> dict[str, set[str]]:
    """{fact id -> numbers in its pack `claim`}.

    Read from pack.json rather than index.json because the index deliberately does
    not carry `claim` — it holds the evidence (quote, source), not the assertion.
    The distinction is the whole point of this check: `claim` is what the model was
    shown, `quote` is what the reader can verify.
    """
    out: dict[str, set[str]] = {}
    for ydata in (pack.get("years") or {}).values():
        for items in (ydata.get("facts") or {}).values():
            for it in items or []:
                if isinstance(it, dict) and it.get("id"):
                    out[it["id"]] = numbers_in(
                        json.dumps(it.get("claim"), ensure_ascii=False))
    return out


def numeric_evidence(paras: list[str], index: dict,
                     claims: dict[str, set[str]]) -> dict[str, list[str]]:
    """Classify every figure in the prose against the facts cited in its paragraph.

    Paragraph scope, not sentence, because the paragraph is the pack's own citation
    granularity — a sentence-scope check reports a figure as unsupported whenever
    the evidence was cited one sentence earlier, which is normal, correct writing.
    """
    thin, unsourced = [], []
    for p in paras:
        ids = ID_RE.findall(p)
        if not ids:
            continue
        quoted = set().union(*[
            numbers_in((index.get(i, {}).get("quote") or "") + " "
                       + (index.get(i, {}).get("heading") or "")) for i in ids]) \
            if ids else set()
        claimed = set().union(*[claims.get(i, set()) for i in ids]) if ids else set()
        for raw in NUM_RE.findall(NOT_A_FIGURE.sub(" ", ID_RE.sub("", p))):
            n = num_norm(raw)
            if YEAR_RE.match(n):
                continue
            if n in quoted:
                continue
            where = f"“{raw}” in: {p[:120].strip()}…"
            (thin if n in claimed else unsourced).append(where)
    return {"thin": thin, "unsourced": unsourced}


def paragraphs(body: str) -> list[str]:
    return [p for p in body.split("\n\n") if p.strip()]


def sentences(body: str) -> list[str]:
    """Sentences, split WITHIN paragraphs only.

    Splitting the whole body at once welded the last sentence of one paragraph to the
    first heading of the next, and that artifact alone produced the single hit the
    segment detector reported. A sentence does not span a blank line.
    """
    return [s.strip() for p in paragraphs(body)
            for s in re.split(r"(?<=[.;:])\s+", p) if s.strip()]


def body_of(md: str) -> str:
    """The document without its own provenance footer.

    The footer quotes its own check results — "0 did not resolve" — and contains ids
    and figures that would otherwise be scanned as if they were claims in the prose.
    """
    return md.split("### Provenance")[0]


# ---------------------------------------------------------------------------
# Facts about the pack that the checks are derived from
# ---------------------------------------------------------------------------

def pack_facts(pack: dict, index: dict) -> dict:
    """Everything the checks need, computed from the pack — never named in source.

    CLAUDE.md: do not hard-code a value another stage already computes. Which years
    have a shareholder letter, and which disclose reportable segments, are properties
    of this company's filings; naming them here would make the verifier silently wrong
    for the next company and for this one after a re-extraction.
    """
    years = sorted(int(fy[2:]) for fy in pack["years"])
    letter_ids = {i for i, v in index.items()
                  if (v.get("source") or {}).get("section_key") == "letter_full_text"}
    letter_years = sorted({index[i]["fiscal_year"] for i in letter_ids})

    c2 = next((c for c in pack["constraints"] if "segment counts" in c["rule"]), None)
    product = reportable = []
    if c2:
        halves = c2["scope"].split(";")
        product = [int(y) for y in re.findall(r"FY(\d{4})", halves[0])]
        reportable = [int(y) for y in re.findall(r"FY(\d{4})", halves[1])] \
            if len(halves) > 1 else []

    return {
        "years": years,
        "letter_ids": letter_ids,
        "letter_years": letter_years,
        "no_letter": sorted(set(years) - set(letter_years)),
        "segment_product_years": product,
        "segment_reportable_years": reportable,
        "low_confidence": {i for i, v in index.items() if v.get("confidence") != "high"},
        "unverified_quote": {i for i, v in index.items()
                             if v.get("quote_verified") is False},
    }


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

class Report:
    """Accumulates results so the whole document is checked before anything exits.

    Deliberately not fail-fast. A run that stops at the first problem tells you one
    thing per run, and these are cheap to compute and expensive to iterate on.
    """

    def __init__(self, doc: str) -> None:
        self.doc, self.rows = doc, []

    def hard(self, tag: str, name: str, ok: bool, detail: str = "") -> None:
        # `tag` is a stable machine name. The human name is prose and gets reworded;
        # anything that needs to select a specific check -- the constraint repair in
        # generate_outputs.py skips the two provenance checks -- must match on the tag,
        # not on a substring of the sentence.
        self.rows.append({"kind": "HARD", "tag": tag, "name": name, "ok": ok,
                          "detail": detail, "items": []})

    def review(self, name: str, items: list[str], note: str = "") -> None:
        self.rows.append({"kind": "REVIEW", "name": name, "ok": True, "detail": note,
                          "items": items})

    @property
    def failures(self) -> list[dict]:
        return [r for r in self.rows if r["kind"] == "HARD" and not r["ok"]]


def verify(doc: str, md: str, pack: dict, index: dict, pf: dict, cfg: dict,
           sha: str) -> Report:
    r = Report(doc)
    body = body_of(md)
    paras, sents = paragraphs(body), sentences(body)
    ids = ID_RE.findall(body)

    # --- provenance: is this document written from the pack on disk? -----------
    # `stamped_pack_sha` comes from generate_outputs, which WRITES this footer.
    # This check used to carry its own copy of the regex; the generation stage's
    # freshness check now asks the same question, and two spellings of "which
    # pack is this document from" is how they come to disagree.
    stated = stamped_pack_sha(md)
    r.hard("prov_present", "provenance records the pack it was written from", bool(stated))
    if stated:
        r.hard("prov_matches", "that pack is the one on disk", stated == sha,
               "" if stated == sha else
               f"document says {stated[:16]}…, pack on disk is {sha[:16]}…. "
               f"Regenerate, or rebuild the pack from the ledger it was written from.")

    # --- constraint 5: ids resolve, quotations are the filing's characters ------
    c = check_citations(body, index)
    r.hard("ids_resolve", "every citation resolves to a fact in the pack", not c["unknown"],
           ", ".join(c["unknown"]))

    # A citation whose FIELD CODE does not exist — MDNA-FY2021-deadbeef. Until this
    # existed, ID_RE (built from the real codes) read such a token as prose, so it
    # was invisible to `ids_resolve` above and to the repair round that feeds it: a
    # reader saw a citation, every check saw a word.
    #
    # REVIEW, NOT HARD, FOR THIS ONE COMMIT. CLAUDE.md rule 3 — a new check gets its
    # output read once before it is allowed to stop anything, because roughly
    # eighteen bugs in this project were in checkers rather than in what they
    # checked. It is already fatal in generate_outputs.report_failures, which runs
    # at generation time where a false positive costs a re-run rather than
    # condemning a committed artifact. Promote to hard next commit.
    r.review("citations naming a field code that does not exist", c["malformed"],
             "Not the same as an unresolvable id: the field itself is not real, so "
             "there is no slice of the index the claim could have meant. Expected "
             "zero — this fired on nothing when it was added.")
    q = check_quotes(body, index)
    r.hard("quotes_verbatim", "every quotation is verbatim in a fact cited in the same paragraph",
           not q["bad"] and not q["elsewhere"],
           "; ".join([f'“{b["quote"][:60]}” matches no filing text' for b in q["bad"]]
                     + [f'“{b["quote"][:50]}” is really from '
                        f'{", ".join(b["actual_source"][:2])}' for b in q["elsewhere"]]))

    # A fact whose quote was never located in a source section has no verified text at
    # all. check_quotes cannot catch this: the quote string is stored, so a quotation
    # copied from it matches. Only the pack knows it was never found in a filing.
    quoted_unverified = sorted(pf["unverified_quote"].intersection(
        i for p in paras if '"' in p for i in ID_RE.findall(p)))
    r.hard("no_unverified_quoted", "no quotation rests on a fact whose quote was never verified",
           not quoted_unverified, ", ".join(quoted_unverified))

    # --- constraint 1: low-confidence facts are flagged where they are used -----
    flag = re.compile(cfg["low_confidence_flag_pattern"], re.I)
    unflagged = [p[:160] for p in paras
                 if pf["low_confidence"].intersection(ID_RE.findall(p))
                 and not flag.search(p)]
    r.hard("low_conf_flagged", "every paragraph resting on a low-confidence fact says so",
           not unflagged, f"{len(unflagged)} paragraph(s): "
                          + " | ".join(unflagged[:3]) if unflagged else "")

    # --- constraint 3: a vote claim carries its meeting date --------------------
    date = re.compile(cfg["date_pattern"])
    undated = [s[:160] for s in sents if "VOTE-FY" in s and not date.search(s)]
    r.hard("vote_dated", "every sentence citing a vote result names a date",
           not undated, " | ".join(undated[:3]))

    # --- constraint 4: the Regulation FD register is established ---------------
    fd = re.compile(cfg["reg_fd_pattern"], re.I)
    first_qa = next((m.start() for m in re.finditer(r"\bQA-FY", body)), None)
    first_fd = next((m.start() for m in fd.finditer(body)), None)
    if first_qa is None:
        r.hard("reg_fd_established", "Regulation FD register established before the first QA citation", True,
               "no investor_qa facts cited")
    else:
        r.hard("reg_fd_established", "Regulation FD register established before the first QA citation",
               first_fd is not None and first_fd < first_qa,
               "" if first_fd is not None and first_fd < first_qa else
               "the document cites investor_qa facts without ever naming the register. "
               "These are voluntary, unaudited disclosures and the reader has to be "
               "told once, in the text, not only by the id prefix.")

    # 4b: per-year QA counts reflect how many questions investors happened to ask,
    # not anything about the company, so they must never be laid out as a trend.
    # Run on PARAGRAPHS, not sentences. A year-by-year enumeration is written with
    # semicolons and a colon — "answered: 2021, 113; 2022, 157; 2023, 231" — and the
    # sentence splitter breaks on both, so it fragments precisely the shape this check
    # is looking for. Tested against that exact string; on sentences it found nothing.
    series = re.compile(r"(?:\b20\d\d\b\D{0,20}\b\d+\b\D{0,40}){3,}")
    qa_series = [p[:160] for p in paras
                 if re.search(cfg["qa_subject_pattern"], p, re.I) and series.search(p)]
    r.hard("qa_not_a_series", "investor_qa counts are never presented as a year-by-year series",
           not qa_series, " | ".join(qa_series[:2]))

    # --- constraint 6: the shareholder letter is not present for every year -----
    cited_letter_years = sorted({index[i]["fiscal_year"] for i in ids
                                 if i in pf["letter_ids"]})
    if cited_letter_years and pf["no_letter"]:
        # The document must name the missing year alongside the word "letter". The
        # brief failed this on its first run: it built a five-year arc partly out of
        # the letters and never said the first year has none, so an apparent change
        # in leadership voice at the FY2021/FY2022 boundary reads as a change in tone
        # when it may be a missing document.
        told = any(re.search(r"letter", s, re.I) and any(str(y) in s for y in pf["no_letter"])
                   for s in sents)
        r.hard("letter_gap_named", "the years with no shareholder letter are named where letters are used",
               told, "" if told else
               f"cites letter-sourced facts for {cited_letter_years} and never says "
               f"FY{', FY'.join(str(y) for y in pf['no_letter'])} has none")
    else:
        r.hard("letter_gap_named", "the years with no shareholder letter are named where letters are used",
               True, "no letter-sourced facts cited" if not cited_letter_years else
                     "a letter is present for every year in the window")

    # --- shape: the document is the document SPEC.md asked for ------------------
    want = cfg["required_headings"].get(doc, [])
    missing = [h for h in want if h.lower() not in body.lower()]
    r.hard("sections_present", "every required section is present", not missing, ", ".join(missing))

    lo, hi = cfg["word_range"].get(doc, [0, 10**9])
    words = word_count(body)
    r.hard("length", f"length is within {lo:,}–{hi:,} words", lo <= words <= hi, f"{words:,} words")

    # --- REVIEW: detectors with known false positives ---------------------------
    numseg = re.compile(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b"
                        r"[^.]{0,40}\b(?:reportable |operating )?segments?\b", re.I)
    both = []
    for s in sents:
        if not numseg.search(s):
            continue
        yrs = {int(y) for y in re.findall(r"\b(20\d\d)\b", s)}
        if yrs & set(pf["segment_product_years"]) and yrs & set(pf["segment_reportable_years"]):
            both.append(s[:200])
    r.review("segment counts compared across the disclosure-basis change", both,
             f"a count comparison spanning FY{pf['segment_product_years']} "
             f"(product areas) and FY{pf['segment_reportable_years']} (reportable "
             f"segments) is a change in disclosure, not necessarily in the business")

    # --- D2: does the citation beside a figure actually show that figure? -------
    ne = numeric_evidence(paras, index, claim_numbers(pack))
    # HARD as of the D3 fix. It shipped as a review check for exactly one commit —
    # long enough to prove it fired on real defects and nothing else. It found the
    # only two unsourced figures in either deliverable (8,484 shares and $1.4
    # million, cited to a 10-K containing neither), those were corrected, and the
    # tier went to zero. A figure supported by nothing a reader can resolve is not a
    # style matter, and the check has now earned the right to stop a build.
    r.hard("figures_evidenced",
           "every figure stated in prose appears in a fact cited beside it",
           not ne["unsourced"],
           "; ".join(ne["unsourced"][:5])
           + (f" (+{len(ne['unsourced']) - 5} more)" if len(ne["unsourced"]) > 5 else ""))
    r.review("figures traceable to a cited fact's claim but NOT to its quote",
             ne["thin"],
             "VERIFICATION.md D2. The number is real and the model read it in the "
             "pack, but resolving the id shows a table lead-in rather than the "
             "figure — which is not what this document promises in its provenance. "
             "Review, not failure, until D2(b) decides whether to capture table rows "
             "into the vote quotes")

    heavy = []
    for p in paras:
        pid = ID_RE.findall(p)
        qa = [i for i in pid if i.startswith("QA-")]
        if qa and len(qa) / len(pid) >= cfg["qa_majority_share"] and not fd.search(p):
            heavy.append(p[:200])
    r.review("paragraphs resting mostly on investor_qa with no local Reg FD marker",
             heavy,
             "not a failure: the register is established once and the `QA-` id prefix "
             "carries it thereafter, which is what the pack's own constraint says the "
             "prefix is for. Listed so a reader can confirm none of these reads as a "
             "10-K disclosure")

    return r


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_report(reports: list[Report], sha: str, stamp: str) -> str:
    lines = ["# Output verification", "",
             f"Generated {stamp}. Deterministic — no model call, free to re-run.", "",
             f"**`pack.json` sha256** `{sha}`", "",
             "Hard checks are decidable and gate the run. Review lists are detectors "
             "with known false positives: they are printed for a human and never fail "
             "anything.", ""]
    for r in reports:
        n_fail = len(r.failures)
        lines += [f"## {r.doc} — {'FAIL' if n_fail else 'pass'}", ""]
        for row in r.rows:
            if row["kind"] != "HARD":
                continue
            mark = "x" if row["ok"] else " "
            lines.append(f"- [{mark}] {row['name']}"
                         + (f" — **{row['detail']}**" if row["detail"] and not row["ok"]
                            else f" ({row['detail']})" if row["detail"] else ""))
        lines.append("")
        for row in r.rows:
            if row["kind"] != "REVIEW":
                continue
            lines += [f"**Review — {row['name']}: {len(row['items'])}**", "",
                      f"> {row['detail']}", ""]
            lines += [f"- {it}…" for it in row["items"][:10]] + [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Milestone 5f — verify the deliverables.")
    ap.add_argument("--only", help="one document, by file name")
    ap.add_argument("--review", action="store_true", help="print the review lists too")
    add_ticker_arg(ap)

    args = ap.parse_args()

    payload, pack, index, cfg, gen = load()
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    pf = pack_facts(pack, index)

    docs = [d for d in cfg["documents"] if not args.only or d == args.only]
    if not docs:
        sys.exit(f"FATAL: no document matching {args.only!r}. "
                 f"Known: {', '.join(cfg['documents'])}")

    print(f"Verifying {len(docs)} document(s) against pack {sha[:16]}…")
    print(f"  letters present FY{pf['letter_years']}, absent FY{pf['no_letter']}; "
          f"{len(pf['low_confidence'])} low-confidence facts in the pack")
    print()

    reports = []
    for doc in docs:
        p = OUT_DIR / doc
        if not p.exists():
            sys.exit(f"FATAL: {p} not found.\n"
                     f"  Generate it: uv run python -m equity_research.generate_outputs")
        r = verify(doc, p.read_text(encoding="utf-8"), pack, index, pf, cfg, sha)
        reports.append(r)

        print(f"{doc} — {'FAIL' if r.failures else 'pass'}")
        for row in r.rows:
            if row["kind"] == "HARD":
                print(f"  [{'x' if row['ok'] else '!'}] {row['name']}"
                      + (f"\n        {row['detail']}" if row["detail"] and not row["ok"]
                         else ""))
        for row in r.rows:
            if row["kind"] == "REVIEW":
                print(f"  --  review: {row['name']}: {len(row['items'])}")
                if args.review:
                    for it in row["items"]:
                        print(f"        {it}…")
        print()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    P.verify_report.write_text(
        render_report(reports, sha, stamp), encoding="utf-8")

    total = sum(len(r.failures) for r in reports)
    print("=" * 72)
    # Printed from the real path rather than a literal: with the report now under
    # companies/<TICKER>/, a hardcoded "data/pack/..." would name a file that does
    # not exist and send a reader looking in the wrong place.
    print(f"wrote {P.verify_report.relative_to(ROOT).as_posix()}")
    if total:
        sys.exit(f"\nFATAL: {total} hard check(s) failed across "
                 f"{sum(1 for r in reports if r.failures)} document(s).")
    print(f"{len(docs)} document(s), every hard check passed.")


if __name__ == "__main__":
    main()
