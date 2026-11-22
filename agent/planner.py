"""
Task planner — decomposes a player instruction into numbered steps.

Uses a one-shot LLM call with a tight structured prompt to produce
a short JSON list of steps. The executor then works through them
one at a time.
"""

import json
import requests
from config import OLLAMA_URL, answer_text, ensure_not_truncated, think_field
import brain
import openai_brain
from action_binding import BINDABLE_KINDS, _REQUIRED_FIELDS, _REQUIRED_COORDS


class PlannerResult(list):
    """A planner answer: a list of steps, optionally carrying a script.

    It IS a list, so every existing caller that iterates `decompose`'s return
    value or indexes it behaves exactly as before -- the step path is not
    migrated to a new type, it simply never sees `script` set.

    `script` is the source text the planner wrote, or None. It is carried in
    the process only: the agent has no write path for script source (spec,
    "A Planner-Authored Script Lives In Memory, Not On Disk"), so a script that
    survives a restart would be a file this type never creates.
    """

    def __init__(self, steps, script=None):
        super().__init__(steps)
        self.script = script


# The script surface holds a slot for the required-argument block; filled by
# _fill_required_fields() after the kind list is substituted.
_SCRIPT_SURFACE_SLOT = "@@SCRIPT_SURFACE@@"
_REQUIRED_FIELDS_SLOT = "@@REQUIRED_FIELDS@@"


