# bot-coded-agents — script say dedupe

## ADDED Requirements

### Requirement: A Script's Repeated Line Does Not Reach Chat Twice In A Minute

The agent MUST NOT deliver a script's `say` whose text was delivered by that
bot through the script path within the last 60 seconds, and MUST NOT deliver a
script's `send` whose `(to, text)` pair was so delivered within the last 60
seconds. A suppressed call MUST be counted as suppressed rather than as
delivered, and the agent MUST log at most one line per suppressed key per
60-second window — not one per tick. Nothing MUST replace a suppressed line.

This requirement dedupes repeated *content*; it is not a rate limit. The
runner's per-bot limits (30 `say` and 20 `send` per rolling minute, enforced in
the runner) remain the only bounds on how often a script may speak, and the
agent MUST NOT add a second one. A script that says several *different* things
in a minute is unaffected by this requirement.

The memory is per bot and holds the last delivered key per stream, together
with the time it was delivered. It is held by the agent, not by the runner and
not by the sandbox, so a sandbox recycle does not clear it.

A suppressed call is not a refusal: the tick still counts as handled, and a
script that is being deduped is not treated as though it failed.

#### Scenario: The same line is not delivered twice within a minute
- **GIVEN** a bot whose script delivered `api.say("No diamond ore within 5-block radius.")`
- **WHEN** 10 seconds later the script calls `api.say` with the exact same text
- **THEN** the agent MUST NOT deliver it to chat again
- **AND** it MUST count as suppressed, not delivered

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
