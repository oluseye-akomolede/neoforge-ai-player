"""Content dedupe for a script's `say`/`send` (change: script-say-dedupe).

A script runs every tick. A script whose job is to watch something, or to
report the situation, naturally produces the same line each time -- and a bot
that repeats "No diamond ore within 5-block radius." every ten seconds reads
as broken to a player. This records what each bot said and when, so the same
line is not delivered twice inside a minute.

This is NOT a rate limit and must not become one. It bounds how often the
SAME line reaches chat; it does not bound how many DISTINCT lines a script may
say per minute. The runner's own caps (`api.say` 30/min, `api.send` 20/min per
bot, `binding.js:96`) remain the only bound on how often a script may speak --
see `agent/agent.py:3028-3031`, "do not add a second limiter".

The memory is per bot and is deliberately not cleared by `reset()`: a reset
ends a plan, not the bot's chat presence, and a bot that just said something
should not say it again because its plan was reset. It does not survive a
process restart, which is right -- a restarted bot may say it again, and the
first line after a restart is the one a player expects to see.
"""

import time


class ScriptSayGuard:
    """Per-bot record of what was last delivered, keyed by content.

    One record per key, holding the monotonic time that key was last delivered
    and whether this window's suppression has already been logged. Both live
    in the same record so the flag cannot drift from the window it describes:
    a delivery that moves the timestamp past the window clears the flag in the
    same write.
    """

    def __init__(self, clock=time.monotonic, window_seconds=60.0):
        self._clock = clock
        self._window = window_seconds
        # key -> [last_delivered_time, logged_this_window]
        self._records = {}

    @staticmethod
    def key_for(call, text, to=None):
        """The stream a delivery belongs to.

        `send` is keyed by recipient as well as text: `send("Scout", "go")` and
        `send("Builder", "go")` are different deliveries, and the first must
        not suppress the second. `say` has no recipient.
        """
        if call == "send":
            return ("send", to or "", text or "")
        return ("say", text or "")

    def check(self, call, text, to=None):
        """Return `(should_deliver, is_first_suppression)`.

        `is_first_suppression` is True only for the first suppressed call of
        this key in the current window, so the caller logs one line per window
        rather than one per tick. It sets the record's logged flag, so a second
        call returns False. On a delivery it returns `(True, False)` and does
        not touch the record -- `deliver()` does that after the send succeeds.
        """
        key = self.key_for(call, text, to)
        record = self._records.get(key)
        if record is not None and self._clock() - record[0] < self._window:
            first = not record[1]
            record[1] = True
            return False, first
        return True, False

    def deliver(self, call, text, to=None):
        """Record that this key was just delivered, opening a fresh window."""
        self._records[self.key_for(call, text, to)] = [self._clock(), False]
