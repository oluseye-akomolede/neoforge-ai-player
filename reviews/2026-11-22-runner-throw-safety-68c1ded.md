# Runner throw-safety (68c1ded + b2b90ef/963d263, specs 907109a/69655b2) — PASS, with one retracted premise and one unreproduced figure

Rev reviewed: `68c1ded`, `b2b90ef`, `963d263` (agent-script-runner); specs `907109a`,
`69655b2` (neoforge-ai-player, `openspec/changes/ai-written-scripts/specs/bot-coded-agents/spec.md`).
Row: qitem-20261122143741-1c28616bac13f4d4. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

## Verdict

PASS. The code change is right, it kills the strand on the path it targets, it
introduces no double-dispose, and it regresses nothing (56/56 at `963d263`). The
spec delta states the mechanism accurately, including the measured retraction of
the "the context already reclaimed it" rationale; I reproduced every one of its
lifetime claims against the real runtime.

Two things the row asked me to check and that do not hold as stated. Neither is a
code defect, both are prose that will get quoted:

- **R-1.** The root cause cited for the guard — "the parent masked the original
  error as `wasm_trap` 'context is gone', which also flips the recycle decision" —
  is **not borne out**. The kind is identical before and after the fix.
- **R-2.** The figure "~480 KB per failed install" appears in the spec (`:1333`)
  and in `68c1ded`'s comment (`:822`) and I **could not reproduce it**. *My own
  replacement figures in the first edition of this review — "~209.5 KB at the
  40-bot shape, ~68 KB at one bot" — were also wrong; see the R-2 correction
  below. The correct measurement is a flat ~33.5 KB per torn-down install,
  independent of payload.*

## Check 1: `safeDispose` swallows cleanup errors and never masks the install error

**Confirmed.** On a torn-down context, `safeDispose` catches and the caller still
sees the original error. Measured with the real runtime (`probe-ref.mjs`):

```
dispose() on a context-disposed handle:
  objHandle : QuickJSUseAfterFree: Lifetime not alive
  innerHandle: QuickJSUseAfterFree: Lifetime not alive
  big       : QuickJSUseAfterFree: Lifetime not alive
```

so a bare `dispose()` in a `finally` would replace the install error. The guard is
necessary and does its job.

**The recycle-kind premise is retracted.** The row asked me to "verify the recycle
kind on the fixed path", because the builder said the parent masked the original
error and that this also flipped `mustRecycle`. Driven through the real
`evaluate()` with an injected context whose `setProp` throws on `snapshot`,
**both** revs report the same thing:

| rev | ok | kind | message | trap |
|---|---|---|---|---|
| `a0a1ff2` (pre-fix) | false | `wasm_trap` | `Lifetime not alive` | true |
| `963d263` (fixed) | false | `wasm_trap` | `Lifetime not alive` | true |

`SCRIPT_RAISED` does not contain `wasm_trap`, so `mustRecycle` is true on both.
Nothing was masked — the message the caller sees is the original one on the old
code too — and the decision does not change. The guard's real value is narrower
than cited: it keeps a *second* cleanup throw from replacing the install error,
which the 3.3 fixture does exercise (its `dispose()` throws on purpose). The code
is right; the justification overstates what it changes.

## Check 2: no double-dispose on any path

**Confirmed.** `#installApi`'s loop `finally` owns each loop handle; the outer
`finally` owns only `obj`; nothing else disposes `obj`. Test 3.4
(`a successful #installApi disposes every handle exactly once`) is discriminating:
mutating `#installApi` so the same handle is disposed twice reddens exactly that
test (`not ok 56 - 3.4 …`, pass 55/fail 1).

I also ran the **missing**-dispose counterpart in `#installApi`'s outer `finally`
(`if (false) safeDispose(obj);`, replacing the call, confirmed by
`grep -c MUTANT` = 1 and `node --check`): it is killed — whole suite 207/212 with
5 failures, test 3.3 failing at `:1568` with
`disposed: ["fn-do"]`, and `api-obj` absent. So the "exactly once" and "at least
once" halves are each pinned.

*Correction to my own earlier note in this row:* a first attempt at this mutant
left all 56 green. That was my instrument, not the test — I inserted a dead
`if (false) safeDispose(obj);` **above** the live call rather than replacing it, so
the code was unchanged. Replayed verbatim, it prints `ok 1 … 3.3` and `# fail 0`;
replaced properly, it fails as above.

## Check 3: the tests are red on the revs that lack each fix

Run from committed bytes, `--rerun`-style on extracted trees, reading each
runner's own summary line:

| test | against | result |
|---|---|---|
| 3.2 a FAILED snapshot install strands no refs (F-1) | `a0a1ff2` engine | `not ok 1`, rc=1 |
| 3.2 | `68c1ded` engine | green |
| 3.3 a dispose that throws does not mask the install error | `68c1ded` engine | `not ok 1`, rc=1 |
| 3.3 | `b2b90ef` engine | green |

