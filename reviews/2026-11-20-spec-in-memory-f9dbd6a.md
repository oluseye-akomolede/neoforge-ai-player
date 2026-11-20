# Review: spec delta `f9dbd6a` — planner script lives in memory

- **neoforge-ai-player `f9dbd6a`** (openspec change `ai-written-scripts`, spec only)
- Row `qitem-20261120103228-9b7460ae4b8ce10d`
- `openspec validate ai-written-scripts --strict` at `f9dbd6a`: **valid, rc=0** (run in the worktree that holds the rev).

## Verdict

**Spec content: sound, and I would pass the argument. Findings are citation-level
and one is a wrong cross-reference — NOT YET until they are fixed, because both
are exact-address defects of the kind this delta's own commit claims to have
swept.**

The design change itself holds up under all three attack points. The two
findings are: a stale `agent.py` line range in the latch paragraph, and a
"see requirement 4" pointer that names the wrong requirement.

## Attack point 1 — does "bindings.json names only hand-written scripts" hold?

**Yes, verified by execution rather than by the spec's own assertion.**

`agent.py` has exactly one open of the file, at `:3099`:
`with open(bindings_path, encoding="utf-8") as f:` — read mode, no write flag.
A whole-rev sweep (`git grep` over `*.py`, `*.yaml`, `*.yml`, `*.sh`) finds
`bindings.json` written only in `agent/test_agent_script_branch.py` (test
fixtures) and `deploy/agent-scripts.yaml` (the ConfigMap a human applies).
No production code path writes it.

So the load-bearing invariant — "an entry in `bindings.json` can only have been
placed by a human" — is true of the code as it stands. The whole provenance
inversion rests on this, and it rests on real behaviour, not on the spec
asserting it.

## Attack point 2 — is the restart-drop consequence complete?

**Yes.** The one-shot `_script_loaded` latch (`agent.py:3138-3140`, `False` at
`:235`) is the mechanism that made a mid-process rebind impossible, and the
spec names it and requires a defined reset that is "the only writer that clears
it" (spec `:96-104`). Both directions are covered by scenarios:

- *"A passing dry tick rebinds a previously written script"* — latch IS reset,
  next real tick runs the new source.
- *"A failed dry tick does not disarm a working bot"* — latch NOT reset, "no
  tick is missed".

An in-memory script cannot outlive the process, so nothing needs provenance to
*survive* a restart — which is exactly what removes the old freeze cost. I found
no remaining reliance on provenance surviving: `_script_loaded` is the only
provenance-shaped state, and it is per-process by construction. Single
production caller at `:2890` (verified). The fallback on restart is stated twice
(restart scenario + condition-2 fallback), including "no error is raised and no
tick is missed".

## Attack point 3 — does any scenario still assert the old freeze?

**No.** All 19 scenario titles at `f9dbd6a` were listed; the old
"A restart freezes the script an agent wrote" is gone and replaced by
"A restart drops the script an agent wrote" (`:306`). Every surviving occurrence
of "freeze"/"frozen"/"indistinguishable"/"unbinds" is a *replace-this* sentence
(spec `:279-290`, proposal `:63`, `:130-131`, tasks `:75`), not a live assertion.

## Findings

### F1 — stale line range in the latch paragraph (spec `:97`)

> `_script_loaded` latch (`agent/agent.py:3052-3054`, set `False` at `:235`)

`:3052-3054` is **not** the latch. At `f9dbd6a` those lines are a dry-tick
refusal comment:

```
3052:            return False
3053:        # A post-run binding refusal is NOT a dry-tick failure: the script ran.
3054:        # Read the refusal apart from a genuine non-run so an `api.say` script,
```

The latch is at **`:3138-3140`**:

```
3138:        if self._script_loaded:
3139:            return self._script_tick
3140:        self._script_loaded = True
```

`:235` (`self._script_loaded = False`) is correct.

This matters more than a typo: this is the paragraph whose entire job is to tell
an implementer *where the latch is* so they do not wire the rebind into a path
that returns the cached previous script. A wrong address here sends them to
unrelated code.

### F2 — "see requirement 4" names the wrong requirement (proposal `:60`)

> The agent has no write path for script source (see requirement 4), ...

Requirement 4 is **"The Agent Decides Script Vs Plain Planner By Stated
Conditions"** (`spec.md:222`). It mentions "write path" zero times. The
no-write-path claim lives in requirement **2**, "A Planner-Authored Script Lives
In Memory, Not On Disk" (`spec.md:37`), which states it and cites `:3092`,
`:3097`, `:3121`.

The pointer should read **requirement 2**. Requirement 4 has the *consequence*
(condition 2 is answerable because the script never enters the file) but not the
*premise* the sentence is citing.

## Citations I checked and found CORRECT

So the fix is narrow, not another sweep:

- `agent.py` `:3092`, `:3097`, `:3121`, `:3113`, `:3070`, `:235`, `:2890`,
  `:1330-1333` — all resolve to what the text says.
- `script_tick.py:387` — `self._memory = result.memory`. Correct.
- `binding.js` `:31`, `:44`, `:45-52`, `:59-65`, `:126-136`, `:154-174`,
  `:225-318`, `:244-251`, `:314`, `:337-346` — all resolve: the per-bot rate
  window, `createBotState`, `acceptAction`'s `actionTimes`, `api.do` pushing to
  the sandbox array, `state.memoryOut = blob`, and the `logTimes` window.

(My first pass flagged `:31`, `:45-52`, `:244-251` as unresolved; that was my
grep being too narrow, not the spec being wrong. Re-read directly — all three
are accurate.)

## Minor, not blocking

- The change has a single `## ADDED Requirements` header while it *modifies*
  scenarios from its own earlier draft (freeze → drop). That is correct here:
  the change is unarchived, so it is replacing its own text, not a live spec,
  and `validate --strict` agrees. Worth knowing it is ADDED-only if this is ever
  split.
- Scenario "A dry tick carries no memory" (`:201`) asserts "the bot's memory is
  what it was before" — at the agent level this is the stub-path test I noted on
  the runner review; the real wire-level guard is the runner test at `549c80d`.
  Consistent with what already shipped; no new hazard.

## Not done by me

Spec-only change; nothing deployed, nothing pushed. No code in scope per the
lead's decision.
