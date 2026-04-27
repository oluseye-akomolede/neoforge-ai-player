package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.Holder;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.util.RandomSource;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.enchantment.Enchantment;
import net.minecraft.world.item.enchantment.EnchantmentHelper;
import net.minecraft.world.item.enchantment.EnchantmentInstance;
import net.minecraft.world.phys.Vec3;

import java.util.List;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * Channeled enchanting — bots enchant items directly using XP.
 * No enchanting table needed. Random enchantments based on XP level spent.
 * Phases: VALIDATE → MEDITATING → ENCHANTING
 */
public class EnchantBehavior implements Behavior {
    private enum Phase { VALIDATE, MEDITATING, ENCHANTING }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String targetItem;
    private int option; // 0=basic(1-8), 1=mid(9-20), 2=max(21-30)
    private int itemSlot = -1;
    private int enchantLevel;
    private int enchantTicks;
    private int meditateTarget;
    private int meditateTicks;
    private int meditateLevelsGained;

    private static final int ENCHANT_DURATION = 60; // 3 seconds
    private static final int TICKS_PER_LEVEL = 5;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetItem = directive.getTarget();
        this.option = 2;
        if (directive.getExtra().containsKey("option")) {
            try { this.option = Integer.parseInt(directive.getExtra().get("option")); }
            catch (NumberFormatException ignored) {}
        }
        this.option = Math.max(0, Math.min(2, this.option));
        enterPhase(Phase.VALIDATE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> tickValidate(bot);
            case MEDITATING -> tickMeditating(bot);
            case ENCHANTING -> tickEnchanting(bot);
        };
    }

    private BehaviorResult tickValidate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // Find enchantable item
        itemSlot = -1;
        if (targetItem != null && !targetItem.isEmpty()) {
            try {
                int slot = Integer.parseInt(targetItem);
                ItemStack stack = player.getInventory().getItem(slot);
                if (!stack.isEmpty() && stack.isEnchantable()) {
                    itemSlot = slot;
                }
            } catch (NumberFormatException e) {
                String search = targetItem.toLowerCase();
                for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                    ItemStack stack = player.getInventory().getItem(i);
                    if (stack.isEmpty() || !stack.isEnchantable()) continue;
                    String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                    if (id.contains(search)) {
                        itemSlot = i;
                        break;
                    }
                }
            }
        }

        if (itemSlot < 0) {
            for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                ItemStack stack = player.getInventory().getItem(i);
                if (!stack.isEmpty() && stack.isEnchantable()) {
                    itemSlot = i;
                    break;
                }
            }
        }

        if (itemSlot < 0) {
            progress.setFailureReason("No enchantable item found in inventory");
            return BehaviorResult.FAILED;
        }

        // Determine enchant level based on option tier
        RandomSource random = player.getRandom();
        enchantLevel = switch (option) {
            case 0 -> 1 + random.nextInt(8);      // 1-8
            case 1 -> 9 + random.nextInt(12);      // 9-20
            default -> 21 + random.nextInt(10);     // 21-30
        };

        int xpCost = getXpCost(enchantLevel);
        String itemId = BuiltInRegistries.ITEM.getKey(player.getInventory().getItem(itemSlot).getItem()).toString();
        progress.logEvent("Enchanting " + itemId + " at level " + enchantLevel + " (cost: " + xpCost + " XP levels)");

        if (player.experienceLevel < xpCost) {
            meditateTarget = xpCost - player.experienceLevel;
            meditateTicks = 0;
            meditateLevelsGained = 0;
            progress.logEvent("Need " + meditateTarget + " more XP levels, meditating");
            bot.systemChat("Meditating for " + meditateTarget + " XP levels...", "light_purple");
            enterPhase(Phase.MEDITATING);
            return BehaviorResult.RUNNING;
        }

        enchantTicks = 0;
        enterPhase(Phase.ENCHANTING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickMeditating(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        meditateTicks++;

        if (meditateTicks % 4 == 0) {
            Vec3 pos = player.position();
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z, 3, 0.5, 0.5, 0.5, 0.1);
        }

        if (meditateTicks % TICKS_PER_LEVEL == 0) {
            player.giveExperienceLevels(1);
            meditateLevelsGained++;
            progress.increment("xp_levels_gained");

            if (meditateLevelsGained >= meditateTarget) {
                progress.logEvent("Meditation complete: gained " + meditateLevelsGained + " levels");
                enchantTicks = 0;
                enterPhase(Phase.ENCHANTING);
            }
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickEnchanting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();
        enchantTicks++;

        // Enchanting particles
        if (enchantTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.0, pos.z, 5, 0.8, 1.0, 0.8, 0.3);
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 0.5, pos.z, 3, 0.5, 0.5, 0.5, 0.2);
        }

        if (enchantTicks < ENCHANT_DURATION) return BehaviorResult.RUNNING;

        // Apply enchantments
        ItemStack item = player.getInventory().getItem(itemSlot);
        if (item.isEmpty()) {
            progress.setFailureReason("Item disappeared from slot " + itemSlot);
            return BehaviorResult.FAILED;
        }

        int xpCost = getXpCost(enchantLevel);
        player.giveExperienceLevels(-xpCost);

        // Use vanilla enchantment selection
        RandomSource random = player.getRandom();
        Stream<Holder<Enchantment>> enchantmentStream =
                level.registryAccess().lookupOrThrow(Registries.ENCHANTMENT)
                        .listElements().map(ref -> (Holder<Enchantment>) ref);
        List<EnchantmentInstance> enchants =
                EnchantmentHelper.selectEnchantment(random, item, enchantLevel, enchantmentStream);

        if (enchants.isEmpty()) {
            // Fallback: refund XP, item wasn't compatible
            player.giveExperienceLevels(xpCost);
            progress.setFailureReason("No compatible enchantments for this item at level " + enchantLevel);
            return BehaviorResult.FAILED;
        }

        for (var inst : enchants) {
            item.enchant(inst.enchantment, inst.level);
        }

        // Effects
        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.5, pos.z, 20, 0.5, 1.0, 0.5, 0.15);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENCHANTMENT_TABLE_USE, SoundSource.PLAYERS, 1.0f, 1.0f);

        String itemId = BuiltInRegistries.ITEM.getKey(item.getItem()).toString();
        StringBuilder enchantNames = new StringBuilder();
        for (var inst : enchants) {
            if (!enchantNames.isEmpty()) enchantNames.append(", ");
            String name = inst.enchantment.unwrapKey()
                    .map(k -> k.location().getPath()).orElse("unknown");
            enchantNames.append(name).append(" ").append(inst.level);
        }

        progress.increment("items_enchanted");
        progress.logEvent("Enchanted " + itemId + ": " + enchantNames);
        bot.systemChat("Enchanted " + itemId + " with " + enchantNames, "light_purple");
        AIPlayerMod.LOGGER.info("[{}] Channeled enchant: {} -> {} (level {}, cost {} XP)",
                player.getName().getString(), itemId, enchantNames, enchantLevel, xpCost);

        return BehaviorResult.SUCCESS;
    }

    private int getXpCost(int level) {
        if (level <= 8) return level;
        if (level <= 20) return level;
        return level;
    }

    private void enterPhase(Phase p) {
        this.phase = p;
        progress.setPhase(p.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case VALIDATE -> "Preparing to enchant";
            case MEDITATING -> "Meditating for XP (" + meditateLevelsGained + "/" + meditateTarget + ")";
            case ENCHANTING -> "Channeling enchantment (" + enchantTicks + "/" + ENCHANT_DURATION + ")";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
