package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class FollowAction implements BotAction {
    private final String targetName;
    private final double followDistance;
    private final double searchRadius;
    private int ticksWithoutTarget = 0;
    private double yVelocity = 0;
    private static final int GIVE_UP_TICKS = 100;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double TELEPORT_THRESHOLD = 32.0;
    private static final double FLY_THRESHOLD = 4.0;

    public FollowAction(String targetName, double followDistance, double searchRadius) {
        this(targetName, followDistance, searchRadius, false);
    }

    public FollowAction(String targetName, double followDistance, double searchRadius, boolean sprint) {
        this.targetName = targetName.toLowerCase();
        this.followDistance = followDistance;
        this.searchRadius = searchRadius;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Entity target = null;
        double closest = Double.MAX_VALUE;

        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            String name = online.getName().getString().toLowerCase();
            if (name.contains(targetName)) {
                double dist = online.distanceTo(player);
                if (dist < closest) {
                    closest = dist;
                    target = online;
                }
            }
        }

        if (target == null) {
            AABB box = player.getBoundingBox().inflate(searchRadius);
            for (Entity e : player.level().getEntities(player, box)) {
                if (!(e instanceof LivingEntity)) continue;
                String type = e.getType().toShortString().toLowerCase();
                String name = e.getName().getString().toLowerCase();
                if (type.contains(targetName) || name.contains(targetName)) {
                    double dist = e.distanceTo(player);
                    if (dist < closest) {
                        closest = dist;
                        target = e;
                    }
                }
            }
        }

        if (target == null) {
            return ++ticksWithoutTarget > GIVE_UP_TICKS;
        }
        ticksWithoutTarget = 0;

        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());

        if (closest <= followDistance) {
            if (!player.onGround()) {
                yVelocity -= GRAVITY;
                player.move(MoverType.SELF, new Vec3(0, yVelocity, 0));
            } else {
                yVelocity = 0;
            }
            return false;
        }

        double heightDiff = Math.abs(target.getY() - player.getY());

        if (closest > TELEPORT_THRESHOLD) {
            Vec3 tPos = target.position();
            Vec3 dir = player.position().subtract(tPos).normalize();
            player.moveTo(tPos.x + dir.x * followDistance, tPos.y, tPos.z + dir.z * followDistance);
            yVelocity = 0;
            return false;
        }

        if (heightDiff > FLY_THRESHOLD || !player.onGround()) {
            Vec3 dir = target.position().subtract(player.position()).normalize();
            player.moveTo(
                    player.getX() + dir.x * FLY_SPEED,
                    player.getY() + dir.y * FLY_SPEED,
                    player.getZ() + dir.z * FLY_SPEED
            );
            yVelocity = 0;
            return false;
        }

        Vec3 dir = target.position().subtract(player.position()).normalize();
        if (player.onGround()) {
            yVelocity = 0;
            if (GoToAction.shouldJump(player, dir)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        player.move(MoverType.SELF, new Vec3(dir.x * SPRINT_SPEED, yVelocity, dir.z * SPRINT_SPEED));
        return false;
    }

    @Override
    public String describe() {
        return "Follow(" + targetName + ")";
    }
}
