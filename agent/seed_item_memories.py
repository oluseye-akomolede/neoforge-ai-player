#!/usr/bin/env python3
"""
Seed shared semantic memory with correct Minecraft item knowledge.

Run once to populate the shared memory pool with crafting recipes,
smelting inputs/outputs, and common mining targets. All bots can
recall these via recall_shared().
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import OLLAMA_URL, PG_DSN
from semantic_memory import SemanticMemory

CRAFTING_KNOWLEDGE = [
    # Basic materials
    "To get oak_planks: craft from oak_log (1 log = 4 planks). Works with any log type.",
    "To get sticks: craft from 2 planks (any type). Yields 4 sticks.",
    "To get charcoal: smelt oak_log (or any log) in a furnace.",
    "To get torches: craft 1 stick + 1 coal (or charcoal). Yields 4 torches.",

    # Stone tier tools
    "To craft stone_pickaxe: need 3 cobblestone + 2 sticks. Arranged: 3 cobblestone across top row, 1 stick center, 1 stick bottom center.",
    "To craft stone_axe: need 3 cobblestone + 2 sticks.",
    "To craft stone_sword: need 2 cobblestone + 1 stick.",
    "To craft stone_shovel: need 1 cobblestone + 2 sticks.",
    "To craft stone_hoe: need 2 cobblestone + 2 sticks.",

    # Wooden tier tools
    "To craft wooden_pickaxe: need 3 oak_planks + 2 sticks.",
    "To craft wooden_axe: need 3 oak_planks + 2 sticks.",
    "To craft wooden_sword: need 2 oak_planks + 1 stick.",
    "To craft wooden_shovel: need 1 oak_planks + 2 sticks.",

    # Iron tier tools
    "To craft iron_pickaxe: need 3 iron_ingot + 2 sticks.",
    "To craft iron_sword: need 2 iron_ingot + 1 stick.",
    "To craft iron_axe: need 3 iron_ingot + 2 sticks.",

    # Diamond tier tools
    "To craft diamond_pickaxe: need 3 diamond + 2 sticks.",
    "To craft diamond_sword: need 2 diamond + 1 stick.",

    # Workstations
    "To craft crafting_table: need 4 planks (any type) in 2x2 grid.",
    "To craft furnace: need 8 cobblestone arranged in a ring (3x3 with empty center).",
    "To craft blast_furnace: need 5 iron_ingot + 3 smooth_stone + 1 furnace.",
    "To craft anvil: need 3 iron_block + 4 iron_ingot.",
    "To craft enchanting_table: need 1 book + 2 diamond + 4 obsidian.",
    "To craft brewing_stand: need 1 blaze_rod + 3 cobblestone.",
    "To craft smithing_table: need 2 iron_ingot + 4 planks.",

    # Storage
    "To craft chest: need 8 planks (any type) arranged in a ring.",
    "To craft barrel: need 6 planks + 2 slabs.",
    "To craft hopper: need 5 iron_ingot + 1 chest.",

    # Iron armor
    "To craft iron_helmet: need 5 iron_ingot.",
    "To craft iron_chestplate: need 8 iron_ingot.",
    "To craft iron_leggings: need 7 iron_ingot.",
    "To craft iron_boots: need 4 iron_ingot.",
    "To craft shield: need 6 planks + 1 iron_ingot.",

    # Diamond armor
    "To craft diamond_helmet: need 5 diamond.",
    "To craft diamond_chestplate: need 8 diamond.",
    "To craft diamond_leggings: need 7 diamond.",
    "To craft diamond_boots: need 4 diamond.",

    # Smelting
    "To get iron_ingot: smelt raw_iron (or iron_ore) in furnace. Need fuel (coal, charcoal, or planks).",
    "To get gold_ingot: smelt raw_gold (or gold_ore) in furnace.",
    "To get copper_ingot: smelt raw_copper (or copper_ore) in furnace.",
    "To get smooth_stone: smelt cobblestone in furnace (cobblestone -> stone -> smooth_stone).",
    "To get glass: smelt sand in furnace.",
    "To get brick: smelt clay_ball in furnace.",
    "To get cooked_beef: smelt beef (raw) in furnace or campfire.",
    "To get netherite_scrap: smelt ancient_debris in blast_furnace.",

    # Mining knowledge
    "Iron ore spawns at y=-64 to y=72, most common around y=16. Need stone_pickaxe or better.",
    "Diamond ore spawns at y=-64 to y=16, most common at y=-59. Need iron_pickaxe or better.",
    "Gold ore spawns at y=-64 to y=32. Also in badlands at higher levels. Need iron_pickaxe or better.",
    "Coal ore spawns at y=0 to y=320, most common around y=96. Any pickaxe works.",
    "Copper ore spawns at y=-16 to y=112, most common around y=48. Need stone_pickaxe or better.",
    "Cobblestone: mine any stone block. Found everywhere underground.",
    "Oak logs: chop oak trees at surface level. No tool required but axe is faster.",

    # Misc useful
    "To craft bucket: need 3 iron_ingot in V shape.",
    "To craft compass: need 4 iron_ingot + 1 redstone.",
    "To craft bed: need 3 wool (same color) + 3 planks.",
    "To craft bread: need 3 wheat in a row.",
    "To craft golden_apple: need 1 apple + 8 gold_ingot.",
    "To craft book: need 3 paper + 1 leather.",
    "To craft paper: need 3 sugar_cane in a row.",
    "To craft bow: need 3 sticks + 3 string.",
    "To craft ladder: need 7 sticks. Yields 3 ladders.",
    "To craft rail: need 6 iron_ingot + 1 stick. Yields 16 rails.",

    # Redstone
    "To craft piston: need 3 planks + 4 cobblestone + 1 iron_ingot + 1 redstone.",
    "To craft repeater: need 3 stone + 2 redstone_torch + 1 redstone.",
    "To craft comparator: need 3 stone + 3 redstone_torch + 1 nether_quartz.",
]


def main():
    if not PG_DSN:
        print("Error: PG_DSN not configured")
        sys.exit(1)

    mem = SemanticMemory("shared_seeder", OLLAMA_URL, PG_DSN)
    mem.connect()

    stored = 0
    dupes = 0
    for i, knowledge in enumerate(CRAFTING_KNOWLEDGE):
        try:
            mid = mem.store_shared(knowledge, category="knowledge")
            if mid:
                stored += 1
            else:
                dupes += 1
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i+1}/{len(CRAFTING_KNOWLEDGE)} ({stored} new, {dupes} dupes)")
        except Exception as e:
            print(f"  Error storing '{knowledge[:40]}...': {e}")

    print(f"\nDone! Stored {stored} new memories, {dupes} duplicates skipped.")
    mem.close()


if __name__ == "__main__":
    main()
