# Review: ccfd69c - M3-2 step (a) spec, rate-budget scenario made implementable

**Verdict: PASS, with one non-blocking note (N1).** Doc-only, 3 deltas,
`openspec validate ai-written-scripts --strict` rc=0 from `git archive ccfd69c`.

Reviewed at the same time as the rebase pointer for REVIEW-58689f7.md; this rev
sits on the builder's branch after the rebase, so nothing here depends on the
old shas.

## The unimplementable scenario - their read is correct, and I checked it

They said the original scenario ("window at 30/min, THEN rejected as
rate_limited, AND actionTimes unchanged") cannot be built because
`acceptAction` has no check-without-spending mode. Verified by printing the
function at 2733485 in agent-script-runner:

- `binding.js:154-174` - `acceptAction` filters in place (:159-163), then
  EITHER returns `rate_limited` (:165-171) OR pushes (:172). There is no path
  that inspects and declines to record. Their reading is exactly right.
- `binding.js:126-136` - `createApi(state, { botState = createBotState(), ... })`.
  `botState` is a parameter with a fresh default, and the doc comment says the
  engine always passes its own. So a throwaway window is reachable without
  touching the runner.
- `engine.js:756` - the engine passes `this.#botState`, created once at :238
  and documented at :236-237 as surviving ticks "which is why the api.log cap
  never fired". Confirms the window is deliberately long-lived.
- `binding.js:244-251` - `api.do` pushes onto `state.actions` AFTER
  `accept()`/`acceptAction()` at :240. So the action is discarded but the
  spend already happened: the asymmetry that makes the original scenario
  impossible.

All four citations were printed at that rev, not taken from the message. They
are correct. The throwaway-botState mechanism is not a workaround; it is the
only construction that satisfies both "the gate runs real code" and "the live
window is untouched".

## N1 (non-blocking) - botState carries TWO windows; the requirement names one

`createBotState` (binding.js:59-65) holds `actionTimes` AND `logTimes`. The
throwaway object replaces both, so the mechanism is complete. But:

- The MUST at spec:69 says only "`actionTimes` MUST be unchanged by it".
- The MUST at spec:61-69 motivates with `api.do` alone.
- Scenario "A dry tick spends no rate budget" (:106-113) asserts only
  `botState.actionTimes` is unchanged.

`api.log` spends from `botState.logTimes` (:337-346) by the same
survives-the-tick argument, and the six-method api (spec:12, :30) includes
`log`. A dry tick is bounded to 8 host calls by `accept()` (:138-145), so the
exposure is up to 8 lines of a 100/min log window - small, and the throwaway
state already prevents it. This is a completeness note, not a defect: an
implementer who does what the paragraph says is safe. It matters only if
someone later "optimises" to a shared window for `do` and reasons from the
requirement text that `log` was never in scope.

Suggested, not required: say "neither `actionTimes` nor `logTimes`", and add
`logTimes` to the scenario's THEN. One phrase.

## Their three vacuity commitments - all three are the right shape

- memory test must make the dry tick RETURN a non-None memory. Correct: the
  adoption guard is `if result.memory is not None` (script_tick.py:363), so a
  None-returning dry tick passes without exercising the hazard.
- actionTimes test asserts on the live window after a dry tick that actually
  queued actions. Correct: an empty script never reaches acceptAction, so a
  no-call dry tick proves nothing.
- Both are the same fixture-shape discipline that 2438898 lacked.

## Judgement

The revision improves the requirement rather than weakening it: the guarantee
changes from "a dry tick is not wrongly rate-limited" (which the runner cannot
express) to "a dry tick has no access to the bot's budget at all" (which it
can). That is stronger and testable. PASS.

Nothing applied or pushed. Read-only throughout.