SCRIPT_SURFACE = """For goals that are REPETITIVE or CONDITIONAL — "keep the chest stocked",
"until I say stop, mine whatever you see" — a step list cannot express the
loop. You may answer with a JavaScript program instead. It runs once per tick
in a sandbox with no filesystem and no network, and reaches the world ONLY
through these calls:

- `api.do(directive, args)` — queue one game action. `directive` MUST be one of
  the @@N_KINDS@@ bindable kinds, named here in full; anything else is refused:

@@KIND_LIST@@

  Examples: @@EXAMPLES@@. Matching is
  case-insensitive (`"mine"` works), but the names are the ones above — there
  is no `"attack"` and no `"place"`; melee is `"COMBAT"` and putting an item in
  a container is `"CONTAINER_STORE"`. `args` is a plain object.
@@REQUIRED_FIELDS@@
  Returns `{ok, seq}` or a rejection.
- `api.say(text)` — speak in chat.
- `api.send(otherBot, msg)` — message another bot.
- `api.remember(blob)` — store a string (≤16 KB) that the NEXT tick's
  `api.recall()` returns. This is the only state that persists between ticks.
- `api.recall()` — the string this tick started with, or `null`.
- `api.log(level, text)` — write one diagnostic line (≤1 KB).
- `api.result(value)` — report a value to the planner. Returns `{ok: true}`
  or a rejection. The value reaches the planner when the script ENDS (`done`,
  an error, or `escalate`); the LAST call in a tick wins; it is cut at 2 KiB
  with a truncation marker. The script's top-level return value is discarded —
  this call is how a script reports. Use it to say what a goal found, or why
  it stopped.

  Say whether the work SUCCEEDED by passing an object with a boolean `done`
  field: `api.result({done: true, found: 3})` closes the goal, while
  `api.result({done: false, reason: "no diamond_ore within 32 blocks"})` keeps
  it open and re-plans. The `done` field is what decides — not the wording, so
  a successful result may contain the word "failed" and a failed one need not
  use it. A plain-string result carries no verdict and is treated as done, so
  a script that must report failure has to set `done: false`.

`look` — read-only questions about the tick's snapshot, already in hand (no
call cost, no network). It answers the world as of THIS tick, not a live query:

- `look.blocks(kind, options?)` → `{ok: true, kind: 'blocks', matches: [...]}`
- `look.entities(type, options?)` → `{ok: true, kind: 'entities', matches: [...]}`
- `look.age()` → `{ok: true, ageMs}`, how old the snapshot is
- `look.inventory()` → `{ok: true, items: [...]}`, what the bot is carrying
  right now (same snapshot). Read-only: it cannot change the inventory.
- `look.self()` → `{ok: true, position: {x, y, z}, health, food}`, the bot's
  OWN body this tick. `position` is the bot, the same `{x, y, z}` shape a block
  or mob entry has. This is how a script checks whether it has ARRIVED — there
  is no `snapshot.self`; reading that gives `undefined` and an arrival check
  written on it never passes, so the script re-issues the same movement
  forever. Compare `look.self().position` against the target.
- `look.task()` → `{ok: true, id, type, status, result, phase, failure_reason}`,
  the directive the bot is running and what it has REPORTED. `api.do` answers
  `{ok: true, seq}`, which means the action was ACCEPTED — it never means it
  happened or where it ended up. `status` is `RUNNING`, `COMPLETED`, `FAILED`
  or `CANCELLED`, and `id` says which directive, so you can ignore a stale
  completion from an earlier one. `result` carries the fields the finished
  action reported: a `GOTO` puts `arrived_at` (`{x, y, z}` where the bot
  actually stopped), and `adjusted_from`/`adjusted_to` when the target was
  lifted. `result` is `{}` before anything is reported, so
  `result.arrived_at` is `undefined` rather than an error; `failure_reason` is
  where a failure explains itself (e.g. `target_enclosed`).
  A FINISHED directive keeps being reported until you dispatch another one, so
  a wait on `status === 'COMPLETED'` ends instead of polling forever.
  Every field is a TOP-LEVEL field of what `look.task()` returns: read
  `task.type` and `task.status`, never `task.directive` (no such field — there
  is no nested `directive` object, and reading it gives `undefined`, so a wait
  written on it never ends). With no directive yet it answers `ok: true` with
  `id: null`, `type: null`, `status: null` and `result: {}`.
- A failed query answers `{ok: false, reason, message}`.
- `kind`/`type` match the entry's id or display name, case-insensitive, and a
  leading `minecraft:` on either side is ignored, so `'iron_ore'` and
  `'minecraft:iron_ore'` both work. A block entry has `{id, block, position}` —
  no block state, so you cannot ask for "a red flower" that way.
- The three lookups return entries with DIFFERENT identity fields, so read the
  right one and do not assume `id` works everywhere:
  a block entry has `{id, block, position}` (`id` is the namespaced registry id);
  a mob entry has `{type, name, position, distance}` — the identity field is
  `type`, NOT `id`;
  an inventory item has `{slot, item, count, display_name, max_stack_size}`
  (plus `durability`/`max_durability` on a damageable tool) — the identity field
  is `item`, NOT `id`. Read `items[0].item` and `items[0].count`; reading
  `items[0].id` gives `undefined`, which looks like an empty inventory rather
  than an error.
- Check `look.inventory()` before a task that needs a tool: shearing needs
  shears, mining needs a pickaxe. If the tool is missing, say so or fetch it.
  Do not start an action the bot has no tool for.
- The snapshot covers blocks within 5 blocks and entities within 16. Asking
  for more answers `not-searched-that-far`, which is NOT the same as "none
  there". `options.radius` only narrows.
- Use it to look before acting on a block the bot has to be near — check a
  chest is there before walking to it.

Rules for scripts:
- At most 8 host calls per tick. `api.do`, `api.say`, `api.send`,
  `api.remember`, `api.log` and `api.result` each count; `api.recall()` and
  `look` are free, because they answer from data already in hand.
  Rate limits are enforced: `do` 30/min, `say` 30/min, `send` 20/min.
  Exceeding them is REFUSED, not queued.
- A script that returns does nothing further this tick; the next tick runs it
  again. Do not loop forever inside one tick — it is not a thread.
- Use `api.recall()` at the top to continue work across ticks.
- `api.say` only when something changed since the last tick; a line you say
  again within a minute is suppressed, so a repeat is wasted, not harmful.
- Anything a script `api.do`s is dispatched like a planned step, so use real
  directive names, not invented ones.
- An action you `api.do` takes effect AFTER this tick: the dispatch is queued
  and the world changes on a later tick, so `look` in the same tick still shows
  the old state. Never assume the effect landed because `api.do` returned
  `{ok: true}` -- `ok` means the action was ACCEPTED, not that it happened.
  Verify on a later tick before reporting progress, or you will log work that
  has not occurred.
- `GOTO` goes to a POSITION, not to a block. To work on a block, `GOTO` a
  neighbouring open block, or a position within reach of it -- never the block
  itself. A GOTO into solid rock fails with `target_enclosed` rather than
  digging to it; if the destination was lifted up to 3 blocks to a clear
  standing spot, the COMPLETED result carries `adjusted_from` and
  `adjusted_to` -- the requested and the actual destination, each an
  `{x, y, z}` map. Write an arrival check against `look.task().result`
  (`arrived_at`, `adjusted_to`) or against `look.self().position`, never
  against the coordinates you asked for."""


