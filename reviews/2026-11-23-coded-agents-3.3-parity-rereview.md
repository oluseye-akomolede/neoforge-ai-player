# Re-review — coded-agents 3.3, parity test after F-1 (`c1ff2cc`)

**Rev:** `c1ff2cc` on `ship-ca27-harness` (2 files, +81/−13, all in
`agent/test_script_planner_parity.py` and `tasks.md`). Supersedes
`reviews/2026-11-23-coded-agents-3.3-parity.md` (F-1 at `60b85cf`). Read from a
clean `git archive`, not the builder's worktree.

**Verdict: PASS.** F-1 is fixed and every mutant I raised against it now reddens.
One narrower finding (F-1) survives, in a place the fix did not reach — same
class, smaller blast radius, and it does not reopen the outcome of 3.3.

> **Forward pointer (added 11-23 10:2xZ, post-park).** The builder took the
> *reword* option, not the code fix, at `dddf493` (doc-only against `c1ff2cc`);
> I re-verified that commit and the verdict stays **PASS**. Measured at
> `dddf493`: suite 5 OK, rc=0, and the planner-slot mutant still reproduces —
> replacing `dispatch_fn` at `agent.py:2202` with an unrelated lambda leaves
> **5 OK**, real-dispatcher call count unchanged at 10 — so the finding was real
> and the new text now states the limitation rather than papering over it. The
> docstring and `tasks.md` 3.3 carry separate PROVEN/ASSUMED headings naming
> `agent.py:2202` as assumed, with the reason (`_run_plan_orchestrator_task` is
> not driven by this harness, which supplies the dispatcher as an argument) and
> what would pin it. That is exactly the shape I said I would accept.
>
> Two residual notes, neither blocking. (a) **Nit:** the new docstring says
> "`_both` hands each path the **bound** `_l3_orchestrator_dispatch`". The script
> path does; the planner path is handed `recording_dispatch` as a *free*
> function — `_planner_dispatched_directives` passes it in the `dispatch_fn`
> positional slot. It is the same slip the paragraph exists to fix, one notch
> smaller; worth three words in a future doc pass. (b) The `escalation` shim is
> `mock.Mock()` in `sys.modules` — fine for the three actions tested, load-bearing
> for `ASK_PLAYER`, now documented as a limitation rather than fixed. Accepting
> that for this row.

## F-1 from the first review: fixed, measured

`make_dispatcher()` now calls `real(br, d)` with `api` swapped for a `Mock` and
`sys.modules["escalation"]` replaced, `br._run_directive` mocked, and a per-path
`br`. Nothing about the callee is stubbed any more.

I reproduced every claim, mutating `agent.py` one exact site at a time and
restoring (`cmp`-clean against `agent.py.orig`, sha256 `91050c44cd34ff36…`,
after each run):

| Probe | Before (`60b85cf`) | After (`c1ff2cc`) |
|---|---|---|
| Print in the dispatcher's normal path, unmutated suite | 0 hits, 3 OK | fires (10 hits across 5 tests) |
| Body short-circuits to `FAILED MUTANT_BODY` | 3 OK | **3 FAIL** (`same_outcome`, `key_filter`, `locate`) |
| Body raises `RuntimeError` | 3 OK | **3 FAIL** (same three) |
| Key filter disabled (`if _dropped:` → `if False:`) | n/a | **1 FAIL** (`key_filter` only — precise) |
| LOCATE `share_with` default disabled | n/a | **1 FAIL** (`locate` only — precise) |
| Script path bypasses the dispatcher for `_run_directive` | (A, 2F+1E) | **4 FAIL + 1 ERROR** |

The two new tests pin exactly the two body behaviours I named as unobserved, and
each reddens *only* on its own mutant — that is the specificity I asked for.
`test_same_action_produces_same_outcome` now pins the real body's literal
`"COMPLETED STORE_ALL {}"`, so it can no longer pass by the two paths agreeing on
a wrong answer.

Baseline reproduced exactly: `test_script_planner_parity` **5 OK**, and
**154 tests OK** across the four affected suites (rc=0).

## F-1 (this round) — the planner's *slot* is not pinned; a stub can stand in for it

