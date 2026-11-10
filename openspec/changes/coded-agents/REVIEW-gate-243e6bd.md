# Gate — coded-agents at 243e6bd (1b.1 / 1b.2)

Rows: qitem-20261110110743-2bae77970a14dafe, qitem-20261110110808-a1aa4288c63f76b9
(same rev, same review; the second handoff is a duplicate)
Reviewed: 243e6bd, read from the sha in `~/minecraft-wt-deepseek/neoforge-ai-player`
(confirmed: `git cat-file -t` = commit)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10T11:12Z

## Verdict: PASS — 1b.1 and 1b.2 may be ticked at 243e6bd

I re-ran the measurement myself rather than reading it, because a measured
number I cannot reproduce is prose.

### The stack measurement reproduces exactly

Installed `quickjs-emscripten@0.32.0` + `@jitl/quickjs-wasmfile-release-asyncify`
in a throwaway dir (`/tmp/qjs-verify`) on Node 22.23.3 and ran their
`probe-stack5.mjs` unmodified:

```
{"limit":"default","died":"Maximum call stack size exceeded","depth":2362}
{"limit":262144,   "died":"Maximum call stack size exceeded","depth":2362}
{"limit":524288,   "died":"Maximum call stack size exceeded","depth":2362}
{"limit":1048576,  "died":"Maximum call stack size exceeded","depth":2362}
{"limit":4194304,  "died":"Maximum call stack size exceeded","depth":2362}
```

2362 frames at every stack size, default through 4 MB. **`setMaxStackSize()`
does not move the depth** — the builder's claim is correct, and it is the
important one, because it means the proposal's "stack limit" was never a
settable control.

### On catchability I tested further, and the claim holds with a sharper mechanism

My first test wrapped `evalCode` in a host `try/catch` and the overflow unwound
into it as a normal `RangeError`; the process survived. That looked like a
contradiction, so I tested the case the spec actually names — a script catching
its own recursion:

```
function rec(n){rec(n+1)} try{rec(0)}catch(e){globalThis.out="IN-SCRIPT-CAUGHT"}
```

**Exit 1, uncaught, no stdout, process dead.** The in-script `catch` does not
contain it.

So the precise mechanism is: the overflow is *not* containable by a script, and
only the host sees it as a catchable error when nothing in script tries to
absorb it. The spec's sentence — "The failure is not catchable inside the
script" — is exactly right, and the design conclusion that follows is right for
the right reason: contain by process isolation, because the script cannot save
itself.

Worth adding one clause, since it's the natural next question an implementer
will ask: **the runner must not rely on catching the overflow at the host
either** — a supervisor that catches and continues has a process whose runtime
state is already unwound. Losing and replacing the worker is the only safe path,
which is what task 2.6 already says.

### The rate anchoring checks out

`TICK_DELAY = float(os.getenv("TICK_DELAY", "2.0"))` at `agent/config.py:89` —
confirmed by reading the file. At 2.0 s, 30 actions/min is one per tick, so
`api.do` = 30 is parity with the LLM path rather than headroom above it. That is
the correct basis: a script must not outpace the bot it replaces against a shared
4-thread pool. `api.send` = 20 (below tick rate) is justified on its own terms as
the burst-prone call. These are labelled "policy, not measurements" with the
reasoning a reviser must beat — that framing is honest and is the right way to
record a chosen number.

### `api.log` retention contradiction is resolved

My `e0e4a4e` finding is fixed: the row now reads "**unstated for v1**" with "an
implementer MUST NOT adopt cardgame's 7-day term by default", and `:122` matches
it. The two paragraphs no longer disagree.

### Validators

- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid"
- `openspec show coded-agents` → clean

### Housekeeping, not a finding

`git diff e0e4a4e..243e6bd` includes my two review files
(`REVIEW-gate-7698f81.md`, `REVIEW-head-e0e4a4e.md`) committed into the change
dir. Harmless, but the change directory is the deliverable and reviewer
artefacts in it will ship with the archive. Consider keeping them out of the
repo, or in a `reviews/` path that is clearly not spec content.

## Scope

Spec gate only. The probe ran in `/tmp/qjs-verify`, a throwaway dir, not in any
repo; no code in the change was built or run.
