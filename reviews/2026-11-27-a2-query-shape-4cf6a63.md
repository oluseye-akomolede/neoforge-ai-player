# Review: A2 declared-query result shape (`4cf6a63`, spec `7d1bf8d`)

**Verdict: PASS.** The defect is real, the fix is correct, the red evidence is genuine
behavioural red, and the stub it replaces was in fact asserting the bug's own assumption.
One observation (O-1) about a *mod-side* limitation the spec now glosses, which is not a
defect in this commit and not a blocker.

- Repo: `neoforge-ai-player`, branch `fix-declared-query-shape`, tip `4cf6a63`
- Spec commit pinned in the row: `7d1bf8d` (rewritten `openspec/changes/script-lookups-and-results/specs/bot-coded-agents/spec.md`, +24)
- Implementation commit: `4cf6a63`, parent `c97948b`
- Row: `qitem-20261127114039-f7370dc8`

Everything below was measured by me from `4cf6a63`, `7d1bf8d` and the Java source at that
rev. Scratch tree in `/tmp/a2q` from `git archive 4cf6a63`, removed after use.

## The wire shapes are as claimed

Read from `src/main/java/com/sigmastrain/aiplayermod/api/HttpApiServer.java` at `4cf6a63`:

| verb | line | shape |
|---|---|---|
| `find_blocks` | `:1126` | `Map.of("blocks", boundedJoin(blockFuture))` |
| `find_entities` | `:1136` | `Map.of("entities", boundedJoin(entityFuture))` |
| cached `blocks`/`entities` | `:540-541` | `Map.of("blocks"/"entities", ...)` |
| `block_at` | `:589-601` | the block map itself, sent directly |
| `locate` | `:616+` | its own `found`/`error`/`candidates` fields |

No `ok`, no `kind`, no `matches` anywhere on the list verbs. The premise of the commit is
correct: a script written as the spec's example read `undefined` from a good answer.

## The stub really was asserting the bug

`test_script_tick.py:974` returned
`{"ok": True, "kind": "blocks", "matches": [...]}` from `find_blocks` — the exact shape the
agent was supposed to *produce*, handed in as the input the agent *receives*. That is the
false-green species: a fixture-shaped gate that tests the assumption rather than the code.
It now returns `{"blocks": [...]}` and asserts the rename on the output side, which is a
test of the seam rather than of a restatement.

The new `assertNotIn("blocks", ...)` is the assertion that matters — it forbids mirroring,
so the two spellings cannot drift apart later.

## Red evidence is real, verified independently

Reverting **only** `agent/script_tick.py` to `4cf6a63^` and keeping the new tests:

```
ERROR: test_an_entities_result_is_renamed_too        KeyError: 'matches'
ERROR: test_declared_queries_ride_on_the_envelope    KeyError: 'matches'
FAIL:  test_a_list_answer_missing_its_list_is_an_error_not_empty   AssertionError: True != False
Ran 120 tests  FAILED (failures=1, errors=2)
```

Two `KeyError: 'matches'` is the live defect exactly — the script asks for a key the agent
never installed — and the third is the missing-list case reporting empty instead of error.
These are behavioural reds, not missing names. The other 117 pass either way, which is
correct: they do not touch the result shape.

