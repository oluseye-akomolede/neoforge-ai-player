#!/usr/bin/env python3
"""Regenerate deploy/agent-scripts.yaml from agent/scripts/*.js.

The ConfigMap duplicates the script text, so the two can drift. This script is
the single direction of truth: the .js files are authoritative, the ConfigMap is
output. Run it after any script edit and commit both.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "agent", "scripts")
OUT = os.path.join(ROOT, "deploy", "agent-scripts.yaml")

HEADER = """# The M2 scripts, delivered to the agent pods as files.
#
# scout.js is the first script (task 8.2). It lives here rather than baked into
# the image so a script change does not need a rebuild -- but that only holds if
# the pod actually MOUNTS this, and it does not yet: agent-deployment.yaml has
# `envFrom: secretRef` only, no volume. Mounting it is part of the step-4 TEST
# run plan, not something this file can do on its own.
#
# The agent reads a script only when a bot's profile names one
# (`"script": "<path>"`, see BotRunner._get_script_tick). Without that profile
# entry this ConfigMap changes nothing, which is the safe default.
#
# scout.js below is GENERATED from agent/scripts/scout.js by scripts/gen-scripts-cm.py.
# Edit the .js, then regenerate; do not hand-edit the block.
"""


def main():
    blocks = []
    for name in sorted(os.listdir(SCRIPTS)):
        if not name.endswith(".js"):
            continue
        text = open(os.path.join(SCRIPTS, name), encoding="utf-8").read()
        body = "\n".join(("    " + ln) if ln else "" for ln in text.rstrip("\n").split("\n"))
        blocks.append(f"  {name}: |\n{body}")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HEADER + "\napiVersion: v1\nkind: ConfigMap\nmetadata:\n"
                "  name: agent-scripts\n  labels:\n    app: aibot-agent\n"
                "data:\n" + "\n".join(blocks) + "\n")


if __name__ == "__main__":
    main()
