# M2 8.3.4 — why the script produces zero actions: it returns, the runner ignores returns

Measured 2026-11-13T04:5xZ on TEST, pod `aibot-agent-test-6f64489bc9-xgg6d`,
runner `agent-script-runner-c4596854f-kgvr7` (image `sha256:6e079944...`).
All read-only: every call was a `POST /v1/tick` through the agent's own
`script_tick._default_transport()`. No config changed.

## The two contracts disagree

The runner's action channel is `api.do(kind, args)`:

    src/worker.js:86      actions: state.actions ?? []
    src/engine.js:367-368 "§4.4's rule that the return value is ignored holds either way"

`scout.js` emits its action by RETURNING an array from `tick()`:

    return [
      { kind: "STORE_ALL" }
    ];

and ends with a bare `tick();`. The runner wraps the source as a function body
and discards the value, so `state.actions` is empty on every tick.

## Proof, same runner and same snapshot, only the source differing

Deployed `scout.js` bytes (4893 bytes, `838efd891994f434`) with an idle
directive, health 20, 16 cobblestone in inventory:

    {"status":"ok","actions":[],"cpu_ms":0.598,"wall_ms":2.96,"cold":false}

A probe whose only difference is that it calls `api.do`:

    function tick(){ api.do("STORE_ALL", {}); }
    tick();

    {"status":"ok","actions":[{"seq":1,"call":"do","directive":"STORE_ALL","args":{}}]}

Same three task shapes tried against the deployed script (idle-progress,
no-task, busy) all returned `[]`, so the suppression is not the guard.

## Why no agent log line either

`script_tick.py:188` returns `handled=True, actions=[], "script chose silence"`.
`agent.py:2682-2684` then hits `if not actions: return False` with NO print.
So a script that runs, succeeds, and proposes nothing is completely silent in
the agent log. Zero `[Scout/script]` lines is the correct signature of both
"working script choosing silence" and "action discarded" — the two are
indistinguishable from the agent log alone.

## Why the test suite did not catch it

`agent/test_scout_script.py:42` rewrites the script before running it:

    body = src.replace("\ntick();", "\n;return tick();")

and `:43` enforces that the rewrite applied:

    assert body != src, "scout.js no longer ends with a bare tick(); update this test"

It then runs the REWRITTEN body under its own `new Function(...)` harness, which
does read the return value, with `api.do` stubbed to a no-op (`:49`). So the
test asserts on a contract the runner does not implement, and the stub removes
the only channel the runner actually reads.

## Fix direction (not implemented, awaiting the lead)

`scout.js` should emit via `api.do("STORE_ALL", {})` instead of returning an
array, and `test_scout_script.py` must stop rewriting the source and must assert
against the runner's real collection path rather than a stubbed `api.do`.
