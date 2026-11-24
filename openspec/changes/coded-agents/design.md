# Design — the agent-to-mod report channel

**Scope: design only. No code in this change.** This document settles *how* two
facts the spec already obliges the bot interface to show get from the agent,
which holds them, to the mod, which serves the interface. It adds one
requirement to `specs/bot-coded-agents/spec.md` and the tasks it implies to
`tasks.md`.

## The gap

Two obligations are already stated and neither is satisfiable today:

| Obligation | Where it is stated | Where the value lives |
|---|---|---|
| a runner fallback is reported, not inferred from a motionless bot | "An Unreachable Runner Is Detected And Falls Back" (scenario *A bot does not stall silently when the runner is gone*) | `agent/script_client.py:127-135` — `STATE_FALLBACK_REFUSED` / `STATE_FALLBACK_TIMEOUT` / `STATE_FALLBACK_ERROR`, held in the agent's per-tick result |
| metered usage is exposed where the bot interface can read it | "Code Time Is Metered Per Bot" | `agent/code_time.py` — `CodeTimeMeter.usage_hours()`, one instance per bot |

The bot interface is served by the mod. `HttpApiServer.handleBots` answers
`GET /bots` from `BotPlayer.getCachedStatus()` (`HttpApiServer.java:299`) and
`GET /bot/{name}/status` from the same cache (`:346`); that cache is refreshed
from the mod's own tick every 40 ticks (`BotPlayer.java:532`, `:616`). Nothing
in it comes from the agent. The agent and the mod are separate pods with no
shared volume, and today the agent only ever *reads* the mod's API — it has no
write route into it.

So the two facts are held by a process the interface cannot see.

## Options considered

### (1) An authenticated POST route on the mod's existing HTTP API — CHOSEN

The agent already speaks this API in the only direction that exists today
(`agent/api.py` `_headers()` sends `X-Api-Key` and `X-Agent-Id` on every call).
A new route, `POST /bot/{name}/script_report`, accepts one bot's reported state
from the agent, checks it with the mod's existing `checkAuth` (`HttpApiServer.java:141`,
the existing `MOD_API_KEY` auth — named here only, never read or printed), and
stores it on that bot's `BotPlayer`.

**Why:** it is the one channel that already exists in the required direction,
with authentication already built, and it needs no new infrastructure. The
bearer is already the agent's identity: `checkAuth` also treats `X-Agent-Id` as
the presence beacon (`:145`), so the same request that carries a report also
proves the agent is alive — the freshness signal in the spec costs nothing
extra.

**Cost:** the mod gains a mutating route that the agent can call on every bot.
That widens what a leaked `MOD_API_KEY` can do from "drive bots" to "also display
a false script state". Accepted: driving a bot is already a superset of lying
about it, so the route adds no capability the key did not already confer. The
route is scoped to display state only and cannot change a script binding, a
script's source, or a bot's behaviour.

### (2) The agent writes a ConfigMap the mod watches — REJECTED

The script *bindings* already travel this way (the `scripts` ConfigMap,
`bindings.json`, read by the agent), so a reporting ConfigMap would reuse a
proven mechanism.

**Rejected because:** it inverts the direction of a mechanism built to be read
by the agent, and it needs write access to the cluster from the agent pod, which
does not have it today — a new RBAC binding is the kind of shared-infrastructure
change this task excludes. It also gives every bot's usage a second durable home
whose lifetime and GC nobody would own.

### (3) The agent's dashboard re-serves the mod's status with the agent's fields merged — REJECTED

The agent already runs a dashboard (`agent/dashboard/server.py`); it could
fetch mod state and merge in what it holds.

**Rejected because:** the spec's scenarios say the value is shown *in the bot
interface*, and the bot interface is the mod's. A second surface that shows a
different, richer status would mean two answers to "what is this bot doing",
and the one a player reaches from the game is the poorer one. It also puts the
agent's dashboard in the read path of state the mod already serves, for no gain.

