# PTC prod rollout, steps 3 and 4 re-review — NOT PASS as written

Re-review of `~/minecraft/docs/ptc-prod-rollout-plan.md` (7377 bytes, mtime
06:52Z) after the F-1/F-2 revision. Reviewer: minecraft-reviewer@minecraft.
2026-11-22. Prior review: commit `ecd04e6`.

F-1 and F-2 as I filed them are **addressed**. The revision is a real fix, not
a rewording: step 3 is image-only with a single restorable field, step 4 carries
no Secret edit, and the `set env NAME-` rollback is gone. What the revision
introduced is a new blocking defect, and it is the one P6 was written to avoid.

## F-7 (blocking, new): a bot in SCRIPT_BOTS gets the script in the LEGACY planner

P6 says "a bot in SCRIPT_BOTS takes the L3 plan path even with
USE_L3_PLAN_LAYER unset; other bots are unchanged." That is not what a bot in
`SCRIPT_BOTS` does today, and turning the L3 gate per-bot is not sufficient.

**Both planners offer a script, and they teach different dialects.** Read at
`3e900cc` and measured by rendering both prompts:

```
step3 prod (both unset)    offered=False | decompose_surface=False | l3_section=False
step3 prod other bot       offered=False | decompose_surface=False | l3_section=False
step4 Mystic               offered=True  | decompose_surface=True  | l3_section=True
step4 other bot            offered=False | decompose_surface=False | l3_section=False
```

`agent/planner.py:470-473` renders the **legacy** planner prompt with
`bot_name=bot_name`, and `render_planner_prompt` (`:446-451`) splices
`SCRIPT_SURFACE` (9186 bytes) in when `script_mode` says yes. So a bot listed in
SCRIPT_BOTS is offered the legacy surface on its first instruction — before,
and regardless of, any L3 routing.

**The legacy offer is unusable.** `SCRIPT_SURFACE` is injected by
`.replace(_SCRIPT_SURFACE_SLOT, ...)`, and `SCRIPT_SURFACE` contains `{ok, seq}`
(`planner.py:437-438`) — fine for a replace. The unsubstituted template does not:

```
KeyError: '{ok, seq}'
  planner.py:448  PLANNER_PROMPT.format(script_section=_SCRIPT_SURFACE_SLOT, ...)
```

The placeholder is safe; the surrounding template is not. This is the same
class as the published `{{` bug already fixed at `planner.py:470-473` — the
legacy template still carries an unescaped `{ok, seq}` in the same sentence at
`:470`.

**The plumbing to bind a legacy script does not exist.**
`_bind_planner_script`'s docstring (`agent.py:3870-3896`) documents three
orderings as tests and none of them runs: at `agent.py:1149-1157` `steps` is the
return of `planner.decompose` (a `PlannerResult`), while the script branch at
`:1150-1157` is reached only by an L3 `Plan` object that carries `.script`. And
`_get_script_tick` (`:4158`) returns None unless `_planner_script` or a
`bindings.json` entry exists — it is reached only after a bind, and the legacy
bind never happened.

Net: step 4 as written either raises `KeyError` on the first legacy-planned
instruction for Mystic, or — if the prompt renders — offers a surface whose
result is dropped by `_script_from` (`planner.py:409-428`) with a log line and
no bind. The plan's step 4 verify ("Mystic logs script mode on and takes the L3
path") would pass the first half and fail the second, after a restart cycle.

**Minimum fix to the plan.** P6 must be "for a bot in SCRIPT_BOTS the L3 path is
taken *and* the legacy planner does not offer scripts," which is a two-line
gate — `if USE_L3_PLAN_LAYER or script_mode(self.name)[0]:` at `:1114`, and the
same at `:891` — plus a decision on `:470-473`. It cannot be a manifest-only
step.

**The orchestration entry points are already per-bot-only at both gates.**
`USE_L3_PLAN_LAYER` gates exactly two dispatch sites (`agent.py:891`, `:1114`),
both fed by a chat message; `:5669` gates order intake (FAILED + telemetry when
off, so orders do not orphan). Orchestrator runs started from an in-flight
goal (`:1309` result hand-back, `:4143` yield re-plan) inherit the
orchestrator and need no separate gate. Whatever gate is chosen, it must be
applied at both `:891` and `:1114` or addressed and broadcast instructions
diverge.

## F-8 (blocking on the uncommitted status): P6 does not exist yet

`3c55acdb` is "Not a valid object name" in the builder worktree (rc=128). The
newest ref there is `3e900cc`, and at `3e900cc` there is no `script_mode`, no
`SCRIPT_RUNNER_URL` key, and no per-bot `USE_L3_PLAN_LAYER`. Every claim under
"Verified" in my F-7 is therefore a claim **about today's tree**, and the plan's
step 3 is titled "the build that carries P6" — a build no one can point at.

`git grep <pattern> <rev>` on a nonexistent rev prints nothing and exits 0, so
an absence probe here proves nothing on its own; the object-type check with a
positive control (`3e900cc` → `commit`) is the evidence.

Steps 3 and 4 cannot be signed off against a rev that does not exist. This is a
sequencing problem, not a wording one: P6 has to land, be reviewed, and be
deployed to test before step 3 can be judged.

## F-1 and F-2 as filed

- **F-1 addressed.** The plan no longer asserts that SCRIPT_BOTS unset reaches
  the current planner; §"Planner fact" states prod plans through
  `planner.decompose` and that the script surface is L3-only. Step 3's verify
  no longer claims a script-mode log line it cannot produce.
- **F-2 addressed.** Step 3 rollback is one field
  (`set image ...sha256:b2b274bf...`), byte-restorable, and the commit records
  it. Step 4 no longer uses `set env NAME-` and moves `MOD_API_URL` out of
  scope by construction ("No Secret edit"). The `RUNNER_TOKEN` key moves to
  `secretKeyRef` in the pod spec, which is restorable by re-applying the saved
  object as the plan says.

## Minor

- Step 4's rollback re-applies "the deployment as recorded before the step."
  Before step 3 the deployment is `b2b274bf`; after step 3 it is the new image.
  The record must be taken **after** step 3 and named by step, or the rollback
  reverts a reviewed image change as a side effect.
- Step 2's note says the mod fixes "also help the current planner" — true, and
  worth keeping, but it is the only prod step that is live-verifiable without
  scripts and it is currently in the middle of the sequence rather than first.

## Not established

I did not apply any step, and I read no live prod state for this pass. The
render measurements above were run against `3e900cc`'s code with
`nice -n 19`. No live bot.
