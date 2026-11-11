## ADDED Requirements

### Requirement: Health Endpoint Reports Server Tick Liveness

The mod MUST record the completion time of every server tick on a monotonic clock
(`System.nanoTime()` or equivalent, never wall-clock `System.currentTimeMillis()`),
and `GET /health` MUST fail when that age is older than a configured threshold. The
clock MUST be monotonic: a wall-clock step would fabricate a stall in one direction
and mask a real one in the other.

The endpoint MUST distinguish three `status` values — ticking (`ok`), stalled
(`stalled`) and not yet started (`starting`) — and MUST bound the `starting` state
so that it cannot last forever, because the deployment's startup and liveness
probes (`startupProbe` 60 × 15 s, `livenessProbe` 4 × 30 s) both read this one
endpoint.

`GET /health` MUST be answerable without an API key; the Mod API Server requirement
below records that exception.

The handler MUST answer from its own HTTP thread and MUST NOT execute work on the
server thread. A handler that hops to the server thread would queue behind the
stall it is meant to detect and time out instead of answering, which the probe
would score as a failure of the API rather than of the tick.

Not executing on the server thread is necessary but not sufficient: the handler
also MUST NOT wait for a thread or executor that other API routes can occupy.
This is not hypothetical. On 2026-10-27 a held server thread made `GET /health`
answer nothing at all for 22 consecutive 15 s attempts and the pod was killed by
its liveness probe without a body ever being served; on 2026-10-28 the same
silence began within 20 s of a held tick, with no test load fired, while five
bots polled routes that wait on the server thread. `/health` has the same
port as the rest of the API and therefore serves from an executor that those
routes can fill. A handler that is correct on a quiet server and silent on a
busy one fails the probe exactly when the probe is the only thing that matters,
so the isolation has to hold for the executor as well as for the server thread.

`GET /health` MUST therefore be served from a dedicated HTTP listener, distinct
from the listener that serves every other API route, with its own executor that
no other route can enqueue work onto. The address MUST be this mod's own: when the
probe path and probe port name a dedicated listener and it answers, that listener
is this mod's; it is not required to prove sole ownership of the port against any
other process.

The response body MUST keep the existing `status`, `mod` and `bots` fields and MUST
add `tick_age_seconds` (null before the first tick, otherwise the whole-second age
of the last completed tick). A 503 body MUST carry a `reason`: for a stall it names
the observed age and the configured threshold, and for the never-started case it is
`never ticked`.

The `starting` state MUST be bounded by the startup budget. Measured from the moment
the API server starts listening, once 900 s have passed with no completed tick,
`GET /health` MUST answer 503 with `reason` `never ticked` and `tick_age_seconds`
null. Without that bound a server thread that hangs before its first tick reports
200 `starting` forever: a startup probe passes on the first 200 and no liveness
signal ever fires.

900 s is the deployment's startup allowance (a 60 × 15 s probe budget in the
production pod spec), so the bound is deliberately equal to it: the mod must not
still be claiming `starting` at the moment the platform would give up on it.

The threshold MUST be configurable, resolved in this order: system property
`aiplayermod.health.tickStallSeconds`, environment variable
`AIPLAYER_HEALTH_TICK_STALL_SECONDS`, default **120** seconds. A blank or
whitespace-only value MUST be treated as unset, and that check MUST come before
the malformed-value rule: it is not a misconfiguration, it is how a deployment
says "not configured", so it falls back to the default and logs no WARN. Any
other unparseable or non-positive value MUST fall back to the default and MUST log
exactly one WARN at startup.

The dedicated listener's port MUST be configurable, resolved in this order:
system property `aiplayermod.health.probePort`, environment variable
`AIPLAYER_HEALTH_PROBE_PORT`, default **3101**. The resolver MUST be given the
already-resolved main API port as an input, because that port is itself
configurable (`aiplayermod.api.port` / `AIPLAYER_API_PORT` / 3100) and a
comparison against the constant 3100 would be wrong on any deployment that sets
it. A probe-port value that is blank, unparseable, outside the valid TCP range
(1-65535), or equal to that resolved API port MUST fall back to the default and
MUST log exactly one WARN at startup, naming the rejected value.

The collision MUST be checked at resolution time rather than left to the bind to
discover: a bind failure cannot tell a collision with this mod's own API listener
from another process holding the port, so only an early check can make the
fallback reachable at all. Falling back rather than failing to start is
deliberate: a listener that cannot bind would leave `/health` unanswered, which is
the failure this requirement exists to prevent.

The deployment's probes and this mod move together. The pod spec's probe port is a
literal, not something it reads from the mod, so `startupProbe` and `livenessProbe`
MUST both name the same port the dedicated listener binds
(`AIPLAYER_HEALTH_PROBE_PORT` in the deployment), and they MUST be changed in the
same commit as the code that moves `/health`. A mod that binds 3101 while the
kubelet still probes 3100 turns every probe into a connection refusal: that is a
permanent CrashLoop, a worse outcome than the silence being fixed.

