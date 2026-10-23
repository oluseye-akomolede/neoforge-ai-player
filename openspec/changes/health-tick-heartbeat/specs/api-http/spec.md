## ADDED Requirements

### Requirement: Health Endpoint Reports Server Tick Liveness

The mod MUST record the completion time of every server tick, and `GET /health`
MUST fail when that time is older than a configured threshold. The endpoint MUST
distinguish three states — ticking, stalled, and not yet started — because the
deployment's startup and liveness probes (`startupProbe` 60 × 15 s, `livenessProbe`
4 × 30 s) both read this one endpoint.

The handler MUST answer from its own HTTP thread and MUST NOT execute work on the
server thread. A handler that hops to the server thread would queue behind the
stall it is meant to detect and time out instead of answering, which the probe
would score as a failure of the API rather than of the tick.

The response body MUST keep the existing `status`, `mod` and `bots` fields and MUST
add `tick_age_seconds` (null before the first tick, otherwise the whole-second age
of the last completed tick). A 503 body MUST also carry a `reason` naming the
observed age and the threshold. `/health` MUST remain reachable without an API key:
the kubelet sends none.

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
- GIVEN the mod is loaded and the API server is listening, but no server tick has completed yet
- WHEN `GET /health` is served
- THEN the response status is 200
- AND `status` is `starting`
- AND `tick_age_seconds` is null
- AND the startup probe is not failed by the heartbeat

#### Scenario: A long save blocks the server thread
- GIVEN a world save is running on the server thread and blocks it for less than the threshold (prod's world is 2.6 GiB; the default 120 s is an order of magnitude above an observed save pause)
- WHEN `GET /health` is served during the save
- THEN the response status is 200
- AND the pod is not restarted for it
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

#### Scenario: Probe access needs no API key
- GIVEN API key authentication is enabled for the rest of the API
- WHEN `GET /health` is requested without an `X-Api-Key` header
- THEN the request is answered as described above rather than rejected with 401
