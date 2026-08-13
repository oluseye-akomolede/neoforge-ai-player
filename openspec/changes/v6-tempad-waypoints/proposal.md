# v6: TemPad waypoints — bots write to your device

## Why

v5 made bots able to find things. A coordinate in a log is not a
destination: somebody still has to walk 1,288 blocks to the end city the
bot found. TemPad is already in the pack and already solves the second
half — saved locations you can open a portal to.

Connecting them turns reconnaissance into transport. A bot finds a
structure and the pin appears in your device.

## Design

**Reflection, not a compile dependency.** Binding against TemPad would
drag in resourcefullib as well, and the modpack is frozen — a hard
dependency on two jars we do not control is the coupling that rule
exists to prevent. The surface is one constructor and one method, so
reflection is cheap here and the failure mode is a logged no-op rather
than a mod that will not load.

`TempadBridge` (compat/) wraps, verified against tempad-1.21.1-3.0.4:

```
DefaultLocationHandler(GameProfile).plusAssign(NamedGlobalVec3)
NamedGlobalVec3(Component, Vec3, ResourceKey<Level>, float, Color)
```

`plusAssign` puts into `PlayerPointsData` — **server saved data keyed by
player UUID**, not a player attachment. Two consequences worth relying
on: writes work whether or not the recipient is online, and they survive
restarts. Offline recipients resolve through the server profile cache.

## Who gets the waypoint

Defaulted in L2, not left to L3. `_l3_orchestrator_dispatch` stamps
`share_with` with the player who gave the order, because the alternative
is hoping the model carries a username correctly across a multi-subtask
plan — the same class of assumption that produced invented item ids.
L3 may override to send a finding to a *different* player, or pass an
empty string to opt out.

## What Changes

- **compat**: `TempadBridge` — `addWaypoint`, `listWaypoints`,
  `resolveProfile` (online → profile cache), `prettyName`, `colorFor`.
- **bot-brain**: LOCATE takes `extra.share_with`; reports `shared`,
  `shared_with`, or `share_error` in its result. A failed delivery never
  fails the directive — the structure was still located.
- **api-http**: `POST /bot/{name}/tempad_share` for arbitrary
  coordinates (the bot as courier, not just as scout);
  `GET /server/tempad?player=<name>` to read waypoints back;
  `POST /bot/{name}/tempad_remove` to take one out — a device bots can
  write to needs a way to unwrite.
- **l3-spec-driven-planning**: LOCATE documented as auto-sharing;
  `share_with` is for redirecting to someone else.

Waypoints are tinted per structure family (end purple, nether orange,
village green…) so a device full of bot pins stays readable, and named
from the structure id — `minecraft:end_city` → "End City".

## Non-Goals

- No Timedoor opening from the bot side. TemPad's `TimedoorEvent` exists
  and the bot could in principle punch portals, but a bot that can move
  the player is a much larger blast radius than a bot that can leave a
  pin. Deliberately deferred.
- No location cards (`WalletLocationHandler`), anchor points, or shared
  team locations yet — one delivery path first.
- The bots' own vault/economy is untouched; waypoints cost nothing.

## The waypoint must be standable

A structure's generator position is a bounding-box reference whose Y is
routinely **0**. Writing that verbatim produced `Village Plains (336, 0,
288)` — a TemPad portal there opens inside bedrock. Waypoints now resolve
a real surface first: when the bot travelled, the shared position is
exactly where it is standing (already proven standable); otherwise the
destination chunk is force-generated and the same ring search runs.
`pillager_outpost` went from the reference `y=0` to a written `y=90`.

## Verification (2026-08-07)

Live on the test server, TemPad 3.0.4, 327 mods.

- **Bridge active** — `available: true`; resolved the offline player
  `sigmastrain` → `SigmaStrain` through the server profile cache.
- **Write + readback** — `tempad_share` wrote `Bridge Test (100, 64,
  -200)`; `GET /server/tempad` returned it with its UUID.
- **Persistence** — both waypoints survived a full server restart,
  confirming `PlayerPointsData` is saved data rather than a session
  attachment.
- **LOCATE sharing** — `LOCATE village` resolved via tag to
  `minecraft:village_plains` and reported `shared: true, shared_with:
  SigmaStrain`; the pin appeared named "Village Plains".
- **Standable Y** — `LOCATE pillager_outpost` reference `y=0` was written
  as `waypoint_y: 90`.
- **End to end, no share_with anywhere** — "Forge, find the nearest
  woodland mansion and tell me where it is" in chat. L3 emitted
  `LOCATE {target: woodland_mansion, extra: {travel: true}}`; L2 stamped
  `share_with: sigmastrain` from the requester. Forge landed on
  `dark_oak_planks` at `(-5935, 83, 3216)` — inside the mansion, 6,700
  blocks out — and the pin "Mansion" landed in the device at that exact
  position. Plan finalized `complete`.
- **Removal** — `tempad_remove` cleared the pre-fix `y=0` pin and the
  test pin, leaving the device holding only real findings.

Device state at the end of verification: `Mansion (-5935, 83, 3216)` and
`Pillager Outpost (512, 90, -511)`, both standable.
