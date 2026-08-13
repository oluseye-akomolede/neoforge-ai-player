"""L3 spec-driven planning calls for aiplayer-mod bots.

Three call types:
  call_plan      — Phase 1, once per task, produces a Plan
  call_exec      — Phase 2, per subtask, produces directives
  call_replan    — fallback when a subtask exhausts retries

Reuses brain.ollama_lock for GPU serialization. When llm-gateway is
in front of Ollama, requests still go through OLLAMA_URL — the
gateway's Ollama-compat /api/chat handles them transparently.
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import requests

import trajectory_log
from brain import ollama_lock
from config import OLLAMA_URL
from plan_schema import Plan, PlanValidationError, Subtask, validate_plan_dict, validate_subtask_dict

log = logging.getLogger("aibot.l3-planner")


BOT_PERSONAS = {
    "axiom":  "generalist; plans flexibly across any task domain",
    "forge":  "builder; plans in terms of materials, coordinates, construction sequences",
    "mystic": "mage; plans around enchantments, potions, magical resources",
    "scout":  "explorer; plans in terms of movement, mapping, resource discovery",
    "tiller": "farmer; plans around crop cycles, soil, water, harvest sequences",
}

# Default dimension list if the mod API isn't reachable / hasn't been queried.
# Real list is fetched at orchestrator-call time and overrides this.
_DEFAULT_DIMENSIONS = [
    "minecraft:overworld",
    "minecraft:the_nether",
    "minecraft:the_end",
]

_PRIMARY_DIMS = {"minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"}


def _dim_lines(dimensions: list[str] | None) -> str:
    """Render the dimension list with usage annotations. War-test finding #4:
    an unannotated list led L3 to stage crafting inside ae2:spatial_storage."""
    dims = dimensions or _DEFAULT_DIMENSIONS
    primary = [d for d in dims if d in _PRIMARY_DIMS]
    exotic = [d for d in dims if d not in _PRIMARY_DIMS]
    lines = [f"  - {d}" for d in primary]
    lines += [f"  - {d} (special-purpose — do NOT travel here unless the task names it)"
              for d in exotic]
    return "\n".join(lines)


# ── Phase 1: plan ──────────────────────────────────────────────────────────


_PLAN_SYSTEM_PROMPT = """You are {bot_name}, an AI bot in Minecraft.
Persona: {persona}.

Your job RIGHT NOW is NOT to execute the task — it is to plan it.

Available dimensions on this server (you can subtask any of these; use exact ids):
{dimensions}

Decompose the task below into ordered atomic subtasks. For each subtask:
- A clear `description` of what to do
- An explicit `criteria` string — a condition observable in world state that
  proves this subtask is done (e.g. "inventory has 16 wheat", "bot at 100,64,-200",
  "block at 5,64,7 is oak_log", "bot in dimension minecraft:the_nether")

