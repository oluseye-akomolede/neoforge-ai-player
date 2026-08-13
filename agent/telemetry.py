"""Agent → mod thought stream.

The overlay's Mind tab shows the player what a bot is thinking. The thinking
happens HERE — plans, criteria, verdicts — and until now its only trace was
kubectl logs. Each transition worth seeing gets pushed to the mod, which
caches per bot and forwards to subscribed overlay clients.

Fire-and-forget on purpose: telemetry must never slow or break planning.
A dead mod endpoint costs one warning, then silence for a cooldown.
"""
import threading
import time

import requests

from config import MOD_API_URL, MOD_API_KEY

_TIMEOUT = 2.0
_COOLDOWN_SECONDS = 60
_muted_until = 0.0
_lock = threading.Lock()


def push(bot: str, type_: str, text: str):
    """Send one thought. Never raises; never blocks the caller thread."""
    threading.Thread(target=_send, args=(bot, type_, str(text)[:240]),
                     daemon=True).start()


def _send(bot: str, type_: str, text: str):
    global _muted_until
    with _lock:
        if time.time() < _muted_until:
            return
    try:
        headers = {"X-Api-Key": MOD_API_KEY} if MOD_API_KEY else {}
        requests.post(f"{MOD_API_URL}/telemetry/event",
                      json={"bot": bot, "type": type_, "text": text},
                      headers=headers, timeout=_TIMEOUT)
    except Exception:
        with _lock:
            _muted_until = time.time() + _COOLDOWN_SECONDS
