package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;

import java.util.Map;

/**
 * Internal smelting — bots convert items directly in inventory using XP.
 * No furnace blocks needed. Phases: VALIDATE → CHANNEL → SMELTING → DONE.
 */
public class SmeltBehavior implements Behavior {
    private enum Phase { VALIDATE, CHANNEL, SMELTING }

    private static final int SMELT_TICKS = 40; // 2 seconds per batch
    private static final int TICKS_PER_PARTICLE = 5;

    private static final Map<String, String> SMELTING_RECIPES = Map.ofEntries(
        Map.entry("minecraft:raw_iron", "minecraft:iron_ingot"),
        Map.entry("minecraft:raw_gold", "minecraft:gold_ingot"),
        Map.entry("minecraft:raw_copper", "minecraft:copper_ingot"),
        Map.entry("minecraft:iron_ore", "minecraft:iron_ingot"),
        Map.entry("minecraft:gold_ore", "minecraft:gold_ingot"),
        Map.entry("minecraft:copper_ore", "minecraft:copper_ingot"),
        Map.entry("minecraft:deepslate_iron_ore", "minecraft:iron_ingot"),
        Map.entry("minecraft:deepslate_gold_ore", "minecraft:gold_ingot"),
        Map.entry("minecraft:deepslate_copper_ore", "minecraft:copper_ingot"),
        Map.entry("minecraft:cobblestone", "minecraft:stone"),
        Map.entry("minecraft:stone", "minecraft:smooth_stone"),
        Map.entry("minecraft:sand", "minecraft:glass"),
        Map.entry("minecraft:red_sand", "minecraft:glass"),
        Map.entry("minecraft:clay_ball", "minecraft:brick"),
        Map.entry("minecraft:clay", "minecraft:terracotta"),
        Map.entry("minecraft:netherrack", "minecraft:nether_brick"),
        Map.entry("minecraft:ancient_debris", "minecraft:netherite_scrap"),
        Map.entry("minecraft:wet_sponge", "minecraft:sponge"),
        Map.entry("minecraft:kelp", "minecraft:dried_kelp"),
        Map.entry("minecraft:cactus", "minecraft:green_dye"),
        Map.entry("minecraft:sea_pickle", "minecraft:lime_dye"),
        Map.entry("minecraft:log", "minecraft:charcoal"),
        Map.entry("minecraft:oak_log", "minecraft:charcoal"),
        Map.entry("minecraft:birch_log", "minecraft:charcoal"),
        Map.entry("minecraft:spruce_log", "minecraft:charcoal"),
        Map.entry("minecraft:jungle_log", "minecraft:charcoal"),
        Map.entry("minecraft:acacia_log", "minecraft:charcoal"),
        Map.entry("minecraft:dark_oak_log", "minecraft:charcoal"),
        Map.entry("minecraft:mangrove_log", "minecraft:charcoal"),
        Map.entry("minecraft:cherry_log", "minecraft:charcoal"),
        Map.entry("minecraft:nether_gold_ore", "minecraft:gold_ingot"),
        Map.entry("minecraft:quartz_ore", "minecraft:quartz"),
        Map.entry("minecraft:nether_quartz_ore", "minecraft:quartz"),
        Map.entry("minecraft:lapis_ore", "minecraft:lapis_lazuli"),
        Map.entry("minecraft:deepslate_lapis_ore", "minecraft:lapis_lazuli"),
        Map.entry("minecraft:redstone_ore", "minecraft:redstone"),
        Map.entry("minecraft:deepslate_redstone_ore", "minecraft:redstone"),
        Map.entry("minecraft:diamond_ore", "minecraft:diamond"),
        Map.entry("minecraft:deepslate_diamond_ore", "minecraft:diamond"),
        Map.entry("minecraft:emerald_ore", "minecraft:emerald"),
        Map.entry("minecraft:deepslate_emerald_ore", "minecraft:emerald"),
        Map.entry("minecraft:coal_ore", "minecraft:coal"),
        Map.entry("minecraft:deepslate_coal_ore", "minecraft:coal"),
        // Food
        Map.entry("minecraft:beef", "minecraft:cooked_beef"),
        Map.entry("minecraft:porkchop", "minecraft:cooked_porkchop"),
        Map.entry("minecraft:chicken", "minecraft:cooked_chicken"),
        Map.entry("minecraft:mutton", "minecraft:cooked_mutton"),
        Map.entry("minecraft:rabbit", "minecraft:cooked_rabbit"),
        Map.entry("minecraft:cod", "minecraft:cooked_cod"),
        Map.entry("minecraft:salmon", "minecraft:cooked_salmon"),
        Map.entry("minecraft:potato", "minecraft:baked_potato")
    );

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String inputItemId;
    private String outputItemId;
    private int totalToSmelt;
    private int totalSmelted;
    private int smeltTicks;
    private int xpCostPerItem;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.inputItemId = directive.getTarget();
        if (!inputItemId.contains(":")) inputItemId = "minecraft:" + inputItemId;
        this.totalToSmelt = directive.getCount() > 0 ? directive.getCount() : 1;
        this.totalSmelted = 0;
        this.smeltTicks = 0;
        enterPhase(Phase.VALIDATE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> tickValidate(bot);
            case CHANNEL -> tickChannel(bot);
            case SMELTING -> tickSmelting(bot);
        };
    }

    private BehaviorResult tickValidate(BotPlayer bot) {
        outputItemId = SMELTING_RECIPES.get(inputItemId);
        if (outputItemId == null) {
            progress.setFailureReason("No smelting recipe for " + inputItemId);
            return BehaviorResult.FAILED;
        }

        xpCostPerItem = getSmeltXpCost(inputItemId);
        progress.logEvent("Internal smelt: " + totalToSmelt + "x " + inputItemId + " → " + outputItemId);

        ServerPlayer player = bot.getPlayer();
        int haveCount = countItemById(player, inputItemId);
        if (haveCount >= totalToSmelt) {
            enterPhase(Phase.SMELTING);
        } else {
            enterPhase(Phase.CHANNEL);
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChannel(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int haveCount = countItemById(player, inputItemId);
        int needed = totalToSmelt - haveCount;
        if (needed <= 0) {
            enterPhase(Phase.SMELTING);
            return BehaviorResult.RUNNING;
        }

        int channelCost = getChannelCost(inputItemId) * needed;
        if (player.experienceLevel < channelCost) {
            player.giveExperienceLevels(channelCost - player.experienceLevel);
        }

        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(inputItemId));
        player.getInventory().add(new ItemStack(item, needed));
        player.giveExperienceLevels(-channelCost);
        progress.increment("items_channeled", needed);
        bot.systemChat("Channeled " + needed + "x " + inputItemId, "light_purple");
        enterPhase(Phase.SMELTING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickSmelting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        smeltTicks++;

        // Particles every few ticks for visual feedback
        if (smeltTicks % TICKS_PER_PARTICLE == 0 && player.level() instanceof ServerLevel serverLevel) {
            serverLevel.sendParticles(ParticleTypes.FLAME,
                player.getX(), player.getY() + 1.0, player.getZ(),
                3, 0.3, 0.3, 0.3, 0.01);
            serverLevel.sendParticles(ParticleTypes.SMOKE,
                player.getX(), player.getY() + 1.2, player.getZ(),
                2, 0.2, 0.2, 0.2, 0.02);
        }

        if (smeltTicks < SMELT_TICKS) {
            return BehaviorResult.RUNNING;
        }

        // Smelting complete — consume input, produce output
        int toProcess = Math.min(totalToSmelt - totalSmelted, 64);
        int consumed = removeItems(player, inputItemId, toProcess);
        if (consumed == 0) {
            progress.setFailureReason("No input items in inventory");
            return BehaviorResult.FAILED;
        }

        // XP cost for smelting
        int totalXpCost = xpCostPerItem * consumed;
        if (player.experienceLevel < totalXpCost) {
            player.giveExperienceLevels(totalXpCost - player.experienceLevel);
        }
        player.giveExperienceLevels(-totalXpCost);

        // Give output
        Item outputItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(outputItemId));
        player.getInventory().add(new ItemStack(outputItem, consumed));
        totalSmelted += consumed;
        progress.increment("items_smelted", consumed);

        // Sound effect
        if (player.level() instanceof ServerLevel serverLevel) {
            serverLevel.playSound(null, player.blockPosition(),
                SoundEvents.FURNACE_FIRE_CRACKLE, SoundSource.BLOCKS, 1.0f, 1.0f);
        }

        bot.systemChat("Smelted " + consumed + "x " + inputItemId + " → " + outputItemId
            + " (" + totalSmelted + "/" + totalToSmelt + ")", "gold");

        if (totalSmelted >= totalToSmelt) {
            progress.logEvent("Internal smelting complete: " + totalSmelted + " items");
            return BehaviorResult.SUCCESS;
        }

        // More batches needed
        smeltTicks = 0;
        return BehaviorResult.RUNNING;
    }

    private int countItemById(ServerPlayer player, String itemId) {
        int count = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            if (id.equals(itemId)) count += stack.getCount();
        }
        return count;
    }

    private int removeItems(ServerPlayer player, String itemId, int amount) {
        int removed = 0;
        for (int i = 0; i < player.getInventory().getContainerSize() && removed < amount; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            if (id.equals(itemId)) {
                int take = Math.min(stack.getCount(), amount - removed);
                stack.shrink(take);
                removed += take;
            }
        }
        return removed;
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case VALIDATE -> "Validating smelting recipe";
            case CHANNEL -> "Channeling input materials";
            case SMELTING -> "Internal smelting (" + smeltTicks + "/" + SMELT_TICKS + " ticks)";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}

    private int getChannelCost(String itemId) {
        return switch (itemId) {
            case "minecraft:cobblestone", "minecraft:sand", "minecraft:clay_ball",
                 "minecraft:netherrack", "minecraft:kelp", "minecraft:cactus" -> 1;
            case "minecraft:coal", "minecraft:raw_copper", "minecraft:clay",
                 "minecraft:potato", "minecraft:beef", "minecraft:porkchop",
                 "minecraft:chicken", "minecraft:cod", "minecraft:salmon" -> 2;
            case "minecraft:raw_iron", "minecraft:raw_gold", "minecraft:quartz" -> 3;
            case "minecraft:ancient_debris" -> 25;
            default -> 3;
        };
    }

    private int getSmeltXpCost(String itemId) {
        return switch (itemId) {
            case "minecraft:cobblestone", "minecraft:sand", "minecraft:red_sand",
                 "minecraft:clay_ball", "minecraft:netherrack", "minecraft:kelp",
                 "minecraft:cactus", "minecraft:sea_pickle", "minecraft:wet_sponge" -> 1;
            case "minecraft:potato", "minecraft:beef", "minecraft:porkchop",
                 "minecraft:chicken", "minecraft:mutton", "minecraft:rabbit",
                 "minecraft:cod", "minecraft:salmon" -> 1;
            case "minecraft:raw_copper", "minecraft:copper_ore",
                 "minecraft:deepslate_copper_ore", "minecraft:coal_ore",
                 "minecraft:deepslate_coal_ore" -> 1;
            case "minecraft:raw_iron", "minecraft:iron_ore",
                 "minecraft:deepslate_iron_ore" -> 2;
            case "minecraft:raw_gold", "minecraft:gold_ore",
                 "minecraft:deepslate_gold_ore", "minecraft:nether_gold_ore" -> 2;
            case "minecraft:diamond_ore", "minecraft:deepslate_diamond_ore",
                 "minecraft:emerald_ore", "minecraft:deepslate_emerald_ore",
                 "minecraft:lapis_ore", "minecraft:deepslate_lapis_ore" -> 3;
            case "minecraft:ancient_debris" -> 10;
            default -> 2;
        };
    }
}
