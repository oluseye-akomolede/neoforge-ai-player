"""
Pydantic models for the dashboard REST/WebSocket API.
"""

from pydantic import BaseModel
from typing import Optional


class CommandRequest(BaseModel):
    bot: str
    message: str


class DirectiveRequest(BaseModel):
    bot: str
    directive_type: str
    target: Optional[str] = None
    count: Optional[int] = None
    radius: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    extra: Optional[dict] = None


class BroadcastRequest(BaseModel):
    message: str


class WaypointRequest(BaseModel):
    name: str
    x: float
    y: float
    z: float
    dimension: Optional[str] = "minecraft:overworld"
    set_by: Optional[str] = "dashboard"


class WaypointDeleteRequest(BaseModel):
    name: str


DIRECTIVE_CATALOG = [
    {
        "type": "MINE",
        "label": "Mine",
        "params": [
            {"name": "target", "type": "string", "label": "Block type", "required": True,
             "options": ["diamond_ore", "iron_ore", "gold_ore", "coal_ore", "copper_ore",
                         "lapis_ore", "redstone_ore", "emerald_ore", "ancient_debris",
                         "stone", "deepslate", "cobblestone", "oak_log", "birch_log",
                         "spruce_log", "dark_oak_log", "jungle_log", "acacia_log",
                         "sand", "gravel", "clay", "dirt", "obsidian"]},
            {"name": "count", "type": "int", "label": "Count", "required": False, "default": 64},
        ],
    },
    {
        "type": "CRAFT",
        "label": "Craft",
        "params": [
            {"name": "target", "type": "string", "label": "Item", "required": True,
             "options": ["crafting_table", "furnace", "chest", "stick", "planks",
                         "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe",
                         "wooden_sword", "stone_sword", "iron_sword", "diamond_sword",
                         "wooden_axe", "stone_axe", "iron_axe", "diamond_axe",
                         "wooden_shovel", "stone_shovel", "iron_shovel", "diamond_shovel",
                         "torch", "iron_ingot", "gold_ingot", "bucket", "shield",
                         "iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots",
                         "diamond_helmet", "diamond_chestplate", "diamond_leggings", "diamond_boots",
                         "bow", "arrow", "bread", "cake", "rail", "powered_rail"]},
            {"name": "count", "type": "int", "label": "Count", "required": False, "default": 1},
        ],
    },
    {
        "type": "SMELT",
        "label": "Smelt",
        "params": [
            {"name": "target", "type": "string", "label": "Item to smelt", "required": True,
             "options": ["raw_iron", "raw_gold", "raw_copper", "cobblestone", "sand",
                         "clay_ball", "cactus", "kelp", "wet_sponge", "netherrack",
                         "ancient_debris"]},
            {"name": "count", "type": "int", "label": "Count", "required": False, "default": 1},
        ],
    },
    {
        "type": "CHANNEL",
        "label": "Channel (Meditate + Conjure)",
        "params": [
            {"name": "target", "type": "string", "label": "Item to conjure", "required": True},
            {"name": "count", "type": "int", "label": "Count", "required": False, "default": 1},
        ],
    },
    {
        "type": "FOLLOW",
        "label": "Follow",
        "params": [
            {"name": "target", "type": "string", "label": "Player/bot name", "required": True},
            {"name": "radius", "type": "float", "label": "Max range", "required": False, "default": 32.0},
        ],
    },
    {
        "type": "GOTO",
        "label": "Go To",
        "params": [
            {"name": "x", "type": "float", "label": "X", "required": True},
            {"name": "y", "type": "float", "label": "Y", "required": True},
            {"name": "z", "type": "float", "label": "Z", "required": True},
        ],
    },
    {
        "type": "TELEPORT",
        "label": "Teleport",
        "params": [
            {"name": "x", "type": "float", "label": "X", "required": True},
            {"name": "y", "type": "float", "label": "Y", "required": True},
            {"name": "z", "type": "float", "label": "Z", "required": True},
            {"name": "extra", "type": "dimension", "label": "Dimension", "required": False,
             "options": ["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"]},
        ],
    },
    {
        "type": "COMBAT",
        "label": "Combat Mode",
        "params": [
            {"name": "target", "type": "string", "label": "Target type", "required": False,
             "options": ["hostile", "zombie", "skeleton", "creeper", "spider",
                         "enderman", "blaze", "wither_skeleton", "piglin", "player"]},
            {"name": "radius", "type": "float", "label": "Radius", "required": False, "default": 24.0},
        ],
    },
    {
        "type": "FARM",
        "label": "Farm",
        "params": [
            {"name": "target", "type": "string", "label": "Crop type", "required": True,
             "options": ["wheat", "carrots", "potatoes", "beetroots", "melon",
                         "pumpkin", "sugar_cane", "bamboo", "nether_wart", "cocoa"]},
        ],
    },
    {
        "type": "BUILD",
        "label": "Build",
        "params": [
            {"name": "target", "type": "string", "label": "Structure type", "required": True},
            {"name": "x", "type": "float", "label": "X", "required": False},
            {"name": "y", "type": "float", "label": "Y", "required": False},
            {"name": "z", "type": "float", "label": "Z", "required": False},
        ],
    },
    {
        "type": "SEND_ITEM",
        "label": "Send Item",
        "params": [
            {"name": "target", "type": "string", "label": "Recipient bot", "required": True},
            {"name": "extra", "type": "dict", "label": "Item/slot", "required": False},
        ],
    },
    {
        "type": "ENCHANT",
        "label": "Enchant",
        "description": "Apply a specific enchantment to an item using XP. Select an enchantment from the registry or leave blank for random.",
        "params": [
            {"name": "target", "type": "string", "label": "Item (name or slot #)",
             "hint": "Item to enchant — searched in inventory by name", "required": False},
            {"name": "extra", "type": "dict", "label": "Enchantment", "required": False,
             "fields": [
                 {"name": "enchantment", "type": "string", "label": "Enchantment",
                  "hint": "Leave blank for random enchantment"},
                 {"name": "level", "type": "string", "label": "Level",
                  "hint": "Enchantment level (default: max)"},
                 {"name": "option", "type": "string", "label": "Random tier (if no enchantment selected)",
                  "options": ["0", "1", "2"],
                  "option_labels": ["Basic (1-8)", "Mid (9-20)", "Max (21-30)"],
                  "default": "2"},
             ]},
        ],
    },
    {
        "type": "BREW",
        "label": "Brew Potion",
        "params": [
            {"name": "target", "type": "string", "label": "Potion type", "required": True,
             "options": ["healing", "regeneration", "strength", "swiftness", "night_vision",
                         "invisibility", "fire_resistance", "water_breathing", "leaping",
                         "slow_falling", "poison", "weakness", "slowness", "harming",
                         "turtle_master"]},
            {"name": "count", "type": "int", "label": "Count (1-3)", "required": False, "default": 3},
        ],
    },
    {
        "type": "WIDE_SEARCH",
        "label": "Wide Search",
        "description": "Expanding-cube search that scans outward from a center point. "
                       "Multiple bots can divide the area into a checkerboard grid for parallel searching.",
        "params": [
            {"name": "target", "type": "string", "label": "Search target",
             "hint": "Block or entity name (e.g. diamond_ore, cow). Fuzzy matching and ore variants supported.",
             "required": True},
            {"name": "x", "type": "float", "label": "Center X", "required": True,
             "hint": "X coordinate of the search center", "use_bot_pos": True},
            {"name": "y", "type": "float", "label": "Center Y", "required": True,
             "hint": "Y coordinate of the search center", "use_bot_pos": True},
            {"name": "z", "type": "float", "label": "Center Z", "required": True,
             "hint": "Z coordinate of the search center", "use_bot_pos": True},
            {"name": "extra", "type": "dict", "label": "Search settings", "required": False,
             "fields": [
                 {"name": "search_type", "type": "string", "label": "Search for",
                  "options": ["block", "entity"],
                  "option_labels": ["Block (scans terrain)", "Entity (scans mobs/animals)"],
                  "default": "block"},
                 {"name": "radius", "type": "string", "label": "Max search radius",
                  "options": ["64", "128", "256", "512", "1024"],
                  "option_labels": ["64 blocks (small)", "128 blocks", "256 blocks", "512 blocks (default)", "1024 blocks (large)"],
                  "default": "512"},
                 {"name": "bot_index", "type": "string", "label": "This bot's index",
                  "hint": "Which slice of the grid this bot searches (0 = first bot)",
                  "options": ["0", "1", "2", "3", "4"],
                  "option_labels": ["0 (first)", "1 (second)", "2 (third)", "3 (fourth)", "4 (fifth)"],
                  "default": "0"},
                 {"name": "bot_count", "type": "string", "label": "Total bots searching",
                  "hint": "How many bots are searching in parallel (each gets a grid slice)",
                  "options": ["1", "2", "3", "4", "5"],
                  "option_labels": ["1 (solo)", "2 bots", "3 bots", "4 bots", "5 bots"],
                  "default": "1"},
             ]},
        ],
    },
    {
        "type": "CONTAINER_PLACE",
        "label": "Place Container",
        "params": [
            {"name": "target", "type": "string", "label": "Label (optional)", "required": False},
        ],
    },
    {
        "type": "CONTAINER_STORE",
        "label": "Store in Container",
        "params": [
            {"name": "target", "type": "string", "label": "Item to store", "required": True},
            {"name": "count", "type": "int", "label": "Count", "required": False, "default": 64},
            {"name": "x", "type": "float", "label": "X", "required": False},
            {"name": "y", "type": "float", "label": "Y", "required": False},
            {"name": "z", "type": "float", "label": "Z", "required": False},
        ],
    },
    {
        "type": "CONTAINER_WITHDRAW",
        "label": "Withdraw from Container",
        "params": [
            {"name": "target", "type": "string", "label": "Item to withdraw", "required": False},
            {"name": "x", "type": "float", "label": "X", "required": False},
            {"name": "y", "type": "float", "label": "Y", "required": False},
            {"name": "z", "type": "float", "label": "Z", "required": False},
        ],
    },
]