If the dedicated listener cannot be created or started, the mod MUST log an ERROR
naming the port, MUST keep the rest of the API running rather than abort startup,
and MUST NOT serve `/health` from any other listener as a fallback. What the mod
owns is that refusal; whether the pod then fails is the deployment's behaviour,
produced by the kubelet probing a port nothing answers on, not something the mod
can enact. Failing visibly is the point: a silent fallback onto the main listener
would restore, in the one situation where it matters most, exactly the shared
executor this requirement exists to avoid.

#### Scenario: Healthy ticking
- GIVEN the server thread has completed a tick within the threshold
- WHEN `GET /health` is served
- THEN the response status is 200
- AND `status` is `ok`
- AND `tick_age_seconds` is the age of the last completed tick, well under the threshold

#### Scenario: Stalled tick
- GIVEN the server thread has not completed a tick for longer than the threshold
- WHEN `GET /health` is served
- THEN the response status is 503
- AND `status` is `stalled`
- AND `reason` names the observed age and the configured threshold
- AND the response is produced by the HTTP thread without waiting on the server thread, so it arrives within the probe's `timeoutSeconds` (10 s)

#### Scenario: Stalled tick while the main API listener is saturated
- GIVEN the server thread has not completed a tick for longer than the threshold
- AND four requests are in flight to routes that wait on the server thread, so the main API listener's executor has no free thread
- WHEN `GET /health` is served
- THEN it is answered by the dedicated listener
- AND the response status is 503 with `status` `stalled`, within `timeoutSeconds` (10 s)
- AND the answer does not depend on any thread owned by the main API listener
- NOTE: this is the case that failed on 2026-10-27 and 2026-10-28 against the shared-executor implementation, and it is the case the TEST rerun must reproduce

#### Scenario: Main listener saturated, server thread healthy
- GIVEN the server thread is ticking normally
- AND the main API listener's executor has no free thread because of in-flight slow routes
- WHEN `GET /health` is served
- THEN the response status is 200
- AND `status` is `ok`
- AND the reported `tick_age_seconds` is the real age, not a frozen or stale value

#### Scenario: Before the first tick
- GIVEN the mod is loaded and the API server is listening, and less than the startup budget (900 s) has passed since it started listening
- AND no server tick has completed yet
- WHEN `GET /health` is served
- THEN the response status is 200
- AND `status` is `starting`
- AND `tick_age_seconds` is null
- AND the startup probe is not failed by the heartbeat

#### Scenario: No tick before the startup budget expires
- GIVEN the API server has been listening for more than the startup budget (900 s)
- AND no server tick has ever completed
- WHEN `GET /health` is served
- THEN the response status is 503
- AND `status` is `stalled`
- AND `reason` is `never ticked`
- AND `tick_age_seconds` is null

