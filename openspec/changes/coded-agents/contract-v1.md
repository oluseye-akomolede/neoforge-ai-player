# Contract v1 — agent script runner

**Status: FROZEN — v1, 2026-11-10.** Both teams have agreed: minecraft by
reviewed PASS, cardgame by `cardgame-lead`'s answers to §10
(`qitem-20261110142143-2fb67b47187ded20`). Version: `1`.

Frozen means the SHARED shape and every per-game value in §7 are agreed and may
not change without a new version of this document. It does **not** freeze the
implementation: `deadline_ms` and `tick_cpu_ms` may be raised later by the game
that owns them, which is a value change in its binding, not a wire change.
`max_sandboxes` is **not** in that set: a game that wants a larger quota raises a
request with the runner's owner (minecraft), and the new quota takes effect only
once the owner has confirmed the instance memory limit still covers it, raising
that limit first if it does not. The limit itself is owned by minecraft as
runner owner and is a value change there, never a game's own decision.

**SHARED** marks the part both games consume and neither may change alone.
**MINECRAFT BINDING** marks this game's choices inside the shared shape; cardgame
has its own binding for the same fields.

This document is the deliverable that `tasks.md` 1b.1 names. The OpenSpec spec
states *what the contract must specify*; this file specifies it.

---

## 0. Scope

One runner service, one HTTP endpoint, both games. Each `tick` call is:
the game sends a snapshot, the runner executes the bot's script for that tick and
returns the actions the script asked for. The runner calls nothing back.

The single design rule everything else follows from: **the game drives the tick,
the runner never initiates.** That removes the runner→game auth leg, the
runner→game network path, and the callback timeout, all of which appear in
earlier drafts of this design and none of which survive here.

---

## 1. Transport and authentication (**SHARED**)

- **Protocol:** HTTP/1.1 + JSON. Content-Type `application/json`.
- **Address:** the runner's ClusterIP Service over cluster DNS,
  `agent-script-runner.agent-script-runner.svc.cluster.local:8080`.
- **Probe port:** `GET /healthz` and `GET /readyz` are served on a **separate
  port, 8081**, not the contract port. This is a stated field, not a deployment
  detail, so both games can probe the same way: the probes must answer when the
  contract port is saturated, which is exactly when a probe is worth having.
- **Auth:** `Authorization: Bearer <token>`. One token **per game**, issued from
  a Kubernetes secret. A request with a missing, malformed, or wrong-game token
  is refused `401` before any parsing. The runner MUST NOT accept an
  unauthenticated request on any path except `GET /healthz` and `GET /readyz`.
- **Identity:** every request body carries `game_id` (string) and
  `contract_version` (integer). The runner refuses `contract_version != 1` with
  `409 contract_version_unsupported`.
- **Bot identity:** a sandbox is keyed by `(game_id, bot_id)`. The same `bot_id`
  in two games is two sandboxes. The runner MUST NOT treat a bare `bot_id` as
  unique.

Decided by cardgame's point 3 and accepted by minecraft.

---

## 2. Endpoints (**SHARED**)

Four endpoints. All are `POST` except health.

| endpoint | purpose |
|---|---|
| `POST /v1/tick` | advance one bot one tick |
| `POST /v1/destroy` | dispose a bot's sandbox |
| `POST /v1/load` | supply source after a `need_source` answer |
| `GET /healthz`, `GET /readyz` | liveness / readiness, unauthenticated |

`script.get` / `script.put` / `script.logs` are **not** runner endpoints. The
game owns script storage (cardgame point 4); the runner is a cache keyed by
`script_revision`. `script.logs` are collected in the tick result (§5) and
stored by the game.

---

### 2.1 `POST /v1/tick`

**Request**

```json
{
  "game_id": "minecraft",
  "contract_version": 1,
  "bot_id": "bot-7f3a",
  "script_revision": "sha256:1f0a…",
  "source": "…",                         // present only when resending after need_source
  "memory": "base64…",                   // or null; the game's stored blob
  "snapshot": { … },                      // §3
  "deadline_ms": 250                      // the game's wall budget for this whole call
}
```

