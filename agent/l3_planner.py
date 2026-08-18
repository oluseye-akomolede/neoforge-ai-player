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
import time
from typing import Any

import requests

import api
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

# Single HTTP timeout for every L3 ollama call. 32b (19 GB) cold-loads in ~5m
# on the V100 pair — llama-server startup + CUDA-graph capture across the
# tensor-parallel split dominates, not the weight copy. 120s used to abort the
# load mid-flight on the first call after a pod restart (the agent's read
# timeout closed the connection, which cancelled the in-progress load). 420s
# rides out a full cold start; warm calls are unaffected.
_OLLAMA_TIMEOUT = 420.0


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


# ── Skill catalog (v10) ─────────────────────────────────────────────────────

_skills_cache: tuple[float, str] | None = None
_SKILLS_CACHE_TTL = 60.0


def _skills_lines() -> str:
    """Render the registered skill catalog from GET /skills, cached briefly.

    The catalog is server-global and changes only via runtime self-expansion,
    so a short TTL avoids a GET per subtask while still picking up new skills.
    Returns "" when the API is unreachable (L3 still emits raw directives)."""
    global _skills_cache
    now = time.monotonic()
    if _skills_cache is not None and now - _skills_cache[0] < _SKILLS_CACHE_TTL:
        return _skills_cache[1]
    text = ""
    try:
        entries = (api.skills() or {}).get("skills") or []
        lines = []
        for s in entries:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "?"))
            desc = str(s.get("description", "") or "").strip()
            params = s.get("params") or {}
            param_str = (", ".join(f"{k}:{v}" for k, v in params.items())
                         if isinstance(params, dict) else "")
            line = f"    {sid}"
            if desc:
                line += f" — {desc}"
            if param_str:
                line += f"  [params: {param_str}]"
            lines.append(line)
        text = "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — best-effort enrichment
        log.debug("skills fetch failed: %s", e)
    _skills_cache = (now, text)
    return text


# ── Post-EXEC skill collapse (deterministic backstop) ──────────────────────
#
# L3 is asked to prefer SKILL, but a small model may still hand-decompose a
# skill-covered subtask into its raw directive sequence. This backstop detects
# that case and collapses the raw sequence into a single SKILL directive, so the
# v10 "skills first, directives fallback" contract holds regardless of model
# behavior. It is deliberately conservative:
#   - Only the five curated seed skills are matched (their kind signature + param
#     names are fixed here; self-expanded skills fall through to their raw
#     directives, which is always safe).
#   - The match is an EXACT kind-sequence match (order + kinds). Any same-shape
#     raw pair is re-routed to the skill, but a bad param is caught by the
#     skill's verify predicate and the orchestrator retries/replans.

# seed skill id -> (ordered directive kind signature, param names to extract)
_SEED_SKILLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "mine_and_smelt": (("MINE", "SMELT"), ("target", "count")),
    "goto_and_scan": (("TELEPORT", "WIDE_SEARCH"), ("x", "y", "z", "target")),
    "search_and_loot": (("AREA_LOOT", "STORE_ALL"), ("x", "y", "z", "radius")),
    "harvest_and_store": (("FARM", "STORE_ALL"), ("crop", "count")),
    "resupply_network": (("CHANNEL", "SEND_ITEM"), ("item", "count", "to")),
    "summon_vehicle": (("REQUISITION", "MOUNT_VEHICLE"), ("vehicle",)),
    "channel_gun": (("CHANNEL",), ("gun",)),
}


def _build_skill_extra(param_names, directives: list[dict]) -> dict[str, str]:
    """Map raw directives back onto a skill's param names. Conservative: a param
    it cannot map is omitted (the skill's own verify predicate catches a bad run)."""
    def find(*kinds: str):
        for d in directives:
            if str(d.get("kind", "")).upper() in kinds:
                return d
        return None

    extra: dict[str, str] = {}
    for name in param_names:
        n = str(name).lower()
        if n == "count":
            for d in directives:
                if d.get("count") is not None:
                    extra[name] = str(d["count"])
                    break
        elif n == "target":
            # first directive that actually carries a target (MINE for
            # mine_and_smelt; WIDE_SEARCH for goto_and_scan whose TELEPORT has none)
            for d in directives:
                if d.get("target"):
                    extra[name] = str(d["target"])
                    break
        elif n == "smelt":
            d = find("SMELT")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "item":
            d = find("CHANNEL", "SEND_ITEM", "CONTAINER_SEARCH", "CONTAINER_WITHDRAW")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "crop":
            d = find("FARM")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "to":
            d = find("SEND_ITEM")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n in ("x", "y", "z"):
            d = find("TELEPORT", "GOTO", "AREA_LOOT")
            extra[name] = str(d.get(n, "")) if d else ""
        elif n == "radius":
            d = find("AREA_LOOT", "WIDE_SEARCH")
            extra[name] = str(d.get("radius", "")) if d else ""
        # unknown param name -> omitted (SkillParams leaves ${name} visible)
    return extra


