"""The seat/API boundary: no credential reaches a call that asked for the seat.

Run:  uv run python tests/unit/test_seat_billing.py

WHY THIS FILE EXISTS
--------------------
The operating assumption of the whole project is in CLAUDE.md: `claude_code` is
the default because "the operating assumption is that API keys are unavailable to
almost everyone who will use this", and consequently "on a seat, every dollar
figure the pipeline prints is NOTIONAL — what the API would have charged".

Nothing enforced it. Found 2026-09-02, before the first MSFT extraction call, by
asking where the CLI subprocess gets its environment:

  - `_bootstrap` loads `.env` into `os.environ` on every import.
  - `ClaudeCodeBackend._invoke` called `subprocess.run(...)` with no `env=`, so
    the child inherited everything.
  - The Claude Code CLI treats ANTHROPIC_API_KEY as an authentication method.

So on any machine that has a key — this one, because the MORN pilot used it — the
calls would very likely have authenticated as API traffic and billed the key,
while every facts record still stamped `backend: claude_code` and every printed
dollar was still labelled notional. The notional claim would have been false and
the ~$6 real.

Two things were then done, and this file pins both:

  1. `seat_only_env()` removes every API credential from the child's environment,
     so `backend = "claude_code"` means what it says on any machine.
  2. `LLMResult.billing` and `credentials_withheld` record which credential paid,
     because `backend` records only which CODE PATH ran. Those two came apart
     once and nothing could have detected it after the fact.

WHY A UNIT TEST AND NOT A PROBE
The probe that found this was a throwaway, and its own regex was wrong once the
fix landed: it looked for `env=` inside `subprocess.run(` with a character class
that could not cross the `)` in `prompt.encode("utf-8")`, so it reported the fix
as absent. A test that asserts the BEHAVIOUR of `seat_only_env()` cannot be
fooled that way.

Reads no company data and makes no model call.
"""

from __future__ import annotations

import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from equity_research import model_client as mc  # noqa: E402

PASS = FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


# The environment is mutated and restored rather than mocked: `seat_only_env`
# reads os.environ directly, which is the thing under test.
SAVED = {k: os.environ.get(k) for k in
         ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "EDGAR_IDENTITY")}


def restore() -> None:
    for k, v in SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


try:
    print("seat_only_env — the child sees no API credential")

    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-not-a-real-key"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "also-not-real"
    os.environ["EDGAR_IDENTITY"] = "Tester tester@example.com"

    env = mc.seat_only_env()
    check("ANTHROPIC_API_KEY is removed", "ANTHROPIC_API_KEY" in env, False)
    check("ANTHROPIC_AUTH_TOKEN is removed too", "ANTHROPIC_AUTH_TOKEN" in env, False)
    check("EDGAR_IDENTITY SURVIVES — the stages need it",
          env.get("EDGAR_IDENTITY"), "Tester tester@example.com")
    check("  and it is not an empty environment; PATH-like keys remain",
          len(env) >= len(os.environ) - 2, True)
    check("os.environ itself is NOT mutated — only the child's copy",
          os.environ.get("ANTHROPIC_API_KEY"), "sk-ant-test-not-a-real-key")

    check("api_credentials_visible names what was withheld",
          sorted(mc.api_credentials_visible()),
          ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])

    # Every variable the scrubber knows about must actually be scrubbed. Pinned
    # as a loop so adding one to API_CREDENTIAL_VARS without scrubbing it fails.
    leaked = [k for k in mc.API_CREDENTIAL_VARS
              if os.environ.get(k) and k in mc.seat_only_env()]
    check("every var in API_CREDENTIAL_VARS is scrubbed", leaked, [])

    print("\nwith no credential present at all — the colleague case")
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        os.environ.pop(k, None)
    env2 = mc.seat_only_env()
    check("nothing to withhold, and nothing breaks",
          mc.api_credentials_visible(), [])
    check("  EDGAR_IDENTITY still passes through",
          env2.get("EDGAR_IDENTITY"), "Tester tester@example.com")

    print("\nLLMResult.billing — which credential paid, not which code path ran")
    seat = mc.LLMResult(text="x", usage={}, backend="claude_code", model="m",
                        billing="seat", credentials_withheld=("ANTHROPIC_API_KEY",))
    api = mc.LLMResult(text="x", usage={}, backend="api", model="m",
                       billing="api_key")
    check("a seat result says its dollars are notional", seat.billing, "seat")
    check("  and records what was withheld as evidence",
          seat.credentials_withheld, ("ANTHROPIC_API_KEY",))
    check("an api result says its dollars are real", api.billing, "api_key")
    check("billing defaults to 'unknown', never silently to 'seat'",
          mc.LLMResult(text="x", usage={}, backend="b", model="m").billing,
          "unknown")
    check("  and withheld defaults to empty",
          mc.LLMResult(text="x", usage={}, backend="b", model="m")
          .credentials_withheld, ())

    # The two fields must not be confusable: backend alone cannot answer the
    # billing question, which is the entire reason `billing` exists.
    check("backend and billing are independent fields",
          (seat.backend, seat.billing) != (api.backend, api.billing), True)

finally:
    restore()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