`script_revision` is required. `source` is optional and, when present, populates
the cache for that revision. `memory` is optional.

**Response — success**

```json
{
  "contract_version": 1,
  "status": "ok",
  "script_revision": "sha256:1f0a…",
  "actions": [ { …opaque… } ],
  "cpu_ms": 4.2,
  "wall_ms": 6.1,
  "host_calls": 3,
  "heap_peak_bytes": 1048576,
  "memory_out": "base64…",              // or null when unchanged
  "logs": [ { "level": "info", "line": "…" } ],
  "logs_dropped": 0,
  "cold": false                         // true when this tick recreated the sandbox
}
```

`cold` is `true` when the sandbox was created or recompiled for this tick —
after an idle eviction, or after this game's quota forced the eviction of its
least-recently-ticked sandbox (§7.1). It is the game's signal that a tick paid
compile time; it does not mean the tick failed.

**Response — need source**

```json
{
  "contract_version": 1,
  "status": "need_source",
  "script_revision": "sha256:1f0a…"
}
```

Returned when the runner has no cached source for `script_revision`. The game
resends the same tick with `source` populated. **No action is taken and no tick
is consumed.** This is also the first-tick-after-restart answer.

**Response — error**

```json
{
  "contract_version": 1,
  "status": "error",
  "error_class": "cpu_exceeded",
  "message": "tick exceeded 20 ms CPU",
  "script_revision": "sha256:1f0a…",
  "cpu_ms": 20.0,
  "wall_ms": 21.4,
  "host_calls": 2,
  "heap_peak_bytes": 2097152
}
```

`script_revision` echoes the revision that was executed, so a swap during the
call is observable.

---

### 2.2 `POST /v1/load`

Supplies source out of band, for the game that would rather push than resend a
tick.

```json
{ "game_id": "minecraft", "contract_version": 1,
  "bot_id": "bot-7f3a", "script_revision": "sha256:1f0a…", "source": "…" }
```

Response: `{"contract_version":1,"status":"ok","cached":true}` or
`{"status":"error","error_class":"source_too_large","message":"…"}`.

---

### 2.3 `POST /v1/destroy`

```json
{ "game_id": "minecraft", "contract_version": 1, "bot_id": "bot-7f3a" }
```

Disposes the sandbox and frees its worker slot. Idempotent: destroying an unknown
bot is `{"status":"ok","destroyed":false}`.

---

## 3. Snapshot schema (**SHARED envelope, MINECRAFT payload**)

The envelope is shared. What goes inside `state` is each game's binding; the
runner treats it as opaque, read-only data.

```json
{
  "tick": 18422,                        // monotonically increasing per bot
  "server_ms": 1762777200123,           // game's clock, for drift diagnosis
  "state": { … },                        // game-specific, opaque to the runner
  "events": [ { "type": "…", "data": { … } } ],  // outcomes of earlier actions
  "task": { "goal": "…", "progress": 0.5 } // game-specific, opaque
}
```

**MINECRAFT BINDING** for `state`: health, food, position `{x,y,z,dim}`,
inventory, nearby blocks and nearby mobs, plus the agent's task progress. This
matches the spec's read-only-snapshot requirement; the runner deep-freezes it
before the script sees it, and mutation by the script never reaches the game.

**Events** are how action outcomes arrive: an action accepted in tick *n* is
performed by the game, and its result appears in the `events` array of tick
*n+1*. The runner does not track them.

---

## 4. `api.*` call shapes (**MINECRAFT BINDING**)

All calls are **synchronous inside the tick**. A call either returns a value
(storage calls) or an acceptance (§4.2); it never blocks for the game to answer.
This **replaces** the earlier "host calls are async and awaited" design — see §9
for why, and the spec delta.

### 4.1 The binding

