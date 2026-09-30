## ADDED Requirements

### Requirement: Bot Conversation Behaviour

A bot SHALL hold a conversation when addressed conversationally, replying in
server chat in its persona, and SHALL treat the conversation as distinct from an
order. Conversation MUST NOT create a directive or a plan.

Personas are the ones already defined for the plan layer: Axiom (generalist),
Forge (builder), Mystic (mage), Scout (explorer), Tiller (farmer).

#### Scenario: Bot answers a character question in character

- **WHEN** a player asks a bot who it is
- **THEN** the bot replies in server chat in the persona for its name
- **AND** the reply appears in the server chat log from that bot
- **AND** no directive is set

#### Scenario: Conversation does not disturb a running plan

- **GIVEN** a bot has a plan executing
- **WHEN** a player addresses it conversationally
- **THEN** the bot replies in chat
- **AND** the running plan is not replaced, restarted, or cancelled

#### Scenario: Other bots ignore an addressed message

- **GIVEN** several bots are online
- **WHEN** a player addresses one bot by name
- **THEN** only that bot replies

### Requirement: Bot Stop Acknowledgements

For the stop shortcuts the bot recognizes — `stop`, and the phrases `halt`,
`go idle`, `stand still`, `stay here`, `stay put`, `wait here`, `stop what you`,
`stop following` — the bot SHALL tell the player it is stopping, and the
acknowledgement MUST reflect that a plan was or was not cancelled. The
acknowledgement is a chat message from the bot, not only an agent log line.

A cancellation of a running plan is not limited to those wordings: any stop
signal the bot accepts SHALL cancel a running plan. This requirement covers only
which wordings are *acknowledged in chat*; a wording outside this list gets no
acknowledgement, which is the current intended scope.

#### Scenario: Acknowledgement names the stopping state

- **GIVEN** a bot is executing a plan
- **WHEN** a player says "stop"
- **THEN** the bot says it is stopping
- **AND** the bot's next directive state does not show a plan still executing

#### Scenario: Acknowledgement without a plan

- **GIVEN** a bot is idle
- **WHEN** a player says "stop"
- **THEN** the bot acknowledges and remains idle

#### Scenario: A recognized phrase also acknowledges

- **GIVEN** a bot is executing a plan
- **WHEN** a player says "halt"
- **THEN** the bot says it is stopping, by the same path as "stop"

### Requirement: Bot Declines Are Spoken

When a bot cannot or should not act on a request, it SHALL say so in chat with a
short reason rather than acting on a substituted interpretation. A decline is a
normal, successful outcome of the bot's reasoning, not an error state of the bot
itself.

#### Scenario: Vague request gets a question instead of an invention

- **WHEN** a player gives an underspecified request
- **THEN** the bot asks for the missing specifics in chat
- **AND** the bot does not start work the player did not ask for

#### Scenario: Impossible request gets a refusal

- **WHEN** a player asks for something the world does not permit
- **THEN** the bot refuses in chat with a short reason
- **AND** the bot does not report success

### Requirement: Bot Success Reports Are Truthful

A bot SHALL report a request as complete only when the work it was given was
actually completed. If part of the work did not complete, the bot's report MUST
say what did not work.

#### Scenario: Incomplete work is not reported complete

- **GIVEN** a bot's plan has a subtask that did not complete
- **WHEN** the plan is finalized
- **THEN** the bot does not report the request as complete
- **AND** the report names the unfinished work

#### Scenario: Completed work is reported complete

- **GIVEN** a bot's plan finished every subtask
- **WHEN** the plan is finalized
- **THEN** the bot reports the request as complete