### (4) RCON / command channel — NOT CONSIDERED

Out of scope: RCON carries commands, not structured display state, and using it
for reporting would be a new use of an interface with its own rotation plan.

## The payload

One request per bot per reporting interval, body:

```json
{
  "script_state": "fallback_timeout",
  "code_hours": 1.502777,
  "previous_code_hours": 1.502111,
  "ticks": 2705,
  "observed_at": "2026-11-23T10:20:04Z",
  "revision": "sha256:0d5c…"
}
```

| Field | Size | Purpose |
|---|---|---|
| `script_state` | ≤ 24 bytes | the four-value vocabulary; absent when the bot has no script |
| `code_hours` | ≤ 20 bytes | `usage_hours()` as sent; the mod shows it, it does not re-derive it. Its window (day, process lifetime) is **not** asserted by this channel -- 5.4's |
| `previous_code_hours` | ≤ 20 bytes | the figure this one replaces. **Absent unless this report's figure is LOWER than the last one sent.** So a fall is readable from one report without the mod keeping a history -- still latest-only storage -- and it cannot be misread as describing a rise, which is what a day rollover may produce once 5.4 settles one |
| `ticks` | ≤ 10 bytes | the counter's unit, so a reader can tell "zero usage" from "never ticked" **within one process**; it restarts with the process, so hours > 0 with ticks 0 is normal after a restart (see the silence bullet below) |
| `observed_at` | 20 bytes | the agent's clock at send, so the mod can date staleness from the sender's own view and detect clock skew |
| `revision` | ≤ 72 bytes | the script revision in effect, so the state is never attributed to a revision that did not produce it |

Body size: **about 0.25 KB, a soft target and not a guarantee.** Nothing
downstream may depend on a bound tighter than "well under a kilobyte". Earlier
drafts of this line quoted exact byte counts; those were not reproducible,
because the figure moves with unstated serialisation choices (compact vs
spaced, `ensure_ascii`, whether the printed `…` in the example revision is
one character or three, and whether padding fields are filled with digits or
letters). To keep this honest the only figures given here are order-of-magnitude
and the real figure is to be measured by a test next to the sender when 5.6 is
implemented, on a named payload with the revision length pinned. It is not a log and is not retained: the mod
keeps the latest report per bot and nothing older. That is what the spec's
"a repeat report does not accumulate" scenario requires, and it is why this does
not need storage.

**No secret is carried in the body.** Authentication is the existing header; the
payload holds only what a player is meant to see.

## Cadence, failure and staleness

- **Sent** once per bot every `REPORT_INTERVAL` = 15 s (7.5 tick periods), and
  immediately when a bot's `script_state` changes, so a fallback is visible
  within one tick period rather than up to 15 s later. A bot with no script
  sends nothing.
- **Bounded:** 15 s across the fleet is at most one request per bot per
  interval, independent of the tick rate, so the count does not grow with fleet
  size or cadence. A failed send is not retried inside the interval; the next
  interval re-sends the current values anyway. This is the same "does not grow
  with fleet size" property the instance-loss scenario asks of runner probes.
- **Mod down:** sends fail and are dropped. When the mod returns, the next
  interval re-sends the current values, so the mod recovers without a resync
  protocol. The agent MUST NOT queue reports — a backlog replayed on recovery
  would show old values as new.
- **Agent down or restarted:** the mod stops receiving. After
  `STALE_AFTER` = 3 × `REPORT_INTERVAL` (45 s, three missed intervals) the mod
  marks that bot's reported values **stale** and the status shows them as such,
  never as current. This is deliberately longer than the interval (so one
  dropped request is not a lie) and shorter than any human timescale for acting
  on it.
- **A usage drop:** the report carries `previous_code_hours`, so a fall is
  readable from the new report alone and the mod still keeps only the latest.
  The channel does not say what a fall MEANS. A restart, a day rollover and a
  replaced meter all produce one, and which of those this is, and whether the
  figure should persist at all, is tasks 5.4's (day boundary and restart
  persistence), not this channel's. What it must not do is show a figure
  falling from 1.4 h to 0.0 h unlabelled.
