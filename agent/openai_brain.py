"""
L4 escalation layer — OpenAI API for higher-quality reasoning.

Called when L3 (local ollama) fails to produce valid primitives or
when the planner needs better decomposition for complex tasks.
"""

import json
import os

_client = None
_model = None
_enabled = False


def init():
    global _client, _model, _enabled
    api_key = os.getenv("OPENAI_API_KEY", "")
    _model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    _enabled = bool(api_key) and os.getenv("L4_ENABLED", "true").lower() in ("true", "1", "yes")
    if not _enabled:
        return
    from openai import OpenAI
    _client = OpenAI(api_key=api_key)


def is_available():
    return _enabled and _client is not None


def think(system_prompt, observation, history=None):
    if not is_available():
        return None
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": observation})

    resp = _client.chat.completions.create(
        model=_model,
        messages=messages,
        temperature=0.3,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        return None


def generate_primitives(prompt):
    if not is_available():
        return None
    messages = [
        {"role": "system", "content": "You are a Minecraft bot assistant. Respond ONLY with a valid JSON array of primitives. No explanation, no markdown."},
        {"role": "user", "content": prompt},
    ]
    resp = _client.chat.completions.create(
        model=_model,
        messages=messages,
        temperature=0.3,
        max_tokens=512,
    )
    return resp.choices[0].message.content


def decompose(instruction, context=""):
    if not is_available():
        return None
    messages = [
        {"role": "system", "content": context},
        {"role": "user", "content": instruction},
    ]
    resp = _client.chat.completions.create(
        model=_model,
        messages=messages,
        temperature=0.3,
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        parsed = json.loads(content)
        return parsed.get("steps", [])
    except (json.JSONDecodeError, AttributeError):
        return None
