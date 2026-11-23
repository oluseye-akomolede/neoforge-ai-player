# Review — coded-agents 3.3, script/planner dispatch parity

**Rev:** `60b85cf0f81d5a8638cc7933059b046f0da72d37` on `ship-ca27-harness`
(2 files, +239/−2: `agent/test_script_planner_parity.py` new, `tasks.md` 3.3).
Change: `coded-agents`. Requested by the builder at 04:19Z; **no queue row was
named for this commit** (the builder's message gave only the sha), so this review
is the durable record until one is filed. Read from a clean `git archive`, not
from the builder's worktree.

**Verdict: FAIL — one finding (F-1), in the test, not the product code.**

The product code does have parity, and by construction, exactly as the commit
says: both paths call one function. What the test does not do is *prove* it. It
replaces the shared dispatcher with a local stub before pinning anything, so the
thing whose sameness 3.3 is about is excluded from the test that claims to pin
it. That is the same failure 3.3 itself was filed to correct — parity asserted,
nothing proving it — moved one level up.

## What is true and worth keeping

- The **claim under test is real**: `BotRunner._l3_orchestrator_dispatch`
  (`agent.py:1503`) is the single dispatcher; the planner reaches it as
  `dispatch_fn=self._l3_orchestrator_dispatch` (`agent.py:2202`) and the script
  directly (`agent.py:3896`). Two call sites, one callee.
- The **plumbing is genuine**: I instrumented a copy of the test and confirmed
  `_planner_dispatched_directives` drives the real `plan_orchestrator._step` and
  `_script_dispatched_directives` drives the real `_run_script_tick`. Both hand
  the same dict (`{'kind': 'DROP', 'target': 'dirt'}` and
  `{'kind': 'STORE_ALL'}`) to whatever is in the dispatcher slot. The paths are
  correctly exercised up to the seam.
- **152 tests OK** across `test_script_planner_parity + test_code_time +
  test_agent_script_branch + test_dispatch_must_start` reproduces exactly
  (rc=0). The count is honest.

## F-1 — the "real dispatcher" the test claims to use is never called

`test_script_planner_parity.py:174` binds the method to a local name:

```python
real = self.agent_mod.BotRunner._l3_orchestrator_dispatch
```

`real` is **never referenced again** anywhere in the file (grep: one assignment,
two mentions in comments). `make_dispatcher()` instead returns a closure,
`disp`, whose entire body is a type check and a string build (:181–187):

```python
def disp(d):
    with mock.patch.object(self.agent_mod, "api", mock.Mock()):
        if not isinstance(d, dict) or "kind" not in d:
            return f"FAILED bad_directive {d}"
        return f"COMPLETED {str(d.get('kind', '')).upper()}"
```

So the "REAL shared dispatcher" in the docstring, the commit message and
`tasks.md` 5.1/3.3 is not in the path. And the outcome test is not weak here —
it is **tautological**: given equal arguments, that closure returns an equal
string by construction. `test_same_action_produces_same_outcome` cannot fail for
any reason except the arguments differing, which is test 1's job.

### Measured, from the clean archive at `60b85cf`

Each of the following was applied to `agent.py` in `/tmp/p33/t`, run, and
reverted (`cmp` clean against `/tmp/p33/agent.py.orig`, sha256
`91050c44cd34ff36…`, after every one):

| Probe | Result |
|---|---|
| Print at the top of the shared dispatcher's normal path, run the **unmodified** test | `DISPATCH-BODY` printed **0 times** in 3 passing tests |
| Mutant B — the dispatcher's normal body replaced by `return "FAILED MUTANT_B_shortcircuit"` | **3 OK, rc=0**; across all 152 in the affected suites, **152 OK, rc=0** |
| Mutant C — `raise RuntimeError` on the dispatcher's normal path | **3 OK, rc=0** |

The shared dispatcher can be made to raise on every call and no test in the
suite notices. The only mutants the test actually catches are the builder's
A (script path bypasses the dispatcher slot) and B/D (arguments altered before
the slot) — all of which perturb the *stub's input*, never the callee.

### Why this matters beyond wording

3.3 exists because "a script action behaves like the planner's" was held by
convention. Today it is still held by convention past the slot: the dispatcher
body carries real, path-shared behaviour — the `_set_directive_params()` filter
that drops keys `api.set_directive` won't take (`agent.py:1609`), the
`LOCATE`/`share_with` defaulting (:1633), the `kind`→`type` rename (:1601), the
DROP slot resolution (:1597). A change to any of those changes what the script
path does — and the parity test stays green. That is exactly the regression class
3.3 was created to catch.

### What a passing version needs

Not much, and it does not need the network:

1. Call the **real** bound method inside `disp` (the `real` name is already
   there), with `api` patched as it already is. The I/O the comment worries about
   is only reached after the body's own branches, so patch `_run_directive` and
   `escalation` and let the real argument-handling run.
2. Keep tests 1 and 3 as they are — they are good and they do catch A/B/D.
3. Replace or repoint test 2 so its outcome comes from the real body; as written
   it is a restatement of test 1.
4. Add the missing mutant to the record: **mutate the shared dispatcher's body**
   (not the call sites) and require the suite to redden. Any of B or C above
   would do.

My patched tree is at `/tmp/p33/t` with the recipe under "Repro".

## Also checked

- `openspec validate coded-agents --strict` — the builder's claim; the change
  parses (I did not re-run the CLI in this worktree, so I state it as
  unchecked here rather than confirmed).
- The `sys.path`/stub block (:29–73) inserting `_HERE` is sound for running by
  path from `agent/`, and matches the established pattern.
- No product code changed in this commit, so there is no product risk in
  reverting or rewriting it.

## Not done, stated plainly

- I did not run the live agent, the Java suite, or drive a bot; this row is
  agent-side and the finding is entirely inside one test file.
- I did not verify the planner's `dispatch_fn` slot *on a live plan run*; I read
  `agent.py:2202` and drove `_step` through the test's own harness.

## Repro

```
git archive 60b85cf | tar -x -C /tmp/p33/t
cd /tmp/p33/t/agent
nice -n 19 python3 -m unittest test_script_planner_parity test_code_time test_agent_script_branch test_dispatch_must_start
#   -> Ran 152 tests, OK  (matches the claim)

# F-1, probe 1: does the shared dispatcher's body ever run?
#   insert `print("[] DISPATCH-BODY")` before `_accepted = _set_directive_params()`
#   in agent.py:1609, then run test_script_planner_parity  -> 3 OK, zero prints

# F-1, probe 2: mutate the shared dispatcher's body, not the call sites
#   insert `return f"FAILED MUTANT_B {kind}"` after the `kind = ...upper()` line
#   -> 3 OK; full suite 152 OK   (should redden)
```

Scratch: `/tmp/p33/` (`agent.py.orig` is the clean copy, `A.log`,
`mutantB.log`, `mutantC.log`).
