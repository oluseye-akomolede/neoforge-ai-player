# 47c959a: my review is withdrawn - the builder's architecture finding is correct

**Status: my REVIEW-47c959a.md (4e2ef22) is superseded in its central premise.**
The builder found, after reading the code, that the throwaway-botState
mechanism the commit claims does not exist on the production path. I verified
the claim independently at 2733485 and it holds. The defect is bigger than the
two I filed.

## What I verified, at source, not on report

1. **ScriptTick runs no JS in-process.** `script_tick.py` builds a request body
   (`:318-326`) and POSTs it (`:331-333`). The body carries
   `contract_version, game_id, bot_id, script_revision, source, snapshot,
   memory`. There is **no** `bot_state` and no mode field. The agent cannot
   reach the engine's botState, let alone pass a replacement.

2. **The engine owns the long-lived botState.** `engine.js:238`
   `this.#botState = createBotState()`, passed to `createApi` at `:754-756` on
   every tick. One instance per engine.

3. **That engine is cached per bot.** `fleet.js` `#ensure(botId, ...)` does
   `this.#workers.get(botId)`; a worker and its engine outlive a request.
   `main.js:221` `fleet.tick(sandboxKey(gameId, botId), ...)` and
   `handleTick` reads `bot_id` straight off the body (`:168`).

4. **Same key, same window.** The dry tick POSTs with the same `bot_id` a real
   tick uses, so it resolves to the same sandbox and the same `#botState`. Not
   inferred from the shape of the code - `handleTick` is four lines long and
   passes `botId` through untouched.

5. **No dry-run mode exists.** `grep -ci dry` over `src/server.js`,
   `src/worker.js`, `src/engine.js`, `src/fleet.js` at 2733485 returns **0** for
   every file.

So the commit's central claim - "the dry tick evaluates against a THROWAWAY
botState... the live window is neither read nor written" - is false in
production. The `createApi` citation is real and irrelevant, exactly as the
builder now says: it proves the *engine* can accept a botState, not that the
*agent* can supply one across an HTTP boundary.

## How my review got this wrong, because it matters

My REVIEW-47c959a.md checked the mechanism against `binding.js` and against the
**stub** `_dry_tick` swaps in. Both look right. Neither is the production
transport. `_dry_tick`'s tests inject `_dry_script_factory` and never POST, so
the suite cannot see the boundary at all - and I read the passing suite as
evidence about the mechanism rather than as evidence about the stub.

That is the vacuity failure I warned the builder about twice, applied to my own
review. The correct instrument was `git show 2733485:src/main.js` on the
request path; I never opened it. The builder did.

## What survives from my review

- **F2 stands and is unaffected** - the memory test asserts on
  `self.a._script_memory`, which exists only in a comment at `agent.py:3041`.
  That is an inert test regardless of the transport question. It stays filed.
- **F1 needs re-specifying, not withdrawing.** `handled` still is not "ok"
  (`script_tick.py:340` vs `:390`), and a `say`-only script still fails the
  gate. But if the dry tick is redesigned or dropped, this changes with it, so
  it should be re-filed against whatever replaces 47c959a rather than fixed in
  place.
- M2/M3 genuinely bite; the rate test's `len(calls)==1` is real. Those were
  true statements about the stub harness, which is now known not to be the
  production path.

## On the three options

The builder says this is not theirs to pick and they are right. I am not
picking either - it is the lead's call and it changes what the lead accepted at
04:06Z. My read, offered as input not decision:

- **(a) is the only option that delivers the approved requirement.** The
  requirement is not "a dry tick that mostly does not spend"; it is "the dry
  tick MUST spend no rate budget". Only the engine can honour that, and only if
  the request grows an explicit mode the engine acts on. It is a second repo,
  its own tests and its own deploy - a real scope expansion, correctly not
  started unilaterally.
- **(b) is honest but defeats the requirement's purpose.** The builder already
  named why: a rejected script would rate-limit the accepted one, which is the
  precise failure the requirement exists to prevent. If the lead takes (b), the
  requirement text must change, not just the implementation.
- **(c) is the only option that ships today** and does not need another repo.

A fourth framing worth putting to the lead, since it changes the trade: the
budget cost of (b) is bounded by `accept()` at **8 host calls per tick** and
happens **once per authored script**, not once per tick. "Up to 8 of 30 do
slots, once, per script the planner attempts" is a much smaller incursion than
it sounds - though it still lets a bad script eat a quarter of the minute.
That number is worth having in front of the lead when they choose, because it
may make (b) acceptable where it otherwise would not be.

## Nothing applied, nothing pushed

Read-only throughout. The builder has pushed nothing and deployed nothing.
