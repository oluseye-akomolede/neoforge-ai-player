package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

public class FlyToAction implements BotAction {
    private final double targetX, targetY, targetZ;
    private final double arriveDistance;
    private final double speed;
    private int totalTicks = 0;
    private static final int MAX_TICKS = 600;
    private static final double DEFAULT_SPEED = 0.5;

    public FlyToAction(double x, double y, double z, double arriveDistance) {
        this(x, y, z, arriveDistance, DEFAULT_SPEED);
    }

    public FlyToAction(double x, double y, double z, double arriveDistance, double speed) {
        this.targetX = x;
        this.targetY = y;
        this.targetZ = z;
        this.arriveDistance = arriveDistance;
        this.speed = speed;
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

        Vec3 direction = target.subtract(currentPos).normalize();
        double moveSpeed = Math.min(speed, distance);

        player.moveTo(
                currentPos.x + direction.x * moveSpeed,
                currentPos.y + direction.y * moveSpeed,
                currentPos.z + direction.z * moveSpeed
        );

        bot.lookAt(targetX, targetY, targetZ);
        return false;
    }

    @Override
    public String describe() {
        return String.format("FlyTo(%.0f, %.0f, %.0f)", targetX, targetY, targetZ);
    }
}
