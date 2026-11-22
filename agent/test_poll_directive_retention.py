"""A completion the agent has READ must not be cancelled away.

Trial 4.2 retry (TEST, 2026-11-22 04:28Z): Forge's script waited on
``type === 'GOTO' && status === 'COMPLETED'`` and never saw it. The mod was
fine -- ``BotBrain.toMap()`` retains the terminal directive in ``lastDirective``
and the route answers it (``BotBrain.java:222-225``). The agent destroyed the
record: on reading COMPLETED (and FAILED/CANCELLED) the L1 poller called
``api.cancel_directive``, and ``BotBrain.cancelDirective`` clears all three
retention fields (``BotBrain.java:62-64``). The bot idled, goal unfinished,
until a human restarted the agent.

These tests drive the REAL ``_poll_directive`` loop. The thing being pinned is
which calls the agent makes, so the assertions are on the recorded call list,
not on a re-implementation of the loop.

Importing agent.py needs the dashboard/DB/web modules stubbed; the stub block
lives in test_agent_script_branch and is imported from there rather than
copied, so the two files cannot drift into testing different module loads.

What is NOT covered here: that the mod actually retains. That is Java-side.
``BotBrain.toMap`` retains the terminal directive in ``lastDirective`` and the
route answers it (``BotBrain.java:222-225``); the clear is
``BotBrain.cancelDirective`` at ``:62-64``. Both are verified by reading the
source, NOT by a test: ``cancelDirective`` dereferences ``bot`` at ``:53`` and
throws on a null one, so it cannot be driven server-free without a
``ServerPlayer``. The terminal-path retention IS covered, but only on the
FAILED path: ``BotBrainApplyDirectiveTest.the_failure_is_visible_to_the_next_poll``
asserts ``toMap().get("directive")`` is non-null after a failure. The COMPLETED
path assigns ``lastDirective`` the same way (``BotBrain.java:93``, the
``case SUCCESS`` branch: ``lastDirective = activeDirective`` then
``lastProgress = activeBehavior.getProgress()`` at ``:94``) but has no test of
its own. Neither is a live run; the emission half needs a server.
"""

import threading
import unittest
from unittest import mock

# Importing this module runs its stub block, which makes the REAL agent.py
# importable in a clean seat. Reusing it beats copying it.
import test_agent_script_branch as _stubs  # noqa: F401
import agent as agent_mod


def _runner():
    """A BotRunner with __init__ skipped -- the pattern the other tests use."""
    r = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
    r.name = "Forge"
    r._stop_event = threading.Event()
    r._lock = threading.Lock()
    r._new_messages = []
    r._directive_missing_count = 0
    r.DIRECTIVE_POLL_INTERVAL = 0
    return r


class PollDirectiveRetentionTest(unittest.TestCase):

    def _poll(self, brain_state):
        """Run one poll pass against `brain_state`; return (result, cancel).

        `_stop_event.wait` is neutralised rather than slept: the loop's only
        yield point is the poll interval, and these tests are about calls, not
        timing.
        """
        r = _runner()
        r._stop_event.wait = mock.Mock(return_value=False)
        with mock.patch.object(agent_mod.api, "get_brain",
                               return_value=brain_state), \
                mock.patch.object(agent_mod.api, "cancel_directive") as cancel, \
                mock.patch.object(agent_mod, "shared_state"):
            result = agent_mod.BotRunner._poll_directive.__get__(r)(
                dtype="GOTO", directive_id=7)
        return result, cancel

    def _completed(self):
        return {"directive": {"id": 7, "type": "GOTO", "status": "COMPLETED"},
                "progress": {"phase": "idle",
                             "result": {"arrived_at": {"x": -138.2,
                                                       "y": -33.7,
                                                       "z": -151.0}}}}

    def test_a_completion_does_not_trigger_a_cancel(self):
        result, cancel = self._poll(self._completed())

        self.assertTrue(result.get("success"), "COMPLETED must report success")
        self.assertEqual(cancel.call_count, 0,
            "cancelling here clears the retained directive (BotBrain.java:62-64) "
            "and is what made a script unable to see its own completion")

    def test_the_result_reaches_the_caller(self):
        # The lead's note: L1 printed `{}` for the result, so check it really
        # arrives rather than only that the cancel is gone.
        result, _ = self._poll(self._completed())

        self.assertEqual(
            result.get("progress", {}).get("result", {}).get("arrived_at"),
            {"x": -138.2, "y": -33.7, "z": -151.0},
            "the completion's result must be handed on, not dropped")

    def test_a_failure_does_not_trigger_a_cancel_either(self):
        # FAILED/CANCELLED are read the same way and must also survive, or a
        # script waiting on FAILED hangs exactly as the COMPLETED case did.
        state = {"directive": {"id": 7, "type": "GOTO", "status": "FAILED",
                               "failure_reason": "target_enclosed: no clear "
                                                 "standing position"},
                 "progress": {}}
        result, cancel = self._poll(state)

        self.assertFalse(result.get("success"))
        self.assertEqual(cancel.call_count, 0,
            "a terminal FAILED directive must stay readable to the script")

    def test_a_running_directive_is_left_to_the_stuck_paths(self):
        # The distinction the fix must preserve: a directive still RUNNING is
        # abandoned by the stuck/interrupt paths, not by the poller's terminal
        # branch. Stopping the loop while RUNNING must not be read as success.
        state = {"directive": {"id": 7, "type": "GOTO", "status": "RUNNING"},
                 "progress": {"phase": "moving"}}
        r = _runner()
        r._stop_event.wait = mock.Mock(side_effect=lambda *_: r._stop_event.set())
        with mock.patch.object(agent_mod.api, "get_brain", return_value=state), \
                mock.patch.object(agent_mod.api, "cancel_directive") as cancel, \
                mock.patch.object(agent_mod, "shared_state"):
            result = agent_mod.BotRunner._poll_directive.__get__(r)(
                dtype="GOTO", directive_id=7)

        self.assertEqual(cancel.call_count, 0,
            "a RUNNING directive is left alone by the poller; abandoning it is "
            "the stuck/interrupt paths' job")
        self.assertFalse(result.get("success"),
                         "a stop while RUNNING is not a success")


if __name__ == "__main__":
    unittest.main()
