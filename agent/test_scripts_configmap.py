"""The ConfigMap copy of scout.js must match agent/scripts/scout.js.

test_scout_script.py reads the repo file. The agent pod, when the step-4 plan
mounts it, reads the ConfigMap. Those are two copies of one script, so they can
drift in exactly the silent way a duplicate always does: the tests stay green
against the file nobody deploy. This checks the copy that would actually run.

It is a separate file from test_scout_script.py on purpose: that one must stay
runnable without PyYAML, and this one needs it to parse the manifest.

PyYAML ABSENCE IS A FAILURE, NOT A SKIP (reviewer, 12:44Z). This class used to
carry @skipUnless(yaml is not None), which wraps every test in it -- so in any
seat without PyYAML the drift check silently did not run and the suite still
printed OK. That is the same inert check this repo already fixed one file over,
and it bit exactly where it matters: this is the copy the pod actually runs.
`setUp` raises here instead, so a missing PyYAML goes red with a message that
says what to install. There is no configuration in which this file is green
without having checked anything.
"""
from __future__ import annotations

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_HERE, "scripts", "scout.js")
_CONFIGMAP = os.path.join(_ROOT, "deploy", "agent-scripts.yaml")

try:
    import yaml
except ImportError:  # pragma: no cover - asserted in setUp, never skipped
    yaml = None


class ConfigMapDriftTest(unittest.TestCase):

    def setUp(self):
        # Deliberately NOT a skip: a skipped drift test is indistinguishable
        # from a passing one in the summary line, and this is the copy that
        # ships. Fail loudly and name the install.
        if yaml is None:
            self.fail("PyYAML is required for the ConfigMap drift test "
                      "(pip install pyyaml). It must not be skipped: the "
                      "ConfigMap copy is the one the pod runs, so a silent "
                      "no-op here is the drift nobody catches.")

    def test_configmap_matches_the_script(self):
        doc = yaml.safe_load(open(_CONFIGMAP, encoding="utf-8"))
        self.assertEqual(doc.get("kind"), "ConfigMap")
        data = doc.get("data") or {}
        self.assertIn("scout.js", data,
                      "agent-scripts ConfigMap does not carry scout.js")
        script = open(_SCRIPT, encoding="utf-8").read().strip()
        self.assertEqual(data["scout.js"].strip(), script,
                         "ConfigMap copy of scout.js has drifted from agent/scripts/scout.js "
                         "-- run scripts/gen-scripts-cm.py")

    def test_the_configmap_is_not_mounted_yet(self):
        # The manifest says the pod does not mount this. If someone adds the
        # volume without updating that comment (and the step-4 plan), the
        # comment becomes a lie. This fails on the first half of that: it pins
        # the fact the comment asserts, so editing the deployment is noticed.
        dep = open(os.path.join(_ROOT, "deploy", "agent-deployment.yaml"),
                   encoding="utf-8").read()
        self.assertNotIn("agent-scripts", dep,
                         "agent-deployment.yaml now references agent-scripts: the ConfigMap "
                         "header comment and the step-4 run plan both claim it is unmounted. "
                         "Update both, and this test, together.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
