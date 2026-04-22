import json
import threading
import requests
from config import OLLAMA_URL

# Serialize all ollama requests — single GPU can only serve one at a time.
# Exported so planner and semantic_memory can use the same lock.
ollama_lock = threading.Lock()


def think(model, system_prompt, observation, history):
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": observation})

    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.7,
                    "num_predict": 512,
                },
            },
            timeout=120,
        )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
        else:
            parsed = {"thoughts": "Failed to parse response", "actions": []}

    return parsed


def raw_generate(model, prompt):
    """Text generation using chat API for instruct models. Used by L3."""
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a Minecraft bot assistant. Respond ONLY with a valid JSON array of primitives. No explanation, no markdown."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512,
                },
            },
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def check_ollama(url):
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return True, models
    except Exception as e:
        return False, str(e)