def _render_kind_list(kinds):
    """The bindable kinds as a wrapped backticked list, sorted for stability."""
    names = [f"`\"{k}\"`" for k in sorted(kinds)]
    lines, line = [], "  "
    for name in names:
        if len(line) + len(name) + 2 > 78:
            lines.append(line.rstrip())
            line = "  "
        line += name + ", "
    lines.append(line.rstrip(", "))
    return "\n".join(lines)


def _render_examples(kinds):
    """Four kinds for the prompt's Examples line, taken FROM the binding.

    Named here as candidates only; a candidate the binding does not have is
    skipped, so removing a kind from the binding removes it from the prompt
    instead of leaving a stale example behind. Falls back to the first sorted
    kinds if none of the preferred ones survive, so the line is never empty.
    """
    preferred = ["MINE", "GOTO", "COMBAT", "CONTAINER_STORE"]
    chosen = [k for k in preferred if k in kinds][:4]
    if len(chosen) < 4:
        chosen += [k for k in sorted(kinds) if k not in chosen][:4 - len(chosen)]
    return ", ".join(f'`"{k}"`' for k in chosen)


def _render_required_fields(required, coords=None):
    """Say which arguments a kind cannot do without, taken FROM the binding.

    The wedge this prevents: `MINE` sent with coordinates and no `target` bound
    cleanly and then killed the bot's tick loop. The script author cannot know
    which argument a kind needs unless the prompt says so, and a hand-written
    list would drift from `_REQUIRED_FIELDS` the moment a kind is added --
    exactly how "attack" and "place" got into the Examples line. Kinds whose
    arguments are optional are not listed. Returns the lines without their
    indent, or [] -- so a caller can emit nothing rather than a stray bullet.

    `coords` is the separate coordinate table. It is rendered here, by the same
    join against `BINDABLE_KINDS`, rather than in a second function, so the two
    tables can never disagree about which kinds survive into the prompt.
    """
    # Only kinds the binding can still dispatch. A required entry for a kind
    # that is gone would be a prompt line about an action nothing accepts; the
    # required table and the bindable set are separate declarations, so they
    # are joined here rather than assumed to agree.
    required = {k: v for k, v in (required or {}).items()
                if k in BINDABLE_KINDS and v}
    coords = {k: v for k, v in (coords or {}).items()
              if k in BINDABLE_KINDS and v}
    items = []
    for kind in sorted(required):
        named = " and ".join(f'`"{f}"`' for f in required[kind])
        items.append(f'`"{kind}"` needs {named}.')
    for kind in sorted(coords):
        named = ", ".join(f'`{f}`' for f in coords[kind])
        items.append(f'`"{kind}"` needs {named}, as numbers.')
    if not items:
        return []
    lines = ["Some kinds also NEED an argument; an action without one is "
             "not dispatched at all:",
             *[f"- {item}" for item in items]]
    if required:
        lines.append("`target` is a block, item or entity id "
                     "(`\"minecraft:iron_ore\"`), never a position: x/y/z are "
                     "coordinates and do not stand in for it.")
    if coords:
        lines.append("Coordinates are where the bot ends up, so a zero is a "
                     "real position: send x, y and z as numbers or the action "
                     "is refused (it will NOT default to 0,0,0).")
    return lines


