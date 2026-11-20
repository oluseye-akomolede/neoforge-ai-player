# Review: 47c959a - M3-2 step (a) impl rev 1, the dry-tick gate

**Verdict: NOT YET.** One blocking defect in `_dry_tick`, one test that is
blind to the hazard it names. Both are in this rev and both are cheap to fix;
the rest of the commit is good and I would take it once they are.

Reviewed from `git archive 47c959a`, not a worktree. Parent is `ccfd69c`, which
I passed, so no rebase drift. Suite from the archive:
`test_agent_script_branch` Ran 45 tests, OK, rc=0.

Row: qitem-20261120005150-b22bc52d8503ab66.

## F1 (blocking) - `handled` is not "the script ran ok"

`_dry_tick` returns True iff `handled` is true, and its docstring says "Returns
True iff the tick reported `ok`". Those are not the same predicate.
`script_tick.tick()` returns `handled=False` for two unrelated situations:

  :340   `return False, [], [], f"runner {result.state}: {result.detail}"`  <- did not run
  :390   `return False, [], refusals, "all actions refused"`               <- RAN FINE

The second is reached when the script executed cleanly and emitted actions that
`action_binding` or `translate_runner_actions` refused. A script can therefore
run perfectly and still be rejected by the gate, and the gate will report it as
a script that failed its first tick.

This is not theoretical. `translate_runner_actions._translate_one` refuses every
`say` and `send` record on principle - they are legitimate runner calls that are
simply not dispatchable `do`s. Print at this rev, run on the real translate
path:

    recs = [{'seq':0,'call':'say','directive':None,'args':{}}]
    pairs, refusals = translate_runner_actions(recs)
    -> pairs: []
       refusals: [{'seq':0,'error':"action is a 'say' call, not a dispatchable
                   'do': only do-calls become directives"}]
    -> bind_actions([]) = [], []
    -> tick() would return handled=False   (script ran fine)

So a planner-authored script whose whole purpose is `api.say(...)` to the player
fails its dry tick and is never bound. Same for any `do` carrying an argument
outside `_ALLOWED_ARGS`:

    bind_actions([{'kind':'MINE','teleport_to':(1,2,3)}])
    -> bound: [], refusals: [... 'unsupported argument' ...]  -> handled=False

The spec's own MUST is the anchor here (`spec.md:56`): bind the script "only if
that tick returns `ok`". The requirement is about whether the code RUNS - it
names "throw, host-call cap, CPU budget" as the failure classes. A refusal is
not one of those; it is a binding decision taken after a successful run, and
today it is being folded into the same bit.

**Fix.** `_dry_tick` must distinguish "did not run" from "ran, but some actions
were refused". Either return a new `result.state != STATE_SCRIPT` style
predicate, or have `tick()` expose the run outcome separately from `handled`.
`script_tick.py:386-391` already documents that this distinction matters ("That
is still a handled tick *if* the script genuinely said do nothing... Distinguish
the two") - the dry-tick path collapses exactly that distinction. Note that the
builders' tests never reach `:390`: every stub returns a pre-cooked tuple, so
the translate/bind path is not exercised at all.

## F2 (blocking) - the memory test is blind to the real hazard

`test_dry_tick_returns_the_bot_memory_unchanged` asserts on
`self.a._script_memory`. That attribute does not exist in production: `grep -c
_script_memory agent/agent.py` at this rev returns 1, and it is the comment at
`:3041` ("Nothing is assigned to `self._script_memory`"). The real field is
`ScriptTick._memory` (`script_tick.py:264`, adopted at `:364`).

The test sets the attribute itself, `_dry_tick` never touches it, and the
assertion compares the value the test put there to itself. It passes because
nothing happened, not because the guard works.

I checked M1 the way the builder says they ran it, then the way it matters:

  - M1 as an assignment to `self._script_memory` -> test reddens. CIRCULAR: the
    mutant writes the exact attribute the test asserts on.
  - M1 as the real hazard, adopting from the tick's own `._memory` the way
    `script_tick.py:364` does -> **test stays green.** Test is blind.

That is the inert-gate failure: a gate whose fixture shape differs from the
hazard it names always passes. The docstring's reasoning is right - a non-None
stub memory is necessary - but necessary is not sufficient; the assertion has to
land on the field the production code would actually adopt into.

**Fix.** Assert on a real Agent attribute that `_dry_tick` could plausibly write
(or on absence of any memory assignment), and re-run M1 in the shape of the real
adoption, i.e. have the mutant do `self._memory = st._memory`.

For the record, M2 and M3 are genuine - I applied both to the real `_dry_tick`
and both redden their target tests:
  M2 (`return True` always)        -> test_failing_dry_tick_does_not_bind FAILS
  M3 (append to live actionTimes)  -> test_dry_tick_never_touches_the_live_rate_window FAILS
And the rate test does assert `len(calls) == 1`, so it cannot pass on a script
that never ran. That half of the vacuity defence holds; the memory half does not.

## What is good

- **The throwaway-botState mechanism is right.** `createApi(api, ..., botState)`
  with a private window is the only thing `acceptAction`'s filter-then-push shape
  supports, and the commit explains why rather than asserting it.
- **N1 taken correctly.** spec now says "neither `actionTimes` nor `logTimes`",
  and the scenario THEN covers both. I re-printed `createBotState`
  (`binding.js:59-65`) and `api.log`'s spend (`:337-346`) at `2733485`: correct.
- **The `import api` self-check is the best thing in the message.** The builder
  nearly filed a pre-existing-NameError bug, the end-to-end test contradicted the
  AST analysis, and they believed the test. That is the right instinct and I want
  it recorded, not just noted.
- **`if not source: return False`** and the broad `except` around `st.tick()` are
  correct: an unavailable runner must fail closed, not bind.

## Residual, not blocking this rev

`_dry_tick` is dead code - nothing calls it - so F1 and F2 cannot ship a wrong
bot today. That is why this is NOT YET rather than a reject. Please fix both
before the wiring rev, because the wiring rev is where a `say`-only script would
start silently failing to bind, and the memory test would stay green over it.
