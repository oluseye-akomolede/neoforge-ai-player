# Review: agent-script-runner 0e845e5 - dry-tick mode (option (a))

**Verdict: NOT YET.** The production code is correct on every point I attacked.
One test cannot fail, and it is the test for the headline guarantee.

Read from `git archive 0e845e5` into a fresh dir, per-repo, never the builder's
worktree. Suite re-run by me: **141/141, rc=0** - matches their number.
Agent side (`_dry_tick` at 6e83762) not re-reviewed here; unchanged by this rev.

## Attack 1 - default-off. CORRECT

main.js:224 is `const isDry = body.dry === true;` - strict identity, so absent,
null and the string `"true"` all fall through to the live path. Their four cases
are the right four. cardgame is unaffected unless it sends a literal boolean
`true`, which it cannot have been sending before the flag existed.

## Attack 2 - throwaway botState. CORRECT, and the reasoning is the load-bearing part

They claim the api only mutates NESTED arrays and never reassigns the field, so a
different object with its own arrays suffices. Printed every mutation site in
binding.js rather than taking the claim:

  :159-172  `const times = state.actionTimes[kind]` -> in-place filter
            (`times[keep++] = t`, `times.length = keep`) -> else `times.push(at)`
  :341-346  `const times = botState.logTimes` -> `times.push(at)`, same shape

No assignment to `botState.actionTimes` or `botState.logTimes` anywhere in the
file. The only `=` near the field is the destructuring default at :134. So handing
`createBotState()` to a fresh Sandbox genuinely isolates both windows. The claim
holds - and it holds for the reason they gave, not by luck.

## Attack 3 - warmUp / finish() / runtime disposal. CORRECT

- **dry-first**: verified by driving a brand-new worker whose first-ever request
  is a dry tick - `ok, actions: 1, host_calls: 1`. The `box.warmUp()` call is what
  makes this true; without it the tick reports ok with zero actions, which is a
  gate that answers "this can run" without running it - worse than no gate.
- **finish()**: they snapshot `box.tickState` before `disposeContext()`. Correct
  order; the live path would otherwise read the module-level sandbox's state,
  which the dry tick never touched.
- **runtime**: the dry Sandbox borrows `live.runtime` and disposes only its own
  context in `finally`. The 30 s hang they describe is real and this avoids it.

## The finding: the headline test cannot fail

`test/dry.test.mjs` test 1, "a dry tick does not spend the bot's rate budget",
names its kill exactly - *"KILLS: a dry tick that reuses the worker's live
sandbox"* - and then never measures it. Its assertions are `status === "ok"`
three times plus `cpu_ms >= 0`. It defines `doSlots()` above and does not call it.

I built the mutant that test describes. Replaced the whole throwaway block in
worker.js (`createBotState()`, the second `Sandbox`, `warmUp()`, `disposeContext()`)
with an evaluate on the live sandbox, so a dry tick shares the live worker's
state entirely. **All 4 dry tests pass.** The mutant that defeats the entire
guarantee is green.

The gap is structural, not a near-miss: test 2 does assert on `doSlots`, but it
constructs `Sandbox` objects directly and never enters `dryEvaluate` - it tests
the engine's `botState` parameter, not the worker's dry wiring. Nothing exercises
`handleTick({dry:true})` against the rate budget.

Discriminator, measured on a window pre-exhausted by 31 live ticks:

    real code        live tick #31: ok, 0 actions    dry: ok, 1 action
    sharing mutant   live tick #31: ok, 0 actions    dry: ok, 0 actions

The dry tick reporting 0 actions on an exhausted window is the signature of
sharing it. One assertion on that test catches it:

    // after the dry ticks, before the `fresh` tick:
    assert.equal(doSlots(/* live worker's state */), 0,
      "a dry tick must not spend the live window");

or, in the shape they already use, exhaust the window with live ticks and then
assert the dry tick still reports its action.

## Also noted, not blocking

- `api.do` rejected by the rate limiter returns a rejection object to the script;
  if the script ignores it the tick still reports `ok` with 0 actions. Pre-existing
  and not this change's to fix, but it means "ok with 0 actions" is ambiguous at
  the agent's gate - the same ambiguity my F1 finding was about. Worth a look when
  the agent side is wired.
- Rollback digest `e07a90c5...` read from the cluster rather than the commit
  message's stale `342c10e1`: correct call, and the right instinct. I did not
  re-derive it; I take no position on the deploy.

## Nothing applied

Read-only. Archive in a scratch dir, suite re-run there, mutants applied and
restored (`git diff` empty, suite 141/141 after restore).
