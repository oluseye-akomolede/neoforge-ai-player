# d4e7d37 — a thrown tick's carried result: PASS on the fix, one narrow defect (F-1)

Rev reviewed: `d4e7d37` (parent `8f7dfbe`), neoforge-ai-player, branch `minecraft-wt-qwen`.
Runner at `27d786b` (unchanged by this commit).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Verdict: the F-1 I filed against `8f7dfbe` is closed.** A script that reports and
then throws now keeps its report, the report is classified as a failure, and the
goal is re-planned rather than closed. I drove the case my earlier review named,
through a real `status: error` payload, and it now produces the intended outcome.

One narrow defect remains (F-1 below): a null payload is turned into the string
`"None"`. It does not block this commit's requirement — that requirement is about
a *real* report surviving — but it is a phantom the bots would act on.

## What I verified

Suite, my worktree at `d4e7d37`, tail read directly (not piped):
`Ran 610 tests`, `errors=1` (`dashboard`: `No module named 'uvicorn'`, pre-existing),
`skipped=1`. The builder's figure reproduces exactly.

Mutants, each restored and `cmp`-identical afterwards:

- **Drop the carried result** (`if result.failed and result.result:` -> `if False:`):
  4 red, all four the tests that depend on the hold —
  `test_a_failed_tick_that_reported_holds_its_result_as_failure`,
  `test_a_thrown_ticks_result_does_not_close_the_goal_as_done`,
  `test_a_thrown_ticks_result_reaches_the_planner_not_the_closer`,
  `test_a_carried_result_with_done_true_still_counts_as_failure`.
- **Hold but classify as success** (`"ok": False` -> `"ok": True`): the same 4 red.

Both match the commit message's claim ("each red exactly the 4 tests that depend on
the half they remove").

The chain, verified by reading the bytes rather than the description:

- `capResult` (`binding.js:252`) always returns `{text, truncated}` and returns
  `{text: null, ...}` — never a placeholder — when nothing was reported.
- `main.js` sends `result: result.result ?? null` on the error branch, so the
  agent receives the runner's own dict, null-when-absent intact.
- `script_client.call_runner` now carries that dict (`result=reported,
  failed=True`) instead of dropping it, and its gate `isinstance(dict) and "text"
  in reported` is the right discriminator between "reported" and "did not".
- `script_tick` holds it as `{"text": ..., "ok": False}`, so the downstream trigger
  mapper produces `error`, not `done`. `agent.py` needed no change because it
  already maps an explicit `False` to `"error"` — the commit message says this and
  it is true.

The requirement text (`openspec/.../bot-coded-agents/spec.md:316`) reads correctly
against the code: "A failed tick MUST still fall back to the planner... Only the
*result* MUST survive, delivered with the failure classification above so it cannot
close the goal as done." The new hold runs before the `return False` and the caller
still gets `handled=False`; both halves hold.

## F-1: a null result becomes the string `"None"`

`script_tick.py:563`:

    text, cut = cap_result(text=str(result.result["text"]))

`cap_result(text=None)` correctly returns `(None, False)` — "no report". But the
call site applies `str()` *before* calling it, so a payload of
`{"text": null, "truncated": false}` becomes `str(None)` = `"None"`, which is not
`None`, and `cap_result` returns the literal string `"None"`.

That payload is reachable: a script that calls `api.result(null)` and then throws.
`binding.js:415` sets `state.result = capResult(null)` -> `{text: null,
truncated: false}`, and `main.js` carries it on the error branch. The agent's gate
accepts it, because the key `"text"` is present.

Driven end to end through the real `_run_script_tick` and `ResultSlot`, on the bytes
of `d4e7d37`:

    PARSED.failed = True
    PARSED.result = {'text': None, 'truncated': False}
    GATE_PASSES = True
    CAP_RESULT = 'None' False
    HAS_PENDING = True
    SLOT = ('goal-A', {'text': 'None', 'truncated': False}, 'error')

So the planner is re-planned and told the bot's report was the four-character string
`None`. The runner's own comment at `binding.js:257-262` states the contract this
breaks: "`None` and 'not reportable at all' are the SAME case... `cap_result` in
`agent/script_tick.py` returns `(None, False)` for exactly these inputs; the two
must agree." They agree in `cap_result`; they disagree at this call site.

Suggested shape (theirs to choose): pass the value, not its `str()`, so
`cap_result(text=result.result["text"])` preserves `None`; the text path already
handles a string correctly. Or guard the call site with `if result.result.get("text")
is not None`. The existing test `cap_result(None)` at `test_script_tick.py:826`
already pins the callee's half; the call site needs the same. Alternatively widen
the parser gate to drop `{text: null}` alongside `null`, which keeps the phantom out
of `last_result` entirely and matches `capResult`'s stated equivalence.

Why no test caught it: every new test carries a real text string. The null case is
the one shape the fixtures do not produce.

## N-1 (not owed): the docstring correction is right

`escalate` really is accepted but never produced — `agent.py:3385` is the only
`_result_slot.store` caller and it produces only `done`/`error`. The two corrected
docstrings (`planner.py`, `result_delivery.py`) now say so, and say it as a spare
seat rather than a live contract. That is the accurate framing.

## Note on my own instrument

My first full-suite background run reported `failures=4, errors=2`. That was mine:
I checked out `d4e7d37` while the suite was already running on a different rev, so
some modules were read before the checkout and some after. Re-run cleanly in a
stable worktree it is `errors=1, skipped=1`, matching the builder. The
`failures=4` figure was never a fact about the commit and I did not report it.

A second instrument fault, caught before filing: `git archive d4e7d37 agent` gives a
tree without `node_modules`, fixtures and the sibling runner, so running the suite
there reds 30 tests that have nothing to do with this change. The numbers in this
review are all from the real worktree.

## Not established

No live bot. The carried-result path is now proven from a real `status: error`
payload through to the planner trigger, which is as far as a serverless review can
go; whether a bot in the world actually throws after reporting has not been
observed, and cannot be here.
