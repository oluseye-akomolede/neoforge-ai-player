# M2 8.3.4 run 2 — blocked by the L3 planner, not the script or runner

Captured 2026-11-13T04:40-04:46Z on TEST, pod `aibot-agent-test-6f64489bc9-xgg6d`
(image `sha256:d1513fa2...`, agent `9292002`), runner `agent-script-runner-c4596854f-kgvr7`
(image `sha256:6e079944...`, built from `2e1d608`).

## Precondition satisfied

Scout carries 16 cobblestone, granted via the mod's give API (the lead's option 1):

    POST /bot/Scout/give {"items":[{"item_id":"minecraft:cobblestone","count":16}]}
    -> {"items_given": 1, "status": "given"}

    POST /bot/Scout/effective_inventory
    -> {"inventory":[{"item":"minecraft:cobblestone","name":"Cobblestone",
                      "carried":16,"vault":0,"count":16}]}

A storage block exists and is a valid `STORE_ALL` candidate: one
`minecraft:chest` at (16, 99, -15), stable at radius 16/32/64. `nearby_containers`
at radius 8 returns none, but `StoreAllBehavior` sources candidates from
`ContainerRegistry.get().getByDimension(...)` with no radius limit, so the chest
is reachable. Both preconditions in the lead's ruling are therefore met.

## Why no action was produced

The goal was injected twice through the plan's own path (mod chat injection,
`api.inject_chat("Scout","OperatorTest","Scout, please store all your items in the nearby chest.")`).
Both times the L3 planner produced a directive kind the mod does not accept:

- run 1: `SEARCH_AND_STORE` -> `unknown (id=None)`, then
  `subtask 1 criteria: True (world_state) — holdings 0/0 of minecraft:items (0 carried)`
  then `plan finalized: complete`.
- run 2: `SEARCH_AND_MINE` x4 attempts -> `unknown (id=None)` each time, then
  `plan finalized: complete`.

The only two kinds the planner emitted across both runs, counted from the log:

    2 SEARCH_AND_MINE
    1 SEARCH_AND_STORE

Neither is in the mod's directive vocabulary. A directive that never reaches the
mod never yields an in-flight task, so the script is never consulted with
anything to act on. `[Scout/script]` lines: 0. `action(s) this tick`: 0.
`dispatch:`: 0.

## The two defects this exposes

1. The planner can emit directive kinds no consumer accepts.
2. A plan whose directives never started is recorded `plan finalized: complete`.
   Run 1 reached `complete` on a `True (world_state)` criterion that was true of a
   bot that did nothing (holdings 0/0). Run 2 at least detected failure
   (`False (result_text)`) but still closed `complete`.

## What this is not

Not the script guard, not the runner, not the review fix. The reviewed agent
filter behaved correctly throughout, dropping the stray `container` key and
keeping `type`.

## Verification still owed for 8.3.5 rows 1-4

Unchanged: needs an agent-loop tick with a non-empty `actions` list, which needs a
directive that actually starts. That needs the planner to emit a real kind, which
is the blocker above.
