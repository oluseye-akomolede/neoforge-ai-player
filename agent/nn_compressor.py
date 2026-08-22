"""Off-hot-path client for the neural state-compression worker.

The compressor is a BACKGROUND service, never a dependency of the decision loop.
This client:
  * runs on its own daemon thread at a slow cadence (never per-tick),
  * uses a short timeout, and
  * treats ANY failure (disabled, unreachable, slow, error) as a no-op.

So if the compressor is down, unwired, or overwhelmed, the agent is completely
unaffected — L1 pathfinding and L3 orchestration keep using raw state. The only
thing lost while it is unavailable is the compressed archival + the pre-baked L3
situational summary; those are enrichments, not correctness.

Enable by setting NN_COMPRESSOR_URL (e.g. the in-cluster service DNS); leave it
empty to disable entirely.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

import requests

from config import NN_COMPRESSOR_URL

log = logging.getLogger("aibot.nn-compressor")

# Latest L3 summary per bot (thread-safe enough for single-writer/many-reader).
_summaries: Dict[str, Dict[str, Any]] = {}
_TIMEOUT = 60.0         # generous — off the hot path, so a slow GPU compress is fine
_INTERVAL = 90.0        # seconds between sweeps (a full sweep of slow compresses fits)
_DEGRADED_BACKOFF = 120.0  # after a failure, wait longer before retrying


def enabled() -> bool:
    return bool(NN_COMPRESSOR_URL)


def latest_summary(bot: str, max_age_s: float = 180.0) -> Optional[str]:
    """The most recent L3 situational summary for a bot, or None.

    Returns None if the newest summary is older than ``max_age_s`` (the worker
    sweeps every ~90s, so a healthy summary is well under that). This stops a
    stale "situation:" line — e.g. a position from before a long teleport —
    from being injected into the planner as if it were current."""
    entry = _summaries.get(bot)
    if not entry:
        return None
    if max_age_s and (time.time() - entry.get("at", 0)) > max_age_s:
        return None
    return entry.get("summary") or None


def compress_state(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """POST one state to the worker; return its response, or None on any failure."""
    if not enabled():
        return None
    try:
        r = requests.post(f"{NN_COMPRESSOR_URL}/compress",
                          json={"state": state}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001 — degradation is by design
        log.debug("compress unavailable (%s) — using raw state", e)
        return None


def run_worker(live_bots: Callable[[], list], fetch_state: Callable[[str], Optional[Dict[str, Any]]]) -> None:
    """Daemon loop: periodically compress each live bot's state and stash its L3
    summary. Fully best-effort; a compressor outage just means empty summaries."""
    if not enabled():
        log.info("state compression disabled (NN_COMPRESSOR_URL unset)")
        return
    log.info("state compression worker started -> %s", NN_COMPRESSOR_URL)
    healthy = True
    while True:
        try:
            for name in live_bots():
                state = None
                try:
                    state = fetch_state(name)
                except Exception:
                    state = None
                if not state:
                    continue
                resp = compress_state(state)
                if resp is None:
                    healthy = False
                    continue
                healthy = True
                l3 = resp.get("l3") or {}
                _summaries[name] = {
                    "summary": l3.get("summary", ""),
                    "ratio": resp.get("ratio"),
                    "at": time.time(),
                }
        except Exception as e:  # noqa: BLE001
            log.debug("compression sweep error: %s", e)
            healthy = False
        time.sleep(_INTERVAL if healthy else _DEGRADED_BACKOFF)
