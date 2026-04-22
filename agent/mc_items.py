"""
Canonical Minecraft vanilla item/block names for L3 primitive validation.

L3 (LLM) generates primitives with item names that may be hallucinated or
use wrong IDs. This module provides a whitelist of valid names so we can
reject or correct bad output before it reaches L1.
"""

# Blocks that can be mined
MINEABLE_BLOCKS = frozenset({
    # Stone variants
    "stone", "cobblestone", "deepslate", "cobbled_deepslate",
    "granite", "diorite", "andesite", "tuff", "calcite",
    "smooth_stone", "stone_bricks", "mossy_stone_bricks",
    "cracked_stone_bricks", "chiseled_stone_bricks",
    # Ores
    "coal_ore", "iron_ore", "copper_ore", "gold_ore", "diamond_ore",
    "emerald_ore", "lapis_ore", "redstone_ore",
    "deepslate_coal_ore", "deepslate_iron_ore", "deepslate_copper_ore",
    "deepslate_gold_ore", "deepslate_diamond_ore", "deepslate_emerald_ore",
    "deepslate_lapis_ore", "deepslate_redstone_ore",
    "nether_gold_ore", "nether_quartz_ore", "ancient_debris",
    # Wood
    "oak_log", "birch_log", "spruce_log", "jungle_log",
    "acacia_log", "dark_oak_log", "cherry_log", "mangrove_log",
    "oak_planks", "birch_planks", "spruce_planks", "jungle_planks",
    "acacia_planks", "dark_oak_planks", "cherry_planks", "mangrove_planks",
    "bamboo_planks", "crimson_planks", "warped_planks",
    "crimson_stem", "warped_stem",
    # Dirt/sand
    "dirt", "grass_block", "sand", "red_sand", "gravel",
    "clay", "mud", "soul_sand", "soul_soil",
    "sandstone", "red_sandstone",
    # Plant
    "sugar_cane", "cactus", "bamboo", "kelp", "melon",
    "pumpkin", "hay_block",
    # Misc
    "obsidian", "crying_obsidian", "netherrack", "end_stone",
    "basalt", "blackstone", "glowstone", "ice", "packed_ice", "blue_ice",
    "terracotta", "prismarine", "sea_lantern",
    "moss_block", "dripstone_block",
})

# Items that can be crafted (minecraft: prefix)
CRAFTABLE_ITEMS = frozenset({
    # Tools
    "wooden_pickaxe", "wooden_axe", "wooden_shovel", "wooden_hoe", "wooden_sword",
    "stone_pickaxe", "stone_axe", "stone_shovel", "stone_hoe", "stone_sword",
    "iron_pickaxe", "iron_axe", "iron_shovel", "iron_hoe", "iron_sword",
    "golden_pickaxe", "golden_axe", "golden_shovel", "golden_hoe", "golden_sword",
    "diamond_pickaxe", "diamond_axe", "diamond_shovel", "diamond_hoe", "diamond_sword",
    "netherite_pickaxe", "netherite_axe", "netherite_shovel", "netherite_hoe", "netherite_sword",
    "shears", "flint_and_steel", "fishing_rod", "bow", "crossbow",
    "shield", "spyglass", "brush",
    # Armor
    "leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots",
    "iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots",
    "golden_helmet", "golden_chestplate", "golden_leggings", "golden_boots",
    "diamond_helmet", "diamond_chestplate", "diamond_leggings", "diamond_boots",
    "netherite_helmet", "netherite_chestplate", "netherite_leggings", "netherite_boots",
    "chainmail_helmet", "chainmail_chestplate", "chainmail_leggings", "chainmail_boots",
    "turtle_helmet",
    # Building blocks
    "crafting_table", "furnace", "blast_furnace", "smoker",
    "chest", "barrel", "trapped_chest", "ender_chest",
    "anvil", "smithing_table", "grindstone", "stonecutter",
    "loom", "cartography_table", "fletching_table",
    "composter", "brewing_stand", "cauldron", "lectern",
    "enchanting_table", "bookshelf", "lantern", "soul_lantern",
    "torch", "soul_torch", "campfire", "soul_campfire",
    "ladder", "scaffolding",
    # Basic materials
    "stick", "oak_planks", "birch_planks", "spruce_planks",
    "jungle_planks", "acacia_planks", "dark_oak_planks",
    "cherry_planks", "mangrove_planks", "bamboo_planks",
    "iron_ingot", "gold_ingot", "copper_ingot", "netherite_ingot",
    "iron_nugget", "gold_nugget",
    "iron_block", "gold_block", "diamond_block", "emerald_block",
    "copper_block", "netherite_block", "coal_block", "lapis_block",
    "redstone_block",
    "brick", "nether_brick",
    "glass", "glass_pane",
    "paper", "book", "writable_book",
    "bowl", "bucket", "water_bucket", "lava_bucket",
    "charcoal", "coal",
    "string", "leather",
    # Redstone
    "redstone_torch", "repeater", "comparator",
    "piston", "sticky_piston", "observer", "dropper", "dispenser",
    "hopper", "lever", "tripwire_hook",
    "daylight_detector", "target",
    # Rails
    "rail", "powered_rail", "detector_rail", "activator_rail",
    "minecart", "chest_minecart", "hopper_minecart",
    # Transport
    "oak_boat", "birch_boat", "spruce_boat",
    # Food
    "bread", "cake", "cookie", "pumpkin_pie", "golden_apple",
    "mushroom_stew", "rabbit_stew", "beetroot_soup",
    "golden_carrot", "fermented_spider_eye",
    # Dyes
    "white_dye", "orange_dye", "magenta_dye", "light_blue_dye",
    "yellow_dye", "lime_dye", "pink_dye", "gray_dye",
    "light_gray_dye", "cyan_dye", "purple_dye", "blue_dye",
    "brown_dye", "green_dye", "red_dye", "black_dye",
    # Wool & concrete
    "white_wool", "white_concrete", "white_concrete_powder",
    # Misc craft
    "map", "compass", "clock", "name_tag",
    "lead", "saddle", "armor_stand",
    "item_frame", "painting", "flower_pot",
    "sign", "oak_sign", "birch_sign", "spruce_sign",
    "oak_door", "birch_door", "spruce_door", "iron_door",
    "oak_fence", "birch_fence", "spruce_fence",
    "oak_fence_gate", "birch_fence_gate", "spruce_fence_gate",
    "oak_stairs", "birch_stairs", "spruce_stairs",
    "cobblestone_stairs", "stone_brick_stairs",
    "oak_slab", "birch_slab", "spruce_slab",
    "cobblestone_slab", "stone_brick_slab", "smooth_stone_slab",
    "cobblestone_wall", "stone_brick_wall",
    "tnt", "bed", "white_bed",
})

