"""Regression test for the run-1 dispatch failure (2026-11-12, M2 step 4).

THE BUG IT PINS. `_l3_orchestrator_dispatch` built the directive params as
`params = dict(directive)` and then splatted them into
`api.set_directive(self.name, dtype, **params)`. That signature accepts only
type/target/count/radius/x/y/z/extra (plus the positional bot), so ANY other
key L3 supplied was a TypeError that killed the directive before it reached
the mod:

    [Scout/L1] Failed to send directive: set_directive() got an unexpected
    keyword argument 'container'

Run 1 on TEST produced exactly that line five times and the planner never
dispatched anything. The cause on the L3 side was kind=SEARCH_AND_STORE
carrying a stray `container` key; l2-mcp flagged that kind unknown_kind and
passed it through fail-open, so nothing ever removed the key.

WHAT THIS TEST DOES NOT DO. It does not assert "dispatch no longer raises".
A test written that way passes for any number of reasons -- a different
exception, a mocked callee, a directive that never gets built. It asserts the
two properties the fix actually has to deliver, and it fails without the fix:

  1. the stray key does not reach api.set_directive, and the directive is
     still dispatched (not dropped entirely), and
  2. the dropped key's NAME is logged -- the lead's explicit condition. A fix
     that filtered silently would satisfy (1) and lose the field invisibly,
     which is the same class of defect as the original.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


class _Any:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __iter__(self):
        return iter(())

    def __getattr__(self, n):
        return _Any()


class _BaseModel:
    def __init__(self, *a, **k):
        pass

    def __init_subclass__(cls, **k):
        pass


class _Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _BaseModel if n == "BaseModel" else _Any()


# Same reason as test_agent_script_branch.py: agent.py imports the dashboard
# (fastapi), the DB (psycopg2) and uvicorn at module scope. Stub them so the
# REAL agent.py loads and the REAL dispatch method runs. A version of this test
# that stubbed _l3_orchestrator_dispatch would assert nothing about the code
# under test.
_STUBS = (
    "psycopg2", "psycopg2.extras", "uvicorn", "fastapi", "fastapi.responses",
    "fastapi.staticfiles", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic", "starlette.responses", "python_multipart",
)
for _m in _STUBS:
    sys.modules.setdefault(_m, _Mod(_m))
sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]


def _agent_module():
    return importlib.import_module("agent")


class DirectiveParamFilterTest(unittest.TestCase):

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a.name = "Scout"
        # Dispatched-directive bookkeeping the real method touches.
        self.a._task_sender = ""
        self.a._record_finding = mock.Mock()
        # Capture what api.set_directive would actually receive, and stand in
        # for the mod's response so the method gets past the POST.
        self.captured = {}

    def _run(self, directive):
        """Run the REAL dispatch -> REAL _run_directive, recording the call.

        Only the two boundaries are stubbed: api.set_directive (the POST) and
        _poll_directive (the POLL). _run_directive itself RUNS, because the
        TypeError run 1 hit was raised INSIDE it, at the
        `api.set_directive(self.name, dtype, **params)` splat. A test that
        mocked _run_directive out would never execute that line -- the exact
        "fixture that never reaches the gate" failure this session kept
        finding.

        The stub carries the REAL function's signature: the fix reads
        inspect.signature(api.set_directive) to build its allowlist, and a
        bare Mock reports (*args, **kwargs), which would make it drop every
        key. That is a stub artefact, not a property of the code under test.

        It must be a REAL FUNCTION rebound into the module, not a MagicMock
        with __signature__ attached: _set_directive_params calls
        inspect.signature(api.set_directive) on the MODULE ATTRIBUTE, so a
        patched mock is what gets inspected and the stub's __signature__ is
        never consulted. The first version of this test made exactly that
        mistake, so it exercised the fallback set -- which happened to contain
        `type` -- and never ran the signature path or found that the filter
        dropped the kind (reviewer, 2026-11-12).
        """
        real = self.agent_mod.api.set_directive

        def fake_set_directive(bot, directive_type, target=None, count=None,
                               radius=None, x=None, y=None, z=None,
                               extra=None):
            self.captured["bot"] = bot
            self.captured["type"] = directive_type
            for k, v in (("target", target), ("count", count),
                         ("radius", radius), ("x", x), ("y", y), ("z", z),
                         ("extra", extra)):
                if v is not None:
                    self.captured[k] = v
            return {"status": "accepted", "directive": {"id": 7}}

        # _run_directive reads these; __new__ skipped __init__.
        self.a.L2_MAX_RETRIES = 0
        self.a._stop_event = mock.Mock()
        self.a._stop_event.is_set.return_value = False
        self.a._store_success_memory = mock.Mock()
        self.a._l2_adjust = mock.Mock(return_value=None)

        # mock.patch replaces the module attribute, so if the mock is installed
        # BEFORE the helper runs, the helper inspects the mock. Bind the real
        # function in place of the mock for the duration instead.
        self.agent_mod.api.set_directive = fake_set_directive
        try:
            with mock.patch.object(self.agent_mod.api, "system_chat"), \
                 mock.patch.object(self.a, "_poll_directive",
                                   return_value={"success": True,
                                                 "progress": {"counters": {}}}):
                return self.a._l3_orchestrator_dispatch(directive)
        finally:
            self.agent_mod.api.set_directive = real

    def test_helper_agrees_with_the_real_callee(self):
        # The reviewer's condition: the allowlist must be the callee's real
        # parameter names. If the helper and api.set_directive ever disagree,
        # the filter drops a live field -- which is how `type` was lost. This
        # asserts the two contracts are the same set, not merely non-empty.
        names = self.agent_mod._set_directive_params(
            self.agent_mod.api.set_directive)
        real = {n for n, p in inspect.signature(
            self.agent_mod.api.set_directive).parameters.items()
            if n != "bot" and p.kind in (p.POSITIONAL_OR_KEYWORD,
                                         p.KEYWORD_ONLY)}
        self.assertEqual(names, real,
                         "the filter's allowed set differs from the callee's "
                         "real signature: a key in the gap is silently dropped")
        self.assertIn("directive_type", names,
                      "directive_type missing: api.py:428 takes that name")

    def test_run1_stray_container_key_is_dropped_and_dispatched(self):
        # The exact directive shape that failed run 1: a known kind carrying an
        # extra key. `container` is not in api.set_directive's signature.
        out = self._run({"kind": "STORE_ALL", "target": "",
                         "container": "nearby_chest"})
        self.assertNotIn("did not reach", str(out),
                         "regression: the stray key still broke dispatch")
        self.assertEqual(self.captured.get("type"), "STORE_ALL",
                         "the directive was dropped instead of filtered")
        self.assertNotIn("container", self.captured,
                         "the stray key still reached api.set_directive")
        self.assertIn("COMPLETED", str(out),
                      f"dispatch did not complete: {out}")

    def test_dropped_key_is_named_in_the_log(self):
        # Lead's condition: never silently lose a field. Capture stdout and
        # require the key's NAME in it.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run({"kind": "STORE_ALL", "container": "nearby_chest"})
        logged = buf.getvalue()
        self.assertIn("container", logged,
                      "the dropped key was not named in any log line - "
                      "a silent drop is the defect, not the fix")

    def test_legitimate_keys_are_all_preserved(self):
        # The filter must not over-reach: every real directive parameter has to
        # survive intact, or the fix trades one silent loss for another.
        out = self._run({"kind": "MINE", "target": "iron_ore", "count": 4,
                         "radius": 32, "x": 1, "y": 64, "z": -3,
                         "extra": {"note": "keep"}})
        self.assertEqual(self.captured.get("type"), "MINE")
        for k, v in (("target", "iron_ore"), ("count", 4), ("radius", 32),
                     ("x", 1), ("y", 64), ("z", -3), ("extra", {"note": "keep"})):
            self.assertEqual(self.captured.get(k), v, f"{k} was not preserved")
        self.assertIn("COMPLETED", str(out))

    def test_a_clean_directive_logs_no_drop_line(self):
        # The inverse control. Without this, a filter that always printed a
        # drop line would pass the naming test above while crying wolf on
        # every normal dispatch.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run({"kind": "MINE", "target": "stone"})
        self.assertNotIn("dropping non-directive key", buf.getvalue(),
                         "a directive with no stray keys still reported a drop")


if __name__ == "__main__":
    unittest.main()
