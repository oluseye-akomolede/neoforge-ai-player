# v5: LOCATE — structure reconnaissance

## Why

The End expedition (2026-08-04) sent Scout, Axiom and Mystic to find a
large structure. All three reached the End. None found anything, and the
failure was structural, not LLM variance.

L3 correctly reached for the only search directive that existed —
`WIDE_SEARCH` — with `target="end_city"`. But `WIDE_SEARCH` is a **block
scanner**: `WideSearchBehavior` fuzzy-matches its target against
`BuiltInRegistries.BLOCK`. There is no block named `end_city`, so no
amount of scanning could ever match. Axiom alone scanned **5,197,568
blocks** across 79 cells before the 15-minute directive deadline killed
it, then replanned the identical doomed directive four more times.

Brute force was never going to work regardless: an end city is typically
1,000+ blocks away, and `WIDE_SEARCH`'s largest shell is 1024 blocks of
*full-column* scanning. The bots had no primitive that could answer
"where is the nearest X" — only one that could answer "is X within
arm's reach", run very slowly, very far.

## Design

Minecraft already answers this question. `/locate` asks the chunk
generator where structures were **placed**, which is a placement
calculation rather than a search — one call, thousands of blocks, no
scanning. `LOCATE` exposes exactly that query.

- **`StructureLookup`** (`world/`) — name → `HolderSet<Structure>`, then
  `chunkGenerator.findNearestMapStructure(...)`. The same call
  `LocateCommand` makes.
- **`LocateBehavior`** — one-shot generator query on the first tick,
  reports coordinates, optionally travels.
- **`GET /server/structures`** — full structure + tag registry dump,
  modded included. The `/server/items` argument applies unchanged: a
  hand-written list of structure names cannot cover a 300+ mod pack.
- **`POST /bot/{name}/locate`** — the same lookup synchronously, without
  the plan pipeline.

### Resolution

Mirrors the item registry's contract — try increasingly loose matches,
prefer exactness, flag rather than guess:

