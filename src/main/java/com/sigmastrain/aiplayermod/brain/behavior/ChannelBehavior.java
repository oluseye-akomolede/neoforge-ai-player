package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.shop.TransmuteRegistry;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.Vec3;

/**
 * Channels a discovered item from the TransmuteRegistry into the bot's inventory.
 * Only works for items the shared database has seen before.
 * Phases: VALIDATE → MEDITATING → CHANNELING
 */
public class ChannelBehavior implements Behavior {
    private enum Phase { VALIDATE, MEDITATING, CHANNELING }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String itemId;
    private int count;
    private int xpCost;
    private int channelTicks;
    private int meditateTarget;
    private int meditateTicks;
    private int meditateLevelsGained;

    private static final int TICKS_PER_ITEM = 40; // 2 seconds per item
    private static final int TICKS_PER_LEVEL = 40;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.itemId = directive.getTarget();
        this.count = directive.getCount() > 0 ? directive.getCount() : 1;
        enterPhase(Phase.VALIDATE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> tickValidate(bot);
            case MEDITATING -> tickMeditating(bot);
            case CHANNELING -> tickChanneling(bot);
        };
    }

    private BehaviorResult tickValidate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (itemId == null || itemId.isEmpty()) {
            progress.setFailureReason("No item specified");
            return BehaviorResult.FAILED;
        }

        if (!itemId.contains(":")) {
            itemId = "minecraft:" + itemId;
        }

        if (!TransmuteRegistry.isKnown(itemId)) {
            progress.setFailureReason("Item not in transmute registry: " + itemId);
            return BehaviorResult.FAILED;
        }

        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        if (item == Items.AIR) {
            progress.setFailureReason("Unknown item ID: " + itemId);
            return BehaviorResult.FAILED;
        }

        int perItemCost = TransmuteRegistry.getCost(itemId);
        xpCost = perItemCost * count;

        progress.logEvent("Channeling " + count + "x " + itemId + " (cost: " + xpCost + " XP levels)");

        if (player.experienceLevel < xpCost) {
            meditateTarget = xpCost - player.experienceLevel;
            meditateTicks = 0;
            meditateLevelsGained = 0;
            progress.logEvent("Need " + meditateTarget + " more XP levels, meditating");
            bot.systemChat("Meditating for " + meditateTarget + " XP levels...", "light_purple");
            enterPhase(Phase.MEDITATING);
            return BehaviorResult.RUNNING;
        }

        channelTicks = 0;
        enterPhase(Phase.CHANNELING);
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
                channelTicks = 0;
                enterPhase(Phase.CHANNELING);
            }
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChanneling(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();
        channelTicks++;

        if (channelTicks % 4 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 5, 0.6, 0.8, 0.6, 0.2);
            level.sendParticles(ParticleTypes.WITCH,
                    pos.x, pos.y + 1.5, pos.z, 2, 0.3, 0.3, 0.3, 0.05);
        }

        int totalDuration = TICKS_PER_ITEM * count;
        if (channelTicks < totalDuration) return BehaviorResult.RUNNING;

        player.giveExperienceLevels(-xpCost);

        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        int maxStack = item.getDefaultMaxStackSize();
        int remaining = count;
        while (remaining > 0) {
            int stackSize = Math.min(remaining, maxStack);
            ItemStack stack = new ItemStack(item, stackSize);
            if (!player.getInventory().add(stack)) {
                player.drop(stack, false);
            }
            remaining -= stackSize;
        }

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.5, pos.z, 15, 0.5, 1.0, 0.5, 0.1);
        level.playSound(null, player.blockPosition(),
                SoundEvents.EXPERIENCE_ORB_PICKUP, SoundSource.PLAYERS, 1.0f, 0.8f);

        progress.increment("items_channeled", count);
        progress.logEvent("Channeled " + count + "x " + itemId);
        bot.systemChat("Channeled " + count + "x " + itemId + " (" + xpCost + " XP)", "light_purple");
        AIPlayerMod.LOGGER.info("[{}] Channeled {} x{} (cost {} XP)",
                player.getName().getString(), itemId, count, xpCost);

        return BehaviorResult.SUCCESS;
    }

    private void enterPhase(Phase p) {
        this.phase = p;
        progress.setPhase(p.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case VALIDATE -> "Validating channel request";
            case MEDITATING -> "Meditating for XP (" + meditateLevelsGained + "/" + meditateTarget + ")";
            case CHANNELING -> "Channeling " + count + "x " + itemId
                    + " (" + channelTicks + "/" + (TICKS_PER_ITEM * count) + ")";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
