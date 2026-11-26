#!/usr/bin/env python3
"""Check that each runner code-cite in the delta lands on the construct its
claim names, and that the delta has no cite outside those claims.

WHAT THIS CHECK IS (read this before quoting it at archive)
-----------------------------------------------------------
It is a manual aid. `git grep` finds no caller -- it is not wired into any
gate, CI, or archive step, and nothing runs it automatically.

The property it establishes is exactly this:

    1. Each of the claims hardcoded in CHECKS holds against the runner at the
       named rev: the cited lines match the pattern, and the pattern encodes
       the ACTION the claim asserts (not merely that the identifier appears).
    2. No cite in the delta sits outside CHECKS. Any cite not covered fails as
       "ungoverned" -- including one added anywhere in the text, not just at a
       known position.

What it does NOT establish, and an earlier version of this docstring wrongly
implied: it does not read the prose. The verb phrases are string literals in
CHECKS; the delta is read only to harvest cite tokens and to confirm each
CHECKS cite is still present in it. So the check binds CODE to CLAIM. It does
not bind CLAIM to PROSE. If a sentence's verb were reworded while its cite
stayed put, the check would still pass -- the sentence could become false with
the check green. Reviewer L-1 raised exactly that (their M3). Reading the
sentences is still required; this narrows what a human must re-read, it does
not replace it.

Presence is asserted, so a CHECKS entry whose cite has left the prose fails
rather than lingering as a stale row that always passes (their M5).

Why it exists
-------------
An earlier check in this change ("print the first cited line and read it")
passed all 14 stale cites, because it asked "does this line mention the
identifier the cite sits next to?" That is symbol presence. The defect is a
cite landing on a line about the right *thing* that does not do the right
*action*: 165 is `async #ensure(...) {`, a definition, while the claim said it
"reuses the worker" -- the reuse is the `this.#workers.get` on 166, and the
body settles it (`:182` discards a dead worker, `:207` spawns only when that
lookup missed). Naming the action in the pattern is what makes 165 fail.

Usage:  python3 check_cites.py <runner-repo> <rev>
Exit 0 = every claim holds and no cite is ungoverned. Exit 1 = otherwise.
"""
import re
import subprocess
import sys

DELTA = "openspec/changes/host-api-count-seven/specs/bot-coded-agents/spec.md"

# (cite, the CLAIM this pattern encodes -- written here, not read from the
#  delta, must-include regex on the landing line, attestation -- the evidence
#  read when the pattern alone is not decisive)
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

    failures, ungoverned, vanished, moved = [], [], [], []
    governed = set()
    for cite, verb, pattern, attest in CHECKS:
        fname, rng = cite.split(":")
        start, _, end = rng.partition("-")
        start, end = int(start), int(end or start)
        governed.add((fname, start, end))
        # L-1/M5: a claim whose cite has left the prose is a stale row that
        # would otherwise always pass. Fail it instead.
        if (fname, start, end) not in present:
            print(f"FAIL {cite:<18} {verb}")
            # Distinguish the two causes. The presence set is exact-tuple, so a
            # stale entry and a moved range look identical to it. Compare the
            # entry against the NEAREST cite in this file:
            #   PROSE moved  -- some adjacent cite is close to the entry, so
            #                   the sentence's range probably shifted.
            #   STALE entry  -- nothing in this file is near it; the entry
            #                   names a position the prose no longer mentions.
            near = sorted((p for p in present if p[0] == fname),
                          key=lambda p: min(abs(p[1] - end), abs(start - p[2])))
            close = near[0] if near and min(abs(near[0][1] - end),
                                            abs(start - near[0][2])) <= 8 else None
            if close:
                print(f"       PROSE moved: {fname} is cited but not at {start}-{end}.")
                print(f"       Nearest cite: {close[0]}:{close[1]}-{close[2]}"
                      " -- update the cite or this CHECKS entry.")
                moved.append(cite)
            else:
                print(f"       STALE entry: nothing near {cite} in {DELTA}.")
                vanished.append(cite)
            continue
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

    print(f"\n{len(CHECKS)} hardcoded claims checked against runner {rev}")
    if ungoverned:
        print(f"{len(ungoverned)} cite(s) present in the delta with NO claim:")
        for u in ungoverned:
            print(f"  {u}")
    if moved:
        print(f"{len(moved)} CHECKS entr(y/ies) whose cite RANGE moved in the delta:")
        for m in moved:
            print(f"  {m}")
    if vanished:
        print(f"{len(vanished)} CHECKS entr(y/ies) whose cite has left the delta:")
        for v in vanished:
            print(f"  {v}")
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    if ungoverned:
        print("\nFAILED: ungoverned cites are unverified, not passing")
        return 1
    if moved or vanished:
        print("\nFAILED: CHECKS entries do not match the delta's cites")
        return 1
    print("all clean -- NOTE: this binds code to these claims, not the prose to")
    print("them. The sentences still need reading. See the docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
