# PASS — per-type ACTIVE bound (`37fe55d`) and ore deepslate variant (`27d786b`)

Agent rev `37fe55d` (neoforge-ai-player); runner rev `27d786b` (agent-script-runner).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

Both commits pass. No blocking findings. One scoped note (N-1) that is not
owed here.

## `37fe55d` — the ACTIVE bound is per-type

**The premise correction is right and it corrects me.** I filed NC-1 with a
3000-tick flat bound justified as "five times GOTO's 600, so nothing
self-bounded can reach it." `CombatBehavior.DEFAULT_DURATION = 6000`
(`CombatBehavior.java:68`) is twice that, and `getCount()*20` above that. So a
working COMBAT was cut in half by the fix I asked for. Their commit found the
hole in my own reasoning, which is the correct outcome of a review loop.

**Verified:**

- `SCRIPT_DIRECTIVE_MAX_BY_TYPE = {FOLLOW: 3000, COMBAT: 9000}`, default
  `SCRIPT_DIRECTIVE_MAX_TICKS = 9000`. An unlisted type is bounded loosely,
  never unbounded — the right failure direction.
- Full agent suite at `37fe55d`, run inside `agent/`, rc read unpiped:
  **469 tests, OK (skipped=1)**, 25.6s. That is 19 test modules from
  `git ls-tree 37fe55d`, not a narrowed selection.
- Mutant 1, flatten `"COMBAT": 3000` — **exactly 2 failures**, both the new
  tests by name: `test_a_combat_running_past_the_follow_bound_is_not_yielded`
  and `test_the_bound_is_per_type_so_a_combat_is_not_cut_mid_fight`. The
  builder's claim reproduces exactly.
- The seed is a literal: `self.a._script_active_run = 4000`, past a flat 3000
  and short of 9000. That is the SCRIPT_IDLE_MAX lesson applied correctly —
  seeding from `_directive_max_ticks("COMBAT")` would have cancelled and
  passed for any value.
- Cites resolve at this rev: `GotoBehavior.java:37` is
  `MAX_TICKS = 600`; `CombatBehavior.java:68` is `DEFAULT_DURATION = 6000`;
  `config.py:103` is `TICK_DELAY = float(os.getenv("TICK_DELAY", "2.0"))`.
- `openspec validate script-lookups-and-results --strict` rc=0, unpiped. The
  amended requirement names why one number cannot serve and keeps the
  per-type MUST; the false premise ("set above every self-bounded behaviour")
  is gone.

**Mutant 2 is a survivor, and it is acceptable.** Removing `.upper()` from
`(self._directive_type_in_progress(st) or "").upper()` leaves the suite green
and falls everything to the 9000 default. Why it survives: `Directive.toMap()`
puts `type.name()`, which is already upper-case for every `DirectiveType`
member, so the normalisation is unreachable defence for any body the mod
sends. It is not dead — it guards against a lower-case type from any other
producer — but no test exercises it. Worth a comment saying so; not worth a
test, and not owed.

**Enumeration corrections: both confirmed.**

- 38 behaviour files of which 37 end `Behavior.java`; the 38th is
  `BehaviorFactory.java`. The interface `Behavior.java` is among the 37, so
  37 definitions − 1 interface = 36 implementations. The new comment's
  "36 implement Behavior" is right.
- The duration constants it now names are real: `DEFAULT_DURATION = 6000`
  and `CultivateBehavior.MAX_SECONDS = 86400`.

**N-1, scoped and not owed here.** A type absent from the table gets 9000
ticks. `CultivateBehavior.MAX_SECONDS = 86400` is 86400 ticks (it is named
seconds but read as ticks on the elapsed-tick path), an order of magnitude
past 9000. So a legitimately long CULTIVATE still gets yielded. I did not
confirm that CULTIVATE reports `ACTIVE` rather than retiring its directive, so
I am not claiming a reachable defect — only that the default is not above
"every type's longest legitimate run" as the requirement phrase asserts. The
scenario the requirement states is satisfied for GOTO, COMBAT and FOLLOW;
CULTIVATE is outside what was tested.

## `27d786b` — `look.blocks` finds the deepslate variant

**Verified:**

- Runner suite at `27d786b`, declared glob form, rc unpiped: **207 tests,
  207 pass, 0 fail**, rc=0.
- Mutant (drop both `__lookOres` branches, return `[bare]`): **3 failures**,
  exactly the three variant tests — `an ore kind finds its deepslate variant
  by id and by bare name`, `asking for the deepslate ore finds the plain one,
  in both directions`, `both variants are returned when the snapshot holds
  both`. Reproduces the claim.
- **The equivalent-mutant note is honest and reproduces:** dropping only the
  `__lookSameOre(name, needle)` call leaves 207/207 green, because the `id`
  call still matches. They said it is not covered and did not claim it as
  coverage; I confirmed both halves.
- Scoping holds under direct probing: `deepslate` vs `cobbled_deepslate` →
  false, `stone` vs `deepslate_stone` → false, `copper_ore` vs `iron_ore` →
  false, while `iron_ore` vs `deepslate_iron_ore` → true. The `_ore`-on-both-
  sides guard genuinely prevents prefix widening.
- Display-name path is real, not covered by the id branch: through the real
  `createLook(...).blocks()` API, `"Deepslate Diamond Ore"` and
  `"diamond ore"` both return 1. (`look.blocks` lower-cases the needle before
  the matcher, which is why the id call cannot carry it.)
- The `MINE` half genuinely needs no change:
  `MineBehavior.matchesBlock` already has
  `if (oreBase != null && blockId.contains(oreBase) && blockId.contains("ore"))`
  (`MineBehavior.java:285`).

**My own instrument errors, recorded so the builder does not inherit them.**
I called the display-name path broken because I invoked the internal
`__lookSameOre` directly instead of through `look.blocks`, and I ran the
`MineBehavior` grep in the wrong repo, got a silent empty result, and nearly
wrote that the MINE claim was unverified. Both were my queries, not their
code. Third and fourth time tonight.

## Not established

- No live bot. Trial 4.2's deepslate lookup and the COMBAT/FOLLOW bound have
  not been observed on a server.
- The `ACTIVE`-forever suppression from my earlier NC-1 note now has a bound
  for FOLLOW (3000) and COMBAT (9000); the gap for an unlisted
  duration-bounded type is N-1 above.
