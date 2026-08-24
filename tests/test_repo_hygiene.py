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
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# fixture FIRST: it sets EQR_TICKER, which every later paths() call reads.
from fixture import P  # noqa: E402
from equity_research.paths import known_tickers  # noqa: E402

# ROOT stays: this file walks the WHOLE repository looking for paid model output,
# which is a repo-level question, not a per-company one — a company folder added
# tomorrow with ignored facts/ must fail this suite too. `P` is only for the
# checks that name a specific company's artifacts, and comes from
# tests/fixture.py so that a second company folder does not make it ambiguous.

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


# A string literal that IS a path: starts with data/ or output/ and contains no
# whitespace. The whitespace test is what separates a path from prose about a
# path -- "data/ledger/ as the record of what the model returned" mentions a
# directory in a sentence and is fine, while "data/pack/pack.json" is a path
# being built without asking paths.py.
#
# Deliberately narrow. A check that fires on the two perfectly good error
# messages in build_pack.py and extract_facts.py would be read once, dismissed,
# and then ignored on the day it was right.
PATH_LITERAL = re.compile(r'["\'](?:data|output)/[^"\'\s]*["\']')

# paths.py is the definition site -- it is where these literals are SUPPOSED to
# live. settings.py names config filenames, not data paths, but is excluded with
# it so the pair that owns path resolution is treated the same way.
PATH_LINT_EXEMPT = {"paths.py", "settings.py"}


def path_literals() -> list[str]:
    """Every hardcoded data/ or output/ path literal in the package."""
    src = ROOT / "src" / "equity_research"
    out = []
    for p in sorted(src.glob("*.py")):
        if p.name in PATH_LINT_EXEMPT:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if PATH_LITERAL.search(line):
                out.append(f"{p.name}:{i}: {line.strip()[:90]}")
    return out


# ---------------------------------------------------------------------------
# THE MANIFEST-PATH LINT
# ---------------------------------------------------------------------------
# Manifests store paths relative to the COMPANY folder ("data/raw/..."), and
# `P.resolve()` re-roots them. `P.relative()` is the one correct way to produce
# one. `relative_to(ROOT)` produces "companies/MORN/data/raw/..." instead, which
# P.resolve() rejects outright.
#
# Three writers were left using relative_to(ROOT) after the Phase 2 move:
# fetch.py's manifest `path`, extract_sections.py's `out`, triage_8k.py's
# `trimmed_path`. All three survived eleven days because none of those stages
# had been re-run since the migration — every stage was reading manifests
# written BEFORE the move, which were correct. The first full orchestrated run
# hit all three at once.
#
# WHY THIS IS A SOURCE LINT AND NOT ONLY A DATA CHECK
# The manifests on disk were correct for the entire time the bug existed. A
# check that scanned the data would have passed every day and then failed only
# after the damage was done. The bug lived in source, so the check has to look
# at source to catch it early. The data scan below is the backstop, not the
# primary.
#
# WHAT SEPARATES A BUG FROM A LEGITIMATE USE
# The lint sees 21 `.relative_to(ROOT)` calls in the package and flags none of
# them. (A plain text search finds 25: the other four are prose in comments
# explaining this rule, which the leading `\.` in ROOT_RELATIVE excludes.) Every
# one of them builds a string for a HUMAN to read — inside an f-string in a
# print() or a sys.exit(). The three bugs all built a string to STORE. So a line
# is exempt if it is a print/exit call or the continuation of one (a line that
# begins with an f-string literal), and suspect otherwise.
#
# This is a heuristic and it is worth being honest about the edge it cannot see:
# a display-only use that is neither on a print/exit line nor starts with `f"`
# will be flagged wrongly. That misfire is loud, appears the moment the line is
# written, and its fix is usually `P.relative()` anyway. The alternative —
# matching `str(` or `.replace(` — was tried first and misses
# `dest.relative_to(ROOT).as_posix()`, which is the same bug spelled without a
# str() call.
ROOT_RELATIVE = re.compile(r"\.relative_to\(ROOT\)")


def stores_root_relative_path(line: str) -> bool:
    """True if this line looks like it STORES a relative_to(ROOT) path.

    Kept as a function taking one line so it can be tested against both the
    three real bug shapes and the legitimate display uses, rather than only
    against the package as it currently stands. A lint that has only ever seen
    correct input is untested (CLAUDE.md rule 3).
    """
    if not ROOT_RELATIVE.search(line):
        return False
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    # Display uses: the call itself, or a continuation of its message.
    if "print(" in line or "sys.exit(" in line:
        return False
    if stripped.startswith('f"') or stripped.startswith("f'"):
        return False
    return True