#### Scenario: A long save blocks the server thread
- GIVEN a world save is running on the server thread and blocks it for less than the threshold (prod's world is 2.6 GiB and a full save is expected to block for seconds to tens of seconds; the TEST save check measures the real figure, and the default 120 s is an order of magnitude above the estimate)
- WHEN `GET /health` is served during the save
- THEN the response status is 200
- AND the heartbeat contributes no liveness failures (the endpoint does not answer 503 during the save)
- AND if the save exceeds the threshold the endpoint reports 503 exactly as in the stalled-tick scenario, which is the intended behaviour and is why the default is set above save pauses rather than at the probe period

#### Scenario: Threshold is misconfigured
- GIVEN `aiplayermod.health.tickStallSeconds` (or its environment variable) is set to `0`, a negative number, or a non-numeric string
- WHEN the mod starts
- THEN the threshold is 120 seconds
- AND exactly one WARN line records the ignored value

#### Scenario: Threshold variable is present but empty
- GIVEN `AIPLAYER_HEALTH_TICK_STALL_SECONDS` is set to an empty or whitespace-only value
- WHEN the mod starts
- THEN the threshold is 120 seconds
- AND no WARN line is logged for it

#### Scenario: Probe port falls back when it is unusable
- GIVEN `aiplayermod.health.probePort` (or its environment variable) is blank, unparseable, outside 1-65535, or equal to the resolved main API port
- WHEN the mod starts
- THEN the dedicated listener binds the default port 3101
- AND exactly one WARN line records the rejected value and the port actually used

#### Scenario: Probe port collision is judged against the configured API port
- GIVEN the main API port is configured to 3200 and the probe port is configured to 3200
- WHEN the mod starts
- THEN the probe port falls back to 3101, because the check compares against the resolved API port and not against the default 3100
- AND exactly one WARN line records the collision

#### Scenario: Probe keeps answering after the main listener's executor is saturated
- GIVEN the main API listener's executor has no free thread
- WHEN the probe path and port are requested repeatedly over 30 s or more
- THEN every request is answered, none times out
- AND the answers are served by the dedicated listener, whose executor the main listener cannot reach

#### Scenario: Probe listener cannot bind
- GIVEN the port the dedicated listener must bind is already in use by another process
- WHEN the mod starts
- THEN an ERROR naming the port is logged
- AND the rest of the API still serves its routes
- AND the mod serves `/health` from no other listener, so a probe aimed at that port gets a connection refusal rather than an answer
- AND the resulting probe failure belongs to the deployment, which is what makes the fault visible instead of silently reverting to the shared executor

#### Scenario: Shutdown closes both listeners
- GIVEN the mod is running with both the main API listener and the dedicated probe listener bound
- WHEN the server stops
- THEN both listeners are stopped and their bounds released, so a later start in the same process can bind the same ports

#### Scenario: The agent does not treat a stall as ready
- GIVEN the agent is starting and the mod API answers 503 because the server thread is stalled
- WHEN the agent's readiness loop calls `api.health()`
- THEN it does not conclude the mod API is ready
- AND it retries until the endpoint answers 200 with `status` `ok`

### Requirement: Agent Health Readiness Survives The Port Move
The Python agent's readiness gate MUST keep working when `/health` moves to the
dedicated probe port. The agent reaches the mod over one configurable base URL
(`MOD_API_URL`), not two, so a probe port that defaults to 3101 while the agent's
base URL defaults to `http://localhost:3100` would turn the agent's startup probe
into a permanent 404 `{"error": "not found"}`: `health_is_ready` requires
`status == "ok"`, so the agent would retry 60 times and exit, on every server, with
the mod itself healthy. The agent MUST resolve the `/health` request against the
probe port, and the deployment MUST tell it that port with
`AIPLAYER_HEALTH_PROBE_PORT`, resolved exactly as the mod resolves it (property,
environment, default 3101).

Every other route MUST continue to resolve against the API port: the dedicated
listener serves `/health` and nothing else, so routing all agent traffic at the
probe port would 404 on every bot call. The two ports are resolved from two
settings, not one.

In-repo harnesses that poll `GET /health` to wait for the mod (the agent's
`agent/testing/harness.py` and the pod template's readiness probe) MUST move with
the mod in the same commit, for the same reason the pod spec's probes must: a
health poll against a port that no longer serves `/health` does not fail loudly,
it waits out its whole timeout and reports the server as down.

A readiness probe on the probe port MUST use `httpGet`, not `tcpSocket`. A
`tcpSocket` probe succeeds the moment the port binds, which is true of a listener
whose server thread is held, so it reports Ready on exactly the failure this
change exists to surface. The probe must read a body to tell them apart.

#### Scenario: Agent readiness gate reaches the probe port
- GIVEN the API port is 3100 and the probe port is 3101
- WHEN the agent checks readiness during startup
- THEN `GET /health` is issued to port 3101
- AND an `{"status": "ok"}` body on that port is accepted as ready

#### Scenario: A bound probe port alone is not readiness
- GIVEN the probe port is listening but the server thread is stalled
- WHEN the platform's readiness probe on that port evaluates the pod
- THEN the probe reads `GET /health` and gets a 503 `stalled` body
- AND the pod is not reported Ready, because a bound socket cannot distinguish a
  stalled server from a healthy one

#### Scenario: Bot calls still use the API port
- GIVEN the API port is 3100 and the probe port is 3101
- WHEN the agent lists bots or drives a bot action
- THEN those requests are issued to port 3100, because the probe port serves no other route

#### Scenario: Agent is told a moved probe port
- GIVEN `AIPLAYER_HEALTH_PROBE_PORT` is 3201
- WHEN the agent resolves its health URL
- THEN it uses 3201, so a deployment that moves the probe port does not strand the agent on 3101

#### Scenario: A 404 on the health path is not readiness
- GIVEN a port serves something but not `/health`, answering 404 `{"error": "not found"}`
- WHEN the agent evaluates readiness
- THEN the server is reported not ready rather than ready, because readiness requires `status == "ok"`

## MODIFIED Requirements

### Requirement: Mod API Server
The mod MUST expose a REST API on a configurable port (default: 3100) with optional API key authentication. `GET /health` is served by the dedicated listener described in Health Endpoint Reports Server Tick Liveness, on its own port, not by this listener; that separation is what keeps the probe answerable when this API is saturated. Because that listener needs no API key, the kubelet sends none, and a 401 on `GET /health` would fail every startup and liveness probe.

#### Scenario: Mod API starts on configured port
- GIVEN the mod is loaded with the API port configured to 3100
- WHEN the server starts
- THEN the REST API MUST be listening on port 3100
- AND requests without a valid API key MUST be rejected when authentication is enabled
- AND `GET /health` is served on the dedicated probe port rather than on 3100

#### Scenario: Probe access needs no API key
- GIVEN API key authentication is enabled for the rest of the API
- WHEN `GET /health` is requested on the dedicated probe port without an `X-Api-Key` header
- THEN the request is answered as described in Health Endpoint Reports Server Tick Liveness rather than rejected with 401
- AND the probe port accepts no other route, so the key-free exception cannot widen into key-free access to the rest of the API
