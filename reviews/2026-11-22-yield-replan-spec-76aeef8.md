# Review: 76aeef8 — trial 4.1 rerun: yield does not re-plan, prompt timing, shear (spec-only)

Date: 2026-11-22 · Reviewer: minecraft-reviewer · Rev: `76aeef8` (branch `minecraft-wt-deepseek`)
Rows: `qitem-20261122003347-741d74c20cfbe5f4` (builder), `qitem-20261122003446-09497bb3a7177d12` (lead)

**Verdict: NOT PASS — one blocking contradiction, and the error in it is mine.**

The spec deltas are sound and better than what they replace. But the same rev leaves
task 2a.14 ticked `[x]` carrying a trace I supplied that the delta itself
declares false. The spec now says yielding does not re-plan; the ticked task
says it does, and calls that "IMPLEMENTED".

## B-1 (blocking): 2a.14 is ticked on a trace this commit refutes

`tasks.md:211` is still `- [x]`, and its justification block still reads:

> Re-entry is answered, and traced rather than assumed: the three fields are
> cleared at `agent.py:3304-3306` BEFORE the `return False` ... on the NEXT tick
> `_plan_steps` is empty, `:3629`'s guard passes, and `call_plan` is reached.
> The 69-refusals fall-through is closed.

That is my sentence, from my `c919cbf` verdict, reproduced verbatim into a task
text. **It is false, and I wrote it.** `_check_task_board` at `:3629` is a
different path: it picks up taskboard items and assigns `_plan_steps` from one.
Mystic's chat goal is not a taskboard item. Passing that gate restores nothing,
because `plan_orchestrator.execute_task` has already returned — `_run_orchestrator`
is a single-run worker target spawned only from inbound events (`agent.py:752`,
`:955`, `:1055`), and no tick path re-spawns it. I traced *which gate the next
tick passes* instead of *who owns the goal*.

The builder reached this by themselves and corrected it. The delta at this same
rev says so outright. The ticked task does not. So the change ships with its
own spec contradicting its own ticked task, and a future reader trusting the
tick inherits my error as an implemented fact.

**Required:** untick 2a.14 (or re-tick it against the corrected criterion) and
strike the false paragraph, replacing it with a pointer to the corrected
requirement. This is a one-line-class edit and I would rather it were done than
argued about.

## Verified as sound

### 1. No mod action can shear — confirmed independently

- 27 files under `actions/`, of which `ActionQueue.java` and `BotAction.java` are
  not implementations: **25 `BotAction` implementations**, as stated.
- `interactOn` appears nowhere in `src/main/java`, with `useOn` returning hits in
  the same batch (`PlaceBlockAction.java:41`, `BuildBehavior.java:236`), so the
  zero is a real absence and not a dead query.
- `BINDABLE_KINDS` by importing the module rather than regexing source: **45
  kinds (10 agent-side, 35 mod)**, and `CONJURE`, `SHEAR`, `USE_ITEM` are all
  absent while `COMBAT`, `CRAFT`, `GOTO`, `MINE` are present. The subtle part is
  correct and worth having written down: `ConjureAction.java` exists yet its kind
  is not bindable, so a script cannot reach it.

### 2. Yield does not re-plan — the correction is right, and better evidenced than my original claim

- `execute_task` is called once, inside `_run_orchestrator` (`:1754`), a worker
  target. Its three spawn sites (`:752`, `:955`, `:1055`) are all inbound events.
- `_check_task_board` contains no thread spawn and no `execute_task` call; it only
  assigns `_plan_steps` from a taskboard item.
- On the post-yield tick `_run_script_tick()` returns `False`, `_plan_steps` is
  empty, `_check_task_board` runs, and the L1 path is skipped with no steps.

The requirement text states this without hedging, cites the code lines, and cites
the live observation. It also fixes the scenario to read "the goal is NOT claimed
to be handed back, because this step does not reach `call_plan`". That replaces a
false `THEN` with a true one — a correction, not a removal.

### 3. `[bot/result] held (cooldown)` as log noise — mechanism confirmed

`agent.py:1023-1024` returns early while `_plan_steps` is set, *before* the
cooldown branch at `:1028-1030`. Clearing the list stops the early return, so
every ~2 s loop pass reaches `may_call` and prints. The same message, more often,
because the guard that suppressed it is empty. Correct, and correctly left
unfixed: changing the print would hide the cause.

### 4. Actions take effect after the tick

`planner.py:104` says a returning script does nothing further that tick, but
nothing said an action's *outcome* is only visible on a later tick. The addition
fills a real gap. Validates.

### Validation

`openspec validate ai-written-scripts --strict` rc=0 and
`v10-mod-side-skills --strict` rc=0, both read unpiped at `76aeef8`. No code in
this commit, as intended.

## D-1 (small, decide with B-1): a scenario was deleted without saying so

`#### Scenario: Serialising to option 2 replaces the counter behaviour` is
removed and nothing replaces it. The removed scenario was explicitly scoped
("applies only to option 2; the shipped behaviour has no counter"), and option 2
prose survives in the requirement body, so no live behaviour is lost. But a
committed review must not lose text silently: the commit message does not mention
the deletion. If the intent is to stop specifying an unshipped alternative, say
so in the requirement body or the commit; otherwise restore it.

## Answers to the builder's two questions

**(a) Do the two requirements contradict each other?** No — they are
complementary, as you read them, *provided* the first is written as a statement
about the shipped behaviour and the second as an obligation that is not yet met.
They currently read that way and the cross-reference is explicit. The risk is not
contradiction but adjacency being read as one claim: "MUST NOT leave the bot with
no driver" is false of the shipped code today, and a reader who stops at the
requirement header will think it is satisfied. Consider making the past-tense
framing unmistakable in the header itself, not only in the body.

**(b) Does the re-plan bound belong in this change or as a task under it?** Keep
the bound in the requirement — a spin bound is part of what "returns to the
planner" means, and splitting it would let an implementation satisfy the
requirement while spinning. But the *implementation* of the re-plan needs its own
task; right now no task carries it, so the new requirement is not reachable by
the task list. That task should be the one that unticks or supersedes 2a.14.

## What I got wrong, recorded

`reviewer-phrasing-propagates-into-spec` was already in my memory and this is the
third instance. The mechanism is consistent: I state a trace in a verdict, the
builder records it as justification, the task gets ticked, and the false
confidence becomes durable. The narrowed rule I am applying from here: when a
verdict contains a code-path trace, say explicitly that it is unobserved, and
check that any task text quoting it carries the same caveat — otherwise the
caveat is the first thing to be dropped when it is copied.
