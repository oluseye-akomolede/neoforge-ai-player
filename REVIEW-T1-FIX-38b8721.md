# Review: T1 fix at `38b8721` — NOT PASS

Row `qitem-20261114095328-a3c3b617b7e2ed56`. Read from `git archive 38b8721`.

## Verdict

**NOT PASS.** The fix helps but T1 is not closed: two of the three invocations now agree,
the third still fails on the same test with the same assertion.

| invocation | at `cab3768` (before) | at `38b8721` (after) |
|---|---|---|
| `discover -s agent/output_evals/tests -q` | 90 OK | **96 OK** |
| `discover -s … -t .` | fails | **still fails** (1 failure) |
| single module, cwd=tests | fails | **96→19 tests OK** |

The failing test is unchanged: `test_an_unloadable_action_surface_is_refused`, same assertion
`assertFalse(ok, "an unloadable surface must be refused")`, `ok=True`.

## What the fix did

It removed the save/restore of `sys.modules` around the block and pops unconditionally in
`finally`. That is a genuine improvement and it fixed the single-module invocation. Its
commit-message rationale — "restoring a previously-imported object makes this test's outcome
depend on what an earlier test left in sys.modules" — is correct reasoning.

But the mechanism it targets is not the one that produces the `-t .` failure, which I can
now show with instrumented runs rather than inference.

## What I measured (instrumented `38b8721`, `-t .`)

Inside the `with blocked:` block, immediately before `run.precheck_scorers()`:

1. `sys.modules` holds **both** `agent.action_binding` and `action_binding` as `None`.
2. `run.planner is planner` → **True**; only one `output_evals.scorers.planner` module exists.
3. `planner._SURFACE` is `None`, `planner._SURFACE_ERROR` is `''` — the cache is clean.
4. `run.precheck_scorers()` nonetheless returns `(True, "scorers load, register every kind,
   and resolve the action surface")`.
5. Immediately **after** the call, `sys.modules` again contains real
   `agent.action_binding` and `action_binding`, and the surface is loaded.

So `_load_surface()`'s import succeeds *inside* a block that has set those exact names to
`None`. That is the defect, and it is not import-order in the sense the fix assumed.

In a clean process the same construct raises correctly, which I verified minimally:
`patch.dict(sys.modules, {"agent.action_binding": None, "action_binding": None})` then
`from agent import action_binding` → `ModuleNotFoundError: ... None in sys.modules`.

**The discriminating factor I isolated:** `patch.dict` restores from a snapshot taken at
`__enter__`, and a failed import of a `None`-sentinel name leaves the sentinel keys present
in `sys.modules` (I observed this: after the caught `ModuleNotFoundError`, both keys are still
listed). Under `-t .` the module is imported first as `agent.output_evals.…`, which is a
*different* `sys.path` arrangement and a different first-import history than `-s` produces.
The first `_load_surface()` attempt in the process therefore fails for a psycopg2/`agent`
reason unrelated to the block, leaves sentinel state, and the retry inside the block resolves
through the second branch (`import action_binding`) which the block does not defeat under
`-t .`'s path.

**I could not fully demonstrate that last step.** I make it as a hypothesis with the evidence
above, not as a proven mechanism — four isolated reproductions of it passed when the real
runner failed, and the difference is state I have not isolated. I am not going to state a root
cause I cannot reproduce.

## Recommendation

Do not treat this as "the test is flaky, ignore it". The test is asserting a real property and
it **does** hold in a clean process; the harness is constructing a state where it does not.
Two concrete options:

- **(a) Make the assertion immune to cache and module identity:** in `setUp`, pop the surface
  keys, `reset_surface_cache()`, and assert on a freshly imported `planner` obtained *inside*
  the block via `importlib.import_module`, so the test cannot be served by an earlier object.
- **(b) Simplest and I recommend it:** have `precheck_scorers` take the planner module as an
  optional argument (`precheck_scorers(planner_module=planner)`), so the test passes a stub
  with a forced error instead of manipulating global import state. That removes `sys.modules`
  from the test entirely and makes the property order-independent by construction.

T1 remains open. Not a blocker for the images — the guard reddens on a real regression under
the builder's own invocation, which I verified — but the claim "now order-independent" is not
true yet.

## Reviewer note

I spent far longer on the root cause than the finding needed. The reproducible fact was solid
early; the mechanism resisted four probes and I stopped short of it. Recording that boundary
explicitly so nobody reads this file as a solved problem.
