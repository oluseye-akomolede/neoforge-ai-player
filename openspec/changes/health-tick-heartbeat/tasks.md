# Health tick heartbeat — tasks

Spec-first: nothing under Implementation is done. The spec was written from
`HttpApiServer.java:105-111`, the tick hook at `AIPlayerMod.java:126-127`, and the
probe blocks in both live manifests; the reviewer gates it before any code exists.

## Spec (this change)

- [ ] `Health Endpoint Reports Server Tick Liveness` added to `api-http`, seven scenarios (healthy, stalled, before first tick, long save, misconfigured threshold, agent readiness, no API key required)
- [ ] `openspec validate health-tick-heartbeat --strict` passes

## Implementation

- [ ] Heartbeat: `volatile long lastTickNanos`, stamped with `System.nanoTime()` at the END of `onServerTick(ServerTickEvent.Post)` (`AIPlayerMod.java:127`) — the end, so a tick that throws does not refresh it
- [ ] `/health`: three states from the age — `ok` (≤ threshold), `stalled` (> threshold, 503 + `reason`), `starting` (never ticked, 200 + null age); keep `status`/`mod`/`bots`, add `tick_age_seconds`; serve from the HTTP thread, no `server.execute`
- [ ] Threshold resolution: `aiplayermod.health.tickStallSeconds` → `AIPLAYER_HEALTH_TICK_STALL_SECONDS` → 120; unparseable or ≤ 0 falls back to 120 with exactly one WARN (same idiom as the API port at `AIPlayerMod.java:64-67`)
- [ ] Unit tests with an injected clock: fresh tick → 200/`ok`; age beyond threshold → 503/`stalled`; never ticked → 200/`starting`; `0`, negative and non-numeric thresholds → 120 plus one WARN; body keeps `mod` and `bots`
- [ ] Agent readiness: `agent/agent.py:4141-4147` requires `status == "ok"` (or HTTP 200) before it stops retrying — today any JSON reply, including a 503 body, ends the loop (`agent/api.py:15-17`)
- [ ] Agent-side test for that readiness check (the harness's 200 requirement at `agent/testing/harness.py:116-118` already matches)

## Verification (TEST first, then prod)

- [ ] TEST: normal boot passes the startup probe and `/health` reports `ok` with a small age
- [ ] TEST: hold the server thread past the threshold (a temporary stall hook behind a system property, removed before merge) and watch `/health` turn 503/`stalled` and the pod restart; confirm the handler still answers within `timeoutSeconds: 10`
- [ ] TEST: a normal autosave, and a `/save-all` on the 2.6 GiB world, produce no 503 — this is the case the 120 s default exists for
- [ ] TEST: `/health` on a fresh pod answers 200 `starting` before the first tick (restart the pod and curl it during boot)
- [ ] Prod, after the owner's go: no restart caused by the probe over a 24 h window, and the WorldTick age stays bounded in the logs
- [ ] `openspec archive health-tick-heartbeat` once the code ships, so `openspec/specs/api-http/spec.md` describes the live endpoint

## Deferred

- [ ] Changing the probe settings themselves (`livenessProbe` thresholds) — out of scope; the current 4 × 30 s is what the 120 s default is justified against
- [ ] Surfacing tick age on the dashboard — the agent's `/api/health` (`agent/dashboard/server.py:550`) is a different endpoint and unchanged here
