package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

public class GoToAction implements BotAction {
    private final double targetX, targetY, targetZ;
    private final double arriveDistance;
    private final boolean sprint;
    private int ticksStuck = 0;
    private Vec3 lastPos = null;
    private int totalTicks = 0;
    private double yVelocity = 0;
    private boolean flying = false;
    private static final int MAX_TICKS = 600;
    private static final double WALK_SPEED = 0.2;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double TELEPORT_THRESHOLD = 64.0;
    private static final double FLY_THRESHOLD = 4.0;

    public GoToAction(double x, double y, double z, double arriveDistance, boolean sprint) {
        this.targetX = x;
        this.targetY = y;
        this.targetZ = z;
        this.arriveDistance = arriveDistance;
        this.sprint = sprint;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 currentPos = player.position();
        Vec3 target = new Vec3(targetX, targetY, targetZ);
        double distance = currentPos.distanceTo(target);

        if (distance <= arriveDistance) {
            return true;
        }

        if (++totalTicks > MAX_TICKS) {
            return true;
        }

        if (distance > TELEPORT_THRESHOLD) {
            Vec3 dir = target.subtract(currentPos).normalize();
            player.moveTo(targetX - dir.x * arriveDistance, targetY, targetZ - dir.z * arriveDistance);
            flying = false;
            yVelocity = 0;
            return false;
        }

        double heightDiff = Math.abs(targetY - currentPos.y);
        if (heightDiff > FLY_THRESHOLD) {
            flying = true;
        }

        if (flying) {
            Vec3 dir = target.subtract(currentPos).normalize();
            double moveSpeed = Math.min(FLY_SPEED, distance - arriveDistance + 0.5);
            if (moveSpeed < 0.1) moveSpeed = 0.1;
            player.moveTo(
                    currentPos.x + dir.x * moveSpeed,
                    currentPos.y + dir.y * moveSpeed,
                    currentPos.z + dir.z * moveSpeed
            );
            yVelocity = 0;
            bot.lookAt(targetX, targetY, targetZ);
            return false;
        }

        Vec3 direction = target.subtract(currentPos).normalize();
        double speed = sprint ? SPRINT_SPEED : WALK_SPEED;

        if (player.onGround()) {
            yVelocity = 0;
            if (shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                flying = true;
                ticksStuck = 0;
                return false;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(net.minecraft.world.entity.MoverType.SELF,
                new Vec3(direction.x * speed, yVelocity, direction.z * speed));

        bot.lookAt(targetX, targetY, targetZ);
        return false;
    }

    public static boolean shouldJump(ServerPlayer player, Vec3 direction) {
        BlockPos feetPos = player.blockPosition();
        BlockPos ahead = feetPos.offset(
                (int) Math.round(direction.x),
                0,
                (int) Math.round(direction.z));
        boolean blockAhead = !player.level().getBlockState(ahead).isAir();
        boolean spaceAbove = player.level().getBlockState(ahead.above()).isAir()
                && player.level().getBlockState(ahead.above(2)).isAir();
        return blockAhead && spaceAbove;
    }

    @Override
    public String describe() {
        return String.format("GoTo(%.0f, %.0f, %.0f%s)", targetX, targetY, targetZ, sprint ? " sprint" : "");
    }
}
