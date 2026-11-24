"""Agent-side reporter for the script report channel (coded-agents 5.6).

The design is `openspec/changes/coded-agents/design.md`, "Agent-to-mod report
channel". The rules this module implements, and nothing beyond them:

  * It posts the meter's figure. It does NOT compute a day, a window or a cap --
    all three are 5.4's and this channel states no opinion on them.
  * `previous_code_hours` is the figure the report replaces. It is present ONLY
    when that figure FELL, and absent otherwise (including on a bot's first
    report). The design needs this because the mod keeps only the latest report
    per bot: without it a fall is invisible. A rise is not a fall, so carrying a
    previous value there would invite a reader to treat growth as a reset.
  * Nothing is queued. A failed post is dropped and counted; the next interval
    sends the CURRENT value. A backlog replayed after an outage would present
    old values as current, which is the one thing a status channel must not do.
  * The report is the presence beacon: the mod dates staleness from
    `observed_at`, so a healthy but idle bot still re-sends every interval.

`build_body`/`dumps` exist so the payload shape and its size can be pinned by a
test rather than quoted from memory.
"""
from __future__ import annotations

import json
import time

#: Seconds between reports when nothing changes. The mod ages a report to
#: `stale` after 3 x this, so this value and that factor move together.
REPORT_INTERVAL = 15.0

#: The states the design's closed vocabulary allows. Anything else is a bug in
#: the caller: sending an unknown state would make the mod store a value its
#: own schema does not define.
STATES = ("script", "fallback_timeout", "fallback_refused", "stalled", "stopped")


def build_body(name, state, code_hours, previous_code_hours, ticks,
               observed_at, revision):
    """The exact dict posted to `/bot/{name}/script_report`.

    `previous_code_hours=None` means ABSENT, not null: the design says the field
    is omitted, and a null would be a claim that a previous figure exists.
    """
    body = {
        "script_state": state,
        "code_hours": round(float(code_hours), 6),
        "ticks": int(ticks),
        "observed_at": observed_at,
        "revision": revision,
    }
    if previous_code_hours is not None:
        body["previous_code_hours"] = round(float(previous_code_hours), 6)
    return body


def dumps(body):
    """One serialisation, used for both the wire and the size test.

    `separators` drops the whitespace, `sort_keys` makes the bytes stable so a
    measured size means the same thing on every run.
    """
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


class ReportSender:
    """Decides WHEN to report; `poster` decides how.

    `poster(name, body)` is injected so the cadence rules are testable without a
    mod, and so a test can make the transport fail on demand. It must raise on
    failure -- a poster that swallows its own errors makes `dropped` lie.
    """

    def __init__(self, poster, clock=time.monotonic, interval=REPORT_INTERVAL):
        self._poster = poster
        self._clock = clock
        self._interval = interval
        # Per bot: the last body actually SENT, whether one is due, and when.
        self._last = {}
        self.sent = 0
        self.dropped = 0

    def last_sent(self, name):
        """The last body successfully sent for `name`, or None.

        Returns None after a failed post, which is the point: a failure must
        not make the next comparison behave as though the value was delivered.
        """
        entry = self._last.get(name)
        return entry["body"] if entry else None

    def due(self, name, state, code_hours, ticks, observed_at, revision, now):
        """True when this bot's report should be sent now."""
        entry = self._last.get(name)
        if entry is None:
            return True
        body = entry["body"]
        changed = (body["script_state"] != state
                   or body["code_hours"] != round(float(code_hours), 6)
                   or body["ticks"] != int(ticks)
                   or body["observed_at"] != observed_at
                   or body["revision"] != revision)
        if changed:
            return True
        # Unchanged, but the mod will age it. Re-send to stay fresh.
        return (now - entry["at"]) >= self._interval

    def report(self, name, state, code_hours, ticks, observed_at, revision,
               now=None):
        """Send a report if one is due. Returns True when a report was SENT.

        Never raises for a transport failure: a reporter that can kill the tick
        it observes would be worse than no reporter.
        """
        if now is None:
            now = self._clock()
        if state not in STATES:
            raise ValueError(f"state {state!r} is not in the design's vocabulary")
        if not self.due(name, state, code_hours, ticks, observed_at, revision,
                        now):
            return False
        prev = self.last_sent(name)
        previous_code_hours = None
        if prev is not None and float(code_hours) < prev["code_hours"]:
            previous_code_hours = prev["code_hours"]
        body = build_body(name, state, code_hours, previous_code_hours, ticks,
                          observed_at, revision)
        try:
            self._poster(name, body)
        except Exception:
            # Dropped, not queued. Counting it is the only record kept.
            self.dropped += 1
            return False
        self._last[name] = {"body": body, "at": now}
        self.sent += 1
        return True
