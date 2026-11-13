# Inventory: where the agent asks a model for something

Step 1, item 1. Read from source at `70ab193` (branch `minecraft-wt-deepseek`).

## Which model each call really uses

- `OLLAMA_URL` (`agent/config.py:83`, default `http://localhost:11434`) — **the
  local model**. The model tag is not a config constant: it comes from each
  bot's profile, `profile.get("model", "qwen3-coder:30b")`
  (`agent/agent.py:183`), and all five shipped profiles pin
  `"qwen3-coder:30b"` (`agent/profiles/{scout,forge,mystic,tiller,axiom}.json:3`).
  The eval config's `model` and `endpoint` are what make a rerun against another
  model possible; nothing in the agent needs to change for that.
- `DEEPSEEK_URL` (`agent/config.py:95`, default `https://api.deepseek.com`) with
  `DEEPSEEK_MODEL` (`:96`, default `deepseek-v4-flash`) — **not local**, and not
  reachable from a local-only eval run.
- **The same local endpoint also serves a second model**: semantic memory
  embeds through `{OLLAMA_URL}/api/embeddings` with
  `EMBED_MODEL = "nomic-embed-text"` (`semantic_memory.py:24`, call at `:76`),
  constructed per bot at `agent.py:242` and reached from five paths in
  production (`_embed` at `:90`, `:139`, `:247`, `:274`, `:396`). It is a real
  local-endpoint call, so "the local model is qwen3-coder:30b" is only true of
  the generation calls. `nn_compressor` is a separate URL
  (`NN_COMPRESSOR_URL`, `config.py:84`) that defaults to `""`, so it is off
  unless configured.

## Excluded: the embedding model

`semantic_memory._embed` is **out of scope for this eval**, and named here so
that a reader does not conclude the local endpoint serves only qwen:

- its output is a vector, not an answer anyone reads, so there is no
  "is this decision correct" judgement to make — the only automatic check is
  retrieval quality (does a query return the memory that should match), which is
  a memory-system test, not a model-output eval;
- the model is fixed (`nomic-embed-text`) and is not the model any bot plans,
  acts or speaks with, so it cannot enter a baseline whose yardstick is the
  LoRA fine-tune of the planner;
- the failure mode that matters (a degraded embedder) shows up as bad recalls,
  which the agent's own memory paths already exercise.

If the owner wants retrieval evaluated, it is a separate change with a
different corpus and a different metric, not a kind in this one.

`l3_planner.py:8-10` notes that when `llm-gateway` sits in front of Ollama,
requests still go through `OLLAMA_URL`; the eval must therefore take the
endpoint from config, never assume a hostname.

## The calls

Every row is a real `requests.post` to a model endpoint, with the line of the
call and the function it lives in. "Recorded?" asks whether
`agent/trajectory_log.py` stores the prompt and the verbatim response for it.

