# Run plan — fix minecraft-test/aibot-agent-test crash-loop

Queue: `qitem-20261105001710-4dc79f94bad779e5` · builder · 2026-11-05
Scope: **minecraft-test only.** Prod and the test mod jar are not touched.

## Root cause (verified, not inferred)

`aibot-agent-test` runs `agent:v15-394eb19`. That image is built on commit `394eb19`
(2026-09-30), which **predates** the 2026-10-29 health-split (`7e38039`, `80e9c9e`).
It GETs `/health` on `MOD_API_URL` = port 3100. The test mod jar (`8d1cf64e`, mod-sync'd
11-01) serves `/health` only on the dedicated 3101 listener.

Verified from inside the server pod (not from the lead's note):

| probe | result |
|---|---|
| `GET 127.0.0.1:3100/health` | **404** |
| `GET 127.0.0.1:3101/health` | `{"status":"ok","mod":"aiplayermod","bots":5,"tick_age_seconds":0}` |
| listeners | `:3100` and `:3101` both LISTEN |

So the agent burns its retry attempts against a 404 and exits → 118 restarts.

(The retry count lives in one place, `max_retries` in `agent/agent.py` — 90 on main;
the crash-looping image prints `/60`, an older value. Don't restate the number here.)

## Moving part 1 — image

Build **from current main** `c193f76` (includes merged `agent-health-hygiene`: no
`X-Api-Key` on `/health`, `AIPLAYER_HEALTH_TIMEOUT`), so test proves it before prod.

- Tag: `harbor.arcadia-ecs.local/aiplayermod/agent:2026-11-05-c193f76`
- Built on this VM (`docker build`, `nice -n 19`), `DOCKER_CONFIG=~/.docker-minecraft`.
- Deploy **by digest**, as prod does, not by tag.

Not reusing the existing `2026-11-04-c0a1d62` / `sha256:f1b9f2dc…`: it has the health-split
but predates `agent-health-hygiene` (`d45751d`..`c193f76`). The queue asks for main.

## How the agent finds 3101 — config only, no code change

`agent/config.py` derives the health URL from `MOD_API_URL` by swapping the *port* and
keeping scheme/host (`_health_url`, urlsplit-based). Secret `agent-config` already holds

    MOD_API_URL = http://minecraft-test-server.minecraft-test.svc.cluster.local:3100

so main derives `…svc.cluster.local:3101`. **No env change needed** — the same
`MOD_API_URL` keeps 3100 for every other call (telemetry, bots, commands).

## Moving part 2 — Service port 3101

`minecraft-test-server` currently exposes `25565, 25575, 3100` (type **NodePort**).
Prod (`minecraft/minecraft-server`, ClusterIP) exposes an extra port named
`health-probe` `3101→3101/TCP`; that object is copied verbatim.

Patch by **JSON patch `op: add`** (per queue; no `kubectl apply`). No `nodePort`: the
cluster allocates one, and the agent resolves the port through the ClusterIP DNS name,
not a node IP. **Service type stays NodePort** — not changed.

```json
[{"op":"add","path":"/spec/ports/-","value":{"name":"health-probe","port":3101,"protocol":"TCP","targetPort":3101}}]
```

## Deploy sequence (test namespace only)

1. `docker push` the image; record the registry digest.
2. Service patch (above). Verify 4 ports and `type: NodePort` unchanged.
3. `kubectl -n minecraft-test set image deploy/aibot-agent-test agent=<repo>@sha256:<digest>`
4. Wait for the new pod Ready; confirm it is on the new digest.

## Verification (the DONE bar)

- Pod `aibot-agent-test-*` Ready, **0 new restarts** sustained **15 min**.
- Log shows `Mod API:` (the gate passed) and bots spawning.
- From a throwaway pod: `curl http://minecraft-test-server:3101/health` → `status: ok`
  over the **Service** (proves the svc port, not just the container).
- Restart baseline: current pod 118 restarts; the new ReplicaSet starts at 0.
- Also confirm no `X-Api-Key` is sent to `/health` (hygiene change actually live).

## Rollback (each independent, in this order)

1. **Agent:** `kubectl -n minecraft-test rollout undo deploy/aibot-agent-test`
   (returns to `v15-394eb19`, i.e. the known-bad crash-loop — a true rollback, not a fix).
2. **Service:** remove the added port:
   `kubectl -n minecraft-test patch svc minecraft-test-server --type=json -p '[{"op":"remove","path":"/spec/ports/3"}]'`
   Index 3 is only correct while the port list is unchanged between patch and rollback —
   re-read `/spec/ports` first and confirm `health-probe` is the element being removed.
   Pre-change ports (exact, captured): `minecraft 25565/31907`, `rcon 25575/31167`,
   `aibot-api 3100/31300`, type NodePort.
3. Image stays in Harbor (harmless; can be deleted later).

## Risks

- New pod needs a Harbor pull on a node that may be cache-cold → verify digest on the pod.
- Health gate timeout is 10 s vs mod's 195.6 s cold boot — the agent's retry budget covers it.
- Peak park 01:00–04:00Z: if not finished by ~00:55Z, stop at a safe point.
