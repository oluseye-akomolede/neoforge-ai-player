"""L5 — the external model, summoned by L4 and answering only to L4.

One function, one call, no memory, no agency. If OPENAI_API_KEY is unset the
layer simply does not exist, and escalation degrades to asking the player
again. All local-first inference stays on L3 (user directive: local AI); L5
is an explicitly player-invoked exception, per ruling, per question.
"""
import logging
import os

import requests

log = logging.getLogger("aibot.l5")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1/chat/completions")
_TIMEOUT = 30


def available() -> bool:
    return bool(OPENAI_API_KEY)


def consult(question: str, options: list | None = None) -> str:
    """One-shot advisory answer, or "" if L5 is unavailable/unreachable."""
    if not available():
        log.info("L5 consult requested but OPENAI_API_KEY is unset")
        return ""
    prompt = question
    if options:
        prompt += "\nOptions: " + ", ".join(str(o) for o in options)
    try:
        r = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content":
                        "You advise a Minecraft bot-fleet operator. Answer in one short "
                        "sentence. If options are listed, name exactly one."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 80,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("L5 consult failed: %s", e)
        return ""