| call | returns | notes |
|---|---|---|
| `api.do(directive, args)` | `{ok:true, seq}` or rejection | queues one action |
| `api.say(text)` | `{ok:true, seq}` or rejection | |
| `api.send(otherBot, msg)` | `{ok:true, seq}` or rejection | |
| `api.remember(blob)` | `{ok:true}` or rejection | ≤16 KB, rides the tick |
| `api.log(level, text)` | `void` | ≤1 KB/line, counted |

`api.do` takes a directive name from the existing agent dispatch set (51 names,
`agent/agent.py`). The runner does **not** validate directive names against the
set — that is the game's job, because the set is the game's — but it does bound
the *shape* (JSON, size, call count).

### 4.2 What a rejected call returns

```js
{ ok: false, reason: "rate_limited" | "host_calls_exceeded" | "bad_shape" | "memory_too_large",
  message: "…" }
```

A rejection is a normal return value, not a throw. The script may inspect it and
continue. Rejections do not end the tick and do not count as script errors.

### 4.3 Host functions absent from the sandbox

`process`, `require`, `import()`, `fetch`, `XMLHttpRequest`, `WebSocket`,
`setTimeout`, `setInterval`, `eval` and `Function` on host strings. Attempting
any of them fails inside the sandbox.

---

## 5. Result fields (**SHARED**)

Named by cardgame, required by both games:

| field | type | meaning |
|---|---|---|
| `cpu_ms` | number | CPU milliseconds spent in the sandbox this tick |
| `wall_ms` | number | wall-clock milliseconds for the whole tick call |
| `host_calls` | integer | accepted `api.*` calls this tick |
| `heap_peak_bytes` | integer | peak QuickJS heap during the tick |
| `memory_out` | string \| null | the memory blob, or null when unchanged |
| `script_revision` | string | the revision actually executed |
| `logs` | array | `{level, line}` entries |
| `logs_dropped` | integer | lines dropped by the rate limit this tick |

minecraft's daily cap is **per bot** and counts **wall-clock time its script is
active** — not `cpu_ms`. The game counts it on its own side: each tick it sends
the runner, it adds that tick's period; a paused or fallen-back bot accrues
nothing. `cpu_ms` stays a reported field for visibility and abuse checks, never
the cap's unit. No wire change and no new field: the game already knows when it
sends a tick, so it needs nothing from the runner to do this counting.

cardgame's cap is its own binding's affair. The runner enforces no daily cap for
either.

---

## 6. Outcome classes and fallback (**SHARED list, MINECRAFT state machine**)

The runner reports a **per-tick outcome**, never a bot state. Fixed class list
(cardgame point 5, accepted):

| class | emitted when |
|---|---|
| `ok` | the tick completed |
| `script_error` | the script threw |
| `cpu_exceeded` | exceeded 20 ms CPU |
| `memory_exceeded` | exceeded 32 MB heap |
| `stack_overflow` | recursion exceeded the 256 KB stack |
| `host_call_timeout` | a host call exceeded 2 s |
| `host_calls_exceeded` | more than 8 host calls in one tick |
| `worker_died` | the worker was lost and replaced |
| `bad_action_shape` | an action was not serialisable |
| `source_too_large` | source over 64 KB at load |

**One failure has no per-tick class, by construction:** if the instance is
OOM-killed, no runner is left to report. The tick fails as a **transport**
error, not an outcome — the game sees a dead endpoint and treats it as a
runner loss, which is a different signal from any class above. A reader must
not read `worker_died` as covering it: that class means one sandbox was lost
and replaced, and says nothing about the instance.

**MINECRAFT BINDING — the state machine the game runs on these:** `active`
(default), `degraded` (a class other than `ok` on fewer than 3 consecutive
ticks), `disabled` (3 consecutive non-`ok` ticks, matching the 3-consecutive-error
limit). On `disabled` the game falls back to the existing planner, which is what
the spec's fallback requirement names. cardgame's `manual` override and daily
cap live in its own binding; the runner knows about neither.

---

