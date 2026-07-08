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

Constraints:
- Output ONLY JSON. No prose. No markdown fences.
- 1 to 6 subtasks. Break larger jobs into multiple submissions instead.
- Each subtask should map to 1-3 directives maximum.
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
    dim_lines = "\n".join(f"  - {d}" for d in (dimensions or _DEFAULT_DIMENSIONS))
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
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlanValidationError(f"L3 PLAN returned non-JSON: {e}") from e
    validate_plan_dict(data)
    return Plan(
        task=data["task"],
        bot=bot_name,
        created_at=datetime.datetime.utcnow().isoformat(),
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
  BUILD            — {{ "kind":"BUILD", "x":<int>, "y":<int>, "z":<int>, "extra":{{"shape":"platform","material":"minecraft:oak_planks","size":5}} }}
  COMBAT           — {{ "kind":"COMBAT", "target":"minecraft:zombie", "extra":{{"radius":16}} }}
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
  WIDE_SEARCH      — {{ "kind":"WIDE_SEARCH", "target":"village" }}
  IDLE             — {{ "kind":"IDLE" }}
"""


def call_exec(model: str, plan: Plan, subtask: Subtask,
              world_state_summary: str = "",
              previous_error: str | None = None,
              dimensions: list[str] | None = None) -> list[dict[str, Any]]:
    log.info("[%s] L3 EXEC call — subtask %d/%d", plan.bot, subtask.id, len(plan.subtasks))
    dim_lines = "\n".join(f"  - {d}" for d in (dimensions or _DEFAULT_DIMENSIONS))
    sys_prompt = _EXEC_SYSTEM_PROMPT.format(
        bot_name=plan.bot,
        plan_json=json.dumps(_compact_plan(plan), indent=2),
        subtask_json=json.dumps(_compact_subtask(subtask), indent=2),
        world_state=world_state_summary or "(none provided)",
        dimensions=dim_lines,
        error=previous_error or "(none)",
    )
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Execute subtask {subtask.id}: {subtask.description}"},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 768},
            },
            timeout=120,
        )
    resp.raise_for_status()
    raw = _strip_codefence(resp.json()["message"]["content"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"L3 EXEC returned non-JSON: {e}") from e
    directives = data.get("directives")
    if not isinstance(directives, list) or not directives:
        raise ValueError("L3 EXEC returned no directives")
    return [d for d in directives if isinstance(d, dict) and "kind" in d]


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
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": "Revise the failed subtask."},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 384},
            },
            timeout=120,
        )
    resp.raise_for_status()
    raw = _strip_codefence(resp.json()["message"]["content"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlanValidationError(f"replan returned non-JSON: {e}") from e
    if isinstance(data, dict) and data.get("error"):
        raise PlanValidationError(f"L3 refused replan: {data.get('error')}")
    validate_subtask_dict(data)
    if data["id"] != failed_subtask.id:
        raise PlanValidationError(f"replan returned id {data['id']}, expected {failed_subtask.id}")
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
