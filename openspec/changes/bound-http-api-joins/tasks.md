# Tasks

Spec-only change. These tasks become work only after the lead approves implementation.

## 1. Prove the cause before changing a handler

> **Deferred by the lead, 2026-11-06.** Section 1 is not part of the code change. It
> touches TEST, so it moves into the deploy run plan that the reviewer gates later.
> Keep it here as the first step of that plan; do not retire it.

- [ ] 1.1 Capture a thread dump during a live stall:
      `kubectl -n minecraft-test exec deploy/minecraft-test-server -c mc-server -- kill -3 1`
      then read the pod log tail for `http-pool-N` stacks awaiting
      `CompletableFuture.join()`.
- [ ] 1.2 Record the dump in the evidence directory beside the 2026-10-27 files.
      If the dump does **not** show pool threads blocked in `join()`, stop and report:
      the pool explanation is then wrong and this change must be re-scoped.

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

- [ ] 5.1 Deploy to `minecraft-test` only, under a reviewed plan with a rollback command.
- [ ] 5.2 Re-run the 2026-10-27 stall procedure: with the server thread held, a hopped
      request must answer `503` inside the bound instead of hanging.
- [ ] 5.3 Confirm `/health` behaviour is unchanged (it is on its own listener and out of scope).
      Re-read this before starting: the 2026-11-06 review reported no `minecraft-server`
      Service in `minecraft-test`. The Service exists under the name
      `minecraft-test-server` (NodePort, 217d) and carries minecraft 25565, rcon 25575,
      aibot-api 3100, and health-probe `3101:31049` with targetPort 3101. The review
      searched for the substring `minecraft-server`, which that name does not contain,
      and read the empty result as an absence. Check the live Service by namespace
      listing at the time this task runs, not by a name guess.
