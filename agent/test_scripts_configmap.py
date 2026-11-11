"""The ConfigMap copy of scout.js must match agent/scripts/scout.js.

test_scout_script.py reads the repo file. The agent pod, when the step-4 plan
mounts it, reads the ConfigMap. Those are two copies of one script, so they can
drift in exactly the silent way a duplicate always does: the tests stay green
against the file nobody deploy. This checks the copy that would actually run.

It is a separate file from test_scout_script.py on purpose: that one must stay
runnable without PyYAML, and this one needs it to parse the manifest.
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
except ImportError:  # pragma: no cover
    yaml = None


@unittest.skipUnless(yaml is not None, "PyYAML is required to parse the manifest")
class ConfigMapDriftTest(unittest.TestCase):

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
