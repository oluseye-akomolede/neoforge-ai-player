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

### Requirement: Every Call That Parses A Structured Reply Checks done_reason First

`answer_text` raises `TruncatedAnswer` only when the content is **empty**. A
reply cut mid-object has content, so it does not raise — it reaches the
parser, and the parser reports a syntax error. That error names the wrong
cause: it sends a reader to fix the prompt when the prompt was fine and the
token budget was not. Observed three times before this rule was written (the
PLAN call 2026-11-20 21:52Z, the SCRIPT call 2026-11-20 19:10Z, the exec
call 2026-11-21 21:55Z).

Therefore **every** call that asks the model for a structured reply and then
parses it MUST check `done_reason == "length"` **before** parsing, and MUST
report the result as a truncation rather than a parse error. The check belongs
to the call, not to `answer_text`, because only the call knows whether a cut
reply is unusable — for a prose call it is merely short.

The rule is stated once, generally, because stating it per call is what let it
recur: `call_plan` and `call_script` each learned it separately, and four other
`format: "json"` calls still did not check.

#### Scenario: A truncated structured reply is reported as a truncation

- **GIVEN** a call that requests `format: "json"`
- **WHEN** the reply body carries `done_reason` equal to `length`
- **THEN** the call MUST raise `TruncatedAnswer` (or an equivalent truncation
  error) naming the token limit
- **AND** it MUST NOT reach the JSON parser, so the failure cannot surface as
  a syntax error

#### Scenario: A truncated reply with no content is still caught

- **WHEN** the content is empty and `done_reason` is `length`
- **THEN** the existing `answer_text` guard satisfies this requirement
- **AND** the call's own check MUST NOT turn that into a different error

#### Scenario: A complete reply is unaffected

- **WHEN** `done_reason` is `stop` and the reply parses
- **THEN** the call behaves exactly as before and reports no truncation

### Requirement: Each Call's Token Budget Is A Named Constant Sized By Measurement

Each LLM call's `num_predict` MUST be a named module constant, not a literal at
the request site, and the constant MUST carry a comment recording the
`eval_count` that justified it. A literal records no reason and cannot be
reviewed as a number.

Changing one call's constant MUST NOT change any other call's budget: the
constants are per call, and the existing rule in `l3_planner.py` (the SCRIPT
call's block, which states that changing it must not change any other call's
`num_predict`) is the model to follow rather than a single shared knob.

#### Scenario: A call's budget can be traced to a measurement

- **WHEN** a reader opens a call's `num_predict` constant
- **THEN** its comment MUST state the observed `eval_count` (or equivalent
  measurement) that the value was chosen from

#### Scenario: Budgets are independent

- **WHEN** one call's constant is changed
- **THEN** no other call's requested `num_predict` changes
