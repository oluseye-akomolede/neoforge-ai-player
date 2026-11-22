## Why

A bot asked to "find X within 4 blocks, do not walk" walks a 25-cell, 32-block
sweep instead, and then reports failure as if it had searched 32 blocks. The
radius the caller states is silently discarded.

Two separate defects produce this:

1. `WideSearchBehavior.start()` reads the radius only from the directive's
   top-level field (`WideSearchBehavior.java:90`) and never consults
   `extra.radius`, although the sibling `AreaLootBehavior.java:77` does read
   and clamp `extra.radius`. The model that emits `extra.radius` — which is
   what the skill surface taught it to do for AREA_LOOT — has its value
   dropped on the floor.
2. `Directive.Builder` defaults `radius` to 256, so a caller that supplies no
   radius gets a first shell of 32 and an escalating sweep, while a caller that
   supplies a small radius in `extra` is treated identically.

Neither `SkillRegistry`'s `goto_and_scan` seed nor the L3 directive vocabulary
advertises that WIDE_SEARCH takes a radius at all, so the model has no
supported way to express the constraint and invents the parameter.

## What Changes

- `WideSearchBehavior` reads a search radius from `extra.radius`, falling back
  to the directive's top-level `radius`, clamped to a floor of 1 and a ceiling
  that preserves the existing long-range escalation.
- The ceiling must NOT be copied from `AreaLootBehavior`'s `MAX_RADIUS=64`:
  WIDE_SEARCH exists to sweep up to 1024 blocks, and a 64 cap would delete that
  capability. The cap is applied only as the search's stopping distance.
- The failure path reports the radius actually searched, not the unclamped
  shell-table value. With `maxRadius=4` the current code searches 4 blocks and
  then claims "not found within 32 blocks".
- The `goto_and_scan` seed and the L3 directive vocabulary advertise the radius
  so the model can express it.

## Impact

- Affected specs: `bot-behaviors` (MODIFIED: Escalating Search; ADDED: Wide
  Search Radius).
- Affected code: `WideSearchBehavior.java`, `SkillRegistry.java`,
  `l3_planner.py`.
- No cluster changes. Behaviour with no radius supplied is unchanged: the
  default stays 256 and the 32→64→…→1024 escalation is preserved, so the
  existing "58 cells each at radius 128" scenario still holds.
