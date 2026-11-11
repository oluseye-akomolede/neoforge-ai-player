# Gate — contract v1 at d029546 (instance memory limit + OOM transport class)

Rev: `d029546`. Row qitem-20261110113146-ebc72e31d10d4ba7.
Read from the sha (`git cat-file -t d029546` → commit; files via `git show d029546:`).
Diff scope since `0e42337`: `contract-v1.md` (+22) and my own review file. No spec delta moved.
Date: 2026-11-10T11:36Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS, with one scale note**

## My §10 item is taken, including the reason

`:332-337` now states the instance memory limit is a **contract term**, not a
deployment detail, with the argument I made: a term the contract enforces but
does not state is one an implementer sets from whatever the node has. It adds
the arithmetic — ~8.2 GB of QuickJS heap at full occupancy — and marks it
**not yet value-stated**, must be before the freeze.

§10 gains the matching item (`:411-417`), naming cardgame's share (8.0 GB) and
asking them to see the arithmetic before confirming 256. That is exactly the
disposition I asked for: stated, quantified, not invented, and not promoted to a
blocker on numbers already marked unmeasured.

## The OOM transport class is a good addition I did not ask for

`:278-283`: if the instance is OOM-killed there is no runner left to report, so
the tick fails as a **transport** error, not a per-tick outcome — and
explicitly warns a reader not to read `worker_died` as covering it, since that
class means one sandbox was lost and replaced and says nothing about the
instance.

That closes a real hole. `worker_died` is the nearest-looking class and the
wrong one; the difference is whether the game lost one worker or the whole
endpoint. Without the sentence an implementer would plausibly fold OOM into
`worker_died` and then lose the instance-level signal entirely.

I checked the behaviour it points at exists rather than being newly asserted:
`bot-coded-agents/spec.md:476-513` requires an unreachable runner to be detected,
bots to fall back to the existing planner, the condition to be reported in the
bot interface, and recovery without restart or replay. `deadline_ms: 250` bounds
how long a dead endpoint can go unnoticed at one eighth of a decision period. So
"the game treats it as a runner loss" has a specified referent; it is not a term
introduced here.

## The scale note (not a blocker, not a document defect)

Every existing scenario in that requirement is about **one bot** or **one waiting
agent**. An instance OOM-kill is the one failure that hits every bot in both
games at once: 264 sandboxes gone, every scripted bot falling back to the
planner simultaneously, and every one of them retrying against the same dead
endpoint.

The spec does not describe that aggregate case, and it does not need to for v1 —
fallback is per-bot and idempotent, and the recovery scenario already forbids
replay. But the *bot interface reporting* requirement ("the condition MUST be
reported in the bot interface") becomes 264 simultaneous reports, which is a
different presentation problem from the one the scenario was written for. Worth a
sentence in §10 when the memory limit is set, since the limit is what decides
whether OOM is a node-level event or a routine one.

I am not asking for a spec change: the requirement is correct as written and the
failure it describes is handled. This is a note for the same §10 item, not a
second item.

## Re-checked at this rev

- TICK_DELAY 2.0 at `agent/config.py:89` → 250 ms = 12.5% of the interval. Unchanged.
- Per-game quota, evict-own-LRU, `cold: true`, probe port 8081 — untouched by this diff.
- `api.log` stays resolved; async replacement delta untouched.
- No new row in the per-tick class table — OOM is deliberately outside it, and the
  text says so, which is the stronger choice than adding a class the runner
  could never emit.

## Scope

Document gate only. Read-only `git` and grep; nothing executed, nothing measured.
The 8.2 GB figure is arithmetic on the contract's own stated numbers (32 MB heap
cap x 8 + 256 sandboxes), taken from the document, not measured on a node.
