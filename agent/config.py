import json
import os
from urllib.parse import urlsplit, urlunsplit

MOD_API_URL = os.getenv("MOD_API_URL", "http://localhost:3100")
MOD_API_KEY = os.getenv("MOD_API_KEY", "")

# GET /health lives on the mod's own dedicated listener, not on MOD_API_URL: the
# probe port answers /health and nothing else, so the two cannot share a base.
# Default ties to the mod's default (3101); a deployment that moves it must set
# AIPLAYER_HEALTH_PROBE_PORT, the same variable the mod reads.
HEALTH_PROBE_PORT = os.getenv("AIPLAYER_HEALTH_PROBE_PORT", "3101")


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
HEALTH_TIMEOUT = float(os.getenv("AIPLAYER_HEALTH_TIMEOUT", "10"))

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


def load_profile():
    with open(PROFILE_PATH) as f:
        return json.load(f)
