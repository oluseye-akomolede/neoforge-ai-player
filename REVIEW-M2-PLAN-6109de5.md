# Review — M2-PLAN C2b listener, commit 6109de5

Reviewer: minecraft-reviewer@minecraft · 11:20Z · rev reviewed: `6109de5`
(revises `4a7f369`, whose four findings this addresses)

Verdict: **PASS.** All four findings are fixed, and the one thing the builder
asked me to rule on — the 32-socket cap — is safe, verified with the real
client. Two notes below are non-blocking.

Scope: docs only. I executed nothing against the Deployment's workloads. The
live checks below were read-only in `aibot-agent-test-6f76986444-vqs44`.

---

## The four findings, each re-checked

### (3) Blocker — kill cannot run: FIXED, and verified end-to-end

`pgrep`, `pkill`, `ps`, `procps` are absent from this image; `kill` is present
(shell builtin). The plan now has the listener write `pid <n>` at startup and
kills that pid. I ran the documented sequence verbatim inside the real pod:

    pid 353
    PID=353
    kill_rc=0 probe_rc=0

So the pid line prints, parses with `sed -n "s/^pid //p"`, the kill succeeds,
and the port is free afterwards. The split `kill_rc` / `probe_rc` is exactly
what I asked for: the earlier compound `$?` was the bind probe's status and
could not see `kill_rc=2`. Reporting both, and judging both, is correct.

Cleanup note: the test left no listener and no file behind (verified).

### (2) The listener is no longer single-connection: FIXED

`time.sleep(60)` is out of the accept loop; each accepted socket is appended to
`held` and the loop continues. I reproduced the builder's result with the real
`requests` client, not a bare socket: eight clients one second apart produced
**eight** `accepted` lines (the old listener gave one). The accept count is now
meaningful.

### (4) Isolation paragraph: FIXED and correct

`:1989-1999` now states plainly that `AGENT_SCRIPT_RUNNER_SERVICE_HOST` is
injected and the service DNS resolves, and that the arms are isolated because
`config.py:16` reads `SCRIPT_RUNNER_URL` and every consumer is downstream — not
because the runner is unreachable. It explicitly says not to read the
`ConnectionRefused` as evidence of isolation. That is exactly the correction I
filed; the retained "genuinely closed port" sentence is now correctly scoped to
the port. Good.

### (5) Timestamps: FIXED

Every evidence `kubectl logs` carries `--timestamps`, with a `--since-time`
example. That makes the "timestamped after the epoch" check performable, which
it was not before (the agent's log lines carry no timestamp of their own).

---

## The cap — RULED SAFE (the builder asked me to say so or ask for removal)

I tested it the way the builder said he could not: with `requests`, the real
client, rather than raw sockets.

- **Capped close does not become `connect refused`.** Eight `requests.post`
  calls through a listener capped at two held sockets: all eight raised
  `ReadTimeout` and **none** raised `ConnectionError`. So a capped close cannot
  manufacture a `connect refused:` and void the arm.
- **The "hold > 300 ms" table requirement is met in effect.** Sockets are in
  fact closed immediately when the cap trips (measured: `accepted` and `closed`
  in the same second). Every client still ran the full `0.303 s` to
  `ReadTimeout` — the client is blocked in `recv`, so the peer's FIN is not
  observed before the deadline and no early EOF appears.
- **The client's own bound is far shorter than the tick.** `SCRIPT_TIMEOUT = 0.3`
  (`script_client.py:109`) against a ~2.3 s tick, so by the time the cap could
  close the oldest socket, the request that held it had already given up. The
  cap cannot strand an in-flight request.

**Ruling: keep the cap at 32.** It bounds an otherwise unbounded list against a
512Mi limit, and it does not contaminate the evidence. The builder's honesty in
flagging that his measurement was raw-socket-only was right — the gap was real,
and it comes out in favour of the cap.

---

## Non-blocking notes

1. **`accepted` epochs are second-resolution and can repeat.** In both my runs
   several accepts shared a second. The window rule ("fallback line before the
   first accepted epoch") is unaffected, but a reader comparing a
   `--timestamps` RFC3339 line against `int(time.time())` is comparing a
   sub-second prefix against a whole second. The plan should say to compare at
   one-second granularity and treat a log line within the first accepted second
   as ambiguous, rather than implying a strict ordering at that resolution.

2. **The cap's residual risk note is correctly worded**, but it should name the
   measurement I added (real `requests`, not raw sockets), so a future reader
   knows the gap has been closed empirically rather than only reasoned about.

Neither note blocks the arm.
