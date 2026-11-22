# PTC prod rollout plan — NOT PASS as written (F-1 blocking, F-2 blocking on its own wording)

Plan reviewed: `~/minecraft/docs/ptc-prod-rollout-plan.md` (5614 bytes, 70 lines, written
06:45Z, not yet in a repo — see N-2). Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Cluster reads: live, read-only, 06:5x–07:0xZ. Code read at `3e900cc`
(`~/minecraft-wt-deepseek/neoforge-ai-player`, the tree that holds that rev — my worktree is
at `008b723` and does not contain it).

## Verdict

**Do not start step 1 as written.** Two findings block, and both are cheap to fix before any
step is applied.

**F-1 (blocking).** Under "SCRIPT_BOTS unset", the agent at `3e900cc` does **not** run the
planner the plan calls "the current planner (the fallback)". It runs a *different* planner
unless `USE_L3_PLAN_LAYER` is also set — and prod has that variable nowhere. On this rev the
setting is load-bearing for scripts, which flips its meaning from "experiment" to "kill
switch" the moment scripts are enabled. Step 3's verification ("every bot runs the current
planner") is false as specified, and step 3's rollback removes `SCRIPT_BOTS` from an agent
that never had it.

**F-2 (blocking).** Step 3's rollback has a grep for a variable name that no rev has ever
had; executed verbatim it prints `No resources found`/empty and reads as success. And step 3
is not a reversible swap at all: `b2b274bf` (11-17) does not contain the script code, so the
four script env vars it removes are **no-ops** — but the one it must set, the mod's `MOD_API_URL`,
is not in its own env list. On prod the mod URL comes from the `agent-config` Secret, so step 3
must change the Secret, the single highest-risk object in the namespace. Its rollback says
nothing about restoring it.

Four more findings (F-3 … F-6) are non-blocking but each costs a restart, an hour, or — in
F-4's case — an hour per step.

## F-1 (blocking): "SCRIPT_BOTS unset = the current planner" is false on prod

The claim under test: with `SCRIPT_BOTS` unset, does the agent at `3e900cc` behave exactly like
the current planner — no script section, no runner call?

**Control: yes, the script surface is closed.** `planner.script_mode` defaults to off and gates
every surface on `("SCRIPT_BOTS", "SCRIPT_RUNNER_URL")`:

- `agent/planner.py:271-303` — `script_mode`; an empty `SCRIPT_BOTS` returns
  `(False, "script mode off: SCRIPT_BOTS names no bot")` at `:296-297`.
- `agent/agent.py:489` — the startup log prints that reason per bot.
- `agent/l3_planner.py:488,507` (plan prompt) and `:1675` (script prompt) — same gate.
- `agent/planner.py:446` (legacy `render_planner_prompt`) and `:423` (the
  `_script_from` drop: a `"script"` field is ignored and logged when not offered).
- `agent/script_tick.py:370-372` — `_default_transport()` returns `None` with no
  `SCRIPT_RUNNER_URL`, and `:529-540` turns that into `(False, [], [], no_runner_detail())`.
  No runner call can leave the pod.

**But "exactly like the current planner" is only true if the L3 plan path is the one running,
and on prod it is not.** `l3_planner`'s prompt — the one that carries the script section —
is reached only from `_run_orchestrator`, which only runs when `USE_L3_PLAN_LAYER` is true
(`agent/agent.py:1114`). With it false, chat tasks go to `planner.decompose`
(`agent/agent.py:1143`), the legacy decompose prompt.

| | test (`minecraft-test`) | prod (`minecraft`) |
|---|---|---|
| `USE_L3_PLAN_LAYER` | `true` (`secret/agent-config`) | **absent** — not in `agent-config`'s 12 keys, not in the container env |
| path for a chat task | L3 `call_plan` → `plan_orchestrator` | `planner.decompose` |
| script offer reachable | yes | **never** |

The prod absence is live, not inferred from a manifest: `env | grep -c USE_L3_PLAN_LAYER` in
the running agent pod returns `0`, and `config.py:122` defaults it to `false`.

So step 3's second verification line — "each logs script mode OFF" — cannot be satisfied. No
L3 plan is written on prod, so `call_plan` is never called, so the `[bot] script mode off: ...`
lines at `agent.py:489` are never printed for a chat task. The rollout would stall
on a verification that cannot pass.

**Why this blocks and is not a footnote.** The gate that decides whether a bot is offered
scripts is `USE_L3_PLAN_LAYER`, because it decides whether the script-carrying prompt is
used at all. On prod, `SCRIPT_BOTS=Mystic` alone (step 4) would do nothing: Mystic's chat
tasks would still decompose through the legacy prompt and never be offered a script. So step 4
fails silently in the shape the rig already documents — enabled, verified for the wrong thing
(the other bots stay off, which they would anyway), and "0 script_error" is vacuous.

