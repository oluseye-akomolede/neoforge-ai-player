import json
import math
import os
import sys
from urllib.parse import urlsplit, urlunsplit

MOD_API_URL = os.getenv("MOD_API_URL", "http://localhost:3100")
MOD_API_KEY = os.getenv("MOD_API_KEY", "")

# The M2 script runner is a SEPARATE service from the mod, and must not share
# MOD_API_URL. `api._post` prefixes MOD_API_URL, so using it as the runner
# transport (which `call_runner` does when `post` is None) sends script ticks to
# the game mod -- silently, because the mod answers JSON too. Empty by default
# so a pod that has not been given a runner falls through to the planner rather
# than posting ticks somewhere unintended.
SCRIPT_RUNNER_URL = os.getenv("SCRIPT_RUNNER_URL", "")

# The runner refuses every contract call that arrives without a bearer token,
# with a 401 before it reads the body (agent-script-runner src/server.js). The
# value comes from secret agent-script-runner-token, key `minecraft`; it is
# never logged and never printed -- only whether it is set.
RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "")

# GET /health lives on the mod's own dedicated listener, not on MOD_API_URL: the
# probe port answers /health and nothing else, so the two cannot share a base.
# Default ties to the mod's default (3101); a deployment that moves it must set
# AIPLAYER_HEALTH_PROBE_PORT, the same variable the mod reads.
HEALTH_PROBE_PORT = os.getenv("AIPLAYER_HEALTH_PROBE_PORT", "3101")


def _float_env(name: str, default: float) -> float:
    """Read a numeric setting without crashing the process that reads it.

    This module is imported before the health gate runs, so an unparseable value
    here would kill the agent at startup -- before the very gate the setting is
    meant to configure could report why. A bad value is a misconfiguration, not a
    reason to be unable to say so: warn loudly and fall back to the default.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f"config: {name}={raw!r} is not a number; using default {default}",
              file=sys.stderr)
        return default
    # Reparsing is not enough. nan and inf parse cleanly and then raise inside
    # requests.get (ValueError / OverflowError); zero and negatives parse and
    # raise "connect timeout cannot be set to". Those are caught by the health
    # gate, so the process survives -- but every retry fails before any request
    # is made, and the agent spends the whole budget reporting "Mod API not
    # ready", which is a lie about the cause. A bad number must fail here, where
    # the message can name it.
    if not math.isfinite(value) or value <= 0:
        print(f"config: {name}={raw!r} is not a usable timeout; using default {default}",
              file=sys.stderr)
        return default
    return value


def _health_url(api_url: str, probe_port: str) -> str:
    """Swap the port on the API base, keeping scheme and host.

    Parsed with urlsplit rather than split(":"): "http://host" has no port, and
    rsplit on that yields ["http", "//host"], which would silently build a wrong
    URL for any base without an explicit port.
    """
    parts = urlsplit(api_url)
    return urlunsplit((parts.scheme, parts.netloc.rsplit(":", 1)[0] + ":" + probe_port,
                       parts.path.rstrip("/"), "", ""))


MOD_HEALTH_URL = os.getenv("MOD_HEALTH_URL") or _health_url(MOD_API_URL, HEALTH_PROBE_PORT)

# Per-attempt timeout for the startup health gate. Must be at least the kubelet's
# probe timeoutSeconds (10 s in the pod spec) so a slow-but-healthy answer is not
# cut off sooner than the probe allows. A named setting, not a literal at the call
# site: the retry budget is derived from it (max_retries in agent.py), so anyone
# tuning it must be able to find and change what the code actually reads.
HEALTH_TIMEOUT = _float_env("AIPLAYER_HEALTH_TIMEOUT", 10.0)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
NN_COMPRESSOR_URL = os.getenv("NN_COMPRESSOR_URL", "")  # empty disables state compression

# L4 escalation (OpenAI)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
L4_ENABLED = os.getenv("L4_ENABLED", "true").lower() in ("true", "1", "yes")

# Off-loop skill author (DeepSeek). Separation of concerns: L3 (local qwen3-coder)
# stays in the live loop for planning/dispatch; DeepSeek authors reusable skills
# OFF-LOOP from logged trajectories. The key lives in ANTHROPIC_AUTH_TOKEN (a
# DeepSeek token) by deliberate user choice — never in settings.json.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", os.getenv("ANTHROPIC_AUTH_TOKEN", ""))
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")
SKILL_AUTHOR_ENABLED = os.getenv("SKILL_AUTHOR_ENABLED", "false").lower() in ("true", "1", "yes")
SKILL_AUTHOR_INTERVAL = float(os.getenv("SKILL_AUTHOR_INTERVAL", "90.0"))

PROFILE_PATH = os.getenv("PROFILE_PATH", os.path.join(os.path.dirname(__file__), "profiles", "default.json"))

def _cap_from_env(name: str):
    """Read an hours-per-day cap, or None for unlimited (coded-agents 5.6/B2).

    None is the cap's unlimited marker, matching `code_time.UNLIMITED`, so
    "unset" and "unlimited" are one value rather than two spellings of it.

    A value that is not a positive finite number falls back to unlimited with a
    loud line, for the same reason `_float_env` does: config is imported before
    the health gate runs, so refusing to start would kill the surface that could
    report the misconfiguration. The row's open question -- refuse or fall back
    -- is settled this way, and the spec says why.

    Not `_float_env`: that helper rejects non-positive values as an unusable
    TIMEOUT, and its message would name this variable as one. The arithmetic is
    the same; the sentence a reader sees is not.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None                      # unset/empty = unlimited, silently
    try:
        value = float(raw)
    except ValueError:
        print(f"config: {name}={raw!r} is not a number; cap is unlimited",
              file=sys.stderr)
        return None
    if not math.isfinite(value) or value <= 0:
        print(f"config: {name}={raw!r} is not a positive number of hours; "
              f"cap is unlimited", file=sys.stderr)
        return None
    return value


