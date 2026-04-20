"""
Interaction sessions — constrained state machines that funnel the LLM
into a narrow action set for multi-step tasks like container interaction
and crafting.

The agent enters a session via an LLM action (e.g. open_container, craft_plan).
While in a session, the agent swaps the system prompt to a session-specific one
with only valid actions, then loops until the LLM says "done" or a max iteration
cap is hit.
"""

import json
import api
import brain

MAX_SESSION_ROUNDS = 6


class Session:
    """Base class for interaction sessions."""

    def __init__(self, bot_name, model):
        self.bot_name = bot_name
        self.model = model
        self.history = []
        self.results = []
        self.round = 0

    def prompt(self):
        raise NotImplementedError

    def observation(self):
        raise NotImplementedError

    def execute(self, response):
        raise NotImplementedError

    def is_done(self):
        return self.round >= MAX_SESSION_ROUNDS

    def run(self):
        while not self.is_done():
            self.round += 1
            obs = self.observation()
            sys_prompt = self.prompt()
            response = brain.think(self.model, sys_prompt, obs, self.history)

            thoughts = response.get("thoughts", "")
            print(f"  [{self.bot_name}/session] round {self.round}: {thoughts}")

            self.history.append({"role": "user", "content": obs})
            self.history.append({"role": "assistant", "content": json.dumps(response)})

            done = self.execute(response)
            if done:
                break

        return self.results


