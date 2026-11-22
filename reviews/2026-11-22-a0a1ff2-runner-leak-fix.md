# a0a1ff2: dispose the snapshot/look HostRefs — PASS, with one unclosed path

Rev reviewed: `a0a1ff2` (agent-script-runner) + spec `f6388cc` + proposal `a5bc17f`
(neoforge-ai-player). Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

## Verdict

PASS. The fix is correct, the regression test is discriminating, and the spec pins
the properties that made this bug survive. One adjacent hazard in the same method
is unguarded and I have measured it; it is filed below as F-1, not as a blocker,
because it needs a mid-sequence throw rather than an ordinary tick.

## Check 1: `look` survives disposal of its ref

Proven by running, not by reading. Drove `Sandbox.evaluate(src, {snapshot})` across
five consecutive ticks, each installing a fresh snapshot and each disposing its
`lookRef`; called `look` after every dispose:

| tick | look() answers | ageMs |
|---|---|---|
| 1–5 | correct blocks each time | advances per tick |

`ageMs` advancing is the load-bearing part: it shows `look` reads the CURRENT
tick's frozen snapshot, not a stale closure captured before the dispose. The
mechanism is that `setProp` COPIES the value onto the guest global, so the closure
lives in the copied value; disposing the ref frees the host table entry, not the
JS object.

Control: mutating `look`'s body reddens the same probe with
`cannot read property 'blocks' of undefined`. The five green ticks are a
measurement, not a detector that never fires.

## Check 2: the error path — F-1, and it is worse than the fixed leak

`#installSnapshot` has no `try`/`catch`/`finally` (verified: the only `try` in the
whole notifier path is in `#installApi` at :901 and :911).

`evalCode` failures are contained: `evaluate()` calls `#installSnapshot` inside its
own `try`, catches the throw, and returns `{ok:false}`. So a failed tick is silent,
and the refs allocated before the throw are never disposed.

Measured with the committed test's own instrument (`rt.computeMemoryUsage()`, 20-tick
warm-up, 60-bot + chat-backlog snapshot >= 100 KB):

| run | per failed install | note |
|---|---|---|
| throw after `snapshotRef` is installed | **480,495 B** | 5/20/60/65/66/70 all agree to within 0.02% |
| baseline, same fixture, no throw | **0.0 B/tick** | confirms the fix itself works |

480 KB per failed install is **9.4x** the 51,388 B/tick leak this commit fixes, and
at that rate a 32 MiB QuickJS heap is exhausted in ~66 failed installs. I observed
`RuntimeError: memory access out of bounds` in the wasm trap during the first
unbounded run.

Reachability, not just injectability: this file already documents the trigger.
`#installApi` got a `try/finally` on 2026-11-13 with the reason written down —
*"`setProp` itself can throw — on a context that has already been disposed, which
is reachable if a tick tears down between install and bind."* I confirmed that
trigger directly: `setProp` on a disposed context throws `Lifetime not alive`.

So the same defect has now been fixed twice in `#installApi` (refs in `f63a623`,
throw-safety on 11-13) and once in `#installSnapshot` (refs, this commit) — and the
throw-safety was never carried across.

**One honest limit on the fix shape:** on a disposed context `dispose()` ALSO throws
`Lifetime not alive`. A `try/finally` around each `setProp` is therefore necessary
but not sufficient for that specific trigger; the dispose needs its own guard. I
state this so F-1 is not closed with a `finally` that cannot run.

## Check 3: the regression test is red on the parent, green on the fix

The test does not exist on the parent — `a0a1ff2` adds it — so "red on parent" means
the NEW test file against the PARENT's `src/engine.js`. Built both trees at clean
revs:

- parent `src/engine.js` + new test: **`not ok` at tick 207, `memory_exceeded`**
- `a0a1ff2`: **`ok`**

The builder's tick-207 claim reproduces to the digit.

