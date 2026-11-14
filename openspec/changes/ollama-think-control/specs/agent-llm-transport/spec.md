# agent-llm-transport

## ADDED Requirements

### Requirement: Every Ollama chat request states whether the model may think

The agent SHALL send a top-level `think` boolean on every request it makes to
an Ollama `/api/chat` endpoint. The value SHALL come from a single setting,
`AIBOT_LLM_THINK`, read once in `agent/config.py`, and SHALL default to `false`.

The value SHALL be sent explicitly rather than omitted when thinking is off.
Omitting the field delegates the choice to the serving stack's default, which
is the condition that produced empty content when a thinking model was served
with a small `num_predict`.

`think` SHALL be a top-level field of the request body, not a key inside
`options`: Ollama reads it at the top level, and a value nested under `options`
is silently ignored.

#### Scenario: A planning call carries think=false by default

- **WHEN** the agent posts to `/api/chat` with `AIBOT_LLM_THINK` unset
- **THEN** the request body contains `"think": false` at the top level

#### Scenario: Thinking can be turned on from one place

- **WHEN** `AIBOT_LLM_THINK` is set to a true value and the agent posts to
  `/api/chat`
- **THEN** the request body contains `"think": true` at the top level
- **AND** no call site supplies its own literal value that could disagree with
  the setting

#### Scenario: A new call site cannot omit the field

- **WHEN** a developer adds another request to `/api/chat` in the agent
- **THEN** a test enumerates the agent's `/api/chat` request bodies and fails if
  any of them lacks a top-level `think` boolean

### Requirement: The eval runner states its own think value, independently

The output-eval runner SHALL send a top-level `think` boolean on its
`/api/chat` request. The value SHALL come from the eval config
(`evalconfig`), NOT from `AIBOT_LLM_THINK`: the runner is packaged standalone by
`evals/make-evals-configmap.sh`, which copies `output_evals` and its generated
config into a ConfigMap, so the agent's config module and environment are absent
from that pod. The runner is also the site that measures a candidate model, so it
must be able to enable thinking deliberately while the fleet keeps it off.

#### Scenario: The runner sends think from its own key

- **WHEN** the eval runner posts to `/api/chat`
- **THEN** the request body contains a top-level boolean `think` taken from the
  eval config
- **AND** changing `AIBOT_LLM_THINK` does not change the runner's request body

#### Scenario: A think-on run is refused before it starts, not after every case

- **WHEN** the runner is configured to think and the endpoint rejects a request
  carrying `think`
- **THEN** the endpoint precheck fails and the run exits non-zero with no report
- **AND** the failure is reported before the first case is scored, not as a run
  in which every case is unscorable

### Requirement: Thinking tokens do not consume the answer budget

A request that returns an empty `content` because thinking consumed the entire
`num_predict` budget SHALL be treated as a failed call, not as a well-formed
empty answer.

The agent SHALL distinguish an empty `message.content` accompanied by
`done_reason` of `length` from a genuinely empty answer, and SHALL report it as
an error at the call site that made the request.

#### Scenario: A truncated-to-nothing answer is an error

- **WHEN** Ollama returns `content: ""` with `done_reason: "length"`
- **THEN** the caller reports a failure naming the budget exhaustion
- **AND** the empty string is not parsed, scored or dispatched as a result

#### Scenario: A genuinely empty answer is still an empty answer

- **WHEN** Ollama returns `content: ""` with a `done_reason` other than `length`
- **THEN** the caller handles it as it does today, without reporting budget
  exhaustion

### Requirement: The gateway shim forwards the thinking control

The Ollama-compat shim in `llm-gateway` SHALL accept a `think` field on its chat
request and SHALL forward it into the body it sends to Ollama, following the
same path the shim already uses for `format`.

A client that sends `think` SHALL NOT have it silently dropped. The shim's
request model previously omitted the field, so the value was discarded before
the call left the gateway and no test detected it.

#### Scenario: think reaches the Ollama body through the gateway

- **WHEN** a client posts to the shim's `/api/chat` with `think: false`
- **THEN** the body the gateway sends to Ollama contains `think: false`
- **AND** a unit test asserts on the forwarded body, not on the shim's own
  parsed request object

#### Scenario: A client that omits think is unaffected

- **WHEN** a client posts to the shim without a `think` field
- **THEN** the gateway forwards no `think` key and the serving stack's default
  applies, so existing callers keep their current behaviour
