# Review — host-api-count-seven at 315f12e

Row: `qitem-20261126230913-4f4a5bcd`
Change dir: `openspec/changes/host-api-count-seven/`
Rev: `315f12e` (parent `c920f6a`, which is an ancestor of `origin/main`)
Reviewer: minecraft-reviewer@minecraft, 2026-11-26
Verdict: **PASS on what it changes — but its own premise is incomplete. One finding (F-1) should be fixed before this change is archived, because archiving it will cement a spec that still asserts a false exact set.**

## What the change does, and why the shape is right

Three live requirements say "six `api` methods". The runner binds seven. The change
is a MODIFIED delta whose three requirement blocks are generated from the live text
by phrase substitution, not retyped. That is the correct instinct: a MODIFIED delta
that drops a scenario by name deletes it silently at archive, and retyping is how
scenarios get dropped.

I verified the method by testing its output, not by trusting it.

## Verified independently

| Claim | Method | Result |
|---|---|---|
| Three files, 309 insertions, 0 deletions | `git diff --stat c920f6a 315f12e` | confirmed |
| Live spec untouched | `git diff --name-only … -- openspec/specs/` | empty |
| Single parent at `c920f6a` | `git log -1 --format=%p` | `c920f6a`, ancestor of `origin/main` |
| Scenario names survive | name-diff within the three requirement ranges | **14 vs 14, byte-identical sorted lists** |
| Only the four "six" lines changed | content diff per requirement block | **exactly 4 hunks, all six→seven, nothing else** |
| No "six" left in delta | `grep -c six delta.md` | 0 |
| `over six` at live `:1144` untouched | it falls in requirement `:1141` (a historical measurement note), outside all three ranges | correct to leave |
| No enumerated api list needed `result` | only lists in range are rate budgets `do:30/min`, `say:30/min`, `send:20/min`; `result` has no rate budget | correct — inserting there would have been wrong |
| Seven bindings, `MAX_HOST_CALLS = 8` | read `src/binding.js` at the seven cited lines | **all seven exact** (`:328 do`, `:355 say`, `:364 send`, `:395 recall`, `:412 result`, `:419 remember`, `:440 log`); `:32 MAX_HOST_CALLS = 8` |
| Validate | `openspec validate host-api-count-seven --strict` and `bot-coded-agents --strict`, rc read directly in a scratch worktree at `315f12e` | `rc=0` both; INFOs only (long requirement text) |

The `binding.js` line cites are worth calling out: a generation method cannot make a
line number correct, and all seven land on exactly the function the proposal names.

## F-1 (should be fixed before archive): a fourth stale "six" the change missed, and it is an *enumerated* set

`openspec/specs/bot-coded-agents/spec.md`, requirement **"The Script Prompt Names The
Host API The Sandbox Binds"** (header at live `:906`), says:

> At 2026-11-20 the sandbox binds exactly `do`, `say`, `send`, `recall`,
> `remember`, `log` (`agent-script-runner/src/binding.js:109-135`).

That is six names, `result` is absent, and the word is "exactly". Its own scenario
then requires:

> **THEN** every method the prompt names is bound by the runner
> **AND** every method the runner binds is named by the prompt

Both clauses are now false against the runner: `result` is bound (`src/binding.js:412`).
So this requirement asserts an exact set that is wrong, and a scenario that would fail
if anyone checked it.

Three things make this more than a count:

1. **It is an enumeration, not a count.** A reader can sanity-check "seven methods";
   they cannot sanity-check a list that is missing one name unless they count it.
2. **The cite does not contain what it is cited for.** `binding.js:109-135` is
   `createBotState`/`createTickState`; the api surface is at `:328-440`. So the
   "exactly" list is unsupported by its own reference.
3. **The change's own proposal saw the risk and stopped short.** `proposal.md:48`
   says "where the surface is enumerated", but the delta does not touch this
   requirement at all (`grep -c 'Script Prompt Names The Host API' delta.md` → 0).

**Severity: documentation, not live defect.** The actual prompt is correct — it names
`api.result` at `l3_planner.py:512` and `planner.py:64`/`:139`. Nothing in the running
system is wrong. The risk is that this delta will be archived, and the archived spec
will carry a false "exactly six" for as long as nobody re-reads it. That is precisely
the failure this change exists to prevent, one requirement over.

**Fix:** add this requirement to the same MODIFIED delta, changing the enumerated list
to include `result` and correcting the cite to the api surface lines. The scenario text
needs no change — it is already the right test; it just currently fails.

## Scope note

`315f12e` is on branch `spec-host-api-seven`, not pushed. Merging and archiving are the
lead's steps. Nothing here blocks the merge; F-1 blocks the *archive*, and could also
be a follow-up change if the lead prefers to keep them separate — but a follow-up must
exist before archive, or the false set goes into `openspec/specs/`.

## Corrections I made to my own working

- My first scenario-name diff compared all of `live.md` (90 scenarios) against the
  delta (14) and looked catastrophic. That was my scoping error: the delta is three
  MODIFIED requirement blocks, so the comparison is only meaningful inside their
  ranges. Scoped correctly, the diff is empty. I did not report the unscoped result.
- I initially looked for `_SCRIPT_SYSTEM_PROMPT` in `agent.py` and found nothing,
  which read as "the prompt does not exist". It is in `l3_planner.py:495`. An empty
  grep is a claim about the query.
