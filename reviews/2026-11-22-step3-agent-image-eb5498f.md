# Step 3: agent image → eb5498f on prod — PASS

Rev reviewed: live prod deploy `aibot-agent`, image `@sha256:aea76462…`.
Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Row qitem-20261122115345.
Scope: agent image only. Step 4's manifest is a separate question, answered at the end.

## Verdict

PASS. The running image's own source files are byte-identical to `eb5498f`, proven by
hashing the files inside the live container against the rev. The script and L3 gates are
closed for all five named bots. One chat task ran end-to-end successfully.

## Image identity — proven by content, not by tag

The digest in the spec is `aea76462`; `status.imageID` on the running container is the same
digest, so the running process is that image (not just what the spec asks for).

The digest alone does not say *which rev*. I hashed the two source files inside the live
container and compared to the rev:

| file in `/opt/aibot-agent` | sha256 in live container | sha256 at `eb5498f` |
|---|---|---|
| `planner.py` (39338 B) | `2c9586a05748…` | `2c9586a05748…` |
| `agent.py` (316707 B) | `793518bbb751…` | `793518bbb751…` |

Identical. The image is the `eb5498f` build.

**Instrument note.** I first grepped `agent/agent.py` for the runtime string
`SCRIPT_BOTS names no bot` and found only a comment at the rev, and nearly filed "the
deployed image is not eb5498f". The string lives in **`agent/planner.py`** (`:297`, and
`L3 path off` at `:344`). Both are real code at the rev. The empty result was my grep
aimed at the wrong file — the same species of error as a dead detector.

## Script gate, per bot

5 of each, and distinct names, not five copies of one:

    [Axiom] script mode off: SCRIPT_BOTS names no bot
    [Forge] …  [Mystic] …  [Scout] …  [Tiller] …
    (each also logs: L3 path off: flag unset and this bot is not in SCRIPT_BOTS)

Live deploy env is `OMP/MKL/OPENBLAS_NUM_THREADS` only — no `SCRIPT_BOTS`,
`SCRIPT_RUNNER_URL`, `SCRIPTS_DIR`. Consistent with the log.

## Behaviour: one chat task end-to-end

    10:54:39 [Forge -> Tiller] Task #609 for you: collect 3 dirt (1 steps)
             [Tiller/L1] Directive COMPLETED: {'items_collected': 0, 'blocks_mined': 3}
             [Tiller/planner] Plan COMPLETE! All 1 steps done.
             [Tiller/taskboard] Task #609 completed

Legacy planner path, as the lead said. `items_collected: 0` beside `blocks_mined: 3` is the
known miscount, not new.

## Soak (60 min to 11:53Z), counted at the rev

Traceback 0 · timeout 0 · password-fail 0 · `L3 path on` 0 · `Plan COMPLETE` 1 · plan-failed 0.
Every figure reproduces the lead's report exactly.

## Runner

Running, 0 restarts. **The runner logs nothing at all** — `wc -l` over 98m is 0, not merely
"0 non-health lines". So the lead's "0 non-health lines in 65m" is a statement about an empty
stream and carries no information; it is correctly flagged as unverified in the report.

I measured it instead: `/healthz` 200 `{"ok":true}`, `/readyz` 200 `{"ready":true}`, and the
token gate fires — `POST /v1/scripts` returns **401** with no token and **401** with a bogus
token (112-byte body each).

**Port correction to my step-1 review.** I reported the runner on port `7433`. It is not:
the container declares `8080 (contract)` and `8081 (health)`, and probing 7433 was a
different thing. The step-1 review's statement that unauthenticated calls are refused is
still true, but on 8080, and I have re-driven it here. Also, that image is Node
(`node`, `npm`, no `python3`), so a `python3` client probe fails for instrument reasons.

## `/api/state`

5 bots, each with a `status` object (health 20, food 20, gamemode survival, `alive: true`).

**Observation for step 4, not a step-3 defect:** Mystic and Scout report *identical*
positions (`-92.2, 127.9, -191.2`), and all five bots were stationary across three samples
40s apart. I checked this was not a frozen snapshot: the server's tick counter advances
(97400 → 97800) and the agent reads a live server, so this is idle bots, not a stale cache.
Step 3 does not touch placement. But **Mystic is the step-4 script bot**, and a bot that
spawns coincident with another is worth knowing about before its behaviour is judged.

**Another instrument note:** my first position probe read `bots[k]['position']` and got
`None`; the field is nested at `bots[k]['status']['position']`. Third probe this session
whose "no data" was my addressing the wrong path.

## Rollback

Pre-state image `b2b274bf` recorded in the row. Note the live deploy's
`last-applied-configuration` annotation still names an older image (`e80c2e8b`) — that is a
record, not the live spec; the live spec and `imageID` are `aea76462`.

## CHECK ALSO: is there a reviewed step-4 manifest?

**No.** The builder must write it.

- Live `aibot-agent` env: three thread vars only. No `SCRIPT_BOTS`, `SCRIPT_RUNNER_URL`,
  `SCRIPTS_DIR`, `RUNNER_TOKEN`.
- `deploy/agent-deployment.yaml` at HEAD: `envFrom: secretRef` plus one volume mount for
  `/opt/aibot-agent/data`. No script ConfigMap mount, no SCRIPT_ env. Last touched
  `4d11516` (April).
- `deploy/agent-scripts.yaml` exists but is a **ConfigMap** holding `scout.js`, and its own
  header says the pod does not mount it yet and that mounting "is part of the step-4 TEST
  run plan".
- A `agent-script-runner-token` Secret exists in the namespace, so the credential half of
  step 4 is provisioned; the Deployment side is not.

So step 4 needs a reviewed manifest adding `SCRIPT_BOTS=Mystic`, `SCRIPT_RUNNER_URL`,
`SCRIPTS_DIR`, and `RUNNER_TOKEN` via `secretKeyRef`, plus the script volume mount. None of
those exist at a reviewed sha today.

## Not established

- Idle server, no players (lead's LIMIT stands). This proves a clean start and a quiet run,
  not behaviour under load.
- Step 3 put the *capability* on prod but left every script gate closed by construction. No
  script has ever run in prod — step 4 is the first exercise, not a re-verification.
- The runner's quiet log is unmeasured by design; I verified its endpoints and refusal, not
  its behaviour when a real call arrives.