def _fill_required_fields(surface, required, coords=None):
    """Replace the required-argument slot in `surface` with its rendered lines.

    The slot occupies a line of its own, so it is replaced together with its
    leading newline -- otherwise removing it would leave a blank line. With
    nothing required the whole partial is dropped instead of left in saying
    "nothing here": a prompt line about a rule that does not exist would be a
    claim the binding does not make.
    """
    lines = _render_required_fields(required, coords)
    if not lines:
        return surface.replace("\n" + _REQUIRED_FIELDS_SLOT, "")
    block = "".join("  " + line + "\n" for line in lines)
    return surface.replace("\n" + _REQUIRED_FIELDS_SLOT, "\n" + block.rstrip("\n"))


# The kind list and the required-argument list are computed from the binding,
# not typed: a hand-written list is exactly the thing that drifted (the prompt
# offered "attack" and "place", neither of which the binding accepts, and said
# nothing about `target` before a script wedged a bot with a targetless MINE).
# Substituted by plain string replace rather than .format, because this surface
# holds literal braces like {ok, seq}.
SCRIPT_SURFACE = (SCRIPT_SURFACE
                  .replace("@@N_KINDS@@", str(len(BINDABLE_KINDS)))
                  .replace("@@KIND_LIST@@", _render_kind_list(BINDABLE_KINDS))
                  .replace("@@EXAMPLES@@", _render_examples(BINDABLE_KINDS)))
SCRIPT_SURFACE = _fill_required_fields(SCRIPT_SURFACE, _REQUIRED_FIELDS,
                                       _REQUIRED_COORDS)


