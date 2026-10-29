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
the API server starts listening, once 900 s (the `startupProbe`'s full 60 × 15 s
budget) have passed with no completed tick, `GET /health` MUST answer 503 with
`reason` `never ticked` and `tick_age_seconds` null. Without that bound a server
thread that hangs before its first tick reports 200 `starting` forever: the startup
probe passes on the first 200 and the liveness probe never fires.

The threshold MUST be configurable, resolved in this order: system property
`aiplayermod.health.tickStallSeconds`, environment variable
`AIPLAYER_HEALTH_TICK_STALL_SECONDS`, default **120** seconds. An unparseable or
non-positive value MUST fall back to the default and MUST log exactly one WARN at
startup. A blank value MUST be treated as unset: it falls back to the default and
logs no WARN, because a set-but-empty variable is how a deployment says "not
configured" rather than a mistake the operator needs to be told about.

The dedicated listener's port MUST be configurable, resolved in this order:
system property `aiplayermod.health.probePort`, environment variable
`AIPLAYER_HEALTH_PROBE_PORT`, default **3101**. A value that is unparseable, not a
valid TCP port (1-65535), or equal to the main API port MUST fall back to the
default and MUST log exactly one WARN at startup. Falling back rather than failing
is deliberate: a listener that cannot bind would leave `/health` unanswered, which
is the failure this requirement exists to prevent, and the deployment's probe
would then kill the pod it is meant to protect.

If the dedicated listener cannot be created or started, the mod MUST log an ERROR
naming the port and MUST keep the rest of the API running rather than abort
startup, so that the outcome is a visibly failing probe instead of a dead server.

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
- GIVEN `aiplayermod.health.probePort` (or its environment variable) is unparseable, outside 1-65535, or equal to the main API port
- WHEN the mod starts
- THEN the dedicated listener binds the default port 3101
- AND exactly one WARN line records the ignored value

#### Scenario: Probe keeps answering after the main listener's executor is saturated
- GIVEN the main API listener's executor has no free thread
- WHEN the probe path and port are requested repeatedly over 30 s or more
- THEN every request is answered, none times out
- AND the answers are served by the dedicated listener, whose executor the main listener cannot reach

#### Scenario: Probe listener cannot bind
- GIVEN the dedicated listener's port is already in use by another process
- WHEN the mod starts
- THEN an ERROR naming the port is logged
- AND the rest of the API still serves its routes
- AND the probe fails visibly (it is not answered by the main listener as a silent fallback)

#### Scenario: The agent does not treat a stall as ready
- GIVEN the agent is starting and the mod API answers 503 because the server thread is stalled
- WHEN the agent's readiness loop calls `api.health()`
- THEN it does not conclude the mod API is ready
- AND it retries until the endpoint answers 200 with `status` `ok`

## MODIFIED Requirements

### Requirement: Mod API Server
The mod MUST expose a REST API on a configurable port (default: 3100) with optional API key authentication, except that probe endpoints MUST be answerable without an API key: the kubelet sends none, and a 401 on `GET /health` would fail every startup and liveness probe. `GET /health` is the probe endpoint this exception covers.

#### Scenario: Mod API starts on configured port
- GIVEN the mod is loaded with the API port configured to 3100
- WHEN the server starts
- THEN the REST API MUST be listening on port 3100
- AND requests without a valid API key MUST be rejected when authentication is enabled, except `GET /health`

#### Scenario: Probe access needs no API key
- GIVEN API key authentication is enabled for the rest of the API
- WHEN `GET /health` is requested without an `X-Api-Key` header
- THEN the request is answered as described in Health Endpoint Reports Server Tick Liveness rather than rejected with 401
