"""Console-script entry point for the `pipeline` command.

STUB — not implemented yet. The pipeline stages are currently run individually
(`uv run python -m equity_research.discover`, `...fetch`, etc.); a single
orchestrating `pipeline` command is planned for a later phase. This module
exists now only so `[project.scripts] pipeline = "equity_research.cli:main"`
resolves to something importable, without pretending the orchestration works.
"""

from __future__ import annotations


def main() -> int:
    print("not implemented yet — see Phase 4")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