PLANNER_PROMPT = """You are a Minecraft task planner. Break the player's instruction into simple, sequential steps that a bot can execute one at a time.

## How to decompose

IF the player gives explicit numbered steps or a clear sequence (e.g. "do X then Y then Z"):
- Preserve their steps exactly. Do NOT merge, split, or reorder them.
- You may add missing prerequisites (e.g. "craft a pickaxe" implies gathering wood/stone first).

IF the player gives a vague or high-level goal (e.g. "get me iron gear" or "set up a base"):
- Reason about what Minecraft actions are needed and produce concrete steps.
- Think about prerequisites: what materials are needed? What tools are required first?

## Rules
- Each step = ONE concrete action: mine, craft, find, go to, place, build, farm, collect, smelt, combat, follow, channel, send_item, etc.
- Use Minecraft registry IDs where possible (e.g. "minecraft:stone_pickaxe" not "stone pickaxe")
- For combat vs hostile mobs: "Engage combat mode 300s" (fights hostiles only — zombies, skeletons, spiders, creepers)
- For hunting animals: "Attack cow 120s" or "Attack pig 120s" (targets specific animal type — NEVER use "Engage combat mode" for animals)
- For combat vs specific mob: "Attack zombie 120s" or "Kill creeper 60s"
- IMPORTANT: If prior steps involved mining or digging underground, add "Mine upward to surface" BEFORE any combat or hunting step — mobs spawn on the surface at night, not in lit caves
- For following: "Follow <player_name>" or "goto_player <player_name>" (replace <player_name> with the actual player name from the instruction)
- For channeling: "Channel cataclysm:void_forge" or "Channel 3x thermal:machine_frame" — copy the EXACT item ID from the transmute registry below (do NOT substitute "modid", use the real namespace)
- For sending items: "Send 10 minecraft:iron_ingot to Scout" (transfers items between bots instantly)
- For building: "Build shelter" or "Build wall with minecraft:stone_bricks" (available: shelter, wall, tower, platform)
- For farming: "Farm wheat" or "Farm carrot with minecraft:stone_bricks" (available crops: wheat, carrot, potato, beetroot) — builds a bordered farm, plants, grows with XP, and harvests
- For storing items: "Store 64 minecraft:cobblestone into container" (finds or conjures a chest, deposits items)
- For withdrawing items: "Withdraw 10 minecraft:iron_ingot from container" (searches containers, takes items)
- For teleporting: "Teleport to the nether" or "Teleport to the end at 100 70 100" (cross-dimension travel)
- PRIORITY: always prefer craft > mine > smelt over channel. Channel is a last resort for modded items that have no known recipe or cannot be gathered normally
- For crafting with quantities, ALWAYS include the count: "Craft 16x minecraft:torch", "Craft 4x minecraft:stick". The count is the NUMBER OF ITEMS you want, not the number of recipe batches
- Keep steps short (under 15 words each)
- 1-8 steps maximum
- Do NOT include "equip" as a separate step — the bot auto-equips after crafting
- "collect" after mining is automatic — don't add separate collect steps
- NEVER generate "Follow dashboard", "Follow menu", or any follow-UI steps — follow is ONLY for following players
- If the instruction is already a single action, output just one step
- NEVER say "go to Y=N" — the bot cannot teleport to a Y level. Say "dig a staircase down to Y=N" instead
- For underground tasks, always say "dig down" or "mine downward" — the bot must physically dig, not use goto
- Do NOT re-delegate or assign work to other bots — just describe what YOU need to do
- If YOU need a crafted/conjured item in YOUR inventory, YOU must craft/conjure it yourself — items cannot transfer between bots
- CHECK the bot's inventory before planning. If the bot already has required materials, SKIP the gathering step

## Minecraft knowledge
- Diamonds are found below Y=16, require minecraft:iron_pickaxe or better to mine
- Iron ore requires minecraft:stone_pickaxe or better. Smelt minecraft:raw_iron in a furnace to get ingots
- You cannot craft stone — you mine it (cobblestone drops from stone blocks)
- Furnace recipe: 8x minecraft:cobblestone in a ring
- To smelt, you need fuel (minecraft:coal or minecraft:charcoal) and a placed furnace
- Tools progression: wood -> stone -> iron -> diamond -> netherite
- Use "goto_player" to go to a player — NEVER guess coordinates
- Use "send_item" to transfer items to another bot (works at any distance, across dimensions)
- Use "shop_buy" to purchase items from the bot shop (costs emeralds)
- Use "goto_waypoint" to travel to saved locations
- ALWAYS use "Wide search for X" when asked to search, find, or look for blocks or entities. NEVER use find_blocks or find_entities for search tasks
- For parallel multi-bot searching, delegate wide_search tasks to other bots with different bot_index values

## Examples

Input: "Craft a stone pickaxe, mine coal, build a furnace"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:coal_ore", "Craft and place minecraft:furnace"]}}

Input: "Get me a full set of iron armor"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:iron_ore (at least 24)", "Craft minecraft:furnace and place it", "Smelt minecraft:raw_iron into minecraft:iron_ingot", "Craft minecraft:iron_helmet", "Craft minecraft:iron_chestplate", "Craft minecraft:iron_leggings", "Craft minecraft:iron_boots"]}}

Input: "Go chop some trees"
Output: {{"steps": ["Find and mine nearby logs (minecraft:oak_log or minecraft:birch_log)"]}}

Input: "Craft 32 torches"
Output: {{"steps": ["Find and mine minecraft:coal_ore", "Craft 32x minecraft:torch"]}}

Input: "Hunt animals and cook at least 8 meat"
Output: {{"steps": ["Attack cow 120s", "Attack pig 120s", "Smelt 8x minecraft:beef"]}}

Input: "Restock to at least 16 cooked meat"
Output: {{"steps": ["Attack cow 180s", "Attack pig 120s", "Smelt 16x minecraft:beef"]}}

Input: "Help me get diamonds"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:iron_ore", "Craft and place minecraft:furnace", "Smelt minecraft:raw_iron into minecraft:iron_ingot", "Craft minecraft:iron_pickaxe", "Dig down to Y=16 or below", "Find and mine minecraft:diamond_ore"]}}

{memory_section}

{transmute_section}

{inventory_section}

## Writing a script instead of steps

{script_section}
Respond ONLY with ONE JSON object, either:
{{
  "steps": ["step 1", "step 2", ...]
}}
or, for a repetitive/conditional goal:
{{
  "script": "const s = api.recall(); ..."
}}"""


