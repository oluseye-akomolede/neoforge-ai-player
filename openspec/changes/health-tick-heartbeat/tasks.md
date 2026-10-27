# Health tick heartbeat — tasks

Spec-first: nothing under Implementation is done. The spec was written from
`HttpApiServer.java:105-111`, the tick hook at `AIPlayerMod.java:126-127`, and the
probe blocks in both live manifests; the reviewer gates it before any code exists.

## Spec (this change)

- [x] `Health Endpoint Reports Server Tick Liveness` added to `api-http`, seven scenarios (healthy, stalled, before first tick, no tick before the startup budget, long save, misconfigured threshold, agent readiness), plus a MODIFIED `Mod API Server` with the key-free probe exception and two scenarios (the amended port scenario and `Probe access needs no API key`) (eb5f1cd, openspec/changes/health-tick-heartbeat/specs/api-http/spec.md:3)
- [x] `openspec validate health-tick-heartbeat --strict` passes (eb5f1cd)

## Implementation

- [x] Heartbeat: `volatile long lastTickNanos`, stamped with `System.nanoTime()` at the END of `onServerTick(ServerTickEvent.Post)` (`AIPlayerMod.java:127`) — the end, so a tick that throws does not refresh it; monotonic clock throughout, no `currentTimeMillis` (6ec20b3, AIPlayerMod.java:164)
- [x] `/health`: states from the age — `ok` (≤ threshold), `stalled` (> threshold, 503 + `reason` naming age and threshold), `starting` (never ticked, 200 + null age), and `never ticked` (503 + `reason` `never ticked` once 900 s have passed since the API server started listening with no tick); keep `status`/`mod`/`bots`, add `tick_age_seconds`; serve from the HTTP thread, no `server.execute` (6ec20b3, HttpApiServer.java:112)
- [x] Threshold resolution: `aiplayermod.health.tickStallSeconds` → `AIPLAYER_HEALTH_TICK_STALL_SECONDS` → 120; unparseable or ≤ 0 falls back to 120 with exactly one WARN (same idiom as the API port at `AIPlayerMod.java:64-67`) (6ec20b3, TickHeartbeat.java:87)
- [x] Unit tests with an injected clock: fresh tick → 200/`ok`; age beyond threshold → 503/`stalled`; never ticked inside the budget → 200/`starting`; never ticked past 900 s → 503/`never ticked`; `0`, negative and non-numeric thresholds → 120 plus one WARN; body keeps `mod` and `bots`; a wall-clock jump must not move the age (6ec20b3, TickHeartbeatTest.java:37)
- [x] Unit test, permanent: `handleHealth` never calls `server.execute` or otherwise waits on the server thread (a fake executor that throws), so the no-hop property survives after the temporary stall hook is deleted (6ec20b3, TickHeartbeatTest.java:210)
- [x] Agent readiness: `agent/agent.py:4141-4144` requires `status == "ok"` before it stops retrying — today any JSON reply ends the loop (`_get` at `agent/api.py:15-17`), so both a 503 `stalled` and a 200 `starting` body would be read as ready (6ec20b3, agent/agent.py:4145)
- [x] Agent-side test for that readiness check (the harness's 200 requirement at `agent/testing/harness.py:116-118` already matches) (6ec20b3, agent/tests/test_health_readiness.py:20)

## Verification (TEST first, then prod)

- [x] TEST: normal boot passes the startup probe and `/health` reports `ok` with a small age (~/evidence/2026-10-27-health-test-deploy/phase-a.txt, 04:18:49Z: 200 `ok`, age 0, restartCount 0)
- [ ] TEST: hold the server thread past the threshold (a temporary stall hook behind a system property, removed before merge) and watch `/health` turn 503/`stalled` and the pod restart; confirm the handler still answers within `timeoutSeconds: 10` — ran 04:31-04:43Z, FAILED — a violation of the existing `Stalled tick` scenario, not a spec gap: the endpoint does not answer at all under the deployment's own traffic, so it cannot answer 503 (22 consecutive 15 s timeouts, no body, liveness kill): ~/evidence/2026-10-27-health-test-deploy/phase-C/phase-c.txt, phase-C/probe-events.txt
- [ ] TEST: a normal autosave, and a `/save-all` on the 2.6 GiB world, produce no 503 — this is the case the 120 s default exists for
- [x] TEST: `/health` on a fresh pod answers 200 `starting` before the first tick (restart the pod and curl it during boot) (~/evidence/2026-10-27-health-test-deploy/phase-a.txt, 04:18:49Z: 200 `starting`, `tick_age_seconds` null; phase-b2.txt 04:29:50-04:30:22Z: 17 samples) — note: both runs hit the same API blackout before the procedure's 20-sample bar; see RESULT.md
- [ ] TEST: hold the server thread from boot, before the first tick, past the 900 s startup budget and watch `/health` turn 503 `never ticked` and the startup probe fail — this is the bound that stops a pre-first-tick hang reporting 200 forever
- [ ] Prod, after the owner's go: no restart caused by the probe over a 24 h window, the WorldTick age stays bounded in the logs, and a deliberate stall is measured end to end (expect ~10-15 min back to serving: ~240 s to kill plus preStop and boot)
- [ ] `openspec archive health-tick-heartbeat` once the code ships, so `openspec/specs/api-http/spec.md` describes the live endpoint

## Deferred

- [ ] Changing the probe settings themselves (`livenessProbe` thresholds) — out of scope; the current 4 × 30 s is what the 120 s default is justified against
- [ ] Surfacing tick age on the dashboard — the agent's `/api/health` (`agent/dashboard/server.py:550`) is a different endpoint and unchanged here
