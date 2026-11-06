## MODIFIED Requirements

### Requirement: Thread Safety
Observation endpoints that read world state MUST be wrapped in `server.execute()` + `CompletableFuture.join()` to run on the main server thread.

Every blocking wait for the main server thread MUST be bounded. A handler MUST NOT
wait on that thread indefinitely, and the bound MUST hold even when the server thread
never resumes.

The HTTP API is served from a fixed pool of four threads shared by every registered
route. A wait that never completes holds its pool thread, and four such waits occupy
the whole pool, at which point every other route queues behind them. The requester then
sees no answer at all — not a slow answer, not an error — which is strictly worse than
a failure for a caller that has its own timeout.

The bound MUST end the wait with a specific outcome the client can act on: the
timeout error response defined in *Timeouts MUST be bounded and reported*.
It MUST NOT be expressed as the request eventually being answered, and it MUST NOT be
implemented by silently returning a partial or default body.

The change MUST NOT alter which work runs on the server thread. Work that must happen
on the server thread still happens there; only the caller's willingness to wait for it
without limit is removed.

#### Scenario: Observation endpoint runs on server thread
- GIVEN the agent requests GET /bot/{name}/status
- WHEN the HTTP handler processes the request
- THEN the world state read MUST execute inside server.execute() on the main server thread
- AND the handler MUST block via CompletableFuture.join(), bounded, until the result is available

#### Scenario: A blocked handler releases its pool thread at the bound
- GIVEN fewer than four requests are in flight and the server thread is stalled
- WHEN a handler that hops to the server thread waits past the configured bound
- THEN the handler MUST stop waiting
- AND the pool thread MUST be reused for other requests without waiting for the server thread to resume

#### Scenario: Four blocked handlers no longer hold the pool open-endedly
- GIVEN four handlers are waiting on a stalled server thread
- WHEN the configured bound expires for those waits
- THEN all four pool threads MUST become available again within the bound
- AND the four requests MUST each receive the timeout outcome rather than an open connection

## ADDED Requirements

### Requirement: Timeouts MUST be bounded and reported

A request whose handler must wait for the main server thread MUST get an answer within
a bounded time even when the server thread is stalled. The bound MUST be a single
configured value in one place, not a per-handler literal, so the behaviour can be
described and tested as one thing.

The bound MUST be chosen so a healthy server is never reported as timed out. Normal
handler work completes in milliseconds; the bound exists to distinguish "the server is
stalled" from "the server is slow", not to police ordinary latency.

When the bound expires the client MUST receive a JSON body with an `error` describing
the timeout, returned with HTTP `503`, the status this API already uses for work it
cannot complete. The response MUST NOT be a 200 with a degraded body.

Because the calling agent already treats a timed-out call as a failure, the timeout
MUST be reported as a failure explicitly, so that the alternative — a request that
hangs until the caller's own timeout — is never the observable outcome.

#### Scenario: Timed-out request returns an error, not a hang
- GIVEN the server thread is stalled longer than the configured bound
- WHEN the agent calls an endpoint whose handler must wait for the server thread
- THEN the response MUST arrive within the bound
- AND the body MUST be JSON containing an `error` field naming the timeout
- AND the status MUST NOT be 200

#### Scenario: Healthy server is never reported as timed out
- GIVEN the server thread is processing normally
- WHEN the agent calls any endpoint that hops to the server thread
- THEN the response MUST be the normal success body
- AND no timeout error MUST be produced

#### Scenario: The bound is one configured value
- GIVEN the configured timeout value is changed in its single configuration location
- WHEN the API server starts
- THEN every bounded wait MUST use that value
- AND no handler MUST define its own independent timeout constant
