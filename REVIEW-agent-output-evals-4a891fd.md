# Review — openspec/changes/agent-output-evals at `4a891fd`

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~16:45Z.
**Verdict: NOT PASS — the spec's central sourcing premise is wrong for two of the
three core kinds, which moves the owner's 11-14 18:00Z deadline.**

Read the change at `4a891fd` (branch `minecraft-wt-deepseek`, tree clean).
`openspec validate --strict` valid. Everything below was checked at source.

---

## (b) The exec kind set — CORRECT, and the reasoning is better than the spec states

The builder asked whether scoring `exec` against the mod's `DIRECTIVE_KINDS`
(`script_client.py:35`) rather than the agent's `_VALID_DIRECTIVE_KINDS` is right.

**It is right, and I verified the drift is real rather than assuming it:**

- `DIRECTIVE_KINDS` = 37 unique names, **exactly equal** to
  `DirectiveType.java` — I diffed both directions, zero names in either set and
  not the other.
- `_VALID_DIRECTIVE_KINDS` (`l3_planner.py`) = **35** — it is missing
  **`AREA_LOOT`** and **`SKILL`**, both of which the mod accepts.

So scoring against the agent-side set would reject two directives the mod
actually executes, and the pass rate would understate the model. The builder's
ground (the mod is what executes) is the correct one.

**But the spec under-states its own justification.** The spec says only "every
directive kind in the mod's `DIRECTIVE_KINDS`" (`spec.md:58`). A future reader
will ask why not the agent's list, and the answer — the agent's list is 2 short
— is a fact worth one clause, because that gap of 2 is a *live bug* in the agent
independent of this eval. Worth naming: either the agent's validator is wrong,
or the mod accepts directives the agent is forbidden to emit, and that is worth
a follow-up row.

## (a) The inventory — TWO REAL LOCAL CALL SITES ARE MISSING

I enumerated every `requests.post` in `agent/` (21 sites) and classified each
against `OLLAMA_URL` / `DEEPSEEK_URL` / other. The inventory's 12 + 2 excluded
is **not** the whole set:

**Miss 1 — `semantic_memory._embed` (`semantic_memory.py:76`).** Posts to
`{ollama_url}/api/embeddings` with `EMBED_MODEL = "nomic-embed-text"`
(`:24`). `ollama_url` is `OLLAMA_URL` (`agent.py:242` constructs
`sem.SemanticMemory(self.name, OLLAMA_URL, PG_DSN)`), so **this is a call to the
local endpoint, in production, on every `store`/`recall`/`store_shared`/**
`search`** (five call sites at `:90`, `:139`, `:247`, `:274`, `:396`).

This is a genuine output kind of the local serving stack, and it is a **different
model** from qwen — so it is not covered by the "the local model is qwen3-coder"
framing at `INVENTORY.md:7-13` or `proposal.md:9-10`. Whether to score it is a
judgement call (an embedding is not "an answer" a human reads), but the inventory
must **name it and say it is out of scope deliberately**, not omit it. As written,
a reader concludes the local endpoint serves only qwen.

**Checked and correctly excluded:** `nn_compressor.py:62` posts to
`NN_COMPRESSOR_URL`, which defaults to `""` (`config.py:84`) — disabled, and it
is a compressor service, not a model. `skill_author.py:63` and `l5.py:35` are
`DEEPSEEK_URL`, correctly out of scope. `script_tick.py:203`, `api.py:34`,
`telemetry.py:37`, `plan_orchestrator.py:1016` are mod-API calls, not models.

## (c) The 30-per-kind requirement — NOT REACHABLE AS WRITTEN FOR PLAN AND REPLAN

This is the finding that matters for the deadline.

`INVENTORY.md:47-51` and `proposal.md:39-46` both state that **plan, exec and
replan** are recorded with *"a recorded prompt, a recorded verbatim response and
a recorded ground-truth outcome"*, joined by `call_id`. **That is true for exec
only.**

`trajectory_log.log_outcome` has exactly **one call site in the whole agent** —
`plan_orchestrator.py:616` — and it is:

```python
    if exec_call_id:
        trajectory_log.log_outcome(
            call_id=exec_call_id, bot=plan.bot, phase="exec", ...
```

`exec_call_id` is the only `*_call_id` that exists: `grep` for
`plan_call_id|replan_call_id` across `agent/*.py` returns **nothing**. So:

- **`exec`**: has call records and a `criteria_eval` outcome joined by `call_id`.
  **The 30-per-kind requirement is satisfiable for exec** (subject to data volume).
- **`plan`**: 4 `log_call` sites write `phase="plan"` records and return a
  `call_id`, but **no outcome is ever written against it**. The only plan-level
  ground truth is `log_plan_close` (3 sites, `plan_orchestrator.py:284,302,382`),
  which is keyed by `plan_ref` — *not* `call_id` — and carries a terminal plan
  status, not a per-call verdict.
- **`replan`**: same — 4 `log_call` sites, no outcome writer at all, and no
  plan-level correlate either.

**Consequences for the spec as written:**

1. `spec.md:32-35` ("For `plan`, `exec` and `replan` the source is the trajectory
   log … joining each `call` record to its `outcome` record") describes a join
   that **cannot be performed for two of the three kinds**. The spec as written
   is unsatisfiable for plan and replan.
2. `spec.md:48-51` ("No outcome means no credit") would, applied faithfully,
   put **every** plan and replan case in `no_outcome` — i.e. the two kinds would
   score nothing while appearing to be in scope. That is the "not measured
   reported as measured" failure the same spec forbids two scenarios later.
3. `spec.md:74-83` (30 per kind) is therefore **not testable as written** for
   plan and replan, and the honest answer to the builder's question (c) is: the
   requirement is correctly written *as a requirement* (it says "or report the
   shortfall"), but it is premised on data the agent does not record.

**This is fixable, and cheaply, but it changes the step-2 plan.** Options, in the
order I would take them:

- **(i) Redefine plan/replan ground truth as plan-level, not call-level.** A
  `plan` case is correct if its subtasks were later completed
  (`plan_close.status`), joined on `plan_ref`. This uses data that *does* exist
  and stays honest. It weakens the per-call attribution (a plan with one bad
  subtask is a fail), which must be stated in the spec, not glossed.
- **(ii) Restrict the 30-per-kind core to `exec` alone**, and list plan/replan as
  deferred-with-reason in the first baseline. Honest and delivers a number by the
  deadline, but narrows the headline.
- **(iii) Record plan/replan outcomes in the agent.** Correct long-term and the
  wrong thing to do this week — it changes production behaviour, which
  `proposal.md:28-32` explicitly says this change must not do.

**My recommendation: (i) plus (ii)'s honesty.** Use `plan_ref`-joined plan-level
outcomes for plan/replan, state plainly in the spec that the attribution is
weaker than exec's, and if the recorded volume still yields fewer than 30, report
the shortfall rather than inventing cases. The owner gets a real number for all
three kinds with a stated caveat, rather than a spec that cannot be executed.

## A separate, time-sensitive problem: the trajectory log is not on a volume

`trajectory_log.py:33-38` resolves its directory as
`dirname(PROFILE_PATH)/agent_trajectories`. With the shipped
`PROFILE_PATH=/opt/aibot-agent/profiles/default.json` (`agent.env.example:6`),
that is **`/opt/aibot-agent/profiles/agent_trajectories`** — and the agent's only
volume (`deploy/agent-deployment.yaml:34-43`) mounts the PVC at
**`/opt/aibot-agent/data`**. `AIBOT_TRAJECTORY_DIR` is set in no manifest (grep:
zero hits).

So the trajectory log is written to the **container filesystem** and is lost on
every pod restart. Logging is unconditional (12 call sites, no enable flag), so
data has been written — but a restart, a rollout or a node eviction since 11-20
would have destroyed it. Combined with the rollout the lead ran this morning,
**the recorded plan/exec/replan corpus may be empty or much thinner than the
"30 per kind" premise assumes**, and that is not knowable from here without a pod
read.

I am not asserting the data is gone — I cannot read the pod. I am asserting that
the spec's sizing rests on a corpus with no durability guarantee, and that the
first thing step 2 should do is measure how many call/outcome pairs actually
exist before any kind is promised 30. If the number is small, that is the answer
to the owner's deadline, and it is better said on Thursday than discovered on
Friday.

## Everything else — sound

- **Record shape matches the spec.** `log_call` writes `prompt_system`,
  `prompt_user`, `world_state_summary`, `response_raw`, `parsed`, `parse_error`,
  `plan_ref`, `subtask_id`, `call_id`; `log_outcome` writes `satisfied`,
  `strategy`, `reason`, `call_id`. The join key is real.
- **The DeepSeek exclusions are correct** (`skill_author`, `l5`).
- **The model-tag-in-profile point is correct** (`agent.py:183`, five profiles
  pin `qwen3-coder:30b`; nothing in `config.py` names it).
- **The spec's dead-instrument requirement** (`spec.md:116-120`: absent log →
  non-zero exit, no "0 failures") is well phrased and is exactly the right
  instinct given the volume risk above.
- **Deferral is honest throughout.** The spec's "a kind is deferred" scenario and
  the inventory's stated split are the right posture; my findings are about
  *which* kinds can be sourced, not about the posture.

## Summary

| Question | Answer |
|---|---|
| (a) inventory complete / correctly kinds? | **No** — `semantic_memory._embed` (local, `nomic-embed-text`, 5 call paths) is missing |
| (b) exec scored against the mod's kind set? | **Yes, correct** — and stronger than the spec says: the agent's set is 2 short (`AREA_LOOT`, `SKILL`) |
| (c) 30-per-kind testable as written? | **Not for plan/replan** — outcomes are written only for exec (`exec_call_id`); the call→outcome join does not exist for the other two |

**Blocking:** the (c) premise and its consequence for the deadline. **Fixable
before Friday** with plan-level outcome attribution for plan/replan, and by
measuring the real corpus first.

**Not blocking, but should land in this change:** the missing
`semantic_memory._embed` row, and one clause recording *why* the mod's kind set
is the right one (the agent's is short by two).

**Not verified from here:** how much trajectory data actually exists (no pod
access; `kubectl` is not installed on this VM). That number decides whether the
deadline is achievable and should be the lead's first read in step 2.
