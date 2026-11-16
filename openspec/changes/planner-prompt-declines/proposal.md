# Planner prompt declines: stop false refusals in plan, stop the replan escape hatch

## Why

The 11-14 think-off eval run (`run-1114-q38-think-off.log`, model
`qwen3.8:27b-q4_K_M`, think off) measured:

- exec 25/25
- plan 19/25 (6 fail: 4 `refuse`, 2 `clarify`)
- replan 21/25 (4 fail)

Both deficient kinds fail for reasons traceable to the prompt text in
`agent/l3_planner.py`, not to the model.

**Replan (4 fail).** `_REPLAN_SYSTEM_PROMPT` ends with an invitation:

```
If truly impossible, return: {"error": "<short reason>"}
```

All four replan failures took that invitation verbatim — each recorded answer is
`{"error": "..."}`, e.g. *"minecraft:end_portal_frame cannot be crafted or
placed by players"*, *"End Portal Frames cannot be crafted"*. The scorer reports
them as `subtask missing ['id','description','criteria']`; that is the shape of a
refusal, not a malformed subtask.

This contradicts the live requirement *Replan on Repeated Failure*, which says
a replan MUST return a replacement subtask. The prompt offers an answer the spec
never authorised, so the model is being invited out of compliance. This is a
prompt defect against an existing requirement, not a missing requirement.

**Plan (6 fail: 4 refuse, 2 clarify).** Of the five failing outputs captured in
the run's `examples` (`results.plan.examples` holds 5; the 6th case text was not
captured in this log, so its reason is characterised but not quoted):

| recorded reason | verdict |
|---|---|
| "can't 'report back' … no chat or message channel in my toolset" | **wrong** — the agent can chat; see *The bot can already speak* below |
| "You're not carrying anything to store—your inventory is empty" | **wrong** — current state is not impossibility; plan to obtain/carry first |
| "There is no moon to fly to … bedrock cannot be mined" | correct |
| "What specifically would you like me to get, and how much?" | correct |
| "Which stuff, and how much?" | correct |

So two classes of false decline are in evidence, and they have different causes:

1. **Capability blindness.** The model is shown a directive catalogue that has no
   chat directive (37 kinds in `DirectiveType.java`, none of them SAY/CHAT/MSG),
   so it concludes it cannot report back. It is wrong: `api.chat()` is a live
   side channel the agent uses throughout (`agent.py:390,405,425,501,510,1271`),
   just not as a *plan directive*. The prompt never says "some outcomes happen
   outside the subtask list", so the model infers capability from the directive
   list alone.
2. **State-as-impossibility.** "Your inventory is empty" is a fact about the
   present, not a property of the world. Refusing on it means a task like "store
   my stuff" can never run before the stuff exists. The prompt's refuse rule is
   keyed on "names something this server does not have" and "two mutually
   exclusive things"; a transient precondition is neither, but nothing says so.

The correct refusals (no moon; clarifications of genuinely vague asks) MUST
survive unchanged. The owner's constraint is explicit: *"Correct refusals of
deliberately impossible or vague asks must stay refusals."* This change narrows
the refuse predicate; it does not weaken it.

## What changes

- `agent/l3_planner.py` `_REPLAN_SYSTEM_PROMPT`: remove the `{"error": ...}`
  escape hatch. Require a replacement subtask. If the model still returns an
  error object, that stays a plan failure — the bounded-replan rule is unchanged.
- `agent/l3_planner.py` `_PLAN_SYSTEM_PROMPT`: add two narrow rules to the
  decline section —
  - the bot speaks through a channel outside the directive list; inability to
    express an outcome as a directive is not inability to achieve it;
  - a precondition that is merely not true *yet* (empty inventory, wrong
    dimension, wrong tool held) is planned around, not refused. Only facts about
    the world — a missing dimension, an uncraftable item, unbreakable blocks,
    mutually exclusive simultaneity — justify a refusal.

## What does not change

- The plan JSON schema, the decline response shape
  (`{"kind":"clarify"|"refuse","reason":...}`), and the scorer surface.
- `DirectiveType.java`. Adding a chat directive is a different change with its
  own consequences (the exec layer would have to sequence speech); this change
  only stops the planner from *believing* speech is impossible.
- The bounded-replan rule and `MAX_REPLANS_PER_SUBTASK`.

## Risk

Loosening a decline predicate risks converting correct refusals into fabricated
plans, which the existing prompt already calls out as worse than refusing ("A
fabricated plan is worse than a refusal"). The mitigation is that the two added
rules are scoped to *self-capability* and *transient state*; every example of a
correct refusal in the spec (moon, simultaneity) is untouched, and the spec
delta adds scenarios for both directions so a future regression that starts
planning the moon fails a test.

## Out of scope

- `openspec/specs/**` edits beyond the delta in this change.
- The 6th plan failure's exact text (not captured in the run log). The eval Job
  the lead runs after the prompt edit will either confirm the class or surface a
  new one; the before/after report is per-kind from that Job log.
- LoRA/DPO work — owner default A is "fix the prompt before any LoRA."
- `_REFINE_SKILL_PROMPT` (`l3_planner.py:1097`), whose final instruction is a
  structurally identical error invitation (`{"error": "<why it cannot be
  fixed>"}`). Different contract, so it stays out of this change — but a future
  error-shaped skill-refine answer will NOT be found by grepping for the replan
  text, so it needs its own row rather than being rediscovered from scratch.