Mutant check (the part a green suite cannot give): reverted the fix by putting the
inline `getProp` back. The committed test reddens at tick 208 with
`memory_exceeded`. The test kills the defect it names.

## Check 4: the sweep — one site is unguarded, and it does not leak

Enumerated every `getProp` in `src/engine.js` and checked each against a dispose:

| line | site | disposed |
|---|---|---|
| 503 | `#installApi` name handle | yes, `finally` |
| 764 | snapshot-null branch, inline `getProp(handle,"look")` | **no** |
| 809/811 | the two refs this commit fixes | yes |
| 978 | `res.error` message | no — read-only path, no `setProp` |

Line 764 has the same shape as the defect fixed here: `getProp` fed inline into
`setProp`, only `handle` disposed. I measured it rather than filing it on shape:

- 4,000 evaluations, warm-up, isolated to that branch: 125 B/iter — noise
- 5,000 firings: 51 B/iter — flat
- 20,000 firings: 13.5 B/iter — flat
- 50,000 firings: 5.8 B/iter — flat

Not a leak in any run. The branch fires once per disappearing snapshot (not per
tick), and I could not make it accumulate. I therefore do NOT file it as a leak.
What it IS is the same shape surviving a sweep whose spec now says the rule applies
to every such site — a reader in six months will find it and reasonably ask why it
was exempted. Worth a comment saying the ref is consumed, not worth a fix on
current evidence.

## Check 5: spec and proposal

`f6388cc` adds one requirement and three scenarios. Two are not boilerplate:
scenario 2 requires the bounding test to FAIL on a leaking runner, and scenario 3
records that a snapshot-free tick never enters the branch. That is the property
that let this survive — the pre-existing heap test ticks with no snapshot at all.

The numbers the spec pins match what I measured: >=100 KB fixture, dies at 207,
leak on the order of tens of KB/tick. The requirement also generalises to "every
`getProp`-into-`setProp` site", which is what makes line 764 a question rather
than nothing.

`a5bc17f` is proposal-only — no code, no delta. It is disciplined: it explicitly
does not revisit the ephemeral-script decision, and its "must NOT" list covers
becoming a binding source, surviving restart executably, holding secrets, and
adding per-tick cost. Nothing to verify; nothing overreaches.

## Note on my own instruments

Four failed probes before the numbers above, all recorded because each one
produced output that looked like a finding:

1. `process.memoryUsage()` probes showed flat growth for a reverting-the-fix
   mutant — a DEAD INSTRUMENT. The leak is in the QuickJS wasm heap, which
   `heapUsed` cannot see. The committed test works because it reads
   `rt.computeMemoryUsage()`. Every "no leak" reading I took with the wrong
   instrument is worthless, including my first pass at line 764 — the line-764
   result above was re-measured with the right one.
2. A 552 B/tick near-constant growth on the FIXED rev looked like an unremitting
   leak. It is normal per-tick eval overhead: two orders of magnitude below the
   defect, and under the test's 5,000 B threshold. I nearly filed it.
3. `--test-name-pattern` with invented names matched NOTHING twice, and the
   resulting `ok 1 - test/engine.test.mjs / pass 1` reads exactly like a passing
   suite. It is the file-level wrapper passing with zero tests inside.
4. Probes crashed three times on a module path I invented (`src/runtime.js`) and
   an import resolved from `/tmp` rather than the repo. `tail` hid all three.

The generalisable rule, which the builder and I both hit repeatedly today: scope a
check by what reaches the changed thing, not by what it is called and not by what
was edited.

## Not established

- I did not run the mutant against the full test suite, only the two files that
  cover this method. A mutant reddening the right test is not the same as the suite
  being otherwise undisturbed.
- The line-764 branch's firing rate in prod is inferred from the code (once per
  vanishing snapshot), not measured on the cluster.
- F-1's prod reachability depends on a context being disposed between install and
  bind. I proved the throw exists and the path has no guard; I did not observe it
  occurring in production.
