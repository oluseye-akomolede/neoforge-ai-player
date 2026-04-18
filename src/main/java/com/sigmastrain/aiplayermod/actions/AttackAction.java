package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.AABB;

import java.util.List;

public class AttackAction implements BotAction {
    private final String targetType;
    private final double searchRadius;
    private int ticksWithoutTarget = 0;

    public AttackAction(String targetType, double searchRadius) {
        this.targetType = targetType.toLowerCase();
        this.searchRadius = searchRadius;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        AABB searchBox = player.getBoundingBox().inflate(searchRadius);
        List<Entity> entities = player.level().getEntities(player, searchBox);

        Entity target = null;
        double closest = Double.MAX_VALUE;
        for (Entity e : entities) {
            if (!(e instanceof LivingEntity le)) continue;
            if (!le.isAlive()) continue;
            String type = e.getType().toShortString().toLowerCase();
            String name = e.getName().getString().toLowerCase();
            if (type.contains(targetType) || name.contains(targetType)) {
                double dist = e.distanceTo(player);
                if (dist < closest) {
                    closest = dist;
                    target = e;
                }
            }
        }

        if (target == null) {
            ticksWithoutTarget++;
            return ticksWithoutTarget > 60; // give up after 3 seconds
        }

        ticksWithoutTarget = 0;
        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());

        if (closest <= 3.5) {
            player.attack(target);
            player.resetAttackStrengthTicker();
        } else {
            // Move toward target
            var dir = target.position().subtract(player.position()).normalize().scale(0.2);
            player.move(net.minecraft.world.entity.MoverType.SELF,
                    new net.minecraft.world.phys.Vec3(dir.x, player.onGround() ? 0 : -0.08, dir.z));
        }
        return false;
    }

    @Override
    public String describe() {
        return "Attack(" + targetType + ")";
    }
}
