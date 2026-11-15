#!/usr/bin/env python3
"""The apply commands and the Job must name the same ConfigMaps.

This exists because they drifted. make-evals-configmap.sh had a
`command -v kubectl` branch that created ONE ConfigMap from the whole cases
directory -- the unsplit set the size guard refuses -- and never created the
rebuild ConfigMap at all, while the Job mounts both. The branch only fired on
a machine with kubectl, so every run on this VM took the other branch and
nothing here could see it.

So we do not compare a branch to a branch. We parse the ConfigMap names the Job
mounts, parse the names the script tells the operator to create, and require
the sets to match. Run it after any edit to either file.

Exit 0 = the Job's volumes are all created by the printed commands and nothing
extra is created. Anything else is a defect, and the message names it.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def job_mounts(text):
    """ConfigMap names the Job projects, with the paths they land on."""
    names = {}
    for m in re.finditer(
        r"-\s*name:\s*(?P<vol>[A-Za-z0-9-]+)\s*\n\s*configMap:\s*\n\s*name:\s*(?P<cm>[A-Za-z0-9_$.-]+)",
        text,
    ):
        names[m.group("vol")] = m.group("cm")
    return names


def actionable_commands(text):
    """Command strings the script will actually print for the operator to run.

    The script prints them as  echo "  ssh controlplane '<kubectl ...>'". Take
    the argument of each echo that carries a kubectl, and drop anything whose
    payload is itself a comment or a note. This is deliberately narrow: a guard
    that reads prose instead of commands can be satisfied by prose, which is
    exactly the bug this function exists to prevent.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("echo "):
            continue
        # Take the double-quoted argument of the echo.
        m = re.search(r'echo\s+"(.*)"\s*$', stripped)
        if not m:
            continue
        payload = m.group(1)
        # A payload that begins with '#' is a note we print, not a command.
        if payload.lstrip().startswith("#"):
            continue
        if "kubectl" not in payload:
            continue
        out.append(payload)
    return out


def printed_creates(text):
    """ConfigMap names the script tells the operator to `kubectl create`.

    Uses the same actionable-command extractor as the guards: a `kubectl create`
    mentioned in a comment creates nothing.
    """
    names = []
    for cmd in actionable_commands(text):
        names.extend(re.findall(r"kubectl create configmap \$?([A-Za-z0-9_-]+)", cmd))
    return names


def main():
    job = (HERE / "job-evals.yaml").read_text()
    script = (HERE / "make-evals-configmap.sh").read_text()

    # A second, kubectl-gated branch is how the last drift happened: it created
    # a different shape than the branch we can run here, so no local check could
    # see it. Forbid it. One shape, always printed, always inspected.
    if re.search(r"if\s+command\s+-v\s+kubectl", script):
        print("FAIL: make-evals-configmap.sh branches on `command -v kubectl`.")
        print("That branch never runs on this VM, so it cannot be checked here --")
        print("it is how the unsplit-set + missing-rebuild-ConfigMap bug shipped.")
        print("Delete the branch and always print the operator commands.")
        return 1

    # Every guard below must scan ONLY what will actually execute. The first
    # version of these guards searched the whole file, and the script's own
    # comments mention "--server-side" and "kubectl delete configmap" -- so the
    # server-side guard was permanently False and the delete guard was fooled
    # by a comment that merely said to delete. Both were green on the very bugs
    # they existed to catch. Read the commands, never the prose.
    cmds = actionable_commands(script)
    kubectl = [c for c in cmds if "kubectl" in c]

    if not kubectl:
        print("FAIL: parsed no executable kubectl commands from the script. "
              "The regex is wrong, not the script -- a guard over an empty "
              "list passes everything.")
        return 2

    bad = []
    for cmd in kubectl:
        # Client-side apply embeds the manifest in a last-applied annotation
        # capped at 262144 B; a ~600 KB ConfigMap cannot be applied that way.
        # The test is per-command: an --server-side elsewhere in the file does
        # not licence a client-side apply here.
        if "apply -f -" in cmd and "--server-side" not in cmd:
            bad.append(("client-side apply", cmd))

    if bad:
        for why, cmd in bad:
            print(f"FAIL ({why}): {cmd.strip()}")
        print("A ~600 KB ConfigMap exceeds the 262144 B last-applied annotation "
              "cap, so this apply fails on controlplane. Use --server-side, or "
              "delete-then-create.")
        return 1

    # `apply` merges: keys absent from the new manifest survive. The split left
    # plan.jsonl/replan.jsonl inside the exec ConfigMap that way. If anything
    # applies rather than creates, a delete must be present in the commands
    # themselves -- a comment saying to delete is not a delete.
    applies = [c for c in kubectl if " apply " in f" {c} "]
    deletes = [c for c in kubectl if "delete configmap" in c]
    creates = [c for c in kubectl if "create configmap" in c]
    if (applies or creates) and not deletes:
        print("FAIL: the script creates/applies ConfigMaps but never deletes "
              "them (checked executable commands only).")
        print("`kubectl apply` is a merge and leaves stale keys in place -- the "
              "11-14 unsplit map kept plan.jsonl/replan.jsonl in the exec "
              "ConfigMap this way. Use delete-then-create.")
        return 1

    mounted = job_mounts(job)
    # The script prints shell variables ($NAME, $REBUILD_NAME, $CODE_NAME).
    # Resolve them to the literal defaults declared at the top of the script,
    # since that is what the lead will get when they run it unmodified.
    # Declarations are shell parameter expansion: NAME=${NAME:-evals-scout-cases}
    # or a literal. Take the default arm; a literal is its own default.
    raw = dict(re.findall(r'^(NAME|REBUILD_NAME|CODE_NAME)=(.*)$', script, re.M))
    defaults = {}
    for key, val in raw.items():
        val = val.strip().strip('"')
        m = re.fullmatch(r"\$\{%s:-(.*)\}" % key, val)
        defaults[key] = m.group(1) if m else val
    # REBUILD_NAME's default is itself an expansion of NAME.
    for key, val in list(defaults.items()):
        defaults[key] = re.sub(r"\$\{?([A-Z_]+)\}?",
                               lambda m: defaults.get(m.group(1), m.group(0)), val)
    creates = {defaults.get(n, n) for n in printed_creates(script)}

    if not mounted:
        print("FAIL: parsed no ConfigMap mounts from job-evals.yaml. "
              "The regex is wrong, not the Job -- fix the check.")
        return 2

    missing = sorted(set(mounted.values()) - creates)
    extra = sorted(creates - set(mounted.values()))

    print(f"Job mounts {len(mounted)} ConfigMap volume(s):")
    for vol, cm in sorted(mounted.items()):
        mark = "ok " if cm in creates else "MISSING"
        print(f"  [{mark}] volume {vol} -> {cm}")
    print(f"script creates: {', '.join(sorted(creates))}")

    if missing:
        print(f"\nFAIL: the Job mounts ConfigMaps nothing creates: {', '.join(missing)}")
        print("A pod would start and hang on an unmountable volume.")
    if extra:
        print(f"\nWARN: the script creates ConfigMaps the Job never mounts: "
              f"{', '.join(extra)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
