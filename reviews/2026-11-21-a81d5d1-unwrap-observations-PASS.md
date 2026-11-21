# a81d5d1 unwrap observations — PASS

**Verdict: PASS.** F-1 and F-2 are both closed at a real, committed sha, and
every count the builder quoted reproduced. One finding (F-3) is a spec
inconsistency outside this diff's scope; it does not block this commit.

Supersedes the HOLD in `2026-11-21-b9edb63-unwrap-observations-HOLD.md`.

Reviewed at: `/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player`,
`git rev-parse --short HEAD` → **a81d5d1**, `git status` clean.

## F-1 closed

`git cat-file -t a81d5d19` → `commit`. The eight files are committed, including
`agent/scripts/scout.js`, `deploy/agent-scripts.yaml`, and the spec delta.

## F-2 closed

`a81d5d1:agent/scripts/scout.js:108`:

```js
var inv = Array.isArray(state.inventory) ? state.inventory : [];
```

Read at the commit, not the working tree. The reader was fixed and the unwrap
left alone, as the delta requires.

## Counts — all reproduced

| Check | Builder | Mine |
|---|---|---|
| `test_snapshot` + `test_script_tick` | Ran 78, OK | **Ran 78, OK**, rc=0 |
| `test_scout_script` | Ran 27, OK | **Ran 27, OK**, rc=0 |
| runner `npm test` | 190/190 | **190 pass, 0 fail**, exit 0 |

## Mutants — all reproduced, all restored with cmp

| Mutant | Result |
|---|---|
| unwrap removed entirely (`snapshot.py`) | **3 failures, 2 errors** of 26 |
| old wrapper guard restored in `scout.js` | **21 failures, 1 error** of 27 |
| `deploy/agent-scripts.yaml` drifted from source alone | `test_configmap_matches_the_script` **FAILED** |
| `scout.js` drifted from `yaml` alone | `test_the_scout_script_reads_the_inventory_list_the_snapshot_sends` **FAILED** |

I checked the drift test separately because a gate that cannot red is inert: it
lives in `test_script_tick.SnapshotWireShapeTest` (not `test_scout_script`, where
I first looked), and it does red on a restored wrapper guard. The ConfigMap pair
is bidirectional — mutating either side alone reds its own gate.

`openspec validate script-lookups-and-results --strict` → valid, rc=0.

## F-3 (not blocking this commit): `coded-agents` still requires the wrapper

`openspec/changes/coded-agents/specs/bot-coded-agents/spec.md:1162`:

> **THEN** `snapshot.state.inventory.inventory` in the script is the stack list,
> and the guard does not report the inventory as empty

That scenario is the *opposite* of what `script-lookups-and-results` now
requires, and `coded-agents` is an **active change (29/45 tasks)**, not
archived — so it will not be silently superseded. It also reads as having been
written *because* of this exact bug (its whole point is that the guard must not
report the inventory as empty), which makes it a fix aimed at the wrong layer.

Nobody is at fault for this landing in `a81d5d1`: it is in a different change
directory and predates the delta. It matters because whoever picks up
`coded-agents` next will implement the wrapper path and undo this fix, with a
green suite. The owner of that change should strike or rewrite the scenario.

`coded-agents/tasks.md:373` and `:486` carry the same stale path and should move
with it.

## Not claimed

Full agent discovery. The builder reports `Ran 483, errors=1` (dashboard
`uvicorn`, outside this diff); I did not re-run it and do not certify it.