def root_relative_offenders() -> list[str]:
    """Every line in the package that stores a ROOT-relative path."""
    src = ROOT / "src" / "equity_research"
    out = []
    for p in sorted(src.glob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if stores_root_relative_path(line):
                out.append(f"{p.name}:{i}: {line.strip()[:90]}")
    return out


def root_relative_total() -> int:
    """How many relative_to(ROOT) calls exist at all, offending or not.

    Non-vacuity. If this reaches zero the lint above is guarding nothing, and
    the reason would be that the idiom was renamed rather than that the code got
    safer.
    """
    src = ROOT / "src" / "equity_research"
    return sum(len(ROOT_RELATIVE.findall(p.read_text(encoding="utf-8")))
               for p in sorted(src.glob("*.py")))


# Keys whose value is a path into the company folder. `url` is deliberately not
# here (it is an EDGAR URL), and neither is anything from config.
PATH_KEYS = ("path", "out", "trimmed_path")


def manifest_path_values(doc) -> list[tuple[str, str]]:
    """Every (key, value) in a manifest that is supposed to be a path.

    Walks the whole document rather than naming the field per manifest: the
    three bugs were in three different fields at three different nesting
    depths, and an enumerated list of fields is one more thing to forget to
    update when a fourth appears.
    """
    found = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if isinstance(v, str) and v and (k in PATH_KEYS
                                             or k.endswith("_path")):
                found.append((k, v))
            else:
                found += manifest_path_values(v)
    elif isinstance(doc, list):
        for item in doc:
            found += manifest_path_values(item)
    return found


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
    print("PATHS COME FROM CompanyPaths — a literal here would find the wrong company")
    offenders = path_literals()
    check("no hardcoded data/ or output/ path literals in src/equity_research/",
          not offenders,
          "These build a path from a string instead of asking paths.py, so they "
          "resolve to the repository root rather than to the company being run "
          "-- which reads or writes the wrong company's files without failing:\n" +
          "\n".join(f"  {o}" for o in offenders) +
          "\nUse the matching CompanyPaths property (P.ledger, P.pack, P.output, "
          "...) or P.resolve() for a manifest-relative value.")

    print()
    print("MANIFEST PATHS ARE COMPANY-RELATIVE — relative_to(ROOT) is the bug")

    # Both directions on the discriminator, on synthetic lines, so this lint is
    # tested rather than merely unfired. The three "bug" lines below are the
    # actual pre-fix source, verbatim.
    bugs = [
        '                    "path": str(dest.relative_to(ROOT)).replace("\\\\", "/"),',
        '                row["out"] = str((dest_dir / f"{key}.txt").relative_to(ROOT)).replace("\\\\", "/")',
        '                "trimmed_path": str(tp.relative_to(ROOT)).replace("\\\\", "/"),',
        # The same bug without str(), which an earlier version of this lint missed.
        '        rec["path"] = dest.relative_to(ROOT).as_posix()',
    ]
    caught = [b for b in bugs if stores_root_relative_path(b)]
    check(f"all {len(bugs)} known bug shapes are flagged",
          len(caught) == len(bugs),
          "Not flagged:\n" + "\n".join(f"  {b.strip()}" for b in bugs
                                       if b not in caught))

    legit = [
        '    print(f"wrote {(PACK_DIR / \'pack.json\').relative_to(ROOT)}, "',
        '        sys.exit(f"FATAL: {CORRECTIONS.relative_to(ROOT)} is not usable")',
        '              f"{CORRECTIONS.relative_to(ROOT)}")',
        '    # row["out"] = str(x.relative_to(ROOT))  -- how this used to work',
        '        return path.resolve().relative_to(self.company.resolve()).as_posix()',
    ]
    misfired = [l for l in legit if stores_root_relative_path(l)]
    check(f"none of the {len(legit)} legitimate shapes are flagged",
          not misfired,
          "Wrongly flagged — this lint would be dismissed as noise:\n"
          + "\n".join(f"  {l.strip()}" for l in misfired))

    total = root_relative_total()
    check(f"the lint has something to guard ({total} relative_to(ROOT) calls)",
          total > 0,
          "No relative_to(ROOT) anywhere in the package. Either the idiom was "
          "renamed — in which case this lint now matches nothing and protects "
          "nothing — or every use really is gone.")

    offenders = root_relative_offenders()
    check("no relative_to(ROOT) path is stored in src/equity_research/",
          not offenders,
          "These store a path relative to the REPOSITORY ROOT, but manifests "
          "store paths relative to the COMPANY folder — so P.resolve() rejects "
          "every one of them and the next stage dies on the first record. Note "
          "the writer itself exits 0; the damage surfaces two stages later:\n"
          + "\n".join(f"  {o}" for o in offenders)
          + "\nUse P.relative(<path>) instead. See THE MANIFEST CONTRACT in "
            "paths.py.")

    print()
    print("...AND THE MANIFESTS ON DISK AGREE — the backstop, after a stage runs")

    # inventory.json and triage-8k.json are committed, so they are always here.
    # fetch-manifest.json and sections-manifest.json are derived and gitignored:
    # a fresh clone legitimately has neither, so they are scanned when present
    # rather than required. Scanning zero manifests is still a failure.
    manifests = {
        "inventory.json": (P.inventory, True),
        "triage-8k.json": (P.triage_json, True),
        "fetch-manifest.json": (P.fetch_manifest, False),
        "sections-manifest.json": (P.sections_manifest, False),
    }
    values: list[tuple[str, str, str]] = []   # (manifest, key, value)
    for label, (path, committed) in manifests.items():
        if not path.exists():
            check(f"{label} is present", not committed,
                  f"{label} is committed but missing from disk. A committed "
                  f"record that is gone is not a clean checkout, it is a loss.")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        values += [(label, k, v) for k, v in manifest_path_values(doc)]

    check(f"the scan found manifest paths at all ({len(values)} across "
          f"{len({v[0] for v in values})} manifest(s))",
          len(values) > 0,
          "No path-shaped values found in any manifest. Either the manifests "
          "are empty or the field names changed, and this backstop is now "
          "checking nothing.")

    wrong = [f"{m}: {k} = {v}" for m, k, v in values
             if not v.startswith(("data/", "output/"))]
    check(f"all {len(values)} manifest path(s) are company-relative",
          not wrong,
          "P.resolve() raises on every one of these, so the stage that reads "
          "them dies on its first record:\n"
          + "\n".join(f"  {w}" for w in wrong[:10])
          + ("\n  ..." if len(wrong) > 10 else ""))

    backslashed = [f"{m}: {k} = {v}" for m, k, v in values if "\\" in v]
    check(f"no manifest path contains a backslash",
          not backslashed,
          "A Windows separator in a stored path makes the manifest "
          "platform-specific, so the same run on Linux produces a different "
          "file (CLAUDE.md rule 4: run twice, diff nothing). P.relative() "
          "always emits forward slashes:\n"
          + "\n".join(f"  {b}" for b in backslashed[:10]))

    print()
    print("NO MOJIBAKE — the blind spot in the control-byte scan")

    # tools/check_control_bytes.py enforces CLAUDE.md rule 2 by looking for raw
    # control bytes, the signature of a regex escape mangled by a shell heredoc.
    # It cannot see the OTHER way a shell corrupts source: an encoding round
    # trip. Read a UTF-8 file as cp1252 and write it back as UTF-8 and every
    # non-ASCII character becomes the two or three Latin-1 characters its bytes
    # happen to mean in cp1252 — an ellipsis turns into an a-circumflex, a euro
    # sign and a broken bar. The file still parses, still imports, and the
    # control-byte scan still reports clean.
    #
    # Deliberately DESCRIBED rather than shown: spelling the corrupted form out
    # here put mojibake in this file and made this very check fail on it. That is
    # the check working, and it is also why the markers below are derived rather
    # than typed.
    #
    # Not hypothetical. Five test files were edited with PowerShell string
    # replacement during Phase 4.6; `Get-Content -Raw` reads as cp1252 in
    # PowerShell 5.1, and all five came back with 7 to 34 corrupted sequences
    # each. Three checks in test_generate_outputs.py failed — the ones whose
    # fixtures contain an ellipsis and curly quotes — and the scan said clean.
    # The corruption was in the test fixtures, so what it broke was the ability
    # of those tests to detect a misquotation.
    #
    # The signatures are DERIVED by performing the corruption, not typed out.
    # Typing them would make this file contain mojibake and flag itself — which
    # it did, on the first run of this check. Deriving them also means the
    # markers cannot be subtly wrong: they are whatever the real round trip
    # produces.
    def as_cp1252(s: str) -> str:
        """What `s` becomes when its UTF-8 bytes are read as cp1252."""
        return s.encode("utf-8").decode("cp1252", errors="replace")

    # An em dash gives the two-character lead-in shared by every misread
    # punctuation mark; a non-breaking space gives the one-character form.
    # Neither occurs in correctly encoded English or code.
    #
    # Written as escapes, not as the characters themselves: the first version
    # used a literal non-breaking space, which is indistinguishable from a
    # normal one in an editor. A normal space derives the marker " ", which is
    # present in every file ever written — both checks below failed, and
    # neither said anything about why.
    MOJIBAKE = (as_cp1252('—')[:2], as_cp1252(' ')[:1])

    def mojibake_in(path: Path) -> list[str]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return [m for m in MOJIBAKE if m in text]

    # Both directions, on synthetic input, so this is tested rather than merely
    # unfired: a checker that has only seen clean files is not known to work.
    clean_sample = ("an ellipsis … and a dash — and curly quotes "
                    "“like this”, plus café, naïve and a "
                    "non-breaking space")
    check("the signature matches text that really has been round-tripped",
          all(m in as_cp1252(clean_sample) for m in MOJIBAKE),
          "The markers no longer match text that IS corrupted, so this check "
          "protects nothing.")
    check("correctly encoded punctuation is NOT flagged",
          not any(m in clean_sample for m in MOJIBAKE),
          "The markers fire on legitimate UTF-8, so this check would be "
          "dismissed as noise on the day it was right.")

    text_ext = {".py", ".md", ".toml", ".json", ".txt", ".cfg", ".yml", ".yaml"}
    corrupted = []
    for rel in sorted(tracked):
        p = ROOT / rel
        if p.suffix.lower() not in text_ext or not p.is_file():
            continue
        hits = mojibake_in(p)
        if hits:
            corrupted.append(f"{rel}: {', '.join(hits)}")
    check(f"no tracked text file contains mojibake "
          f"({len(tracked)} tracked, {len(text_ext)} extensions scanned)",
          not corrupted,
          "These were almost certainly written by a tool that read them in one "
          "encoding and wrote them in another — PowerShell's Get-Content reads "
          "cp1252 by default. Restore from git and redo the edit with a "
          "UTF-8-aware editor:\n"
          + "\n".join(f"  {c}" for c in corrupted[:10]))

    print()
    print("THE TEMPLATE MUST NOT FALL BEHIND — a missing key fails on a new company")

    # companies/_template/ is a hand-maintained copy of a company's config,
    # because company.toml is 125 comment lines that no TOML writer can preserve
    # (see the note above cmd_init in cli.py). The cost of hand-maintained is
    # drift: add a [generation] setting, update MORN, forget the template, and
    # `pipeline init TSLA` produces a config missing a key. The failure then
    # lands on whoever starts the next company rather than on whoever changed the
    # schema, which is the worst place for it.
    #
    # Compared as TABLES and KEYS, never values — the template's values are
    # deliberately blank or placeholder, which is the whole point of it.
    template = ROOT / "companies" / "_template" / "company.toml"
    check("companies/_template/company.toml exists", template.exists(),
          "`pipeline init` copies this file; without it no new company can be "
          "created.")

    def key_shape(path: Path) -> set[str]:
        """{"table.key"} for every setting, ignoring values."""
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        out = set()
        for table, body in doc.items():
            if isinstance(body, dict):
                out |= {f"{table}.{k}" for k in body}
            else:
                out.add(table)
        return out

    if template.exists():
        want = key_shape(template)
        # Non-vacuity: an empty key set would make every comparison below pass
        # by agreeing about nothing.
        check(f"the template declares settings at all ({len(want)} keys)",
              len(want) > 0,
              "No tables or keys parsed out of the template, so the comparisons "
              "below are vacuous.")
        # ONE check across every company, not one check per company.
        #
        # The per-company version was written first and is wrong here: it made
        # this file's check COUNT depend on how many company folders happen to
        # exist, so `pipeline init` for a second company took it from 20 to 21
        # and the count gate failed. That gate exists to catch checks
        # disappearing; a number that moves when someone adds a company is a
        # number that cannot do that job. Caught by running the suite with a
        # throwaway company present, which is the state a colleague is in.
        tickers = known_tickers()
        problems = []
        for t in tickers:
            cfg = ROOT / "companies" / t / "company.toml"
            if not cfg.exists():
                problems.append(f"{t}: no company.toml at all")
                continue
            diff = key_shape(cfg) ^ want
            if diff:
                problems.append(
                    f"{t}: only in {t} {sorted(key_shape(cfg) - want)}; "
                    f"only in template {sorted(want - key_shape(cfg))}")
        # The three fields that must arrive EMPTY in a new company. `cik` and
        # `resolved_name` are tripwires: discovery resolves the CIK from the
        # ticker and stops if a value disagrees. A template that shipped a real
        # CIK would scaffold a config pointing at the wrong company, and every
        # stage would then run perfectly on another company's filings — the
        # failure this project guards against hardest, arriving by the one route
        # nobody would think to check.
        tmpl = tomllib.loads(template.read_text(encoding="utf-8"))
        blanks = {k: tmpl.get("company", {}).get(k)
                  for k in ("ticker", "cik", "resolved_name")}
        check("the template's ticker, cik and resolved_name are all empty",
              all(v == "" for v in blanks.values()),
              f"Got {blanks}. Whoever refreshed this template left a real "
              f"company's values in it.")

        check(f"all {len(tickers)} company config(s) agree with the template "
              f"on every key",
              not problems,
              "\n".join(problems)
              + "\nAdd the setting to both, or the next `pipeline init` "
                "scaffolds a config that is missing it. Keys are compared, "
                "never values — the template's values are deliberately blank.")

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