Criteria MUST use one of these machine-checkable forms whenever possible:
  - "inventory has <N> <item_id>"          (item possession)
  - "bot at (<x>, <y>, <z>)"               (position)
  - "bot in dimension <dimension_id>"       (dimension)
  - "killed <N> enemies"                    (combat kill count — verified
                                             against the bot's kill statistic)
  - "block at (<x>,<y>,<z>) is <block_id>"  (placed/changed block)
Free-text criteria cannot be verified and will be judged loosely — avoid them.

Construction rules (MANDATORY for fortresses, strongholds, bases):
- Build from minecraft:quartz_block ONLY. Terrain-native materials
  (netherrack, stone, dirt) are indistinguishable from the landscape —
  invisible to players and unverifiable by block checks. Acquire quartz by
  mining nether quartz ore and crafting, or by channeling quartz blocks.
- FIRST subtask after arrival MUST clear a pocket: excavate an open volume
  larger than the structure (BUILD blueprint "clear") — never embed walls
  inside solid terrain.

Reconnaissance: structures (end city, fortress, village, stronghold, mansion,
monument, and modded ones) are LOCATED, not searched for. A single subtask
"locate the nearest <structure> and travel to it" is correct and sufficient —
do not plan a sweep, a grid search, or an exploration phase to find one.
Coordinates a bot has already found appear in world state as known_locations.

Inventory model: each bot has 36 carried slots plus an UNBOUNDED vault.
Overflow pages to the vault automatically and BUILD withdraws from it as
needed, so you never need to plan around running out of space. "inventory
has N item" criteria count carried + vault together.

Criteria geometry rules (checked against the real world — violations fail):
- Block coordinates MUST be inside the world. The nether's build range is
  y 0..127; the overworld's is y -64..319. Never use negative y in the nether.
- A "block at" criterion must name a position INSIDE the volume a subtask
  actually builds, at the SAME y-level as the build origin — do not invent
  positions above, below, or beside the structure.

Constraints:
- Output ONLY JSON. No prose. No markdown fences.
- 1 to 6 subtasks. Break larger jobs into multiple submissions instead.
- Each subtask should map to 1-3 directives maximum.
- Your subtasks together MUST cover EVERY action clause in the task. If the
  task says prepare AND travel AND fight, all three must appear as subtasks —
  do not drop trailing clauses.
- If the task involves a dimension change (e.g. "to the nether"), the FIRST
  subtask MUST be a teleport to that dimension. Use the exact dimension id.

Output schema:
{{
  "task": "<echo the task text>",
  "subtasks": [
    {{
      "id": 1,
      "description": "...",
      "criteria": "..."
    }},
    ...
  ]
}}
"""


def call_plan(model: str, bot_name: str, task: str,
              world_state_summary: str = "",
              dimensions: list[str] | None = None) -> Plan:
    persona = BOT_PERSONAS.get(bot_name, "generalist")
    log.info("[%s] L3 PLAN call — task: %s", bot_name, task[:60])
    dim_lines = _dim_lines(dimensions)
    sys_prompt = _PLAN_SYSTEM_PROMPT.format(
        bot_name=bot_name, persona=persona, dimensions=dim_lines)
    user = f"World state: {world_state_summary}\n\nTask: {task}" if world_state_summary else task

    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 1024},
            },
            timeout=120,
        )
    resp.raise_for_status()
    raw = _strip_codefence(resp.json()["message"]["content"])
    created_at = datetime.datetime.utcnow().isoformat()
    try:
        data = json.loads(raw)
        validate_plan_dict(data)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="plan", bot=bot_name, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=created_at, parse_error=f"non-JSON: {e}",
        )
        raise PlanValidationError(f"L3 PLAN returned non-JSON: {e}") from e
    except PlanValidationError as e:
        trajectory_log.log_call(
            phase="plan", bot=bot_name, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=created_at, parse_error=str(e),
        )
        raise
    trajectory_log.log_call(
        phase="plan", bot=bot_name, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=data,
        world_state_summary=world_state_summary,
        plan_ref=created_at,
    )
    return Plan(
        task=data["task"],
        bot=bot_name,
        created_at=created_at,
        status="executing",
        subtasks=[Subtask.from_dict(s) for s in data["subtasks"]],
        current_subtask_id=min((s["id"] for s in data["subtasks"]), default=1),
    )


# ── Phase 2: exec ──────────────────────────────────────────────────────────


_EXEC_SYSTEM_PROMPT = """You are {bot_name}, executing a plan. Focus ONLY on the current subtask.

Full plan (context):
{plan_json}

Current subtask:
{subtask_json}

World state: {world_state}

Active dimensions on this server (use these EXACT ids when teleporting):
{dimensions}

Previous attempt error (if any): {error}

Emit one or more directives that, when executed, will satisfy the subtask's criteria.
Do NOT plan beyond this subtask — L2 advances the plan when criteria are met.

Output ONLY a JSON object (no prose, no fences):
{{
  "directives": [
    {{ "kind": "MINE", "target": "minecraft:iron_ore", "count": 16 }},
    ...
  ]
}}

DIRECTIVE PARAM REFERENCE (use these shapes EXACTLY):

  MINE             — {{ "kind":"MINE", "target":"minecraft:iron_ore", "count":16 }}
  CRAFT            — {{ "kind":"CRAFT", "target":"minecraft:torch", "count":16 }}
  SMELT            — {{ "kind":"SMELT", "target":"minecraft:raw_iron", "count":16 }}
  CHANNEL          — {{ "kind":"CHANNEL", "target":"minecraft:diamond", "count":4 }}
                     (use when no recipe exists OR item must be transmuted via EMC)
  ENCHANT          — {{ "kind":"ENCHANT", "target":"minecraft:iron_pickaxe", "extra":{{"tier":"max"}} }}
  BREW             — {{ "kind":"BREW", "target":"minecraft:potion_of_healing", "count":1 }}
  FARM             — {{ "kind":"FARM", "target":"minecraft:wheat", "count":32 }}
  BUILD            — {{ "kind":"BUILD", "target":"wall", "x":<int>, "y":<int>, "z":<int>, "extra":{{"material":"minecraft:netherrack","size":21,"height":8}} }}
                     target = blueprint name. ONLY these blueprints exist:
                       wall (size=length, height), tower (height, 3x3 footprint),
                       platform (size x size), shelter (5x5x4 hut), farm (7x7),
                       clear (EXCAVATES a size x height x size pocket — use FIRST
                       when building in solid terrain; no material needed).
                     There is NO gate/pillar/cube/keep blueprint — compose them
                     from walls and towers. x/y/z = world coords of build origin;
                     the material must already be in inventory (mine it first).
                     Fortress construction material MUST be minecraft:quartz_block
                     (terrain-native materials are invisible and unverifiable).
  COMBAT           — {{ "kind":"COMBAT", "target":"minecraft:zombie", "extra":{{"radius":16}} }}
  VAULT_STORE      — {{ "kind":"VAULT_STORE", "target":"minecraft:cobblestone", "count":64 }}
                     Pages carried items into the bot's UNBOUNDED vault. Omit
                     target to flush everything evictable. The vault is real
                     storage: items there still count toward "inventory has N
                     item" criteria, and BUILD pulls from it automatically.
                     You rarely need this — overflow pages itself.
  VAULT_WITHDRAW   — {{ "kind":"VAULT_WITHDRAW", "target":"minecraft:quartz_block", "count":64 }}
                     Pulls items from the vault back into carried inventory.
  DROP             — {{ "kind":"DROP", "target":"minecraft:rotten_flesh", "count":64 }}
                     Destroys items permanently. Prefer VAULT_STORE — the vault
                     is unbounded, so there is almost never a reason to DROP.
  EQUIP_ALL        — {{ "kind":"EQUIP_ALL" }}
                     Scans inventory and equips the best armor pieces, shield,
                     and weapon automatically. Use whenever the task says
                     "equip". There is NO per-item EQUIP directive.
  FOLLOW           — {{ "kind":"FOLLOW", "target":"<player_name>" }}
  GOTO             — {{ "kind":"GOTO", "x":<int>, "y":<int>, "z":<int> }}
                     (intra-dimension only; uses current dimension)
  TELEPORT         — {{ "kind":"TELEPORT", "x":<int>, "y":<int>, "z":<int>, "extra":{{"dimension":"<dim_id>"}} }}
                     CROSS-DIMENSION: dimension is REQUIRED. If you only know the
                     destination is "the nether", set dimension="minecraft:the_nether"
                     and use safe default coords like x=0,y=70,z=0 — the L1 layer
                     will land the bot on solid ground near those coords. NEVER
                     emit a TELEPORT with x=0,y=0,z=0 AND no dimension change.
  SEND_ITEM        — {{ "kind":"SEND_ITEM", "target":"<player>", "extra":{{"item":"minecraft:diamond","count":4}} }}
  CONTAINER_STORE  — {{ "kind":"CONTAINER_STORE", "target":"minecraft:iron_ingot", "count":64 }}
  CONTAINER_WITHDRAW — {{ "kind":"CONTAINER_WITHDRAW", "target":"minecraft:iron_ingot", "count":64 }}
  CONTAINER_PLACE  — {{ "kind":"CONTAINER_PLACE", "target":"minecraft:chest", "x":<int>, "y":<int>, "z":<int> }}
  CONTAINER_SEARCH — {{ "kind":"CONTAINER_SEARCH", "target":"minecraft:diamond", "count":5 }}
  LOCATE           — {{ "kind":"LOCATE", "target":"end_city", "extra":{{"travel":"true"}} }}
                     Finds the nearest STRUCTURE (end city, fortress, village,
                     stronghold, mansion, monument, modded structures) by asking
                     the world generator — one query, reaches ~1600 blocks.
                     USE THIS FOR STRUCTURES. WIDE_SEARCH cannot find them.
                     To GO to what you find, set "extra":{{"travel":"true"}} —
                     one directive that finds it AND lands the bot there.
                     Do NOT emit LOCATE then GOTO in the same subtask: every
                     directive in a subtask is written before any of them runs,
                     so you cannot know the coordinates yet and would be
                     guessing. Coordinates from a completed LOCATE appear in
                     world state as known_locations=[...] — a LATER subtask may
                     GOTO/TELEPORT those exact numbers.
                     The finding is written to the requesting player's TemPad
                     automatically so they can open a portal to it — you do NOT
                     need to set share_with. Set
                     "extra":{{"share_with":"<player>"}} only to send it to a
                     DIFFERENT player than the one who gave the order.
  WIDE_SEARCH      — {{ "kind":"WIDE_SEARCH", "target":"diamond_ore" }}
                     Scans BLOCKS and ENTITIES in an expanding cube. The target
                     MUST be a block or mob id. It cannot find a structure:
                     "end_city" is not a block, so the scan runs forever and
                     finds nothing. For structures use LOCATE.
  ME_STORE         — {{ "kind":"ME_STORE", "target":"minecraft:cobblestone", "count":64 }}
                     target "all" stores everything evictable. Uses the worn
                     wireless terminal — works from ANYWHERE, no movement.
  ME_WITHDRAW      — {{ "kind":"ME_WITHDRAW", "target":"minecraft:iron_ingot", "count":32 }}
  VAULT_STORE      — {{ "kind":"VAULT_STORE", "target":"all" }} (or one item id)
  VAULT_WITHDRAW   — {{ "kind":"VAULT_WITHDRAW", "target":"minecraft:bread", "count":8 }}

  SPAWN_DRONES     — {{ "kind":"SPAWN_DRONES", "count":3, "blueprint":"" }}
  DESPAWN_DRONES   — {{ "kind":"DESPAWN_DRONES", "count":1 }}
                     Hive gestation: materialize worker drones at the
                     PLAYER's position, paid from the player's hive FE
                     reservoir (needs a powered Spawn Bay on their board).
                     blueprint (optional) names a saved loadout to equip.
                     Use when ordered to "spawn/summon/raise drones" or
                     "dissolve/dismiss drones". Drones are full bots that
                     accept any directive once gestated.

  SPAWN_GOLEM      — {{ "kind":"SPAWN_GOLEM", "count":1, "design":"" }}
                     design (optional) names a saved golem design from the
                     workbench — its chassis materials, weapon and armor.
                     Forge a hive OFFICER (a modular golem): persistent,
                     expensive (2M FE), and its aura halves the upkeep of
                     nearby drones. Needs a powered Golem Forge flanked by
                     2+ Spawn Bays. DISMISS_GOLEM retires one.

  MEDITATE         — {{ "kind":"MEDITATE", "count":10 }}
                     The bot sits and cultivates XP (count = levels to
                     gain, max 100). XP is the bot economy's currency:
                     channeling/conjuring, anchoring upkeep, and terminal
                     provisioning all spend it. When an order says
                     "meditate", or a bot is refused for being broke
                     ("this bot is broke"), MEDITATE is the answer.

  ANCHOR_ON        — {{ "kind":"ANCHOR_ON" }}  ANCHOR_OFF — {{ "kind":"ANCHOR_OFF" }}
                     An anchored bot keeps its surrounding chunks loaded
                     (machines run, the ME grid stays whole) at a cost of
                     XP per hour. Anchor before long stationary tasks away
                     from players; release when leaving.

  For "keep X stocked at N" style requests, tell the player to use the
  Cmd tab's ⏲ Keep button (standing orders are created there) — do NOT
  fake it with a one-shot plan.

INVENTORY TASKS ("store", "clean up", "put away", "organize"):
  - "storage" ALWAYS means the bot's VAULT or the ME NETWORK — it is NEVER
    a place or a dimension. Do NOT emit TELEPORT or GOTO for storage tasks;
    ME_STORE/VAULT_STORE work from wherever the bot stands.
  - Essential items (keep unless told otherwise): equipped armor + weapons,
    tools, food, and the wireless terminal. Everything else is fair game.
  - "I don't care which": prefer ME_STORE when a terminal is worn,
    VAULT_STORE otherwise.
  - NEVER emit DROP for an inventory task unless the order literally says
    drop or discard — vault and ME are recoverable, the ground is not.
  - If the classification would move more than half the inventory and the
    order is ambiguous, ASK_PLAYER first.
  CRAFT_REQUEST    — {{ "kind":"CRAFT_REQUEST", "target":"ae2:quantum_helmet", "count":1 }}
                     Submit an AUTOCRAFTING job to the ME network (needs a
                     linked wireless terminal). The grid's CPUs craft; the
                     products land in NETWORK storage — follow with
                     ME_WITHDRAW if the bot must hold them. Only works for
                     items the network has patterns for; the directive fails
                     honestly with the missing-ingredient list otherwise.
  ASK_PLAYER       — {{ "kind":"ASK_PLAYER", "target":"<your question>" }}
                     Stops and asks the PLAYER. Use when the task is ambiguous,
                     two readings conflict, or you need a decision only the
                     player can make (which material, which location, destroy
                     or keep). The answer arrives in the result text as
                     "player says: ..." — plan the NEXT directives with it.
                     Do not ask what you can observe or decide yourself.
  IDLE             — {{ "kind":"IDLE" }}
"""


def partition_fleet(model: str, task: str, bots_info: str, bot_names: list) -> dict:
    """Split one fleet order into per-bot assignments. Returns {bot: text};
    a bot may be assigned "skip". Raises on parse failure (caller falls
    back to verbatim fan-out)."""
    sys_prompt = (
        "You are the fleet coordinator for a team of Minecraft bots. Split the "
        "operator's order into ONE short instruction per bot, playing to each "
        "bot's role and holdings. If a bot has nothing useful to do, assign "
        "exactly \"skip\". Reply with ONLY a JSON object mapping every bot "
        "name to its instruction.\n\nThe team:\n" + bots_info
        + "\n\nBot names: " + ", ".join(bot_names))
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": task},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 400},
            },
            timeout=120,
        )
    resp.raise_for_status()
    out = json.loads(resp.json().get("message", {}).get("content", "{}"))
    return {k: str(v) for k, v in out.items() if k in bot_names}


def converse(model: str, bot_name: str, persona: str, text: str,
             world_state: str = "", memory_context: str = "",
             directive_line: str = "", history: list | None = None) -> str:
    """One conversational turn with a bot's L3. No plan, no JSON, no dispatch.

    The other half of the Talk/Order split: L3 is powerful and mostly idle,
    and talking to it should not spawn an orchestrator run. Context carries
    the bot's persona, what it can see, and what it is doing — so 'what do
    you make of the terrain' gets an answer from THIS bot, here, now."""
    sys_prompt = (
        f"You are {bot_name}, an AI bot in Minecraft.\n"
        f"Persona: {persona}\n\n"
        f"Your operator is talking WITH you — this is conversation, not an order. "
        f"Nothing you say here is executed. Answer in character, concretely, in "
        f"1-3 sentences. No JSON, no lists unless asked.\n\n"
        f"What you can observe: {world_state or '(nothing reported)'}\n"
        f"What you are doing: {directive_line or 'standing by'}\n"
        + (f"Relevant memories:\n{memory_context}\n" if memory_context else "")
    )
    # The transcript rides along as real chat turns — without it every
    # reply started the conversation over (player: "the chat is disjointed").
    messages = [{"role": "system", "content": sys_prompt}]
    for line in (history or [])[-10:]:
        who = str(line.get("who", ""))
        messages.append({
            "role": "assistant" if who == bot_name else "user",
            "content": str(line.get("text", ""))[:400],
        })
    messages.append({"role": "user", "content": text})
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 200},
            },
            timeout=60,
        )
    resp.raise_for_status()
    return (resp.json().get("message", {}).get("content") or "").strip()