# DirectiveType enum (mod) — the kinds a declarative skill leaf may use. The
# shim refuses to synthesize a skill from any kind outside this set: EQUIP_ALL,
# EQUIP, DROP, VAULT_STORE/WITHDRAW, PROVISION_TERMINAL and ASK_PLAYER are
# agent-side conveniences, not mod directives, and would fail SkillValidator.
_VALID_DIRECTIVE_KINDS = frozenset({
    "MINE", "GATHER", "GOTO", "FOLLOW", "COMBAT", "CRAFT", "SMELT", "ENCHANT",
    "BREW", "CHANNEL", "SEND_ITEM", "BUILD", "FARM", "CONTAINER_PLACE",
    "CONTAINER_SEARCH", "CONTAINER_STORE", "CONTAINER_WITHDRAW", "TELEPORT",
    "IDLE", "PATROL", "WIDE_SEARCH", "LOCATE", "STORE_ALL", "ME_STORE",
    "ME_WITHDRAW", "CRAFT_REQUEST", "MEDITATE", "CULTIVATE",
    "MOUNT_VEHICLE", "DISMOUNT_VEHICLE", "DRIVE_VEHICLE", "REQUISITION",
})

# Valid kinds that are nonetheless context-specific (a hardcoded coordinate,
# a named structure, a followed/patrolled target) — a frozen skill replaying
# them verbatim is wrong, so the shim will not synthesize from them.
_NON_REUSABLE_KINDS = frozenset({
    "TELEPORT", "GOTO", "LOCATE", "PATROL", "FOLLOW", "BUILD", "IDLE",
    "DRIVE_VEHICLE",
})


def _directive_to_node(d: dict) -> dict:
    """One raw L3 directive → a declarative DIRECTIVE leaf. Numeric fields are
    stringified: SkillNode.parse reads leaves as strings, SkillBehavior re-parses
    at execution time."""
    node = {"type": "directive", "kind": str(d.get("kind", "")).upper()}
    for field in ("target", "count", "radius", "x", "y", "z"):
        v = d.get(field)
        if v is not None and str(v) != "":
            node[field] = str(v)
    extra = d.get("extra")
    if isinstance(extra, dict) and extra:
        node["extra"] = {k: str(v) for k, v in extra.items()}
    return node


def _synthesize_skill(directives: list[dict], kinds: tuple[str, ...]) -> dict | None:
    """Deterministic self-expansion: a bounded (2-3 leaf) sequence of valid,
    reusable directive kinds that matches NO seed is a routine L3 hand-expanded
    instead of proposing. Synthesize an inline SKILL for it (register:true) so
    the mod validates + registers it and a future identical task reuses it.

    Frozen, not parameterized: leaf targets/counts are baked in. Deliberate —
    the shim learns the exact routine it just ran, never an over-generalized
    one. Returns None when the sequence is not a candidate."""
    if len(directives) not in (2, 3):
        return None
    if any(k not in _VALID_DIRECTIVE_KINDS for k in kinds):
        return None
    if any(k in _NON_REUSABLE_KINDS for k in kinds):
        return None
    skill_id = "gen_" + "_".join(k.lower() for k in kinds)
    tree = {"type": "sequence", "children": [_directive_to_node(d) for d in directives]}
    log.info("skill-synthesize: %s -> %s (register)", kinds, skill_id)
    return {"kind": "SKILL", "target": skill_id,
            "extra": {"spec": tree, "register": True}}


def _collapse_to_skill(directives: list[dict]) -> list[dict]:
    """Collapse a raw directive sequence into a single SKILL directive: an exact
    seed match re-routes to that seed, otherwise a bounded reusable no-seed
    sequence is synthesized inline (register:true). Returns the input unchanged
    when neither applies."""
    if not directives:
        return directives
    kinds = tuple(str(d.get("kind", "")).upper() for d in directives)
    if "SKILL" in kinds:
        return directives  # already skill-directed
    for skill_id, (signature, param_names) in _SEED_SKILLS.items():
        if kinds == signature:
            extra = _build_skill_extra(param_names, directives)
            log.info("skill-collapse: %s -> SKILL %s (extra=%r)", kinds, skill_id, extra)
            return [{"kind": "SKILL", "target": skill_id, "extra": extra}]
    synthesized = _synthesize_skill(directives, kinds)
    if synthesized is not None:
        return [synthesized]
    return directives


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