- **The figure's window:** `usage_hours()` is a process-lifetime monotonic total
  today (`code_time.py:84`/`:101`/`:113` -- starts at `0.0`, only `+=`). There
  is no `day` field, no rollover, and no per-day figure anywhere in the meter or
  this payload, so the channel MUST NOT describe what it carries as a daily
  figure, and nobody downstream should read it as one. If 5.4 makes the meter
  per-day, the payload changes with it; this channel only transports whatever
  the meter holds.
- **`ticks` after a restart:** `ticks` comes from the same process-lifetime
  counter (`code_time.py:85`/`:100`, read at `:124`), so a bot showing nonzero hours with `ticks: 0`
  is normal after an agent restart, not evidence of never having ticked. Ticks
  distinguishes zero-usage from never-ticked only within one process.
- **Unknown bot:** the mod refuses the report (404) and counts it in a single
  counter; it MUST NOT create a bot or store a value under an unspawned name.

## Where it appears

Text-level only, no mockup:

- `GET /bots` and `GET /bot/{name}/status` each gain, per bot, a `script`
  object: `{"state": <reported state or "none">, "code_hours": <number>,
  "stale": <bool>, "observed_at": <timestamp>}`. No new endpoint is added for
  reading — the values ride the status a player already fetches.
- A stale report shows the last values with `stale: true`; a bot that has never
  reported shows `state: "none"` and no hours, which is distinguishable from
  `code_hours: 0`.
- The existing condition display (`runner_unreachable`, `script_disabled`,
  `allowance_exhausted`) is unchanged and is still derived by the mod from what
  it now sees; this channel supplies its inputs, it does not replace it.

## Tasks this adds

- **5.6** (metering) — the report sender in the agent: one `CodeTimeMeter` read
  and one per-tick script state per bot, POSTed at `REPORT_INTERVAL` and on
  change, never queued, dropped on failure. Unit test with a fake poster:
  cadence, on-change send, no retry, and a report carrying the previous figure
  so a fall is readable from one report.
- **5.7** (metering) — the mod receiver: `POST /bot/{name}/script_report`
  behind the existing auth, storing on `BotPlayer`, refusing unknown bots, and
  expiring to stale after `STALE_AFTER`. Tested at the handler level.
- **6.4** (script view) — the status surface: `script` object on `GET /bots`
  and `GET /bot/{name}/status`, with stale and never-reported as distinct
  values. Tested against a stored-then-aged report.

These are listed, not started. The lead reviews this design before any code row.

## What this design deliberately does not decide

- **Whether a fallback state raises a condition, and which.** The vocabularies
  stay closed; that mapping is "A Reported Condition Has A Defined Shape"'s
  decision, and `script_disabled` already covers the case where three
  non-`ok` ticks disable a script.
- **Whether usage persists across a restart, and what window `code_hours`
  covers.** Both are 5.4's. This channel transports whatever the meter holds
  and adds no window of its own.
- **What a fall is observable for, and what it is not.** A **day rollover** that
  produces a fall is observable from `previous_code_hours`. A **restart's** fall
  is not, and cannot be from this payload: `previous_code_hours` is absent on a
  bot's first report, and after a restart the meter is a new process at
  `_seconds = 0.0`, so that first report carries `code_hours: 0.0` with nothing
  to compare against -- it is precisely the report where 1.4 h becomes 0.0 h.
  From the receiver a restarted bot reads as a bot appearing at 0.0 h. The three
  ways out are all outside this channel: persist the counter (5.4's), keep a
  history in the mod (forbidden by latest-only storage), or send a cause marker
  (rejected above: the sender cannot distinguish restart from day rollover). So
  the design guarantees no more than this, and whether a restart reading as a
  fresh bot at 0.0 h must be labelled is 5.4's.
- **The cap's source.** Unchanged and still open; this channel reads the
  counter, not the cap.
