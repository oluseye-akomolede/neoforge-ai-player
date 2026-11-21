"""Delivery of script results to the planner (change: script-lookups-and-results).

A script reports with `api.result(v)`. That call stores a value for the NEXT
trigger (done / error / escalate) to deliver -- it raises no trigger of its
own. This module holds the rules that decide whether a stored result may
actually start a planner call:

  * a per-bot cap of 4 result-triggered calls per hour;
  * a per-bot cooldown of 15 minutes between them;
  * one slot per bot, holding at most one pending result.

The caps are the load-bearing guard, not a backstop: without them a script
that reports `done` every tick would drive one `call_plan` per tick. They are
keyed on the BOT, not on the script, because a reported `done` releases the
script hold and the next report comes from a different script -- the
bind/release bypass that a script-keyed counter would let through.

State lives for the process lifetime and survives `agent.reset()`: a reset
clears a bot's plan and releases its script hold, but it is not an amnesty
for the planner-call budget.
"""

import time

MAX_RESULTS_PER_HOUR = 4
COOLDOWN_SECONDS = 15 * 60
HOUR_SECONDS = 60 * 60


class ResultSlot:
    """One bot's result-delivery state: the pending value and the call log."""

    def __init__(self, clock=time.monotonic,
                 max_per_hour=MAX_RESULTS_PER_HOUR,
                 cooldown_seconds=COOLDOWN_SECONDS):
        self._clock = clock
        self._max_per_hour = max_per_hour
        self._cooldown = cooldown_seconds
        self._pending = None          # (goal_id, value, trigger)
        self._call_times = []         # monotonic timestamps of actual calls

    # -- storing ------------------------------------------------------
    def store(self, goal_id, value, trigger):
        """Park a result for the next trigger.

        `goal_id` is the goal that was running. A result whose goal differs
        from the bot's current goal is discarded at delivery time, not here,
        so this stays a dumb slot.
        """
        self._pending = (goal_id, value, trigger)

    def has_pending(self):
        return self._pending is not None

    def peek(self):
        return self._pending

    def clear(self):
        self._pending = None

    # -- the guard ----------------------------------------------------
    def _recent_calls(self):
        now = self._clock()
        return [t for t in self._call_times if now - t < HOUR_SECONDS]

    def may_call(self, goal_id=None):
        """(allowed, reason). Reason is None when allowed."""
        pending = self._pending
        if pending is None:
            return False, "no-result"
        if goal_id is not None and pending[0] != goal_id:
            return False, "goal-changed"
        recent = self._recent_calls()
        # The cooldown is checked FIRST because it is the binding limit: at a
        # 900s cooldown the hourly cap cannot be reached on its own (four
        # calls span the window exactly), so when both would refuse the real
        # reason is the cooldown. Naming the cap there sent 424 of 466 of the
        # reviewer's refusals to the wrong reason.
        if recent and (self._clock() - max(recent)) < self._cooldown:
            return False, "cooldown"
        if len(recent) >= self._max_per_hour:
            return False, "hour-cap"
        return True, None

    def record_call(self):
        """Count a call that actually happened, and consume the pending result."""
        self._call_times.append(self._clock())
        self._call_times = self._recent_calls()
        self._pending = None

    def hold_reason(self):
        """Why a pending result is currently held off, for the log."""
        allowed, reason = self.may_call()
        return None if allowed else reason
