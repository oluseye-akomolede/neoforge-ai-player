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

`l3_planner.py:8-10` notes that when `llm-gateway` sits in front of Ollama,
requests still go through `OLLAMA_URL`; the eval must therefore take the
endpoint from config, never assume a hostname.

## The calls

Every row is a real `requests.post` to a model endpoint, with the line of the
call and the function it lives in. "Recorded?" asks whether
`agent/trajectory_log.py` stores the prompt and the verbatim response for it.

| # | call site | model | output | recorded? | how to decide it is correct |
|---|---|---|---|---|---|
| 1 | `l3_planner.call_plan` (`:398`, post `:410`) | local, `format: json`, `num_predict 1024` | a **plan**: `{task, subtasks:[{id, description, criteria, directives?}]}`, or `{kind: clarify|refuse, reason}` | **yes**, phase `plan`, plus `outcome` via `call_id` | (a) parse: JSON after fence-strip; (b) schema: `validate_plan_dict`; (c) every `directive.kind` in `_VALID_DIRECTIVE_KINDS`/`DIRECTIVE_KINDS` with params that pass `action_binding`; (d) achievable from the recorded `world_state_summary`; (e) outcome: `criteria_eval` said the final subtask was satisfied. A `clarify`/`refuse` is correct-on-purpose only when the case is labelled so. |
| 2 | `l3_planner.call_exec` (`:888`, post `:905`) | local, json, `num_predict 768` | **directives**: `{"directives":[{kind, ...}]}` | **yes**, phase `exec`, plus `outcome` | (a) non-empty list of dicts with `kind`; (b) every kind in the mod's `DIRECTIVE_KINDS` (`script_client.py:35`, the 37-value `DirectiveType` set — **not** the skill-leaf set); (c) params in `_ALLOWED_ARGS` (`action_binding.py:53`); (d) no directive beyond the subtask's scope; (e) `criteria_eval` satisfied the subtask. |
| 3 | `l3_planner.call_replan` (`:983`, post `:998`) | local, json | a **replacement subtask** | **yes**, phase `replan`, plus `outcome` | (a) schema of a `Subtask`; (b) differs from the failed one in a way that addresses `last_result_text`; (c) `criteria_eval` satisfied it on the next attempt. |
| 4 | `l3_planner.classify_message` (`:810`, post `:819`) | local | one word: `chat` or `task` | **no** | label agreement on a hand-labelled recorded set. This is the one place where the cheap deterministic check is "did the eval human label it chat or task". |
| 5 | `l3_planner.converse` (`:844`, post `:874`) | local | **chat text** (free prose) | **no** | no schema applies. Automatic checks that do: non-empty, within the `reply[:400]` bound the caller truncates to (`agent.py:1271`), no directive/JSON leakage, persona word list honoured. Everything else needs a judge — name it in the report (the local model itself is the only one available without an online dependency). |
| 6 | `l3_planner.partition_fleet` (`:758`, post `:770`) | local | `{bot: assignment}`, `"skip"` allowed | **no** | (a) parses to the declared shape; (b) every key is a real bot name in the fleet (the caller passes `bots`); (c) the union of assignments covers the order, or the uncovered bots are explicitly `skip`; (d) a per-bot judge only where a `skip` looks unjustified. |
| 7 | `l3_planner.refine_skill` (`:1095`, post `:1111`) | local | a repaired inline **skill spec** | **no** | the validator that rejected the first spec must accept this one — that is a deterministic check, not a judgement. |
| 8 | `brain.raw_generate` via `BotRunner._l3_regenerate` (`agent.py:2504`, post `brain.py:47`) | local | a JSON **array of primitives** replacing a failed step | **no** | (a) parses as a JSON array (the caller finds `[` … `]`); (b) each entry's `type` is one of the primitives the prompt advertises; (c) targets in the prompt's `VALID MINE/CRAFT/SMELT` lists; (d) the step re-executes and succeeds. |
| 9 | `brain.think` via `sessions.Session.run` (`sessions.py:46`, post `brain.py:11`) | local | one action call for container/craft sessions | **no** | the session goal is met within the session's step bound (`sessions.py:41`). Reachable from the `open_container`/`take`/`deposit` and `craft_session` actions (`agent.py:3117`,`:3122`). |
| 10 | `criteria_eval._strategy_l3_fallback` (`:277`, post `:286`), reached from `plan_orchestrator.py:599` | local | a yes/no criterion judgement | **no** | measured against the deterministic strategies that failed first: on the recorded set, compare its verdict with the `world_state`/`result_text` verdict where those exist, and with the labelled answer where they do not. **This one is scorer-shaped, not produce-shaped** — it judges output, so an eval of it measures the judge. Lowest priority. |
| 11 | `planner.decompose` (`:105`, post `:128`) | local | a list of steps from a player instruction | **no** | schema of a step; L4 fallback (`openai_brain.decompose`, `planner.py:160`) fires on failure, which is itself a measurable rate. |
| 12 | `planner.orchestrate` (`:247`, post `:285`) | local | per-bot step lists from a fleet order | **no** | schema; every bot named is a real profile. |
| — | `skill_author._deepseek_chat` (`:315`) | **DeepSeek** | skill code | n/a | **out of scope** — online model. |
| — | `l5.py:36` | **DeepSeek** | L5 output | n/a | **out of scope** — online model. |

## What this means for sourcing inputs

Rows 1–3 (`plan`, `exec`, `replan`) are the main planner and the only ones with a
recorded prompt, a recorded verbatim response **and** a recorded ground-truth
outcome. They are the 30-per-kind core of the eval set, and their inputs come
from `agent_trajectories/*.jsonl` by joining `call` records to `outcome` records
on `call_id`.

Rows 4–9 and 11–12 are logged nowhere. Their inputs have to come from real
recorded context another way:

- `converse` and `classify_message` inputs are player chat lines, which the
  agent already prints and keeps in `chat_history`; the bot's own pod log is the
  source, and the read command for it belongs in the run plan (the lead runs it;
  no exec is authorised from here).
- `partition_fleet` and `orchestrate` inputs are fleet orders with the bots'
  `infos` block (`agent.py:3930`), which is assembled from `api` state at call
  time and not persisted. Sourcing these means recording them through a
  read-only capture, or deferring those kinds out of the baseline and saying so
  in the report.
- `raw_generate` and `brain.think` inputs are a failed step or an observation;
  neither is persisted.

The honest split for the first baseline: **plan / exec / replan are scored from
recorded trajectory data with no new capture; chat and classify need one
read-only log read that the lead runs; fleet-partition, regenerate and
session-think are deferred with a stated reason.** Inventing a game state to
fill them in is exactly what the owner's "sourced from real recorded agent
context" rules out.
