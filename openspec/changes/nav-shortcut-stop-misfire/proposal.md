# Nav shortcut stop misfires on an instruction that contains a stop phrase

## Why

A chat message to a bot was read as a navigation stop command when its actual
intent was the opposite. On test at 2026-11-20 18:57Z the message

> Scout, from now on, whenever your health drops below half, stop what you are
> doing and eat some food

was handled by the nav shortcut and logged `Direct stop (shortcut)`. The bot
never saw the goal. The `_stop_phrases` list at `agent/agent.py:499-500`
contains `"stop what you"`, and the shortcut test is a plain substring test
against the whole lowercased sentence (`agent/agent.py:522`), so any instruction
that *contains* that fragment is treated as an instruction *to stop*.

The damage did not end with the misread message. The shortcut calls
`_cancel_orchestrator` (`agent/agent.py:525`), and when no orchestrator is
running that records `_orch_stop_pending = True`
(`agent/agent.py:1299-1300`). That flag is checked at the start of the *next*
orchestrator (`agent/agent.py:1577-1581`), which then cancels a goal the player
never asked to cancel. The 18:57Z trial logged `honoring pending stop at
orchestrator start` and then `plan finalized: cancelled` on the goal that
followed. So one misread chat message destroyed two goals: its own, and the
next one the player sent.

Both halves are the same root cause — a stop is inferred from a fragment
instead of from a message that means stop — but they need separate guards
because fixing the matcher alone would leave a stale flag able to cancel an
unrelated goal if any other path ever set it.

## What changes

Behaviour changes, so this is a spec delta. The fix is not written yet: this
change records the requirement and the scenarios so the regression can be
tested against, per the lead's instruction to write it up but not fix it yet.

## Impact

- Affected spec: `bot-coded-agents`
- Affected code: `agent/agent.py` (`_stop_phrases`, the pre-scan shortcut
  block at `:503-573`, `_cancel_orchestrator` at `:1290-1307`, and the
  pending-stop check at `:1577-1581`)
- Not affected: the script path, the planner, the gateway
