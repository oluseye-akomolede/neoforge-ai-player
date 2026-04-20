package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;

import java.util.Map;

/**
 * Conjure ritual: bot channels XP to materialize raw materials.
 * Cost scales with item rarity. Takes time proportional to cost.
 * Only raw materials/currencies — never finished items.
 */
public class ConjureAction implements BotAction {
    private final String itemId;
    private final int count;
    private int ticksRemaining;
    private int xpCost;
    private String result = null;

    private static final int TICKS_PER_LEVEL = 20; // 1 second per level of cost

    private static final Map<String, Integer> COST_TABLE = Map.ofEntries(
        // Basic resources (1-2 levels)
        Map.entry("minecraft:dirt", 1),
        Map.entry("minecraft:cobblestone", 1),
        Map.entry("minecraft:sand", 1),
        Map.entry("minecraft:gravel", 1),
        Map.entry("minecraft:clay_ball", 1),
        Map.entry("minecraft:stick", 1),
        Map.entry("minecraft:flint", 1),
        Map.entry("minecraft:bone", 1),
        Map.entry("minecraft:string", 1),
        Map.entry("minecraft:feather", 1),
        Map.entry("minecraft:leather", 2),
        Map.entry("minecraft:coal", 2),
        Map.entry("minecraft:charcoal", 2),
        Map.entry("minecraft:raw_copper", 2),
        Map.entry("minecraft:copper_ingot", 2),
        Map.entry("minecraft:oak_log", 1),
        Map.entry("minecraft:spruce_log", 1),
        Map.entry("minecraft:birch_log", 1),
        Map.entry("minecraft:jungle_log", 1),
        Map.entry("minecraft:acacia_log", 1),
        Map.entry("minecraft:dark_oak_log", 1),

        // Mid-tier resources (3-5 levels)
        Map.entry("minecraft:iron_ingot", 3),
        Map.entry("minecraft:raw_iron", 3),
        Map.entry("minecraft:gold_ingot", 4),
        Map.entry("minecraft:raw_gold", 4),
        Map.entry("minecraft:lapis_lazuli", 3),
        Map.entry("minecraft:redstone", 3),
        Map.entry("minecraft:quartz", 3),
        Map.entry("minecraft:amethyst_shard", 3),
        Map.entry("minecraft:emerald", 5),
        Map.entry("minecraft:slime_ball", 3),
        Map.entry("minecraft:ender_pearl", 5),
        Map.entry("minecraft:blaze_rod", 5),
        Map.entry("minecraft:blaze_powder", 4),
        Map.entry("minecraft:ghast_tear", 5),
        Map.entry("minecraft:magma_cream", 4),
        Map.entry("minecraft:phantom_membrane", 4),
        Map.entry("minecraft:gunpowder", 3),
        Map.entry("minecraft:glowstone_dust", 3),
        Map.entry("minecraft:prismarine_shard", 3),
        Map.entry("minecraft:obsidian", 4),

        // High-tier resources (8-20 levels)
        Map.entry("minecraft:diamond", 15),
        Map.entry("minecraft:ancient_debris", 25),
        Map.entry("minecraft:netherite_scrap", 20),
        Map.entry("minecraft:netherite_ingot", 40),
        Map.entry("minecraft:nether_star", 50),
        Map.entry("minecraft:elytra", 60),
        Map.entry("minecraft:shulker_shell", 15),
        Map.entry("minecraft:totem_of_undying", 30),
        Map.entry("minecraft:heart_of_the_sea", 25),
        Map.entry("minecraft:wither_skeleton_skull", 20),

        // Smithing templates (10 levels)
        Map.entry("minecraft:netherite_upgrade_smithing_template", 10),

        // Food & farming (1-2 levels)
        Map.entry("minecraft:wheat_seeds", 1),
        Map.entry("minecraft:wheat", 1),
        Map.entry("minecraft:carrot", 1),
        Map.entry("minecraft:potato", 1),
        Map.entry("minecraft:beetroot_seeds", 1),
        Map.entry("minecraft:melon_slice", 1),
        Map.entry("minecraft:sugar_cane", 1),
        Map.entry("minecraft:egg", 1),
        Map.entry("minecraft:cocoa_beans", 2),
        Map.entry("minecraft:nether_wart", 3),

        // Brewing ingredients (3-5 levels)
        Map.entry("minecraft:spider_eye", 3),
        Map.entry("minecraft:fermented_spider_eye", 4),
        Map.entry("minecraft:rabbit_foot", 5),
        Map.entry("minecraft:golden_carrot", 5),
        Map.entry("minecraft:glistering_melon_slice", 5),
        Map.entry("minecraft:turtle_scute", 5),
        Map.entry("minecraft:glass_bottle", 1),

        // Dyes (1 level each)
        Map.entry("minecraft:white_dye", 1),
        Map.entry("minecraft:black_dye", 1),
        Map.entry("minecraft:red_dye", 1),
        Map.entry("minecraft:blue_dye", 1),
        Map.entry("minecraft:green_dye", 1),
        Map.entry("minecraft:yellow_dye", 1),
        Map.entry("minecraft:ink_sac", 1),
        Map.entry("minecraft:glow_ink_sac", 2)
    );

