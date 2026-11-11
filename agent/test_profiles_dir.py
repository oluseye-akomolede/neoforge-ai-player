"""load_profiles() must read the directory PROFILES_DIR names.

This exists because that cell was a silent no-op for a whole review cycle. The
Deployment mounts the `agent-data` PVC at /opt/aibot-agent/data, but
load_profiles() read dirname(__file__)/profiles -- the image path. A plan that
edited a profile on the PVC therefore changed a file nothing reads, and the
only symptom would have been that script mode never turned on.

A mutant that ignores the env var and hardcodes the image path survived the
whole 108-test suite. That is the defect this file closes.

Import stubbing matches test_agent_script_branch.py, which learned it the hard
way: a version that skipped every test in a clean seat still printed OK.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock


class _Any:
    def __call__(self, *a, **k):
        return _Any()

    def __getattr__(self, n):
        return _Any()

    def __iter__(self):
        return iter(())


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


# The stubs must be installed before agent.py is imported, and the real
# `dashboard` package must not win: stub its submodules too.
_STUBS = (
    "psycopg2", "psycopg2.extras", "uvicorn", "fastapi", "fastapi.responses",
    "fastapi.staticfiles", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic", "starlette.responses", "python_multipart",
)
for _m in _STUBS:
    sys.modules.setdefault(_m, _Mod(_m))
sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _agent_module():
    import agent as agent_mod
    return agent_mod


class ProfilesDirTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod = _agent_module()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "scout.json"), "w") as f:
            json.dump({"name": "Scout", "script": "scout.js"}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self, value):
        return mock.patch.dict(os.environ, {"PROFILES_DIR": value}
                               if value is not None else {}, clear=False)

    def test_profiles_dir_env_is_honoured(self):
        # The load-bearing assertion. If this fails, a profile written to the
        # mounted volume is invisible to the loader, and every "did script mode
        # turn on?" check reads whatever the image shipped instead.
        with self._env(self.tmp):
            profiles = self.mod.load_profiles()
        names = [p.get("name") for p in profiles]
        self.assertEqual(names, ["Scout"], f"PROFILES_DIR ignored; got {names}")

    def test_unset_falls_back_to_the_image_path(self):
        # Prod sets nothing. Unset must mean exactly today's behaviour.
        env = {k: v for k, v in os.environ.items() if k != "PROFILES_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(self.mod.os.path, "isdir", return_value=True):
                with mock.patch.object(self.mod.os, "listdir", return_value=[]):
                    self.assertEqual(self.mod.load_profiles(), [])

    def test_empty_string_falls_back_like_unset(self):
        # An env var set to "" is what a half-configured manifest produces.
        # `or` makes it behave as unset rather than as the cwd.
        with self._env(""):
            with mock.patch.object(self.mod.os.path, "isdir", return_value=True):
                with mock.patch.object(self.mod.os, "listdir", return_value=[]):
                    self.assertEqual(self.mod.load_profiles(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