1. exact id (`minecraft:end_city`)
2. bare path across namespaces (`end_city` in any mod's namespace)
3. structure tag (`village`, `#minecraft:village`)
4. substring across all registered structures

When a loose match hits several structures, LOCATE searches for the
nearest of **all** of them rather than picking one. "village"
legitimately means five structures; the useful answer is whichever is
closest, and the response names which one was found.

### Dimension pre-filter

Every structure declares the biomes it generates in, and a dimension's
biome source is memoized. Comparing them is nearly free and converts the
worst failure mode — asking for an `end_city` from the Overworld, which
otherwise runs a full multi-thousand-chunk search only to return null —
into an immediate, accurate diagnosis:

> `'end_city' does not generate in minecraft:overworld`

## The critical seam

**Coordinates must survive back to L3.** A structure whose position the
planner cannot name has not been located.

Two things were in the way:

- `ProgressReport` carried only int counters, a prose event log, and
  block scan data. A position fit none of them → added `results`, a
  structured map surfaced as `progress.result`.
- **`BotBrain` was discarding every directive's final progress.** A
  behavior returning SUCCESS is swapped for `idleBehavior` in the same
  tick, so by the time the agent polled (~1s later) `toMap()` reported
  the *idle* behavior's empty report. `lastDirective` was retained for
  polling; its progress was not. Every directive's completion counters
  had been silently empty. Fixed by retaining `lastProgress` alongside
  `lastDirective`.

The dispatch result string now carries it:
`COMPLETED LOCATE {...} result={'found': True, 'structure':
'minecraft:end_city', 'x': ..., 'z': ..., 'distance': ...}`

## What Changes

- **api-http**: `GET /server/structures`; `POST /bot/{name}/locate`.
- **bot-brain**: `LOCATE` directive type + `LocateBehavior`;
  `ProgressReport.results`; `BotBrain` retains the finished behavior's
  progress for polling.
- **l3-spec-driven-planning**: `LOCATE` in the directive vocabulary,
  with `WIDE_SEARCH` re-documented as blocks-and-entities-only and an
  explicit pointer to LOCATE for structures. Aliases FIND_STRUCTURE /
  LOCATE_STRUCTURE / SCOUT / EXPLORE / DISCOVER → LOCATE.
- **dashboard**: Locate Structure directive card.

## Non-Goals

- LOCATE does not replace `WIDE_SEARCH`. Blocks and entities still need
  a scanner; structures need a placement query. Each keeps its job.
- No region survey ("what is *in* this structure") — that is SCOUT, and
  it composes on top of these coordinates.
- Radius is in CHUNKS via `extra.chunk_radius`, not the block-radius
  field every other directive uses, because that is the unit the
  generator search takes. Reading `directive.radius` would silently
  shrink a 1600-block search to 16.

## Verification (2026-08-06)

Live on the test server. 290 structures across 23 namespaces, 88 tags.

**Resolution** — every path exercised against the real registry:

| input | → | via |
|---|---|---|
| `end_city` | `minecraft:end_city` @ 1288 blocks | exact |
| `end city` (spaces) | `minecraft:end_city` | exact |
| `village` | `minecraft:village_plains` @ 442 | tag, nearest of 5 |
| `woodland_mansion` | `minecraft:mansion` @ 6751 | name_contains_id |
| `ocean_monument` | `minecraft:monument` @ 861 | name_contains_id |
| `meteorite` | `ae2:meteorite` @ 559 | path_unique (modded) |
| `desert_temple` | `cataclysm:desert_temple` @ 9129 | path_unique (modded) |
| `ruined_portal` in Nether | `minecraft:ruined_portal_nether` @ 215 | exact+dimension_variant |
| `large_structure` | honest miss | no match |
| `end_city` from Nether | honest miss, no search run | dimension filter |

Cold searches ran 0–784 ms; repeats are ~0 ms (the generator caches
placements). The dimension filter answers instantly.

**The critical seam** — a LOCATE directive polled ~1 s after completion
still returned the behavior's full report, coordinates included:
`result={found: true, structure: minecraft:fortress, x: 320, z: 160,
distance: 357}`. Before the `lastProgress` fix this window returned the
idle behavior's empty report.

**Travel** — two bugs found and fixed by verification:

1. Teleporting into an **ungenerated chunk** made every block read as air,
   so `safeGroundY` found no pocket and returned a fixed fallback. A bot
   landed embedded in a bastion wall above lava. Destination chunks are now
   force-generated before the ground query.
2. Even loaded, the structure's reference corner was **open lava** — the
   generator returns a bounding-box origin, not a doorstep. Landing now
   searches outward in rings for two air blocks over solid, non-fluid
   ground, reports `landed_at`, and flags `travel_unsafe` when there is
   genuinely nowhere to stand. Re-test landed on basalt 4 blocks off the
   corner.

**Coordinate reuse** — the first expedition re-run exposed the last gap:
L3 chose `LOCATE end_city` unprompted and it resolved in 484 ms, but the
follow-up `GOTO` used the bot's *current* position. `last_result` feeds
criteria evaluation only, and every directive in a subtask is written by
one EXEC call before any of them run, so a same-subtask GOTO is always a
guess. Fixed on both sides: findings are recorded per bot and surfaced in
world state as `known_locations=[...]`, and the planner is told to use
`travel:true` for locate-and-go rather than chaining.

**Campaign result**: the End expedition, re-run. L3 emitted
`LOCATE {target: end_city, extra: {travel: true}}` unprompted. Both Scout
and Axiom landed at `(1024, 63, -895)` on end stone, and in-world
verification found `purpur_pillar` and `end_stone_bricks` six blocks away
at `(1030, 72, -890)`. Both plans finalized `complete`.

The identical task on 2026-08-04 finalized `failed` for all three bots
after 5.2 million wasted block scans and 17 replan cycles.
