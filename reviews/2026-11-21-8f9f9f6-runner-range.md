# Review: agent-script-runner 89aa347..8f9f9f6 (build rev 8f9f9f6)

Rev: 8f9f9f6 (agent-script-runner)
Range: 89aa347 (exclusive) .. 8f9f9f6, five commits
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS

The five commits are one coherent change: look reads the world where the
producer writes it, matches kinds regardless of namespace, gains inventory(),
and measures the claim that none of it spends a host call.

## Verified

**Declared suite at 8f9f9f6: 190/190, rc=0** (`npm test`, reading
package.json rather than assuming, NODE_OPTIONS heap bound, no ulimit -v).

**Every behaviour probed against the producer's real shape**, not a hand-built
one:

  snapshot from test/fixtures/envelope-from-producer.json
  blocks("iron_ore")              -> 1
  blocks("minecraft:iron_ore")    -> 1
  entities("sheep")               -> 1
  entities("Sheep")               -> 1
  entities("minecraft:sheep")     -> 1
  inventory().items               -> the two stacks, item shape preserved
  age().ageMs                     -> a number, not null

The near-miss the comment promises holds too, which is the part that matters
for a substring bug: "iron" matches 0, "minecraft:iron" matches 0,
"iron_ore_extra" matches 0, "Minecraft:Iron_Ore" matches 1. One leading prefix
comes off each side and matching stays exact after that.

**The deep copy is real, not a claim.** Pushed an item into a returned list;
a second inventory() in the same tick still returned one item, and the frozen
snapshot was unchanged.

**Read-only is enforced.** Object.isFrozen(look) is true, the inventory
descriptor is writable:false configurable:false, and assigning over it throws
TypeError. The spec's "every property read-only" scenario holds. (radius is a
number, so "all values are functions" is correctly false - I checked that the
assertion being made is about writability, not function-ness.)

**The host-call measurement is not inert.** The spec says wiring any accessor
through accept reds it, so I wired inventory() to api.say and ran both look
suites: 27 pass / 7 fail. Restored, sha256sum -c OK, tree clean, full suite
back to 190/190. The 200-call loop at look-engine.test.mjs:50 does include
inventory(), which was the gap I filed at c6c3233 - it is closed.

## Note, not a finding

The inventory item shape is {slot, item, count, display_name, max_stack_size,
durability...} - the id field is named "item", not "id", unlike blocks (which
use id+block) and mobs (which use type+name). A script reading items[0].id
gets undefined. inventory() returns the stacks verbatim, which is correct for a
read-only accessor, but the three nearby kinds and the inventory all use
different field names for the same idea. That is a producer-shape observation,
not a defect in this diff, and the spec does not promise a normalised shape.

## Instrument failures of mine

1. My first probe imported engine.js by a relative path from /tmp, so it
   resolved against /tmp and failed ERR_MODULE_NOT_FOUND. Absolute path fixed it.
2. My second probe called new Sandbox() with one argument; the constructor
   takes (rt, opts) and rt is required. I read how the existing tests build one
   instead of guessing a third time.

Neither reached a finding. Recording them because a probe that fails to start
produces no information, and "it did not work" is not evidence about their code.