Green at `4cf6a63`: `Ran 120 tests, OK, rc=0` — 46 `declared_queries` + 69 `script_tick` +
5 `result_delivery`, **from inside `agent/`** with `AGENT_SCRIPT_RUNNER` set. The cwd is
named because a count without its directory is not reproducible (last round's error).

## The three behaviours, probed directly

| input | output |
|---|---|
| `{"ok":True}` (list missing) | `{ok:False, reason:"error", message:"blocks returned no blocks list"}` |
| `{"blocks":[{...}]}` | `{matches:[...], ok:True, kind:"blocks"}` — `blocks` **gone** |
| `{"block":"stone","x":1,...}` via `block_at` | fields kept, `+ok +kind`, **no** `matches` |
| `"nope"` | `{ok:False, reason:"error", ...}` |
| `{"blocks":{...}}` (not a list) | `{ok:False, reason:"error", ...}` |

Success is exactly `{ok, kind, matches}` and error exactly `{ok:False, reason, message}` —
matching the spec delta's sentence word for word.

## End to end, the seam driven with real wire shapes

`run_declared_queries` against a fake api returning the **mod's** shapes:

- `ore` → `matches` = both blocks, `ok:true`, `kind:"blocks"`, `.blocks` absent
- `cow` → `matches` populated, `.entities` absent
- `here` (`block_at`) → `block`/`x`/`y`/`z` kept, `+ok +kind`, no `matches`

That is the seam between the producer's real output and the consumer's real function, which
is where a shape claim has to be settled.

## Spec delta (`7d1bf8d`)

Spec-only, one file, +24 and no deletions, inside the pending change
`script-lookups-and-results`. It states the rename, the `block_at`/`locate` exception, and —
the valuable part — that *"a unit test that stubs `find_blocks` to return `matches` directly
does NOT satisfy this requirement."* Writing the anti-pattern into the requirement is what
stops the old stub being reintroduced, and it is more durable than a comment in the test.
Two scenarios added, both matching the implementation.

The parser functions are untouched: `git diff 7d1bf8d 4cf6a63 -- agent/script_tick.py`
matches no line mentioning `_mask_comments`, `_strip_strings`, `_find_declaration`,
`_skip_ws` or `parse_declared_queries`.

## O-1 — a *mod* limitation the new spec text smooths over (not this commit's defect)

`find_blocks` catches its own exception and completes with `List.of()`
(`HttpApiServer.java:1123-1126`), **no error key**. So a failed search and a genuine empty
search are byte-identical at the wire. The agent normaliser cannot tell them apart:

```
find_blocks threw  -> {'matches': [], 'ok': True, 'kind': 'blocks'}
genuine empty      -> {'matches': [], 'ok': True, 'kind': 'blocks'}
```

The commit's own docstring argues that *"searched, found nothing" and "the answer was not
read" are opposite conclusions and only one is safe to report as empty* — and that argument
is right. It is honoured for a **missing** list, but it cannot be honoured for this case,
because the information is destroyed before the agent sees it. Fixing it means changing the
mod's `find_blocks` to carry an error key (as `surface_scan` at `:1420` already does), which
is Java work outside this commit and outside the change's scope as written.

I raised it because the spec delta's sentence "a list answer whose list is missing is an
error" reads as if all unread answers are caught. They are not; only the missing-key case
is. Worth a line in a follow-up row, not a block on this one.

## My own errors, caught before they became findings

- I probed `{"blocks":[], "count":0, "error":"boom"}` and got `ok:true`, and nearly reported
  "a failed search is reported as success". That shape is `surface_scan`'s (`:1420`), not
  `find_blocks`'s (`:1123`), which completes with a bare `List.of()`. I had the wrong verb —
  the same "read the case that owns the line" error as the earlier `HttpApiServer` cite work.
  Corrected before writing, and O-1 above is the accurate version.
- My first end-to-end fixture put `block_at`'s coordinates under `params`; they are top-level
  (`plan_declared_queries:664` reads `query["x"]`). My fixture, fixed, rerun.
- A `[queries] budget exceeded` line prints on a default 32-radius search (274625 cells vs
  `QUERY_SCAN_BUDGET = 65536`) but does not block the result. Pre-existing planner
  behaviour, untouched here; noted only so the lead is not surprised by the log line.

## Summary

PASS. The live defect is real, reproducible as two `KeyError: 'matches'` reds against the
pre-fix source, and fixed in the right layer. The stub that hid it now feeds the real wire
shape and asserts the rename, with mirroring forbidden. The spec pins the shape and names
the stub anti-pattern. O-1 is a mod-side information loss this commit cannot repair and the
spec's wording slightly overstates; it belongs in a follow-up row.
