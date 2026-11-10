# Gate — coded-agents delta at 11e7073 (full delta, not a head confirm)

Rev under review: `11e7073` (branch `minecraft-wt-deepseek`)
Range: `0e42337..11e7073`, 526 lines across 8 files
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS** on all three checks. One implementation hazard named below,
inside the check the lead asked for, not outside it.

Read from the rev via `git show 11e7073:…`. `git branch --contains 11e7073` →
`minecraft-wt-deepseek` (and its `controlplane` remote).

## Scope of the delta, and where 526 lines come from

| commit | what | lines |
|---|---|---|
| `2cd6d8f` | `allowance_exhausted` row points at the settled unit decision | 1 +/1 − |
| `3c00e33` | owner chose option 3: cap settled per bot | 74 +/66 − across proposal, spec, tasks |
| `11e7073` | contract names the per-bot cap and where it is counted | 4 +/1 − |
| (in range) | my own reviews plus `a01533a`'s review placement | ~336 |

By file, the 526 splits as **336 lines of review artefacts** (my three reviews and
`a01533a`'s placement of `reviews/REVIEW-spec-b3e64cc.md`) and **190 lines of
product text** — `spec.md` 119, `contract-v1.md` 31, `proposal.md` 23,
`tasks.md` 17, insertions counted.

That second half is not all new to this review. `0e42337` is a *side branch*, so
the range also carries the spec chain from `b3e64cc` through `d2180ef` that I
gated at their own revs (`b3e64cc` PASS, `0c97a38` PASS, `d2180ef` PASS). Those
are re-read here only for consistency with the per-bot rewrite, not re-gated.

`3c00e33` is the substantive commit and I read it as a rewrite, not a head
confirm.

## (a) The per-bot cap matches the owner's answer

The owner's answer, as recorded: option 3, no bot-to-player link; cap counted
per bot; set in mod settings; default unlimited; no player identity needed;
per-player is a later change. Checked point by point against `11e7073`:

| requirement | where | holds |
|---|---|---|
| counted per bot | spec `:434-437` "The cap MUST be counted per bot… a bot's usage MUST NOT be summed with any other bot's" | yes |
| from `cpu_ms` | contract §5: "counted by the game from the per-bot `cpu_ms` it already receives" | yes, and `cpu_ms` **is** per bot — it is a result field of a tick call keyed by `bot_id` (§4), so the sum is well-defined per bot with no extra plumbing |
| set in mod settings | spec `:432-437`, `serverDir/config/aiplayermod-*.json` | yes |
| default unlimited | spec `:433`, limits table `:128` "Daily code hours per bot | unlimited" | yes |
| no player identity needed | spec scenario "no player identity is required to record it", cap requirement "No player identity is required to enforce it" | yes |
| per-player is later | spec `:439-442` "Adding it later is a separate change that requires that identity first; it MUST NOT be introduced by reinterpreting this cap" | yes, and it names the failure mode rather than only the deferral |

The unmetered half is now metered properly too: "Code Time Is Metered Per Bot"
drops the owner attribution the old title carried, so the requirement no longer
promises an attribution the codebase cannot make.

Residual per-player language in the tree, checked by grep across the spec, the
contract and the proposal: **one hit, and it is correct** — spec `:434` states
per-player accounting is out of scope. The limits table, the two requirement
titles, both affected scenarios and `tasks.md` 5.1/5.2/5.4 are all rewritten or
removed, not left contradicting the requirement.

`tasks.md` 6.2 is **removed as a task rather than deferred**, with the reason
given: "so no implementer tries to invent an ownership check." That is the right
call — a deferred task on an unbuildable premise is an invitation.

## (b) Shared changes, for cardgame-lead

The full delta touches `contract-v1.md` in one commit. Everything shared is in
these five lines:

```diff
--- a/openspec/changes/coded-agents/contract-v1.md
+++ b/openspec/changes/coded-agents/contract-v1.md
 §5 Result fields (**SHARED**)
+Each game applies its own daily cap from these — minecraft's is **per bot**
+(owner decision, 2026-11-10 14:12Z; see the spec's "Daily Code-Hour Cap"),
+counted by the game from the per-bot `cpu_ms` it already receives. The runner
+enforces no daily cap.
```

**This is additive commentary, not a wire change.** To be precise for
cardgame-lead, because "SHARED" is the word that makes them read it:

- **No new field.** `cpu_ms` already exists in the §5 result table and was
  already required by both games.
- **No changed field type, unit or meaning.** §5's table is untouched by
  `11e7073`; the diff is a paragraph inserted after it.
- **No new obligation on the runner.** The paragraph explicitly discharges the
  runner: "The runner enforces no daily cap."
- **What cardgame inherits is a decision rule, not a requirement:** each game
  derives its own cap from per-tick `cpu_ms`; the runner is not the place to
  enforce one. If cardgame's own cap is not per bot, that is theirs to state —
  this text says "minecraft's is per bot" and does not generalise.
- Everything else shared from earlier revs is unchanged by this range: §6's
  outcome classes, §7's capacity fields, §11's one-runner-two-games split, and
  the per-game quota at `0e42337` that I already passed.

The instance-OOM / instance-memory-term text the lead listed is in this range
too (`d029546`, inside the merged `863bd97` chain) but predates `0e42337`'s
follow-on and is not modified by these three commits.

## (c) `validate --strict` and `show`

Run in the tree that has the change checked out —
`/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player` at `11e7073`:

- `openspec validate coded-agents --strict` → **"Change 'coded-agents' is valid"**, rc 0.
- `openspec show coded-agents` → clean, prints the proposal, rc 0.
- Spec now carries 14 requirements / 43 scenarios, up from 13 / 39 at `b3e64cc`:
  one added requirement (the reporting-shape one, `0c97a38`) and four added
  scenarios (3 from the reporting requirement, 1 from `3c00e33`'s "One exhausted
  bot does not stop another"). The two renamed scenarios in `3c00e33` are
  renames, not drops — the whole file is under `## ADDED Requirements`, so no
  scenario here can be removing live behaviour.

**A caution for the lead, since it nearly cost me a false FAIL:** the same
commands in *my* worktree at `8289a30` return "has no proposal.md yet" and "no
deltas found", because the change is not checked out there. Both commands exited
**0** while printing `✖ Error` — the exit code does not carry the verdict here,
so read the words. This is the third time in this chain that a check run in the
wrong tree produced a false negative; it is worth the reviewer and builder
agreeing to always print `git rev-parse --short HEAD` and the change directory
before quoting a validate result.

## One implementation hazard, inside (a)

The contract says the cap is "counted by the game from the per-bot `cpu_ms` it
already receives". That is sound, and it also fixes the unit, which the spec
alone did not:

- `cpu_ms` is microseconds-defined as **CPU milliseconds spent in the sandbox
  this tick**, i.e. CPU time, not wall-clock time. The spec's limits table
  prices the cap in **hours/day**. Summing a CPU-time counter and comparing it
  to a wall-clock daily budget will drift, and the cap will effectively never
  fire on a mostly-idle fleet: a bot that ticks once a second for 24 hours with
  2 ms of CPU per tick accrues 172.8 s, or 0.048 hours, not 24.
- That is not a defect in this rev — it is a consequence of choosing the field
  that already exists over adding one — but some implementer will discover it
  when the cap is first enabled and "unlimited" becomes "limit that never
  triggers".
- The cheapest fix is one clause in the spec's cap requirement naming the
  quantity: either "CPU-hours measured from `cpu_ms`" (consistent with the
  contract, and honest that the budget is compute rather than time) or
  "wall-clock hours", which the contract cannot supply and would need a field.

Not blocking: the rev does not contradict itself, and the contract's choice is
the one that needs no new wire field. But the cap's *unit* is now decided while
its *quantity* is not, and the difference only shows up when someone turns the
cap on.

## Verified, not taken

- `git branch --contains 11e7073` → `minecraft-wt-deepseek`.
- `git diff --stat 0e42337..11e7073` reproduced exactly: 8 files, 526
  insertions, 66 deletions. The lead's line count is right.
- Scenario and requirement headers diffed by name across `3c00e33^..3c00e33`:
  2 scenario renames, 1 scenario added, 0 removed; 2 requirement renames, 0
  removed.
- No review artefact of mine was modified by these commits; `a01533a`'s copy of
  `REVIEW-spec-b3e64cc.md` is still byte-identical to mine at `11e7073` (3592
  bytes, `diff` clean).
