# Review: prompt kinds (24b4bb0), done_reason guards (8cfb376), all-refused yield (6559129)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21
Verdict: **PASS with findings** — F-1 serious, F-2..F-4 minor.

Scope: three commits on `ship-ca27-harness`, deepseek worktree.

- `24b4bb0` prompt action-kind list derived from the binding
- `8cfb376` done_reason guards at the structured call sites + census
- `6559129` the all-refused tick unbinds and re-plans (task 2a.14, option 1)

Spec first: all three implement requirements already reviewed and passed
(`ai-written-scripts` f7b31c4/dd72746/ddf7ebb/2e738dc, `agent-llm-transport`
a80429c/815b600). No code-before-spec violation.

---

## What I verified by running it

**`24b4bb0` — derived list.** Rendering the L3 system prompt at the rev gives
**45 kinds** and no `{{`/`}}`. The count matches `len(BINDABLE_KINDS)` computed
independently from the import. The prompt's two examples, `goto` and `mine`,
both bind (upper-cased at `action_binding.py:74`, tested at `:75`).

**Drift test bites, both directions.** Removing a kind from the binding alone
drops it from the prompt and reds the drift test; hand-typing a list back reds
3 tests. So the gate is not inert — it is tied to the same source the prompt
renders from, which is the property `a4451a3` lacked.

**Census pins both ends.** `test_prompt_kinds` line 68 asserts the guard helper
names inside the census *source*; renaming the helper in `census.py` alone
produced 2 clean failures (not collection errors), so the pin is real. Renaming
in `config.py` alone reds via import. Both ends covered.

**`8cfb376` — census 9/1/0.** The census reports 9 functions, 9 guarded, 0
unguarded, and **reds when a guard is removed** (verified by deleting one call
and re-running: it reports 9/8/1 and exits 1). So it measures the code, not a
list.

**`6559129` — the handoff works, and I traced why.** This was the builder's
question. The yield at `agent.py:3303` sets `yielded`, then `:3304-3306` clears
`_plan_steps`, `_plan_step_idx` and `_plan_instruction` before returning False.
So on the *unbind tick* `_check_task_board` is skipped at `:3630` (correct —
nothing to plan for a goal being abandoned), and on the **next** tick
`_plan_steps` is empty, so `:3629` `if not self._plan_steps:` is true and
`call_plan` is reached. The 69-refusals-fall-through mechanism is closed.

Reason continuity is preserved for option 1: the unbind is unconditional within
an all-refused tick, so there is no consecutive-tick question, and `refusals`
non-empty is the correct all-refused test (a script proposing nothing returned
at `:3242`).

---

## F-1 (serious): the done_reason guards may be dead on the production path

The row asked whether the guard can fire "with the gateway's cut or not". I
checked rather than reasoned, and the answer depends on a deployment fact I
cannot verify from this repo — but the shape is alarming.

`ensure_not_truncated` reads `body.get("done_reason")`. All nine guarded sites
call Ollama's `/api/chat` **directly** (`l3_planner.py`, `brain.py` build their
own URL), so on those paths `done_reason` is present and the guard fires.

But `tests/test_llm_planner_transport.py` contains a test asserting "**every L3
call goes through llm-gateway's /api/chat shim**". That test feeds a
**hand-built envelope** with `done_reason` already present. It proves the guard
survives a shim-shaped body; it does not prove the shim emits the field.

And `openspec/changes/gateway-token-accounting/` — **still open**, task 4.1 is
the parent of this work — describes the llm-gateway shim **dropping
`done_reason` from the response entirely**. The trial log in this repo records
one reply with `done_reason: absent`.

If the gateway is in the path, nine guards read as protection and never fire,
and the test that "covers" it covers a stubbed envelope rather than the
transport. This is the `review-the-transport-not-the-stub` failure mode.

**I could not settle it**: no kubectl here, no gateway manifest in this repo,
and the shim lives in `llm-gateway`. Not a defect in these three commits — but
the claim "the guards protect the L3 call" is conditional on the gateway
forwarding `done_reason`, and that is unproven. **Recommend**: record the
gateway-side requirement, or land the shim fix, before anyone cites these
guards as protection in production.

## F-2 (minor): census edge case reports drift when it should report zero

With no `agent/` directory in cwd the census prints `functions=0` and
`DRIFT: expected 9/1` and exits 1 — correct enough. But run with a `--root`
flag it does not accept, it **ignores the argument**, walks a nonexistent
default path, prints `functions=0`, and still exits 1. A caller passing a root
believes it measured that root. It should refuse an unknown flag. (I hit this
myself and briefly read `functions=0, rc=0` as a dead instrument — see below.)

## F-3 (minor): the census recognises guards by name only

`_GUARD_NAMES` matching means a site guarded by an *equivalent but differently
named* function counts as unguarded — noisy but safe (it fails toward "drift").
The reverse: a future helper named `ensure_not_truncated` that does something
else would be credited. The comment names the three files to keep in step,
which is the right mitigation. Note, not a fix.

## F-4 (nit): two comment discrepancies

`24b4bb0`'s commit message says placement is `CONTAINER_PLACE`;
`planner.py`'s comment says `CONTAINER_STORE`. **Both exist and are different**:
`CONTAINER_STORE` removes into a box (the mod's R-* handlers), `CONTAINER_PLACE`
places a block at an adjacent position. The prompt's sentence — "putting an item
in a container is `CONTAINER_STORE`" — is correct; the commit message's one-line
summary equates them. The message is what a future reader trusts. Reword it.

---

## Instrument failures of mine, recorded

1. **I nearly filed a non-existent function.** My first `done_reason` grep in my
   own worktree returned zero for everything, including `answer_text` — because
   my worktree did not contain `a80429c`. `git merge-base --is-ancestor` said NO.
   Caught by a positive control that should have returned a hit.
2. **I nearly filed a working gate as inert.** I piped the census to `tail` and
   read `rc=0` off a run whose real exit was **1**. That is the
   `a-pipe-reports-the-last-command's-status` trap already in my notes. Re-ran
   with output to a file and `echo $?` unpiped.
3. **I asserted `functions=0, rc=0`** from an invented `--root` flag, and only
   the zero-plus-control reflex stopped it.

None of these reached the builder as findings.

## Not verified / scoped absences

- The gateway deploy state (F-1) — outside this repo.
- The trial's "0 new plans over six minutes" — a trial record I did not re-run.
- Full agent discovery was not run; I ran the suites named in findings
  (`test_prompt_kinds`, `test_llm_planner_transport`, `test_script_tick`).
