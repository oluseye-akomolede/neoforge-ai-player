# Review: 3bab810 — three spawn sites, bump at entry

Revs read via `git show <rev>:...` from `ship-ca27-harness`.

**Verdict: PASS.** The multi-site fix and the entry-point rule are both correct.
One concurrency note (C1) on the entry rule, for task 9.8.

---

## Their third site is real; mine was incomplete

Verified at `3bab810`, all three references to `_run_orchestrator`:

| site | caller |
|---|---|
| `:626` | tick loop, plan-layer branch |
| `:824` | tick loop, spec-driven `else` arm |
| `:4370` | `_order_worker`, overlay orders — **`runner._run_orchestrator`**, a different object |

I named two; `:4370` is a genuine gap in my finding, and it is the one that
would have been missed under my "increment at a common point" suggestion, since
it is a different object's method.

## Entry-at-`:1285` is right, and for the stated reason

Confirmed independently: `:1294` and `:1305` are early returns that precede the
body's first field use at `:1309`. Bumping "somewhere inside" could land after
either, so entry is the only correct position.

`_plan_instruction` counts reproduce exactly at this rev: 9 clears
(`:209`, `:304`, `:476`, `:542`, `:679`, `:912`, `:2989`, `:3052`, `:3087`),
sets at `:573`, `:623`, `:800`, `:821`, `:841`, `:1518`, `:1536`.

## C1 — the three callers are not in one thread, so `+=` at entry can alias

`:626` and `:824` run on the bot's tick loop. **`:4370` runs on `_order_worker`** —
a separate `while True: time.sleep(2)` daemon draining `/telemetry/orders`
(`def :4280`, started at `:4715`). An overlay order and a chat goal can therefore
call `_run_orchestrator` on the same runner *concurrently*, not only in sequence.

A monotonic `int` bumped at entry is a read-modify-write. Two threads can read
the same value and write the same increment, issuing two orchestrators the same
generation — the precise aliasing the generation was introduced to prevent,
arriving through the one caller that is not on the tick loop. The GIL makes this
pass most runs, which is what would make it surface in production rather than in
a test.

**A lock for this lane already exists**: module-level `_orchestration_lock`
(`:133`), taken at `:652` around the coordinator election and at `:311` in
`reset`. The order path at `:4370` does not take it.

Suggested: bump under `_orchestration_lock` at entry, so the generation and the
coordinator decision cannot disagree about who is current. Anything else is a
second lock over the same state.

This is implementer detail, not a requirement change — the same class as the
two-versus-three-sites point: cheap before the code exists, and afterwards it
reads as a flaky test rather than a missing lock.

## Not disputed

- `openspec validate --strict` valid at `3bab810`.
- The requirement text stays as written; no change asked for.
- No code exists; nothing applied or pushed.