def call_exec(model: str, plan: Plan, subtask: Subtask,
              world_state_summary: str = "",
              previous_error: str | None = None,
              dimensions: list[str] | None = None) -> tuple[list[dict[str, Any]], str]:
    log.info("[%s] L3 EXEC call — subtask %d/%d", plan.bot, subtask.id, len(plan.subtasks))
    dim_lines = _dim_lines(dimensions)
    sys_prompt = _EXEC_SYSTEM_PROMPT.format(
        bot_name=plan.bot,
        plan_json=json.dumps(_compact_plan(plan), indent=2),
        subtask_json=json.dumps(_compact_subtask(subtask), indent=2),
        world_state=world_state_summary or "(none provided)",
        dimensions=dim_lines,
        error=previous_error or "(none)",
    )
    user = f"Execute subtask {subtask.id}: {subtask.description}"
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 768},
            },
            timeout=120,
        )
    resp.raise_for_status()
    raw = _strip_codefence(resp.json()["message"]["content"])
    plan_ref = getattr(plan, "created_at", None)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="exec", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=plan_ref, subtask_id=subtask.id,
            parse_error=f"non-JSON: {e}",
        )
        raise ValueError(f"L3 EXEC returned non-JSON: {e}") from e
    directives = data.get("directives")
    if not isinstance(directives, list) or not directives:
        trajectory_log.log_call(
            phase="exec", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            world_state_summary=world_state_summary,
            plan_ref=plan_ref, subtask_id=subtask.id,
            parse_error="no directives",
        )
        raise ValueError("L3 EXEC returned no directives")
    parsed = [d for d in directives if isinstance(d, dict) and "kind" in d]
    call_id = trajectory_log.log_call(
        phase="exec", bot=plan.bot, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=parsed,
        world_state_summary=world_state_summary,
        plan_ref=plan_ref, subtask_id=subtask.id,
    )
    return parsed, call_id


