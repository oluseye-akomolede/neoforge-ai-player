package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.Vec3;

public class GotoBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();
    private double targetX, targetY, targetZ;
    private double arriveDistance = 2.0;
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;
    private int totalTicks;

    private static final int MAX_TICKS = 600;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double TELEPORT_THRESHOLD = 64.0;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("moving");
        this.targetX = directive.getX();
        this.targetY = directive.getY();
        this.targetZ = directive.getZ();
        if (directive.getExtra().containsKey("distance")) {
            this.arriveDistance = Double.parseDouble(directive.getExtra().get("distance"));
        }
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        this.totalTicks = 0;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 currentPos = player.position();
        Vec3 target = new Vec3(targetX, targetY, targetZ);
        double distance = currentPos.distanceTo(target);

        if (distance <= arriveDistance) {
            progress.logEvent("Arrived at destination");
            return BehaviorResult.SUCCESS;
        }

        if (++totalTicks > MAX_TICKS) {
            progress.setFailureReason("Timed out after " + MAX_TICKS + " ticks");
            return BehaviorResult.FAILED;
        }

        if (distance > TELEPORT_THRESHOLD) {
            Vec3 dir = target.subtract(currentPos).normalize();
            player.moveTo(targetX - dir.x * arriveDistance, targetY, targetZ - dir.z * arriveDistance);
            return BehaviorResult.RUNNING;
        }

        double heightDiff = Math.abs(targetY - currentPos.y);
        if (heightDiff > 4.0) {
            Vec3 dir = target.subtract(currentPos).normalize();
            double moveSpeed = Math.min(FLY_SPEED, distance);
            player.moveTo(
                    currentPos.x + dir.x * moveSpeed,
                    currentPos.y + dir.y * moveSpeed,
                    currentPos.z + dir.z * moveSpeed
            );
            bot.lookAt(targetX, targetY, targetZ);
            return BehaviorResult.RUNNING;
        }

        Vec3 direction = target.subtract(currentPos).normalize();

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                player.moveTo(
                        currentPos.x + direction.x * 2.0,
                        currentPos.y + 1.0,
                        currentPos.z + direction.z * 2.0
                );
                yVelocity = 0;
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(MoverType.SELF, new Vec3(direction.x * SPRINT_SPEED, yVelocity, direction.z * SPRINT_SPEED));
        bot.lookAt(targetX, targetY, targetZ);
        return BehaviorResult.RUNNING;
    }

    @Override
    public String describeState() {
        return String.format("Moving to %.0f, %.0f, %.0f", targetX, targetY, targetZ);
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {}
}
