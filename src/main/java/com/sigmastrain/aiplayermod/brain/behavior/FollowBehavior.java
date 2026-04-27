package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class FollowBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();
    private String targetName;
    private double followDistance = 3.0;
    private double searchRadius = 64.0;
    private double yVelocity;
    private int searchTicks = 0;

    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double TELEPORT_THRESHOLD = 32.0;
    private static final int CROSS_DIM_SEARCH_DELAY = 40;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("following");
        this.targetName = directive.getTarget();
        if (directive.getExtra().containsKey("distance")) {
            this.followDistance = Double.parseDouble(directive.getExtra().get("distance"));
        }
        this.yVelocity = 0;
        this.searchTicks = 0;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Entity target = findTarget(player);

        if (target == null) {
            searchTicks++;
            if (searchTicks >= CROSS_DIM_SEARCH_DELAY) {
                searchTicks = 0;
                if (tryTeleportToTarget(bot, player)) {
                    return BehaviorResult.RUNNING;
                }
            }
            progress.setPhase("searching");
            return BehaviorResult.RUNNING;
        }
        searchTicks = 0;

        progress.setPhase("following");
        Vec3 currentPos = player.position();
        Vec3 targetPos = target.position();
        double distance = currentPos.distanceTo(targetPos);

        if (distance <= followDistance) {
            bot.lookAt(targetPos.x, targetPos.y + 1.0, targetPos.z);
            return BehaviorResult.RUNNING;
        }

        if (distance > TELEPORT_THRESHOLD) {
            Vec3 dir = targetPos.subtract(currentPos).normalize();
            double tx = targetPos.x - dir.x * followDistance;
            double tz = targetPos.z - dir.z * followDistance;
            player.moveTo(tx, safeY(player, tx, targetPos.y, tz), tz);
            return BehaviorResult.RUNNING;
        }

        Vec3 direction = targetPos.subtract(currentPos).normalize();
        double heightDiff = Math.abs(targetPos.y - currentPos.y);

        if (heightDiff > 4.0) {
            double moveSpeed = Math.min(FLY_SPEED, distance);
            player.moveTo(
                    currentPos.x + direction.x * moveSpeed,
                    currentPos.y + direction.y * moveSpeed,
                    currentPos.z + direction.z * moveSpeed
            );
            bot.lookAt(targetPos.x, targetPos.y + 1.0, targetPos.z);
            return BehaviorResult.RUNNING;
        }

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        player.move(MoverType.SELF, new Vec3(direction.x * SPRINT_SPEED, yVelocity, direction.z * SPRINT_SPEED));
        bot.lookAt(targetPos.x, targetPos.y + 1.0, targetPos.z);
        return BehaviorResult.RUNNING;
    }

    private Entity findTarget(ServerPlayer player) {
        String search = targetName.toLowerCase();

        // Check nearby entities (within searchRadius)
        AABB box = player.getBoundingBox().inflate(searchRadius);
        Entity closest = null;
        double closestDist = Double.MAX_VALUE;
        for (Entity entity : player.level().getEntities(player, box)) {
            String name = entity.getName().getString().toLowerCase();
            String type = entity.getType().toShortString().toLowerCase();
            if (name.contains(search) || type.contains(search)) {
                double dist = entity.distanceToSqr(player);
                if (dist < closestDist) {
                    closestDist = dist;
                    closest = entity;
                }
            }
        }
        if (closest != null) return closest;

        // Check all bots (not in entity lists due to FTB Chunks workaround)
        String currentDim = player.level().dimension().location().toString();
        for (BotPlayer bp : BotManager.getAllBots().values()) {
            ServerPlayer bp_player = bp.getPlayer();
            if (bp_player == player) continue;
            if (!bp_player.level().dimension().location().toString().equals(currentDim)) continue;
            if (bp_player.getName().getString().toLowerCase().contains(search)) {
                double dist = bp_player.distanceToSqr(player);
                if (dist < closestDist) {
                    closestDist = dist;
                    closest = bp_player;
                }
            }
        }
        if (closest != null) return closest;

        // Check all real players on the server in the same dimension (handles far-away players)
        var server = player.getServer();
        if (server != null) {
            for (ServerPlayer online : server.getPlayerList().getPlayers()) {
                if (online == player) continue;
                if (!online.level().dimension().location().toString().equals(currentDim)) continue;
                if (online.getName().getString().toLowerCase().contains(search)) {
                    return online;
                }
            }
        }

        return null;
    }

    private boolean tryTeleportToTarget(BotPlayer bot, ServerPlayer player) {
        var server = player.getServer();
        if (server == null) return false;
        String currentDim = player.level().dimension().location().toString();

        // Check all real players across all dimensions
        for (ServerPlayer online : server.getPlayerList().getPlayers()) {
            if (online == player) continue;
            if (!online.getName().getString().equalsIgnoreCase(targetName)) continue;

            String dim = online.level().dimension().location().toString();
            Vec3 pos = online.position();

            if (dim.equals(currentDim)) {
                // Same dimension but far — teleport directly
                Vec3 dir = pos.subtract(player.position()).normalize();
                double tx = pos.x - dir.x * followDistance;
                double tz = pos.z - dir.z * followDistance;
                player.moveTo(tx, safeY(player, tx, pos.y, tz), tz);
                progress.logEvent("Teleported to far-away " + targetName);
                progress.setPhase("following");
                return true;
            } else {
                // Different dimension — cross-dimension teleport
                var dimKey = ResourceKey.create(Registries.DIMENSION, ResourceLocation.parse(dim));
                AIPlayerMod.LOGGER.info("[{}] Follow target {} found in {}, teleporting",
                        player.getName().getString(), targetName, dim);
                bot.systemChat("Teleporting to " + dim + " to follow " + targetName, "light_purple");
                boolean ok = bot.teleportToDimension(dimKey, pos.x(), pos.y(), pos.z());
                if (ok) {
                    progress.logEvent("Teleported to " + dim);
                    progress.setPhase("following");
                }
                return ok;
            }
        }

        // Check all bots across all dimensions
        for (BotPlayer bp : BotManager.getAllBots().values()) {
            ServerPlayer bp_player = bp.getPlayer();
            if (bp_player == player) continue;
            if (!bp_player.getName().getString().equalsIgnoreCase(targetName)) continue;

            String bpDim = bp_player.level().dimension().location().toString();
            Vec3 pos = bp_player.position();

            if (bpDim.equals(currentDim)) {
                Vec3 dir = pos.subtract(player.position()).normalize();
                double tx = pos.x - dir.x * followDistance;
                double tz = pos.z - dir.z * followDistance;
                player.moveTo(tx, safeY(player, tx, pos.y, tz), tz);
                progress.logEvent("Teleported to far-away " + targetName);
                progress.setPhase("following");
                return true;
            } else {
                var dimKey = ResourceKey.create(Registries.DIMENSION, ResourceLocation.parse(bpDim));
                AIPlayerMod.LOGGER.info("[{}] Follow target {} (bot) found in {}, teleporting",
                        player.getName().getString(), targetName, bpDim);
                bot.systemChat("Teleporting to " + bpDim + " to follow " + targetName, "light_purple");
                boolean ok = bot.teleportToDimension(dimKey, pos.x(), pos.y(), pos.z());
                if (ok) {
                    progress.logEvent("Teleported to " + bpDim);
                    progress.setPhase("following");
                }
                return ok;
            }
        }

        // Check all entities across all dimensions
        for (ServerLevel level : server.getAllLevels()) {
            String dim = level.dimension().location().toString();
            if (dim.equals(currentDim)) continue;
            for (Entity entity : level.getAllEntities()) {
                if (entity.getName().getString().equalsIgnoreCase(targetName)) {
                    var dimKey = ResourceKey.create(Registries.DIMENSION, ResourceLocation.parse(dim));
                    Vec3 pos = entity.position();
                    AIPlayerMod.LOGGER.info("[{}] Follow target {} (entity) found in {}, teleporting",
                            player.getName().getString(), targetName, dim);
                    bot.systemChat("Teleporting to " + dim + " to follow " + targetName, "light_purple");
                    boolean ok = bot.teleportToDimension(dimKey, pos.x(), pos.y(), pos.z());
                    if (ok) {
                        progress.logEvent("Teleported to " + dim);
                        progress.setPhase("following");
                    }
                    return ok;
                }
            }
        }

        return false;
    }

    private static double safeY(ServerPlayer player, double x, double y, double z) {
        var level = player.level();
        BlockPos pos = BlockPos.containing(x, y, z);
        while (y < level.getMaxBuildHeight() - 1
                && !level.getBlockState(pos).isAir()
                && !level.getBlockState(pos).canBeReplaced()) {
            y += 1.0;
            pos = pos.above();
        }
        return y;
    }

    @Override
    public String describeState() {
        return "Following " + targetName;
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {}
}
