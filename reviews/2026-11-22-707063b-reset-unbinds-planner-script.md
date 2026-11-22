# 707063b: a reset unbinds the planner's script

Rev reviewed: `707063b`. Closes my F-1 on `1e2a789`.
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**PASS. F-1 is closed.** No findings.

## What the fix does

`reset()` now mirrors the stop path exactly, through the same two calls rather
than a second mechanism (`agent.py:575-582`):

    if self._unbind_planner_script():
        print(f"[{self.name}/reset] unbound the planner's script")
    else:
        self._halt_script_for_stop()

A planner script is unbound outright; a hand-written one is halted with its
binding kept, so the player's `bindings.json` deployment survives. That is the
right pair of outcomes — my F-1 named only the first, and erasing a player's
deployment on RESET would have been a worse bug than the one I reported.

## Verified at this rev

All rc read unpiped from a file:

- `test_agent_script_branch`: **138 pass, rc=0**.
- Full agent suite: **Ran 637, errors=1, skipped=1**. The error is the
  pre-existing `ImportError: dashboard` (missing uvicorn).
- `openspec validate coded-agents --strict` **rc=0**.

**Mutants, each anchored with an `assert` on its pattern, restored
`cmp`-identical:**

| Mutant | Removed | Result |
|---|---|---|
| 1 | the whole reset block | 2 red — both reset tests |
| 2 | only the `_halt_script_for_stop()` call | 1 red — the halt test |
| 3 | the `_script_halted_for_stop` gate in `_get_script_tick` (`:4184`) | 2 red — reset **and** stop halt tests |

All three reproduce the commit's claims exactly.

## The half I checked that the tests do not

Halting with the binding intact only helps if something lifts the halt. I
traced it: the lift is in `_begin_script_hold` (`agent.py:1749-1753`), which I
verified earlier has exactly two callers, both L3 plan-accept paths. So a
reset-halted hand-written script dispatches again on the next accepted goal,
which is the spec's third `THEN`. The claim holds — and it holds because of a
property of a different method, which is exactly the coupling that made the
original bug possible in reverse. Worth knowing it is still coupled.

The commit's note about its first gate mutant matching nothing (the guard is
written `getattr(...)`, so a literal-pattern patch found no text, ran clean and
read as a survivor) is the same species as my own `SCRIPT_IDLE_MAX` survivor
and my `SyntaxError` mutant tonight. Anchoring every patch with `assert old in
s` is the right mitigation and it is now in their diff.

## Not established

No live bot. Nothing deployed. Whether an in-game "All tasks cleared" actually
reaches `reset()` on a running deployment is unobserved here; the Python path
is proven, the wire is not.
