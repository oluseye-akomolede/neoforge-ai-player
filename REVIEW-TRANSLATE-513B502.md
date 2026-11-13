# Review — 513b502 (runner→binder boundary translation)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS on the code. Two corrections to the run-4 plan, one of which
would send a reader looking for a step that no longer exists.**

Reviewed at `513b502`, not `59f30a5`. The builder's correction arrived before I
reported, which is why every claim below names the rev it was measured on.
`513b502` adds two commits on top of the rev I was first handed:
`d9c1707` (run-4 plan) and `513b502` itself (three seq-alignment tests).

**Production code is byte-identical between `59f30a5` and `513b502`:**

```
git diff 59f30a5 513b502 -- agent/script_tick.py agent/agent.py \
    agent/action_binding.py agent/test_scout_script.py
-> (empty)
```

So the translation and the end-to-end test I examined are the same bytes at the
rev that will ship.

---

## 1. THE TRANSLATION IS CORRECT, AND MATCHES THE PRODUCER

The producer is `agent-script-runner/src/binding.js`. Read against that, not
against the translator's own docstring:

| call | record emitted | translated |
|---|---|---|
| `do` | `{seq, call:"do", directive, args}` (`:242-249`) | `{"kind": directive, **args}` ✓ |
| `say` | `{seq, call:"say", text}` (`:259`) | refused by name, no `directive` ✓ |
| `send` | `{seq, call:"send", to, msg}` (`:272`) | refused by name, no `directive` ✓ |

`args: args === undefined ? null : args` at `:247` means a `do` with no
arguments arrives as **null**, and `_translate_one`'s `if args is None: args = {}`
handles exactly that. The producer and the consumer agree on the same bytes,
which is what every earlier round in this run failed to check.

The reserved-argument refusal (`kind`/`action` inside `args`) is right for the
reason given: `bind_action` reads `action.get("kind", action.get("action"))`, so
an arg by that name would become the action name and the real directive would be
lost silently.

## 2. THE SEQ ALIGNMENT — MEASURED, NOT ARGUED

The builder said the alignment was "reasoning, not a test". At `513b502` it is
tested. I re-derived the mutation rather than accepting the claim:

```
mutation: self._last_action_seqs = [pairs[i][1] for i in range(len(bound))]
          (survivors indexed by position-in-bound, not position-in-pairs)

-> Ran 28 tests, FAILED (failures=1)
-> FAIL: test_seqs_stay_with_their_actions_when_a_middle_one_is_refused
```

**Exactly one test fails, and it is the one the builder named.** The mutant is
identical to the real code when nothing is refused, which is precisely why the
old fixtures could not have caught a slide.

I also ran the alignment myself on a mixed record list before this rev, and the
mapping holds: a `say` refused in the middle did not shift the bind refusals.
The two new tests pin both seams — binder refusal (`[11,13]`, refused `12`) and
translation refusal (`[11,13]`, refused `12`).

**One thing worth recording, because it is load-bearing and not obvious:**
`state.seq` is **reset to 0 each tick** (`binding.js:116`) and incremented on
every accepted host call, so a `say` between two `do`s consumes a seq. Seq
values are therefore not contiguous, and the code is right to align by *pair
position* and carry `seq` as a label rather than to assume `seq == index`. The
tests use non-contiguous seqs (1/3, 11/12/13) for that reason.

## 3. THE SIDECAR IS NOT A MODULE GLOBAL

Worth stating because it looked like one. `agent.py:2706` reads
`st._last_action_seqs`, and `st` is the `ScriptTicker` **instance**, not the
module — the attribute is set per-instance at `script_tick.py:301`. So there is
no cross-bot or cross-tick bleed.

Two smaller checks:

- `_last_action_seqs` is built from `pairs` with rejected indices removed, so it
  is aligned to `bound` in order.
- `agent.py`'s `if not isinstance(act, dict) or not act.get("kind"): continue`
  cannot desynchronise the index, because `bind_action` returns
  `{"kind": kind}` with a non-empty upper-cased kind or raises. Nothing in
  `bound` can lack `kind`. The guard is dead defensive code, harmless.

## 4. MEASUREMENTS REPRODUCED

All run on a clean `git archive 513b502` export, with
`AGENT_SCRIPT_RUNNER=/home/sigmastrain/minecraft/agent-script-runner` and
without `ulimit -v` (Node exception).