    // Default cost for items not in the table
    private static final int DEFAULT_COST = 8;

    public ConjureAction(String itemId, int count) {
        this.itemId = itemId;
        this.count = Math.max(1, Math.min(64, count));
        this.xpCost = getCostForItem(itemId) * this.count;
        this.ticksRemaining = Math.max(20, xpCost * TICKS_PER_LEVEL);
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // First tick: validate
        if (ticksRemaining == Math.max(20, xpCost * TICKS_PER_LEVEL)) {
            // Verify item exists
            Item item;
            try {
                item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
                if (item == net.minecraft.world.item.Items.AIR) {
                    result = "FAILED: Unknown item '" + itemId + "'. Use minecraft:item_name format.";
                    return true;
                }
            } catch (Exception e) {
                result = "FAILED: Invalid item ID '" + itemId + "'";
                return true;
            }

            // Check XP
            if (player.experienceLevel < xpCost && !player.getAbilities().instabuild) {
                result = "FAILED: Need " + xpCost + " XP levels to conjure " + count + "x " + itemId
                        + " but only have " + player.experienceLevel + ". Use meditate first.";
                return true;
            }
        }

        // Channel — emit particles and sounds
        ServerLevel level = (ServerLevel) player.level();
        Vec3 pos = player.position();

        // Portal particles spiraling inward every 3 ticks
        if (ticksRemaining % 3 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z,
                    2, 0.8, 0.5, 0.8, 0.2);
            level.sendParticles(ParticleTypes.END_ROD,
                    pos.x, pos.y + 1.5, pos.z,
                    1, 0.3, 0.3, 0.3, 0.02);
        }

        // Start sound on first channel tick
        if (ticksRemaining == Math.max(20, xpCost * TICKS_PER_LEVEL) - 1) {
            level.playSound(null, player.blockPosition(),
                    SoundEvents.BEACON_ACTIVATE, SoundSource.PLAYERS,
                    0.6f, 1.5f);
        }

        ticksRemaining--;
        if (ticksRemaining > 0) return false;

        // Complete the ritual — big particle burst + sound
        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        ItemStack stack = new ItemStack(item, count);

        if (!player.getAbilities().instabuild) {
            player.giveExperienceLevels(-xpCost);
        }

        player.getInventory().add(stack);

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.0, pos.z,
                15, 0.5, 0.8, 0.5, 0.1);
        level.sendParticles(ParticleTypes.WITCH,
                pos.x, pos.y + 1.0, pos.z,
                10, 0.4, 0.4, 0.4, 0.05);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS,
                0.7f, 1.2f);

        // Build inventory summary so the bot knows what it has now
        StringBuilder inv = new StringBuilder();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty()) {
                if (inv.length() > 0) inv.append(", ");
                inv.append("slot ").append(i).append(": ")
                   .append(BuiltInRegistries.ITEM.getKey(s.getItem())).append(" x").append(s.getCount());
            }
        }

        result = "Conjured " + count + "x " + itemId + " (cost " + xpCost + " levels). Inventory now: [" + inv + "]";
        return true;
    }

    private static int getCostForItem(String itemId) {
        return COST_TABLE.getOrDefault(itemId, DEFAULT_COST);
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        return String.format("Conjure(%s x%d, %d levels, %ds remaining)",
                itemId, count, xpCost, ticksRemaining / 20);
    }
}
