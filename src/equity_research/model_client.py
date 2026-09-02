"""The model seam: one interface, two backends.

WHY THIS EXISTS
---------------
Colleagues have Claude Enterprise seats and, in almost every case, no API key.
The pipeline therefore has to be able to reach a model without one. Claude Code
headless is that path, and it is the DEFAULT. The anthropic-SDK path stays as a
config-selectable secondary for whoever does hold a key.

Everything downstream of a model call — quote verification, the 13 hard checks,
pack-sha provenance, PDF read-back — operates on files that have already been
written, so it is call-path agnostic. The blast radius of this module is itself
plus its call sites in extract_facts, generate_outputs and build_pack.

===========================================================================
WHAT THE PROBES MEASURED, 2026-08-13 (claude.exe 2.1.231)
===========================================================================
These are measurements, not assumptions, and several contradict the plan.

1. THE BINARY IS USUALLY NOT ON PATH. Most colleagues run Claude Code through
   the VS Code extension, which SHIPS the CLI rather than depending on one:
       ~/.vscode/extensions/anthropic.claude-code-<VER>/resources/native-binary/claude.exe
   That path carries the version, so it moves on every extension update — three
   versions were installed side by side on the development machine. Discovery
   must glob and take the newest. See `find_binary`.

2. EVERY CALL CARRIES A ~20,400-TOKEN HARNESS PREAMBLE, and it is unavoidable.
   `--allowed-tools ""` is rejected outright ("argument missing"), so tools are
   denied by name instead. `--system-prompt` REPLACES Claude Code's own prompt
   and saves 4,525 tokens a call; `--append-system-prompt` would only add.
   Running from a neutral working directory saves a further ~4,500, because
   otherwise both CLAUDE.md files are loaded into every call.

3. THE PROMPT IS ALWAYS CACHE-**WRITTEN** AT 1h TTL, WHICH BILLS AT 2x INPUT.
   `input_tokens` comes back as ~2 no matter how large the prompt is; the whole
   thing lands in `cache_creation_input_tokens`. There is no flag to opt out.
   This is the single biggest cost difference from the API path, where the same
   content is ordinary 1x input.

4. AN IDENTICAL PROMPT DOES NOT CACHE ACROSS CALLS. Two fresh calls sending a
   byte-identical 60KB prefix seconds apart produced byte-identical usage:
   22,691 written and 20,443 read, both times. Only Claude Code's OWN prefix is
   read back; user content never is. So there is no point trying to order calls
   to share a cached pack — it will not happen.

5. `--resume` PRESERVES CONTEXT BUT SAVES NOTHING. The resumed turn recalled the
   first turn's content correctly, and re-wrote the entire conversation at 2x:
   cache_read 0, cache_creation 34,316. Turn 2 cost MORE than turn 1. The plan's
   "run both documents and their repair rounds in one resumed session so the
   1.4 MB pack is not re-ingested" DOES NOT WORK, and its failure is invisible
   from the outside — you get the right answer at full price.
   => Repair rounds must be SELF-CONTAINED and pack-free (the plan's fallback:
      an index excerpt of ~15-25K tokens), not resumed.

6. Cost, measured head to head on FY2024's 17 extraction units:
       API path            $2.28
       Claude Code path    $4.68     (2.0x)
   Generation is far less affected, because it is ~4 large calls rather than 88
   small ones: roughly $8 against $7.00. Whole company ≈ $32 vs ≈ $18 notional.
   On a subscription seat those dollars are NOTIONAL — they are what the API
   would have charged. The real currency is seat allowance.

7. Structured output works via a schema embedded in the prompt plus local
   pydantic validation: 16/17 units validated first time and NONE wrapped their
   output in a markdown fence. The one failure returned malformed JSON, so
   `max_schema_retries` defaults to 1 rather than 0 — at ~1-in-17 you would
   expect roughly five failures across a full company.

8. `stop_reason` reliably distinguishes truncation, so the existing
   "truncation is a FAILED call, never a stored partial" rule survives intact.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which
from typing import Any, Protocol

from pydantic import BaseModel

from equity_research import settings

# Tools are denied by name because an empty allow-list is rejected. Denying them
# also means `num_turns` comes back as 1 without needing `--max-turns`, which
# does not exist in 2.1.231 despite the plan specifying it.
DENIED_TOOLS = ("Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task,"
                "NotebookEdit,TodoWrite")

# How long to wait on one headless call. The slowest real extraction unit
# measured 87s; a whole-pack generation call is much larger, so this is set well
# above anything observed rather than tuned to it.
DEFAULT_TIMEOUT_S = 1800


# ---------------------------------------------------------------------------
# The canonical result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMResult:
    """One model response, in the shape the audit records already store.

    `backend` and `model` are stamped onto every record so the audit trail
    survives the engine change — a facts file written through Claude Code and
    one written through the API must be distinguishable after the fact, or
    "which engine produced this?" becomes unanswerable the moment both have run.

    `billing` answers the question `backend` does NOT. `backend` records which
    CODE PATH ran; it says nothing about which credential paid. Those came apart
    once already: with ANTHROPIC_API_KEY inherited by the CLI subprocess, a record
    stamped `claude_code` could have been billed to an API key while every dollar
    printed alongside it was labelled notional. Recording it makes "this cost no
    real money" a fact on the record rather than an inference from the config.
    """

    text: str
    usage: dict[str, Any]
    backend: str
    model: str
    # "seat"  — the CLI ran with every API credential stripped from its
    #           environment, so the dollars derived from `usage` are NOTIONAL.
    # "api_key" — the anthropic SDK was used; the dollars are REAL.
    # Set by the backend, never by a caller.
    billing: str = "unknown"
    # Credentials that existed in the parent process but were withheld from the
    # call. Empty on a machine with no key. Non-empty is not a problem — it is
    # the evidence that the withholding happened.
    credentials_withheld: tuple[str, ...] = ()
    # Which write multiplier prices this record's cache_creation tokens. Carried
    # on the result rather than looked up later because a usage dict on its own
    # cannot say: the same numbers cost 1.25x or 2.0x depending on the engine
    # that produced them, and the engine is not recoverable from the tokens.
    cache_ttl: str = "5m"
    stop_reason: str | None = None
    cost_usd: float | None = None
    session_id: str | None = None
    parsed: BaseModel | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def truncated(self) -> bool:
        """A structured response cut off by the output cap is a FAILED call.

        The JSON is incomplete, so storing it would put a partial record into the
        ledger. Callers check this and fail rather than persisting.
        """
        return self.stop_reason == "max_tokens"


class BackendError(RuntimeError):
    """A call that did not produce a usable response. Never a silent None."""


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------

class Backend(Protocol):
    name: str
    cache_ttl: str

    def generate(self, *, model: str, system: str, prompt: str, max_tokens: int,
                 effort: str, schema: type[BaseModel] | None = None,
                 cache_prefix: str | None = None,
                 stream: bool = False) -> LLMResult:
        """One model call.

        `cache_prefix` is content that goes BEFORE `prompt` and is the same
        across a series of calls — for generation, the 353K-token pack that both
        documents read. It is a separate argument rather than something the
        caller concatenates because on the API path it carries the cache
        breakpoint, and a breakpoint has to fall between the shared part and the
        varying part. Concatenating first would put the whole prompt inside the
        cached prefix, and two documents with different asks would then share no
        prefix at all.

        `stream` asks for a streamed request. It changes nothing about the
        result; it exists because a high-effort call over a very large prompt can
        run past the non-streaming request timeout, and a request that dies at
        the timeout has still been paid for.

        Both are inert on the Claude Code backend — see its `generate`.
        """
        ...

    def count_tokens(self, *, model: str, system: str, prompt: str) -> int | None:
        """Exact input tokens, or None when the backend cannot say.

        None is a real answer, not a failure: Claude Code exposes no
        count-tokens endpoint. Callers must present an estimate as approximate
        rather than printing a confident number they did not measure.
        """
        ...


# ---------------------------------------------------------------------------
# Locating the Claude Code binary
# ---------------------------------------------------------------------------

EXTENSION_GLOB = "anthropic.claude-code-*/resources/native-binary/claude.exe"


def _extension_candidates() -> list[Path]:
    """Claude Code binaries shipped inside IDE extensions, oldest first."""
    roots = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-insiders" / "extensions",
        Path.home() / ".vscode-server" / "extensions",
    ]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(root.glob(EXTENSION_GLOB)))
            # Non-Windows hosts ship the binary without the extension.
            found.extend(sorted(root.glob(EXTENSION_GLOB[:-4])))
    return found


def find_binary(configured: str | None = None) -> Path:
    """Locate the Claude Code executable.

    Order: an explicit config value, then PATH, then a binary discovered inside
    an installed IDE extension (newest wins).

    Discovery matters more than it looks. Most colleagues use Claude Code
    THROUGH VS CODE and have never installed the CLI, so requiring `claude` on
    PATH would mean asking each of them to install something before they could
    run the pipeline at all — which is the friction this backend exists to
    remove. Reaching into another program's install directory is admittedly
    brittle, so the failure is made loud and specific rather than mysterious:
    a missing binary must not surface three stages later as "extraction returned
    nothing".
    """
    if configured:
        p = Path(os.path.expandvars(configured)).expanduser()
        if not p.is_file():
            raise BackendError(
                f"FATAL: [llm] binary_path points at {p}, which does not exist.\n"
                "Fix the path, or remove the setting to fall back to PATH and "
                "IDE-extension discovery."
            )
        return p

    on_path = which("claude")
    if on_path:
        return Path(on_path)

    cands = _extension_candidates()
    if cands:
        return cands[-1]           # newest version sorts last

    raise BackendError(
        "FATAL: no Claude Code executable found.\n"
        "Looked in three places, in order:\n"
        "  1. [llm] binary_path in config — not set\n"
        "  2. `claude` on PATH — not found\n"
        f"  3. IDE extensions matching {EXTENSION_GLOB}\n"
        f"     under {Path.home() / '.vscode' / 'extensions'} — none found\n\n"
        "If you use Claude Code inside VS Code, the CLI ships with the extension "
        "and is normally discovered automatically; if you use another IDE or the "
        "desktop app, set [llm] binary_path in config to the executable."
    )


# ---------------------------------------------------------------------------
# Claude Code backend (default)
# ---------------------------------------------------------------------------

def _schema_instruction(schema: type[BaseModel]) -> str:
    """The schema, in the prompt, because the CLI has no structured-output flag.

    Measured: 16/17 real extraction units returned valid JSON first time and none
    added a markdown fence. The remaining failure is handled by a bounded retry
    in `generate`, not by loosening the parse.
    """
    return ("\n\n=== REQUIRED OUTPUT FORMAT ===\n"
            "Return ONLY a single JSON object conforming to this JSON Schema. "
            "No prose before or after it, no markdown fence, no explanation.\n\n"
            + json.dumps(schema.model_json_schema(), indent=2))


def _strip_fence(text: str) -> str:
    """Remove a ```json fence if one appears despite the instruction not to."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t[3:]
    if "\n" in t:
        t = t.split("\n", 1)[1]
    return t.rsplit("```", 1)[0].strip()


