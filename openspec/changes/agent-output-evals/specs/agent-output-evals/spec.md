## ADDED Requirements

### Requirement: Every Local-Model Output Kind Is Named and Scored

The eval capability MUST score each kind of output the local model produces.
The kinds are the ones the agent asks for: `plan`, `exec`, `replan`, `classify`,
`converse`, `partition`, `skill_refine`, `regenerate`. The report MUST NOT
aggregate them into a single number without also giving the per-kind rate: a
model that plans correctly and chats badly is two facts, not one.

Calls to an endpoint other than the configured local endpoint (the DeepSeek
skill author and L5) MUST NOT be counted in the local-model baseline.

#### Scenario: A kind is scored
- **WHEN** the eval runs
- **THEN** the report carries a pass rate for that kind, computed over that
  kind's cases only
- **AND** the pass rate names the checks that decided it

#### Scenario: A kind is deferred
- **WHEN** a kind has no recorded real inputs available
- **THEN** it is listed in the report as deferred, with the reason
- **AND** it is not scored from invented inputs and is not omitted silently

### Requirement: Eval Cases Come From Real Recorded Agent Context

Each eval case MUST consist of a fixed recorded input — the prompt actually
sent and the game-state snapshot actually supplied — and the properties its
answer must have. Cases MUST be sourced from data the agent really produced, and
the report MUST say where each kind's cases came from.

For `plan`, `exec` and `replan` the source is the agent's trajectory log
(`agent/trajectory_log.py`). `exec` cases join each `call` record to its
`outcome` record on `call_id`. `plan` and `replan` have no `outcome` record —
`log_outcome` has one call site, on `exec_call_id` — so their attribution is
**plan-level**: a `plan`/`replan` call record carries `plan_ref`, and the
terminal `plan_close` record for that `plan_ref` carries the plan's `status`.
That attribution is weaker than `exec`'s: a plan that closed `complete` does not
mean every subtask it proposed was good, so the spec asks for the plan-level
rate and does not claim a per-call one. The report MUST name which derivation a
case used, and a case whose label cannot be derived MUST NOT be counted as a
success.

Secret-like values in a recorded input (API keys, tokens, DSNs, player names)
MUST be redacted in the committed eval set, and the redaction MUST be reversible
only locally — the committed file never carries the raw value.

#### Scenario: A case is a recorded input, not a constructed one
- **WHEN** a case is inspected
- **THEN** its `prompt_system`, `prompt_user` and `world_state` are verbatim
  from a recorded trajectory call
- **AND** its expected properties were fixed before the run, not after seeing
  what the model did

#### Scenario: No outcome means no credit
- **WHEN** an `exec` trajectory `call` record has no matching `outcome` record,
  or a `plan`/`replan` case's label cannot be derived from the plan archive
- **THEN** that case is excluded from the pass-rate denominator and counted in
  a separate `no_label` bucket

### Requirement: Scoring Is Automatic Where an Automatic Check Exists

A case MUST be scored by a deterministic check when one exists. In order of
preference: parse validity; schema validity against the real validator
(`validate_plan_dict`, `action_binding._ALLOWED_ARGS`); every directive kind in
the mod's `DIRECTIVE_KINDS`; the plan or directive set achievable from the
recorded state; the recorded `criteria_eval` outcome.

A judge model MUST be used only for a kind where no automatic check decides the
case — in practice `converse` — and the report MUST name the judge, its endpoint
and its prompt.

The directive surface an `exec` case is scored against MUST be the **mod's**
`DIRECTIVE_KINDS` (`script_client.py:35`), not the agent's narrower
`_VALID_DIRECTIVE_KINDS` (`l3_planner.py:204`), because the mod is what
executes: a directive the mod accepts is valid whether or not the agent's own
list names it.

#### Scenario: A check exists
- **WHEN** a case's kind has an automatic check
- **THEN** it is scored by that check and the judge is not consulted

#### Scenario: The judge is used
- **WHEN** a case is judged
- **THEN** the report names the judge model, endpoint and the scoring prompt
- **AND** the judged rate is reported separately from the automatic rates

### Requirement: The Main Planner Has At Least 30 Cases Per Kind

The eval set MUST carry at least about 30 cases for each of `plan`, `exec` and
`replan` **when the recorded corpus holds that many**. The set is sized from a
count of what the corpus actually contains, taken before the number is
promised: a kind whose corpus cannot yield 30 MUST be reported with the count it
has and the reason, and MUST NOT be filled with constructed cases or padded from
another bot's unrelated calls.

#### Scenario: The set is sized
- **WHEN** the eval set is built
- **THEN** each of `plan`, `exec` and `replan` carries at least 30 cases counted
  from the corpus, or the report states how many it carries and why that is fewer

### Requirement: Rerunning Against Another Model Changes Config Only

The eval MUST be runnable from a CLI against a different endpoint and model
without editing code. The endpoint and model URL MUST come from a config file
that also sets the request timeout and the per-call concurrency.

The runner MUST make its calls one at a time by default, because the local GPUs
are shared with live bots; a concurrency above one MUST be an explicit setting.

#### Scenario: A rerun against a new model
- **WHEN** the config's `endpoint` or `model` changes
- **THEN** the same eval set runs unmodified against the new target
- **AND** the report records the endpoint and model it ran against, taken from
  the config that was actually read

### Requirement: The Report Gives Per-Kind Pass Rates and Failure Examples

The report MUST be a file that carries: the endpoint and model, the case counts
per kind, the pass rate per kind, the deferred kinds with reasons, and for each
kind at least a few failing cases with their input, the model's output and the
check that rejected it.

A report MUST NOT be produced from a run that could not read its inputs: a
missing trajectory file, an unreachable endpoint or an empty case set STOPS the
run with a non-zero exit, rather than reaching a verdict.

The trajectory corpus MUST be counted before the report is written, and the
corpus's durability MUST be reported with the result: the trajectory directory is
container-local unless `AIBOT_TRAJECTORY_DIR` points inside the mounted volume,
so a restart destroys it. A run MUST NOT present a rate over a corpus whose
survival it has not checked.

#### Scenario: The corpus is counted
- **WHEN** a report is written
- **THEN** it states the number of `call` records, the number joined to a label,
  and the number of distinct days the corpus covers
- **AND** it states whether the trajectory directory is on the persistent volume

#### Scenario: A failing case is inspectable
- **WHEN** a kind has any failing case
- **THEN** the report shows the failing case's input, the raw model output, and
  the named check that rejected it

#### Scenario: A dead instrument yields no verdict
- **WHEN** the trajectory log is absent or unreadable, or the endpoint does not
  answer
- **THEN** the run exits non-zero and writes no pass rate
- **AND** it does not report "0 failures" in place of "not measured"
