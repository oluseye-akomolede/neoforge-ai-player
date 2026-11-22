# 2fb40e7: offer the script surface per bot, not per deployment — PASS

Rev reviewed: `2fb40e7`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**PASS.** No blocking findings. One note (N-1), not owed here.

## What was checked

- Suite at `2fb40e7`, read unpiped: **631 run, 1 error**
  (`ImportError: dashboard`, missing uvicorn — pre-existing). Matches the
  builder's figure.
- `openspec validate --strict` rc=0.
- The threading is complete: both production `decompose` callers pass
  `bot_name=self.name`, and `bot_name` is a required positional parameter on
  `call_script` and `render_script_system_prompt`, so a caller that forgot
  cannot silently pass `None`.
- The gate works in both directions and formats cleanly: with the default off,
  a disabled bot's prompt is ~9186 characters shorter than an enabled one's,
  and a non-named bot rendered in the same process matches the off length
  exactly — proving the gate is per-bot, not per-deployment.

## Mutants

Four, each red on exactly its named tests; all restored `cmp`-identical.

1. runner check removed -> 2 red (`test_no_runner_means_no_surface...`,
   `test_named_but_no_runner_is_off...`)
2. the "no names" default flips to on -> 4 red across both parameterisations
   of `test_unset_enabled_set_is_off_for_everyone`
3. **the render gate** (`SCRIPT_SURFACE if offered else ""` -> always
   `SCRIPT_SURFACE`) -> 2 red (`test_disabled_bot_gets_no_surface`,
   `test_no_runner_means_no_surface_even_when_named`)
4. the stray-script drop removed -> 2 red
   (`test_a_disabled_bot_loses_it`, `test_a_disabled_bots_script_is_dropped`)

Mutant 3 was the one the builder flagged as their own risk, and it is covered.
My first attempt at it was a `SyntaxError` that produced a false "survivor" —
see the note in the `1e2a789` review; the correct mutant holds.

## N-1: the plan prompt still invites a script for a bot that is not offered one

Not blocking this commit, whose claim is scoped to the *surface*: the surface
is per-bot and correctly withheld.

But the gate withholds the surface **inside** a call it never prevents. The
sequence on a deployment with `SCRIPT_BOTS` unset:

1. `_PLAN_SYSTEM_PROMPT` is formatted with no gate and still teaches
   "WHEN TO ASK FOR A SCRIPT" and `wants_script: true`.
2. A model that follows it sets `wants_script: true`.
3. `call_script` contains no `script_mode` check and fires.
4. The model receives "You are writing ONE game script" with the entire API
   surface deleted — it will do its best to write JavaScript against an API it
   cannot see — and the deployment spends a second planner call to learn that.

`_script_from` correctly drops the resulting script (and logs once), so nothing
unsafe runs. What is not saved is the call. This is arguably the same class of
waste the commit set out to end, one layer up: the plan prompt offers what the
deployment cannot honour.

Suggested shape (the builder's call): gate `wants_script` in the plan prompt on
`script_mode`, or short-circuit `call_script` when `not offered`. Either makes
the invitation and the capability agree.

## Not established

No live bot. Nothing deployed.