# Credentials that would make the CLI authenticate as API traffic instead of
# against the seat. Removed from the child's environment, not merely unused.
API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def seat_only_env() -> dict[str, str]:
    """The parent environment with every API credential removed.

    WHY THIS EXISTS, and it is the difference between a true statement and a
    false one.

    `backend = "claude_code"` selects the CLI, and the whole operating assumption
    of this project is that the CLI runs on a seat with no API key -- so every
    dollar figure the pipeline prints is NOTIONAL, what the API would have
    charged. That claim was not enforced anywhere.

    `_bootstrap` loads `.env` into `os.environ`, and `subprocess.run` without an
    explicit `env=` hands the child everything. The Claude Code CLI treats
    ANTHROPIC_API_KEY as an authentication method. So on any machine where a key
    exists -- this one, because the MORN pilot used it -- the calls would very
    likely authenticate as API traffic and bill the key, while every facts record
    still stamped `backend: claude_code` and every printed dollar still said
    "notional". The notional claim would have been false and the spend real.

    Found before the first MSFT extraction call, by asking where the subprocess
    gets its environment rather than trusting the docstring above.

    NOT a workaround for having a key around: the `api` backend is a deliberate
    fallback and still works when it is explicitly selected, because it reads the
    key in-process through the SDK and never goes through here. This only stops a
    credential leaking into a call that was asked to use the seat.

    A LOUD FAILURE IS THE POINT. If seat auth is not configured, the call now
    fails with an auth error instead of silently billing a key. That is the safe
    direction, and the error is the diagnosis.
    """
    return {k: v for k, v in os.environ.items() if k not in API_CREDENTIAL_VARS}