def _script_from(parsed):
    """The planner's script source from a parsed answer, or None.

    Kept deliberately strict: a script is a non-empty string under "script".
    Anything else -- a list, a dict, "", None -- is not a program, and treating
    it as one would hand the runner source it cannot run while suppressing the
    step list that answer actually carried. A model that emits both keys is a
    contract violation; the script wins because the step list is the older,
    safer reading and a half-formed program is worth more scrutiny than a plan.
    """
    if not isinstance(parsed, dict):
        return None
    script = parsed.get("script")
    if isinstance(script, str) and script.strip():
        return script
    return None


def render_planner_prompt(memory_section="", transmute_section="", inventory_section=""):
    """The planner prompt as the model receives it.

    SCRIPT_SURFACE is substituted AFTER .format, not through it: it holds
    plain single braces (real API shapes like {ok, seq}) which .format would
    read as fields. l3_planner substitutes the same constant the same way, so
    one string serves both prompts and they cannot drift apart.
    """
    return PLANNER_PROMPT.format(
        script_section=_SCRIPT_SURFACE_SLOT,
        memory_section=memory_section, transmute_section=transmute_section,
        inventory_section=inventory_section,
    ).replace(_SCRIPT_SURFACE_SLOT, SCRIPT_SURFACE)


def decompose(model, instruction, memory_context="", transmute_context="", inventory_context="", sender=""):
    """Break an instruction into a list of step strings."""
    memory_section = ""
    if memory_context and memory_context != "No relevant memories.":
        memory_section = f"## Relevant memories from past experience\n{memory_context}\n\nUse these memories to make better plans. Avoid repeating past mistakes."
    transmute_section = ""
    if transmute_context:
        transmute_section = f"## Discovered transmutable items (can be conjured with XP)\n{transmute_context}"

    inventory_section = ""
    if inventory_context:
        inventory_section = f"## Bot's current inventory (skip gathering steps for items already owned)\n{inventory_context}"

    sender_section = ""
    if sender:
        sender_section = f'\nThe player who sent this instruction is named "{sender}". When steps reference this player (e.g. "come to me"), use their exact name "{sender}" — not a placeholder.\n'

    prompt = render_planner_prompt(
        memory_section=memory_section, transmute_section=transmute_section,
        inventory_section=inventory_section) + sender_section

    with brain.ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": instruction},
                ],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.3,
                    "num_predict": 256,
                },
            },
            timeout=60,
        )
    resp.raise_for_status()
    _body = resp.json()
    ensure_not_truncated(_body, "decompose")
    content = answer_text(_body)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
        else:
            return PlannerResult([instruction])

    script = _script_from(parsed)
    if script is not None:
        # A program answer: there is no step list to execute. Returning it with
        # zero steps keeps every caller's iteration correct (it does nothing)
        # and the agent binds the script instead of driving a plan.
        return PlannerResult([], script=script)

    steps = parsed.get("steps", [])
    if not steps or not isinstance(steps, list):
        # L4 fallback: try OpenAI if local LLM produced nothing useful
        if openai_brain.is_available():
            try:
                l4_steps = openai_brain.decompose(instruction, prompt)
                if l4_steps and isinstance(l4_steps, list):
                    print(f"[planner/L4] OpenAI produced {len(l4_steps)} steps")
                    return PlannerResult([str(s) for s in l4_steps[:8]])
            except Exception as e:
                print(f"[planner/L4] OpenAI fallback failed: {e}")
        return PlannerResult([instruction])

    return PlannerResult([str(s) for s in steps[:8]])


