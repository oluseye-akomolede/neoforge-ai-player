# Contract v1 freeze — confirm at 81a5905

Rev: `81a5905` (parent `aabcba5`), branch `minecraft-wt-deepseek`
Range: `aabcba5..81a5905`, 2 files, 47 insertions / 39 deletions
Reviewer: minecraft-reviewer@minecraft
Verdict: **CONFIRMED, one defect in the §8 row.** The values are right, the
arithmetic is right, the freeze mark says the right thing. The retention row
that was reworded to carry the MUST does not parse as a table row.

Everything below was read from `git show 81a5905:…`, not from the handoff.

## The values, checked against each other rather than each in isolation

- **`max_sandboxes` cardgame 64.** §7 table `:315` reads `8 | 64 | concurrent
  sandboxes per game (keyed by game_id)`. The "why quotas differ" paragraph
  `:323-330` states 64 with the reason and the date. No `256` survives in the
  contract or the spec.
- **Instance memory 4Gi, and the arithmetic holds.** `:351-353`: "~2.3 GB of
  QuickJS heap (8 minecraft + 64 cardgame sandboxes x 32 MB)". I recomputed it:
  8 + 64 = 72; 72 x 32 MB = 2304 MB = 2.25 GiB + 32 MB = 2.28 GiB ≈ **2.3 GB**.
  The spec's four 72s (`:576`, `:586`, `:658`, `:659`) are the same 72. The
  number in the prose, the number in the spec, and the two per-game quotas all
  agree, which is the thing worth checking — 2.3 GB inside a 4Gi limit is
  ~1.7 GiB for Node, QuickJS runtimes and the OS, and that is a stated
  headroom, not a coincidence.
- **`deadline_ms` 250 / `tick_cpu_ms` 20 cardgame: unchanged.** Confirmed
  present and unchanged in the §7 table.
- **cardgame cap metered on their side, no runner field.** §10 last bullet says
  their driver never ticks an inactive script, "so it needs no runner field",
  and names it as the same shape as minecraft's — which is the reason no field
  was added. That is the correct answer to the wire question I raised at
  `349581a`.
- **The freeze paragraph** (`:3-10`) freezes the SHARED shape and every §7
  per-game value, and explicitly does *not* freeze the per-game numbers being
  raised later by the owning game as a value change. That is the right scope:
  it stops the shape drifting while leaving each game its own ceiling, which is
  exactly the distinction that made the cap thread long.

## The fleet-figure move (264 → 72) is right, and belongs here

The builder asked whether this should be its own confirm. It should not. The
scenario's assertion is "the bound does not grow with fleet size" — if the two
fleet sizes are checked against a quota the fleet does not actually hold, the
scenario is arithmetic against a fiction. 72 is now the real number, so the
assertion is against the real quota. It is the same edit as the value change and
splitting it would gate the number without the sentence that depends on it.
All four sites moved together (`:576`, `:586`, `:658`, `:659`) and no `264`
remains in `specs/`.

## The defect: the §8 retention row is not a table row

Rewording the row so an implementer greps it was the right instinct — the row
*is* what gets grepped. But the rewritten row has **four cells where every other
row has five**:

    | `api.log` retention | **unstated for v1** | 7 days | the game, in its own store; ... |

Counted across the table (`:371-382`): twelve rows at 5 cells, this one at 4.
The columns are `limit | value | unit | enforced by | on breach`, so what the
row says when parsed is:

- value = `unstated for v1`
- unit = `7 days`
- enforced by = the prose clause
- on breach = **missing**

Two problems follow, and the second is the bad one:

1. It renders as a row with no breach behaviour, which is a real column for every
   other limit and invites an implementer to supply one.
2. **`7 days` lands in the unit column**, and cardgame's retention is 7 days
   while minecraft's is unstated. So the row attributes cardgame's number to the
   limit as a whole. That is the reverse of what §10 says — §10 (`:422`) has the
   per-game split correct, so the table and the prose now disagree, and the table
   is the one the builder reworded *because it is what gets grepped*.

`openspec validate --strict` passes this. It checks delta headers and scenario
blocks and does not look at Markdown table shape, so it is not evidence about
this row — the same lesson as the validation exit code: the instrument does not
cover the claim.

Fix is mechanical and stays inside this cycle: one cell per game, or a single
value cell that reads "unstated (minecraft) / 7 days (cardgame, their store)" and
a `none — the runner stores nothing` in the breach column. Which it is depends on
whether §8 is meant to carry per-game values at all; §7 uses separate columns for
that, §8 does not, which is what made the row ambiguous in the first place.

## LAYOUT.md — not verifiable from here

`~/minecraft/agent-script-runner` is outside this tree and has no commits, so I
cannot check the `12Gi → 4Gi` and `256 → 64` edits against a rev. I am not
recording them as confirmed. What I can say is that the number they must agree
with is `4Gi` and `64`, both now established in the frozen contract, so the file
has the right targets; its own content is unread. Keeping the two wrong values'
history (2Gi and 12Gi, both sized against minecraft's 256) rather than replacing
them silently is the right call — it records that the failure was using one
game's proposal for the other game's number.

## Verified

- `81a5905^` is `aabcba5`; 2 files, +47 −39; on `minecraft-wt-deepseek`.
- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid",
  0 error/warning lines, run at `81a5905` in
  `/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player` with `rev-parse
  --short HEAD` printed in the same command. Run first in my own worktree, where
  HEAD is `bf471f4` and the change is not checked out; it reported "No deltas
  found" — a tree error, not a rev error, discarded.
- §10 carries the `cardgame-lead` answer id and states the section 10 answers as
  given; the five bullets match the handoff's five, including the reversal from
  256 to 64.
