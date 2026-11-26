#!/usr/bin/env python3
"""Check that every runner code-cite in the delta lands on what its SENTENCE says.

Why this exists
---------------
A previous check in this change ("print the first cited line and read it")
passed all 14 stale cites, because it asked "does this line mention the
identifier the cite sits next to?" That is symbol presence. The defect is a
cite landing on a line that is about the right *thing* but does not do the
right *action*: 165 is `async #ensure(...) {`, a definition, while the sentence
claimed it "reuses the worker" -- the reuse is the `this.#workers.get` on 166,
and the body settles it (`:182` discards a dead worker, `:207` spawns only when
that lookup missed).

So each cite is paired with the VERB PHRASE of its own clause, and checked by
the line it lands on satisfying that phrase -- an explicit pattern, or a human
attestation with the evidence that was read. A cite with neither fails.

Usage:  python3 check_cites.py <runner-repo> <rev>
Exit 0 = every cite satisfied. Exit 1 = at least one failed.
"""
import re
import subprocess
import sys

DELTA = "openspec/changes/host-api-count-seven/specs/bot-coded-agents/spec.md"

# (cite, verb phrase from the sentence, must-include regex on the landing line,
#  attestation -- the evidence read when the pattern alone is not decisive)
CHECKS = [
    ("binding.js:342-346", "api.do pushes onto a sandbox-local array",
     r"state\.actions\.push", "push inside the do() body"),
    ("binding.js:214-216", "acceptAction records the call in actionTimes",
     r"function acceptAction", "def; :216 is botState.actionTimes[kind]"),
    ("binding.js:111-118", "createBotState is the object both windows live on",
     r"export function createBotState", "def; body declares logTimes and actionTimes"),
    ("binding.js:96", "MAX_ACTIONS_PER_MIN is the budgets",
     r"MAX_ACTIONS_PER_MIN.*do: 30.*say: 30.*send: 20", "the literal budgets"),
    ("binding.js:459-466", "api.log spends logTimes",
     r"botState\.logTimes", "the window read, inside log()"),
    ("binding.js:192-195", "createApi takes botState as a parameter",
     r"botState = createBotState\(\)", "the default parameter"),
    ("binding.js:436", "remember writes state.memoryOut",
     r"state\.memoryOut = blob", "the assignment"),
    ("binding.js:327-496", "the createApi object literal / api surface",
     r"return \{", "opens the returned api object"),
    ("engine.js:851-853", "the engine passes its long-lived state to createApi",
     r"botState: this\.#botState", "the argument"),
    ("engine.js:254", "the engine creates the long-lived botState",
     r"this\.#botState = botState \?\? createBotState\(\)", "the assignment"),
    ("engine.js:737-850", "#installSnapshot is the snapshot global",
     r"#installSnapshot\(snapshot\)", "the method def"),
    ("engine.js:2-12", "no filesystem and no network",
     r"No filesystem and no network", "the module-header claim"),
    # The cite this check was built for. A definition does not reuse; the
    # lookup line does.
    ("fleet.js:166", "the #ensure lookup reuses the worker across requests",
     r"let worker = this\.#workers\.get\(botId\)",
     "the cache lookup; :182 discards dead, :207 spawns only on a miss"),
]


def line_at(repo, rev, fname, start, end=None):
    end = end or start
    src = subprocess.run(["git", "-C", repo, "show", f"{rev}:src/{fname}"],
                         capture_output=True, text=True)
    if src.returncode != 0:
        return None
    lines = src.stdout.split("\n")
    return "\n".join(lines[start - 1:end])


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    repo, rev = sys.argv[1], sys.argv[2]

    text = open(DELTA).read()
    present = {(m.group(1) + ".js", int(m.group(2)), int(m.group(3) or m.group(2)))
               for m in re.finditer(r"(binding|engine|fleet)\.js:(\d+)(?:-(\d+))?", text)}

    failures, ungoverned = [], []
    governed = set()
    for cite, verb, pattern, attest in CHECKS:
        fname, rng = cite.split(":")
        start, _, end = rng.partition("-")
        start, end = int(start), int(end or start)
        governed.add((fname, start, end))
        body = line_at(repo, rev, fname, start, end)
        if body is None:
            failures.append((cite, verb, "FILE UNREADABLE at rev"))
            continue
        ok = re.search(pattern, body, re.M) is not None
        print(f"{'ok  ' if ok else 'FAIL'} {cite:<18} {verb}")
        print(f"       {body.splitlines()[0].strip()[:72]}")
        if not ok:
            failures.append((cite, verb, f"pattern {pattern!r} not in cited lines"))
        elif attest:
            print(f"       attested: {attest}")

    # A cite in the delta that no verb check covers is unverified, not fine.
    for fname, start, end in sorted(present - governed):
        ungoverned.append(f"{fname}:{start}" + (f"-{end}" if end != start else ""))

    print(f"\n{len(CHECKS)} cites checked against the verb of their own sentence")
    if ungoverned:
        print(f"{len(ungoverned)} cite(s) present in the delta with NO verb check:")
        for u in ungoverned:
            print(f"  {u}")
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    if ungoverned:
        print("\nFAILED: ungoverned cites are unverified, not passing")
        return 1
    print("all clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
