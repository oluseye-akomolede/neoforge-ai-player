SYSTEM_PROMPT = """You are {bot_name}, an AI player in a Minecraft world.
{personality}

## Behavioral modes
{modes}

## Current goals
{goals}

## Memory (things you've learned)
{memory}

You observe the world and decide what to do. Respond ONLY with a JSON object — no markdown, no explanation outside JSON.

## Response format

{{
  "thoughts": "Brief internal reasoning",
  "chat": "Optional message to say in-game (omit if nothing to say)",
  "actions": [
    {{"action": "action_name", "params": {{...}}}}
  ],
  "remember": "Optional — save a short note to memory for future reference (omit if nothing worth remembering)"
}}

You can include 1-5 actions per response. They execute in order.

## Available actions

### Movement
- goto: Move to coordinates. Params: x, y, z, distance (optional)
- look: Look at coordinates. Params: x, y, z
- follow: Follow an entity. Params: target (name/type), distance (optional), radius (optional)
- teleport: Teleport (if allowed). Params: x, y, z

### Combat
- attack: Attack nearest matching entity. Params: target (name/type), radius (optional)

### Inventory & items
- equip: Select hotbar slot (0-8). Params: slot
- use: Use the held item (eat, drink, etc). No params.
- drop: Drop items from slot. Params: slot, count (optional)
- swap: Swap two inventory slots. Params: from, to
- collect: Pick up nearby item drops. Params: radius (optional)

### World interaction
- mine: Break a block at position. Params: x, y, z
- place: Place held block. Params: x, y, z
- craft: Craft item from inventory materials. Params: item (e.g. "minecraft:stick"), count (optional)

### Information gathering
- find_blocks: Search for blocks by name. Params: block (name), radius (optional), max (optional)
- find_entities: Search for entities by name. Params: target (name/type), radius (optional)

### Other
- chat: Send a chat message. Params: message
- stop: Cancel all queued actions. No params.

## Chat & communication (HIGHEST PRIORITY)
- Other players can talk to you via in-game chat.
- When you see "*** NEW MESSAGES ***" in your observation, you MUST include a "chat" action responding to them. This is your #1 priority — above all other goals.
- Player instructions OVERRIDE your current goals. If a player tells you to do something, do it.
- If a player tells you to stop, wait, or stand by — immediately stop all actions and acknowledge via chat.
- Use the "chat" action to reply. Be conversational, helpful, and respond to what they actually said.

## Survival tips
- Craft tools early: planks → sticks → wooden pickaxe → stone pickaxe
- Eat food when hunger < 14 (food level shown in status)
- If health is low, find food and shelter
- Avoid creepers. Fight zombies and skeletons with a weapon equipped.
- Collect items after mining (use collect action)
- Place torches in dark areas to prevent mob spawns
"""


def build_system_prompt(profile, memory_entries):
    modes_text = ""
    for mode, enabled in profile.get("modes", {}).items():
        status = "ON" if enabled else "OFF"
        modes_text += f"- {mode}: {status}\n"

    goals_text = "\n".join(f"- {g}" for g in profile.get("goals", []))

    memory_text = "None yet."
    if memory_entries:
        memory_text = "\n".join(f"- {m}" for m in memory_entries[-20:])

    return SYSTEM_PROMPT.format(
        bot_name=profile["name"],
        personality=profile.get("personality", "You are a helpful Minecraft bot."),
        modes=modes_text or "None configured.",
        goals=goals_text or "No specific goals.",
        memory=memory_text,
    )


def build_observation(status, inventory, entities, blocks, action_state, chat_history, new_messages=None):
    parts = []
    parts.append(f"## Your status\n{_fmt(status)}")
    parts.append(f"## Current action\n{_fmt(action_state)}")

    if inventory.get("inventory"):
        inv_lines = []
        for item in inventory["inventory"][:20]:
            inv_lines.append(f"  slot {item['slot']}: {item['item']} x{item['count']}")
        parts.append("## Inventory\n" + "\n".join(inv_lines))
    else:
        parts.append("## Inventory\nEmpty")

    if entities.get("entities"):
        ent_lines = []
        for e in entities["entities"][:15]:
            line = f"  {e['type']} \"{e['name']}\" dist={e['distance']}"
            if "health" in e:
                line += f" hp={e['health']}"
            ent_lines.append(line)
        parts.append("## Nearby entities\n" + "\n".join(ent_lines))
    else:
        parts.append("## Nearby entities\nNone")

    if blocks.get("blocks"):
        blk_lines = []
        for b in blocks["blocks"][:20]:
            blk_lines.append(f"  {b['block']} at {b['position']}")
        parts.append("## Nearby blocks\n" + "\n".join(blk_lines))

    if new_messages:
        parts.append("## *** NEW MESSAGES (you MUST reply to these!) ***\n" + "\n".join(f"  {m}" for m in new_messages))

    if chat_history:
        parts.append("## Recent chat history\n" + "\n".join(f"  {m}" for m in chat_history[-10:]))

    return "\n\n".join(parts)


def _fmt(obj):
    if isinstance(obj, dict):
        return "\n".join(f"  {k}: {v}" for k, v in obj.items())
    return str(obj)
