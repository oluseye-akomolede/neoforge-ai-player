# Gate — coded-agents at cc68e1f (corrected stack finding)

Rows: qitem-20261110110808-a1aa4288c63f76b9 (builder, reassigned to cc68e1f),
qitem-20261110111143-3c90ee6afbbd2b35 (lead, "run the corrected stack probe yourself")
Reviewed: cc68e1f, read from the sha in `~/minecraft-wt-deepseek/neoforge-ai-player`
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10T11:15Z

## Verdict: PASS — the corrected finding holds. 1b may be ticked at cc68e1f.

My PASS at 243e6bd is withdrawn: it certified a claim that was wrong. The
builder's self-criticism of my method is exact — I re-ran their
`probe-stack5.mjs` unmodified, so I reproduced the bug faithfully rather than
the engine's behaviour. Re-running a suspect probe proves reproducibility, not
correctness. That is now the second time in this change that an instrument
fault produced a confident wrong answer, mine and theirs.

## What I ran, and why it is not their probe again

The lead asked me to run the corrected probe. Running *their* corrected probe
would repeat the same error one layer up. I wrote independent tests in
`/tmp/qjs-verify` (throwaway dir, Node 22.23.3, `quickjs-emscripten@0.32.0`,
release-asyncify) that assert the runtime/context relationship first and then
the curve.

**The bug is real and I reproduced the mechanism:**

```
orphan ctx.runtime === rt ?        false      # mod.newContext() carries its own runtime
rt.newContext().runtime === rt ?   true       # only this one shares the limit
```

So `setMaxStackSize` on a runtime never reaches a context from
`mod.newContext()`. Every value behaves identically, which is exactly what the
first probe reported.

**The corrected curve reproduces, tested by mine not theirs:**

| `setMaxStackSize` | result in my independent test |
|---|---|
| 64 KB | `{"caught":"InternalError","alive":2}` |
| 256 KB | `{"caught":"InternalError","alive":2}` |
| 512 KB | process killed (no stdout, non-zero exit) |

That matches their table: 64 KB → 338 frames and 256 KB → 1362 frames, both a
catchable `InternalError` with the runtime usable afterwards; 512 KB and above
dies at the ~2362-frame host ceiling.

**So the stack limit IS a first-line control, 256 KB is a defensible ship
value, and process isolation is correctly re-based as defence in depth** for
Wasm abort/OOM rather than as stack containment. The spec's two-regime framing
is the right model and both regimes are evidenced.

### Validators

`openspec validate coded-agents --strict` → valid. `openspec show` → clean.
`1.4` correctly unticked. Task 2.7 requires the test whose absence caused this
(every context created from the limited runtime), which is the right fix: it
converts a one-off discovery into a standing assertion.

## One correction to the 2.6 note — reasoning, not advice

`tasks.md:104-106` warns against a host-side `try/catch` because it "can catch
the error and continue in a runtime whose state is already unwound."

The advice is right; the reason is wrong. I tested it — at 256 KB, after the
host catches the overflow, the same context still evaluates:

```
simple eval after:      42
heavy loop after:       4999950000     # 100k iterations
recursion 500 after:    "bottom"
```

The runtime is **not** unwound and is genuinely usable. So the instruction to
lose and replace the worker should stand on a different justification:

- a caught overflow is survivable **only when it was caught below the host
  ceiling**, so the same `try/catch` gives no protection in the very regime
  process isolation exists for (≥512 KB / unset), where the process dies before
  any catch runs;
- a runner that treats a caught overflow as "script handled it, continue" will
  keep running a script that is provably able to reach the ceiling under other
  inputs.

Suggested replacement: *"Do not rely on a host-side `try/catch` to contain
stack overflow: it only works below the host ceiling, and contributes nothing in
the ≥512 KB/unset regime this task exists for. Lose and replace."* That keeps
2.6's conclusion and removes a claim a future reader could test and find false —
which is how this whole thread started.

## Scope

Spec gate, plus independent probes in `/tmp/qjs-verify`. Nothing in the change
was built or run; no repo was modified by the probes.
