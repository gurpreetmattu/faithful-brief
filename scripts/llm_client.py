"""
Shared LLM call wrapper for writer.py and verifier.py.

Four providers, tried in order (see _PROVIDERS below): Groq, Gemini, OpenRouter,
Hugging Face -- all OpenAI-compatible chat-completions APIs. A live check
(2026-09-06) showed Groq's own GROQ_API_KEY_2..13 all report the same
"organization" ID in their error responses, so they share one 8000-token/minute
and 200,000-token/day budget, not independent ones -- key rotation across them was
tried and removed, it bought nothing. Gemini and OpenRouter were added the same
day specifically because they're genuinely separate quotas (different companies,
different accounts), not another key on the same pool. HF's free monthly credit
was also observed fully depleted mid-session, hence it's last in the order rather
than removed -- it may recover next month.

All four providers speak the same OpenAI-style chat-completions + tool-calling
format, so one function (call_llm) builds one payload and just changes the
endpoint/key/model on fallback -- no separate code path, no gateway framework
(CLAUDE.md's not-yet list names "LLM gateway" explicitly; this is a plain
in-order fallback loop, not that).

Plain urllib, no HTTP SDK dependency -- matches fetch_corpus.py's existing style.
call_llm() is used by both agents so there is exactly one place that (a) emits the
call_log record specs/writer-verifier.md Sec 9 defines, (b) reports the same call to
Langfuse if configured, and (c) can never accidentally thread state between calls --
each call is a fresh, independent HTTP request; no client-side conversation object is
reused across calls.

Note: Groq's and HF's routers return odd errors to requests with no User-Agent
header (Groq: a bare 403, Cloudflare code 1010) -- not an auth error. UA is set
explicitly below for all providers as a precaution.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "data" / "logs" / "call_log.jsonl"


def _load_dotenv() -> None:
    """Minimal .env loader (no python-dotenv dependency): sets os.environ from
    REPO_ROOT/.env for any key not already set in the real environment, so a
    shell export always wins over the file."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key] = value


_load_dotenv()

UA = {"User-Agent": "faithful-brief-agents/0.1 (research; contact via repo)"}

# spec Sec 11: same model for both roles, one constant, no per-role override.
# Two separate model constants because the providers don't host the same models --
# the "same model" decision is "same model per provider", the invariant that
# actually matters (Sec 1) is that Writer and Verifier calls are never distinguished
# by model choice.
GROQ_MODEL = os.environ.get("AGENT_MODEL_GROQ", "openai/gpt-oss-20b")
HF_MODEL = os.environ.get("AGENT_MODEL_HF", "meta-llama/Llama-3.3-70B-Instruct")
GEMINI_MODEL = os.environ.get("AGENT_MODEL_GEMINI", "gemini-3.6-flash")
OPENROUTER_MODEL = os.environ.get("AGENT_MODEL_OPENROUTER", "nvidia/nemotron-3-super-120b-a12b:free")

# .strip() defensively: a credential pasted from an editor selection (or a
# GitHub Actions secret saved with a trailing newline) can carry a stray \n
# or space, which urllib/http.client rejects outright when it lands in an
# Authorization header ("ValueError: Invalid header value") -- a real failure
# hit on live CI (verifier-eval, 2026-09-07) once a call fell through to a
# provider whose key had exactly this problem. No downside to stripping a
# key that was already clean.
def _clean_env(name: str) -> "str | None":
    val = os.environ.get(name)
    return val.strip() if val is not None else None


GROQ_API_KEY = _clean_env("GROQ_API_KEY")
HF_TOKEN = _clean_env("HF_TOKEN")
GEMINI_API_KEY = _clean_env("GEMINI_API_KEY")
OPENROUTER_API_KEY = _clean_env("OPENROUTER_API_KEY")

