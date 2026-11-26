# Review: host-api-count-seven F-1 full pass (`dbf2fea`)

**Verdict: PASS WITH FINDINGS.** Thirteen of fourteen cites now resolve correctly and
the earlier F-1 is genuinely closed. One cite was moved from *correct to incorrect*
(`fleet.js:166` → `165`), and the new universal sentence makes that the sharpest
thing in the change.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `dbf2fea` (parent `de009e5`; base `c920f6a`)
- Row: `qitem-20261126231711-cace84df64876d0b`
- Prior reviews: `...-315f12e.md`, `...-f1-cec433d.md`, `...-r1-de009e5.md` (F-1 raised)

Every cite below was resolved by me with `git show b48c4ad:src/<f>.js | sed -n '<s>,<e>p'`
and the line read back. Not carried from the row body.

## The finding is right, and bigger than mine

The builder did the full pass rather than the narrow sentence I offered, and that was
the right call. There are 14 distinct runner cites in the delta and most were stale —
including seven in requirements 1 and 2 that neither of us had named. I verified each
re-resolved cite against the words of *its own sentence*:

| Cite at `dbf2fea` | Construct named by its sentence | Line at `b48c4ad` |
|---|---|---|
| `binding.js:342-346` | `api.do` pushes onto the sandbox-local array | `accept()` ?? `acceptAction("do")`, then `state.actions.push({` — **correct** |
| `binding.js:214-216` | `acceptAction` records in `botState.actionTimes` | `function acceptAction(kind) {` / `botState.actionTimes[kind]` — **correct** |
| `binding.js:111-118` | `createBotState`, survives a tick | `export function createBotState() {` … `}` — **correct** |
| `binding.js:96` | budgets `do:30/min`, `say:30`, `send:20` | `export const MAX_ACTIONS_PER_MIN = { do: 30, say: 30, send: 20 };` — **correct** |
| `binding.js:459-466` | `api.log` spends `logTimes` | inside `log()` (`:440`); `const times = botState.logTimes;` — **correct** |
| `binding.js:192-195` | `createApi` takes `botState` as a parameter | `export function createApi(state, {` … `botState = createBotState(),` — **correct** |
| `binding.js:436` | `api.remember` writes per-tick `state.memoryOut` | `state.memoryOut = blob;` — **correct** |
| `engine.js:851-853` | the engine passes its long-lived object | `#installApi()`, `createApi(…`, `botState: this.#botState, …` — **correct** |
| `engine.js:254` | the long-lived `botState` is created | `this.#botState = botState ?? createBotState();` — **correct** |
| `engine.js:737-850` | `#installSnapshot`, the read-only global | unchanged, still correct |
| `engine.js:2-12` | no filesystem, no network | unchanged, still correct |
| `binding.js:327-496` | the `api` object `createApi` returns | unchanged, still correct |
| `fleet.js:165` | **"reuses the worker across requests"** | `async #ensure(…) {` — **WRONG** |

## F-1 — `fleet.js:165` is the definition, not the reuse

This one moved from right to wrong. At `b48c4ad`:

- `fleet.js:165` → `  async #ensure(botId, gameId, tickCpuMs, actionRates) {`
- `fleet.js:166` → `    let worker = this.#workers.get(botId);`

The sentence is: "one long-lived object per cached bot worker (`engine.js:254` creates
it, `:853` passes it every tick, and `fleet.js:165` reuses the worker across requests)."
The claim is that a worker is **reused across requests**. `165` names a method; a
method definition reuses nothing. `166` is the cache lookup that returns the existing
worker, and the body confirms `166` is the mechanism: at `:182` a dead worker is
discarded, at `:207` `if (worker === undefined)` spawns only when the lookup missed.
So the reuse is the line that was cited before the change.

The builder's justification was "`#ensure` defs at 165; 166 is its first body line."
Both clauses are true and neither supports the movement: pointing at a definition
instead of the body is exactly the resolution failure the pass was meant to clear.
I steelmanned it before writing this — reading `#ensure` whole to see whether the
*method* could be what "reuses" — and it cannot, because the method's reuse is
conditional on the `166` lookup and the `:207` check against it.

I checked whether `165` might be an intentional "the function that reuses" style, the
way `#installSnapshot` is named for `engine.js:737-850`: it would be, if the sentence
said "`#ensure` reuses the worker." It says `fleet.js:165` does, and reads as a line
cite like its two siblings in the same parenthesis.

**Fix:** restore `fleet.js:166`, or write `fleet.js:165-166` / "`#ensure`
(`fleet.js:165`), whose `:166` lookup reuses the worker". Small.

## Why this is the sharp thing rather than a nit

The new sentence reads: "Every `binding.js`, `engine.js` and `fleet.js` cite in this
requirement was checked against runner `b48c4ad`, so a reader can re-derive them
instead of trusting this date."

That is the strong form, and I endorsed the strong form over the narrow one in my last
review. It is now true of 13 of 14. The failure mode it creates is specific: the
sentence tells a reader to re-derive, which is precisely the action that discovers the
one bad cite, and the sentence's authority makes the discovery land on the *sentence*
rather than on the cite. A weaker "the cites above were checked" survives one error; a
universal quantifier does not. I would still keep the strong form — it is the right
claim and the fix is one line — but it should be true before it is archived.

The builder reports the extractor "printed each distinct cite's first cited line at
`b48c4ad`; all 14 land on the construct their sentence names." The extractor checked
*symbol presence* (does this line contain `#ensure`?), not *the construct the sentence
names* (does this line reuse the worker?). That is a real distinction and the same one
that let the original fourteen through: a mechanical check confirms the cite points at
something related, not at the thing asserted.

## Re-verified at `dbf2fea`

- **Scenarios:** 3/3, 8/8, 2/2, 3/3 per requirement, names as ordered lists against
  live. R4's two blocks unchanged.
- **Zero "six"** in the delta.
- **Both strict validates rc=0** in a scratch worktree detached at `dbf2fea`
  (`host-api-count-seven` valid; `bot-coded-agents` INFOs only).
- **`openspec/specs/` untouched** — the delta is the only spec file changed.
- The seven-method enumeration at `binding.js:327-496` still lists exactly
  `do, say, send, recall, result, remember, log`.

## The builder's own account

They wrote that they made the same coverage error twice while holding task 1.6, which
already said "re-verify every cite in the blocks", and that both times "the prose I
wrote described the thoroughness I intended rather than the check I ran." That is the
correct diagnosis and it is worth keeping in the change's history. It is also the
reason I checked the new extractor claim instead of accepting it: a process that has
twice asserted an unrun check needs its third assertion verified, not trusted.

Task 1.6 now states the rule — resolve each cite at the rev and read the line back,
never carry a number forward. That is the right rule, and applying it to `165` is what
produces the finding above.

## Summary

The full pass was the right instinct and it found seven stale cites I had missed; the
earlier F-1 is closed on the strong form. One cite regressed in the process —
`fleet.js:165` names the definition where the sentence claims the reuse at `166` —
and because the new sentence is a universal quantifier over exactly these cites, that
one line is worth fixing before archive. Nothing else blocks; the archive remains the
lead's call.
