# Gate — contract v1 at 0e42337 (per-game quota)

Rev: `0e42337`. Row qitem-20261110113044-cb477188e66793af.
Read from the sha (`git cat-file -t 0e42337` → commit; file read via
`git show 0e42337:openspec/changes/coded-agents/contract-v1.md`).
Diff scope since my `2f595a4` PASS: `contract-v1.md` and my own review file only.
Date: 2026-11-10T11:34Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS, with one new item for §10**

## The lockout finding is resolved, and better than I asked

My `2f595a4` note was that `max_sandboxes: 32` "per runner instance" with one
instance serving both games made the pool jointly held, so whichever game filled
it first locked the other out under a refuse-new/never-evict rule.

`0e42337` fixes both halves, not just the number:

- `max_sandboxes` is now **keyed by `game_id`** (`:293`), 8 minecraft / 256
  cardgame, and §7.1 states plainly "one game cannot lock the other out; a
  shared pool was the earlier design and is withdrawn."
- The refusal policy is **inverted**: at quota the runner evicts *that game's*
  least-recently-ticked sandbox rather than refusing the new bot. §7.1
  justifies it correctly — the game owns the script (§1) and the remember blob
  rides the tick, so an eviction costs compile time, not state.

That is strictly stronger than what I flagged. My finding was that the shared
pool needed a reservation rule; the fix removes the shared pool instead, which
has no fairness question to leave unspecified.

## What the fix correctly added alongside

- **`cold: true`** in the tick result (`:105-112`), so eviction churn is a
  signal the game can see rather than latency it must infer. Given eviction is
  now the normal over-quota path rather than an error, this is necessary, not
  decorative.
- **Refusal demoted to last resort** (`:319-323`): `429 sandbox_limit` only when
  the requesting game's own quota is 0 or one sandbox exceeds the instance's
  memory limit. That is a coherent last line after evict-owns-LRU.
- **Probe port 8081** (`:33-36`), separate from the contract port, so probes
  answer when the contract port is saturated. Right reasoning — a probe that
  queues behind the load it is monitoring reports health by timing out at a
  moment when the answer matters.

## The new item (§10, not a blocker)

**`:323` cites "the instance's memory limit" as though it were a stated field.
It is not defined anywhere in the contract.**

This matters more after the quota split than before it, because the split
raised the ceiling:

- One sandbox's heap cap is **32 MB** (`:270`, `:341`).
- One instance now serves up to **8 + 256 = 264** sandboxes.
- 264 × 32 MB = **8.2 GB** of QuickJS heap if both pools fill — cardgame's
  share alone is 8.0 GB.

§11 says one instance serves both games; §7.1's scaling note says a second
replica is out of v1. So that 8.2 GB lands on one pod, and the contract states
no memory request/limit for it. §10 lists cardgame's *number* as needing
confirmation but not whether the resulting pool fits on a node.

Why it belongs in the contract and not in deployment: `:323` already makes the
instance memory limit a **contract term** — it is the condition under which a
tick is refused rather than evicted. A term the contract enforces but does not
state is one an implementer will set from whatever the node happens to have.

Recommend §10 gains: *"The runner instance's memory limit, and therefore whether
cardgame's 256 × 32 MB heap fits on one node. Both quotas are unmeasured; at
full occupancy the pool is ~8.2 GB of heap on a single instance."* Cardgame
should see that arithmetic before confirming 256.

Not a gate failure: both numbers are already marked proposed and unmeasured,
the eviction path degrades safely (evict + recompile) rather than crashing, and
an under-provisioned limit surfaces as `worker_died` or OOM — visible, not
silent. It is the kind of unstated term that becomes a prod incident, which is
why it goes in the document now.

## Re-checked, unchanged and still correct

- `TICK_DELAY = 2.0` at `agent/config.py:89`; 250 ms = 12.5% of the interval,
  arithmetic right. Re-verified against `0e42337`'s text, which is unchanged.
- 12 limit rows, stricter than the spec's own table (no on-breach column, no
  stack row in the spec).
- The async replacement delta and the asyncify-pin justification correction are
  untouched by this diff.
- `api.log` appears in the limits/rate rows and the binding table with no
  exclusion list, so the earlier contradiction stays resolved.

## Scope

Document gate only. Nothing executed beyond read-only `git` and arithmetic.
I did not measure memory per sandbox — 32 MB is the contract's own heap cap,
which is the right figure to size against and is what I used.