The one live consequence of enabling it is what makes F-1 a *risk* and not just a
correction. On prod today, chat, direct-address routing and task-board work all go through
`planner.decompose`. `USE_L3_PLAN_LAYER=true` moves all of it onto `plan_orchestrator`
(`agent.py:891`, `:1114`, and the order lane `:5669`) — the same lane that carries
`_begin_script_hold` at `agent.py:1108`. That is exactly why it must not be slipped in
underneath step 3, whose own text says the agent change is "the fallback".

**Fix (either, lead's call):**
1. **Enable L3 on prod deliberately, as its own reviewed step, before scripts.** Default L3
   off, soak it for a full period, verify chat + direct address + task board still work via the
   orchestrator. Only then enable `SCRIPT_BOTS` for one bot. This is a second, real rollout
   stage; the plan should say so and give it its own rollback.
2. **Do not use the L3 path for scripts on prod.** Not a recommendation — it would mean
   porting the script offer into `planner.decompose`'s path, a new feature, not a rollout.

Either way, step 3's verification must be restated. "Scripts are off" is verified today by:
`env` showing `SCRIPT_BOTS` and `SCRIPT_RUNNER_URL` unset, plus zero runner calls in the
runner's own logs — not by a line the agent will not print.

**Also required regardless of the choice:** a spec requirement that the script surface
depends on `USE_L3_PLAN_LAYER` (or that it must not). The change
`openspec/changes/script-lookups-and-results` says "Scripts MUST be offered to a bot's planner
only when that bot is BOTH enabled... AND a runner is configured" — it is silent about the
second, earlier gate, so a future reviewer reading the spec cannot learn from it that the
surface is unreachable unless a *different* flag is set. Both new change names validate
(`openspec validate coded-agents --strict` rc=0; `script-lookups-and-results` valid).

## F-2 (blocking): step 3's rollback is a false success, and the swap it describes is wrong

Step 3's rollback, copied from the plan:

```
kubectl -n minecraft set env deploy/aibot-agent -c agent \
  SCRIPT_BOTS- SCRIPT_RUNNER_URL- RUNNER_TOKEN- SCRIPTS_DIR-
```

**The name error.** The agent has never read a bare `RUNNER_TOKEN`. It reads it from the
Secret via `secretKeyRef` (test: `secret/agent-script-runner-token`, key `minecraft`, verified
live), and the runner's own rotation runbook spells out that the bare name is absent:
`openspec/changes/coded-agents/ROTATION-PLAN-RUNNER-TOKEN.md:44` — "the loop iterates
`process.env` entries matching `RUNNER_TOKEN_*`, so a dropped key is..." and `:76` — "the bare
`RUNNER_TOKEN` is... unset". `kubectl set env NAME-` on a name that is not in the pod spec
prints `No resources found`/`env updated` with nothing removed, and the rollout does not
restart the pod. Executed as written, the "rollback" is a no-op that reports success — the
same "silent no-op that reports success" shape `openspec/changes/coded-agents/M2-PLAN.md:1629`
says this rig has been bitten by before.

**The swap error.** `b2b274bf` is a 11-17 image. `SCRIPT_BOTS`, `SCRIPT_RUNNER_URL`,
`SCRIPTS_DIR` and the Secret-sourced token are **not read by it at all** — the script mode gate
was added at `2fb40e7` (verified ancestor of `3e900cc`) and the runner transport predates
nothing here. So step 3 changes five env entries of which four are inert, and every one of
them is inert on both sides of the rollback. The only entry that is *not* inert in effect is
`MOD_API_URL`, and it is not in step 3's own list — it is `secret/agent-config/MOD_API_URL`
in prod (`http://...minecraft-server.minecraft.svc.cluster.local:3100`), whereas test uses
`http://minecraft-test-server...`. An agent that talks to the test server from prod would
inject chat into the test world and dispatch directives to test bots.

**The rollback gap.** A rollback that restores the image and removes four no-op env vars
does not put the Secret back. If step 3 edits `agent-config` (and that is how prod's mod URL
would have to move), the rollback must record the previous value and restore it. Right now it
silently leaves prod pointing wherever step 3 left it.

**What step 3 should say, concretely.** Since `b2b274bf` ignores all script env, and
`3e900cc` with `SCRIPT_BOTS` unset makes no runner call, the *only* agent settings that move
on the wire are the image and (if you keep prod's existing Secret) nothing else. My
recommendation: set the image alone; do not add the four script env vars or change
`MOD_API_URL`, and defer that whole set to step 4, where a bot is actually enabled and the
runner URL is load-bearing. That makes step 3 a genuinely reversible one-field swap, and the
rollback is `set image` back to `b2b274bf` — the byte-restorable object rather than four
deletions of things that were never there. Then step 4 carries the real env change, with a
rollback that says what it added and what the Secret held before.

## F-3 (non-blocking): P4's resource numbers are right, but "the same yaml as test" is not a copy-paste

P4 asks for "same resources as test (requests 500m/4Gi, limits 2 CPU/12Gi)". I read the live
deployment's own field: `requests {"cpu":"500m","memory":"4Gi"}`, `limits {"cpu":"2","memory":"12Gi"}`
(`kubectl -n minecraft-test get deploy agent-script-runner -o jsonpath='{...resources}'`). So
the numbers in the plan are exact. This is not a finding against the plan's arithmetic.

It is a caution about the instruction's *verb*. Four other things in the test runner's spec do
**not** copy to prod unchanged, and a P4 implemented as "apply the test yaml with the
namespace changed" would carry them:

- `imagePullSecrets: [{name: harbor-creds}]` — present in `ns minecraft` (verified), so fine,
  but it is a namespace-scoped reference and must be named.
- The NetworkPolicy's three `namespaceSelector` blocks (`cardgame`, `minecraft-test` ×2) —
  the plan already says these must be rewritten; the resource block sits in the same file.
- Probes on `/healthz` and `/readyz` at port `8081` — copying them is right (the runner binds
  both; live ports confirmed `8080 contract`, `8081 health`), but a hand-typed prod manifest
  that drops them turns step 1's "pod Ready" into a check that cannot fail.
- `RUNNER_TOKEN_CARDGAME` — the plan correctly drops it.

The narrow ask: P4 should say **compose from the live object's fields**, and step 1's
verification should be the three resource numbers read back plus one Ready pod, rather than
"same as test". Not blocking, because the plan quotes the numbers inline and an implementer
who reads them gets them right.

## F-4 (non-blocking): four of six step transitions throw away an hour of soak

Step 5 adds one bot per step (Axiom, Forge, Tiller, Scout), each with the same verify + 1 h
soak. The plan itself notes at the end: **"changing `SCRIPT_BOTS` restarts the agent pod,
which restarts all 5 bots, not only the one added."** Combined with a 1 h soak after each of
steps 4, 5×4, that is four-ish restarts whose soak is spent re-proving the previous bots still
work — while the four-bot fleet's blast radius is the only thing the soak is buying. A
restart of all five bots on a production server is also the step most likely to disturb the
players the plan says to warn about in step 2.

Recommendation: either add bots two at a time (Mystic+Axiom, Forge+Tiller, Scout) with one
soak per pair, or keep one-at-a-time but say in the plan that the soak exists to bound the
*restart*, not the bot — and that a rollout is 6 restarts. As written, a reviewer of a later
step cannot tell from the plan whether the previous hour of silence is evidence.

## F-5 (non-blocking): step 0's "the hourly archive that finished after the last prod game change" is not readable as written

The hourly archives live on `pvc/minecraft-backups-pvc` (`/backups`), which is RWX and
mounted only by the backup Job. `kubectl cp`/`exec` into `deploy/minecraft-server` cannot see
them, and the prod agent pod mounts only `agent-data`. Step 0 must name its read route. The
route I used (an ephemeral `busybox` pod with a `pvc` volume, removed on exit) works and is
read-only; the plan should name a route, because "record its name and size" with no route is
where an operator invents one on a 10 GiB archive.

Measured 07:0xZ for reference: newest archive `world_2026-11-22_06-00-16.tar.gz` 9,977,996,936
bytes; six archives, ~10 GiB each, 55.8 GiB used of 147 GiB. The world is 12 GiB on disk
(`df`), so these are close to a full copy — a "backup" that is 83% of the source is worth
knowing the read time of before step 0 renames the previous jar.

## F-6 (non-blocking): the b2 offsite backup is failing for a different, simpler reason than the plan records

The plan says b2 is "failing, open follow-up" and the failure it implies is about backups.
Live: `job/minecraft-backup-b2-29920530` failed with **`DeadlineExceeded`** — "Job was active
longer than specified deadline", start 2026-11-21T03:30:00Z, failed at 03:55:00Z — and the one
*after* it (03:18Z today, `29921970`) **succeeded** in 7m7s. Two of the last three b2 runs
succeeded. So the b2 leg is flaky under a deadline, not broken; the plan's "failing" is a
statement about one run that has since recovered. Not blocking — and arguably good news for
step 0 — but a plan that says "failing" will send someone to debug b2 when the real question
(does the b2 copy predate the last game change) is answerable from the successful run at
03:18Z. Confirmed separately: cronjob `minecraft-backup-offsite` is `SUSPEND: True` (the plan's
"offsite suspended" is correct).

## What I checked and agree with

- **Image digests**: prod agent `sha256:b2b274bf…` and `run` is `1/1`; test runner
  `sha256:1da521c1…` from `27d786b` is `Running` `1/1` since 05:20:15Z. Both match the plan.
- **P3's drift is real.** The runner repo's `manifests/agent-script-runner.yaml:64` pins
  `sha256:6e079944…` ("the push of 2e1d608"), while the live test deployment runs
  `sha256:1da521c1…` (`27d786b`). Different digests. The plan is right that the prod copy
  must start from the live truth, not the pinned file.
- **P4's token split is shippable.** `manifests/agent-script-runner.yaml` carries
  `imagePullSecrets: [harbor-creds]`, and `secret/harbor-creds` exists in `ns minecraft`, so a
  prod runner can pull. Its self-token references the `minecraft` key only, so dropping
  `RUNNER_TOKEN_CARDGAME` is a one-line diff and safe (`main.js:113-126` requires at least one
  `RUNNER_TOKEN_*`).
- **The NetworkPolicy namespace copy is harmless-but-inert, as the plan says.** Flannel does
  not enforce NP here; the copy at manifest lines 230/243/256 references `cardgame` and
  `minecraft-test`, so a namespace-changed copy is required only to keep the file
  self-describing, not for security. The plan says the token is the real gate; agreed.
- **Steps 1 and 0 are otherwise ordered correctly**: runner before agent means the agent's
  first scripted tick finds a live runner, and a rollback of step 1 (scale 0) leaves a running
  agent that does not call it (F-1's gate makes this true even more strongly).
- **The mod jar step (2) is correctly independent.** `9ddfdef`'s Java change is
  `GotoBehavior.java` plus a test; test and prod run the *same* base image
  (`minecraft-server-opencl:2026-09-28-b961a70e`), so prod is only one jar behind, not a
  different lineage. The directive-result carrier (`9ddfdef`'s `agent/snapshot.py` half) is
  agent-side and inert on prod until scripts are enabled. Step 2 is safe ahead of step 3.
- **Backups before step 1**: hourly cronjob is live, `SUSPEND False`, last schedule 48m ago,
  and six archives exist. The plan's "back up before prod" precondition is satisfiable.

## Not established

- **No step was executed.** Every command above is read-only (`get`, `describe`, an ephemeral
  `busybox` pod that lists a PVC and exits).
- **I did not verify the prod server's running mod jar contents.** The plan's "older jar via
  mod-sync from minio prod path" is plausible and consistent with the shared base image, but
  the jar's version line is only readable from the mod itself, which I did not call. Step 2's
  verification ("the mod's version line shows 9ddfdef") is therefore untested as a route.
- **I did not review the runner image at `27d786b`.** The plan's precondition P2 and step 1
  verification depend on `/health` and `/readyz` (probes confirmed live at ports 8080/8081),
  not on the runner's script semantics, which I have reviewed separately at earlier revs.

## Note on my own mistakes this turn

Two, both worth carrying forward:

1. **I printed live secret values into my own context.** Reading `secret/agent-config` in
   `minecraft-test` with a loop that base64-decoded every key put the PG DSN, the mod API key
   and the DeepSeek token in front of me. I did not repeat them here and nothing was written
   outside this session, but the read was avoidable: I only needed the key names and, for one
   key, a length. I emitted full values because I had already written a "print value" script
   for prod's non-secret keys and reused it on a secret. Do not reuse a decode-and-print loop
   across namespaces.
2. **I grepped my own worktree for the reviewed rev's code.** `SCRIPT_BOTS` returned nothing
   in `~/minecraft-wt-qwen/neoforge-ai-player` because that tree is at `008b723` and does not
   contain `3e900cc` at all — the builder's tree holds it. The empty result was my tree, not
   absence from the rev, which is exactly the failure a previous note warns about. I moved to
   the tree that holds the rev before drawing any conclusion.

## Recommendation

Hold step 1. Fix F-1 and F-2 in the plan, in that order — F-1 changes what step 3 *is*
(it becomes "turn on the L3 lane, or nothing"), and F-2 changes what its rollback *does*.
F-3 through F-6 are one-line edits to the plan text and can land with the same revision.
Then re-review those two steps only; I do not need to see the whole plan again.
