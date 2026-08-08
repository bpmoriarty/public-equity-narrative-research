"""Claude Code PreToolUse hook: refuse shell heredocs that write source files.

Wired up in .claude/settings.json. Reads the tool call as JSON on stdin and
exits 2 to block it, with the reason on stderr.

WHY THIS FILE EXISTS
--------------------
Writing a Python or TOML file through a shell heredoc has corrupted a regex
three times in this project:

    cat > src/thing.py <<'EOF'      # even quoted, other layers can still eat it
    PAT = re.compile(r"\\bItem\\s+7\\b")
    EOF

...arriving on disk with 0x08 where the \\b should be. The file still imports and
still passes a linter; the pattern simply stops matching, and the check built on
it reports green forever. See tools/check_control_bytes.py for the full account.

This is the EARLY, advisory half of that defence: it stops the mistake at the
moment it is made, with the reason attached. The pre-commit scan is the real
gate — it inspects bytes rather than guessing at shell syntax, and it cannot be
fooled by a quoting form this pattern does not recognise.

WHAT IT ALLOWS
--------------
Heredocs that do NOT redirect into a .py or .toml file. Passing a commit message
to `git commit -F -` is the common one, and it is fine: nothing is written to a
source file, so a mangled escape cannot survive into code.
"""

from __future__ import annotations

import json
import re
import sys

# A heredoc introducer: <<EOF, <<-EOF, <<'EOF', <<"EOF".
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?[A-Za-z_][A-Za-z0-9_]*")

# A redirect or tee whose destination is a source file. `>` and `>>` cover
# `cat > x.py` and `cat >> x.py`; `tee` covers the piped form.
TARGET_RE = re.compile(
    r"""(?:>>?|\btee\b(?:\s+-a)?)\s*['"]?([^\s'"|;&>]+\.(?:py|toml))""")


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # A hook that cannot parse its input must not block the session.
        return 0

    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""

    if not HEREDOC_RE.search(command):
        return 0
    targets = TARGET_RE.findall(command)
    if not targets:
        return 0

    sys.stderr.write(
        "BLOCKED: this writes a source file through a shell heredoc.\n"
        f"  target(s): {', '.join(sorted(set(targets)))}\n"
        "\n"
        "Backslash escapes do not reliably survive that path. It has corrupted a\n"
        "regex three times in this repository: \\b arrived as byte 0x08 and \\1 as\n"
        "0x01, leaving a pattern that matches nothing while the file still imports,\n"
        "lints clean and reports green.\n"
        "\n"
        "Use the Write or Edit tool instead — same content, no shell in the path.\n"
        "(Heredocs that do not write .py/.toml files, such as `git commit -F -`,\n"
        "are not affected.)\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