def api_credentials_visible() -> list[str]:
    """Which API credentials are present in this process. For the audit record."""
    return [k for k in API_CREDENTIAL_VARS if os.environ.get(k)]


class ClaudeCodeBackend:
    """Headless `claude --print`. The default: needs a seat, not an API key."""

    name = "claude_code"

    # Not a setting. The CLI writes its cache at a 1-hour TTL and offers no flag
    # to change or disable it, so anything pricing a headless usage record has to
    # use the 1h multiplier (2.0x) rather than the API's default 1.25x. Recorded
    # here so the cost code can ask the backend instead of assuming.
    cache_ttl = "1h"

    def __init__(self, binary: Path | None = None, *, configured: str | None = None,
                 timeout_s: int = DEFAULT_TIMEOUT_S, max_schema_retries: int = 1):
        self.binary = binary or find_binary(configured)
        self.timeout_s = timeout_s
        self.max_schema_retries = max_schema_retries
        # A neutral working directory, so the project's two CLAUDE.md files are
        # not loaded into every call. Measured cost of not doing this: 4,525
        # tokens per call, which across 88 extraction units is ~400K tokens of
        # instructions the model does not need in order to read one filing.
        self._cwd = Path(tempfile.mkdtemp(prefix="eqr-llm-"))

    def _invoke(self, *, model: str, system: str, prompt: str, effort: str) -> dict:
        cmd = [
            str(self.binary), "--print",
            "--output-format", "json",
            "--model", model,
            "--effort", effort,
            # REPLACES Claude Code's own system prompt (-4,525 tokens/call).
            # `--append-system-prompt` would keep both.
            "--system-prompt", system,
            "--disallowed-tools", DENIED_TOOLS,
        ]
        try:
            proc = subprocess.run(cmd, input=prompt.encode("utf-8"),
                                  capture_output=True, cwd=self._cwd,
                                  env=seat_only_env(), timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            raise BackendError(
                f"claude_code call exceeded {self.timeout_s}s and was killed."
            ) from None

        out = proc.stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0 or not out.strip():
            err = proc.stderr.decode("utf-8", errors="replace")[:600]
            raise BackendError(
                f"claude_code exited {proc.returncode} with no usable output.\n"
                f"binary: {self.binary}\nstderr: {err}"
            )
        try:
            env = json.loads(out)
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"claude_code did not return a JSON envelope ({exc}).\n"
                f"first 400 chars: {out[:400]}"
            ) from None

        if env.get("is_error"):
            raise BackendError(
                f"claude_code reported is_error=true: "
                f"{str(env.get('result'))[:400]}"
            )
        return env

    def generate(self, *, model: str, system: str, prompt: str, max_tokens: int,
                 effort: str, schema: type[BaseModel] | None = None,
                 cache_prefix: str | None = None,
                 stream: bool = False) -> LLMResult:
        # `max_tokens` and `stream` are accepted for interface parity and are
        # deliberately unused: the CLI exposes no output cap, and `--print` is
        # a subprocess that returns when it returns, so there is no timeout to
        # stream around. The subprocess timeout does that job instead.
        #
        # `cache_prefix` is CONCATENATED rather than marked. There is nothing to
        # mark: the CLI always cache-writes the whole prompt at 1h TTL with no
        # opt-out, and never reads user content back — two calls sending a
        # byte-identical 60KB prefix seconds apart produced identical usage and
        # identical cost (module docstring, notes 3 and 4). So splitting the
        # prompt here would buy nothing. It is still passed as a separate
        # argument by the caller because the API backend needs the split.
        del max_tokens, stream

        prompt = (cache_prefix or "") + prompt
        body = prompt + (_schema_instruction(schema) if schema else "")
        attempts = 1 + (self.max_schema_retries if schema else 0)
        last: Exception | None = None

        for attempt in range(attempts):
            env = self._invoke(model=model, system=system, prompt=body, effort=effort)
            text = (env.get("result") or "").strip()
            result = LLMResult(
                text=text,
                usage=env.get("usage") or {},
                backend=self.name,
                model=model,
                billing="seat",
                credentials_withheld=tuple(api_credentials_visible()),
                cache_ttl=self.cache_ttl,
                stop_reason=env.get("stop_reason"),
                cost_usd=env.get("total_cost_usd"),
                session_id=env.get("session_id"),
                raw=env,
            )
            if schema is None:
                return result
            try:
                parsed = schema.model_validate_json(_strip_fence(text))
            except Exception as exc:                                # noqa: BLE001
                last = exc
                # Retry ONCE with the failure named. Not a loop: a model that
                # cannot produce the schema twice will not produce it on the
                # fifth attempt either, and each try costs a full prompt.
                body = (prompt + _schema_instruction(schema)
                        + f"\n\nYour previous reply could not be parsed: "
                          f"{type(exc).__name__}. Return ONLY the JSON object.")
                continue
            return LLMResult(
                text=text, usage=result.usage, backend=self.name, model=model,
                billing="seat",
                credentials_withheld=tuple(api_credentials_visible()),
                cache_ttl=self.cache_ttl, stop_reason=result.stop_reason,
                cost_usd=result.cost_usd, session_id=result.session_id,
                parsed=parsed, raw=env,
            )

        raise BackendError(
            f"claude_code returned output that did not match {schema.__name__} "
            f"after {attempts} attempt(s): {type(last).__name__}: "
            f"{str(last)[:300]}"
        )

    def count_tokens(self, *, model: str, system: str, prompt: str) -> int | None:
        """Not available. See the Backend protocol — None is a real answer.

        Claude Code exposes no count-tokens endpoint, and guessing would put a
        confident wrong number in front of someone deciding whether to spend.
        Callers fall back to a labelled approximation.
        """
        del model, system, prompt
        return None


