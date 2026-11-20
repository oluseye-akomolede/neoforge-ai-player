# agent-llm-transport

## ADDED Requirements

### Requirement: The gateway passes the serving stack's completion accounting through

The llm-gateway's Ollama-compatible `/api/chat` shim SHALL pass the upstream
serving stack's `done_reason`, `eval_count` and the assistant `thinking` text
through to the client.

These are not decoration. `done_reason` is the only signal that distinguishes
"the model had nothing to say" from "the model spent its whole budget and was
cut off", and the two need opposite responses: the first is an empty answer,
the second is a failed call. A shim that reports `done: true` and drops
`done_reason` presents both as a successful empty reply, which is
indistinguishable to the caller from a model that declined to answer.

The passthrough SHALL be additive. No field currently present in the shim's
response envelope SHALL be removed or renamed.

#### Scenario: A reply cut off at the token limit reports done_reason length

- **WHEN** the upstream serving stack returns `done_reason: "length"` for a
  request made through the shim
- **THEN** the shim's response body contains `done_reason: "length"`
- **AND** the `eval_count` it reports is the upstream value, not a constant

#### Scenario: A normal reply reports its own done_reason

- **WHEN** the upstream serving stack returns `done_reason: "stop"`
- **THEN** the shim's response body contains `done_reason: "stop"`

#### Scenario: The gateway does not invent token counts

- **WHEN** the upstream response carries an `eval_count` greater than zero
- **THEN** the shim reports that value
- **AND** it does not report a hardcoded zero

#### Scenario: Thinking text is not discarded

- **WHEN** the upstream reply separates `thinking` from `content`
- **THEN** the shim's `message` object carries the `thinking` text when present
- **AND** omits the field when the upstream sent none, rather than reporting an
  empty string that a reader cannot tell from "thinking was off"

#### Scenario: Passthrough is additive

- **WHEN** any existing client reads a field it read before this change
- **THEN** that field is still present with the same name and meaning
- **AND** `_gateway`, `done`, `model`, `created_at`, `total_duration` and
  `message.content` are unchanged

### Requirement: A truncated answer is a failed call, not an empty answer

The agent's `answer_text` guard SHALL raise `TruncatedAnswer` when the model
stopped at the token limit with nothing to parse, and that guard SHALL be
reachable through the deployed transport.

An unreachable guard is worse than no guard: it reads in review as protection
that does not exist. Because `TruncatedAnswer` depends on `done_reason`, the
guard is only meaningful if the gateway passes `done_reason` through, so the
two requirements ship together.

#### Scenario: The guard fires on a truncated reply through the gateway

- **WHEN** a reply arrives through the gateway with empty content and
  `done_reason` equal to `length`
- **THEN** `answer_text` raises `TruncatedAnswer`
- **AND** the caller treats the call as failed rather than returning an empty
  string

#### Scenario: The guard does not fire on a genuine empty answer

- **WHEN** a reply arrives with empty content and `done_reason` equal to
  `stop`
- **THEN** `answer_text` returns the empty string
- **AND** does not raise `TruncatedAnswer`

#### Scenario: A missing done_reason is distinguishable from length

- **WHEN** a reply body has no `done_reason` key at all
- **THEN** the guard does not report truncation
- **AND** the absence is not silently treated as `length`