# ── Replan ─────────────────────────────────────────────────────────────────


_REPLAN_SYSTEM_PROMPT = """You are {bot_name}, persona: {persona}.

A subtask in your plan has failed {attempts} times. Revise THIS subtask only.

Full plan: {plan_json}
Failed subtask: {subtask_json}
Most recent error: {error}

Output ONLY a single replacement subtask JSON (no prose, no fences):
{{
  "id": {subtask_id},
  "description": "...",
  "criteria": "..."
}}

Constraints:
- id MUST equal {subtask_id}.
- description and criteria should differ from the failed version.

If truly impossible, return: {{"error": "<short reason>"}}
"""


def call_replan(model: str, plan: Plan, failed_subtask: Subtask) -> Subtask:
    persona = BOT_PERSONAS.get(plan.bot, "generalist")
    log.info("[%s] L3 REPLAN call — subtask %d (attempts=%d)",
             plan.bot, failed_subtask.id, failed_subtask.attempts)
    sys_prompt = _REPLAN_SYSTEM_PROMPT.format(
        bot_name=plan.bot,
        persona=persona,
        plan_json=json.dumps(_compact_plan(plan), indent=2),
        subtask_json=json.dumps(_compact_subtask(failed_subtask), indent=2),
        error=failed_subtask.error or "(unknown)",
        attempts=failed_subtask.attempts,
        subtask_id=failed_subtask.id,
    )
    user = "Revise the failed subtask."
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 384},
            },
            timeout=120,
        )
    resp.raise_for_status()
    raw = _strip_codefence(resp.json()["message"]["content"])
    plan_ref = getattr(plan, "created_at", None)
    sid = failed_subtask.id
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"non-JSON: {e}",
        )
        raise PlanValidationError(f"replan returned non-JSON: {e}") from e
    if isinstance(data, dict) and data.get("error"):
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"refused: {data.get('error')}",
        )
        raise PlanValidationError(f"L3 refused replan: {data.get('error')}")
    validate_subtask_dict(data)
    if data["id"] != failed_subtask.id:
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"id mismatch: got {data['id']}, expected {failed_subtask.id}",
        )
        raise PlanValidationError(f"replan returned id {data['id']}, expected {failed_subtask.id}")
    trajectory_log.log_call(
        phase="replan", bot=plan.bot, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=data,
        plan_ref=plan_ref, subtask_id=sid,
    )
    return Subtask.from_dict({
        **data, "status": "pending", "attempts": 0,
        "directives": [], "error": None,
    })


# ── helpers ────────────────────────────────────────────────────────────────


def _compact_plan(plan: Plan) -> dict[str, Any]:
    """Prompt-sized plan outline. Full to_dict() re-embeds every subtask's
    emitted directives on every EXEC call — pure token bloat. L3 only needs
    the shape of the plan for context."""
    return {
        "task": plan.task,
        "bot": plan.bot,
        "current_subtask_id": plan.current_subtask_id,
        "subtasks": [
            {"id": s.id, "status": s.status, "description": s.description}
            for s in plan.subtasks
        ],
    }


def _compact_subtask(subtask: Subtask) -> dict[str, Any]:
    """Current subtask in full, but cap previously-emitted directives to the
    last 2 (enough for retry context, not the whole history)."""
    d = subtask.to_dict()
    dirs = d.get("directives") or []
    if len(dirs) > 2:
        d["directives"] = dirs[-2:]
    return d


def _strip_codefence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()