| # | call site | model | output | recorded? | how to decide it is correct |
|---|---|---|---|---|---|
| 1 | `l3_planner.call_plan` (`:398`, post `:410`) | local, `format: json`, `num_predict 1024` | a **plan**: `{task, subtasks:[{id, description, criteria, directives?}]}`, or `{kind: clarify|refuse, reason}` | **partly** — phase `plan` records the prompt and the response, but **no `outcome`**: `log_outcome` is joined on `exec_call_id` only (`plan_orchestrator.py:616-620`), and `call_plan` returns a `Plan`, not its `call_id` | (a) parse: JSON after fence-strip; (b) schema: `validate_plan_dict`; (c) every `directive.kind` in `_VALID_DIRECTIVE_KINDS`/`DIRECTIVE_KINDS` with params that pass `action_binding`; (d) achievable from the recorded `world_state_summary`; (e) outcome: `criteria_eval` said the final subtask was satisfied. A `clarify`/`refuse` is correct-on-purpose only when the case is labelled so. |
| 2 | `l3_planner.call_exec` (`:888`, post `:905`) | local, json, `num_predict 768` | **directives**: `{"directives":[{kind, ...}]}` | **yes**, phase `exec`, plus `outcome` | (a) non-empty list of dicts with `kind`; (b) every kind in the mod's `DIRECTIVE_KINDS` (`script_client.py:35`) — see the 35-vs-37 gap below; (c) params in `_ALLOWED_ARGS` (`action_binding.py:53`); (d) no directive beyond the subtask's scope; (e) `criteria_eval` satisfied the subtask. |
| 3 | `l3_planner.call_replan` (`:983`, post `:998`) | local, json | a **replacement subtask** | **partly** — phase `replan` records prompt and response; no `outcome` is ever written for it (`plan_orchestrator.py:1136` uses the returned `Subtask` only) | (a) schema of a `Subtask`; (b) differs from the failed one in a way that addresses `last_result_text`; (c) `criteria_eval` satisfied it on the next attempt. |
| 4 | `l3_planner.classify_message` (`:810`, post `:819`) | local | one word: `chat` or `task` | **no** | label agreement on a hand-labelled recorded set. This is the one place where the cheap deterministic check is "did the eval human label it chat or task". |
| 5 | `l3_planner.converse` (`:844`, post `:874`) | local | **chat text** (free prose) | **no** | no schema applies. Automatic checks that do: non-empty, within the `reply[:400]` bound the caller truncates to (`agent.py:1271`), no directive/JSON leakage, persona word list honoured. Everything else needs a judge — name it in the report (the local model itself is the only one available without an online dependency). |
| 6 | `l3_planner.partition_fleet` (`:758`, post `:770`) | local | `{bot: assignment}`, `"skip"` allowed | **no** | (a) parses to the declared shape; (b) every key is a real bot name in the fleet (the caller passes `bots`); (c) the union of assignments covers the order, or the uncovered bots are explicitly `skip`; (d) a per-bot judge only where a `skip` looks unjustified. |
| 7 | `l3_planner.refine_skill` (`:1095`, post `:1111`) | local | a repaired inline **skill spec** | **no** | the validator that rejected the first spec must accept this one — that is a deterministic check, not a judgement. |
| 8 | `brain.raw_generate` via `BotRunner._l3_regenerate` (`agent.py:2504`, post `brain.py:47`) | local | a JSON **array of primitives** replacing a failed step | **no** | (a) parses as a JSON array (the caller finds `[` … `]`); (b) each entry's `type` is one of the primitives the prompt advertises; (c) targets in the prompt's `VALID MINE/CRAFT/SMELT` lists; (d) the step re-executes and succeeds. |
| 9 | `brain.think` via `sessions.Session.run` (`sessions.py:46`, post `brain.py:11`) | local | one action call for container/craft sessions | **no** | the session goal is met within the session's step bound (`sessions.py:41`). Reachable from the `open_container`/`take`/`deposit` and `craft_session` actions (`agent.py:3117`,`:3122`). |
| 10 | `criteria_eval._strategy_l3_fallback` (`:277`, post `:286`), reached from `plan_orchestrator.py:599` | local | a yes/no criterion judgement | **no** | measured against the deterministic strategies that failed first: on the recorded set, compare its verdict with the `world_state`/`result_text` verdict where those exist, and with the labelled answer where they do not. **This one is scorer-shaped, not produce-shaped** — it judges output, so an eval of it measures the judge. Lowest priority. |
| 11 | `planner.decompose` (`:105`, post `:128`) | local | a list of steps from a player instruction | **no** | schema of a step; L4 fallback (`openai_brain.decompose`, `planner.py:160`) fires on failure, which is itself a measurable rate. |
| 12 | `planner.orchestrate` (`:247`, post `:285`) | local | per-bot step lists from a fleet order | **no** | schema; every bot named is a real profile. |
| — | `semantic_memory._embed` (`:76`, `nomic-embed-text`) | **local, different model** | an embedding vector | n/a | **out of scope** — see "Excluded: the embedding model" above. |
| — | `skill_author._deepseek_chat` (`:315`) | **DeepSeek** | skill code | n/a | **out of scope** — online model. |
| — | `l5.py:36` | **DeepSeek** | L5 output | n/a | **out of scope** — online model. |

## Two directive-kind sets, and the 35-vs-37 gap

`exec` scoring uses the **mod's** `DIRECTIVE_KINDS` (`script_client.py:35`), not
the agent's `_VALID_DIRECTIVE_KINDS` (`l3_planner.py:204`), because the mod is
what executes a directive: a kind the mod rejects never runs, whatever the agent
thought.

