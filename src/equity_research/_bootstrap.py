"""Shared process setup: the repo root, the Windows cert store, and .env.

WHY THIS MODULE EXISTS
-----------------------
Every stage in this pipeline needs the same three things before it can do
anything else:

  1. `ROOT` — the repository root, so `data/`, `config/` and `output/` resolve
     the same way no matter which directory the stage is invoked from or where
     this package happens to live on disk.
  2. The Windows certificate store wired into `ssl` (`truststore.inject_into_ssl()`),
     without which corporate SSL inspection breaks every HTTPS request `httpx`
     and `anthropic` make.
  3. `.env` loaded (`load_dotenv`), so `EDGAR_IDENTITY` and `ANTHROPIC_API_KEY`
     are in `os.environ` before anything asks for them.

These three used to be copy-pasted at the top of four different modules
(`discover.py`, `fetch.py`, `extract_facts.py`, `generate_outputs.py`), each
computing its own `ROOT`. That duplication is exactly what caused the move
into `src/equity_research/` to be dangerous: `ROOT = Path(__file__).resolve()
.parent.parent` is correct when the file lives in `src/`, and silently wrong
by one directory once the file lives in `src/equity_research/` instead — every
`data/` and `output/` path would quietly repoint into `src/`.

Computing `ROOT` here, once, means fixing it once. Do not delete this module
because it looks unused — every module that imports it does so for these
import-time side effects (cert store injection, `.env` loading) as much as for
the `ROOT` value itself. Both calls are idempotent, so importing this module
more than once (Python only runs it once anyway) or alongside a module that
used to call these itself is harmless.
"""

from __future__ import annotations

from pathlib import Path

import truststore
from dotenv import load_dotenv

# This file lives at src/equity_research/_bootstrap.py, so the repository root
# is three levels up: .parent is src/equity_research/, .parent.parent is src/,
# .parent.parent.parent is the root that contains pyproject.toml, data/, etc.
ROOT = Path(__file__).resolve().parent.parent.parent

# Use the Windows certificate store. Without this, corporate SSL inspection
# makes httpx/anthropic fail to verify remote certificates.
truststore.inject_into_ssl()

# Load EDGAR_IDENTITY and ANTHROPIC_API_KEY from the repo-root .env, regardless
# of the current working directory the pipeline is invoked from.
load_dotenv(ROOT / ".env")
