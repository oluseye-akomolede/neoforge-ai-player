package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;

public class TeleportBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();
    private double targetX, targetY, targetZ;
    private String dimension;
    private boolean done = false;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("teleporting");
        this.targetX = directive.getX();
        this.targetY = directive.getY();
        this.targetZ = directive.getZ();
        this.dimension = directive.getExtra().getOrDefault("dimension", null);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (done) return BehaviorResult.SUCCESS;
        done = true;

        ServerPlayer player = bot.getPlayer();

        if (dimension != null && !dimension.isEmpty()) {
            String currentDim = player.level().dimension().location().toString();
            if (!currentDim.equals(dimension)) {
                var dimKey = ResourceKey.create(Registries.DIMENSION, ResourceLocation.parse(dimension));
                boolean ok = bot.teleportToDimension(dimKey, targetX, targetY, targetZ);
                if (!ok) {
                    progress.setFailureReason("Dimension teleport failed: " + dimension);
                    return BehaviorResult.FAILED;
                }
                progress.logEvent("Teleported to " + dimension + " at " + (int) targetX + ", " + (int) targetY + ", " + (int) targetZ);
                return BehaviorResult.SUCCESS;
            }
        }

        bot.teleport(targetX, targetY, targetZ);
        progress.logEvent("Teleported to " + (int) targetX + ", " + (int) targetY + ", " + (int) targetZ);
        return BehaviorResult.SUCCESS;
    }

    @Override
    public String describeState() {
        return String.format("Teleporting to %.0f, %.0f, %.0f%s", targetX, targetY, targetZ,
                dimension != null ? " (" + dimension + ")" : "");
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