The reviewer checked this by diffing both sets against
`DirectiveType.java` in both directions: `DIRECTIVE_KINDS` is exactly the mod's
37, with zero drift; `_VALID_DIRECTIVE_KINDS` holds 35 and is missing
`AREA_LOOT` and `SKILL`. So an eval scored against the agent's set would reject
two directives the mod actually executes. Scoring against the mod's set is the
only choice that measures what the bot can do.

**That gap is a live agent bug, independent of this eval** — whatever the agent
validates against is what the model is steered toward, and it currently cannot
name two real directive kinds. It belongs in its own queue row, not in this
change.

## The corpus, measured

Counted by the lead live over every file in the pod's
`/opt/aibot-agent/data/agent_trajectories` (2026-08-14 .. 2026-11-13):

| phase | `call` records | outcome-attributed | label source |
|---|---|---|---|
| exec | 1545 | 1530 | `call_id` -> `outcome` |
| plan | 299 | 0 | `plan_ref` -> `plan_close.status` (359 plan_close records) |
| replan | 271 | 0 | `plan_ref` -> `plan_close.status` |

Plan and replan together give 570 recorded inputs, so both are testable as a
**replay** eval even though neither has an `outcome` record.

By model, the corpus spans two eras, and the split matters for a yardstick of
today's behaviour: `qwen2.5:32b-instruct` (August) accounts for exec 1395 /
plan 262 / replan 250, and `qwen3-coder:30b` (September and November) for exec
148 / plan 37 / replan 21. **The live model is `qwen3-coder:30b`**; the sampling
prefers its inputs and the report states how many cases come from the August
model.

The directory is read from `AIBOT_TRAJECTORY_DIR` (env, or config), never
hardcoded — the layout is the deployment's, not this document's.

Record keys, as measured: call records carry `bot call_id model parse_error
parsed phase plan_ref prompt_system prompt_user response_raw subtask_id ts`;
outcome records add `reason satisfied strategy`; plan_close carries `plan_ref
status subtasks_complete subtasks_total task`.

## What this means for sourcing inputs

Rows 1–3 (`plan`, `exec`, `replan`) are the main planner and the core of the
eval set.

**Replay (primary).** Every one of the 2115 recorded inputs across the three
kinds can be replayed against the configured model and scored automatically on
the new output: parse ok, kinds in the mod's accepted set, params valid, a plan
non-empty and composed only of valid kinds. That measurement needs no outcome
join, which is why all three kinds are testable even where attribution is thin.

**Outcome attribution (secondary, and weaker for plan/replan).** `log_outcome`
is called once in the whole repo (`plan_orchestrator.py:616`), always with
`call_id=exec_call_id` and `phase="exec"`; `call_plan` returns a `Plan` and
`call_replan` a `Subtask`, so neither surfaces the `call_id` its record was
written under. `exec` therefore gets a true per-call label from `criteria_eval`;
`plan` and `replan` get a plan-level one through `plan_ref` -> `plan_close`'s
`status`. A plan that closed `complete` does not mean every subtask it proposed
was good, so that rate is reported as plan-level and never as per-call.

The other kinds are logged nowhere, and their inputs have to come from real
recorded context another way:

- `converse` and `classify_message` inputs are player chat lines, which the
  agent keeps in `chat_history` and prints; the bot's own pod log is the source,
  and the read command belongs in the run plan (the lead runs it; no exec is
  authorised from here).
- `partition_fleet` and `orchestrate` inputs are fleet orders with the bots'
  `infos` block (`agent.py:3930`), assembled from `api` state at call time and
  not persisted. Sourcing them means a read-only capture, or deferring those
  kinds out of the baseline and saying so.
- `raw_generate` and `brain.think` inputs are a failed step or an observation;
  neither is persisted.

The honest split for the first baseline: **plan, exec and replan are replayed
from recorded inputs and scored automatically; exec additionally carries a
per-call outcome label and plan/replan a plan-level one, labelled as such; chat
and classify need one read-only log read that the lead runs; fleet-partition,
regenerate and session-think are deferred with a stated reason.** Inventing a
game state to fill them in is exactly what the owner's "sourced from real
recorded agent context" rules out.
