"""Configuration loading, the pricing table, and window validation.

WHAT LIVES WHERE
----------------
Two kinds of configuration, and the distinction is the whole point of the
`companies/` layout:

  config/forms.toml          GLOBAL DEFAULTS. Company-neutral. Every company
  config/sections.toml       reads these unless it overrides them. The values in
  config/outputs.toml        them were calibrated on MORN, which is exactly why
                             they need to be overridable rather than assumed.

  companies/<T>/company.toml COMPANY-SPECIFIC. Ticker, CIK, fiscal window,
  companies/<T>/corrections.toml  model settings, and hand-verified corrections.
                             Moved whole; never layered, because "half a
                             company.toml" is not a meaningful thing.

A company may override any global default by dropping a partial file at
`companies/<T>/overrides/<name>.toml`. Absent means "use the global defaults" —
the common case, and MORN's, since the global values *are* MORN's.

THE MERGE RULE
--------------
`deep_merge` recurses into tables and replaces everything else:

    tables (dicts)      recurse, so an override may set one key of a table
                        without restating the other twelve
    scalars             replace
    arrays              replace WHOLESALE, including arrays of tables

Arrays are replaced rather than concatenated or key-matched, and that is
deliberate. `sections.toml` holds arrays of section-pattern tables whose ORDER
is load-bearing — patterns are tried in sequence, and the first match wins.
Merging two such arrays element-by-element would produce a pattern list that
neither file describes, and the failure would show up as a section boundary
landing in the wrong place three stages later. Replacing wholesale means an
override that touches one pattern restates the list, which is more typing and
exactly one obvious behaviour.

WINDOW VALIDATION
-----------------
`1 <= years <= 10`, hard error outside. The upper bound is not arbitrary: the
pack for five MORN years measures 352,194 tokens, quality degrades before the
1M context window binds (the measured comfort zone is ~450-500K), and ten
MORN-density years would land near 700K. Above ten years the honest answer is
"subset the pack or chunk by era", not "send it and hope", so the window refuses
rather than silently producing a worse document.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from equity_research.paths import CompanyPaths, paths

# ---------------------------------------------------------------------------
# Which config files are global defaults, and which belong to a company
# ---------------------------------------------------------------------------

# Live in config/, may be overridden per company via companies/<T>/overrides/.
#
# `llm` is global for a different reason than the other three: it describes the
# machine the pipeline runs on and what that machine can reach — a Claude seat,
# an API key, where the CLI lives — rather than anything about a company. It is
# layerable anyway, so a company that needs a different backend can say so.
GLOBAL_CONFIGS = ("forms", "sections", "outputs", "llm")

# Live in companies/<T>/, never layered.
COMPANY_CONFIGS = ("company", "corrections")

# Config files a stage may reference that are optional. A company with no
# corrections has no corrections.toml, and that is not an error — it means zero
# corrections, which is the normal state for a company nobody has audited yet.
OPTIONAL_CONFIGS = ("corrections",)


# ---------------------------------------------------------------------------
# Pricing — one table, with the date it was true
# ---------------------------------------------------------------------------

# Anthropic list prices, USD per million tokens. Read from the pricing page on
# this date; they were previously spelled out as bare numbers in six format
# strings in build_pack.py and one constant pair in extract_facts.py, which
# meant a price change had to be found in seven places.
#
# PRICES_AS_OF exists so a cost estimate can say how stale its own numbers are.
# An estimate that silently uses year-old prices is worse than one that admits
# it might be wrong.
PRICES_AS_OF = "2026-08-12"


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float
    output: float


MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(input=5.00, output=25.00),
    # Sonnet 5 carries introductory pricing of $2.00/$10.00 through 2026-08-31.
    # The standard rate is recorded here because it is what a run after that date
    # will actually be billed, and an estimate that under-quotes is the more
    # damaging direction to be wrong in.
    "claude-sonnet-5": ModelPrice(input=3.00, output=15.00),
}

# Prompt-caching multipliers, applied to the model's INPUT price.
#
# A cached read costs 0.1x input, so a cache only repays its own write after
# enough reads: 1.25 / (1 - 0.1) = 1.4 reads for the 5-minute TTL, 2.0 / 0.9 =
# 2.2 reads for the 1-hour one. Below that, paying full price each call is
# cheaper. This is why caching is not automatically a saving, and why the
# generation stage measured its read count before turning it on.
#
# The 1-hour figure was recorded as "2.3 reads" in build_pack.py, in both a
# comment and a hardcoded markdown table, while the line between them COMPUTED
# 2.0 / 0.9 and printed 2.2 — so the stage printed 2.2 to the terminal and wrote
# 2.3 into pack-report.md on the same run. 2.2 is correct. `break_even_reads`
# below exists so the number has one source instead of three.
CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.00}
CACHE_READ_MULTIPLIER = 0.10


def break_even_reads(ttl: str) -> float:
    """How many cached reads before a cache write repays itself.

    A write costs `mult` x input and each read costs 0.1x, against 1.0x for
    paying full price every call — so the write is repaid once
    `mult / (1 - 0.1)` reads have happened.
    """
    try:
        return CACHE_WRITE_MULTIPLIER[ttl] / (1 - CACHE_READ_MULTIPLIER)
    except KeyError:
        raise SystemExit(
            f"FATAL: unknown cache TTL {ttl!r}; "
            f"known: {', '.join(sorted(CACHE_WRITE_MULTIPLIER))}"
        ) from None


def price_for(model: str) -> ModelPrice:
    """The price table entry for a model, or a loud failure.

    Deliberately not a `.get(model, some_default)`: a silent default would make
    every cost estimate for an unpriced model quietly wrong, and a cost estimate
    nobody can trust is worse than no estimate at all.
    """
    try:
        return MODEL_PRICES[model]
    except KeyError:
        known = ", ".join(sorted(MODEL_PRICES))
        raise SystemExit(
            f"FATAL: no price recorded for model {model!r}.\n"
            f"Priced models (as of {PRICES_AS_OF}): {known}\n"
            "Add it to MODEL_PRICES in src/equity_research/settings.py rather "
            "than hardcoding a number at the call site."
        ) from None


# ---------------------------------------------------------------------------
# Loading and layering
# ---------------------------------------------------------------------------

def _read_toml(path: Path) -> dict:
    with open(path, "rb") as fh:  # "rb" — tomllib needs binary
        return tomllib.load(fh)


def deep_merge(base: dict, override: dict) -> dict:
    """Merge `override` onto `base`. See THE MERGE RULE in the module docstring.

    Neither input is mutated: an override applied to a cached global config must
    not change what the next company sees.
    """
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            # Scalars and arrays (including arrays of tables) replace wholesale.
            out[key] = value
    return out


def load_config(*names: str, P: CompanyPaths | None = None) -> dict:
    """Load config files by bare name, layered where layering applies.

        cfg = load_config("company", "forms", "sections")
        cfg["forms"]["triage"]["include_items"]

    Global names are read from `config/<name>.toml` and then deep-merged with
    `companies/<T>/overrides/<name>.toml` when that file exists. Company names
    are read straight from the company folder. An optional file that is absent
    yields `{}`; a required file that is absent is a hard error naming the path,
    because every other outcome of a missing config is a stage running on
    defaults nobody chose.
    """
    P = P or paths()
    cfg: dict[str, dict] = {}

    for name in names:
        if name in GLOBAL_CONFIGS:
            base = _read_toml(_require(P.config_dir / f"{name}.toml", name))
            override_path = P.overrides_dir / f"{name}.toml"
            if override_path.is_file():
                base = deep_merge(base, _read_toml(override_path))
            cfg[name] = base

        elif name in COMPANY_CONFIGS:
            path = P.company / f"{name}.toml"
            if not path.is_file() and name in OPTIONAL_CONFIGS:
                cfg[name] = {}
            else:
                cfg[name] = _read_toml(_require(path, name))

        else:
            raise ValueError(
                f"unknown config name {name!r}. "
                f"Global: {', '.join(GLOBAL_CONFIGS)}. "
                f"Company: {', '.join(COMPANY_CONFIGS)}."
            )

    return cfg


def _require(path: Path, name: str) -> Path:
    if not path.is_file():
        raise SystemExit(
            f"FATAL: required config {name}.toml not found at {path}.\n"
            "Global defaults live in config/; per-company files live in "
            "companies/<TICKER>/."
        )
    return path


# ---------------------------------------------------------------------------
# Window validation
# ---------------------------------------------------------------------------

MAX_WINDOW_YEARS = 10


def window(company_cfg: dict) -> tuple[int, int]:
    """The inclusive fiscal-year window, validated.

    Takes the parsed `company.toml` (the value of `cfg["company"]`), not the
    whole config dict, so it can be called on a config assembled any way.
    """
    win = company_cfg.get("window", {})
    try:
        first = int(win["first_fiscal_year"])
        last = int(win["last_fiscal_year"])
    except (KeyError, TypeError, ValueError):
        raise SystemExit(
            "FATAL: company.toml [window] needs integer first_fiscal_year and "
            "last_fiscal_year.\nThese are fiscal YEAR NUMBERS (2021), inclusive "
            "on both ends — not dates."
        ) from None

    if last < first:
        raise SystemExit(
            f"FATAL: window runs backwards — first_fiscal_year={first} is after "
            f"last_fiscal_year={last}.\nBoth ends are inclusive; for a single "
            f"year set them equal."
        )

    years = last - first + 1
    if years > MAX_WINDOW_YEARS:
        raise SystemExit(
            f"FATAL: window is {years} fiscal years ({first}-{last}); the "
            f"supported maximum is {MAX_WINDOW_YEARS}.\n"
            "This is a hard limit rather than a warning because the pack grows "
            "with the window:\nfive MORN years measure 352,194 tokens, and "
            "document quality degrades well before\nthe 1M context window binds "
            "(measured comfort zone ~450-500K). Beyond ten years the\n"
            "pack needs subsetting or era-chunking, which is a real decision, "
            "not a default."
        )
    return first, last
