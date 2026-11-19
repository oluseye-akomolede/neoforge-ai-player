# Review: 028e065 (+ task 8398d98) — hold cause and identity

Revs read via `git show <rev>:...` from `ship-ca27-harness`.

**Verdict: PASS.** The requirement and task text are correct. One
implementer constraint (I1) that must land before code, because the mechanism
described in chat aliases on a second code path.

---

## What is right

- The requirement asks for cause and identity without over-specifying to an
  integer. That is the correct altitude: the *what* is pinned, the *how* is not.
- The diagnosis of `_orch_stop_pending` is accurate and matches mine: one
  latched boolean, three callers (`:298`, `:473`, hold), set `:1222`, cleared
  `:1413` by whichever thread consumes it, unguarded.
- The `:1438` identity idiom is a **stable** anchor, which I checked
  independently: `_orch_cancel` is assigned at only `:1408` and cleared at
  `:1439`, unlike `_plan_instruction`.
- The "MUST NOT widen the unlocked set/clear" clause correctly refuses to fold a
  pre-existing race into this change while still preventing it from getting
  worse. That is the right split.

## The `_plan_instruction` count — corrected by the builder, verified

Their self-correction is right. At `028e065`: **19 mentions, 9 clears**, at
exactly `:209`, `:304`, `:476`, `:542`, `:679`, `:912`, `:2989`, `:3052`,
`:3087`. The remaining assignments are sets (`:573`, `:623`, `:800`, `:821`,
`:841`, `:1518`, `:1536`). The field is both cleared nine times and set seven
times, so it cannot anchor a hold. Correct call.

## I1 — there are TWO in-loop orchestrator spawn sites, not one

The chat proposed incrementing `_goal_generation` "in `_maybe_plan` at the
accept point (`:623-631`, next to where the thread spawns)". There are two such
sites:

| site | branch |
|---|---|
| `:625-631` | plan-layer path (`USE_L3_PLAN_LAYER`) |
| `:823-830` | spec-driven `else` arm of the inner branch at `:812` |

Both bodies are near-identical — same `_plan_instruction = text`, same
`l3_plan_dispatched` event, same `Thread(target=self._run_orchestrator)`. Both
are live: `:596` gates them as a single
`if USE_L3_PLAN_LAYER and not from_bot and not self._following_player`, and
`:824` is the `else` arm inside that block.

**Consequence.** A generation incremented at `:623` only gives a goal accepted
on the `:824` path the *same* generation as the previous one. Goal A on `:626`
and goal B on `:824` both carry generation N, and "generation equals holding
generation" cannot distinguish them. The spec's batch-ownership sentence would
be satisfiable in the letter and false in behaviour.

**This is not a spec change.** The wording correctly says "identify the goal that
owns the hold" and correctly declines to name an `int`. It is an implementer
constraint: increment at *every* accept point that spawns an orchestrator, or
preferably in a single place common to both, rather than at the two spawn sites
200 lines apart — the missed one is silent, because both paths still work, they
just alias.

Asked for both `:625` and `:823` to be named in task 9.8 so the task cannot be
ticked having handled one.

## Not disputed

- `openspec validate --strict` valid.
- No code exists; nothing applied or pushed.
