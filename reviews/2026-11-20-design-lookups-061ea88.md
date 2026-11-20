# Review: design `061ea88` — F7, F8, N-1, goal_id

**Rev:** `061ea88` (on `682b092`)
**Prior:** `5ae0372` (F1–F6 closed, F7/F8/N-1 raised)
**Verdict:** **F7, F8, N-1 and goal_id all closed — correctly.** One new defect,
F9, in the bound the design recommends as its fix for the payload.

---

## Closed, checked against source not the commit text

### F7 — the cap scenario can now fail. Closed.
Ten distinct scripts, each `done` once, bound and run back to back inside the
hour (`spec.md:76-79`). That is the bind/release bypass shape I asked for, and
the third bullet — "the fifth script MUST NOT start a planner call even though
its binding and release are the same shape as the first" — is what makes an
implementation keyed on the *script* fail it. The design says so itself at
`:84-86`. This now tests the per-bot cooldown rather than assuming it.

### F8 — the payload is costed from source. Closed.
`design.md:165-176` builds the entry from `BotPlayer.java:907-910`, derives
41–51 B over 20 real display names with a median of 44, and computes the
full-cube bound as `1331 × 44 B ≈ 57 KiB`. **Checked the arithmetic and the
method:** 1331 × 44 = 58,564 B ≈ 57.2 KiB, correct; and the design explicitly
labels it a full-cube bound, so it is not assuming all cells are non-air on the
quiet — it names the assumption and bounds it. It also credits the 30–54 KiB
figure as the partial-fill estimate, which is the right relationship between
the two numbers. The `27×` radius-16 claim is also correct (35937/1331 = 27.0).

### N-1 — cap-state lifetime. Closed, and better than asked.
`design.md:412-421`: per bot, process lifetime, keyed by bot name, explicitly
**not** cleared by `reset()`, with the reason stated (a reset is the moment a
fresh goal arrives, so clearing would hand back the budget on demand) and a
test required to fail if `reset()` clears it. That last part is more than I
asked for and is the right guard.

### goal_id — closed.
`:359-364`: `replace` keeps the existing `goal_id`; the planner does not mint
ids; `_new_goal_id` stays player-message-only. Matches the lead's call and
closes the gap I raised. The `{bot, goal_id}` delivery key at `:314-315` still
holds with a stable id across replaces.

---

## F9 — "nearest K per block id" is not the nearest K, and cannot be without a sort

`design.md:180-186` recommends **nearest K per block id** as the payload bound,
and states it "costs one insertion-ordered pass over the cube rather than a
sort ... a per-id counter in the existing `seen` loop (`:898-911`), which is a
few lines in the same method — not a new scan."

**The loop does not scan by distance.** `BotPlayer.java:893-897` is
`for x = -r..r { for y = -r..r { for z = -r..r {`, starting at the
`(-r, -r, -r)` corner. A counter on that loop keeps the **first K in scan
order**, which begins at the most-negative corner of the cube. And the method
computes **no distance at all** — grepping `distance|sqrt` over `:892-915`
returns nothing (exit 1), so a counter has no quantity to rank by even if it
wanted to.

**Executed, not reasoned.** Replaying the exact loop order with two chests, one
at (2, 0, 2) (2.83 blocks away) and one at (-5, -5, -5) (8.66 away), taking K=1:

```
chest scan order: [(-5, -5, -5), (2, 0, 2)]
first kept (K=1): (-5, -5, -5)
kept the nearest? False
```

It keeps the chest **8.66 blocks away and drops the one 2.83 away**. A script
asking "is there a chest nearby" would get a position behind a wall to the far
corner. This is not a naming quibble — the bound the design recommends as its
answer to F8 silently degrades the answer for exactly the lookup it exists to
support.

**Two honest fixes, and the design should pick one:**

1. **Say "first K in scan order" and accept it.** Then cost it truthfully: the
   kept entries are the -x,-y,-z corner of the cube, so for a bot in open
   terrain near the corner the "nearby chest" may be ~8 blocks away in a fixed
   direction. That is a poor lookup and I would not ship it as the default.
2. **Make it actually nearest.** That means holding a distance per candidate —
   either keep the K best by a per-id list with insertion, or sort the per-id
   collisions at the end. It is *not* "a few lines", and it is *not* free: it
   either adds a comparison per non-air cell or a small sort per id. Still
   cheaper than the full cube, which is the point — but the design must cost it
   honestly rather than claim "not a sort" for something that has to be one.

A third option worth naming: **expose `find_blocks`** (already at
`BotPlayer.java:1238-1263`, radius 32, real ids, stops at `maxCount`) and drop
the snapshot-widening path entirely for the query shapes that need distance.
The design already describes that alternative at `:191+` and it does not have
this defect, because `findBlocks` can order however it likes on demand.

---

## The lead's second question — the 57 KiB figure

**Computed, not assumed.** `1331 × 44 B ≈ 57 KiB` is arithmetic from a stated
per-entry size, and the text calls it "the full-cube bound" explicitly at
`:174-176`, contrasting it with my 30–54 KiB partial-fill estimate. So it does
**not** assume all cells are non-air; it takes the worst case as a bound and
labels it as one. This one is honest.

---

## Not disputed

- `validate script-lookups-and-results --strict` rc=0 at `061ea88`, rev printed
  in the same command.
- The radius-5/16 scan cost is unchanged by the K bound (same loop, same cells),
  which the design states correctly at `:185-186`.
- No task in `tasks.md` carries the "nearest K" claim, so F9's fix is confined
  to `design.md` and does not orphan a task.

Nothing built, pushed or deployed by this review. No `ollama-l3` request, no
pod exec, nothing written in `ci`.

## Suggested disposition

Close F7, F8, N-1 and goal_id. **Revise before code** on F9 — pick fix 1 with
honest cost, or fix 2 with the sort costed, or switch to `find_blocks`. The
rest of the design is ready to build.
