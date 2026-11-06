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
- [~] 3.2 **Partly done (unit layer).** `BoundedWait.DEFAULT_TIMEOUT_MS` is guarded
      at >= 1000 ms so ordinary latency cannot trip it
      (`defaultTimeoutIsFarAboveOrdinaryLatency`); confirming no `503` under real
      traffic needs TEST and is part of the deploy run plan.
      Original: Confirm a healthy server never produces this response under normal traffic.

## 4. Tests

- [~] 4.1 **Partly done (unit layer).** The wait itself is covered by
      `BoundedWaitTest.fourBlockedWaitersAllReleaseAtTheBound` and
      `expiredBoundRaisesTimeoutRatherThanHanging`; the HTTP `503` body end-to-end
      needs a running server and belongs to the deploy run plan.
      Original: A test that stalls the server thread and asserts a hopped request returns `503`
      with an `error` body inside the bound.
- [x] 4.2 A test that four concurrent hopped requests all get the timeout outcome and the
      pool accepts new work afterwards.
- [~] 4.3 **Partly done (unit layer).** A completed future returns its value
      unchanged (`BoundedWaitTest.completedFutureReturnsItsValueWithoutWaiting`); the
      endpoint-level healthy-server check needs a running server and moves to the
      deploy run plan with 4.1.
      Original: A test that a healthy server returns the normal success body for the same endpoints.

## 5. Verify on TEST before any prod consideration

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