Registered skills (each runs end-to-end as ONE deterministic directive):
{skills}

When a registered skill above covers the ENTIRE task, plan exactly ONE subtask
for it: set the description to "Run skill <skill_id> with <param>=<value>, ..."
and the criteria to what that skill verifies (e.g. "inventory has 8
minecraft:iron_ingot"). Do NOT split a skill-covered task into its component
directives — the skill already sequences them. Fall back to raw subtasks only
when no skill fits.

When NO skill covers the task but the task is a bounded, reusable multi-step
routine (2-3 directive kinds in a fixed order, e.g. "equip then fight"), plan a
SINGLE subtask for the whole routine — do NOT split it into one-directive
subtasks. The exec layer can then synthesize a NEW skill for it inline. Split
into separate subtasks only when the steps are independent goals, not one routine.

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
        bot_name=bot_name, persona=persona, dimensions=dim_lines,
        skills=_skills_lines())
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
            timeout=_OLLAMA_TIMEOUT,
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

SKILL REFERENCE (registered skills — pick one when it covers the subtask):
{skills}

FIRST, check the SKILL REFERENCE above. If a registered skill covers this entire
subtask end-to-end, emit exactly ONE directive of kind SKILL — do NOT hand-expand
the skill into its raw directive sequence. Skills are deterministic and
post-verified against world state, so a matching skill is always the better choice.

A skill covers a subtask ONLY when EVERY step in its description applies — never
just one. Each seed skill is a fixed two-step routine (e.g. "mine THEN smelt",
"farm THEN store", "conjure THEN send"). If the subtask asks for only ONE of
those steps, or pairs a step with a DIFFERENT second step (e.g. "mine then
store", "craft then store", "conjure then keep"), the skill does NOT cover it —
hand-expand the raw directives instead. Never drop or rename a step the subtask
requires just to fit a skill, and never repurpose a skill's parameter (e.g. a
"crop" slot is for crops, not planks or ingots).

Worked example — subtask "mine 8 iron ore and smelt into ingots" is covered by the
mine_and_smelt skill, so emit:
{{
  "directives": [
    {{ "kind": "SKILL", "target": "mine_and_smelt", "extra": {{ "target": "minecraft:iron_ore", "count": "8" }} }}
  ]
}}

