"""
Task planner — decomposes a player instruction into numbered steps.

Uses a one-shot LLM call with a tight structured prompt to produce
a short JSON list of steps. The executor then works through them
one at a time.
"""

import json
import requests
from config import OLLAMA_URL
import brain

PLANNER_PROMPT = """You are a Minecraft task planner. Break the player's instruction into simple, sequential steps that a bot can execute one at a time.

## How to decompose

IF the player gives explicit numbered steps or a clear sequence (e.g. "do X then Y then Z"):
- Preserve their steps exactly. Do NOT merge, split, or reorder them.
- You may add missing prerequisites (e.g. "craft a pickaxe" implies gathering wood/stone first).

IF the player gives a vague or high-level goal (e.g. "get me iron gear" or "set up a base"):
- Reason about what Minecraft actions are needed and produce concrete steps.
- Think about prerequisites: what materials are needed? What tools are required first?

## Rules
- Each step = ONE concrete action: mine, craft, find, go to, place, build, collect, smelt, etc.
- Use Minecraft registry IDs where possible (e.g. "minecraft:stone_pickaxe" not "stone pickaxe")
- Keep steps short (under 15 words each)
- 1-8 steps maximum
- Do NOT include "equip" as a separate step — the bot auto-equips after crafting
- "collect" after mining is automatic — don't add separate collect steps
- If the instruction is already a single action, output just one step
- NEVER say "go to Y=N" — the bot cannot teleport to a Y level. Say "dig a staircase down to Y=N" instead
- For underground tasks, always say "dig down" or "mine downward" — the bot must physically dig, not use goto
- Do NOT re-delegate or assign work to other bots — just describe what YOU need to do
- If YOU need a crafted/conjured item in YOUR inventory, YOU must craft/conjure it yourself — items cannot transfer between bots

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

## Examples

Input: "Craft a stone pickaxe, mine coal, build a furnace"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:coal_ore", "Craft and place minecraft:furnace"]}}

Input: "Get me a full set of iron armor"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:iron_ore (at least 24)", "Craft minecraft:furnace and place it", "Smelt minecraft:raw_iron into minecraft:iron_ingot", "Craft minecraft:iron_helmet", "Craft minecraft:iron_chestplate", "Craft minecraft:iron_leggings", "Craft minecraft:iron_boots"]}}

Input: "Go chop some trees"
Output: {{"steps": ["Find and mine nearby logs (minecraft:oak_log or minecraft:birch_log)"]}}

Input: "Help me get diamonds"
Output: {{"steps": ["Craft minecraft:stone_pickaxe", "Find and mine minecraft:iron_ore", "Craft and place minecraft:furnace", "Smelt minecraft:raw_iron into minecraft:iron_ingot", "Craft minecraft:iron_pickaxe", "Dig down to Y=16 or below", "Find and mine minecraft:diamond_ore"]}}

{memory_section}

Respond ONLY with a JSON object:
{{
  "steps": ["step 1", "step 2", ...]
}}"""


def decompose(model, instruction, memory_context=""):
    """Break an instruction into a list of step strings."""
    memory_section = ""
    if memory_context and memory_context != "No relevant memories.":
        memory_section = f"## Relevant memories from past experience\n{memory_context}\n\nUse these memories to make better plans. Avoid repeating past mistakes."

    prompt = PLANNER_PROMPT.format(memory_section=memory_section)

    with brain.ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
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
    content = resp.json()["message"]["content"]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
        else:
            return [instruction]

    steps = parsed.get("steps", [])
    if not steps or not isinstance(steps, list):
        return [instruction]

    return [str(s) for s in steps[:8]]


# ── Orchestrator: specialization-aware decomposition ──

ORCHESTRATOR_PROMPT = """You are a Minecraft task orchestrator. Break the player's instruction into steps AND assign each step to the best-suited bot based on their specializations.

## Available bots
{bot_list}

## Rules
- Each step = ONE concrete action: mine, craft, find, go to, place, build, collect, smelt, etc.
- Use Minecraft registry IDs where possible (e.g. "minecraft:stone_pickaxe")
- Keep steps short (under 15 words each)
- 1-8 steps maximum
- Assign each step to the bot whose specialization best matches
- If no bot is a great fit, use "any"
- Steps assigned to different bots can potentially run in parallel
- Steps for the SAME bot run sequentially
- NEVER say "go to Y=N" — say "dig a staircase down to Y=N" instead (bots must physically dig)
- Each step must be self-contained — the assigned bot will execute it alone without help
- NEVER delegate crafting if the orchestrating bot needs the crafted item in its OWN inventory. Crafted items stay in the crafter's inventory — they cannot be transferred between bots. If YOU need the result, do it yourself.
- Similarly, do NOT delegate conjure, smelt, or any action where the product must end up in a specific bot's inventory
- If bot A crafts something that bot B needs, add a "send_item" step: bot A sends the item to bot B (works at any distance, across dimensions)
- For "come to me" or "go to player" commands, EVERY bot should use goto_player — do NOT decompose navigation into mining/crafting steps
- Use "goto_waypoint" to send bots to saved locations

## Minecraft knowledge
- Diamonds are found below Y=16, require minecraft:iron_pickaxe or better
- Iron ore requires minecraft:stone_pickaxe or better. Smelt in furnace for ingots
- Furnace recipe: 8x minecraft:cobblestone in a ring
- Tools progression: wood -> stone -> iron -> diamond -> netherite

{memory_section}

Respond ONLY with a JSON object:
{{
  "steps": [
    {{"step": "description", "assign": "bot_name_or_any", "specialization": "mining/building/crafting/combat/gathering/any"}}
  ]
}}"""


def orchestrate(model, instruction, bot_profiles, memory_context=""):
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

    prompt = ORCHESTRATOR_PROMPT.format(
        bot_list=bot_list,
        memory_section=memory_section,
    )

    with brain.ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
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
    content = resp.json()["message"]["content"]

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
    for s in steps[:8]:
        if isinstance(s, dict):
            result.append({
                "step": str(s.get("step", "")),
                "assign": str(s.get("assign", "any")),
                "specialization": str(s.get("specialization", "any")),
            })
        else:
            result.append({"step": str(s), "assign": "any", "specialization": "any"})
    return result