class ContainerSession(Session):
    """
    Constrainted session for container (chest/barrel/crate) interaction.

    Flow:
    1. Agent reads container contents and bot inventory automatically
    2. LLM sees both lists, picks from: take, deposit, equip, done
    3. Repeats until done or max rounds
    """

    def __init__(self, bot_name, model, x, y, z, instruction=""):
        super().__init__(bot_name, model)
        self.x = x
        self.y = y
        self.z = z
        self.instruction = instruction
        self._done = False

    def prompt(self):
        goal = ""
        if self.instruction:
            goal = f"\n## Player's instruction\n{self.instruction}\n"
        return f"""You are interacting with a container at ({self.x}, {self.y}, {self.z}).
{goal}
Your DEFAULT behavior: take ALL items from the container and equip any armor/weapons.
Only deposit items if the player specifically asked you to store something.

Respond ONLY with a JSON object:

{{
  "thoughts": "Brief reasoning about what to take/deposit/equip",
  "chat": "Optional message to say in-game",
  "actions": [
    {{"action": "action_name", "params": {{...}}}}
  ]
}}

## Available actions (ONLY these — nothing else)

- take: Take an item from the container. Params: item (registry ID from the container list, e.g. "minecraft:diamond_sword"), count (optional, default all)
- deposit: Put an item from your inventory into the container. Params: item (registry ID from your inventory, e.g. "minecraft:cobblestone"), count (optional, default all)
- equip: Equip an item that is already in your inventory (you must take it first!). Params: item (registry ID, e.g. "minecraft:iron_chestplate"). Armor goes to the correct slot automatically.
- done: Finished with this container. No params.

## Rules
- Use registry IDs exactly as shown in the lists below (e.g. "minecraft:diamond_sword", NOT "Diamond Sword")
- You can include multiple actions per response (e.g. take + take + equip in one round)
- To equip something from the container: FIRST take it, THEN equip it (in the next round)
- Call "done" when you have taken/equipped everything you need
- NEVER deposit items unless the player specifically asked you to store something
- If unsure what to do, take everything and equip armor/weapons
"""

    def observation(self):
        container_items = api.container(self.bot_name, self.x, self.y, self.z)
        inv = api.inventory(self.bot_name)

        parts = []

        items = container_items.get("items", [])
        if items:
            lines = []
            for item in items:
                lines.append(f"  {item['item']} \"{item.get('name', '')}\" x{item['count']}")
            parts.append("## Container contents\n" + "\n".join(lines))
        else:
            parts.append("## Container contents\nEmpty")

        if inv.get("inventory"):
            inv_lines = []
            for item in inv["inventory"][:20]:
                inv_lines.append(f"  slot {item['slot']}: {item['item']} x{item['count']}")
            parts.append("## Your inventory\n" + "\n".join(inv_lines))
        else:
            parts.append("## Your inventory\nEmpty")

        if self.results:
            parts.append("## Previous results\n" + "\n".join(f"  {r}" for r in self.results[-5:]))

        return "\n\n".join(parts)

    def execute(self, response):
        actions = response.get("actions", [])
        for act in actions:
            name = act.get("action", "")
            params = act.get("params", {})

            if name == "done":
                self._done = True
                self.results.append("Session complete")
                return True

            elif name == "take":
                item_id = params.get("item", "")
                count = params.get("count", 64)
                resp = api.container_extract(
                    self.bot_name, self.x, self.y, self.z,
                    item=item_id, count=count
                )
                error = resp.get("error") if isinstance(resp, dict) else None
                if error:
                    self.results.append(f"FAILED take {item_id}: {error}")
                    print(f"  [{self.bot_name}/session] take {item_id}: FAILED {error}")
                else:
                    extracted = resp.get("count", 0)
                    self.results.append(f"OK took {item_id} x{extracted}")
                    print(f"  [{self.bot_name}/session] take {item_id} x{extracted}: ok")

            elif name == "deposit":
                item_id = params.get("item", "")
                count = params.get("count", 64)
                inv = api.inventory(self.bot_name)
                slot = None
                for entry in inv.get("inventory", []):
                    if entry["item"] == item_id:
                        slot = entry["slot"]
                        break
                if slot is None:
                    self.results.append(f"FAILED deposit {item_id}: not in inventory")
                    print(f"  [{self.bot_name}/session] deposit {item_id}: not in inventory")
                else:
                    resp = api.container_insert(
                        self.bot_name, self.x, self.y, self.z, slot, count
                    )
                    error = resp.get("error") if isinstance(resp, dict) else None
                    if error:
                        self.results.append(f"FAILED deposit {item_id}: {error}")
                        print(f"  [{self.bot_name}/session] deposit {item_id}: FAILED {error}")
                    else:
                        self.results.append(f"OK deposited {item_id}")
                        print(f"  [{self.bot_name}/session] deposit {item_id}: ok")

            elif name == "equip":
                item_id = params.get("item", "")
                inv = api.inventory(self.bot_name)
                slot = None
                for entry in inv.get("inventory", []):
                    if entry["item"] == item_id:
                        slot = entry["slot"]
                        break
                if slot is None:
                    self.results.append(f"FAILED equip {item_id}: not in inventory")
                    print(f"  [{self.bot_name}/session] equip {item_id}: not in inventory")
                else:
                    resp = api.equip(self.bot_name, slot)
                    error = resp.get("error") if isinstance(resp, dict) else None
                    if error:
                        self.results.append(f"FAILED equip {item_id}: {error}")
                        print(f"  [{self.bot_name}/session] equip {item_id}: FAILED {error}")
                    else:
                        self.results.append(f"OK equipped {item_id}")
                        print(f"  [{self.bot_name}/session] equip {item_id}: ok")

            else:
                self.results.append(f"Unknown session action: {name}")

        chat_msg = response.get("chat")
        if chat_msg:
            api.chat(self.bot_name, chat_msg)

        return False

    def is_done(self):
        return self._done or super().is_done()


