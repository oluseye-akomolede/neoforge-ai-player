"""
SharedState — thread-safe bridge between synchronous bot threads and async WebSocket layer.

Bot threads call push_snapshot() on each observe tick.
The FastAPI WebSocket layer awaits changed() to get notified of new data.
"""

import asyncio
import threading
import time
from typing import Any


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._bots: dict[str, dict[str, Any]] = {}
        self._server: dict[str, Any] = {}
        self._events: list[dict] = []
        self._max_events = 200
        self._version = 0
        self._async_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._async_event = asyncio.Event()

    def push_bot_snapshot(self, name: str, snapshot: dict):
        with self._lock:
            self._bots[name] = snapshot
            self._version += 1
        self._notify()

    def push_server_snapshot(self, snapshot: dict):
        with self._lock:
            self._server = snapshot
            self._version += 1
        self._notify()

    def push_event(self, event: dict):
        event.setdefault("ts", time.time())
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
            self._version += 1
        self._notify()

    def remove_bot(self, name: str):
        with self._lock:
            self._bots.pop(name, None)
            self._version += 1
        self._notify()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "version": self._version,
                "bots": dict(self._bots),
                "server": dict(self._server),
            }

    def events_since(self, after_ts: float) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["ts"] > after_ts]

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def _notify(self):
        if self._loop and self._async_event:
            self._loop.call_soon_threadsafe(self._async_event.set)

    async def changed(self):
        if self._async_event:
            await self._async_event.wait()
            self._async_event.clear()


shared_state = SharedState()
