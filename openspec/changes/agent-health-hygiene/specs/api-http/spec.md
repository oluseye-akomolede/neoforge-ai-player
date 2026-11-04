## MODIFIED Requirements

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

The health request MUST NOT carry the agent's API credential. The probe listener
performs no authentication and documents that it ignores the beacon headers, so
`GET /health` MUST be issued with the presence beacon (`X-Agent-Id`) and MUST NOT
set `X-Api-Key`, from the environment or otherwise. The mod is on the same host
today, which bounds the present impact, but a credential the receiving component
never checks is one that a future change to that listener, a forwarded port, or a
shared network would turn into a live exposure without any record that it is
there.

The startup gate's per-attempt timeout MUST be a named setting with a default of
10 seconds, and every place that describes the retry budget MUST refer to that
setting by the name the code reads. A comment naming a constant that does not
exist is worse than no comment: it sends a reader who tunes the budget looking for
something to change, and anything they define will be ignored because the call
site reads a literal. Changing the default MUST be a deliberate act with its own
scenario, because the retry arithmetic that bounds the startup gate is derived
from it.

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

#### Scenario: The health request carries no API key
- GIVEN `MOD_API_KEY` is set to a live key
- WHEN the agent requests `/health` from the probe port
- THEN the request carries `X-Agent-Id` so the presence beacon keeps working
- AND the request does NOT carry `X-Api-Key`

#### Scenario: Bot calls still authenticate
- GIVEN `MOD_API_KEY` is set to a live key
- WHEN the agent lists bots over the API port
- THEN that request DOES carry `X-Api-Key`, because the API port enforces authentication
- AND dropping the header from the health call MUST NOT drop it from any other call

#### Scenario: The health timeout is a named setting
- GIVEN no explicit health timeout is configured
- WHEN the agent resolves its health request timeout
- THEN it uses a named setting whose default is 10 seconds
- AND the retry-budget comment refers to that setting by the name the code reads

#### Scenario: Tuning the timeout actually takes effect
- GIVEN the health timeout setting is set to 20 seconds
- WHEN the agent issues a health request
- THEN the request is issued with a 20 second timeout
- AND a constant defined but not read cannot satisfy this scenario