class CraftSession(Session):
    """
    Constrained session for crafting.

    Flow:
    1. LLM specifies what it wants to craft
    2. Agent shows available recipes matching the request + current inventory
    3. LLM picks: craft, craft_chain, or done
    4. Repeats until done or max rounds
    """

    def __init__(self, bot_name, model, goal=""):
        super().__init__(bot_name, model)
        self.goal = goal
        self._done = False

    def prompt(self):
        return f"""You are in crafting mode. Your goal: {self.goal or "Craft whatever is needed."}

You can see matching recipes and your inventory below. Choose what to craft.

Respond ONLY with a JSON object:

{{
  "thoughts": "Brief reasoning about what to craft",
  "chat": "Optional message to say in-game",
  "actions": [
    {{"action": "action_name", "params": {{...}}}}
  ]
}}

## Available actions (ONLY these — nothing else)

- search: Search for crafting recipes. Params: filter (search term, e.g. "pickaxe"), craftable_only (optional, true to only show recipes you can craft now)
- craft: Craft a single recipe (ingredients must be in inventory). Params: item (registry ID, e.g. "minecraft:stick"), count (optional, default 1)
- craft_chain: Craft with automatic dependency resolution (e.g. logs → planks → sticks → pickaxe). Params: item (registry ID), count (optional, default 1)
- equip: Equip a crafted item from your inventory. Params: item (registry ID)
- done: Finished crafting. No params.

## Rules
- Use registry IDs exactly as shown (e.g. "minecraft:stone_pickaxe", NOT "Stone Pickaxe")
- Use "search" first if you're not sure of the exact registry ID
- Use "craft_chain" when you need intermediate materials crafted automatically
- Call "done" when you're finished crafting
"""

    def observation(self):
        inv = api.inventory(self.bot_name)
        parts = []

        if inv.get("inventory"):
            inv_lines = []
            for item in inv["inventory"][:20]:
                inv_lines.append(f"  slot {item['slot']}: {item['item']} x{item['count']}")
            parts.append("## Your inventory\n" + "\n".join(inv_lines))
        else:
            parts.append("## Your inventory\nEmpty")

        if self.results:
            parts.append("## Previous results\n" + "\n".join(f"  {r}" for r in self.results[-5:]))

        return "\n\n".join(parts)

    def execute(self, response):
        actions = response.get("actions", [])
        for act in actions:
            name = act.get("action", "")
            params = act.get("params", {})

            if name == "done":
                self._done = True
                self.results.append("Crafting session complete")
                return True

            elif name == "search":
                filter_str = params.get("filter", "")
                craftable_only = params.get("craftable_only", False)
                resp = api.list_recipes(self.bot_name, filter_str, craftable_only)
                recipes = resp.get("recipes", [])
                if recipes:
                    lines = []
                    for r in recipes[:15]:
                        ings = ", ".join(r.get("ingredients", []))
                        item_id = r.get("output") or r.get("item", "?")
                        count = r.get("output_count") or r.get("count", 1)
                        lines.append(f"  {item_id} x{count} <- {ings}")
                    self.results.append(f"Found {len(recipes)} recipe(s):\n" + "\n".join(lines))
                    print(f"  [{self.bot_name}/session] search '{filter_str}': {len(recipes)} recipes")
                else:
                    self.results.append(f"No recipes found for '{filter_str}'")
                    print(f"  [{self.bot_name}/session] search '{filter_str}': none found")

            elif name == "craft":
                item_id = params.get("item", "")
                count = params.get("count", 1)
                resp = api.craft(self.bot_name, item_id, count)
                error = resp.get("error") if isinstance(resp, dict) else None
                if error:
                    self.results.append(f"FAILED craft {item_id}: {error}")
                    print(f"  [{self.bot_name}/session] craft {item_id}: FAILED {error}")
                else:
                    self.results.append(f"OK crafted {item_id} x{count}")
                    print(f"  [{self.bot_name}/session] craft {item_id} x{count}: ok")

            elif name == "craft_chain":
                item_id = params.get("item", "")
                count = params.get("count", 1)
                resp = api.craft_chain(self.bot_name, item_id, count)
                error = resp.get("error") if isinstance(resp, dict) else None
                if error:
                    self.results.append(f"FAILED craft_chain {item_id}: {error}")
                    print(f"  [{self.bot_name}/session] craft_chain {item_id}: FAILED {error}")
                else:
                    self.results.append(f"OK craft_chain {item_id} x{count} (queued)")
                    print(f"  [{self.bot_name}/session] craft_chain {item_id} x{count}: ok")

            elif name == "equip":
                item_id = params.get("item", "")
                inv = api.inventory(self.bot_name)
                slot = None
                for entry in inv.get("inventory", []):
                    if entry["item"] == item_id:
                        slot = entry["slot"]
                        break
                if slot is None:
                    self.results.append(f"FAILED equip {item_id}: not in inventory")
                    print(f"  [{self.bot_name}/session] equip {item_id}: not in inventory")
                else:
                    resp = api.equip(self.bot_name, slot)
                    error = resp.get("error") if isinstance(resp, dict) else None
                    if error:
                        self.results.append(f"FAILED equip {item_id}: {error}")
                        print(f"  [{self.bot_name}/session] equip {item_id}: FAILED {error}")
                    else:
                        self.results.append(f"OK equipped {item_id}")
                        print(f"  [{self.bot_name}/session] equip {item_id}: ok")

            else:
                self.results.append(f"Unknown session action: {name}")

        chat_msg = response.get("chat")
        if chat_msg:
            api.chat(self.bot_name, chat_msg)

        return False

    def is_done(self):
        return self._done or super().is_done()