# Order matters: cheapest/most-proven-reliable first, since call_llm() below tries
# each in turn and only falls through on failure. Groq first (fastest, already
# proven correct); Gemini and OpenRouter next (added 2026-09-06 specifically
# because Groq's shared daily quota and HF's shared monthly credit both being
# per-organization pools -- not per-key -- meant no amount of extra Groq/HF keys
# could add real capacity; these two are genuinely independent quotas); HF last
# since its free monthly credit was already observed depleted this session.
_PROVIDERS = [
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": GROQ_API_KEY,
        "model": GROQ_MODEL,
    },
    {
        "name": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key": GEMINI_API_KEY,
        "model": GEMINI_MODEL,
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key": OPENROUTER_API_KEY,
        "model": OPENROUTER_MODEL,
    },
    {
        "name": "huggingface",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "key": HF_TOKEN,
        "model": HF_MODEL,
    },
]


def _append_log(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- Langfuse (optional observability) -------------------------------------------
# Augments, doesn't replace, the call_log.jsonl file spec Sec 9 requires -- that
# file is what the spec's contract actually needs; Langfuse is a nicer way to look
# at the same calls, not a substitute for the committed contract.

_langfuse_client = None
_langfuse_checked = False


def _get_langfuse():
    global _langfuse_client, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_client
    _langfuse_checked = True
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    base_url = os.environ.get("LANGFUSE_BASE_URL")
    if not (public_key and secret_key):
        return None
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=public_key, secret_key=secret_key, base_url=base_url
        )
    except Exception as e:  # noqa: BLE001 -- observability must never break a real call
        print(f"WARNING: Langfuse init failed, continuing without it: {e}")
        _langfuse_client = None
    return _langfuse_client


def _trace_to_langfuse(role, provider, model, messages, response_message, usage, latency_ms):
    client = _get_langfuse()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            name=f"{role}:{provider}",
            as_type="generation",
            model=model,
            input=messages,
            metadata={"role": role, "provider": provider, "latency_ms": latency_ms},
        ) as gen:
            gen.update(
                output=response_message,
                usage_details={
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                },
            )
        client.flush()
    except Exception as e:  # noqa: BLE001 -- same: never break a real call over tracing
        print(f"WARNING: Langfuse trace failed, continuing without it: {e}")


# --- Self-imposed pacing (Groq only) ------------------------------------------------
# Reactive retry-on-429 isn't enough here: a single corpus-wide entailment check
# (Sec 5.3, all 21 abstracts) alone runs ~5-6k tokens against an 8000-token/minute
# budget, so two such calls back-to-back always blow the window regardless of
# retry logic, and the Hugging Face fallback's own free credit is too thin to
# reliably absorb the overflow (observed depleting mid-eval-run more than once).
# Tracking our own rolling token usage and waiting *before* an over-budget call is
# strictly better than firing it and handling the rejection after the fact -- no
# wasted request, no reliance on the fallback catching what Groq couldn't.
_GROQ_TPM_BUDGET = 7500  # stay under Groq's real 8000 with a safety margin
_groq_call_history = []  # list of (timestamp, estimated_tokens)


def _estimate_tokens(payload: dict) -> int:
    return len(json.dumps(payload)) // 4  # rough chars/4 estimate, good enough to pace by


def _wait_for_groq_budget(estimated_tokens: int) -> None:
    global _groq_call_history
    while True:
        now = time.monotonic()
        _groq_call_history = [(t, n) for t, n in _groq_call_history if now - t < 60]
        used = sum(n for _, n in _groq_call_history)
        if used + estimated_tokens <= _GROQ_TPM_BUDGET:
            _groq_call_history.append((now, estimated_tokens))
            return
        if not _groq_call_history:
            # This single call's own estimated size already exceeds the whole
            # budget (can happen for a large Writer call) -- there is nothing
            # queued to wait for, so waiting would loop forever. Proceed
            # best-effort: this pacer is a proactive throttle, not a hard cap;
            # Groq's real rate limit (and call_llm's retry/fallback) is still
            # the actual enforcement if this guess runs over.
            _groq_call_history.append((now, estimated_tokens))
            return
        oldest_t = _groq_call_history[0][0]
        time.sleep(max(1.0, 60 - (now - oldest_t) + 1))


