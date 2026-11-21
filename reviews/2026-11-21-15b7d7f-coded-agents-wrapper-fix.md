# Review: 15b7d7f — coded-agents stops teaching the inventory wrapper path

Rev: 15b7d7f (neoforge-ai-player, branch ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21
Related: a81d5d1 (review ddc89db), F-3 from that review; lead chose option 1.

## Verdict: PASS

Doc-only, as the commit claims. Three files, +70/-33, no executable line changed.
`validate --strict` rc=0 on both `coded-agents` and `script-say-dedupe`.

## What I verified rather than read

Every quantitative/structural claim in the new prose, run at 15b7d7f:

1. **The three Java cites are exact.** Read at a81d5d19:
   - `:469` `sendJson(exchange, 200, Map.of("inventory", bot.getCachedInventory()));`
   - `:504` `case "entities" -> ... Map.of("entities", bot.getCachedEntities())`
   - `:505` `case "blocks" -> ... Map.of("blocks", bot.getCachedBlocks())`

2. **The mobs/entities mapping at spec:943 is accurate, though confusing.**
   The sentence maps `state.nearby.mobs` to `:504`, and `:504` is the *entities*
   endpoint. That is correct because `snapshot.py:119` keys the local entry
   `"mobs"` while reading the `entities` endpoint and the `"entities"` wrapper key:
   `"mobs": _obs("entities", lambda: api.entities(...), "entities")`.
   A script author reading `:943` could easily think `mobs` is a typo for
   `entities` — it is not. Worth one clause in a later pass, not a defect: the
   mapping IS right, and `look.entities` is the script-facing name while
   `state.nearby.mobs` is the snapshot-dict name, so both spellings are live and
   they denote the same data by different names at different layers.

3. **The `_obs` behaviour the prose describes reproduces exactly.** I drove the
   real `snapshot.build_state` at the rev with a real wrapped API double:
   - `{'inventory': [{slot,item,count}]}` -> `state.inventory` is a **list**, errors `[]`
   - `{'blocks': [...]}` -> `state.nearby.blocks` is a **list**
   - `{'entities': []}` -> `state.nearby.mobs` is `[]`
   - `{'error': 'Bot not found'}` -> `[]` **plus** `{'reader':'inventory','error':'wrapped-value-not-a-list','got':'NoneType'}`
   - a raising reader -> `[]` plus `{'reader':'entities','error':'RuntimeError'}`
   So "keeps a bare list, unwraps the key, otherwise `[]` and a reader error" is
   true of the shipped code, not just of the docstring.

4. **The "opposite directions" claim is directionally correct, one word loose.**
   The new text says reading the list's `.length` on a wrapper gives `undefined`,
   and "unwrapping a list gives `undefined` too". The first is exactly right.
   The second is loose: `state.inventory.inventory.length` on a **list** does not
   give `undefined`, it **throws** a TypeError — unless guarded. The shipped
   guard (`scout.js:110`) is `Array.isArray(state.inventory) ? ... : []`, so in
   practice it degrades to `[]` and fails closed, never reaching `.length`.
   Both readings still "fail silently / never fire", so the *consequence* the
   prose draws is correct; only the mechanism word is imprecise. See F-1.

5. **No live wrapper instruction remains.** Every `state.inventory.inventory`
   surviving in the tree is inside historical narration ("an earlier revision
   had it read ..."). Verified in both files by reading the surrounding lines,
   not by grep count alone — a grep hit that is the sentence *describing* the old
   bug is not a live instruction, and both are clearly framed as history.

## Findings

### F-1 (minor, prose): "unwrapping a list gives undefined" is imprecise
The spec note says both wrong readings yield `undefined`. On a list,
`state.inventory.inventory` is `undefined` but `.length` on it throws. The
shipped guard is Array.isArray-protected so it degrades to `[]`, which is why
nothing breaks. Suggested one-word fix: "unwrapping a list gives `undefined`, and
`.length` on that throws". Not blocking — the argument the paragraph makes (both
wrong shapes fail closed, so pin the shape with a test) stands either way.

### F-2 (nit, task 9.6): "records a reader error" is right; the shape is worth naming
tasks.md:485 now says an unusable body stores `[]` AND appends a reader error
naming the reader. Confirmed: the error entry is
`{"reader": ..., "error": ..., "got": ...}` with `error` taking one of
`wrapped-value-not-a-list` / `unexpected-shape` / the exception's type name.
Naming those three in the task would let an implementer assert on them directly.
Optional.

## Not verified

I did not re-run the suites on this commit — it is doc-only with no executable
line changed, and the claim under test is a documentation correction whose
substance I verified against the code directly. If the builder wants a suite
count on record for 15b7d7f I will run the declared ones on request.

## Process

This closes F-3 on a81d5d1: the conflicting requirement at coded-agents:1162 is
now the list shape, the task entries are corrected, and the 1b4371b message
discrepancy has a correction of record in script-say-dedupe/design.md section 8
that says to read the tree rather than the message — which is the right fix,
since rewriting the message would have hidden the fact that a message and a tree
disagreed at all.
