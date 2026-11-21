# bot-coded-agents — script say dedupe

## MODIFIED Requirements

### Requirement: A Script's Say And Send Are Delivered, Not Refused

The runner's `api.say` and `api.send` produce action records beside the
`do` records, and the agent MUST deliver them through the paths the planner
already uses rather than refusing them: `say` through the existing chat-send
path, `send` through the existing inter-bot message path. The agent MUST NOT
open a new channel for either, MUST NOT change the runner, its rate limits, or
the set of `do`-dispatchable kinds, and MUST NOT deliver anything from a dry
tick.

A delivered `say` or `send` counts toward the tick having handled it. Before
this, the trial of 2026-11-20 22:21Z (image `e3478fb8`, goal "say all clear in
chat") ran a script every ~61 s that called `api.say` each time, and every call
was refused with "action is a 'say' call, not a dispatchable 'do'". The script
then read as "all actions refused" and fell back to the planner, so nothing was
said in game. The planner prompt offers `api.say` and `api.send`; a planner
script that chats must be able to chat.

The runner's own rates bound this and remain the only bound: `api.say` 30/min
and `api.send` 20/min per bot, enforced inside the runner (contract §8), so a
script that calls them too often is already rate-limited before its records
reach the agent. The agent adds no second limiter.

Content dedupe is not a second limiter. Suppressing a repeat of a line the bot
already delivered within the last 60 seconds bounds how often the *same* line
reaches chat; it does not bound how many *distinct* lines a script may say per
minute, which the runner's rates alone decide. A script saying twelve different
things in a minute is unaffected by it.

One known gap bounds that guarantee: the window lives on the sandbox
(`engine.js:251`, documented at `engine.js:399-406`), so a sandbox recycle
after a `memory_exceeded`, a guard eviction or a wasm trap restarts it empty.
The honest bound is therefore 30 per rolling minute for `say` and 20 for
`send`, plus up to the same amount again per recycle. An ordinary script
throw does not recycle the sandbox (`recycle.js:45-49`).

#### Scenario: A say action is delivered through the chat path
- **GIVEN** a tick whose script called `api.say("all clear")`
- **WHEN** the agent processes the action records
- **THEN** it MUST call the existing chat path once with that text
- **AND** the tick MUST count as handled, not as "all actions refused"

#### Scenario: A send action reaches the other bot
- **GIVEN** a tick whose script called `api.send("Scout", "on my way")`
- **WHEN** the agent processes the action records
- **THEN** it MUST deliver the message through the existing inter-bot path
- **AND** the tick MUST count as handled

#### Scenario: A tick with both a do and a say handles both
- **GIVEN** a tick whose script called `api.do` and `api.say`
- **WHEN** the agent processes the action records
- **THEN** the `do` MUST dispatch as it does today
- **AND** the `say` MUST be delivered
- **AND** neither MUST be refused merely for sharing a tick with the other

#### Scenario: A dry tick delivers nothing
- **GIVEN** a script that calls `api.say` and `api.send`
- **WHEN** it is run under a dry tick
- **THEN** no chat message MUST be sent and no message MUST reach another bot
- **AND** the script's `last_deliveries` MUST be empty
- **AND** the dry tick's question MUST remain "can this script run" only

## ADDED Requirements

### Requirement: A Script's Repeated Line Does Not Reach Chat Twice In A Minute

The agent MUST NOT deliver a script's `say` whose text was delivered by that
bot through the script path within the last 60 seconds, and MUST NOT deliver a
script's `send` whose `(to, text)` pair was so delivered within the last 60
seconds. A suppressed call MUST be counted as suppressed rather than as
delivered, and the agent MUST log at most one line per suppressed key per
60-second window — not one per tick. Nothing MUST replace a suppressed line.

This requirement dedupes repeated *content*; it is not a rate limit, and it is
the content dedupe that the delivered-not-refused requirement above says is not
a second limiter: it does not bound distinct lines per minute. The runner's
per-bot limits (30 `say` and 20 `send` per rolling minute, enforced in the
runner) remain the only bounds on how often a script may speak, and the agent
MUST NOT add a second one. A script that says several *different* things in a
minute is unaffected by this requirement.

The memory is per bot and holds, per key, the time that key was last delivered
and whether its suppression has already been logged for the current window.
Both live in one record per key, so the log-once flag cannot drift from the
suppression window it describes. The memory is held by the agent, not by the
runner and not by the sandbox, so a sandbox recycle does not clear it.

A suppressed call is not a refusal: the tick still counts as handled, and a
script that is being deduped is not treated as though it failed.

#### Scenario: The same line is not delivered twice within a minute
- **GIVEN** a bot whose script delivered `api.say("No diamond ore within 5-block radius.")`
- **WHEN** 10 seconds later the script calls `api.say` with the exact same text
- **THEN** the agent MUST NOT deliver it to chat again
- **AND** it MUST count as suppressed, not delivered

#### Scenario: The window boundary is exclusive at exactly 60 seconds
- **GIVEN** a bot that delivered a `say` with some text at time `T`
- **WHEN** the script says the exact same text at exactly `T + 60.0` seconds
- **THEN** the agent MUST deliver it, because the comparison is `now - then < 60.0`
- **AND** at `T + 59.999` seconds it MUST NOT deliver it

#### Scenario: The same line is delivered again after the window
- **GIVEN** a bot that delivered a `say` with some text
- **WHEN** 61 seconds later the script says the exact same text
- **THEN** the agent MUST deliver it to chat

#### Scenario: A different line is delivered at once
- **GIVEN** a bot that just delivered `api.say("watching for diamond ore")`
- **WHEN** the next tick the script says `api.say("found diamond ore at -42, 12, 87")`
- **THEN** the agent MUST deliver it

#### Scenario: Alternating lines do not defeat the rule
- **GIVEN** a script that alternates `api.say("A")` and `api.say("B")` every tick
- **WHEN** the ticks are 10 seconds apart
- **THEN** each of `A` and `B` MUST be delivered at most once per 60 seconds

#### Scenario: send is deduped per recipient
- **GIVEN** a bot whose script sent `("Scout", "on my way")` 5 seconds ago
- **WHEN** the script sends `("Scout", "on my way")` again
- **THEN** the agent MUST NOT deliver it
- **AND** had the recipient been `"Builder"` with the same text, it MUST deliver it

#### Scenario: A suppression is logged once per window, not once per tick
- **GIVEN** a script that says the same text on every tick for 60 seconds
- **WHEN** the agent suppresses those calls
- **THEN** it MUST log the suppression once for that key in that window, not
  once per suppressed tick

#### Scenario: Dedupe does not become a rate limit
- **GIVEN** a script that says twelve different lines in one minute
- **WHEN** all are within the runner's own limits
- **THEN** the agent MUST deliver all twelve

#### Scenario: Suppression is not a refusal
- **GIVEN** a tick whose only script output is a `say` that was suppressed as a repeat
- **WHEN** the agent processes the tick
- **THEN** the tick MUST still count as handled
- **AND** the script MUST NOT be reported as having its actions refused

#### Scenario: A dry tick neither reads nor writes the memory
- **GIVEN** a bot has delivered a `say`
- **WHEN** a dry tick runs a script saying the same text
- **THEN** the dry tick MUST NOT deliver anything
- **AND** it MUST NOT change what the next live tick is compared against
