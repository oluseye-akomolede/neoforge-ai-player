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
import os
import re
import subprocess
import sys
import tempfile
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


def ordered_ops(cmds, defaults=None):
    """(verb, resolved-name) for every kubectl create/apply/delete configmap.

    A delete and a create name their ConfigMaps differently in the script: the
    delete lists several in one command, a create names one. Everything is
    expanded through `defaults` so the two are comparable by name rather than
    by token position, which is what makes G1 (one-of-three deleted) visible.
    """
    defaults = defaults or {}

    def expand(name):
        m = re.fullmatch(r"\$\{?([A-Z_]+)\}?", name)
        return defaults.get(m.group(1), name) if m else name

    ops = []
    for cmd in cmds:
        m = re.search(
            r"kubectl\s+(create|apply|delete)\s+configmap\s+(.*?)(?:\s+-n\s|\s+--|$)",
            cmd,
        )
        if not m:
            continue
        verb, names = m.group(1), m.group(2)
        for tok in names.split():
            tok = tok.strip("'\"")
            if not tok or tok.startswith("-"):
                continue
            ops.append((verb, expand(tok)))
    return ops


def printed_creates(text):
    """ConfigMap names the script tells the operator to `kubectl create`.

    Uses the same actionable-command extractor as the guards: a `kubectl create`
    mentioned in a comment creates nothing.
    """
    names = []
    for cmd in actionable_commands(text):
        names.extend(re.findall(r"kubectl create configmap \$?([A-Za-z0-9_-]+)", cmd))
    return names


def name_defaults(script):
    """The literal each $NAME-like ConfigMap variable resolves to.

    Declarations are shell parameter expansion: NAME=${NAME:-evals-scout-cases}
    or a plain literal. Take the default arm; a literal is its own default.
    REBUILD_NAME's default is itself an expansion of NAME, so resolve twice.
    """
    raw = dict(re.findall(r'^(NAME|REBUILD_NAME|CODE_NAME)=(.*)$', script, re.M))
    defaults = {}
    for key, val in raw.items():
        val = val.strip().strip('"')
        m = re.fullmatch(r"\$\{%s:-(.*)\}" % key, val)
        defaults[key] = m.group(1) if m else val
    for key, val in list(defaults.items()):
        defaults[key] = re.sub(r"\$\{?([A-Z_]+)\}?",
                               lambda m: defaults.get(m.group(1), m.group(0)), val)
    return defaults