## 7. Timeouts and capacity (**SHARED fields**; `deadline_ms` and `tick_cpu_ms` are per-game values, `max_sandboxes` and `idle_evict_minutes` are not)

| field | minecraft | cardgame | meaning |
|---|---|---|---|
| `deadline_ms` | **250** | 250 | the game's wall budget for one tick call |
| `tick_cpu_ms` | 20 | 20 | CPU budget inside the sandbox |
| `max_sandboxes` | **8** | **64** | concurrent sandboxes **per game** (keyed by `game_id`) — see below |
| `idle_evict_minutes` | **10** | 10 | idle sandbox eviction |

**Why minecraft's `deadline_ms` is 250 ms:** the agent's decision cadence is
2.0 s (`agent/config.py:89`, `TICK_DELAY`), so 250 ms leaves 87.5 % of each
interval for the game server's own work and for network slack, while still
bounding a dead runner to one eighth of a decision period.

**Why the per-game quotas differ:** minecraft has a handful of bots, so 8 is
sized for the current fleet with headroom. Cardgame states "hundreds of
characters, mostly idle"; idle eviction means the ceiling they need is the
number *awake at once*, not the number that exist. cardgame confirmed **64**
(2026-11-10): live traffic today is one agent, and 64 covers 2026 load with room
under the 10-minute idle eviction. Both games own their timeouts:
**`deadline_ms` and `tick_cpu_ms` are each game's own to raise, and doing so is a
value change, not a wire change.** `max_sandboxes` is not in that set — a quota
rise is a request to the runner owner, granted only once the instance memory
limit covering it is confirmed or raised (§7.1, and the freeze statement).

### 7.1 Quota is per game, and full means evict — not refuse

`max_sandboxes` is keyed by `game_id`. Each game has its own ceiling, so
**one game cannot lock the other out**; a shared pool was the earlier design and
is withdrawn.

When a game is at its own quota and a new bot ticks, the runner **evicts that
game's least-recently-ticked sandbox** and creates the new one. It does **not**
refuse. This is safe because the game owns the script (§1) and the remember blob
rides the tick: an evicted sandbox loses only compile time, not state.

A tick that had to recreate its sandbox reports `cold: true` in the result, so a
game can see churn rather than discovering it from latency.

**Refusal is the last resort:** `429 sandbox_limit` is returned only when a
single tick cannot fit at all — i.e. the requesting game's own quota is 0, or
one sandbox exceeds the instance's memory limit.

The instance memory limit is a **contract term**, not a deployment detail:
this rule is enforced against it, and a term the contract enforces but does not
state is one an implementer will set from whatever the node happens to have.
It is **4Gi**. At full occupancy the two pools request ~2.3 GB of QuickJS heap
(8 minecraft + 64 cardgame sandboxes x 32 MB), leaving the rest for Node and
the QuickJS runtimes themselves — headroom, not a coincidence.

**Owner: minecraft, as runner owner.** This is why the memory limit and the
quota cannot be raised independently: `max_sandboxes` (8 + 64) is what the 4Gi
is sized against, so a game raising its quota without the limit moving would
size the instance past its own limit and turn a cap into an OOM kill. A quota
rise is therefore a request to the owner, granted only once the limit covering
it is confirmed or raised (see the freeze statement above). The limit is a value
change in minecraft's binding; it is never a calling game's decision.

`idle_evict_minutes` remains: a sandbox untouched for 10 minutes is evicted
regardless of quota, and recompiled on its next tick, also reported as
`cold: true`.

> **Scaling out is not in v1.** A second replica would give two independent
> rule sets and two pools, with bots landing on whichever the Service picks,
> unless the supervisor learns sharding. The values above are chosen so the
> first incident is a visible refusal or a visible `cold: true`, not a silent cap.

---

## 8. Limits (**SHARED**)

