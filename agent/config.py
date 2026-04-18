import json
import os

MOD_API_URL = os.getenv("MOD_API_URL", "http://localhost:3100")
MOD_API_KEY = os.getenv("MOD_API_KEY", "")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

PROFILE_PATH = os.getenv("PROFILE_PATH", os.path.join(os.path.dirname(__file__), "profiles", "default.json"))

TICK_DELAY = float(os.getenv("TICK_DELAY", "2.0"))
BUSY_POLL_DELAY = float(os.getenv("BUSY_POLL_DELAY", "0.5"))

OBSERVE_ENTITY_RADIUS = 24.0
OBSERVE_BLOCK_RADIUS = 8

MAX_CHAT_HISTORY = 20
MAX_CONVERSATION = 12
MAX_MEMORY = 50


def load_profile():
    with open(PROFILE_PATH) as f:
        return json.load(f)
