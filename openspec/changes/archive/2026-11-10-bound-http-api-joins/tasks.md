# Tasks

Spec-only change. These tasks become work only after the lead approves implementation.

## 1. Prove the cause before changing a handler

> **CLOSED as "cause inferred, never observed" — lead decision, 2026-11-09T04:21Z
> (option 1).** The cause remains *inferred from the 2026-10-27 evidence and never
> observed* in a thread dump. It is **not reproducible by API load**: `future.complete(...)`
> is the last statement in every `server.execute(...)` lambda, so `boundedJoin` returns as
> soon as the server thread runs and no API-only burst parks a pool thread. The
> 2026-10-27 evidence agrees it was never captured
> (`~/evidence/2026-10-27-health-test-deploy/RESULT.md:94`: "Not proven. No thread dump
> was captured during a live stall"), so there is no existing dump to close this against.
> The bound is still worth having: on a *slow or lagging* server thread the lambda's work
> (AE2 extraction ~`:995`, player-list iteration ~`:2051`) runs before `complete()`, so the
> join genuinely waits and the bound fires. What cannot happen is provoking it from API
> load alone.

**Task marker legend:** `[x]` done · `[ ]` not done · `[~]` **DROPPED or partly
done — read the line, do not assume a pass.** A bare `[~]` with no note would be read
as a tick by the next reader.

- [~] DROPPED (cause stays inferred, lead decision 2026-11-09T04:21Z — never observed)
      1.1 Capture a thread dump during a live stall — **DROPPED, not done.** No live
      stall was captured. `diag-stall.txt` and `diag-threaddump.txt` are boot-state
      captures and must **not** be read as stall evidence.
- [~] DROPPED (cause stays inferred, lead decision 2026-11-09T04:21Z — never observed)
      1.2 Record the dump beside the 2026-10-27 files — **not applicable; no dump
      exists.** The re-scope warning below is retained because it still applies if a
      future revision ever does observe the cause: if a dump does **not** show pool
      threads blocked in `join()`, the pool explanation is wrong and this change must be
      re-scoped.

## 2. Bound the waits

- [x] 2.1 Add one configured timeout value in the API server's configuration, with a
      default that a healthy server never reaches. No per-handler literals.
- [x] 2.2 Bound the 43 `join()` sites in `handleBotAction` (`/bot/`).
- [x] 2.3 Bound the single `join()` in each of `handleServerStructures` (`/server/structures`),
      `handleTempadList` (`/server/tempad`), `handleMeNetworks` (`/server/me_networks`)
      and `handlePlayers` (`/server/players`).
- [x] 2.4 Confirm each wait still does its work on the server thread; only the waiting is bounded.

## 3. Report timeouts honestly

- [x] 3.1 Return HTTP `503` with a JSON `error` naming the timeout when a bound expires.
- [~] 3.2 **Partly done.** `BoundedWait.DEFAULT_TIMEOUT_MS` is guarded at >= 1000 ms so
      ordinary latency cannot trip it (`defaultTimeoutIsFarAboveOrdinaryLatency`), and
      `BoundedHandlerTest.healthyHandlerIsUntouchedByTheWrapper` shows the wrapper leaves a
      normal response alone. Confirming no `503` under real traffic still needs TEST and
      stays in the deploy run plan.

## 4. Tests

- [x] 4.1 A test that stalls the server thread and asserts a hopped request returns `503`
      with an `error` body inside the bound. Covered end to end by
      `BoundedHandlerTest.blockedHandlerReturns503WithAnErrorNamingTheTimeout`, which
      drives a real `HttpServer` through `BoundedHandler` on loopback.
- [x] 4.2 A test that four concurrent hopped requests all get the timeout outcome and the
      pool accepts new work afterwards. `BoundedHandlerTest.thePoolAcceptsNewWorkAfterBlockedRequestsTimeOut`
      fills all four pool threads and then serves a healthy request.
- [x] 4.3 A test that a healthy server returns the normal success body for the same endpoints.
      `BoundedHandlerTest.healthyHandlerIsUntouchedByTheWrapper` serves the same wrapper with a
      handler that answers normally and asserts the 200 body is unchanged.

## 5. Verify on TEST before any prod consideration

> **Deploy watch item (reviewer, 2026-11-06).** Inventory POST calls `clearContent()`
> before completing, so on a stall the client can now receive `503` while the queued
> restore still lands. This ordering predates the bound; the `503` only makes it
> visible. During the TEST run, re-read the inventory after a stall and reconcile
> against the expected contents — do not treat a `503` as "nothing happened".

- [x] 5.1 Deploy to `minecraft-test` only, under a reviewed plan with a rollback command.
      (Done 2026-11-09 on TEST, jar b0c934e5; then PROD 2026-11-10T04:24Z under a reviewed plan.)
- [~] 5.2 NOT RUN (lead decision 2026-11-09: not authorised; on a fast server it would not reach
      the bound). The 503 is proven at unit level only; no live 503 has been observed.
      Re-run the 2026-10-27 stall procedure: with the server thread held, a hopped
      request must answer `503` inside the bound instead of hanging.
- [x] 5.3 (Verified on TEST and PROD: 3101 /health 200, 3100 /health 404, as before.) Confirm `/health` behaviour is unchanged (it is on its own listener and out of scope).
      Re-read this before starting: the 2026-11-06 review reported no `minecraft-server`
      Service in `minecraft-test`. The Service exists under the name
      `minecraft-test-server` (NodePort, 217d) and carries minecraft 25565, rcon 25575,
      aibot-api 3100, and health-probe `3101:31049` with targetPort 3101. The review
      searched for the substring `minecraft-server`, which that name does not contain,
      and read the empty result as an absence. Check the live Service by namespace
      listing at the time this task runs, not by a name guess.