# The daily code-hours cap, in hours per day per bot. Unset on test and prod is
# how "unlimited while testing" is configured -- see the coded-agents spec,
# "Daily Code-Hour Cap Is Read From The Deployment Environment".
CODE_HOURS_CAP = _cap_from_env("CODE_HOURS_CAP")


def code_hours_cap():
    """The configured cap as a function, so callers name it rather than import
    a value copied into their module at import time.

    Resolved ONCE at import (`CODE_HOURS_CAP`), not on every call: a bot builds
    its meter once, and re-reading would print a bad-value warning once per bot
    instead of once per process. A test that needs a different value sets the
    env var and reloads `config`, which is honest about the once-per-process
    semantics the spec now states.
    """
    return CODE_HOURS_CAP

TICK_DELAY = float(os.getenv("TICK_DELAY", "2.0"))
BUSY_POLL_DELAY = float(os.getenv("BUSY_POLL_DELAY", "0.5"))

OBSERVE_ENTITY_RADIUS = 24.0
OBSERVE_BLOCK_RADIUS = 8

MAX_CHAT_HISTORY = 20
MAX_CONVERSATION = 12
MAX_MEMORY = 50

PG_DSN = os.getenv("PG_DSN", "")

DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))

# Opt-in: route new tasks through the L3 spec-driven planning layer
# (plan_orchestrator.execute_task) instead of the legacy decompose path.
# Default off so prod aibot-agent keeps its proven behavior. Enable on the
# test agent (minecraft-test ns) to exercise the new flow.
USE_L3_PLAN_LAYER = os.getenv("USE_L3_PLAN_LAYER", "false").lower() in ("true", "1", "yes")

# Whether the served model may spend tokens thinking before it answers.
# Default off: a thinking model served with the small num_predict these call
# sites use will spend the whole budget thinking and return empty content, which
# parses as "the model had no opinion". Sent explicitly, never omitted -- see
# openspec/changes/ollama-think-control. The value is a top-level field of the
# /api/chat body, not a key inside `options`; a nested value is silently ignored.
LLM_THINK = os.getenv("AIBOT_LLM_THINK", "false").lower() in ("true", "1", "yes")


def think_field():
    """The `think` entry for a /api/chat body. One source for every call site.

    Returned as a dict so each site can splat it into the body it already
    builds; no site supplies its own literal, so they cannot disagree.
    """
    return {"think": LLM_THINK}


class TruncatedAnswer(RuntimeError):
    """The model stopped at the token limit with nothing to parse.

    Distinct from an empty answer: the model had a budget and spent it, so the
    call failed rather than returning "no opinion". Callers let this propagate
    -- a truncated call is a failed call, not an empty result.
    """


def answer_text(body):
    """The answer text from an Ollama /api/chat response body.

    Raises TruncatedAnswer when the content is empty AND the response says it
    stopped for length. Without that check an empty string reaches a parser,
    fails to parse, and reads as a model with nothing to say -- which is how a
    thinking model on a small num_predict budget disappears silently.
    """
    msg = body.get("message") if isinstance(body, dict) else None
    content = (msg or {}).get("content") or ""
    done = body.get("done_reason") if isinstance(body, dict) else None
    if not content.strip() and done == "length":
        raise TruncatedAnswer(
            "model hit the token limit before answering (done_reason=length, "
            "eval_count=%s); this is a failed call, not an empty answer"
            % (body.get("eval_count") if isinstance(body, dict) else None))
    return content


def ensure_not_truncated(body, call_name):
    """Raise TruncatedAnswer if the reply stopped for length.

    The rule, stated once: a length stop means the reply is not a usable
    answer, whatever it contains. answer_text only catches the EMPTY case; a
    reply cut mid-object has content and would otherwise reach json.loads,
    which reports a syntax error and sends a reader to fix a prompt that was
    fine. Callers use this BEFORE parsing.

    `call_name` names the call in the message, so a log line says which budget
    ran out rather than "a call".
    """
    if not isinstance(body, dict):
        return
    if body.get("done_reason") != "length":
        return
    raise TruncatedAnswer(
        "%s hit the token limit before finishing (done_reason=length, "
        "eval_count=%s); this is a failed call, not a short answer"
        % (call_name, body.get("eval_count")))


def load_profile():
    with open(PROFILE_PATH) as f:
        return json.load(f)