# Items that can be smelted
SMELTABLE_ITEMS = frozenset({
    "raw_iron", "raw_gold", "raw_copper",
    "iron_ore", "gold_ore", "copper_ore",
    "deepslate_iron_ore", "deepslate_gold_ore", "deepslate_copper_ore",
    "cobblestone", "sand", "clay_ball",
    "oak_log", "birch_log", "spruce_log", "jungle_log",
    "acacia_log", "dark_oak_log", "cherry_log", "mangrove_log",
    "wet_sponge", "ancient_debris",
    "raw_iron", "raw_gold", "raw_copper",
    "cactus", "kelp",
    "potato", "beef", "porkchop", "chicken", "mutton",
    "rabbit", "cod", "salmon",
})

# Combined set for quick lookup (strip minecraft: prefix)
ALL_VALID_ITEMS = MINEABLE_BLOCKS | CRAFTABLE_ITEMS | SMELTABLE_ITEMS


def normalize_item(name):
    """Strip minecraft: prefix and validate against whitelist.
    Returns (normalized_name, is_valid)."""
    clean = name.strip()
    if clean.startswith("minecraft:"):
        clean = clean[len("minecraft:"):]
    return clean, clean in ALL_VALID_ITEMS


def validate_primitive(primitive):
    """Validate a single L3 primitive. Returns (primitive, is_valid, reason)."""
    ptype = primitive.get("type", "").upper()

    if ptype == "GOTO":
        for coord in ("x", "y", "z"):
            if coord not in primitive:
                return primitive, False, f"GOTO missing {coord}"
            try:
                float(primitive[coord])
            except (ValueError, TypeError):
                return primitive, False, f"GOTO {coord} not a number"
        return primitive, True, ""

    # Types that don't use standard item targets — pass through with basic checks
    _PASSTHROUGH_TYPES = {
        "SEND_ITEM", "BUILD", "FARM", "CONTAINER_PLACE", "CONTAINER_SEARCH",
        "CHANNEL", "COMBAT", "FOLLOW", "ENCHANT", "BREW",
    }
    if ptype in _PASSTHROUGH_TYPES:
        return primitive, True, ""

    target = primitive.get("target", "")
    if not target:
        return primitive, False, f"{ptype} missing target"

    clean, valid = normalize_item(target)
    if not valid:
        return primitive, False, f"unknown item: {target}"

    if ptype == "MINE" and clean not in MINEABLE_BLOCKS:
        if clean in CRAFTABLE_ITEMS:
            return primitive, False, f"{clean} is craftable, not mineable"
    elif ptype == "CRAFT" and clean not in CRAFTABLE_ITEMS:
        if clean in MINEABLE_BLOCKS:
            return primitive, False, f"{clean} is mineable, not craftable"
    elif ptype == "SMELT" and clean not in SMELTABLE_ITEMS:
        return primitive, False, f"{clean} is not smeltable"
    elif ptype not in ("MINE", "CRAFT", "SMELT"):
        return primitive, False, f"unknown primitive type: {ptype}"

    count = primitive.get("count", 1)
    if not isinstance(count, (int, float)) or count < 1 or count > 64:
        primitive["count"] = max(1, min(64, int(count) if isinstance(count, (int, float)) else 1))

    if ptype == "CRAFT":
        primitive["target"] = f"minecraft:{clean}"
    else:
        primitive["target"] = clean

    return primitive, True, ""


def validate_primitives(primitives):
    """Validate a list of L3 primitives. Returns (valid_list, rejected_list)."""
    valid = []
    rejected = []
    for p in primitives:
        p, ok, reason = validate_primitive(p)
        if ok:
            valid.append(p)
        else:
            rejected.append((p, reason))
    return valid, rejected
