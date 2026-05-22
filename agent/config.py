import json
import os

MOD_API_URL = os.getenv("MOD_API_URL", "http://localhost:3100")
MOD_API_KEY = os.getenv("MOD_API_KEY", "")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# L4 escalation (OpenAI)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
L4_ENABLED = os.getenv("L4_ENABLED", "true").lower() in ("true", "1", "yes")

PROFILE_PATH = os.getenv("PROFILE_PATH", os.path.join(os.path.dirname(__file__), "profiles", "default.json"))

TICK_DELAY = float(os.getenv("TICK_DELAY", "2.0"))
BUSY_POLL_DELAY = float(os.getenv("BUSY_POLL_DELAY", "0.5"))

OBSERVE_ENTITY_RADIUS = 24.0
OBSERVE_BLOCK_RADIUS = 8

MAX_CHAT_HISTORY = 20
MAX_CONVERSATION = 12
MAX_MEMORY = 50

PG_DSN = os.getenv("PG_DSN", "host=pgvector.minecraft-test.svc.cluster.local port=5432 dbname=botmemory user=aibot password=aibot-memory-2026")

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