# ---------------------------------------------------------------------------
# API backend (secondary)
# ---------------------------------------------------------------------------

class ApiBackend:
    """The anthropic SDK path. Requires ANTHROPIC_API_KEY."""

    name = "api"

    def __init__(self, client: Any | None = None, *, cache_ttl: str = "1h"):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        if cache_ttl not in settings.CACHE_WRITE_MULTIPLIER:
            raise BackendError(
                f"FATAL: [llm] cache_ttl = {cache_ttl!r} is not a TTL the API "
                f"accepts. Valid: "
                f"{', '.join(sorted(settings.CACHE_WRITE_MULTIPLIER))}."
            )
        self.cache_ttl = cache_ttl

    def generate(self, *, model: str, system: str, prompt: str, max_tokens: int,
                 effort: str, schema: type[BaseModel] | None = None,
                 cache_prefix: str | None = None,
                 stream: bool = False) -> LLMResult:
        content: list[dict[str, Any]] = []
        if cache_prefix:
            # The breakpoint goes on the SHARED block and nothing else. A cache
            # hits only on a byte-identical prefix, so everything that differs
            # between calls has to sit after this block — which is why the caller
            # hands the two parts over separately instead of one string.
            content.append({
                "type": "text", "text": cache_prefix,
                "cache_control": {"type": "ephemeral", "ttl": self.cache_ttl},
            })
        content.append({"type": "text", "text": prompt})

        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": max_tokens,
            "output_config": {"effort": effort},
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if schema is not None:
            resp = self.client.messages.parse(**kwargs, output_format=schema)
            parsed = getattr(resp, "parsed_output", None)
        elif stream:
            with self.client.messages.stream(**kwargs) as s:
                resp = s.get_final_message()
            parsed = None
        else:
            resp = self.client.messages.create(**kwargs)
            parsed = None

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage)
        # billing="api_key": these dollars are REAL, not notional. The one place
        # in the project where that is true, and it says so on every record.
        return LLMResult(text=text.strip(), usage=usage, backend=self.name,
                         model=model, billing="api_key",
                         cache_ttl=self.cache_ttl,
                         stop_reason=resp.stop_reason, parsed=parsed, raw=None)

    def count_tokens(self, *, model: str, system: str, prompt: str) -> int | None:
        """Exact input tokens. Free, and INTERMITTENTLY available.

        Two observations, ten days apart, and both matter:

          2026-08-16 — returned 500 for every request, including a two-word
            control, while `messages.create` on the same key worked normally.
          2026-08-26 — working again. Six consecutive calls, all sub-second, a
            two-word control and a 36,000-character payload.

        So "not available" was a service condition and not a permanent one. The
        conclusion that survives both is the one that matters: **the callers'
        "fall back to an estimate and label it approximate" path must stay
        usable, not merely present.** It is not a courtesy to seat users who
        cannot count; it is a live path for API users on any day this endpoint is
        having a bad one, and nothing warns you in advance.

        Do not delete the fallback because this worked today.

        No retry here. Three consecutive attempts failed in under a second each
        in 2026-08-16's outage, so retrying a service-wide 500 only delays the
        fallback — and the fallback is correct, just approximate.
        """
        return self.client.messages.count_tokens(
            model=model, system=system,
            messages=[{"role": "user", "content": prompt}]).input_tokens


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

