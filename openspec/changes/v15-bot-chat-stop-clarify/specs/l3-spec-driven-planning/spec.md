## ADDED Requirements

### Requirement: Chat Is Answered, Not Planned

A player chat message addressed to a bot MUST first be classified as conversation
or order. A conversational message SHALL be answered in the bot's persona via the
L3 conversation path and sent to server chat, and MUST NOT start a plan.

Classification MUST default to `task` on any error, timeout, or unrecognised
reply, so an order is never silently dropped. The classifier is one L3 call per
addressed message.

#### Scenario: Character question is answered without a plan

- **WHEN** a player says "Mystic, who are you?"
- **THEN** the bot replies in server chat in its persona
- **AND** no plan file is written and no subtask is dispatched
- **AND** the agent log shows the message was handled on the conversation path

#### Scenario: An instruction still plans

- **WHEN** a player says "Scout, gather 4 oak logs"
- **THEN** the message is classified as a task
- **AND** the plan layer runs exactly as it did before this change

#### Scenario: Classifier failure does not swallow an order

- **GIVEN** the classifier call errors or returns an unrecognised kind
- **WHEN** a player addresses the bot
- **THEN** the message is treated as a task
- **AND** the bot does not answer with a conversational reply instead of acting

### Requirement: Stop Cancels a Running Plan

A stop signal SHALL abort the bot's running plan. The plan MUST be finalized
`cancelled` — never `complete` — and the bot SHALL confirm in chat.

The abort is delivered by a per-run cancellation signal that the plan layer
checks between subtasks and before each subtask attempt; clearing plan state on
the agent's main thread is not sufficient on its own, because the plan runs on a
separate thread.

#### Scenario: Stop during a running plan

- **GIVEN** a bot is executing a multi-subtask plan
- **WHEN** a player says "stop"
- **THEN** the orchestrator aborts before dispatching the next subtask
- **AND** the plan is finalized `cancelled`
- **AND** the bot says "Stopping." in chat
- **AND** the plan is not reported `complete`

#### Scenario: Reset cancels a running plan

- **GIVEN** a bot is executing a plan
- **WHEN** the bot's state is reset
- **THEN** the running plan is cancelled by the same signal as a stop

#### Scenario: Stop with no plan running is harmless

- **GIVEN** a bot has no plan executing
- **WHEN** a player says "stop"
- **THEN** the bot acknowledges and no plan is created or finalized

### Requirement: Clarify or Refuse Instead of Inventing

The planning step MAY return a clarification or refusal instead of a plan. When it
does, the bot SHALL say the reason in server chat and MUST NOT dispatch any
subtask, and the plan SHALL be recorded as failed with the decline preserved.

The planning prompt MUST state that declining is required rather than substituting
a different, doable-sounding task; a plausible substitution is not an acceptable
plan.

#### Scenario: Vague request is questioned

- **WHEN** a player says "Tiller, go get some stuff"
- **THEN** the bot asks what and how much, in chat
- **AND** no subtask is executed
- **AND** the plan is failed, carrying the decline kind `clarify` and the reason

#### Scenario: Impossible request is refused

- **WHEN** a player asks for something the world does not permit
- **THEN** the bot declines in chat with a short reason
- **AND** no subtask is executed
- **AND** the decline kind `refuse` is preserved on the plan record

#### Scenario: Declining does not require a substituted plan

- **GIVEN** the planning call can answer with a clarify or refuse object
- **WHEN** it does
- **THEN** the plan layer accepts that answer without validation against the plan
  schema, because it is not a plan

### Requirement: Plan Complete Only If Every Subtask Passed

A plan SHALL be reported `complete` only if every subtask is `complete` at
finalize. Any subtask not `complete` MUST force the plan to `failed` and MUST be
recorded on the plan record.

The plan status MUST NOT be derived solely from how the execution loop exited,
because the loop also leaves "complete" when it runs off the end past abandoned
subtasks.

#### Scenario: Failed subtask cannot yield a complete plan

- **GIVEN** a plan whose loop exits with a subtask still failed
- **WHEN** the plan is finalized
- **THEN** the plan status is `failed`
- **AND** the unfinished subtask ids are recorded on the plan record

#### Scenario: Genuine completion is unaffected

- **GIVEN** a plan whose every subtask is `complete`
- **WHEN** the plan is finalized
- **THEN** the plan status is `complete`
- **AND** no unfinished-subtask marker is recorded

## MODIFIED Requirements

### Requirement: Plan JSON Schema

Plan artifacts MUST conform to `plan_schema.Plan`. Plan `status` MUST be one of
`planning`, `executing`, `complete`, `failed`, or `cancelled`, where `complete`,
`failed`, and `cancelled` are terminal.

A plan MAY carry `declined` (`clarify` or `refuse`) and `reason` in its metadata
when the planning step declined, and `unfinished_subtasks` when it was failed at
finalize with work outstanding.

#### Scenario: Cancelled plan is valid and terminal

- **GIVEN** a plan cancelled by a stop
- **WHEN** the plan file is read back
- **THEN** its status is `cancelled`
- **AND** it is treated as terminal, not as an incomplete execution

#### Scenario: Declined plan preserves its reason

- **GIVEN** a plan whose planning step returned `refuse`
- **WHEN** the plan file is read back
- **THEN** its status is `failed`
- **AND** its metadata carries the decline kind and the reason the bot spoke

### Requirement: Plan File Location and Lifecycle

A plan MUST be written when planning completes and archived when it reaches a
terminal state — `complete`, `failed`, or `cancelled`. A plan that never
executed because the planning step declined MUST still be written and archived,
so the decline is visible rather than vanishing.

#### Scenario: Plan written on Phase 1 completion

- GIVEN L3 returns a valid plan in Phase 1
- WHEN the plan is parsed and validated
- THEN it is written to `agent_plans/{bot_name}_current.json`
- AND the plan status is set to `executing`

#### Scenario: Plan archived on completion

- GIVEN a bot's plan is marked complete
- WHEN cleanup runs
- THEN the file is moved to `agent_plans/archive/{bot_name}_{timestamp}.json` with `status = complete`

#### Scenario: Plan archived on abandonment

- GIVEN a bot's plan is marked failed or cancelled
- WHEN cleanup runs
- THEN the file is moved to `agent_plans/archive/{bot_name}_{timestamp}.json` with `status = failed` or `status = cancelled`

#### Scenario: Declined plan is archived

- GIVEN a planning step that declined
- WHEN the plan is finalized
- THEN a failed plan carrying the decline is written and archived
- AND no subtask was ever dispatched
