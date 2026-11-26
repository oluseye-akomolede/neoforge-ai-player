# Review: host-api-count-seven R-1 fix (`de009e5`)

**Verdict: PASS on what was asked; one new finding (F-1) that this change did not
introduce but that its own new sentence now makes a claim about, and that sentence
is broader than what is true.**

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `de009e5` (parent `cec433d`; base `c920f6a`)
- Row: `qitem-20261126231451-84f92ddc4f7c42db`
- Prior reviews: `...-host-api-count-seven-315f12e.md` (F-1), `...-f1-cec433d.md` (R-1 raised)

Every claim below was produced by me from the revs named. Scratch worktree removed.

## R-1 is closed, correctly

The requirement now ends: "Both cites were checked at runner `b48c4ad`, so a reader
can re-derive them instead of trusting this date." That is exactly the fix I asked
for, and the rev chosen is the right one.

**The rev claim verifies.** The builder says their runner worktree is at `b1cd6f5`,
one commit past `b48c4ad`, touching neither cited file, and that they named
`b48c4ad` because that is the rev I read them at. Checked rather than accepted:

- `git diff b48c4ad b1cd6f5 -- src/binding.js src/engine.js` → **empty**.
- `git show --stat b1cd6f5` touches `src/look.js` and two test files only.
- The three cited `binding.js` lines (`:327` `  return {`, `:412`
  `    result(value) {`, `:496` `  };`) are byte-identical at both revs — printed
  and compared, not inferred from the empty diff alone.

Naming the rev I read rather than their HEAD was the right call and they gave the
right reason: it is the one a later reader can check from either side.

**The symbols were right to leave alone.** `:327-496` is already described as "the
`api` object `createApi` returns; `result` is at `:412`", and the engine cite names
`#installSnapshot`. What was missing was the rev, not the symbol. Agreed.

## Re-verified, computed myself at `de009e5`

- **Scenarios per requirement:** 3/3, 8/8, 2/2, 3/3 — names as ordered lists, delta
  against live. 16 delta, 16 live. R4's two scenario blocks are byte-identical to
  live (compared with the full text visible, not only the headers).
- **Zero occurrences of "six"** in the delta.
- **The seven-method set still resolves:** `binding.js:327-496` at `b48c4ad`
  enumerates exactly `do, say, send, recall, result, remember, log`. `engine.js:737`
  `  #installSnapshot(snapshot) {`, `:843` the `setProp(global, "snapshot", …)`,
  `:850` closes it.
- **Validates, rc read directly** in a scratch worktree detached at `de009e5`:
  `host-api-count-seven --strict` rc=0 "is valid"; `bot-coded-agents --strict` rc=0,
  INFOs only, no leak to the live spec.
- **No live-spec edit:** diffstat is two files, both under the change dir.

## F-1 (new, pre-existing text, now over-claimed by the new sentence)

The added sentence says **"Both cites were checked at runner `b48c4ad`"**. In a
requirement that carries more than two cites, "both" reads as the two I raised and,
to a later reader, as *a guarantee about this requirement's cites*. That guarantee
does not extend to the others, and two of the others are wrong at `b48c4ad`:

| Cite | What the sentence says it is | What `b48c4ad:src/…` line actually holds |
|---|---|---|
| `binding.js:126-136` | "`createApi` already takes `botState` as a parameter" | `createTickState(...)` — a **different function**, and the sibling of the state object the comment exists to distinguish from `botState` |
| `engine.js:249` | "creates it" (the long-lived `botState`) | `// field itself, so handing it a different object…` — a **comment line** |
| `engine.js:783` | "passes it every tick" | `?.replace(/ /g, "\\u2028")` — the snapshot **JSON escaping** |
| `fleet.js:166` | "reuses the worker across requests" | `let worker = this.#workers.get(botId);` — **correct** |

`engine.js:2-12` is correct: it is the module doc comment stating "No filesystem and
no network", which is what that sentence leans on. That one carries real weight (it
is the argument that logging script source leaks nothing) and it holds.

**Why `binding.js:126-136` is the sharpest of them:** `binding.js:111` is
`export function createBotState()`, and `109-135` is precisely the range this change
already corrected *away from* in task 1.6 — "`binding.js:109-135` (createBotState, no
api surface → `:327-496`)". The surviving `126-136` lands **inside that same stale
range** and now names `createTickState`, the other half of a distinction the nearby
comment spells out. I checked whether it was ever right: `botState = createBotState`
appears inside `126-136` at exactly one rev of the last 60, `4c8bc07`, which is
**53 commits before** `b48c4ad`. So this cite was stale before this change and is
stale now.

The correct locations at `b48c4ad`:
- `botState` parameter: **`binding.js:194`** (`botState = createBotState(),`,
  inside `createApi`'s options object, signature at `:192`); factory at `:111-118`.
- long-lived state created: **`engine.js:254`** (`this.#botState = botState ?? createBotState();`).
- passed to the api: **`engine.js:853`** (`botState: this.#botState, …` inside
  `#installApi`).
- `acceptAction`: **`binding.js:214-225`** (the cite `:154-174` resolves to the end
  of `createTickState` instead).

**Not a regression from `de009e5`, and not a reason to hold the archive of the
count fix** — but the new sentence is now the thing that makes these falsifiable and
simultaneously asserts they were checked. Either narrow the sentence to the two cites
it means ("The `binding.js` and `engine.js` snapshot cites above were checked at
runner `b48c4ad`") or widen the check until it is true of all of them. I would
prefer the second, because the four above are the same defect species as the two that
were fixed, and a reader who re-derives one and finds it wrong will stop trusting the
rest.

## On the builder's self-flagged process point

They note that fixing R3 by piecemeal substitution duplicated a sentence twice
before they replaced the paragraph whole, caught both times by re-reading the
rendered block, and that "did the replace match" is not a sufficient check. That is
correct and worth keeping. The rendered block is the right unit here: the fragment
they were editing ends mid-clause ("with\n the binding."), so a match-only check can
leave a sentence that reads fine in isolation and wrong in place.

## Instrument notes (mine)

- My first attempt at the R4 scenario byte comparison used an `awk` range with an
  apostrophe inside a single-quoted program; both extracted files were **0 lines** and
  `diff` returned equal, printing a confident "R4 SCENARIOS IDENTICAL" from two empty
  inputs. Caught by the `wc -l` beside it. Re-ran on explicit line ranges with the
  content visible. The finding above is from the clean run; the empty result is
  discarded.
- An earlier era scan for `126-136` reported five matching revs because the pattern
  included a bare `botState,` alternative that matches `createTickState`. Tightened
  to the exact construct before reporting; the one-rev answer is from the narrow scan.

## Summary

R-1 closed on the terms it was raised: the rev is named, the rev is the right one,
and the claim about `b1cd6f5` verifies. The four-method set, the scenario table and
both validates are clean at `de009e5`. One new finding: the new sentence's "both
cites" reads as a guarantee over a requirement that carries more, and four sibling
cites in that requirement are wrong at `b48c4ad` — one of them inside the very range
this change already corrected. Fix that sentence's scope or those cites; neither
blocks the count fix itself, and the archive remains the lead's call.
