## ADDED Requirements

### Requirement: Bot Chunk Anchoring

A bot MAY anchor itself, holding a chunk ticket over a small radius around its
position so that the world stays loaded while no player is online. Anchoring MUST
be opt-in per bot and MUST be metered: holding an anchor drains bot XP at a
configured hourly rate (default 2 levels/hour). When a bot cannot afford the
drain, the anchor MUST drop with one chat line and a telemetry event — it MUST
NOT silently keep the world warm for free.

The anchor state MUST persist across a server restart so a fleet that believed it
was anchored does not silently freeze, and a fleet-wide cap on anchored bots MUST
be enforced with an honest refusal beyond the cap.

The agent drives anchoring through `ANCHOR_ON` and `ANCHOR_OFF` directive kinds,
which dispatch to the bot's anchor API and report the meter rate on success.
Anchor state and burn rate are surfaced per bot.

#### Scenario: Anchor costs XP and reports the rate
- GIVEN a bot with enough XP
- WHEN the bot is told to anchor
- THEN the bot holds its chunk ticket
- AND the reply names the XP-per-hour cost
- AND the bot is reported as anchored

#### Scenario: A broke bot loses its anchor honestly
- GIVEN an anchored bot whose XP falls below the drain
- WHEN the meter next evaluates
- THEN the anchor is released
- AND the bot emits one chat line and a telemetry event
- AND the bot is no longer reported as anchored

#### Scenario: Anchor persists across restart
- GIVEN an anchored bot and a server restart
- WHEN the bot is loaded again
- THEN it re-anchors from persisted state
- AND if re-anchoring is refused, a warning is logged

#### Scenario: Fleet cap refuses honestly
- GIVEN the fleet is already at its anchored-bot cap
- WHEN another bot is asked to anchor
- THEN the request is refused with a reason

#### Scenario: Anchor released on request
- GIVEN an anchored bot
- WHEN the bot is told to release its anchor
- THEN the anchor is released
- AND the bot is reported as not anchored
