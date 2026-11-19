# Review: dc45196 — M3-1, gate Scout's STORE_ALL on inventory and cooldown

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Rev under review: dc45196039509953c152a3ec5fb064adab080dba (task tick e44a860)
Row: qitem-20261119102953-ba671057fc5eefe3

## Verdict

**PASS**, with one spec-accuracy finding and two notes. No code defect found.
Nothing applied, nothing pushed.

## Re-run, not read

Clean `git archive dc45196`; runner copied to a scratch dir (the driver writes
into the runner root, so pointing at the real worktree would mutate it).

- **18/18 OK**, rc from the runner's own summary, in 15.1s.
- **M1 bare-array read** (`state.inventory` instead of `.inventory`): **11 red**.
- **M2 no inventory guard**: **2 red**.
- **M3 no cooldown**: **1 red**, and it is exactly `test_cooldown_holds_a_repeat_store`.
- Restored and re-confirmed 18/18 after the mutants.
- `openspec validate coded-agents --strict` rc=0, "is valid", printed with the
  tree's rev (`e44a860`).

All three counts match the builder's claim exactly.

## The two shape facts — both true

1. **Wrapper.** `HttpApiServer.java:469` is literally
   `Map.of("inventory", bot.getCachedInventory())` — verified at that line.
   `snapshot.py:71` stores the returned body verbatim as `state["inventory"]`,
   so the list is `state.inventory.inventory`. A `.length` guard on the wrapper
   is `undefined`, compares false, never fires. Confirmed by execution: the
   wrapper fixture proposes `STORE_ALL`, and M1 reddens 11 tests.
2. **One string blob.** `binding.js:293` `recall() { return state.memoryIn; }`
   and `:312` `remember(blob)` with a `typeof blob !== "string"` rejection;
   `engine.js:405` sets `memoryIn` from the tick's input. So a tick-number stamp
   is correct and a same-tick decrement would be invisible. Verified in the
   runner source, not taken from the message.

## Finding (non-blocking): the spec forbids a shape the system produces

Spec delta line ~778 says `state.inventory` "is **not** a bare array, and it is
not absent when the bot carries nothing — it is present with an empty list."

That is absolute, and it is false in one real case. `snapshot.py:48-62`
(`_read`) substitutes the default on a failed read, and `:71` passes `[]` as
that default. So when the inventory read raises, `state.inventory` is a **bare
array** — the exact shape the spec says it is not.

The **code is safe** here, and I checked rather than reasoned: feeding a
snapshot with `state.inventory = []` yields no actions and logs
`scout: inventory empty, not storing`. `(state.inventory && state.inventory.inventory) || []`
degrades to `[]` and the guard holds. The bot does not store on a degraded
snapshot, which is the right direction — it under-acts, never over-acts.

So this is spec accuracy, not a defect. Suggested wording: the wrapper is the
shape on a **successful** read, and a failed read degrades to a bare `[]` which
the guard treats as empty. Worth fixing because the spec explicitly says
"Fixtures MUST be copied from the real response shape", and a future fixture
built against the absolute sentence would not cover the degraded case.

## Note 1: the cooldown value is a product decision recorded nowhere

Spec says "a cooldown of at least one tick". Code uses
`STORE_ALL_COOLDOWN_TICKS = 100` (~5 minutes at 20 tps). 100 satisfies the
floor, so this is not a spec violation — but 100 is a choice with a user-visible
effect (how often a full bot retries a failing store) and neither the spec delta
nor task 9.1 names it. Someone will later read "at least one tick" and assume 1.
Suggest pinning the number, or the intent behind it, in the spec.

## Note 2: guard ordering changes what a mid-store bot logs

The inventory guard sits **before** the task check (`snapshot.task`), where the
old unconditional store came after it. A bot mid-store that has already
deposited its items now returns at the inventory guard and logs
`inventory empty, not storing`, instead of falling through the busy-task check
and returning silently. Behaviour (no action) is unchanged; only the log line
differs. Flagging because log lines are evidence in the C1/C4 arms, and a
reviewer reading "inventory empty" mid-store could misread it as the guard
misfiring.

## Other checks

- Diff: 4 files, +255/-11. Spec delta, code, tests, tasks. No image or manifest change.
- The six pre-existing tests that gained inventory pin channels/form, not
  inventory semantics, so leaving them on an empty inventory would assert a
  silence unrelated to what they test. Adding `CARRYING` is right. The
  returned-array negative test correctly stays inventory-free.
- Task 9.1 left unticked: correct for unshipped work.
- No apply, no push, no secrets, no script or bindings contents printed.

## Provenance

- `git archive dc45196` into a fresh dir; runner copied to scratch.
- Suite and all three mutants run by me, counts taken from the runner's summary.
- Java/Python citations read at the cited lines.
