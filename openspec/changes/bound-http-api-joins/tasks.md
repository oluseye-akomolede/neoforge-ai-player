# Tasks

Spec-only change. These tasks become work only after the lead approves implementation.

## 1. Prove the cause before changing a handler

- [ ] 1.1 Capture a thread dump during a live stall:
      `kubectl -n minecraft-test exec deploy/minecraft-test-server -c mc-server -- kill -3 1`
      then read the pod log tail for `http-pool-N` stacks awaiting
      `CompletableFuture.join()`.
- [ ] 1.2 Record the dump in the evidence directory beside the 2026-10-27 files.
      If the dump does **not** show pool threads blocked in `join()`, stop and report:
      the pool explanation is then wrong and this change must be re-scoped.

## 2. Bound the waits

- [ ] 2.1 Add one configured timeout value in the API server's configuration, with a
      default that a healthy server never reaches. No per-handler literals.
- [ ] 2.2 Bound the 43 `join()` sites in `handleBotAction` (`/bot/`).
- [ ] 2.3 Bound the single `join()` in each of `handleServerStructures` (`/server/structures`),
      `handleTempadList` (`/server/tempad`), `handleMeNetworks` (`/server/me_networks`)
      and `handlePlayers` (`/server/players`).
- [ ] 2.4 Confirm each wait still does its work on the server thread; only the waiting is bounded.

## 3. Report timeouts honestly

- [ ] 3.1 Return HTTP `503` with a JSON `error` naming the timeout when a bound expires.
- [ ] 3.2 Confirm a healthy server never produces this response under normal traffic.

## 4. Tests

- [ ] 4.1 A test that stalls the server thread and asserts a hopped request returns `503`
      with an `error` body inside the bound.
- [ ] 4.2 A test that four concurrent hopped requests all get the timeout outcome and the
      pool accepts new work afterwards.
- [ ] 4.3 A test that a healthy server returns the normal success body for the same endpoints.

## 5. Verify on TEST before any prod consideration

- [ ] 5.1 Deploy to `minecraft-test` only, under a reviewed plan with a rollback command.
- [ ] 5.2 Re-run the 2026-10-27 stall procedure: with the server thread held, a hopped
      request must answer `503` inside the bound instead of hanging.
- [ ] 5.3 Confirm `/health` behaviour is unchanged (it is on its own listener and out of scope).