# ── Orchestrator: specialization-aware decomposition ──

ORCHESTRATOR_PROMPT = """You are a Minecraft task orchestrator. Break the player's instruction into L1-ready primitive steps AND assign each to the best bot.

## Available bots
{bot_list}

## Step format — CRITICAL
Each step MUST be a single primitive that the bot can execute directly. Use these exact patterns:
- Mine: "Mine minecraft:iron_ore (24)" or "Find and mine minecraft:oak_log"
- Craft: "Craft minecraft:iron_pickaxe" or "Craft 4x minecraft:stick"
- Smelt: "Smelt minecraft:raw_iron" or "Smelt 8x minecraft:raw_iron"
- Channel: "Channel modid:item_name" or "Channel 3x modid:item_name" (conjure discovered items for XP)
- Combat: "Engage combat mode 300s" (fights hostile mobs for N seconds — use 300s for a full night cycle)
- Attack: "Attack zombie 30s" or "Kill creeper" (fights specific mob type)
- Follow: "Follow <player_name>" or "goto_player <player_name>" (replace <player_name> with the actual player name)
- Goto: "goto_player <player_name>" or "goto_waypoint base"
- Send: "Send 10 minecraft:iron_ingot to Scout" (instant item transfer between bots)
- Build: "Build shelter" or "Build wall with minecraft:stone_bricks" (shelter, wall, tower, platform)
- Farm: "Farm wheat" or "Farm carrot with minecraft:stone_bricks" (wheat, carrot, potato, beetroot)
- Store: "Store 64 minecraft:cobblestone into container" (finds or conjures a chest, deposits items)
- Withdraw: "Withdraw 10 minecraft:iron_ingot from container" (searches containers, takes items)
- Teleport: "Teleport to the nether" or "Teleport to the end at 100 70 100" (cross-dimension travel)
- Search: "Wide search for diamond_ore" or "Wide search for cow (entity)" — expanding-cube search across a large area
- Dig: "Dig down to Y=16"

PRIORITY: always prefer Craft > Mine > Smelt over Channel. Channel is a last resort for modded items that have no known recipe or cannot be gathered normally. Only use Channel for items listed in the transmute registry section below.
CHECK bot inventories below before planning. If a bot already has required materials, SKIP the gathering step for that bot. Use send_item to transfer materials between bots when it saves time.

For "engage combat", "fight enemies", "defend me", or similar — use "Engage combat mode 300s" for EVERY bot. Use longer durations (600s+) for sustained combat or "fight through the night" scenarios.
For "hunt animals", "kill cows/pigs/chickens" — use "Attack cow 120s" or "Attack pig 120s" (NOT "Engage combat mode"). NEVER use "Engage combat mode" for hunting — it only targets hostile mobs.
For "get food", "cook meat", "restock cooked meat", or any food task — first hunt animals ("Attack cow 120s", "Attack pig 120s"), then smelt the drops ("Smelt Nx minecraft:beef"). Hunting provides raw meat without spending XP. Only fall back to channeling if no animals are available.
For "come to me" or "come here" — use "Follow <player_name>" for EVERY bot (replace <player_name> with the sender's actual name from the instruction).
When the instruction says "all bots", "every bot", or "everyone" — create a separate step for EVERY available bot. If there is a quantity, split it evenly (e.g. "all bots channel 200 items" with 5 bots = 40 per bot). Assign each step to a specific bot name — do NOT use "any".
For "search for X" or "find X" across a large area — use "Wide search for X" and assign to ALL available bots for parallel searching. Each bot automatically searches a different grid slice.

ALWAYS use registry IDs (modid:item_name). Include counts where relevant.

## Rules
- 1-20 steps maximum (more if many bots)
- Assign each step to the bot whose specialization best matches
- If no bot fits, use "any"
- Steps for different bots run in parallel
- Steps for the SAME bot run sequentially (order matters!)
- Think about prerequisites: tools before mining, materials before crafting
- Each bot's steps must be self-contained — items stay in the crafter's inventory
- If bot A makes something bot B needs, add a send_item step
- For "come to me" commands, ALL bots use goto_player
- Do NOT combine actions: "Craft and place minecraft:furnace" is TWO steps

## Minecraft knowledge
- Diamonds below Y=16, need minecraft:iron_pickaxe+
- Iron ore needs minecraft:stone_pickaxe+. Smelt minecraft:raw_iron for ingots
- Furnace: 8x minecraft:cobblestone
- Tools: wood -> stone -> iron -> diamond -> netherite
- Torches: 1 minecraft:coal + 1 minecraft:stick = 4 torches
- Sticks: 2 minecraft:oak_planks = 4 sticks
- Planks: 1 minecraft:oak_log = 4 planks
- Hunting: "Attack cow 120s" or "Attack pig 120s" kills animals and auto-collects drops (raw beef, raw porkchop, raw chicken)
- Cooking: "Smelt 8x minecraft:beef" cooks raw meat into cooked food. Works for beef, porkchop, chicken, mutton, rabbit, cod, salmon, potato
- For "get food", "cook meat", or "restock cooked meat" — hunt animals first ("Attack cow 120s", "Attack pig 120s"), then smelt the drops ("Smelt Nx minecraft:beef"). Hunting provides free raw meat without XP cost

{memory_section}

{transmute_section}

{inventory_section}

Respond ONLY with JSON:
{{
  "steps": [
    {{"step": "primitive action string", "assign": "bot_name_or_any", "specialization": "mining/building/crafting/combat/gathering/any"}}
  ]
}}"""


