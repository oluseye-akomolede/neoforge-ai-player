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
startup.

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
