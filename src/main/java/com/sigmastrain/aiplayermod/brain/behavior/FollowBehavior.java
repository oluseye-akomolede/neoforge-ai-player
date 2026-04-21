package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
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

    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double TELEPORT_THRESHOLD = 32.0;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("following");
        this.targetName = directive.getTarget();
        if (directive.getExtra().containsKey("distance")) {
            this.followDistance = Double.parseDouble(directive.getExtra().get("distance"));
        }
        this.yVelocity = 0;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Entity target = findTarget(player);

        if (target == null) {
            progress.setPhase("searching");
            return BehaviorResult.RUNNING;
        }

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
            player.moveTo(
                    targetPos.x - dir.x * followDistance,
                    targetPos.y,
                    targetPos.z - dir.z * followDistance
            );
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
        return closest;
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
