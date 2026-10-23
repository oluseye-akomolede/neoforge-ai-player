# Health tick heartbeat — `/health` must fail when the server thread stalls

## Why

`/health` never touches the server thread. `HttpApiServer.handleHealth`
(`src/main/java/com/sigmastrain/aiplayermod/api/HttpApiServer.java:105-111`)
is served by a 4-thread pool (`:45`, registered at `:47`) and answers
`200 {"status":"ok","mod":…,"bots":…}` from a map literal. It cannot tell a
healthy server from one whose server thread has stopped.

Both deployments probe exactly that endpoint, and both state that the probe is
the watchdog for a hung server:

- prod `clustering/manifests/base/minecraft/deployment.yaml:223-229` —
  `httpGet /health:3100`, `periodSeconds: 30`, `failureThreshold: 4`; the
  comment at `:219-222` says the probe was added after the May 26 zombie
  incident and that "4 * 30s = 2 min of API blackout now triggers an automatic
  pod restart".
- test `clustering/manifests/base/minecraft/test-server.yaml:257-263` — the
  same numbers, with the comment at `:254-256`: "if the mod API stops answering
  for 4 * 30s = 2 min, the server has hung (GC death-spiral, deadlock, zombie
  shutdown). Kill the pod".

The blackout those comments rely on never happens in the case they were written
for: a stalled server thread leaves the HTTP executor threads alive, so `/health`
keeps answering 200 while nothing in the world moves. That is the gap recorded
in `qitem-20261002033056-5ab50678`. The owner approved this fix on 2026-10-23
(Slack, "2 yes").

## What

A tick heartbeat, and a `/health` that reads it:

1. **Stamp** — a `volatile long lastTickNanos` set at the end of every completed
   server tick. The mod already has the hook: `onServerTick(ServerTickEvent.Post)`
   at `AIPlayerMod.java:126-127`.
2. **Read** — `handleHealth` compares `now - lastTickNanos` against a configured
   threshold and returns **503** with a short reason when the age exceeds it.
   It stays on the HTTP thread: it MUST NOT hop to the server thread
   (`server.execute`), because a hop would queue behind the very stall it is
   trying to detect and would time out instead of answering.
3. **Never ticked** — before the first tick the heartbeat is unset and
   `/health` answers **200** with `"status":"starting"`. The API server starts
   at `ServerStartedEvent` (`AIPlayerMod.java:53,86-88`), which precedes the
   first tick, and the startup probe has to keep passing. That state is
   **bounded**: 900 s after the API server starts listening (exactly the
   startup probe's own budget) a still-never-ticked server answers **503**
   with `"reason":"never ticked"`. Unbounded, a server thread that hangs before
   its first tick would answer 200 forever: the startup probe passes on the
   first 200 and liveness never fires.
4. **Threshold** — system property `aiplayermod.health.tickStallSeconds`, else
   env `AIPLAYER_HEALTH_TICK_STALL_SECONDS`, else **120**; an unparseable or
   non-positive value falls back to the default with one WARN. This follows the
   existing API-port idiom (`aiplayermod.api.port` / `AIPLAYER_API_PORT`,
   `AIPlayerMod.java:64-67`).

No manifest change. The existing probe settings are what make the default safe
(below); changing them is explicitly out of scope for this change.

### Why 120 seconds

The threshold is a **heartbeat age**, not a tick rate: TPS does not enter into
it (20 TPS and the condenser baseline's 5-7 TPS behave the same as long as ticks
complete). Three things set the floor:

- **Detection is ~120 s; getting back to serving is 10-15 minutes.** The endpoint
  turns 503 as soon as the age passes the threshold, and liveness then needs four
  consecutive failures at `periodSeconds: 30` (`deployment.yaml:223-229`), so the
  container is killed ~240 s after the stall began. That 240 s is kill time, not
  recovery: on a hung server `preStop` can burn up to 240 s of its own
  (30 + 180 + 30 s, `deployment.yaml:128-137`, inside the 300 s grace at `:21`),
  and a modded boot is 5-10 minutes, so the pod is serving again roughly 10-15
  minutes after the stall. That is the figure to judge this against — still far
  better than the fifteen-minute incident it exists for, and the detection half
  is bounded and observable.
- **Save pauses must not trip it.** The prod world is 2.6 GiB on the `/data`
  volume (`du -sh /data/world` in the running prod pod, 2026-10-23), and vanilla
  saves run on the server thread. A full save is expected to block it for seconds
  to tens of seconds (not measured on prod yet; the TEST save check measures it).
  At 120 s there is an order-of-magnitude margin against that estimate. A 30 s default would
  sit inside that range: one slow autosave would produce 503s, and with probes at
  exactly 30 s a healthy server could reach four failures and be restarted
  mid-save — the outcome this probe exists to prevent.
- **Startup must never fail it.** Before the first tick, `/health` is 200
  "starting" (point 3), and liveness only begins after the startup probe has
  passed once (60 × 15 s = 15 min, `deployment.yaml:212-218`,
  `test-server.yaml:247-253`). A 5-10 minute modded boot therefore never touches
  the heartbeat.

### Shutdown is unchanged

`onServerStopping` posts from `runServer` at `MinecraftServer:730`, before
`stopServer()` saves at `:748`, and stops the API server (`AIPlayerMod.java:92-97`),
so during the shutdown save `/health` is already refusing connections — the
heartbeat is not consulted after that point and this change does not alter that
path. Caveat: a hard JVM crash or `SIGKILL` skips that event, but it also takes the
HTTP listener down with it, so no answer is served from a dead process. The case
this change covers is the JVM that is alive with the server thread stalled — which
is exactly the May 26 zombie.

## Consumers

- `agent/agent.py:4141-4144` starts the agent by calling `api.health()` in a retry
  loop and `break`s on **any** JSON reply (`_get` at `agent/api.py:15-17` does not
  raise on a non-2xx). A 503 `stalled` body would therefore read as "mod API
  connected", and so would a 200 `starting` one. The loop must require
  `status == "ok"` before it stops retrying. One task below.
- `agent/testing/harness.py:116-118` already waits for HTTP 200 — compatible as
  written.
- The dashboard's `/api/health` (`agent/dashboard/server.py:550-556`) is a
  passthrough that returns whatever the mod's `/health` returns, so it now shows
  `stalled`/`starting` too. That is the information the dashboard wants; no
  dashboard change is needed.

## Impact

- Spec: `api-http` gains one requirement (`Health Endpoint Reports Server Tick
  Liveness`, seven scenarios) and **modifies** `Mod API Server`. The
  modification adds the key-free probe exception and a `Probe access needs no API
  key` scenario; it also amends the last step of `Mod API starts on configured
  port` (`openspec/specs/api-http/spec.md:15`) to except `GET /health`. That step
  read "requests without a valid API key MUST be rejected", which contradicted a
  working probe — and `handleHealth` (`HttpApiServer.java:105-111`) never calls
  the auth check (`:94-99`) today, so the live spec is already behind the code.
  The endpoint table entry for `/health` (`openspec/specs/api-http/spec.md:33`)
  stays true.
- Code: two files (heartbeat + handler) and the agent readiness check. No jar, no
  image, no manifest, no probe change.
- Rollback: revert the code commit; the endpoint returns to the unconditional 200.