def main():
    job = (HERE / "job-evals.yaml").read_text()
    script = (HERE / "make-evals-configmap.sh").read_text()
    defaults = name_defaults(script)

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
    # Job args have gone missing twice (--rebuild-from-source, then
    # --decline-labels): the code path existed, was reviewed, and the Job never
    # passed the flag that reaches it. Nothing checked args at all, so neither
    # miss could fail a local check. Two directions, both required:
    #   - every flag the Job passes must be one run.py actually parses, so a
    #     typo'd flag fails here instead of silently in a pod;
    #   - the two flags the reported numbers depend on must be present.
    run_py = (HERE.parent / "agent" / "output_evals" / "run.py").read_text()
    job_args = re.findall(r"^\s+-\s+(--[A-Za-z0-9-]+)\s*$", job, re.M)
    if not job_args:
        print("FAIL: parsed no --flags out of job-evals.yaml args. The regex is "
              "wrong, not the Job -- a guard over an empty list passes anything.")
        return 2

    # Parse the argument SET, do not substring-search the file. A search over
    # the whole source is satisfied by a flag named in a comment, a docstring,
    # or a comment-out declaration left behind after a rename -- so a Job flag
    # that the pod would reject ('unrecognized arguments') passes here. That is
    # the same shape as the server-side guard that matched its own comment.
    #
    # And it has to be the EXECUTING source, not the file text. The first
    # version of this line regexed run_py directly and so matched a commented
    # line as readily as a live one: the reviewer commented out one
    # add_argument, left the call intact, and got rc=0 while the pod would
    # have rejected the flag. A rename mutant missed it because a rename also
    # removes the add_argument( token -- the mutant tested the rename and never
    # reached the comment. Strip comment lines first; match the live lines only.
    live = "\n".join(l for l in run_py.splitlines()
                     if not l.lstrip().startswith("#"))
    declared = set(re.findall(r'\badd_argument\(\s*"(--[A-Za-z0-9-]+)"', live))
    if not declared:
        print("FAIL: parsed no add_argument flags out of run.py. The regex is "
              "wrong, not run.py -- a guard over an empty set passes anything.")
        return 2

    unknown = [a for a in job_args if a not in declared]
    if unknown:
        print("FAIL: the Job passes flags run.py does not parse: "
              + ", ".join(sorted(set(unknown))))
        return 1

    # Each of these turns a silently-wrong number into a correct one, so a run
    # without them is not a cheaper run -- it is a different measurement.
    for required, why in (
        ("--rebuild-from-source",
         "without it every plan and replan case sends '' as its system prompt"),
        ("--decline-labels",
         "without it decline_cases is n=0 and a correct refusal looks like a fail"),
    ):
        if required not in job_args:
            print(f"FAIL: Job does not pass {required} -- {why}.")
            return 1
        if required not in run_py:
            print(f"FAIL: {required} is in the Job but run.py no longer parses it.")
            return 1
        if required not in declared:
            print(f"FAIL: Job passes {required} but run.py has no add_argument "
                  f"for it -- the pod would reject it.")
            return 1

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

    # `apply` merges and `create` lacks --ignore-not-found: keys absent from the
    # new manifest survive a merge, and a create over an existing map fails with
    # AlreadyExists. So every ConfigMap that is written to must first be deleted,
    # BY NAME, and the delete must come BEFORE the write.
    #
    # Checking that a delete merely EXISTS is not enough -- the reviewer showed a
    # delete of only $NAME passing while $REBUILD_NAME and $CODE_NAME kept their
    # stale keys (G1), and the delete moved after the creates passing while every
    # create would then fail AlreadyExists or delete what it just made (G2).
    # That is F7 one level down: verify the sequence, not the presence of verbs.
    ops = ordered_ops(kubectl, defaults)
    delete_names = {n for verb, n in ops if verb == "delete"}
    write_names = {n for verb, n in ops if verb in ("create", "apply")}

    undeleted = sorted(write_names - delete_names)
    if undeleted:
        print(f"FAIL: these ConfigMaps are created but never deleted: "
              f"{', '.join(undeleted)}")
        print("A create over an existing map fails AlreadyExists; an apply "
              "merges and leaves stale keys. Delete each by name first.")
        return 1

    first_write = next((i for i, (v, _) in enumerate(ops)
                        if v in ("create", "apply")), None)
    last_delete = max((i for i, (v, _) in enumerate(ops) if v == "delete"),
                      default=None)
    if first_write is not None and last_delete is not None and last_delete > first_write:
        print("FAIL: a `kubectl delete configmap` appears AFTER a create/apply.")
        print("Order must be delete-then-create: deleting after the create "
              "removes the map that was just made, and on a re-run the create "
              "fails AlreadyExists before it.")
        return 1

    mounted = job_mounts(job)
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

    # The decline labels are DATA, so unlike run.py and l3_planner NO *.py glob
    # stages them. If they do not reach code.tar, load_decline_labels() returns
    # {} by design and the report says decline_cases n=0 -- a silent zero where
    # the number should be, reading as "no declines happened" rather than "the
    # labels never shipped". Nothing else in this file can see that: the args
    # guard checks flags and the ConfigMap guards check names. So read the
    # staging rules themselves and require a copy that matches the label file.
    staged = re.findall(r"^cp\s+(.+?)\s+\"?\$OUT/code[^\n]*", script, re.M)
    if not staged:
        print("\nFAIL: found no `cp ... $OUT/code` staging lines. The regex is "
              "wrong, not the script -- a guard over an empty list passes "
              "everything, and this is the only check that can see a missing "
              "data file.")
        return 2
    # MODEL must not have a default. It had one (qwen3-coder:30b) and a run
    # that forgot to set it silently measured the wrong model -- the lead's
    # first rework leg did exactly that. The report is signed against this
    # yardstick, so a fallback model makes a missing input look like a sound
    # number.
    #
    # The SOURCE check runs FIRST, deliberately, and the behavioural probe runs
    # after it. Both diagnose the same script, and a mutant that breaks both
    # would otherwise only ever prove whichever ran first -- the earlier order
    # made every ordering mutant report "has a default", so the ordering check
    # was unprovable-by-mutant. Structure first, behaviour second.
    #
    # Anchor on the GUARD, not on the message text, and anchor on the FIRST
    # live one. Three wrong versions preceded this:
    #  - find("REFUSED: MODEL is unset") returned the first occurrence, so any
    #    earlier copy of the string satisfied it;
    #  - refuse_blocks[-1] took the LAST match, so a leftover guard sitting
    #    after a real early one got blamed and the ordering check fired on a
    #    script whose live check was in the right place;
    #  - neither filtered comments, so a commented-out guard counted as live.
    # Match the EXECUTING lines only (the same strip as the H1 arg guard above)
    # and take the first, which is the guard that actually runs. No live match
    # at all is rc=2: that is this check failing to parse, not the script
    # failing the rule, and a zero-width match on an empty list passes anything.
    live_script = "\n".join(l for l in script.splitlines()
                            if not l.lstrip().startswith("#"))
    refuse_blocks = [m.start() for m in
                     re.finditer(r'if \[ -z "\$\{?MODEL', live_script)]
    if not refuse_blocks:
        print("\nFAIL: no live `if [ -z \"$MODEL\" ]` guard in the script -- "
              "MODEL is unguarded again (or every guard is commented out).")
        return 2
    src_refuse = refuse_blocks[0]
    src_extract = live_script.find("python3 agent/output_evals/run.py")
    if src_extract < 0:
        print("\nFAIL: could not locate the extraction call in the script -- "
              "the ordering check cannot run. Fix the pattern, not the script.")
        return 2
    if src_refuse > src_extract:
        print("\nFAIL: the MODEL refusal sits AFTER the extraction call. "
              "Required inputs must be checked before the expensive step, or "
              "an operator waits minutes to be told an input was missing.")
        return 1

    # Now the behavioural probe: does the script actually refuse when run with
    # MODEL unset? A static pattern over the source is satisfiable by prose,
    # which is the trap this file has already been caught by. The stand-in
    # CORPUS is fine here because ordering is settled above; this probe is only
    # asking whether the refusal is produced at all.
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        corpus.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "MODEL"}
        env.update(CORPUS=str(corpus), OUT=str(Path(tmp) / "out"))
        # cwd must be the repo root: the script resolves agent/output_evals
        # relatively and documents that it is run from there. From evals/ it
        # fails on a missing path BEFORE any check, which reads as "refused for
        # another reason" and makes the probe test its own harness, not the
        # script. (This is the stale-harness failure again, caught once.)
        proc = subprocess.run(
            ["bash", str(HERE / "make-evals-configmap.sh")],
            capture_output=True, text=True, env=env, cwd=str(HERE.parent),
        )
        # Judge on the REFUSAL, not on rc. Extraction on a stand-in corpus
        # fails too (rc=3), so "non-zero" does not prove the MODEL check ran --
        # a script with a default and an empty corpus also exits non-zero, for
        # an unrelated reason. The only sound signal is the message itself.
        if "MODEL is unset" not in proc.stderr:
            print("\nFAIL: with MODEL unset the script did not refuse for that "
                  "reason -- it has a default model again, so a run that forgets "
                  "MODEL measures a model nobody chose. rc="
                  f"{proc.returncode}, stderr tail:")
            print("\n".join(proc.stderr.strip().splitlines()[-5:]) or "  <empty>")
            return 1

    label_src = "agent/output_evals/case_labels.json"
    if not any(label_src in line for line in staged):
        print(f"\nFAIL: {label_src} is never staged into $OUT/code, so it "
              f"cannot reach code.tar.")
        print("The after-leg would report decline_cases n=0 and read as 'there "
              "were no declines'. Add the cp line.")
        return 1

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