The fix makes the **callee** real. It still substitutes the **dispatcher object**
on the planner side: `_planner_dispatched_directives` passes `recording_dispatch`
in the `dispatch_fn=` position, whatever `agent.py:2202` actually puts there is
never called.

Measured at `c1ff2cc`:

- Replace `dispatch_fn=self._l3_orchestrator_dispatch` (:2202) with
  `dispatch_fn=lambda d: "COMPLETED " + kind.upper()` — a callable that never
  touches the real dispatcher: **5 OK**.
- Count real-dispatcher invocations across the suite: **10 with the mutant, 10
  without** — identical, because every call comes from the test's own `disp`.
- Replace the slot with `lambda d: "COMPLETED " + kind.upper()`, and
  `test_same_action_produces_same_outcome` alone still passes: the planner result
  is produced by the stub, and the script result is produced by `disp` — which
  contains the same body — so they agree.

So the round-trip now reads: `disp` stands on the planner's side of the seam,
`real` stands on the dispatcher's side of it. Both are test code. What is
genuinely proven is that the *script* path (agent.py:3896) reaches the real
dispatcher and that the real body does what the two new tests say. What is still
assumed is that the *planner* path (agent.py:2202) reaches it.

That is a real reduction in exposure — the body mutants that motivated the first
FAIL are all caught now — and it is *not* the same severity as before: the
planner line is a one-line pass-through that no test would have caught at
`60b85cf` either, and its blast radius is the planner alone, not both paths. It
does not reopen 3.3's verdict.

**Fix, if the builder wants the last inch** (small, and I would take it in this
row rather than file another): in `_planner_dispatched_directives`, obtain the
callable from the same `br` the test already builds —

```python
real = self.agent_mod.BotRunner._l3_orchestrator_dispatch
plan_orchestrator._step(..., recording_dispatch(real, br), ...)
```

i.e. wrap `br`'s *bound* method rather than passing a free function; then the
planner-slot mutant above reddens. If 3.3's intent is only "the dispatcher body
is shared once a directive reaches the seam", then the claim should be worded
that way in `tasks.md` and the docstring — today both say "both paths reach the
same callee", which the planner half of the test does not demonstrate.

## Kept as agreed

Tasks 1 and 3 (`same_arguments`, `bound_arguments`) are untouched and still
carry mutant A. `_params_reaching_run_directive` mirrors `_both` cleanly and
`br._task_sender = "alice"` is what makes the LOCATE assertion non-vacuous —
I checked that by disabling the default and watching that one test, and only
that one, redden.

## Not done, stated plainly

- No live agent, no bot, no Java. Agent-side row; all evidence is from the clean
  archive and mutants.
- I did not re-run `openspec validate --strict` in this worktree; I read the
  `tasks.md` delta and it is prose plus two ticks. Stated as unchecked.
- I did not test the `escalation` shim's fidelity (`mock.Mock()` in
  `sys.modules`); for the three actions tested it is never reached before the
  return, but for `ASK_PLAYER` it would matter. Out of this row's scope and worth
  a note for whoever tests that branch.

## Repro

```
git archive c1ff2cc | tar -x -C /tmp/p33b && cd /tmp/p33b/agent
python3 -m unittest test_script_planner_parity           # 5 OK
python3 -m unittest test_script_planner_parity test_code_time \
        test_agent_script_branch test_dispatch_must_start  # 154 OK

# body mutants (all now caught):
#   after `kind = str(directive.get("kind","")).upper()` in agent.py:1512
#     insert `return f"FAILED MUTANT_BODY {kind}"`        -> 3 FAIL
#     insert `raise RuntimeError("MUTANT_C")`             -> 3 FAIL
#   `if _dropped:` -> `if False:`                         -> 1 FAIL (key_filter)
#   LOCATE condition -> `if False:`                       -> 1 FAIL (locate)

# F-1 (this round):
#   agent.py:2202 dispatch_fn=self._l3_orchestrator_dispatch
#     -> dispatch_fn=lambda d: "COMPLETED " + str(d.get("kind","")).upper()
#                                                          -> 5 OK  (should redden)
```