| what | result |
|---|---|
| `test_script_tick.py` | `Ran 28 … OK` |
| full suite, discovery | `Ran 118 … FAILED (errors=1)`, `rc=1`, **0 skipped** |
| only error | `dashboard` (pre-existing `uvicorn` import) |
| `openspec validate coded-agents --strict` | `valid` (rev `513b502` printed in the same command) |
| `scout.js` sha256 prefix cited by the plan (`1824967e`) | **matches** the bytes at `6f8ad66`, 5852 bytes |
| `scout.js` at `6f8ad66` vs `513b502` | identical |

The full-suite error is the same one present at `fb8030d` and every rev since;
`dashboard` imports `uvicorn`, absent on this VM. Not a defect in the commit.

**The mutation both directions, as the builder claimed it:**

```
old path (runner record -> bind_actions, no translation):
  -> refused: "action has no 'kind': {'seq': 1, 'call': 'do',
               'directive': 'STORE_ALL', 'args': {}}"
binder-shaped fixture -> translate_runner_actions:
  -> refused (was previously accepted by the old test fixtures)
```

The suite can no longer pass on a shape the producer never emits. That was the
defect class this whole run kept returning to, and it is now closed by
construction rather than by care.

## 5. FINDING (plan, should be fixed before run 4) — §9 contradicts itself

`openspec/changes/coded-agents/M2-PLAN.md`, in the rollback section:

- `:1555` — **"No profile file is restored, because no profile is edited."** It
  then explains that the `cp` step was deleted because the profile never
  changed, and calls the deleted copy the "silent no-op that reports success"
  shape.
- `:1574-1577` — **"The profile restore is the piece git cannot do."** It says
  that "without the explicit `cp` above" the bot comes back silently reverted,
  and adds a paragraph on why that `cp` needs `-c agent`.

There is no `cp` above. It was removed by the first paragraph. A reader working
§9 top to bottom is told the step is unnecessary, then told a later consequence
depends on it, and looks for something that is not there. The trailing
verification line — "the restored file's sha256 equals the one recorded on the
row at step 3 (i)" — depends on the same absent step.

This is not a judgement about which paragraph is right. It is that they cannot
both stay, and the one that must go is the argument for a step the section has
deleted. My reading is that `:1555` is the current intent and `:1574-1587` is
leftover from the profile-based design, but the builder should decide and say.

## 6. FINDING (plan, minor) — step 1 names a rev whose tree it does not ship

Step 1: *"Build and push … from `agent/` at `59f30a5`."* The reviewed rev is
`513b502`, and the plan above that step is `d9c1707`. The production bytes are
identical across all three so **the image is the same**, but a deploy record
should name the tree it ships, and the run-4 plan's own evidence criterion asks
for a rev-matched trail. Naming `513b502` costs nothing and removes the question.

## 7. WHAT I DID NOT VERIFY

- **The live cluster.** I did not run a single `kubectl` command for this
  review. The plan's "before" digest
  (`sha256:d1513fa2…`) and ConfigMap state (`838efd89…`) are its own claims,
  which I have not checked against the running objects. The `1824967e` scout.js
  digest I did verify, against bytes in the tree.
- **The image.** The builder says it is building `59f30a5` now and has applied
  nothing. I did not build, push, or inspect it. Step 6's in-pod checks
  (`translate_runner_actions` present in `/opt/aibot-agent/script_tick.py`,
  mounted `scout.js` hashing to `1824967e`) are the ones that would prove the
  image is what this review passed; they are unrun.
- **History at `6f8ad66` vs now on TEST.** The plan says TEST holds the
  rolled-back `838efd89` bytes. Not checked.

## Verdict

The code passes: the translation matches the producer's actual record shape, the
seq alignment is tested at both seams and I re-derived the mutation that reddens
exactly one test, the sidecar is per-instance rather than global, and the
suite/spec/digests all reproduce. Refusals are collected, named, and carry the
seq, so no record can vanish silently.

The two plan corrections are cheap and should land before run 4, because run 4
is the deployment this PASS is being asked to authorise. §5 in particular is a
step a reader cannot follow, in the section they will follow **if the run fails
and has to be rolled back**.

**I have not authorised the rollout.** That needs the lead's OK and the
cardgame-lead's, and this review covers the commit, not the cluster.
