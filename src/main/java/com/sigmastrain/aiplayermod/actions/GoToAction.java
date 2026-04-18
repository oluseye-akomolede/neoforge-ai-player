package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.pathfinder.Path;
import net.minecraft.world.phys.Vec3;

public class GoToAction implements BotAction {
    private final double targetX, targetY, targetZ;
    private final double arriveDistance;
    private int ticksStuck = 0;
    private Vec3 lastPos = null;
    private int totalTicks = 0;
    private static final int MAX_TICKS = 600; // 30 seconds
    private static final double MOVE_SPEED = 0.2;

    public GoToAction(double x, double y, double z, double arriveDistance) {
        this.targetX = x;
        this.targetY = y;
        this.targetZ = z;
        this.arriveDistance = arriveDistance;
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

        // Detect stuck
        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 40) {
                // Try jumping
                if (player.onGround()) {
                    player.jumpFromGround();
                }
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        // Simple movement toward target
        Vec3 direction = target.subtract(currentPos).normalize().scale(MOVE_SPEED);
        player.move(net.minecraft.world.entity.MoverType.SELF,
                new Vec3(direction.x, player.onGround() ? 0 : -0.08, direction.z));

        bot.lookAt(targetX, targetY, targetZ);
        return false;
    }

    @Override
    public String describe() {
        return String.format("GoTo(%.0f, %.0f, %.0f)", targetX, targetY, targetZ);
    }
}
