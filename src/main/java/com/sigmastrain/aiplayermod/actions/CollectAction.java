package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class CollectAction implements BotAction {
    private final double radius;
    private int totalTicks = 0;
    private static final int MAX_TICKS = 200;

    public CollectAction(double radius) {
        this.radius = radius;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        if (++totalTicks > MAX_TICKS) return true;

        ServerPlayer player = bot.getPlayer();
        AABB box = player.getBoundingBox().inflate(radius);

        ItemEntity closest = null;
        double closestDist = Double.MAX_VALUE;
        for (Entity e : player.level().getEntities(player, box)) {
            if (e instanceof ItemEntity item && item.isAlive()) {
                double dist = e.distanceTo(player);
                if (dist < closestDist) {
                    closestDist = dist;
                    closest = item;
                }
            }
        }

        if (closest == null) return true;

        if (closestDist <= 2.0) {
            closest.playerTouch(player);
            return false;
        }

        Vec3 dir = closest.position().subtract(player.position()).normalize().scale(0.2);
        player.move(MoverType.SELF, new Vec3(dir.x, player.onGround() ? 0 : -0.08, dir.z));
        bot.lookAt(closest.getX(), closest.getY(), closest.getZ());
        return false;
    }

    @Override
    public String describe() {
        return String.format("Collect(radius=%.0f)", radius);
    }
}
