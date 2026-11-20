# Runner review — step 3 api binding, `5df8dcc..6a755d6`

Range: three commits (`32b592a`, `4c06661`, `6a755d6`), head `6a755d6`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on the binding; one open defect in the log rate limiter.**

Tree at `/home/sigmastrain/minecraft/agent-script-runner`, clean at `6a755d6`.

## The binding matches contract §4.1 exactly

Compared field by field against the §4.1 shape table at `b23b299`:

| §4.1 | binding.js |
|---|---|
| `do` → `{seq,call,directive,args}` | `:120-126` — identical; `args === undefined` becomes `null` |
| `say` → `{seq,call,text}` | `:134` — identical |
| `send` → `{seq,call,to,msg}` | `:143-148` — identical; `msg` undefined becomes `null` |

- **One entry per accepted call, in call order, none for a rejection** — the
  accumulator is appended only after `accept()` returns null, so a rejected call
  cannot leave a partial entry. Verified by reading the order, not the tests.
- **`seq` is what the script was returned** — `accept()` increments `seq` and
  `queueAction` returns `{ok:true, seq: entry.seq}`, so the value the script sees
  is the value stamped on the entry. Same integer, one source.
- **Rejections are return values, not throws** — every rejection path returns
  `{ok:false, reason, message}` with a reason from the §4.2 set
  (`bad_shape`, `host_calls_exceeded`, `memory_too_large`). No `throw` in the
  binding except the host-call cap's own return. A script can inspect and carry
  on.
- **`args`/`msg` verbatim** — no re-serialisation in the runner; the entry
  carries the script's value untouched, per §5.
- **`remember`/`log` are not actions** — no entry is produced; `remember` rides
  out as `memoryOut`, `log` as `logs`.

Two details worth recording because they are easy to get wrong and are right
here:

- `remember` measures `Buffer.byteLength(blob, "utf8")`, not `.length`. A
  multi-byte character would otherwise let a 16 KB budget carry 48 KB.
- `resetTickState` mutates the state object in place rather than returning a new
  one, because the installed `api` closes over that identity. Replacing it would
  detach the binding and every call from the second tick on would vanish
  silently. Same reason `createTickState`'s fields are reset, never replaced.

## No persistence between ticks — re-run, not read

`npm test` at `6a755d6`: **73 pass, 0 fail, rc 0** (captured from npm, not a
pipe). The no-persistence tests are genuine controls:

- `var` set in tick 1 reads `undefined` in tick 2, **and** the same variable
  reads `number` inside its own tick — so the assertion cannot pass merely
  because the declaration never took effect.
- `globalThis.sneaky` is also gone, so the check is not `var`-specific.
- The engine comment records the corrected mechanism (runtime disposal, not
  context disposal, was the abort), which is why the fresh-context path is now
  the one production takes.

## The defect: the 100-lines/minute cap is unreachable

`binding.js:195-209` implements a rolling per-minute log window over
`state.logTimes`, and `resetTickState` clears it every tick (`:79`, with
`logsDropped` cleared at `:75`). So the window is always empty when a tick
starts, and the cap can only fire *within* one tick — where the 8-call budget
already limits output to 8 lines.

Measured on the head:

```
60 ticks x 8 lines = 480 lines emitted, 0 dropped   (stated cap: 100/minute)
```

At the contract's 1 tick/second cadence a script emits **480 lines per minute
against a stated ceiling of 100**, and the runner reports `logsDropped: 0`
throughout. The cap is not "rarely hit"; it is structurally unreachable across
ticks.

The existing test does not catch this, and says why in its own comment:
`test/binding.test.mjs:101` asserts "the counter must persist on the sandbox,
not the tick state" — but nothing makes it persist. The test emits 24 lines
across 3 ticks and asserts `logsDropped === 0`, which passes because 24 < 100.
The comment states the property; the code does the opposite; the assertion is
satisfied either way.

**Suggested fix**, smallest first: keep `logTimes` and `logsDropped` on the
sandbox rather than in `resetTickState`'s cleared set, since §8 rates are
per-minute and cannot live in a per-tick object. Then the existing test becomes
a real control, and a 60-tick run should drop 380 of 480 lines.

Not blocking the binding: the `actions[]`, `seq`, rejection and verbatim rules
all hold, and a script can act. But §8's log ceiling is not in force, and the
run plan should not claim it is.

## Fresh-context cost, measured independently

The lead asked whether the builder's figures are the overhead or the total tick
time. **They are totals, and the overhead is a constant ~0.32 ms.**

My own harness (`/tmp/reviewer-bench-311d/bench.mjs`, not the builder's), full
`evaluate()` call timed end to end, `N=300` then `N=200` to confirm:

| script | reused median | fresh median | **difference** |
|---|---|---|---|
| 11 B (`return 2+2;`) | 0.055 ms | 0.373 ms | **+0.319 ms** |
| 17.9 KB (~450 stmts) | 3.603 ms | 3.923 ms | **+0.319 ms** |

Second run: +0.336 / +0.336. Fresh small-script p95: 0.59 ms.

**Threshold p95 < 5 ms: met**, with roughly 8x headroom.

The two deltas agreeing to three decimals is the finding: context creation is a
fixed cost per tick, independent of script size. The builder's "the larger
script is cheaper" is the signature of measuring total tick time at a size where
the fixed cost dominates — no real per-tick cost can fall as the source grows.

## Not in scope

`3.1` (snapshot into the script) is still being built. No image is verified in
this range: no digest, and no tick run against a digest. That remains owed
before anything is deployable.