| limit | value | unit | enforced by | on breach |
|---|---|---|---|---|
| heap | 32 | MB | QuickJS runtime | `memory_exceeded` |
| CPU per tick | 20 | ms | runner supervisor | `cpu_exceeded` |
| stack | 256 | KB | QuickJS `setMaxStackSize` on the owning runtime | catchable `InternalError`, else `stack_overflow` |
| wall per host call | 2 | s | runner | `host_call_timeout` |
| host calls per tick | 8 | count | runner | 9th call rejected, tick continues |
| source size | 64 | KB | runner at load | `source_too_large` |
| source versions cached | 20 | count | runner (LRU) | oldest evicted |
| `api.remember` blob | 16 | KB | runner | rejection returned to script |
| consecutive errors before fallback | 3 | count | game binding | `disabled` |
| `api.log` line | 1 | KB | runner | truncated |
| `api.log` rate | 100 | lines/min | runner | dropped, `logs_dropped` |
| `api.log` retention | unstated (minecraft) / 7 days (cardgame, their own store) | days | each game, in its own store | the runner stores nothing and forwards lines in the tick result, so it has no retention to breach |

**MINECRAFT BINDING** rates: `api.do` 30/min, `api.say` 30/min, `api.send`
20/min per bot, anchored to the 30 decisions/minute the 2.0 s cadence permits.

**The stack row's enforcement point is load-bearing:** the limit only applies if
every context is created from the runtime that carries it
(`rt.newContext()`, never `mod.newContext()`, which makes its own unlimited
runtime). A test asserts `ctx.runtime === rt` for every sandbox the engine
creates. Above ~2362 frames Node's own stack overflows before QuickJS can raise
its error and the process dies — which is why a worker per bot exists as
defence in depth, not as the primary control.

---

## 9. Decisions taken in this revision (**SHARED**)

1. **Tick ownership is game-driven.** Cardgame cannot run on a runner clock (a
   battle ticks on state change). The game calls `tick`; the runner enforces
   ≤1 tick/s per sandbox as a limit only.
2. **Host calls are synchronous, returning actions.** This replaces the earlier
   async-and-awaited design. Consequences: no runner→game transport, no second
   auth leg, no callback URL, no inbound endpoint on either match server, and one
   network policy direction. **The asyncify variant pin remains** (it is the
   build QuickJS's stack behaviour was measured on and it costs nothing to keep);
   it is no longer *justified* by host-call callbacks.
3. **Script storage is game-side.** The runner caches by revision and answers
   `need_source` on a miss.
4. **The runner owns no state machine.** It reports an outcome class; each game
   maps that to its own states.
5. **Actions are opaque.** Passed through verbatim, never normalised, never
   cleaned. The game validates the exact body.

---

## 10. Settled with cardgame (2026-11-10)

Answers from `cardgame-lead` (`qitem-20261110142143-2fb67b47187ded20`, answering
section 10 as circulated at `c5c9f96`). None of these is a wire change:

- **`api.log` retention:** cardgame keeps 7 days in its own store; minecraft is
  **unstated for v1**. The runner MUST forward log lines in the tick result and
  MUST store none — retention belongs to the game that receives them.
- **NetworkPolicy ingress selector:** namespace `cardgame`, podSelector
  `app=match-server` (their only caller), plus the minecraft agent pod. Nothing
  else.
- **`deadline_ms` 250 and `tick_cpu_ms` 20 for cardgame:** unchanged. Their
  tick runs inside `battle.act`, where 250 ms is well inside what the match
  server already tolerates for a turn.
- **`max_sandboxes`:** cardgame **64**, not the 256 proposed here. Their live
  traffic is one agent; 64 covers 2026 load at full occupancy with room.
- **Instance memory limit: 4Gi.** 72 sandboxes x 32 MB = 2.3 GB of heap, plus
  Node and QuickJS overhead.
- **Their cap** counts wall-clock time from the ticks their match server sends,
  metered on their side. Their driver never ticks an inactive script, so it
  needs no runner field. This is the same shape as minecraft's, reached
  independently, and it is why no field was added for either.

---

## 11. Not in v1

Runner-to-game callbacks; runner-side script storage; a runner-side daily cap;
multi-replica sharding (one runner instance serves both games).