Suite size grows 53 → 54 → 55 → 56 across `a0a1ff2` → `68c1ded` → `b2b90ef` →
`963d263`. Each test is red on the rev that lacks its fix and green on the rev
that has it.

## Check 4: the strand comment matches measurement

**Confirmed, in both directions.** The spec's retraction ("a handle whose context
is disposed is NOT reclaimed — `dispose()` throws, it stays in the runtime-wide
table, `rt.dispose()` later aborts with `list_empty(&rt->gc_obj_list)`") is
exactly what happens (`probe-ref.mjs`): each `dispose()` threw, the runtime heap
**grew** by ~33.5 KB per handle after the disposes, and `rt.dispose()` aborted with
`Aborted(Assertion failed: list_empty(&rt->gc_obj_list) …, JS_FreeRuntime)`.

I also checked that `safeDispose` does not change that. Stranding the same state
with and without the guarded disposes retains the **same bytes to the byte**
(209,440 / 209,765 / 209,697 / 209,440 per attempt either way). The comment is
honest that the guard is not a reclaim, and the code behaves that way.

## R-2: the ~480 KB figure (reported, not blocking)

The spec and the commit comment both say "measured ~480 KB per failed install,
enough to exhaust a 32 MiB runtime in ~66 of them". I measured the strand directly
(`probe-strand*.mjs`: build what `#installSnapshot` builds, dispose the context,
let the bind strand the refs, sum the runtime heap):

| payload | retention per torn-down install |
|---|---|
| one-bot snapshot | ~68 KB |
| 40 bots × 36-item inventories + 200 chat lines (the spec's own shape) | ~209.5 KB |

QuickJS retains the bound payload inside the stranded handle, so the cost tracks
size; at the spec's own payload shape it is ~2.3× smaller than quoted. This does
not weaken the requirement — the leak exists, is per-install, is unreclaimed, and
is real on the mechanism path — but the sentence carrying the number, and the
"~66 of them" derivation, are not reproducible with the instrument I can run.
Since reviewer numbers become test expectations, I am filing it rather than
silently letting it be quoted.

### R-2 correction (same review, 2026-11-22 ~15:0xZ): both of my figures were wrong

The builder took my table and wrote it into the spec (`f57bdeb`) and the code
comments ("~209.5 KB at a 40-bot / 200-message shape, ~68 KB at one bot,
payload-proportional"). Before that hardened further I re-derived it rather than
let my own number be quoted, and **my table does not survive re-measurement**:

- My probes above were **not on disk any more** (the `/tmp` trees were cleared),
  so I rebuilt the measurement from the real code path: a real `Sandbox`, a real
  `#installSnapshot`, `disposeContext()` between install and bind, a real
  `createLimitedRuntime()` and `rt.computeMemoryUsage()` (`probe-bind.mjs`).
- **A torn-down install retains 33,496 bytes — identical for a 1-bot snapshot and
  a 60-bot / 200-chat snapshot.** The cost is **flat, not payload-proportional**.
  The ~33.5 KB is the one stranded `HostRef`; it agrees with the "grew by ~33.5 KB
  per handle" figure already in Check 1 above.
- Stranding 1, 2 and 3 handles in isolation measured 67,282 / 67,456 / 67,264 B —
  flat in handle count too, i.e. a one-time ~67 KB object-shape cost, not a
  per-handle rate.

So the correct statement is: **a failed snapshot install strands one ref, costing
a one-time ~33.5 KB, independent of payload size.** The payload does not ride
along because the strand is the ref, not a copy of the JSON.

This does not change the verdict: the guard still prevents a cleanup throw from
replacing the install error, and the strand is still permanent. But the
"payload-proportional, ~209.5 KB" sentence the builder committed is **my error,
propagated into the spec and two comments**, and should be replaced with the flat
figure or with no figure at all. Filed to the builder as R-3.

## Check 5: accept the structural change

**Accepted.** One outer `try/finally` owning `obj`, one inner `try/finally` owning
each loop handle, and the same shape on the snapshot-disappeared branch. The
ownership is single and evidenced by 3.3 + 3.4 in opposite directions. The
retraction comments are long but they carry measurements, not narrative.

## What I did not verify

No live bot, no deployment: everything here is the extracted source trees at the
named revs plus the real QuickJS runtime in `node_modules`. The mid-install
tear-down is defensive: `disposeContext()` is called only *after* a dry tick
returns (`src/worker.js:82`), and `evaluate()` disposes the previous context
before creating the new one (`src/engine.js:409`), so reproducing the strand
needed an injected throw; the tests do the same thing deliberately.

Scratch: `/tmp/rsr-a0a1ff2`, `/tmp/rsr-963d263` (+ `probe-*.mjs` there);
both extracted trees left with `src/` clean.
