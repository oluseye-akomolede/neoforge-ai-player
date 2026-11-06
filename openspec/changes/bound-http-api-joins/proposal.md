# Bound the `join()` calls in the HTTP API handlers

## Why

`HttpApiServer` serves every API route from one fixed pool of four threads
(`HttpApiServer.java:54`, `Executors.newFixedThreadPool(4)`). Many handlers hop to
the main server thread with `BotManager.getServer().execute(...)` and then block the
pool thread on `CompletableFuture.join()`. When the server thread is stalled, four
such requests in flight occupy all four pool threads and every other route queues
behind them.

On 2026-10-27 this was measured, not theorised: with the server thread held,
`GET /health` answered nothing at all for 22 consecutive 15 s attempts (connection
open, no reply), and the kubelet killed the pod on liveness timeout. The requester
saw a request that never answers instead of an error.

`/health` has since moved to its own listener with its own executor (change
`agent-health-hygiene`), so the user-visible failure — a probe that cannot speak
during a stall — is already fixed. This change is **defence in depth** for the
remaining API routes. It does not revisit that fix and must not be folded into it.

## What was wrong with the original scope statement

This work was filed as "bound the 22 remaining endpoints". Reading the current code
shows that figure is not a scope. Across the 22 registered routes there are 47
`.join()` calls, and **all 47 sit inside 5 handlers**:

| Route | Handler | `join()` calls |
|---|---|---|
| `/bot/` | `handleBotAction` | 43 |
| `/server/structures` | `handleServerStructures` | 1 |
| `/server/tempad` | `handleTempadList` | 1 |
| `/server/me_networks` | `handleMeNetworks` | 1 |
| `/server/players` | `handlePlayers` | 1 |

The other 17 routes contain no `join()` at all. They may dispatch work to the server
thread, but they do not block the pool thread waiting for it, so they cannot pin a
pool slot. A handler that never blocks cannot starve the pool.

Two consequences follow, and both shape the delta:

1. **The unit of change is the blocking call site, not the route.** `/bot/` alone
   holds 43 of the 47, so a change that treats all routes as equally costly would put
   most of its effort in the wrong place.
2. **A route must not be bounded merely because it is a route.** Adding a timeout to
   a fire-and-forget dispatch would change behaviour that is already correct.

## Scope

In scope: the 5 handlers above and their 47 blocking `join()` call sites, plus a cap on
how long a request may occupy a pool thread.

Out of scope: `/health` (already isolated), the 17 non-blocking routes, any change to
the routes' request or response shapes other than the new timeout outcome, and any
change to how work is dispatched to the server thread.

## What is deliberately not claimed

No thread dump was captured during a live stall; the two attempts on 2026-10-27
failed (`RESULT.md` records this explicitly). The pool explanation is established from
the code and from two independent clients observing the same blackout, which is
strong but is not a thread dump. The first task of the implementation, if this change
is approved, is to capture one
(`kubectl -n minecraft-test exec deploy/minecraft-test-server -c mc-server -- kill -3 1`)
so the cause is proved rather than inferred before any handler is altered.

This proposal does not assert that a bound eliminates the starvation window. Four
blocked handlers can still occupy all four threads until their bound expires. The
guarantee is that the occupation is *bounded and the client is told*, not that it
cannot happen.