BACKENDS = {"claude_code": ClaudeCodeBackend, "api": ApiBackend}


def get_backend(cfg: dict | None = None, *, stage: str | None = None) -> Backend:
    """Build the backend named by config, with an optional per-stage override.

    `[llm] backend = "claude_code"` is the default. A stage may override it —
    `[llm.extract_facts] backend = "api"` — so whoever does hold an API key can
    move the token-heavy stage onto it without any code change.
    """
    cfg = cfg or {}
    llm = cfg.get("llm", {}) if isinstance(cfg, dict) else {}
    chosen = llm.get("backend", "claude_code")
    binary_path = llm.get("binary_path")
    cache_ttl = llm.get("cache_ttl", "1h")

    if stage and isinstance(llm.get(stage), dict):
        chosen = llm[stage].get("backend", chosen)
        binary_path = llm[stage].get("binary_path", binary_path)
        cache_ttl = llm[stage].get("cache_ttl", cache_ttl)

    if chosen not in BACKENDS:
        raise BackendError(
            f"FATAL: unknown [llm] backend {chosen!r}. "
            f"Known: {', '.join(sorted(BACKENDS))}."
        )
    if chosen == "claude_code":
        return ClaudeCodeBackend(configured=binary_path)
    return ApiBackend(cache_ttl=cache_ttl)


def describe_cost(result: LLMResult) -> str:
    """A one-line cost note that does not overstate what it knows.

    The claude_code backend reports `total_cost_usd`, but on a subscription seat
    that figure is NOTIONAL — what the API would have charged — and saying
    "$0.28" without qualification invites someone to add it to a real budget.
    """
    if result.backend == "claude_code":
        if result.cost_usd is None:
            return "subscription usage — no dollar spend"
        return (f"subscription usage — no dollar spend "
                f"(${result.cost_usd:.3f} API-equivalent)")
    return f"${settings.usage_cost(result.usage, result.model, ttl=result.cache_ttl):.3f}"