# --- Provider call -----------------------------------------------------------------


def _post(provider: dict, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = dict(UA)
    headers["Authorization"] = f"Bearer {provider['key']}"
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(provider["url"], data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm(
    role: str,
    messages: list,
    tools: list = None,
    tool_choice=None,
    max_tokens: int = 1200,
) -> dict:
    """
    One isolated call: messages (+ optional tools/tool_choice) go in, the parsed
    JSON response comes back. `role` is "writer" or "verifier", used only for
    logging/tracing -- it has no effect on the request and carries no state from
    any other call.

    Tries each configured provider in order (see _PROVIDERS). Moves to
    the next provider on a rate-limit response (after retrying once with a wait)
    or on any other request failure (e.g. a model failing to honor a forced tool
    call under a large-context request -- observed with gpt-oss-20b) -- a
    different provider/model is a real chance of success, not a repeat of the
    same failure, so it's worth trying before giving up entirely. Only raises
    once every provider has failed.
    """
    available = [p for p in _PROVIDERS if p["key"]]
    if not available:
        raise RuntimeError("No provider API key found (GROQ_API_KEY / HF_TOKEN in .env).")

    last_err = None
    for provider in available:
        payload = {"model": provider["model"], "messages": messages, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        if provider["name"] == "groq":
            _wait_for_groq_budget(_estimate_tokens(payload))

        start = time.monotonic()
        response = None
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                response = _post(provider, payload)
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                is_rate_limit = e.code in (429, 413) and "rate_limit_exceeded" in err_body
                last_err = RuntimeError(
                    f"{provider['name']} API error {e.code}: {err_body}"
                )
                if is_rate_limit and attempt < max_attempts - 1:
                    m = re.search(r"try again in (\d+(?:\.\d+)?)s", err_body)
                    wait_s = float(m.group(1)) + 1 if m else 65
                    time.sleep(wait_s)
                    continue
                break  # rate-limit retries exhausted, or a non-rate-limit error -- try next provider
        if response is None:
            continue  # this provider failed; try the next

        message = response["choices"][0]["message"]
        # A forced tool_choice can come back as HTTP 200 with no tool_calls at all
        # -- observed with OpenRouter's nemotron-3-super-120b, which burned its
        # whole max_tokens budget on visible chain-of-thought reasoning and never
        # reached the actual function call. That's not an HTTPError, so it never
        # hit the except block above, and get_tool_call() would otherwise raise
        # outside this function's retry/fallback loop entirely -- crashing the
        # caller instead of trying the next provider. Treat it the same as any
        # other per-provider failure here, before returning.
        if tool_choice and not message.get("tool_calls"):
            last_err = RuntimeError(
                f"{provider['name']} returned no tool_calls despite forced tool_choice "
                f"(likely ran out of max_tokens mid-reasoning): {message!r}"
            )
            continue

        latency_ms = (time.monotonic() - start) * 1000
        usage = response.get("usage", {})

        _append_log(
            {
                "role": role,
                "provider": provider["name"],
                "model": provider["model"],
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "latency_ms": round(latency_ms, 1),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        _trace_to_langfuse(role, provider["name"], provider["model"], messages, message, usage, latency_ms)
        return response

    raise last_err


def get_tool_call(response: dict, tool_name: str) -> dict:
    """Pull one named tool call's parsed arguments out of a chat completion response."""
    message = response["choices"][0]["message"]
    for call in message.get("tool_calls") or []:
        if call["function"]["name"] == tool_name:
            return json.loads(call["function"]["arguments"])
    raise RuntimeError(f"expected a '{tool_name}' tool call, got message: {message!r}")
