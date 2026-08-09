"""Refuse to commit text files containing raw control bytes.

Run:  uv run python tools/check_control_bytes.py          (staged files — what the hook does)
      uv run python tools/check_control_bytes.py --all    (every tracked file)

WHY THIS FILE EXISTS
--------------------
Three separate times in this project, a regex was written into a source file
through a shell heredoc, and the shell ate the backslash before it reached disk:

    \\b   (a word boundary)      became  0x08, a literal BACKSPACE byte
    \\1   (a backreference)      became  0x01, a literal START-OF-HEADING byte

The damage is invisible in every way that matters. The file still opens, still
imports, still passes a linter, and renders in an editor as if the escape were
there — a 0x08 usually shows as nothing at all. What changes is meaning: a
pattern that meant "match at a word boundary" silently becomes "match a
backspace character", which matches nothing, so the check built on it quietly
stops checking and reports green forever.

That is the worst failure shape this project has: a checker that passes because
it is broken. It cost real debugging time three times, and prose telling the
agent "don't use heredocs for regexes" did not prevent recurrence 2 or 3. This
script is the mechanical version of that instruction.

WHAT IT SCANS
-------------
The STAGED blob, not the working-tree file. Those differ whenever something was
edited after `git add`, and the staged blob is what a commit would actually
record — checking the working tree would let a corrupted blob through.

WHICH BYTES ARE ILLEGAL
-----------------------
Every C0 control byte except the three that legitimately appear in text:
tab (0x09), line feed (0x0A) and carriage return (0x0D). Everything else in
0x00-0x1F is a corruption marker, not content.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Tab, line feed and carriage return are the only C0 bytes that belong in text.
ALLOWED = {0x09, 0x0A, 0x0D}
ILLEGAL = frozenset(b for b in range(0x00, 0x20) if b not in ALLOWED)

# Named so the report says "BACKSPACE — the classic \b corruption" rather than
# leaving the reader to look up 0x08.
NAMES = {
    0x00: "NUL", 0x01: "START OF HEADING", 0x02: "START OF TEXT",
    0x03: "END OF TEXT", 0x04: "END OF TRANSMISSION", 0x05: "ENQUIRY",
    0x06: "ACKNOWLEDGE", 0x07: "BELL", 0x08: "BACKSPACE",
    0x0B: "VERTICAL TAB", 0x0C: "FORM FEED", 0x0E: "SHIFT OUT",
    0x0F: "SHIFT IN", 0x1B: "ESCAPE", 0x1F: "UNIT SEPARATOR",
}

# The escape each byte most likely came from. Used to name the probable cause,
# which is the difference between a useful report and a hex dump.
LIKELY_ESCAPE = {
    0x08: r"\b  (a regex word boundary)",
    0x01: r"\1  (a regex backreference)",
    0x02: r"\2  (a regex backreference)",
    0x03: r"\3  (a regex backreference)",
    0x04: r"\4  (a regex backreference)",
    0x05: r"\5  (a regex backreference)",
    0x06: r"\6  (a regex backreference)",
    0x07: r"\a  (an alert/bell escape)",
    0x0B: r"\v  (a vertical tab escape)",
    0x0C: r"\f  (a form feed escape)",
    0x1B: r"\e  (an ANSI escape)",
    0x00: r"\0  (a null escape)",
}

# Files whose bytes are meant to be arbitrary. Nothing here today, but a PDF or
# a PNG added later must not turn the hook into a false alarm.
BINARY_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".tar",
    ".xz", ".7z", ".woff", ".woff2", ".ttf", ".otf", ".xlsx", ".xls", ".docx",
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".parquet", ".db", ".sqlite",
}


def git(*args: str) -> bytes:
    """Run a git command from the repository root and return raw stdout."""
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(f"git {' '.join(args)} failed:\n{r.stderr.decode(errors='replace')}\n")
        raise SystemExit(2)
    return r.stdout


def staged_paths() -> list[str]:
    """Paths a commit would write a blob for.

    A: added.  C: copied.  M: modified.  R: renamed.  T: type changed.
    Only D (deleted) is excluded, because a deletion leaves no blob to check.

    R IS INCLUDED, and that is the whole point of this docstring. This filter
    originally read ACM, on the reasoning that "renames are excluded: there is
    no blob left to check". That reasoning confuses the two halves of a rename.
    Git reports a rename under its DESTINATION path, and the destination very
    much has a blob — often a modified one, since `git mv` plus edits is one
    R entry, not an R plus an M.

    The bug was found by the Phase 1 packaging commit, where 15 modules were
    moved with `git mv` and edited in the same commit: the scanner cheerfully
    reported "clean (14 files)" while skipping every one of the 15 files whose
    contents had actually changed. A commit that is mostly renames — exactly
    what the companies/ restructure will be — was the blind spot.

    That failure mode is the one this whole tool exists to prevent: a checker
    that reports green *because* it is not looking.
    """
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z")
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def tracked_paths() -> list[str]:
    out = git("ls-files", "-z")
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def staged_blob(path: str) -> bytes:
    """The staged content of `path`. `:path` is git's syntax for 'from the index'."""
    return git("show", f":{path}")


