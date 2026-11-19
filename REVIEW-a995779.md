# Review: a995779 — M3-1c 9.6, the snapshot envelope

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Rev under review: a995779bf6eba18a405187e488da56cb5e4207e7
Parent: e7e1526 (my review of 7133983)

## Verdict

**PASS.** The cause is real, the fix is at the right layer, and the suite now
covers the shape production actually sends. 92/92 reproduced, mutant 5 red.

One **note** (tick divergence between the two paths, latent, not live) and one
**answer to the builder's question** about the health guard, which is the most
important paragraph in this file.

## The cause — confirmed, and it is a shape bug not a read bug

`_build_snapshot` had two paths returning different things: `SnapshotCache.get`
returns `(envelope, errors)`, bare `build_state` returns `(state, errors)`.
`tick()` unpacks either as `envelope, snap_errors`. So the uncached path put a
raw state dict on the wire, and the script's `snapshot.state || {}` discarded it.

I did not take the chain on trust. Each link holds:

- `build_envelope(state, *, tick, events=None, task=None)` — signature matches
  the new call, keyword-only, `task=` passed exactly as `SnapshotCache.get` does.
- The `task=` reasoning is the same one the cache documents at length: leaving
  it unset makes `snapshot.task` None on every tick. The fix copies the cache's
  behaviour rather than inventing one.
- Production builds `ScriptTick(api, self.name, source)` — no `cache=`, so
  `self._cache is None` and the uncached path is the only one that ever ran.

## The health guard — answering the builder's question

The builder asked for a second pair of eyes on whether the health guard was
blind by the same mechanism. **It was, and silently.** Reproduced directly:

    PRE-FIX  snapshot = bare state -> snapshot.state undefined -> state = {}
             state.health = undefined -> typeof !== "number" -> guard does not fire
             a bot at health 3.0 proposed actions
    POST-FIX envelope -> state.health = 3.0 -> guard fires, holds

So for the same eight minutes, a hurt bot was not held by the health guard. The
inventory guard was merely the field loud enough to log; the health guard is
silent by construction, because its condition is `typeof health === "number"` and
undefined fails that quietly.

**The suite would not have caught it either.** Every test builds an envelope via
`_envelope()`; none passes a bare state, so no test drives the health guard
through the pre-fix wire shape. Reverting `_build_snapshot` and running the
three suites gives 5 red — and I checked what they are: the wire-shape test, the
inventory-path test, and three others. None of the five is the low-health test.
`test_low_health_holds` stays green under the pre-fix shape because it feeds a
full envelope.

That is not a defect in this commit — the commit fixes the cause. It is a gap in
the suite that this commit does not close, and it is the same species as the
ConfigMap row: a guard that passes because nothing feeds it the failing shape.
Recommend a test that drives the low-health case through the bare-state wire
shape and asserts it is red on e7e1526. I have not filed it as blocking because
the code path that produced it no longer exists.

## Note: the two paths keep different tick clocks (latent)

`SnapshotCache.get` increments `tick` only on a cache **miss**. The new uncached
path increments on every `_build_snapshot()` call. Measured over four ticks:

    uncached: [1, 2, 3, 4]
    cached:   [1, 1, 1, 1]

`scout.js:118` uses `snapshot.tick` as the cooldown clock:
`now - lastStore < STORE_ALL_COOLDOWN_TICKS`. On the cached path `now` does not
advance within a TTL window, so a store at tick 1 reads `0 < 100` forever while
the cache stays warm and the cooldown never expires.

Not a bug today: production always takes the uncached path, so the measured
behaviour is `1,2,3,4` and the cooldown works. It is a trap for whoever enables
the cache. `test_a_cached_tick_and_an_uncached_tick_agree` exists but asserts
`sorted(keys)` — the shape agrees, the clock does not. Worth either a comment at
`SnapshotCache.get` or an assertion on the tick values.

## Checks

- 92/92 OK, RC=0 from the runner's own exit (captured, not piped to tail).
- Bare-state mutant, anchor asserted at 1: exactly 5 red, failure messages name
  the consequence ("every snapshot.state.* read undefined") and the path
  (`scout.js:107`).
- Restored file `cmp`-identical to `a995779:agent/script_tick.py` after mutating.
- `scout.js` untouched; ConfigMap mirror unchanged at 782c9910 / 14333.
- No push, no apply.

## Provenance

- Clean `git archive a995779` into a temp dir; all runs from there, not the
  builder's worktree.
- Suite run with `PYTHONPATH=agent/`, `NODE_OPTIONS` heap bound (no `ulimit -v`,
  the documented Node/WebAssembly trap), `nice -n 19`.