RAW DIRECTIVE REFERENCE (fallback — use ONLY when NO skill above covers the subtask):

  MINE             — {{ "kind":"MINE", "target":"minecraft:iron_ore", "count":16 }}
  CRAFT            — {{ "kind":"CRAFT", "target":"minecraft:torch", "count":16 }}
  SMELT            — {{ "kind":"SMELT", "target":"minecraft:raw_iron", "count":16 }}
  CHANNEL          — {{ "kind":"CHANNEL", "target":"minecraft:diamond", "count":4 }}
                     (use when no recipe exists OR item must be transmuted via EMC)
                     GUNS: TaCZ guns are ONE item — never channel
                     tacz:modern_kinetic_gun; the target is the GUN ID
                     (tacz:ak47, tacz:m4a1 …) and Superb Warfare guns are
                     their item id (superbwarfare:hk_416). Prefer SKILL
                     channel_gun (gun + ammo) and SKILL channel_ammo
                     (target "ammo" = rounds for the gun the bot holds).
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

  MOUNT_VEHICLE    — {{ "kind":"MOUNT_VEHICLE", "target":"tank", "extra":{{"seat":"0","role":"driver"}} }}
                     Board a Superb Warfare vehicle: target = a vehicle name/
                     type substring ("tank","lav","m1a2","ah6","boat") or empty
                     for the nearest within radius (default 32). Seat 0 is the
                     driver; role "gunner" takes the first armed passenger
                     seat. Once aboard, COMBAT fights FROM the vehicle (turret
                     aims and fires; a driver closes to weapon range — land,
                     boat and helicopter only; airplanes can be gunned, not
                     flown). Vehicles need FE energy and ammo in their hold —
                     the hive charges them from the owner's reservoir.
                     VEHICLES CANNOT BE FOUND BY WIDE_SEARCH OR LOCATE — they
                     are entities, not blocks or structures. If no vehicle is
                     nearby, use SKILL summon_vehicle (hive units only; the
                     owner's FE reservoir pays; the skill mounts it too). A bot
                     with no hive owner cannot summon — say so instead of
                     searching for one.
  REQUISITION      — {{ "kind":"REQUISITION", "target":"vehicle:lav_150" }} or an item id + count
                     Ask the hive to materialize something for FE and wait for
                     it (vehicle arrives repaired + charged, 3 blocks ahead).
                     Prefer SKILL summon_vehicle, which requisitions AND mounts.
  DISMOUNT_VEHICLE — {{ "kind":"DISMOUNT_VEHICLE" }}
  DRIVE_VEHICLE    — {{ "kind":"DRIVE_VEHICLE", "x":<int>, "y":<int>, "z":<int>, "count":120 }}
                     Drive the vehicle you pilot to a point (or "target":
                     "<player or entity>" to follow it). Only from the driver
                     seat; count = max seconds. Land/boat/helicopter only.

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

SKILL PROPOSAL (fallback — only when NO registered skill above covers the subtask
AND the subtask is a bounded, reusable sequence of the directive kinds listed
above): you MAY synthesize a NEW skill inline instead of hand-expanding it. Emit
exactly ONE directive of kind SKILL whose extra carries a declarative "spec" (an
object, not a string) plus "register": true:
{{
  "directives": [
    {{ "kind": "SKILL", "target": "equip_and_fight", "extra": {{
      "spec": {{ "type": "sequence", "children": [
        {{ "type": "directive", "kind": "EQUIP_ALL" }},
        {{ "type": "directive", "kind": "COMBAT", "target": "minecraft:zombie", "extra": {{ "radius": 16 }} }}
      ] }},
      "register": true
    }} }}
  ]
}}
Constraints: spec leaves MUST use only the directive kinds listed above; a "loop"
node MUST set "max_iterations"; never "skill-ref" the skill to itself. The mod
validates the spec and rejects anything invalid — a rejection is safe, just retry
as raw directives. Propose a new skill ONLY for a reusable pattern; a one-off
subtask is fine as raw directives.
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
            timeout=_OLLAMA_TIMEOUT,
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
        skills=_skills_lines(),
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
            timeout=_OLLAMA_TIMEOUT,
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
    parsed = _collapse_to_skill(parsed)
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
            timeout=_OLLAMA_TIMEOUT,
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


_REFINE_SKILL_PROMPT = """You are {bot_name}, an AI bot in Minecraft.

You proposed a NEW declarative skill (a SKILL directive carrying an inline
"spec"), but the mod's deterministic validator REJECTED it. Fix ONLY the spec
so it validates. Do not change the skill's intent.

Rejected spec (JSON):
{spec_json}

Validator error:
{error}

Correct SkillSpec contract (a single JSON object):
{{
  "id": "<skill_id>",
  "nodes": {{ <one root node> }}
}}

Node grammar (type → required fields):
  "sequence" / "fallback" → "children": [node, ...]
  "loop" → "body": node, "max_iterations": N (N must be > 0), optional "while"
  "if" → "condition": str, "then": node, optional "else": node
  "skill" (reference an existing skill) → "ref": "<skill_id>"
  "directive" (leaf) → "kind": one of {valid_kinds}, optional
      "target"/"count"/"radius"/"x"/"y"/"z"/"extra" (all strings)

Rules the validator enforces:
  - a "loop" MUST set max_iterations > 0 (never 0 or missing)
  - a "directive" leaf MUST set a valid "kind"
  - never reference the skill itself ("skill" with ref == its own id)
  - any "${{name}}" in nodes must be declared in the top-level "params" map

Output ONLY the corrected spec as a JSON object (no prose, no fences), or:
{{"error": "<why it cannot be fixed>"}}
"""


def refine_skill(model: str, bot_name: str, spec: str, error: str) -> dict | None:
    """Feed a validator rejection back to L3 to fix an inline skill spec.

    Returns the corrected spec dict (with "id" + "nodes"), or None if L3
    gives up or returns non-JSON. The caller re-wraps via _repair_directive.
    """
    sys_prompt = _REFINE_SKILL_PROMPT.format(
        bot_name=bot_name,
        spec_json=spec,
        error=error,
        valid_kinds=", ".join(sorted(_VALID_DIRECTIVE_KINDS)),
    )
    user = "Fix the rejected skill spec."
    log.info("[%s] L3 REFINE-SKILL call — error: %s", bot_name, error[:120])
    try:
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
                timeout=_OLLAMA_TIMEOUT,
            )
        resp.raise_for_status()
    except Exception as e:
        log.warning("[%s] refine_skill call failed: %s", bot_name, e)
        return None
    raw = _strip_codefence(resp.json()["message"]["content"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("[%s] refine_skill returned non-JSON: %s", bot_name, e)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") and "id" not in data:
        log.info("[%s] L3 gave up on skill spec: %s", bot_name, data.get("error"))
        return None
    return data


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
