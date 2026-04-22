package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.Vec3;

/**
 * Places a chest at the bot's position using XP (no inventory item needed).
 * Registers the container in the shared ContainerRegistry.
 * Directive target = ignored (optional label).
 * XP cost: 3 levels per container.
 */
public class ContainerPlaceBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();

    private static final int XP_COST = 3;
    private static final int CHANNEL_TICKS = 40; // 2 second conjure animation
    private int ticks;
    private BlockPos placePos;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        ticks = 0;

        ServerPlayer player = bot.getPlayer();
        placePos = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 1);

        if (!player.level().getBlockState(placePos).isAir()) {
            placePos = player.blockPosition().above();
            if (!player.level().getBlockState(placePos).isAir()) {
                placePos = player.blockPosition();
            }
        }

        if (player.experienceLevel < XP_COST) {
            player.giveExperienceLevels(XP_COST - player.experienceLevel);
        }

        progress.setPhase("channeling");
        progress.logEvent("Conjuring container at " + placePos.toShortString() + " (cost " + XP_COST + " XP)");
        bot.systemChat("Conjuring container...", "light_purple");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) return BehaviorResult.FAILED;

        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        ticks++;

        if (ticks % 4 == 0) {
            Vec3 pos = Vec3.atCenterOf(placePos);
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 0.5, pos.z, 3, 0.3, 0.3, 0.3, 0.1);
        }

        if (ticks < CHANNEL_TICKS) return BehaviorResult.RUNNING;

        player.giveExperienceLevels(-XP_COST);
        level.setBlock(placePos, Blocks.CHEST.defaultBlockState(), 3);
        level.playSound(null, placePos, SoundEvents.WOOD_PLACE, SoundSource.BLOCKS, 1.0f, 1.0f);

        String dimension = level.dimension().location().toString();
        int id = ContainerRegistry.get().register(placePos, dimension, bot.getPlayer().getName().getString());

        progress.increment("containers_placed");
        progress.logEvent("Placed container #" + id + " at " + placePos.toShortString());
        bot.systemChat("Container #" + id + " placed at " + placePos.toShortString(), "green");
        AIPlayerMod.LOGGER.info("[{}] Placed container #{} at {} [{}]",
                player.getName().getString(), id, placePos, dimension);

        return BehaviorResult.SUCCESS;
    }

    @Override
    public String describeState() {
        return "Conjuring container (" + ticks + "/" + CHANNEL_TICKS + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
