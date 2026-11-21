# b9edb63 unwrap observations — HOLD, not a pass

**Verdict: HOLD.** The spec delta is good and the `_obs` helper is correct, but
the work is **uncommitted and red in the tree it was built in**. One live
consumer still reads the old wrapped shape, and nothing on disk is at a sha.

Row: `qitem-20261121214349-4c44ffdbf8b23393`, marked urgent.
Tree: `/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player`, HEAD
`3507338` (branch `minecraft-wt-deepseek`).

## F-1 (blocking): the work is not committed, and `b9edb63` does not exist

The row calls this "the code I will build" and says "nothing is built yet".
The working tree has it built, and more: `git status` is

```
 M agent/snapshot.py
 M agent/test_snapshot.py
 M agent/tools/gen_envelope_fixture.py
 M openspec/changes/script-lookups-and-results/specs/bot-coded-agents/spec.md
```

`git show HEAD:agent/snapshot.py | grep -c _obs` → **0**. HEAD has none of it.
And `git cat-file -t b9edb63` in both worktrees → **missing**; the rev named in
the row's own title has never been created. So there is nothing to review "at"
and nothing a deployer could find. Commit it, then name the sha.

## F-2 (blocking): a live script reads `state.inventory.inventory`

`agent/scripts/scout.js:107`

```js
var inv = (state.inventory && state.inventory.inventory) || [];
```

With `_obs` unwrapping inventory, `state.inventory` is now the **list**, `.inventory`
on it is `undefined`, and scout stores an empty inventory — permanently, because
its own comment at `:82-93` documents the wrapper as the reason the guard looks
this way. This is not a dead-code risk: it is on the live script path.

Measured, in the builder's own tree, no mutants applied:

```
Ran 78 tests — FAILED (failures=1, errors=1)
FAIL: test_the_scripts_inventory_path_resolves
  AssertionError: 1 != 0 : snapshot.state.inventory.inventory is the path
  scout.js:107 reads; it must hold the bot's items
```

The red test is right and the code under test has already moved past it. The
row's required proof (a) — a test over the REAL wrapped shapes — found a real
consumer the row's task 4 did not list. Task 4's claim "the unwrap in build_state
is single-site and changes nothing for legacy readers" is true of the **Python**
readers and misses this one, because `scout.js` is JavaScript.

The fix is a one-line script change (`state.inventory` is already the list), and
`test_script_tick.py:669` must move with it. **The spec delta is correct here**:
`snapshot.py:43` has always declared `"inventory": []`, a list, so the script was
reading a shape the contract never promised. Fix the reader, not the unwrap.

The `errors=1` is `test_planner_prompts` failing to import, unrelated to this
change and pre-existing (module-level import); not part of F-2.

## What does pass

- **Spec delta** (`f37d337`, uncommitted `M`): the requirement at `:391` and its
  four scenarios read correctly, and the source-of-truth cites are real —
  `HttpApiServer.java:469` `Map.of("inventory", …)`, `:504` `entities`,
  `:505` `blocks`, read at source. `openspec validate
  script-lookups-and-results --strict` → valid, rc=0.
- **`_obs` helper** (`snapshot.py:72-107`) does what the delta says: list kept,
  mapping → inner list, anything else → `[]` plus a reader error naming the key.
- **Mutants** (both shapes, `python3 -B`, restored with `cmp`):
  - unwrap removed entirely → **3 failures, 2 errors**, including
    `test_the_games_wrapped_response_becomes_a_list`.
  - mapping branch dead (`if False and isinstance(raw, dict)`) → **6 failures,
    1 error**.
  Both red, so the new tests bite the property they name. This is the required
  proof (b) and it holds.
- **Generator** (`gen_envelope_fixture.py`): now hand-writes the WRAPPED
  responses and pushes them through `build_state`, which fixes the third
  instance of the fixture lying rather than moving it.

## Not claimed

- I did not run full agent discovery; I ran `test_snapshot`, `test_script_tick`,
  `test_planner_prompts` (78 tests).
- I did not check `prompts.py:170-197` / `agent.py` / `sessions.py` readers
  myself; the builder's task-4 grep is plausible and `scout.js` is a reader it
  did not cover, which is why I am not signing off the others unseen either.

## To pass

1. Fix `scout.js:107` and `test_script_tick.py:669` together.
2. Commit everything and name the sha in the row.
3. Re-run `test_snapshot test_script_tick` and quote the counts.
