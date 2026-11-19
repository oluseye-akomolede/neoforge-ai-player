# Review: 04a4622 - M3-2 step (a) spec rev 2

**Verdict: NOT YET.** One contradiction, introduced by the B3 fix. B1 and B2 are
properly closed. Doc-only (3 files). openspec validate --strict: rc=0 at the rev.

## My B2 claim was half wrong, and your correction is right

I said "api.remember also writes memory in a dry tick (16 KiB cap, :35)". You
pushed back and you are correct. Printed at this rev:

  binding.js:113   state.memoryOut = null;      (inside resetTickState)
  binding.js:314   state.memoryOut = blob;      (inside remember)
  binding.js:295   return badShape(...)         (the actual type check)
  binding.js:304-308  the 16 KiB check, which is a REJECTION not a write

memoryOut is per-TICK state cleared by resetTickState, so nothing the sandbox
does reaches botState or the bot's memory. My "writes memory" was wrong at the
layer. Your formulation is right and better: the hazard is downstream, at
script_tick.py:363-364 `if result.memory is not None: self._memory = result.memory`,
so the dry tick's result must not be adopted. Verified at this rev. The spec now
says that and it is testable. B2 is closed on both halves (rate budget, memory).

## B1 closed, in the right place

The rebind is now named in the REQUIREMENT, not only the proposal (spec.md:57-70),
which is what I asked for: an implementer reading only the delta cannot miss it.
Latch citations verified: agent.py:235 False, :3052 early return, :3054 True,
one production caller :2890. Task 2.4 repeats it correctly.

## B3 closed - but it created the one blocking problem (C1)

Your condition 2 is correct and the per-bot reasoning is right. The problem is
what else in the same file still says the opposite.

  spec.md:130  condition 2: "No script - hand-written or previously written - is
               currently bound to this bot."               <-- gate for USE
  spec.md:160  "An existing script is not displaced by a new one ... condition 2
               fails and the bound script keeps driving the bot"
  spec.md:108  Scenario "A passing dry tick rebinds the script"
                 GIVEN a bot already bound to a working script
                 THEN the _script_loaded latch is reset ...
                 AND the next real tick runs the written source, not the
                     previous script

:108 asserts that a passing dry tick REPLACES a working script. Condition 2
(:130) says a written script may be used only when NO script is bound, and :160
affirms an existing script is NOT displaced. All three cannot hold.

The consequence is not cosmetic. Condition 2 does not merely make the rebind
scenario unreachable - it makes the rebind MECHANISM unreachable in the only
case it was built for. B1 exists because the latch must gain a reset; condition
2 as written means the reset may only ever fire when the latch is already
unset, i.e. never on a bot that has a working script. The rebind scenario at
:108 is the one scenario that exercises the B1 fix, and it is gated off by the
sentence the B3 fix added.

The same contradiction is restated in tasks.md 2.6 ("(2) NO script is currently
bound to this bot") against 2.3/2.4 (a failed dry tick "keeps any previously
bound script in force", a passing one resets the latch).

Which way to resolve it is a design call, not a review call, but it has to be
one of these and it has to be the same everywhere:
  (a) condition 2 means "no script bound FOR THIS GOAL" - but you removed that
      phrasing, correctly, because the code cannot test it; or
  (b) written scripts may displace only a script that a previous dry tick bound
      (i.e. condition 2 becomes "no HAND-WRITTEN script bound"), which is
      testable and keeps both :108 and :160 true; or
  (c) :108's GIVEN becomes "a bot whose previously written script has failed by
      its own outcome classes", matching :160's "until it fails ... or is
      unbound".
(b) is the one that makes the B1 mechanism reachable while keeping :160. Your
call, but say which, because step (b) implementation starts from this text.

## Everything else checks out

Citations re-verified at this rev, all correct: binding.js :113/:314/:295/:304-308,
:44, :45-52, :154-174, :244-251; agent.py :235/:2890/:3027/:3052-3054/:1330-1333
/:2901-2904; script_tick.py:363-364. Your three self-corrected numbers are right.
Scenario GIVENs for B3 are now per-bot and the vacuity note is honoured.
