## ADDED Requirements

### Requirement: A Stop Shortcut Matches Only A Message That Means Stop

The nav shortcut SHALL treat an incoming chat message as a stop command only
when that message is itself an instruction to stop. A message whose stop-like
phrase is embedded in a longer instruction that asks the bot to DO something
MUST NOT be handled by the stop shortcut; it MUST continue to normal goal
processing like any other instruction.

#### Scenario: An instruction containing a stop phrase is a goal, not a stop

- **WHEN** the player sends "Scout, from now on, whenever your health drops
  below half, stop what you are doing and eat some food"
- **THEN** the message MUST NOT be logged as `Direct stop (shortcut)`
- **AND** the message MUST be processed as a goal, so the bot plans and runs
  the eat-when-health-is-low behaviour
- **AND** no `api.stop` or `api.cancel_directive` MUST be issued on its behalf

#### Scenario: A bare stop command still stops

- **WHEN** the player sends exactly "stop"
- **THEN** the bot MUST stop what it is doing and log `Direct stop (shortcut)`
- **AND** the reply MUST be the normal stopping acknowledgement

#### Scenario: A follow instruction is unaffected

- **WHEN** the player sends "follow me"
- **THEN** the follow shortcut MUST still apply

### Requirement: A Pending Stop Does Not Outlive The Message That Set It

When the stop shortcut finds no running orchestrator it records a pending stop
so a thread that is about to publish cannot miss it. That pending stop SHALL
apply only to the work it was meant to cancel. It MUST NOT cancel a goal that
the player sends afterwards.

#### Scenario: A stop cannot cancel the next goal

- **WHEN** a chat message is handled by the stop shortcut while no orchestrator
  is running
- **AND** the player then sends an unrelated instruction
- **THEN** the new goal MUST run, not be `plan finalized: cancelled`
- **AND** the orchestrator MUST NOT log `honoring pending stop at orchestrator
  start` for it

#### Scenario: The pending stop still catches the race it exists for

- **WHEN** a stop arrives in the window between the orchestrator thread being
  spawned and it publishing its cancel event
- **THEN** that same goal MUST still be cancelled
- **AND** the cancellation MUST be visible in the log
