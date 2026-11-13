# Review — M2-PLAN §8.4.5.1, commit 4a7f369

Reviewer: minecraft-reviewer@minecraft · 11:09Z · rev reviewed: `4a7f369`
(supersedes `456e0ce`; that review was held, not completed, on the lead's instruction)

Verdict: **FINDINGS — two must be fixed before the arm can run; one is a
blocker for the kill step.**

Scope: docs only. Nothing was executed against the Deployment. All live
observations below were read-only in `aibot-agent-test-6f76986444-vqs44`.

---

## The three checks asked for

### (1) Accept-epoch window rule — SOUND

The rule is right and the reasoning is right.

- The listener stamps `accepted <epoch>` **itself**, in its own `sys.stderr`,
  at the point of `accept()` — verified by reading the verbatim listener. It is
  not client-stamped, so the window cannot start before the kernel completes
  the handshake. This was my one worry going in and the text answers it.
- "A fallback line before the first accepted epoch is C2a's window even though
  byte-identical" is correct: `connect timeout:` and `read timeout:` are
  indistinguishable across the arms, and the accept record is the only
  separator. The plan states this in the arm table, the inherited-guard
  sentence, the void sentence, and evidence list items 2 and 4 — consistently
  in all four places. Checked each.
- "A `connect refused:` after the accept epoch voids the arm" is the right
  polarity: it means the listener died mid-arm and later timeouts would be
  measured against nothing.

No defect in the window rule.

### (2) Does "nothing on :9" license the reuse? — YES, but for a reason the text understates

The reuse is sound. The justification in the text is weaker than the fact.

Measured read-only in the pod: `connect_ex(('127.0.0.1',9))` returns **111
(ECONNREFUSED)**; one container; no sidecar; `SCRIPT_RUNNER_URL=http://127.0.0.1:9`.

But "nothing serves :9" is not *why* the reuse is safe. The real runner is
**still fully reachable** from that pod:

    AGENT_SCRIPT_RUNNER_SERVICE_HOST=10.107.105.168
    agent-script-runner.minecraft-test.svc.cluster.local -> 10.107.105.168

Those are Kubernetes service-injection variables, present in every pod in the
namespace. The agent does not use them because `config.py:16` reads
`SCRIPT_RUNNER_URL`, and every consumer of it (`script_tick.py:181`, `:282`) is
downstream of that one variable. So the reuse is licensed by **the client
keying off one env var**, not by the runner being unreachable. I grepped the
whole image for `SCRIPT_RUNNER_URL` — six hits, all in `config.py` and
`script_tick.py`, none reading the injected service vars.

Why this matters for the plan: the middle row of the measurement table says
"There is no sidecar and no proxy" and calls the port "genuinely closed". Both
are true. But a reader could conclude the container is *networked away* from
the runner, which is false. If anyone later "fixes" the URL by pointing it at
the service name, the isolation silently disappears. The plan should say the
isolation is the env value, and that the service-level route exists and is
deliberately unused.

This is a wording correction, not a blocker.

### (3) Kill pattern — BLOCKER: `pgrep` and `pkill` do not exist in the image

The pattern is narrow enough in principle — `python3 -u -c` does not match the
agent (`python3 agent.py`). I checked the live cmdline. But the tools are
absent:

    pgrep   MISSING
    pkill   MISSING
    ps      MISSING
    procps  MISSING

The plan's kill step runs:

    sh -c 'kill $(pgrep -f "python3 -u -c" | head -1)'

On the live pod this prints `sh: 1: pgrep: not found` and the inner rc is 2.
The listener is **never killed**. The arm cannot complete its own teardown.

Worse, the compound command hides it. The plan reads `rc=$?` of the whole
sequence, which is the *second* `kubectl exec` (the bind probe), not the kill.
Measured live: kill fails (`kill_rc=2`) while the port is free, and the plan's
`FINAL rc=0`. So the only signal the plan reads is taken from a command that
cannot see the kill. Today that is not dangerous, because a live listener keeps
the port held, so the probe returns non-zero and the plan correctly stops. But
the honest failure is that **the kill step is unrunnable**, and the rc the plan
documents does not measure it.

I hit the plan's own note from the other side while testing this: a `/proc`
scan for `listener.py` killed my shell, because the scanning command's own
argv contains the string. The plan's explanation for avoiding a source-text
`pkill` is empirically correct — it just applied it to a tool that is not in
the image.

Suggested fix: kill by the PID the listener reports, or have the listener
write its own pid (`sys.stderr.write("pid %d\n" % os.getpid())`) at startup
and `kill` that. Both are pgrep-free and are exactly checkable.

---

## Additional finding — the listener is single-connection

Not one of the three asked checks, but it interacts with the evidence rules, so
it belongs here.

The listener does `c.settimeout(60); time.sleep(60); c.close()` **inside the
accept loop**. That holds the loop for a full minute per connection. Any
connection arriving during the sleep completes the handshake in the kernel
backlog and is never accepted.

Reproduced locally (port moved to an unprivileged one; the logic is
port-independent):

- Five client connections one second apart → **one** `accepted` line.
- Client at T0, client at T+61 s → **two** accepts, epochs 61 s apart.
- Every non-accepted client still saw `READ TIMEOUT after 0.30s` — i.e. it
  looked exactly like C2b evidence while the listener had proved nothing.

For this arm's *window* that is tolerable: one accept is all that is needed to
open it, and the first connection will be recorded. But it is the precise
failure mode the plan's own table warns about ("an un-accepted connection
completes the handshake in the kernel anyway ... the listener has then proved
nothing about *its* accept path"), and the evidence rules cannot tell the two
apart from the client side.

Recommendation: accept in a loop that holds each connection **without blocking
accept** — e.g. append each accepted socket to a list and keep the references
alive rather than sleeping — so every connection is accepted and recorded, and
the accept count is meaningful. If the single-accept behaviour is intended,
state it explicitly, because a reader will otherwise assume one accept means
one connection.

---

## Confirmed good

- Claim (1), image: final stage is `python:3.11-slim` (`agent/Dockerfile:10`),
  `python3` present at `/usr/local/bin/python3`. Note the base is now **Debian
  13 (trixie)** — the tag floats, so "python:3.11-slim" is not a pinned base.
  "No new pull" verified: node reports the layer already present.
- Claim (3)'s correction: `script_client.py:163-164` quoted verbatim matches the
  code. Both `connect timeout:` and `read timeout:` accepted, `connect refused:`
  after the accept voiding the arm — applied in arm table, inherited-guard
  sentence, void paragraph, and evidence items 3-4. Consistent.
- Claim (4): correct and well put. `test_script_client.py:166` asserts only
  `STATE_FALLBACK_TIMEOUT`; the prefix is expectation, not measurement.
- Claim (5) honesty: the step no longer speculates; it points at the live
  measurement. Good.
- The C1 contradiction I filed on the previous revision is fixed correctly:
  absent-file now expects its own `no bindings at ...` line plus zero
  `dispatch:`, with the §8.3.4 warning against gating on the bare tag.

## Additional finding — the agent log carries no timestamp, so the ordering check cannot be made as written

The plan requires, three times, that evidence be "timestamped after the epoch"
of the first accept, and evidence list item 3 says "record the line's own
timestamp so the ordering is checkable and not asserted." Measured on the live
pod: **the agent's log lines have no timestamp.**

    [Scout/script] falling back to planner: runner fallback_connect_refused: ...

That is the line as emitted. There is no field to record, so the check the plan
asks the operator to perform cannot be performed from `kubectl logs` as
written.

It becomes possible with `--timestamps`:

    kubectl -n minecraft-test logs "$POD" -c agent --timestamps

which prefixes RFC3339 UTC:

    2026-11-13T11:08:49.640537422Z [Scout/script] falling back ...

I checked the two clocks agree: the pod's `date -u +%s` matched wall time to
within 3 s, so comparing an RFC3339 log prefix against the listener's
`int(time.time())` epoch is sound. But the plan must say to pass
`--timestamps` — otherwise the operator either records no timestamp (and the
ordering is asserted, not checked, which the plan explicitly forbids) or
compares a wall-clock string against an epoch by eye.

Fix: add `--timestamps` to every `kubectl logs` in the C2b evidence steps, and
state that the listener's epoch and the log prefix are the same clock
(verified: they agree to within 3 s).
