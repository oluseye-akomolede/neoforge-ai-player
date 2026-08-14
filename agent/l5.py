"""L5 — the external model (DeepSeek), summoned by L4 and answering only to L4.

One function, one call, no memory, no agency. If DEEPSEEK_API_KEY is unset the
layer simply does not exist, and escalation degrades to asking the player
again. All local-first inference stays on L3 (user directive: local AI); L5
is an explicitly player-invoked exception, per ruling, per question — and it
runs on the player's own DeepSeek key, not any cloud default.
"""
import logging

import requests

from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_URL

log = logging.getLogger("aibot.l5")

_TIMEOUT = 30


def available() -> bool:
    return bool(DEEPSEEK_API_KEY)


def consult(question: str, options: list | None = None) -> str:
    """One-shot advisory answer, or "" if L5 is unavailable/unreachable."""
    if not available():
        log.info("L5 consult requested but DEEPSEEK_API_KEY is unset")
        return ""
    prompt = question
    if options:
        prompt += "\nOptions: " + ", ".join(str(o) for o in options)
    try:
        # Same OpenAI-compatible shape as skill_author._deepseek_chat, which is
        # the proven DeepSeek call in this codebase.
        r = requests.post(
            f"{DEEPSEEK_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content":
                        "You advise a Minecraft bot-fleet operator. Answer in one short "
                        "sentence. If options are listed, name exactly one."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 80,
                "stream": False,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("L5 consult failed: %s", e)
        return ""
