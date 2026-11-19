# Review: 88c1ff9 + e14ff1e — M3-1 follow-ups and the ConfigMap mirror

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Row: qitem-20261119102953-ba671057fc5eefe3
Under review:
- 88c1ff9 (on dc45196) — closes the three findings in REVIEW-dc45196 (941e223)
- e14ff1e (on 88c1ff9) — regenerates deploy/agent-scripts.yaml scout.js mirror

## Verdict

**PASS on both.** 20/20 green at e14ff1e, reproduced independently, and all
three mutants reproduce with the counts and names the builder cited.

Two things the builder should know and one it cannot fix from here:

1. **A stale comment survives in scout.js** — the `api.py:101` citation is
   corrected in tasks.md but not in `agent/scripts/scout.js:50`, and the
   comment still carries the "NOT a list" absolute that spec 88c1ff9 removed.
2. **M1 is 10 failures + 1 error, not 11 failures.** Same total, different
   composition; `test_guard_reads_the_wrapper_not_a_bare_array` is among the
   failures, so the substance is unchanged.
3. The stale ConfigMap window cannot be closed by a test. Recorded below.

## 88c1ff9 — the three findings

**Finding (spec shape):** fixed correctly. The delta now states the wrapper is
the shape on a *successful* read and a failed read degrades to a bare `[]`,
naming `snapshot.py`'s default, and requires scripts to treat both as no items.
The fixture note now says fixtures MUST cover the degraded case. Verified the
cited mechanism at source: `snapshot.py:57-62` is `_read(name, fn, default)`,
`:71` passes `[]` for inventory. That is exactly the shape my finding named.

**Note 1 (cooldown):** fixed. `STORE_ALL_COOLDOWN_TICKS = 100` is pinned in
task 9.1 as a chosen value with its reason and location (`scout.js:64`), while
the spec keeps the "at least one tick" floor. That is the right split: the
spec asserts a property, the task records the number and why.

**Note 2 (log line):** fixed and better than asked. The line now ends
`(idle)` or `(already deposited)`, distinguishing the two cases that share the
guard's position before the task check. Since those lines are evidence in the
C1/C4 arms, a single ambiguous string would have been a real hazard.

`941e223` is a true ancestor of 88c1ff9 (checked with `merge-base
--is-ancestor`), so my review was carried forward, not amended away.

## e14ff1e — the mirror

**Byte equality verified independently, by my own computation.** Extracted the
ConfigMap with `yaml.safe_load`, hashed the `scout.js` key value, hashed
`agent/scripts/scout.js`: both 9105 bytes, both
`a480675666cda75243f2ee2875b704b9aaddd88128dd5948c958f97342372c10` —
matching the builder's stated sha. One key found, no duplicate.

**The existing guard does cover it, and it was live the whole time.** The
builder said this was "a test I failed to run, not a coverage gap". Checked
rather than accepted:

- `test_scripts_configmap.py` first appeared in `4035605` (2026-11-11),
  eight days before the fix at `e14ff1e` (2026-11-19).
- At its origin rev it carries no `skipUnless`/`skipIf`; `setUp` raises on
  missing PyYAML, so it cannot pass without checking. Its docstring records
  that this replaced a `@skipUnless`, i.e. it was deliberately made
  non-inert.
- Reverted only the mirror to `e14ff1e^` in an otherwise-fixed tree: the test
  **reddens**, with a message naming `scripts/gen-scripts-cm.py`.

So the suite was green because nothing ran it. That is the correct reading and
it is worth recording plainly: **no test can close this class of window.** The
guard is sound; the failure mode is a green suite over a file nobody executed,
and the only defence is running it before deploy.

## Mutants — reproduced, with one correction

Run against `test_scout_script` at e14ff1e, each anchored on the real code line
with a uniqueness assertion (my first attempts at M2/M3 silently no-oped on a
wrong anchor — `const` where the file says `var` — and printed OK; that is the
same trap the builder hit earlier, and the uniqueness assert is what caught it).

| mutant | builder | mine | names |
|---|---|---|---|
| M1 bare-array read | 11 red | **10 fail + 1 error** | incl. `test_guard_reads_the_wrapper_not_a_bare_array` |
| M2 no inventory guard | 2 red | 2 red | `test_empty_inventory_proposes_nothing`, `test_guard_reads_the_wrapper_not_a_bare_array` |
| M3 no cooldown | 1 red | 1 red | `test_cooldown_holds_a_repeat_store` |

M1's 11th is an `IndexError` in
`EndToEndBindingTest.test_the_binding_uses_the_directive_the_engine_emitted`
(`actions` empty, `pairs[0][0]` out of range) — an error, not an assertion
failure. Both are red in the tally, so the mutant is caught either way; the
distinction is only that the end-to-end test reaches the mutant through an
empty list rather than a message.

M3 is a genuinely single-concern mutant: exactly one test reddens, and it is
the one whose name states the concern.

## Findings for 88c1ff9's comment (not blocking)

`agent/scripts/scout.js:47-51` still reads:

```
// WHY THE OBVIOUS GUARD IS WRONG: `state.inventory` is NOT a list. The
// endpoint returns `Map.of("inventory", bot.getCachedInventory())`
// (HttpApiServer.java:469) and the agent stores that body verbatim
// (api.py:101), so the shape is
```

Two problems, both the ones 88c1ff9 fixed everywhere else:

- **`api.py:101` is `def inventory(bot):`.** The fetch is `:102`; the verbatim
  store is `snapshot.py:71`. The sentence's claim ("stores that body verbatim")
  is about the snapshot layer, so `snapshot.py:71` is the correct reference.
- **"is NOT a list" is the absolute the spec delta removed.** On a failed read
  it *is* a bare `[]`. A reader trusting this comment would rebuild the guard
  the spec now forbids.

It is a comment: nothing executes it, so nothing is blocked. It is flagged
because this comment is the load-bearing explanation for why the guard looks
odd, and it is the first thing a future reader checks. A citation that is off
by one, in the reference implementation, is how the next wrong guard gets
written.

## Instrument notes (mine, recorded so the numbers above can be trusted)

My first full-suite run reported 18 failures. All were my own: I wrapped the
run in `ulimit -v 4194304`, and Node's WebAssembly allocator cannot start under
that cap (`RangeError: WebAssembly.Memory(): could not allocate memory`,
`engine.js:157`). CLAUDE.md warns about exactly this. Re-run with
`NODE_OPTIONS=--max-old-space-size=2048` and no `ulimit -v`: 20/20 OK. The
failures were the instrument, not the tree — and the suite's design helped,
since a skip is reported as a failure rather than a pass.

## Provenance

- Clean `git archive e14ff1e` for every run; the builder's worktree was not
  used as the tree under test.
- Byte equality by `yaml.safe_load` + sha256 of the key value, compared to
  sha256 of the repo file — not by text diff.
- Ancestry by `git merge-base --is-ancestor`.
- Runner checkout at `~/minecraft-wt-deepseek/agent-script-runner`, read-only.
- No apply, no push, no exec into any pod, no secret values read.
