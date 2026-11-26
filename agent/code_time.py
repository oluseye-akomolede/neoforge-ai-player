"""Per-bot code-time metering (change: coded-agents, task 5.1).

A *code hour* is wall-clock time during which a bot's script is active. The
unit is the TICK PERIOD, counted once for each tick the game actually SENDS --
not CPU time, and not a wall clock read between ticks. The spec makes those two
alternatives explicitly wrong (spec, "Code Time Is Metered Per Bot"):

  * CPU time is a *reported* field for visibility, not the cap's unit. A few
    milliseconds of CPU per tick would take days to reach an hours-per-day cap,
    so a CPU-counted cap would silently never fire.
  * A wall clock read between ticks would bill time the bot was not allowed to
    run. The counter is fed only at the send point, so time a script spends
    paused, deleted, fallen back to the planner, or HELD for a player goal
    accrues nothing -- for those, no tick is sent at all, and the tick is the
    only thing this counter sees.

  * NOT gated here: a tick that IS sent but that the runner refuses or times
    out on (an unreachable runner returns `handled=False` with a "runner
    fallback..." detail). That call still reaches the counter and is billed one
    period. This counter meters "a tick was sent", not "the runner ran it"; the
    reviewer flagged it (F-1, 2026-11-23) and it is left deliberately -- whether
    refused time is billable is task 5.4's decision, not 5.1's.

The game (here, the Python agent; spec.md:123) sends the tick. This module is
the one place that turns a sent tick into usage.

Counted per bot and never summed across bots: the bot is the unit of both
measurement and summation, and no player identity exists to attribute to.

## What the spec does NOT say (reported, not chosen)

Two questions are silent in the change spec and are deliberately NOT answered
here; a future task must settle them with the owner rather than have this
module guess:

  1. **Day boundary.** The allowance is "hours/day", but nothing says when the
     day rolls over (UTC midnight? first tick after a gap? a rolling 24h
     window?). Until a day is defined there is nothing to reset, so
     `usage_hours` is a monotonic process-lifetime total, NOT a daily figure.
  2. **Restart persistence.** Nothing says whether usage must survive an agent
     pod restart. `result_delivery.py` and script memory both reset on restart
     by construction, and nothing persists this counter, so a pod restart
     zeroes it. `5.5` proves recording within one process lifetime; it does
     not prove survival across a restart because the spec does not require it.

## The cap seam

`daily_cap_hours` is the ONE place a cap value is read, and it is resolved when
a meter is constructed from the deployment's `CODE_HOURS_CAP` (owner decision
B2, 2026-11-26: hours per day per bot, unset or empty = unlimited). The source
is now settled -- it was "open" in the earlier draft of this docstring, and
that is no longer true.

Reading it once at construction, not per tick, is the spec's requirement
("The cap is read once, not per tick"): a cap that moved mid-process would make
a bot's allowance depend on when the pod was rescheduled rather than on usage.
Enforcement (pause at exhaustion) is task 5.4, not here; this module still only
exposes the value.
"""

import threading

import config

# Owner decision B: the default is unlimited.
UNLIMITED = None

# Sentinel for "no cap argument was passed", distinct from an explicit
# UNLIMITED (None), so a caller that means unlimited can say so and a caller
# that says nothing gets the deployment's configured cap.
_UNSET = object()

# A tick's period, in seconds. Configurable via TICK_DELAY for a test or a
# deployment, but the spec fixes the real cadence at 2.0 s (0.5 ticks/s); the
# metering must use the SAME number the send loop waits, so this is imported
# from config rather than re-declared.
from config import TICK_DELAY


class CodeTimeMeter:
    """Records active script time for ONE bot, in tick periods.

    Fed once per tick that is actually sent. `record_tick()` adds exactly one
    TICK_DELAY; nothing else can add time. The instance is per bot, so usage is
    never summed across bots.

    Thread-safety: the agent runs one poll loop per bot, but `usage_hours` may
    be read from another thread (a status/telemetry surface later), so the
    total is guarded by a lock.
    """

    def __init__(self, tick_period=TICK_DELAY, daily_cap_hours=_UNSET):
        """`daily_cap_hours` defaults to the deployment's configured cap.

        The default is deliberately NOT evaluated at import time: reading the
        env var at import would fix one value for the process but make it
        untestable without reloading config, and a caller that passes an
        explicit cap (tests do) must win. Resolved once, here, so every
        construction site gets the configured cap without having to remember
        to thread it -- a bot whose meter was built by a path that forgot the
        argument would otherwise run uncapped while its neighbour did not.
        """
        self._tick_period = float(tick_period)
        self._daily_cap_hours = (config.code_hours_cap()
                                 if daily_cap_hours is _UNSET
                                 else daily_cap_hours)
        self._seconds = 0.0
        self._ticks = 0
        self._lock = threading.Lock()

    # -- the only mutator ---------------------------------------------------

    def record_tick(self):
        """Count ONE sent tick. The sole way usage increases.

        Called at the send point, after the hold check, so a held, paused,
        deleted or fallen-back script -- none of which sends a tick -- never
        reaches here and accrues nothing. A tick the runner REFUSED or timed out
        on DOES reach here and is billed one period (see the module docstring);
        whether that should bill is 5.4's call, not this meter's.
        """
        with self._lock:
            self._ticks += 1
            self._seconds += self._tick_period

    # -- the accessor (task 5.1's "exposed" half) ---------------------------

    def usage_hours(self):
        """Active script time recorded for this bot, in hours.

        A PROCESS-LIFETIME total, not a daily figure: the day boundary is
        undefined in the spec (see the module docstring). Never summed with
        another bot's usage.
        """
        with self._lock:
            return self._seconds / 3600.0

    def usage_seconds(self):
        """Same total in seconds, for a caller that wants the raw unit."""
        with self._lock:
            return self._seconds

    def tick_count(self):
        """Number of ticks counted. Equals `usage_seconds / tick_period`, kept
        because the tick count is the quantity the cap is specified to count."""
        with self._lock:
            return self._ticks

    # -- the one cap seam (task 5.3 is deferred; this is read-only here) -----

    def daily_cap_hours(self):
        """The cap this bot is held to, in hours per day, or UNLIMITED (None).

        Captured at construction from the deployment's `CODE_HOURS_CAP` unless
        the caller passed one; see the module docstring. Task 5.4 will compare
        `usage_hours()` against this; nothing compares it yet, so a configured
        cap is recorded and reported but never fires.
        """
        return self._daily_cap_hours

    def is_exhausted(self):
        """Whether this bot has used up its allowance.

        Always False while the cap is UNLIMITED, which is every deployment of
        this release. Present so 5.4 has one call site to wire, and so the
        unlimited default is exercised rather than assumed.
        """
        cap = self.daily_cap_hours()
        if cap is UNLIMITED:
            return False
        return self.usage_hours() >= cap
