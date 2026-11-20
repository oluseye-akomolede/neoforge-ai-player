# Script lookups and results

## Why

The owner's goal (Slack, 2026-11-19) is programmatic tool calling for bot work:
(a) the planner writes the bot's JS script, (b) read-only lookups the script can
call, (c) the script's result returned to the planner.

Step (a) is proven on test. At 22:38Z a planner-authored script dry-ticked,
bound, released the hold, and its `api.say` reached game chat about once a
minute (`8e1b3a5`, with `0193a44` and `5adc9c2` as spec follow-ups).

(b) and (c) are designed here and nothing else. No agent code, no runner code,
no deployment. This change exists so the reviewer can reject the shape before
anyone writes it.

## What the two steps are for

Without (b) a script can only act on what the snapshot happens to carry and on
what the previous tick wrote with `api.remember`. A script that wants "the
nearest sheep", "what colour is that flower", or "is there a chest within 16
blocks" has to re-derive it from a fixed-radius list, or give up and hand the
tick back to the planner — which is the one thing a script exists to avoid.

Without (c) the planner is blind after it writes a script. It learns that the
script was accepted at write time and nothing after: not whether the goal was
reached, not what went wrong when it was not. The current path reports a script
error into the agent log and the planner never sees it.

## The shape of what is proposed

**A lookup is a pure function over data already in the tick.** The agent already
sends health, food, position, inventory, nearby blocks (radius 8) and nearby
mobs (radius 24) every tick (`agent/snapshot.py:49-77`). A lookup is a function
over that object, evaluated inside the sandbox. It costs no host call, cannot
reach the network or the mod, and is read-only by construction rather than by
promise — see `design.md` §1 and §2 for the alternative considered and why it
was rejected.

**A result is a small, bounded value the script returns, delivered to the
planner on stated conditions only.** Not every tick, not every log line. The
return value of the script, size-capped, returning to the planner when the
script says the goal is done, when it errors, or when an escalation threshold is
crossed — with a hard cap on how often that can happen per hour, so a script
cannot turn itself into a planner-per-tick loop. See `design.md` §3.

## What this does not do

- It does not add a lookup that reads live game state mid-tick (rejected in
  `design.md` §1, option B).
- It does not change the six-function host API, the 8-host-calls-per-tick cap,
  the rate windows, or the tick CPU budget.
- It does not deliver script logs or delivered actions to the planner.
- It does not change how a script is written, validated, or bound (step a).
- It does not touch the chat-pauses-script rule (M3-1g).

## Risk

The expensive mistake here is a result path that wakes the planner on every
tick: one LLM call per tick per bot, on a shared subscription. §3's caps are the
guard, and §4 gives the trial that would catch it if the caps fail to hold.
