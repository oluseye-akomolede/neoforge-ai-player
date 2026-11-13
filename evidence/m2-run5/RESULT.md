# M2 run 5 — STOCKED run: does a script-driven bot actually move items?

**Date:** 2026-11-13 · **Cluster:** TEST (`minecraft-test`) · **Bot:** Scout
**Image:** `sha256:a9e75ad1b1efd22f9cc15f81662aa0865d068e92c555f034a0440bd0c9147c38`
**ConfigMap `agent-scripts`/`scout.js`:** `1824967e200dab94…` (4893→5852 bytes, the reviewed `scout.js`)
**Pod:** `aibot-agent-test-6b65bdfc95-b8ll5`

Run 4 proved the *dispatch* chain but left the bot unstocked, so STORE_ALL completed
with `{}` — nothing to move. This run repeats it stocked. Run 4 remains valid; it is
not superseded.

## Pass criterion

Per the lead: the pass is a **stack the script may take** (a non-selected slot) ending
up in a chest, read back **verbatim**, with no key in the output — while a stack in the
**selected** slot legitimately stays (the trap).

## Stocking

Scout's inventory is set through the mod's reviewed give path, `/bot/Scout/give`,
called **inside the pod** so the API key never crosses the transcript.

| given | outcome |
|---|---|
| `minecraft:dirt` ×16 | taken by an STORE_ALL tick (`items_stored: 16`) |
| `minecraft:dirt` ×16 | taken by a later tick (`items_stored: 16`) |
| `minecraft:oak_log` ×8 | taken by a later tick (`items_stored: 8`) |

All three stacks were taken. The cobblestone ×16 that was **already** in slot 0 before
the run was not — it stayed for the whole run. That contrast, not a slot index, is what
makes the trap observable: three stacks given and stored, one pre-existing stack left
behind. `selectedSlot` is not exposed by any read endpoint, so the selected slot is
identified here by behaviour rather than by a field.

## BEFORE — Scout's inventory, read via `/bot/Scout/inventory`

```
[{"slot": 0, "item": "minecraft:cobblestone", "count": 16, "display_name": "Cobblestone", "max_stack_size": 64}]
```

Position `(-67.5, 119, -233.5)`, dimension `minecraft:overworld`.

## The dispatch + completion chain, verbatim (agent log, `--timestamps`)

```
2026-11-13T05:35:23.001948130Z [Scout/script] dispatch: STORE_ALL seq=1 {'kind': 'STORE_ALL'}
2026-11-13T05:35:25.051950264Z [Scout/L1] Directive COMPLETED: {'items_stored': 16}
2026-11-13T05:36:36.746450331Z [Scout/L1] Directive COMPLETED: {'items_stored': 16}
2026-11-13T05:36:46.452672203Z [Scout/L1] Directive COMPLETED: {'items_stored': 8}
```

`items_stored` totals **16 + 16 + 8 = 40**, exactly the 32 dirt + 8 oak_log given.

## AFTER — Scout's inventory

```
[{"slot": 0, "item": "minecraft:cobblestone", "count": 16, ...}]
```

Same single entry, same slot, same count as BEFORE, across every read in the run
(the only differences are my elisions in transcription). **The retained stack stayed,
as predicted.**

## Destination — the container holding the items, read back

The behaviour moves Scout to the chosen container (`StoreAllBehavior.tickFindContainer`
→ `player.moveTo`), which is why Scout ended adjacent to container #1 at
`(-68, 119, -234)`. Reading it via `/bot/Scout/container`:

| item | count |
|---|---|
| `minecraft:dirt` | **32** |
| `minecraft:oak_log` | **8** |
| `ae2:stonecutting_pattern` | 12 (pre-existing, not ours) |

**40 items stored, at the destination, verified by reading the container back.**

## Why the earlier reads looked empty

1. The named chest at `16, 99, -15` is ~300 blocks from where Scout stands and was
   never the store target. `ContainerRegistry.getByDimension` walks every container in
   the dimension and takes the first with space.
2. Container #48 (`-74, 119, -230`, `placed_by: discovered:Scout`) is a *different*
   container and is genuinely empty.
3. `StoreAllBehavior`'s `progress.logEvent` writes to an in-memory ring buffer only
   (`ProgressTracker:41-46`) — it never reaches the agent container's stdout. The
   agent-side `Directive COMPLETED` line is the observable record.

## Verdict

**PASS**, on the lead's stated criterion:

- three stacks the script may take (dirt ×32, oak_log ×8) **moved to a chest and are there on read-back**;
- the stack it may not take (cobblestone ×16) **stayed on the bot**, the predicted trap;
- the whole chain — `api.do` → runner → `translate_runner_actions` → `bind_action` →
  director → vanilla container — is exercised end-to-end on real items.

Run 4's contribution stands: it proved the dispatch chain and exposed the boundary
defect. Run 5 closes it with items actually moving.

## Incident carried on this run, separate from the verdict

A live `MOD_API_KEY` value reached this seat's transcript during debugging (see the
lead's rotation ruling). No key appears in this file, in any command recorded here, or
in any committed artefact; every mod call was made inside the pod reading
`os.environ`. Rotation is tracked separately and is not part of this verdict.