def worktree_blob(path: str) -> bytes:
    return (ROOT / path).read_bytes()


def scan(path: str, data: bytes) -> list[dict]:
    """Return one record per illegal byte found in `data`."""
    if Path(path).suffix.lower() in BINARY_SUFFIXES:
        return []
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        # Not text at all (an unlisted binary format). Byte values carry no
        # meaning here, so scanning them would only produce noise.
        return []

    hits = []
    line_no = 1
    line_start = 0
    for offset, byte in enumerate(data):
        if byte == 0x0A:
            line_no += 1
            line_start = offset + 1
            continue
        if byte in ILLEGAL:
            end = data.find(b"\n", offset)
            line = data[line_start: end if end != -1 else len(data)]
            hits.append({
                "path": path,
                "line": line_no,
                "col": offset - line_start + 1,
                "offset": offset,
                "byte": byte,
                "text": line.decode("utf-8", "replace"),
            })
    return hits


def render(hit: dict) -> str:
    """Format one hit, showing the offending byte in context as <0xNN>."""
    b = hit["byte"]
    name = NAMES.get(b, f"control byte 0x{b:02X}")
    # Make every control byte in the line visible; otherwise the caret below
    # points at what looks like empty space.
    shown = "".join(f"<0x{ord(c):02X}>" if ord(c) in ILLEGAL else c for c in hit["text"])
    lines = [
        f"  {hit['path']}:{hit['line']}:{hit['col']}  byte 0x{b:02X} ({name}), "
        f"offset {hit['offset']}",
        f"      {shown.rstrip()}",
    ]
    if b in LIKELY_ESCAPE:
        lines.append(f"      probably a corrupted {LIKELY_ESCAPE[b]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="scan every tracked file in the working tree instead of "
                         "the staged blobs")
    ap.add_argument("paths", nargs="*",
                    help="explicit paths to scan (bypasses git; used by the tests)")
    args = ap.parse_args()

    if args.paths:
        targets = [(p, Path(p).read_bytes()) for p in args.paths]
        where = "the given file(s)"
    elif args.all:
        targets = [(p, worktree_blob(p)) for p in tracked_paths()]
        where = "every tracked file"
    else:
        targets = [(p, staged_blob(p)) for p in staged_paths()]
        where = "the staged changes"

    hits = [h for path, data in targets for h in scan(path, data)]

    if not hits:
        print(f"control-byte scan: clean ({len(targets)} file(s) in {where})")
        return 0

    files = sorted({h["path"] for h in hits})
    print("=" * 74)
    print(f"CONTROL BYTES FOUND — {len(hits)} in {len(files)} file(s)")
    print("=" * 74)
    for h in hits:
        print(render(h))
    print()
    print("These bytes are almost never typed on purpose. The usual cause is a")
    print("regex escape written through a shell heredoc, where the shell consumed")
    print("the backslash: \\b became 0x08, \\1 became 0x01. It has happened three")
    print("times in this repository, and each time the affected check silently")
    print("stopped checking while still reporting green.")
    print()
    print("FIX: rewrite the affected line with the Write or Edit tool, not through")
    print("a shell heredoc. Then re-stage the file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
