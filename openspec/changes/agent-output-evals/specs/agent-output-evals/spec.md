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

### Requirement: The Primary Measurement Is a Replay of Recorded Inputs

The eval MUST re-send each case's recorded input (`prompt_system` and
`prompt_user`, verbatim from the trajectory log) to the configured model, and
score the **new** output. A case that only scores the recorded response is not a
replay case; the two are reported separately.

The corpus location MUST come from `AIBOT_TRAJECTORY_DIR` (or the agent's own
config), never from a path hardcoded in the eval.

#### Scenario: A replay case
- **WHEN** a replay case runs
- **THEN** the request body carries the recorded `prompt_system` and
  `prompt_user` unchanged
- **AND** the score is computed over the model's new response, not the recorded
  `response_raw`

#### Scenario: The corpus directory is configured
- **WHEN** the eval locates its inputs
- **THEN** it resolves the directory from configuration
- **AND** it does not assume any concrete mount path

### Requirement: A Second, Outcome-Attributed Score Is Reported and Labelled by Strength

Separately from the replay score, the eval MUST report what the recorded
responses achieved in play, and MUST label each kind's attribution strength.

`exec` is attributed per call: each `call` record joins its `outcome` record on
`call_id`, and `criteria_eval`'s `satisfied` is the label.

`plan` and `replan` are attributed at **plan level**: `log_outcome` has one call
site, on `exec_call_id`, so neither has an `outcome` record; a `plan`/`replan`
call record carries `plan_ref`, and the terminal `plan_close` record for that
`plan_ref` carries the plan's `status`. That label is weaker — a plan that
closed `complete` does not mean every subtask it proposed was good — so the
report MUST present it as a plan-level rate and MUST NOT present it as a
per-call rate.

A case whose label cannot be derived MUST NOT be counted as a success.

#### Scenario: An exec case is attributed per call
- **WHEN** an `exec` case's outcome is looked up
- **THEN** it is joined on `call_id`
- **AND** the `no_label` bucket counts the `call` records with no `outcome`

#### Scenario: A plan case is attributed at plan level
- **WHEN** a `plan` or `replan` case's outcome is looked up
- **THEN** it is joined on `plan_ref` to that plan's `plan_close` `status`
- **AND** the report labels the resulting rate plan-level, not per-call

### Requirement: Eval Cases Come From Real Recorded Agent Context

Cases MUST be sourced from data the agent really produced, and the report MUST
say where each kind's cases came from.

Secret-like values in a recorded input (API keys, tokens, DSNs, player names)
MUST be redacted in the committed eval set, and the redaction MUST be reversible
only locally — the committed file never carries the raw value.

#### Scenario: A case is a recorded input, not a constructed one
- **WHEN** a case is inspected
- **THEN** its `prompt_system`, `prompt_user` and `world_state` are verbatim
  from a recorded trajectory call
- **AND** its expected properties were fixed before the run, not after seeing
  what the model did

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

The corpus this change was sized against holds, per kind: `exec` 1545 `call`
records with 1530 outcomes, `plan` 299, `replan` 271, and 359 `plan_close`
records, all on the bot's PVC. Split by model era, the current model
(`qwen3-coder:30b`) holds `exec` 148, `plan` 37 and `replan` **21** — so the
30-case minimum cannot be met from the current era for `replan`.

The sample MUST be stratified across the bots and across the corpus's model
eras, and MUST prefer inputs recorded with the model the agent runs today. The
report MUST state how many cases come from each era, because a baseline drawn
from an older model is not a baseline for today's.

**Precedence: reach 30, current era first.** In a replay eval every scored
output comes from the configured model (today's); only the **input** has an
era. So the target is 30 cases per kind, taken from current-era
(`qwen3-coder:30b`) inputs first, and any shortfall filled from older-August
inputs -- `replan` takes 21 current-era plus 9 August. The report MUST give,
for each kind, the pass rate **overall and split by input era**, with the `n`
for each. When a kind's older-input rate differs markedly from its
current-input rate EXCEEDS 15 percentage points, the report MUST flag it as a
possible prompt-format drift between the eras rather than a difference in model
quality. "Marked" means that threshold, not an implementer's judgement; when a
kind's era split has fewer than 10 cases on either side the flag is withheld and
the small `n` is stated instead, because a 15-point gap over 9 cases is noise.

#### Scenario: The set is sized
- **WHEN** the eval set is built
- **THEN** each of `plan`, `exec` and `replan` carries at least 30 cases counted
  from the corpus, or the report states how many it carries and why that is fewer

#### Scenario: A kind is short of 30 in the current era
- **WHEN** a kind has fewer than 30 current-era cases (today: `replan`, 21)
- **THEN** the sample is completed from older-era inputs to reach 30
- **AND** the report gives that kind's overall rate and its rate per input era,
  each with its `n`
- **AND** it flags a gap over 15 points between the era rates as possible
  prompt-format drift, not model quality, withholding the flag when either era
  holds fewer than 10 cases and stating the small `n` instead

#### Scenario: The sample's provenance is stated
- **WHEN** the report is written
- **THEN** it gives the number of cases per kind drawn from each model era
- **AND** it names the model the live agent runs, taken from config

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

The trajectory corpus MUST be counted before the report is written: per kind,
the number of `call` records, the number joined to a label, and the distinct
days the corpus covers.

#### Scenario: The corpus is counted
- **WHEN** a report is written
- **THEN** it states, per kind, the `call` record count, the joined count, and
  the distinct days covered
- **AND** the replay rate and the outcome-attributed rate are reported as two
  separate numbers, never blended into one

#### Scenario: A failing case is inspectable
- **WHEN** a kind has any failing case
- **THEN** the report shows the failing case's input, the raw model output, and
  the named check that rejected it

#### Scenario: A dead instrument yields no verdict
- **WHEN** the trajectory log is absent or unreadable, or the endpoint does not
  answer
- **THEN** the run exits non-zero and writes no pass rate
- **AND** it does not report "0 failures" in place of "not measured"
