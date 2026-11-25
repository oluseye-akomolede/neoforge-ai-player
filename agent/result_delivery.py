"""Delivery of script results to the planner (change: script-lookups-and-results).

A script reports with `api.result(v)`. That call stores a value for the NEXT
trigger to deliver -- it raises no trigger of its own. The triggers the agent
actually produces are `done` and `error`: `error` when the script's own
`{done: false}` says it failed, or when the tick threw (the status decides
then, whatever the carried result says). `escalate` is accepted by this
module and handled as non-done, but NO producer stores it today -- only tests
do -- so it is a spare seat, not a live contract.

Owner A2 (2026-11-25 00:59Z) REMOVED the per-bot rate cap and the 15-minute
cooldown: a script may wake the planner on every stated trigger. The only
remaining bound is serialisation, and it does NOT live here -- the caller skips
delivery while a planner call is in flight (`agent/agent.py`, the `_plan_steps`
check in `_maybe_plan_on_result`). This module is now just the pending slot.

One slot per bot, holding at most one pending result. Keyed on the bot, not the
script, because a reported `done` releases the script hold and the next report
comes from a different script.

State lives for the process lifetime and survives `agent.reset()`: a reset
clears a bot's plan and releases its script hold, but a pending result is the
next trigger's business, not the reset's.
"""

class ResultSlot:
    """One bot's result-delivery state: the single pending value."""

    def __init__(self):
        self._pending = None          # (goal_id, value, trigger)

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

    # -- delivery -----------------------------------------------------
    def may_call(self, goal_id=None):
        """(allowed, reason). No rate cap or cooldown (owner A2) -- the only
        refusals left are about WHICH result this is, not how often."""
        pending = self._pending
        if pending is None:
            return False, "no-result"
        if goal_id is not None and pending[0] != goal_id:
            return False, "goal-changed"
        return True, None

    def record_call(self):
        """Consume the pending result after a delivered call."""
        self._pending = None

    def hold_reason(self):
        """Why a pending result is currently held off, for the log."""
        allowed, reason = self.may_call()
        return None if allowed else reason
