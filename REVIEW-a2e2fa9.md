# Review: a2e2fa9 - M3-2 step (a) spec delta, ai-written-scripts

**Verdict: NOT YET.** Two blocking findings, both about "bind" describing a
mechanism that does not exist. Doc-only commit (3 files, 279 lines). Verified from
git archive a2e2fa9; openspec validate --strict: valid, rc=0.

## Citations: independently verified, and they hold this time

You asked me not to take your numbers. I printed every one.

Runner (from /home/sigmastrain/minecraft/agent-script-runner, the real checkout):
  engine.js:2-12   "one QuickJS runtime per bot ... No filesystem and no network"
  main.js:51       MAX_SOURCE_BYTES = 64 * 1024
  engine.js:32     STACK_LIMIT_BYTES = 256 * 1024
  engine.js:41     HEAP_LIMIT_BYTES = 32 * 1024 * 1024
  binding.js:31    "more than 8 accepted host calls in one tick is host_calls_exceeded"
  binding.js:225-318  exactly six methods: do :226, say :253, send :262,
                   recall :293, remember :297, log :318
All correct. MAX_HOST_CALLS = 8 at :32. No stale numbers in the proposal or tasks.

Liveness claim ("coded-agents unarchived, nothing in openspec/specs") verified:
  openspec/specs/ has no bot-coded-agents; openspec/changes/coded-agents exists
  and is unarchived. Task 4.1's ADDED->MODIFIED warning is honest and correct.

## B1 - "bind" names a mechanism that does not exist; the latch forbids it

Both new requirements are built on "before it is bound" and "bind it only if that
tick returns ok". Nothing in the tree can rebind a script at runtime:

  agent.py:235   self._script_loaded = False     (construction only)
  agent.py:3052  if self._script_loaded: return self._script_tick
  agent.py:3054  self._script_loaded = True       (one shot)

grep for _script_loaded in agent/agent.py returns exactly those three: it is set
False once at construction, read once, set True once. _get_script_tick has one
production caller (:2890) and never reloads. Binding today is a ConfigMap read of
bindings.json at first tick (agent.py:3011), fixed for the process lifetime.

So "a planner-authored script is bound before its first real tick" requires a
rebind path that the design forbids: the script is latched once, at :3054,
precisely so a bind is stable. Requirement 2 and condition 2/3 all presuppose it.
This is not a citation error, it is a missing mechanism, and it is the single
largest thing step (b) implementation will hit.

What I am NOT saying: that the requirements are wrong. A dry-tick-before-bind
gate is the right shape. What they need is one sentence acknowledging that
binding becomes a REBIND (the latch must gain a defined reset for a
planner-authored script, and the reset must be the only writer). Without it an
implementer reads "bind" as "call the existing path", and the existing path
returns the old script forever.

## B2 - the dry tick spends the bot's real rate budget (answers your (2))

You asked whether the dry tick is the right gate or whether the risk is
elsewhere. The gate is right, and cheaper than the spec implies - but it has a
side effect the spec's "with its actions suppressed" does not cover.

Actions are already structurally suppressed. api.do does NOT dispatch; it pushes
onto a sandbox-local array (binding.js:244-251 `state.actions.push`), and
script_tick.tick() returns bound actions for the caller to dispatch
(script_tick.py:396 `return True, bound, ...`). The agent at agent.py:2892
discards the return. So "queued actions are discarded, not dispatched" is true,
but there is nothing to discard: a dry tick is just a tick whose return value is
ignored. That part is free.

The part that is NOT free: acceptAction records into botState.actionTimes, which
is per-BOT state that SURVIVES the tick and is deliberately not reset
(binding.js:47-52, "must SURVIVE a tick ... resetTickState deliberately does not
touch this object"; the window lives on the sandbox, engine.js:251). Limits are
do:30/min, say:30/min, send:20/min (binding.js:44). A dry tick that calls api.do
therefore consumes up to 8 of the bot's 30 do-slots/min for a script that never
runs. Dry-tick every planner-emitted proposal and a bot that keeps proposing gets
its real script rate-limited by scripts it rejected.

Also: api.remember in a dry tick writes memory bytes (16 KiB cap, binding.js:35),
and the spec says a failed dry tick "disarms nothing and interrupts no task" -
that sentence is about the previous script, but the memory write is on the bot,
not the script.

Cheapest fix, and it is a spec sentence not an engine change: the dry tick MUST
NOT consume the bot's rate budget or memory - either run it against a throwaway
botState with limits, or state that a dry tick's actions are discarded and its
remember is not carried. Naming botState.actionTimes and the memory write makes
it testable; "actions suppressed" does not, because the rate window is not an
action.

## B3 - condition 3 and the hold answer different questions (answers your (3))

No, they cannot disagree about ownership, but not for the reason condition 3
implies - condition 3 is unreachable in two different ways.

The hold names a GOAL (`_script_hold = {"goal_id": ...}`, agent.py:1329-1332) and
suppresses THE BOT's dispatch (agent.py:2901-2904: `hold = self._script_hold; if
hold: return SCRIPT_HELD`). It does not name a script. So a held script and a new
script cannot disagree about ownership: the hold owns the bot regardless of which
script is bound, and a new script would simply be held too.

But condition 3 says "No hand-written or previously bound script is already
driving this bot for this goal." Two problems:

  (a) scripts are bound per BOT, not per goal (bindings.json maps bot name ->
      script, agent.py:2987/3027 `bindings.get(self.name)`). There is no
      goal-to-script association to test condition 3 against. The requirement's
      own scenario "an existing script is not displaced" GIVEN "a bot already
      bound to a working script for its goal" assumes an association the binding
      model does not have.

  (b) if a script IS bound, _script_loaded is already True and _get_script_tick
      returns the cached one - so a new script can never be proposed-in and
      bound anyway (B1). Condition 3 currently can only ever evaluate to "an
      existing script exists", for every goal, forever.

Meanwhile the hold requirement you added DOES carry goal identity correctly
("Its identity as 'the script for goal G' MUST be carried wherever a bound
script's identity is carried"). That sentence and condition 3 contradict: one
says script identity is per-goal and must be carried, the other assumes it
already is.

## Vacuity check (answers your (3) style question)

"Plain planner is the default" passes TODAY without any of this change: no script
producer exists, so every plan is directives. That is acceptable for a
no-regression pin but it must not be counted as evidence the feature works. The
three that would be genuinely vacuous if implemented naively are the dry-tick
ones, but they assert a non-ok outcome and a not-bound result, which cannot pass
on a tree with no dry tick at all. So: one pin passes today (fine, by design),
the rest need the mechanism.

## Not findings
- Re-stating nothing from coded-agents is correct and the right instinct.
- The skill-layer tension is named rather than hidden; the sandbox citations
  that back it verified.
- Task 4.1 (ADDED becomes MODIFIED when coded-agents archives) is the kind of
  forward note that usually gets omitted.