def orchestrate(model, instruction, bot_profiles, memory_context="", transmute_context="", inventory_context="", sender=""):
    """Decompose a task with bot specialization assignments.

    Returns list of dicts: [{"step": str, "assign": str, "specialization": str}, ...]
    """
    bot_lines = []
    for p in bot_profiles:
        specs = ", ".join(p.get("specializations", ["general"]))
        bot_lines.append(f"- {p['name']}: {specs} — {p.get('personality', '')[:80]}")
    bot_list = "\n".join(bot_lines) if bot_lines else "- No specialized bots available"

    memory_section = ""
    if memory_context and memory_context != "No relevant memories.":
        memory_section = f"## Relevant memories\n{memory_context}"

    transmute_section = ""
    if transmute_context:
        transmute_section = f"## Discovered transmutable items (can be conjured with XP)\n{transmute_context}"

    inventory_section = ""
    if inventory_context:
        inventory_section = f"## Current bot inventories (skip gathering for items already owned, use send_item to share)\n{inventory_context}"

    sender_section = ""
    if sender:
        sender_section = f'\nThe player who sent this instruction is named "{sender}". When steps reference this player (e.g. "come to me"), use their exact name "{sender}" — not a placeholder.\n'

    prompt = ORCHESTRATOR_PROMPT.format(
        bot_list=bot_list,
        memory_section=memory_section,
        transmute_section=transmute_section,
        inventory_section=inventory_section,
    ) + sender_section

    with brain.ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": instruction},
                ],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512,
                },
            },
            timeout=60,
        )
    resp.raise_for_status()
    _body = resp.json()
    ensure_not_truncated(_body, "orchestrate")
    content = answer_text(_body)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
        else:
            return [{"step": instruction, "assign": "any", "specialization": "any"}]

    steps = parsed.get("steps", [])
    if not steps or not isinstance(steps, list):
        return [{"step": instruction, "assign": "any", "specialization": "any"}]

    result = []
    for s in steps[:20]:
        if isinstance(s, dict):
            result.append({
                "step": str(s.get("step", "")),
                "assign": str(s.get("assign", "any")),
                "specialization": str(s.get("specialization", "any")),
            })
        else:
            result.append({"step": str(s), "assign": "any", "specialization": "any"})
    return result
